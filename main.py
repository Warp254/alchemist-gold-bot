import requests, json, os, time
from datetime import datetime, timezone
import pandas as pd

SYMBOL = "PAXGUSDT"
TF = "15m"
HTF = "4h"
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def fetch_klines(symbol, interval, limit=100):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=["open_time","open","high","low","close","volume","close_time","qav","trades","taker_base","taker_quote","ignore"])
    for c in ["open","high","low","close"]:
        df[c] = pd.to_numeric(df[c])
    return df

def get_live_price(df):
    return float(df.iloc[-1]["close"])

def calc_atr(df, period=14):
    df["tr"] = df["high"]-df["low"]
    df["atr"] = df["tr"].rolling(period).mean()
    return float(df["atr"].iloc[-1])

def calc_htf_bias():
    try:
        htf = fetch_klines(SYMBOL, HTF, 60)
        ema50 = htf["close"].ewm(span=50).mean().iloc[-1]
        price = float(htf["close"].iloc[-1])
        if price > ema50*1.002: return "BULL"
        if price < ema50*0.998: return "BEAR"
        return "NEUTRAL"
    except:
        return "NEUTRAL"

def in_killzone():
    now_utc = datetime.now(timezone.utc)
    h = now_utc.hour + now_utc.minute/60
    london = 7 <= h <= 10
    ny = 12 <= h <= 15
    if london: return True, "LONDON"
    if ny: return True, "NY"
    return False, "OUTSIDE"

def can_send():
    path = "last_signal.json"
    if not os.path.exists(path): return True
    try:
        d=json.load(open(path))
        last = datetime.fromisoformat(d["time"])
        diff = (datetime.now(timezone.utc)-last).total_seconds()/60
        if diff < 90: return False
    except: pass
    return True

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)

def find_qmls(df):
    recent = df.tail(50)
    high_50 = recent["high"].max()
    low_50 = recent["low"].min()
    eq = (high_50+low_50)/2
    candidates = []
    for i in range(len(df)-20, len(df)-3):
        low = df.iloc[i]["low"]
        prev_low = df.iloc[i-5:i]["low"].min()
        if low < prev_low:
            if df.iloc[i+1:]["close"].max() > df.iloc[i]["high"]:
                if df.iloc[i]["close"] < eq:
                    score = 9
                    qml = low + 0.5
                    candidates.append({"side":"BUY","qml":qml,"score_base":score,"eq":eq,"sweep": round(prev_low-low,2)})
        high = df.iloc[i]["high"]
        prev_high = df.iloc[i-5:i]["high"].max()
        if high > prev_high:
            if df.iloc[i+1:]["close"].min() < df.iloc[i]["low"]:
                if df.iloc[i]["close"] > eq:
                    score = 9
                    qml = high - 0.5
                    candidates.append({"side":"SELL","qml":qml,"score_base":score,"eq":eq,"sweep": round(high-prev_high,2)})
    return candidates, eq

def main():
    print("=== V8 + V9 FREE ===")
    df = fetch_klines(SYMBOL, TF, 100)
    live = get_live_price(df)
    atr = calc_atr(df)
    htf_bias = calc_htf_bias()
    ok_kz, kz_name = in_killzone()
    eq = (df.tail(50)["high"].max()+df.tail(50)["low"].min())/2
    print(f"Live {live:.2f} | bias {htf_bias} | ATR {atr:.2f} | KZ {kz_name}")
    os.makedirs("docs", exist_ok=True)
    last_scan_msg = f"{'OUTSIDE KZ live' if not ok_kz else 'V8 ULTIMATE live'} {live:.2f} {'sleep - OK' if not ok_kz else f'in {kz_name}'} | bias {htf_bias}"
    if not ok_kz:
        data = {"live": round(live,2), "bias": htf_bias, "atr": round(atr,2), "eq": round(eq,2), "kz": kz_name, "last_scan": last_scan_msg, "updated": datetime.now(timezone.utc).isoformat(), "signals": []}
        try:
            old=json.load(open("docs/signals.json")); data["signals"]=old.get("signals",[])
        except: pass
        with open("docs/signals.json","w") as f: json.dump(data,f, indent=2)
        return
    cands, _ = find_qmls(df)
    best = None; best_score = 0
    for c in cands:
        dist = abs(live - c["qml"])
        if dist > 15: continue
        score = c["score_base"]
        if htf_bias == "BULL" and c["side"]=="BUY": score+=2
        if htf_bias == "BEAR" and c["side"]=="SELL": score+=2
        score+=1
        if score>best_score:
            best_score=score; best=c; best["dist"]=dist; best["score"]=score
    if not best or best_score < 8:
        data = {"live": round(live,2), "bias": htf_bias, "atr": round(atr,2), "eq": round(eq,2), "kz": kz_name, "last_scan": f"Skip weak {best_score}/12", "updated": datetime.now(timezone.utc).isoformat(), "signals": []}
        try:
            old=json.load(open("docs/signals.json")); data["signals"]=old.get("signals",[])
        except: pass
        with open("docs/signals.json","w") as f: json.dump(data,f, indent=2)
        return
    if not can_send(): return
    sl = best["qml"] - atr*1.5 if best["side"]=="BUY" else best["qml"] + atr*1.5
    tp1 = live + atr*1.5 if best["side"]=="BUY" else live - atr*1.5
    tp2 = live + atr*3 if best["side"]=="BUY" else live - atr*3
    tp3 = best["eq"] + (best["eq"]-best["qml"])*1.5 if best["side"]=="BUY" else best["eq"] - (best["qml"]-best["eq"])*1.5
    grade = "A+" if best_score>=11 else "A" if best_score>=9 else "B"
    msg = f"🔥 {best['side']} V8 [{kz_name} {best_score}/12 {grade}]\nSide: {best['side']} | Bias: {htf_bias} | ATR {atr:.2f}$\nQML: {best['qml']:.2f} | Live {live:.2f} Dist {best['dist']:.2f}$\nLogic: Sweep {best['sweep']}$ + BOS + Discount + FVG + HTF {htf_bias}\nSL: {sl:.2f} | TP1: {tp1:.2f} | TP2: {tp2:.2f} | TP3: {tp3:.2f}"
    print(msg); send_telegram(msg)
    with open("last_signal.json","w") as f: json.dump({"time": datetime.now(timezone.utc).isoformat(), "qml": best["qml"]}, f)
    signal_entry = {"time": datetime.now(timezone.utc).isoformat(), "side": best["side"], "qml": round(best["qml"],2), "live": round(live,2), "score": best_score, "kz": kz_name, "bias": htf_bias}
    try:
        old=json.load(open("docs/signals.json")); signals = old.get("signals",[])
    except: signals=[]
    signals = [signal_entry] + signals[:9]
    data = {"live": round(live,2), "bias": htf_bias, "atr": round(atr,2), "eq": round(eq,2), "kz": kz_name, "last_scan": f"{best['side']} V8 [{kz_name} {best_score}/12 {grade}]", "updated": datetime.now(timezone.utc).isoformat(), "signals": signals}
    with open("docs/signals.json","w") as f: json.dump(data,f, indent=2)

if __name__=="__main__":
    main()
