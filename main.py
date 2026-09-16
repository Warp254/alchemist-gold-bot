import requests, os, json, traceback
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

KILLZONES = {"LONDON": (7,10,"10am-1pm Kisumu"), "NY_AM": (12,15,"3pm-6pm Kisumu")}
DIST_MAX, MIN_SCORE, COOLDOWN_MIN = 12.0, 7, 90
LAST_FILE = "last_signal.json"

def can_send(q):
    if not os.path.exists(LAST_FILE): return True
    try:
        d=json.load(open(LAST_FILE))
        mins=(datetime.now(timezone.utc)-datetime.fromisoformat(d['time'])).total_seconds()/60
        return not (abs(float(d['qml'])-float(q))<1.0 and mins<COOLDOWN_MIN)
    except: return True

def save_last(q):
    json.dump({"qml":float(q),"time":datetime.now(timezone.utc).isoformat()}, open(LAST_FILE,"w"))

def is_kz():
    h=datetime.now(timezone.utc).hour
    for n,(s,e,l) in KILLZONES.items():
        if s<=h<e: return True,n,l
    return False,"OUTSIDE",""

def send_telegram(text):
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id":CHAT_ID, "text":text}, timeout=10)
    except Exception as e:
        print(f"Telegram error {e}")

def get_live_price():
    try:
        r=requests.get("https://api.gold-api.com/price/XAU", timeout=10, headers={"User-Agent":"Mozilla/5.0"}).json()
        return float(r['price'])
    except Exception as e:
        print(f"Gold-API fail {e}")
        return None

def get_candles():
    try:
        url="https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=1h&limit=200"
        r=requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"}).json()
        return [{"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"open":float(x[1])} for x in r]
    except Exception as e:
        print(f"Binance fail {e}")
        traceback.print_exc()
        return []

def scan_qmls(candles, live):
    qmls=[]
    if len(candles)<50: return []
    for i in range(30, len(candles)-2):
        if candles[i]['low'] < candles[i-20]['low'] and candles[i]['close'] > candles[i-20]['low']:
            price=candles[i-20]['low']
            dist=abs(live-price)
            if dist<25:
                qmls.append({"price":price,"dist":dist,"score":10 if dist<12 else 6,"side":"BUY"})
        if candles[i]['high'] > candles[i-20]['high'] and candles[i]['close'] < candles[i-20]['high']:
            price=candles[i-20]['high']
            dist=abs(live-price)
            if dist<25:
                qmls.append({"price":price,"dist":dist,"score":10 if dist<12 else 6,"side":"SELL"})
    qmls=sorted(qmls, key=lambda x: x['dist'])
    uniq=[]
    for q in qmls:
        if not any(abs(q['price']-u['price'])<2 for u in uniq):
            uniq.append(q)
    return uniq[:4]

def main():
    try:
        ok,kz_name,kz_label=is_kz()
        candles=get_candles()
        if not candles:
            print("No candles - Binance blocked, abort")
            return
        live_gold=get_live_price()
        live=live_gold if live_gold else candles[-1]['close']

        if not ok:
            print(f"OUTSIDE KZ live {live} sleeping - no Telegram (correct for now)")
            return

        qmls=scan_qmls(candles, live)
        print(f"HYBRID OK live gold-api {live} found {qmls}")
        if not qmls:
            print("No QML near")
            return

        best=qmls[0]
        if best['dist']>DIST_MAX or best['score']<MIN_SCORE:
            print(f"Best {best}")
            return
        if not can_send(best['price']):
            print("Cooldown")
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
Live: {live:.2f}
Entry: {entry_l:.2f}-{entry_h:.2f} SL: {sl:.2f} TP1 {tp1:.2f} TP2 {tp2:.2f} TP3 {tp3:.2f}
V6.7.1 HYBRID BUY/SELL | Kisumu {datetime.now().strftime('%H:%M')}"""
        save_last(qml)
        send_telegram(text)
        print("Sent Telegram OK")
    except Exception as e:
        print(f"CRASH {e}")
        traceback.print_exc()

if __name__=="__main__":
    main()
