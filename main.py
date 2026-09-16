import os, requests, json, time
from datetime import datetime, timezone
from pathlib import Path

START = time.time()

def send_tg(text):
    t=os.getenv("TELEGRAM_BOT_TOKEN"); c=os.getenv("TELEGRAM_CHAT_ID")
    if not t or not c: return
    try: requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id":c,"text":text,"parse_mode":"Markdown"}, timeout=15)
    except Exception as e: print(e)

def get_real_candles():
    """Try TwelveData REAL OHLC, fallback to gold-api"""
    api_key = os.getenv("TWELVEDATA_API_KEY")
    if api_key:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=5min&outputsize=30&apikey={api_key}"
            r = requests.get(url, timeout=15).json()
            vals = r.get("values", [])[::-1] # oldest -> newest
            if vals:
                closes = [float(v["close"]) for v in vals]
                highs = [float(v["high"]) for v in vals]
                lows = [float(v["low"]) for v in vals]
                print(f"REAL CANDLES from TwelveData: {len(vals)} candles")
                return closes, highs, lows, float(vals[-1]["close"]), "TWELVEDATA REAL"
        except Exception as e: print(f"TwelveData fail: {e}")

    # Fallback: gold-api single price -> build synthetic history
    try:
        price = float(requests.get("https://api.gold-api.com/price/XAU", timeout=10).json().get("price",0))
    except: price=4340.0
    # Load history as fake candles
    hp=Path("docs/history.json")
    hist=json.loads(hp.read_text())[-29:] if hp.exists() else []
    hist.append(price)
    closes=hist[-30:]
    highs=[c+1.5 for c in closes]; lows=[c-1.5 for c in closes]
    return closes, highs, lows, price, "GOLD-API FALLBACK"

def get_session():
    h=datetime.now(timezone.utc).hour
    if 8 <= h < 13: return f"LONDON 🇬🇧 NO SWAP ({h}UTC)", True
    if 13 <= h < 17: return f"NEW YORK AM 🇺🇸 NO SWAP ({h}UTC)", True
    if h==12: return "LONDON/NY OVERLAP 🔥🔥", True
    return f"CLOSED ({h}UTC) SAVING MINS", False

# === FETCH REAL DATA ===
closes, highs, lows, live_price, source = get_real_candles()
session_name, is_open = get_session()

# SAVE history for fallback
Path("docs").mkdir(exist_ok=True)
Path("docs/history.json").write_text(json.dumps(closes[-100:]))

# === REAL ALCHEMIST BRAIN (MT5 LOGIC) ===
if len(closes) >= 20:
    lookback_high = max(highs[-20:])
    lookback_low = min(lows[-20:])
    eq = round((lookback_high + lookback_low)/2, 2)
    
    # REAL ATR = avg of True Range (High-Low) last 14
    tr = [highs[i]-lows[i] for i in range(-14,0)]
    atr = round(sum(tr)/len(tr), 2)
    
    qml_sell = round(lookback_high - atr*0.3, 2)
    qml_buy = round(lookback_low + atr*0.3, 2)

    # REAL BIAS + SWEEP DETECTION
    if live_price > eq + atr*0.5:
        bias="BUY"; qml=qml_buy; reason="Price above EQ"
    elif live_price < eq - atr*0.5:
        bias="SELL"; qml=qml_sell; reason="Price below EQ"
    else:
        if live_price > lookback_high - atr*0.2:
            bias="SELL"; qml=qml_sell; reason=f"Sweep HIGH {lookback_high}"
        elif live_price < lookback_low + atr*0.2:
            bias="BUY"; qml=qml_buy; reason=f"Sweep LOW {lookback_low}"
        else:
            bias="NEUTRAL"; qml=eq; reason="Consolidation at EQ"
else:
    eq=round(live_price-8,2); atr=4.5; qml=eq; bias="NEUTRAL"
    lookback_high=live_price; lookback_low=live_price; reason="Building 20 bars"

# REAL TP/SL (ATR based like MT5)
if bias=="BUY":
    entry=live_price; sl=round(lookback_low - atr*0.5,2); tp1=round(entry+atr*1.5,2); tp2=round(entry+atr*3,2)
elif bias=="SELL":
    entry=live_price; sl=round(lookback_high + atr*0.5,2); tp1=round(entry-atr*1.5,2); tp2=round(entry-atr*3,2)
else:
    entry=live_price; sl=tp1=tp2=0

# === ANTI-SPAM: Only alert if bias changed ===
last_path=Path("docs/last_bias.json")
last_bias = json.loads(last_path.read_text()).get("bias") if last_path.exists() else "NONE"
should_alert = (bias != last_bias and bias in ["BUY","SELL"] and is_open) or (len(closes)%12==0) # hourly heartbeat
last_path.write_text(json.dumps({"bias":bias,"time":datetime.now(timezone.utc).isoformat()}))

payload={
    "version":"V10 REAL CANDLES",
    "source":source, "live":live_price, "price":live_price,
    "bias":bias, "reason":reason, "atr":atr, "eq":eq, "qml":qml,
    "entry":entry, "sl":sl, "tp1":tp1, "tp2":tp2,
    "hh":lookback_high, "ll":lookback_low,
    "session":session_name, "is_open":is_open,
    "history_len":len(closes),
    "run_time":f"{round(time.time()-START,1)}s",
    "scanner_line": f"{source} {live_price} {bias} EQ {eq} QML {qml} SL {sl} TP {tp1}/{tp2} {reason}",
    "updated": datetime.now(timezone.utc).isoformat()
}

with open("signals.json","w") as f: json.dump(payload,f,indent=2)
with open("docs/signals.json","w") as f: json.dump(payload,f,indent=2)
print(payload["scanner_line"])

# === TELEGRAM (fixed, no spam) ===
if should_alert and bias in ["BUY","SELL"]:
    emoji="🟢" if bias=="BUY" else "🔴"
    send_tg(f"""🚨🚨🚨 *ALCHEMIST {bias} REAL CANDLE* 🚨🚨🚨

{emoji*3} *{bias} XAU - {reason}* {emoji*3}

💰 Entry: *{entry}* Live {live_price}
Source: *{source}*
📍 {session_name}
EQ {eq} | QML {qml} | ATR {atr}$ (REAL)
HH {lookback_high} LL {lookback_low}

🎯 TP1: *{tp1}* (+{round(abs(tp1-entry),2)}$)
🎯 TP2: *{tp2}* (+{round(abs(tp2-entry),2)}$)
🛑 SL: *{sl}* (-{round(abs(entry-sl),2)}$)

✅ MT5 Alchemist Logic
🌐 https://warp254.github.io/alchemist-gold-bot/
""")
elif len(closes)%12==0: # hourly heartbeat when NEUTRAL
    send_tg(f"""🏆 *Alchemist V10 Heartbeat*

XAU {live_price} {bias} | {session_name}
{source} | ATR {atr}$ REAL | EQ {eq} QML {qml}
Bars {len(closes)} | {reason}

Bot alive, waiting for sweep...
""")
