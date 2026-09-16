import requests, os, json, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

KILLZONES = {
    "LONDON": (7, 10, "10am-1pm Kisumu"),
    "NY_AM": (12, 15, "3pm-6pm Kisumu")
}
DIST_MAX, MIN_SCORE, COOLDOWN_MIN = 12.0, 7, 90
LAST_FILE = "last_signal.json"

def can_send(qml):
    if not os.path.exists(LAST_FILE): return True
    try:
        d=json.load(open(LAST_FILE))
        mins=(datetime.now(timezone.utc)-datetime.fromisoformat(d['time'])).total_seconds()/60
        if abs(float(d['qml'])-float(qml))<1.0 and mins<COOLDOWN_MIN: return False
        return True
    except: return True

def save_last(q):
    json.dump({"qml":float(q),"time":datetime.now(timezone.utc).isoformat()}, open(LAST_FILE,"w"))

def is_kz():
    h=datetime.now(timezone.utc).hour
    for n,(s,e,l) in KILLZONES.items():
        if s<=h<e: return True,n,l
    return False,"OUTSIDE",""

def send_telegram(text, chart=None):
    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id":CHAT_ID, "text":text, "parse_mode":"HTML"})
    if chart and os.path.exists(chart):
        with open(chart,'rb') as f:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", data={"chat_id":CHAT_ID}, files={"photo":f})

def get_live_price():
    # GOLD-API for REAL XAU broker price
    try:
        r=requests.get("https://api.gold-api.com/price/XAU", timeout=8).json()
        return float(r['price'])
    except:
        return None

def get_candles():
    # BINANCE PAXG for REAL QML STRUCTURE (200 x 1H candles free)
    url="https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=1h&limit=200"
    r=requests.get(url, timeout=10).json()
    return [{"high":float(x[2]), "low":float(x[3]), "close":float(x[4]), "open":float(x[1])} for x in r]

def scan_real_qmls(candles, live_price):
    qmls=[]
    for i in range(30, len(candles)-2):
        # BULLISH V-QML (Support = BUY)
        if candles[i]['low'] < candles[i-20]['low'] and candles[i]['close'] > candles[i-20]['low']:
            price=candles[i-20]['low']
            dist=abs(live_price-price)
            if dist<25:
                score=10 if dist<12 else 6
                if candles[-1]['close']>candles[-1]['open']: score+=1
                qmls.append({"price":price, "dist":dist, "score":min(score,12), "side":"BUY", "crt":"BUY"})
        # BEARISH V-QML (Resistance = SELL)
        if candles[i]['high'] > candles[i-20]['high'] and candles[i]['close'] < candles[i-20]['high']:
            price=candles[i-20]['high']
            dist=abs(live_price-price)
            if dist<25:
                score=10 if dist<12 else 6
                if candles[-1]['close']<candles[-1]['open']: score+=1
                qmls.append({"price":price, "dist":dist, "score":min(score,12), "side":"SELL", "crt":"SELL"})
    qmls=sorted(qmls, key=lambda x: x['dist'])
    uniq=[]
    for q in qmls:
        if not any(abs(q['price']-u['price'])<2 for u in uniq):
            uniq.append(q)
    return uniq[:4]

def main():
    ok, kz_name, kz_label = is_kz()
    candles=get_candles()
    live_gold=get_live_price()
    live=live_gold if live_gold else candles[-1]['close'] # fallback to Binance if gold-api down

    if not ok:
        print(f"OUTSIDE KZ live gold-api {live} sleeping - no Telegram")
        return

    qmls=scan_real_qmls(candles, live)
    print(f"HYBRID SCAN: gold-api live {live} | Binance structure found: {qmls}")

    if not qmls:
        print("No QML near live price")
        return

    best=qmls[0]
    if best['dist']>DIST_MAX or best['score']<MIN_SCORE:
        print(f"Best {best['side']} {best['price']} Dist {best['dist']:.2f} - waiting")
        return
    if not can_send(best['price']):
        print("Cooldown active")
        return

    qml, side = best['price'], best['side']
    if side=="BUY":
        entry_l, entry_h, sl = qml-0.6, qml+0.6, qml-3.0
        tp1, tp2, tp3 = qml+4.5, qml+8.4, qml+13.5
        emoji="🔥 BUY"
    else:
        entry_l, entry_h, sl = qml-0.6, qml+0.6, qml+3.0
        tp1, tp2, tp3 = qml-4.5, qml-8.4, qml-13.5
        emoji="🔻 SELL"

    text=f"""{emoji} ALCHEMIST REAL XAU {side} [{kz_name} A-GRADE {best['score']}/12]
{kz_label} | {side}_V_QML @ {qml:.2f} | Dist {best['dist']:.2f}$
💰 Live Gold-API: {live:.2f} | Binance Structure: {candles[-1]['close']:.2f}
📍 Entry: {entry_l:.2f} - {entry_h:.2f}
🛑 SL: {sl:.2f} ($3.00)
🎯 TP1: {tp1:.2f} | TP2: {tp2:.2f} | TP3: {tp3:.2f}
CRT:{best['crt']} | V6.7 HYBRID BUY/SELL | 0.01 lot
Kisumu {datetime.now().strftime('%H:%M')}"""

    plt.figure(figsize=(8,4), facecolor='black')
    plt.plot([c['close'] for c in candles[-60:]], color='white')
    plt.axhline(qml, color='yellow', ls='--')
    plt.axhline(sl, color='red', alpha=0.6)
    plt.savefig("chart.png", facecolor='black')
    plt.close()

    save_last(qml)
    send_telegram(text, "chart.png")

if __name__=="__main__":
    main()
