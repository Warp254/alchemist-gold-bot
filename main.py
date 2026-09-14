import os, json, urllib.request, sys, shlex, math
from datetime import datetime, timezone
import matplotlib.pyplot as plt
import numpy as np

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
if not TOKEN or not CHAT_ID: print("Missing secrets"); sys.exit(1)

# --- CONFIG - YOUR MT5 RULES ---
SYMBOL = "XAUUSD"
ATR_STOP_MULT = 0.8
RR_TARGETS = [1.5, 2.5, 4.0]
KILLZONES = {"london": (7,10), "ny_am": (12,15), "ny_pm": (18,20)} # UTC

# 1. GET REAL 15M GOLD CANDLES (PAXG = XAU)
url = "https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=15m&limit=200"
data = json.loads(urllib.request.urlopen(url, timeout=15).read())
# [open time, open, high, low, close, volume...]
closes = np.array([float(c[4]) for c in data])
highs = np.array([float(c[2]) for c in data])
lows = np.array([float(c[3]) for c in data])
live = closes[-1]
now_utc = datetime.now(timezone.utc)
hour_utc = now_utc.hour

# 2. KILLZONE CHECK (Alchemist rule: No KZ = No Trade)
kz_now = None
for name,(s,e) in KILLZONES.items():
    if s <= hour_utc < e: kz_now = name
# Allow outside KZ but score lower - we still want signal

# 3. DETECT FRESH MSNR QML LEVELS (Your logic)
def detect_msnr():
    levels=[]
    for i in range(50, len(closes)-3):
        # V Support
        if lows[i-1] > lows[i] < lows[i+1] and lows[i] == np.min(lows[i-2:i+3]):
            if np.min(lows[i+1:]) >= lows[i]: # fresh unmitigated
                strength = abs(lows[i-1]-lows[i])
                levels.append({"type":"SUPPORT_V_QML","price":float(lows[i]),"idx":i,"fresh":True,"strength":strength})
        # A Resistance
        if highs[i-1] < highs[i] > highs[i+1] and highs[i] == np.max(highs[i-2:i+3]):
            if np.max(highs[i+1:]) <= highs[i]:
                strength = abs(highs[i]-highs[i-1])
                levels.append({"type":"RESISTANCE_A_QML","price":float(highs[i]),"idx":i,"fresh":True,"strength":strength})
    levels = sorted(levels, key=lambda x: x['strength'], reverse=True)[:5]
    return levels

levels = detect_msnr()
if not levels:
    print("No fresh QML levels")
    sys.exit(0)

# nearest level to price
nearest = min(levels, key=lambda x: abs(x['price']-live))
if abs(nearest['price']-live) > 3.5: # Gold must be within $3.5
    caption = f"🔍 ALCHEMIST SCAN - NO TRADE\nLive {live:.2f} | Nearest {nearest['type']} {nearest['price']:.2f}\nDistance {abs(live-nearest['price']):.2f}$ > 3.5$ - Waiting\nKZ: {kz_now or 'OUTSIDE'} | {now_utc.strftime('%H:%M UTC')}"
    os.system(f"curl -s -X POST https://api.telegram.org/bot{TOKEN}/sendMessage -d chat_id={CHAT_ID} -d text={shlex.quote(caption)} > /dev/null")
    sys.exit(0)

direction = "BUY" if "SUPPORT" in nearest['type'] else "SELL"

# 4. CRT ENTRY (sweep + close beyond 50%)
def crt_check():
    crt_high = highs[-4]
    crt_low = lows[-4]
    mid = (crt_high + crt_low)/2
    curr_close = closes[-1]
    curr_low = lows[-1]
    curr_high = highs[-1]
    if curr_low < crt_low and curr_close > mid: return "BUY"
    if curr_high > crt_high and curr_close < mid: return "SELL"
    return None

crt = crt_check()
if crt!= direction:
    print(f"CRT mismatch: need {direction} got {crt}"); sys.exit(0)

# 5. INDUCEMENT (small range before sweep)
recent_range = np.max(highs[-30:]) - np.min(lows[-30:])
last5_range = np.max(highs[-5:]) - np.min(lows[-5:])
inducement = last5_range < recent_range * 0.35

# 6. SCORE (your 12 point system)
score = 0
if kz_now in ["london","ny_am"]: score+=4
elif kz_now: score+=2
if inducement: score+=3
if nearest['fresh']: score+=3
if abs(live-nearest['price']) < 1.5: score+=2

if score < 8:
    print(f"Score {score}/12 <8 - B grade, skip")
    sys.exit(0)

# 7. REAL SL/TP (tight for Gold)
atr = np.mean(highs[-14:]-lows[-14:])
sl_dist = atr * ATR_STOP_MULT
sl_dist = max(1.0, min(3.5, sl_dist))

entry = nearest['price']
if direction=="BUY":
    sl = entry - sl_dist
    tps = [entry + sl_dist*rr for rr in RR_TARGETS]
else:
    sl = entry + sl_dist
    tps = [entry - sl_dist*rr for rr in RR_TARGETS]

# 8. CHART WITH QML LEVELS
fig, ax = plt.subplots(figsize=(10,6), facecolor='#0e0e0e')
ax.set_facecolor('#0e0e0e')
ax.plot(closes[-80:], color='white', lw=1.2)
for lv in levels:
    color = '#00ff88' if 'SUPPORT' in lv['type'] else '#ff4444'
    ax.axhline(lv['price'], color=color, ls=':', alpha=0.6, lw=0.8)
ax.axhline(entry, color='yellow', lw=1.5, label=f"QML {entry:.2f}")
ax.axhline(sl, color='red', ls='--', label=f"SL {sl:.2f}")
ax.axhline(tps[0], color='#00ff88', ls='--', label=f"TP1 {tps[0]:.2f}")
ax.axhline(tps[2], color='#00ff88', ls='--', alpha=0.5, label=f"TP3 {tps[2]:.2f}")
plt.title(f'ALCHEMIST XAU {direction} {live:.2f} | {nearest["type"]} | SCORE {score}/12 | KZ {kz_now} | CONF {78+score}%', color='white', fontsize=9, fontweight='bold')
plt.legend(facecolor='#0e0e0e', edgecolor='white', labelcolor='white', fontsize=7)
plt.savefig('/tmp/chart.png', dpi=200, facecolor='#0e0e0e', bbox_inches='tight')
plt.close()

kisumu = datetime.now().strftime('%H:%M')
caption = f"""🪙 ALCHEMIST XAU {direction} [V6 REAL QML] • {kz_now or 'OUTSIDE KZ'} 🔥
{nearest['type']} @ {entry:.2f} | Score {score}/12 A-GRADE
CRT Sweep + IDM: {'YES' if inducement else 'WEAK'}

💰 Live: {live:.2f}
⚡️ Action: {direction} NOW
📍 Entry: {entry-0.3:.2f} - {entry+0.3:.2f} (QML)
🛑 SL: {sl:.2f} (${sl_dist:.2f})
🎯 TP1: {tps[0]:.2f} (50% 1.5RR) | TP2: {tps[1]:.2f} (30% 2.5RR) | TP3: {tps[2]:.2f} (20% 4RR)
📊 ATR: {atr:.2f} | Valid 90m
Kisumu {kisumu}"""

os.system(f"curl -s -X POST https://api.telegram.org/bot{TOKEN}/sendPhoto -F chat_id={CHAT_ID} -F photo=@/tmp/chart.png -F caption={shlex.quote(caption)} > /tmp/out.txt && cat /tmp/out.txt")
print(f"ALCHEMIST REAL {direction} Score {score} {live}")
