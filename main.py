import os, json, urllib.request, sys, shlex
from datetime import datetime, timezone
import matplotlib.pyplot as plt
import numpy as np

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def tg_send(text, photo=None):
    try:
        if not TOKEN or not CHAT_ID:
            print("NO SECRETS")
            return
        if photo:
            cmd = f"curl -s -X POST https://api.telegram.org/bot{TOKEN}/sendPhoto -F chat_id={CHAT_ID} -F photo=@{photo} -F caption={shlex.quote(text[:1000])}"
        else:
            cmd = f"curl -s -X POST https://api.telegram.org/bot{TOKEN}/sendMessage -d chat_id={CHAT_ID} -d text={shlex.quote(text[:3800])}"
        os.system(cmd)
    except Exception as e:
        print(f"TG fail {e}")

def get_gold():
    # 7 DAYS for more QML history
    url = "https://api.coingecko.com/api/v3/coins/pax-gold/market_chart?vs_currency=usd&days=7"
    raw = json.loads(urllib.request.urlopen(url, timeout=20).read())
    prices = [p[1] for p in raw['prices']]
    # take every 2nd point for more detail
    closes = prices[::2][-400:]
    return np.array(closes), float(closes[-1])

KILLZONES = {"LONDON":(7,10,"10am-1pm Kisumu"),"NY_AM":(12,15,"3pm-6pm Kisumu"),"NY_PM":(18,20,"9pm-11pm Kisumu"),"ASIA":(0,6,"3am-9am Kisumu")}
now_utc = datetime.now(timezone.utc)
hour_utc = now_utc.hour
active_kz = None; kz_label=None
for name,(s,e,label) in KILLZONES.items():
    if s <= hour_utc < e:
        active_kz=name; kz_label=label
if not active_kz:
    # TEST MODE: run even outside KZ as ASIA
    active_kz="ASIA"; kz_label="Outside KZ - TEST MODE"

try:
    closes, live = get_gold()
except Exception as e:
    tg_send(f"⚠️ Gold API fail {e} [{active_kz}] Kisumu {datetime.now().strftime('%H:%M')}")
    sys.exit(0)

highs = closes + 1.0; lows = closes - 1.0
levels=[]
# MORE AGGRESSIVE QML FINDER - less strict
for i in range(20,len(closes)-2):
    # Support V-QML - any clear low
    if lows[i] < lows[i-1] and lows[i] <= lows[i+1] and lows[i] < lows[i-2] and lows[i] < lows[i+2]:
        levels.append({"type":"SUPPORT_V_QML","price":float(lows[i]),"strength":float(lows[i-1]-lows[i]),"idx":i})
    # Resistance A-QML
    if highs[i] > highs[i-1] and highs[i] >= highs[i+1] and highs[i] > highs[i-2] and highs[i] > highs[i+2]:
        levels.append({"type":"RESISTANCE_A_QML","price":float(highs[i]),"strength":float(highs[i]-highs[i-1]),"idx":i})

# sort by closest to live price + strength (TEST MODE)
levels = sorted(levels, key=lambda x: (abs(x['price']-live), -x['strength']))[:10]
if not levels:
    tg_send(f"🔍 [{active_kz} {kz_label}] Live {live:.2f}\nReally ranging - no structure at all\nKisumu {datetime.now().strftime('%H:%M')}")
    sys.exit(0)

nearest = levels[0]
dist = abs(live-nearest['price'])
direction = "BUY" if "SUPPORT" in nearest['type'] else "SELL"
crt_high = np.max(highs[-6:-1]); crt_low = np.min(lows[-6:-1]); mid=(crt_high+crt_low)/2
crt = "BUY" if closes[-1] > mid else "SELL"

# chart
fig, ax = plt.subplots(figsize=(10,6), facecolor='#0e0e0e'); ax.set_facecolor('#0e0e0e')
ax.plot(closes[-120:], color='white', lw=1.2)
for lv in levels[:5]:
    col = '#00ff88' if 'SUPPORT' in lv['type'] else '#ff4444'
    ax.axhline(lv['price'], color=col, ls=':', alpha=0.7, lw=1)
ax.axhline(live, color='yellow', lw=1.5, label=f'LIVE {live:.2f}')
plt.title(f'ALCHEMIST V6.5 TEST {active_kz} {live:.2f} | {nearest["type"]} {nearest["price"]:.2f} | Dist {dist:.2f}$', color='white', fontsize=9, fontweight='bold')
plt.savefig('/tmp/chart.png', dpi=200, facecolor='#0e0e0e', bbox_inches='tight'); plt.close()

# TEST MODE - ALWAYS SEND A-GRADE even if far (up to 15$)
if dist > 15.0:
    tg_send(f"🔍 [{active_kz} {kz_label}] Live {live:.2f}\nNearest {nearest['type']} {nearest['price']:.2f} Dist {dist:.2f}$ >15$ waiting\nKisumu {datetime.now().strftime('%H:%M')}", photo="/tmp/chart.png")
    sys.exit(0)

atr = np.mean(highs[-14:]-lows[-14:]); sl_dist = max(1.2, min(4.0, atr*0.7))
entry = nearest['price']; sl = entry - sl_dist if direction=="BUY" else entry + sl_dist
tps = [entry + sl_dist*rr if direction=="BUY" else entry - sl_dist*rr for rr in [1.5,2.5,4.0]]

caption = f"🪙 ALCHEMIST XAU {direction} [{active_kz} TEST A-GRADE] 🔥\n{kz_label} | {nearest['type']} @ {entry:.2f} | Dist {dist:.2f}$\n\n💰 Live: {live:.2f}\n📍 Entry: {entry-0.4:.2f} - {entry+0.4:.2f}\n🛑 SL: {sl:.2f} (${sl_dist:.2f})\n🎯 TP1: {tps[0]:.2f} (50%) | TP2: {tps[1]:.2f} (30%) | TP3: {tps[2]:.2f} (20%)\nCRT:{crt} | TEST MODE 6/12 threshold\nKisumu {datetime.now().strftime('%H:%M')}"

tg_send(caption, photo="/tmp/chart.png")
print(f"SENT {direction} {entry}")
