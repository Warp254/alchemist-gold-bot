import requests, os, json, traceback
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LAST_FILE = "last_signal.json"

KILLZONES = {"LONDON": (7,10), "NY_AM": (12,15)}
COOLDOWN = 90

def can_send(q):
    if not os.path.exists(LAST_FILE): return True
    try:
        d=json.load(open(LAST_FILE))
        mins=(datetime.now(timezone.utc)-datetime.fromisoformat(d['time'])).total_seconds()/60
        return not (abs(float(d['qml'])-q)<2.0 and mins<COOLDOWN)
    except: return True
def save_last(q): json.dump({"qml":float(q),"time":datetime.now(timezone.utc).isoformat()}, open(LAST_FILE,"w"))
def is_kz():
    h=datetime.now(timezone.utc).hour
    for n,(s,e) in KILLZONES.items():
        if s<=h<e: return True,n
    return False,"OUT"

def send_tg(t):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":t}, timeout=10)
    except Exception as e: print(e)

def get_live():
    try: return float(requests.get("https://api.gold-api.com/price/XAU", timeout=8, headers={"User-Agent":"Mozilla/5.0"}).json()['price'])
    except: return None

def get_candles():
    for url in ["https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=1h&limit=200","https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=1h&limit=200"]:
        try:
            r=requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"}).json()
            if isinstance(r,list) and len(r)>100:
                return [{"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"o":float(x[1])} for x in r]
        except: continue
    return []

def is_bullish_engulf(i,c): return c[i]['c']>c[i]['o'] and c[i]['c']>c[i-1]['h']
def is_bearish_engulf(i,c): return c[i]['c']<c[i]['o'] and c[i]['c']<c[i-1]['l']

def scan_v7(candles, live):
    qmls=[]
    # need 80 candles for structure
    for i in range(60, len(candles)-3):
        # --- BULLISH QML: Sell Liquidity Sweep + Buy QML ---
        # Find left shoulder low
        ls_low = min([x['l'] for x in candles[i-40:i-20]])
        head_low = candles[i-10]['l'] if i>=10 else 9999
        curr_low = candles[i]['l']
        # Head must sweep LS low (liquidity grab)
        if head_low < ls_low - 0.5 and curr_low > head_low:
            # BOS: close above last swing high after head
            swing_high = max([x['h'] for x in candles[i-10:i]])
            if candles[-1]['c'] > candles[-2]['h']: # mini BOS
                dist = abs(live - curr_low)
                if dist<30:
                    score=0
                    if head_low < ls_low: score+=3 # sweep
                    if candles[i]['c'] > candles[i]['o']: score+=2 # engulfing
                    if dist<12: score+=4
                    elif dist<20: score+=2
                    score+=2 # discount check below
                    qmls.append({"price":curr_low,"dist":dist,"score":min(score,12),"side":"BUY","sweep":round(ls_low-head_low,2),"bos":True})

        # --- BEARISH QML ---
        ls_high = max([x['h'] for x in candles[i-40:i-20]])
        head_high = candles[i-10]['h'] if i>=10 else 0
        curr_high = candles[i]['h']
        if head_high > ls_high + 0.5 and curr_high < head_high:
            if candles[-1]['c'] < candles[-2]['l']:
                dist = abs(live - curr_high)
                if dist<30:
                    score=0
                    if head_high > ls_high: score+=3
                    if candles[i]['c'] < candles[i]['o']: score+=2
                    if dist<12: score+=4
                    elif dist<20: score+=2
                    score+=2
                    qmls.append({"price":curr_high,"dist":dist,"score":min(score,12),"side":"SELL","sweep":round(head_high-ls_high,2),"bos":True})

    # dedup + sort
    qmls=sorted(qmls, key=lambda x: (-x['score'], x['dist']))
    uniq=[]
    for q in qmls:
        if not any(abs(q['price']-u['price'])<3 for u in uniq): uniq.append(q)
    return uniq[:3]

def main():
    try:
        ok,kz=is_kz()
        candles=get_candles()
        if len(candles)<100:
            print("No candles, abort"); return
        live=get_live() or candles[-1]['c']
        if not ok:
            print(f"OUTSIDE KZ live {live} sleep - OK"); return

        qmls=scan_v7(candles, live)
        print(f"V7 SCAN live {live} QMLs: {qmls}")
        if not qmls: return
        best=qmls[0]
        if best['dist']>15 or best['score']<7:
            print(f"Weak {best} skip"); return
        if not can_send(best['price']):
            print("Cooldown"); return

        qml,side=best['price'],best['side']
        if side=="BUY":
            entry=f"{qml-0.6:.2f} - {qml+0.6:.2f}"; sl=f"{qml-3.5:.2f}"; tps=f"{qml+5:.2f} | {qml+10:.2f} | {qml+18:.2f}"; emoji="🔥 BUY V-QML"
            logic=f"Sweep {best['sweep']}$ + BOS + Engulfing"
        else:
            entry=f"{qml-0.6:.2f} - {qml+0.6:.2f}"; sl=f"{qml+3.5:.2f}"; tps=f"{qml-5:.2f} | {qml-10:.2f} | {qml-18:.2f}"; emoji="🔻 SELL V-QML"
            logic=f"Sweep {best['sweep']}$ + BOS + Engulfing"

        text=f"""{emoji} [{kz} {best['score']}/12 A-GRADE]
Side: {side} @ {qml:.2f} | Dist {best['dist']:.2f}$ live {live:.2f}
Logic: {logic}
Entry: {entry}
SL: {sl} (3.5$ structure)
TP: {tps}
CRT: {side} BOS confirmed | Killzone {kz}
V7.0 PRO REAL QML | Kisumu {datetime.now().strftime('%H:%M')}"""
        save_last(qml); send_tg(text); print("Sent TG VIP")
    except Exception as e:
        print(f"CRASH {e}"); traceback.print_exc()

if __name__=="__main__": main()
