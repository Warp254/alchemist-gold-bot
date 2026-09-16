import requests, os, json, traceback
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LAST_FILE = "last_signal.json"
COOLDOWN = 90

def can_send(q):
    if not os.path.exists(LAST_FILE): return True
    try:
        d=json.load(open(LAST_FILE))
        mins=(datetime.now(timezone.utc)-datetime.fromisoformat(d['time'])).total_seconds()/60
        return not (abs(float(d['qml'])-q)<2 and mins<COOLDOWN)
    except: return True
def save_last(q): json.dump({"qml":float(q),"time":datetime.now(timezone.utc).isoformat()}, open(LAST_FILE,"w"))

def is_kz():
    h=datetime.now(timezone.utc).hour
    if 7 <= h < 10: return True,"LONDON"
    if 12 <= h < 15: return True,"NY_AM"
    return False,"OUT"

def send_tg(t):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":t}, timeout=10)
    except: pass

def get_live():
    try: return float(requests.get("https://api.gold-api.com/price/XAU", timeout=8, headers={"User-Agent":"Mozilla/5.0"}).json()['price'])
    except: return None

def get_candles(interval="1h", limit=200):
    urls=[f"https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval={interval}&limit={limit}",
          f"https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval={interval}&limit={limit}"]
    for url in urls:
        try:
            r=requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"}).json()
            if isinstance(r,list) and len(r)>50:
                return [{"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"o":float(x[1])} for x in r]
        except: continue
    return []

def calc_atr(candles, period=14):
    trs=[]
    for i in range(1,len(candles)):
        tr=max(candles[i]['h']-candles[i]['l'], abs(candles[i]['h']-candles[i-1]['c']), abs(candles[i]['l']-candles[i-1]['c']))
        trs.append(tr)
    return sum(trs[-period:])/period if trs else 2.5

def htf_bias(candles_4h):
    # Simple: 50EMA bias + BOS
    if len(candles_4h)<50: return "NEUTRAL"
    ema50=sum([x['c'] for x in candles_4h[-50:]])/50
    if candles_4h[-1]['c']>ema50 and candles_4h[-1]['h']>candles_4h[-2]['h']: return "BULL"
    if candles_4h[-1]['c']<ema50 and candles_4h[-1]['l']<candles_4h[-2]['l']: return "BEAR"
    return "NEUTRAL"

def is_discount(price, candles):
    lo=min([x['l'] for x in candles[-50:]]); hi=max([x['h'] for x in candles[-50:]])
    mid=(lo+hi)/2
    return price<mid, lo, hi, mid

def find_fvg(candles):
    # Bull FVG: candle1 low > candle3 high
    fvgs=[]
    for i in range(2,len(candles)):
        if candles[i-2]['h'] < candles[i]['l']: fvgs.append({"type":"BULL","low":candles[i-2]['h'],"high":candles[i]['l']})
        if candles[i-2]['l'] > candles[i]['h']: fvgs.append({"type":"BEAR","low":candles[i]['h'],"high":candles[i-2]['l']})
    return fvgs[-5:]

def scan_v8(c1, c4, live):
    atr=calc_atr(c1)
    bias=htf_bias(c4)
    fvgs=find_fvg(c1)
    is_disc, lo, hi, mid = is_discount(live, c1)
    qmls=[]
    for i in range(60, len(c1)-3):
        # BULL QML
        ls_low=min([x['l'] for x in c1[i-40:i-20]])
        head=c1[i-10]['l']; curr=c1[i]['l']
        if head < ls_low - 0.6 and curr > head:
            dist=abs(live-curr)
            if dist<25:
                score=0
                details=[]
                if head < ls_low: score+=3; details.append(f"Sweep {round(ls_low-head,2)}$")
                if c1[i]['c']>c1[i]['o']: score+=1; details.append("Engulf")
                if c1[-1]['c']>c1[-2]['h']: score+=2; details.append("BOS")
                if is_disc: score+=2; details.append("Discount")
                if any(f['type']=="BULL" and abs(f['low']-curr)<3 for f in fvgs): score+=2; details.append("FVG")
                if bias=="BULL": score+=2; details.append(f"HTF {bias}")
                if dist<10: score+=2
                elif dist<15: score+=1
                qmls.append({"price":curr,"dist":dist,"score":min(score,12),"side":"BUY","atr":atr,"bias":bias,"details":details,"lo":lo,"hi":hi,"mid":mid})

        # BEAR QML
        ls_high=max([x['h'] for x in c1[i-40:i-20]])
        head_h=c1[i-10]['h']; curr_h=c1[i]['h']
        if head_h > ls_high + 0.6 and curr_h < head_h:
            dist=abs(live-curr_h)
            if dist<25:
                score=0; details=[]
                if head_h>ls_high: score+=3; details.append(f"Sweep {round(head_h-ls_high,2)}$")
                if c1[i]['c']<c1[i]['o']: score+=1; details.append("Engulf")
                if c1[-1]['c']<c1[-2]['l']: score+=2; details.append("BOS")
                if not is_disc: score+=2; details.append("Premium")
                if any(f['type']=="BEAR" and abs(f['high']-curr_h)<3 for f in fvgs): score+=2; details.append("FVG")
                if bias=="BEAR": score+=2; details.append(f"HTF {bias}")
                if dist<10: score+=2
                elif dist<15: score+=1
                qmls.append({"price":curr_h,"dist":dist,"score":min(score,12),"side":"SELL","atr":atr,"bias":bias,"details":details,"lo":lo,"hi":hi,"mid":mid})
    qmls=sorted(qmls, key=lambda x: (-x['score'], x['dist']))
    uniq=[]
    for q in qmls:
        if not any(abs(q['price']-u['price'])<3 for u in uniq): uniq.append(q)
    return uniq[:3]

def main():
    try:
        ok,kz=is_kz()
        c1=get_candles("1h",200); c4=get_candles("4h",100)
        if len(c1)<80: print("No 1h candles"); return
        live=get_live() or c1[-1]['c']
        if not ok:
            print(f"OUTSIDE KZ live {live:.2f} sleep - OK | bias {htf_bias(c4)}")
            return
        qmls=scan_v8(c1,c4,live)
        print(f"V8 ULTIMATE live {live:.2f} bias {htf_bias(c4)} QMLs: {qmls}")
        if not qmls: return
        best=qmls[0]
        if best['dist']>15 or best['score']<8:
            print(f"Skip weak {best['score']}/12 dist {best['dist']}"); return
        if not can_send(best['price']): print("Cooldown"); return

        atr=best['atr']; qml=best['price']; side=best['side']
        if side=="BUY":
            sl=qml-atr*1.5; tp1=qml+atr*1.2; tp2=qml+atr*2.5; tp3=best['hi']
            emoji="🔥 BUY V8"
        else:
            sl=qml+atr*1.5; tp1=qml-atr*1.2; tp2=qml-atr*2.5; tp3=best['lo']
            emoji="🔻 SELL V8"

        text=f"""{emoji} [{kz} {best['score']}/12 A+]
Side: {side} | HTF Bias: {best['bias']} | ATR {atr:.2f}$
QML: {qml:.2f} | Live {live:.2f} Dist {best['dist']:.2f}$
Logic: {' + '.join(best['details'])}
Entry: {qml-0.5:.2f}-{qml+0.5:.2f}
SL: {sl:.2f} (1.5xATR structure)
TP1: {tp1:.2f} (1.2xATR) | TP2: {tp2:.2f} | TP3 Liquidity: {tp3:.2f}
50% EQ: {best['mid']:.2f} | Range {best['lo']:.2f}-{best['hi']:.2f}
V8.0 ULTIMATE CRT | {datetime.now().strftime('%H:%M')} Kisumu"""
        save_last(qml); send_tg(text); print("Sent V8")
    except Exception as e:
        print(f"CRASH {e}"); traceback.print_exc()

if __name__=="__main__": main()
