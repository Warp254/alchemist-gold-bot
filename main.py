import os, json, urllib.request, sys, shlex
from datetime import datetime, timezone
import matplotlib.pyplot as plt
import numpy as np

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def tg_send(text, photo=None):
    try:
        if photo:
            cmd = f"curl -s -X POST https://api.telegram.org/bot{TOKEN}/sendPhoto -F chat_id={CHAT_ID} -F photo=@{photo} -F caption={shlex.quote(text)}"
        else:
            cmd = f"curl -s -X POST https://api.telegram.org/bot{TOKEN}/sendMessage -d chat_id={CHAT_ID} -d text={shlex.quote(text)}"
        os.system(cmd + " > /tmp/out.txt; cat /tmp/out.txt")
        print(f"TG sent")
    except Exception as e:
        print(f"TG fail {e}")

def get_gold():
    url = "https://api.coingecko.com/api/v3/coins/pax-gold/market_chart?vs_currency=usd&days=3"
    raw = json.loads(urllib.request.urlopen(url, timeout=15).read())
    prices = [p[1] for p in raw['prices']]
    closes = prices[::3][-200:]
    return np.array(closes), float(closes[-1])

closes, live = get_gold()
highs = closes + 0.6
lows = closes - 0.6
hour_utc = datetime.now(timezone.utc).hour

# QML detect
levels=[]
for i in range(50, len(closes)-3):
    if lows[i-1] > lows[i] < lows[i+1] and lows[i]==np.min(lows[i-2:i+3]):
        if np.min(lows[i+1:]) >= lows[i]:
            levels.append({"type":"SUPPORT_V_QML","price":float(lows[i]),"strength":abs(lows[i-1]-lows[i])})
    if highs[i-1] < highs[i] > highs[i+1] and highs[i]==np.max(highs[i-2:i+3]):
        if np.max(highs[i+1:]) <= highs[i]:
            levels.append({"type":"RESISTANCE_A_QML","price":float(highs[i]),"strength":abs(highs[i]-highs[i-1])})

levels = sorted(levels, key=lambda x: x['strength'], reverse=True)[:5]
if not levels:
    tg_send(f"🔍 ALCHEMIST SCAN\nLive {live:.2f}\nNo fresh QML levels - market ranging\nKisumu {datetime.now().strftime('%H:%M')}")
    sys.exit(0)

nearest = min(levels, key=lambda x: abs(x['price']-live))
dist = abs(live-nearest['price'])
direction = "BUY" if "SUPPORT" in nearest['type'] else "SELL"

# CRT
crt_high = highs[-4]; crt_low = lows[-4]; mid=(crt_high+crt_low)/2
crt = "BUY" if lows[-1] < crt_low and closes[-1] > mid else "SELL" if highs[-1] > crt_high and closes[-1] < mid else None

recent_range = np.max(highs[-30:]) - np.min(lows[-30:])
last5_range = np.max(highs[-5:]) - np.min(lows[-5:])
inducement = last5_range < recent_range*0.35

score=0
if 7 <= hour_utc < 15: score+=4
if inducement: score+=3
if abs(dist)<1.5: score+=2
if nearest: score+=3

# --- ALWAYS BUILD CHART ---
fig, ax = plt.subplots(figsize=(10,6), facecolor='#0e0e0e')
ax.set_facecolor('#0e0e0e')
ax.plot(closes[-80:], color='white', lw=1.2)
for lv in levels:
    col = '#00ff88' if 'SUPPORT' in lv['type'] else '#ff4444'
    ax.axhline(lv['price'], color=col, ls=':', alpha=0.6)
ax.axhline(live, color='yellow', lw=1.5, label=f"Live {live:.2f}")
plt.title(f'ALCHEMIST SCAN {live:.2f} | {nearest["type"]} | Score {score}/12', color='white', fontsize=9)
plt.legend(facecolor='#0e0e0e', edgecolor='white', labelcolor='white', fontsize=7)
plt.savefig('/tmp/chart.png', dpi=200, facecolor='#0e0e0e', bbox_inches='tight')
plt.close()

# --- DECISION ---
if dist > 4.0:
    tg_send(f"🔍 ALCHEMIST SCAN [REAL]\nLive {live:.2f} | Nearest {nearest['type']} {nearest['price']:.2f}\nDist {dist:.2f}$ - Waiting for price to tap QML\nCRT: {crt} | IDM: {inducement} | Score {score}/12\nKisumu {datetime.now().strftime('%H:%M')} - Next scan 1h", photo="/tmp/chart.png")
    sys.exit(0)

if crt!= direction:
    tg_send(f"🔍 ALCHEMIST SCAN [REAL]\nLive {live:.2f} | QML {nearest['type']} {nearest['price']:.2f}\nCRT mismatch: need {direction} got {crt} - Waiting for sweep\nScore {score}/12 | Kisumu {datetime.now().strftime('%H:%M')}", photo="/tmp/chart.png")
    sys.exit(0)

if score < 8:
    tg_send(f"🔍 ALCHEMIST SCAN [REAL]\nLive {live:.2f} | {nearest['type']} {nearest['price']:.2f}\nScore {score}/12 B-GRADE - Need 8/12 A-GRADE\nCRT: {crt} IDM: {inducement} Dist: {dist:.2f}$\nWaiting for better confluence\nKisumu {datetime.now().strftime('%H:%M')}", photo="/tmp/chart.png")
    sys.exit(0)

# A-GRADE ENTRY
atr = np.mean(highs[-14:]-lows[-14:])
sl_dist = max(1.0, min(3.5, atr*0.8))
entry = nearest['price']
sl = entry - sl_dist if direction=="BUY" else entry + sl_dist
tps = [entry + sl_dist*rr if direction=="BUY" else entry - sl_dist*rr for rr in [1.5,2.5,4.0]]

caption = f"""🪙 ALCHEMIST XAU {direction} [V6.2 REAL] 🔥
{nearest['type']} @ {entry:.2f} | Score {score}/12 A-GRADE

💰 Live: {live:.2f}
📍 Entry: {entry-0.3:.2f} - {entry+0.3:.2f}
🛑 SL: {sl:.2f} (${sl_dist:.2f})
🎯 TP1: {tps[0]:.2f} (50%) | TP2: {tps[1]:.2f} (30%) | TP3: {tps[2]:.2f} (20%)
CRT: {crt} | IDM: {'YES' if inducement else 'NO'}
Kisumu {datetime.now().strftime('%H:%M')}"""

tg_send(caption, photo="/tmp/chart.png")
