import requests, os, json, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ONLY 2 KZ = 6h = 5min = 1,512 min FREE — NO NY_PM, so no 22:46
KILLZONES = {
    "LONDON": (7, 10, "10am-1pm Kisumu"),
    "NY_AM": (12, 15, "3pm-6pm Kisumu")
}

DIST_MAX = 12.0
MIN_SCORE = 7
CAP_MAX = 18.0
LOT = 0.01
SUPPORT_V_QML = 4297.98
COOLDOWN_MIN = 90
LAST_FILE = "last_signal.json"

def can_send(new_qml):
    if not os.path.exists(LAST_FILE):
        return True
    try:
        data = json.load(open(LAST_FILE))
        last_time = datetime.fromisoformat(data['time'])
        mins = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
        if abs(float(data['qml']) - float(new_qml)) < 1.0 and mins < COOLDOWN_MIN:
            return False
        return True
    except:
        return True

def save_last(qml):
    json.dump({"qml": float(qml), "time": datetime.now(timezone.utc).isoformat()}, open(LAST_FILE, "w"))

def is_killzone():
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    for name, (start, end, label) in KILLZONES.items():
        if start <= hour < end:
            return True, name, label
    return False, "OUTSIDE", ""

def send_telegram(text, chart_path=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    if chart_path and os.path.exists(chart_path):
        url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(chart_path, 'rb') as f:
            requests.post(url_photo, data={"chat_id": CHAT_ID}, files={"photo": f})

def get_live_price():
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
        return float(r['price'])
    except:
        return 4308.10

def calculate_score(dist):
    return 10 if dist <= DIST_MAX else 7

def main():
    is_kz, kz_name, kz_label = is_killzone()
    live = get_live_price()
    dist = abs(live - SUPPORT_V_QML)

    if not is_kz:
        print(f"OUTSIDE KZ {live} - sleeping, no Telegram")
        return  # <-- NO TELEGRAM OUTSIDE, so no 22:19 / 22:46 spam

    score = calculate_score(dist)

    if dist > DIST_MAX or score < MIN_SCORE:
        print(f"Waiting {dist:.2f}$")
        return

    if not can_send(SUPPORT_V_QML):
        print(f"Cooldown active for {SUPPORT_V_QML}")
        return

    entry_low = SUPPORT_V_QML - 0.6
    entry_high = SUPPORT_V_QML + 0.6
    sl = SUPPORT_V_QML - 3.0
    tp1, tp2, tp3 = 4302.48, 4306.38, 4311.48

    text = f"""🔥 ALCHEMIST XAU BUY [{kz_name}_SWING A-GRADE {score}/12] 🔥
{kz_label} |
SUPPORT_V_QML @ {SUPPORT_V_QML} | Dist {dist:.2f}$

💰 Live: {live}
📍 Entry: {entry_low} - {entry_high}
🛑 SL: {sl} ($3.00)
🎯 TP1: {tp1} (1.5R) | TP2: {tp2} (2.8R) | TP3: {tp3} (4.5R)
CRT:BUY | V6.5 D1 SWING DIST12 SCORE7 CAPPED 18$ | {LOT} lot ~$3.00
Kisumu {datetime.now().strftime('%H:%M')}"""

    plt.figure(figsize=(8,4))
    plt.plot([4290, 4310, 4295, 4300, live], color='white')
    plt.axhline(SUPPORT_V_QML, color='yellow', linestyle='--')
    plt.axhline(sl, color='red')
    plt.savefig("chart.png", facecolor='black')
    plt.close()

    save_last(SUPPORT_V_QML)
    send_telegram(text, "chart.png")

if __name__ == "__main__":
    main()
