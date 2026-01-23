import os
import uuid
import time
import requests
import threading
import re
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

active_tasks = {}
logs = ["> System ready."]
site_public_url = ""
keep_alive_running = False
keep_alive_thread = None

API_URL = "https://app.zefame.com/api_free.php?action=config"
ORDER_URL = "https://app.zefame.com/api_free.php?action=order"
CHECK_VIDEO_URL = "https://app.zefame.com/api_free.php?action=checkVideoId"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://app.zefame.com",
    "Referer": "https://app.zefame.com/"
}

TRANS_MAP = {
    "Vues": "Views", "Abonnés": "Followers", "Partages": "Shares",
    "Favoris": "Favorites", "J'aime": "Likes", "Membres": "Members",
    "Vidéos": "Videos", "Gratuits": "", "Free": "", "Chaîne": "Channel"
}

def clean_and_translate(text):
    for fr, en in TRANS_MAP.items():
        text = text.replace(fr, en)
    return " ".join(text.split()).strip()

def get_timer_display(timer_sec):
    try:
        t = int(timer_sec)
        if t <= 0: return "Ready"
        if t >= 3600: return f"{t // 3600}h {(t % 3600) // 60}m"
        return f"{t // 60}m"
    except: return "N/A"

def smart_keep_alive():
    global keep_alive_running, site_public_url
    ping_url = site_public_url.rstrip('/') + "/get_logs"
    while keep_alive_running:
        if any(task.get('running', False) for task in active_tasks.values()):
            try: requests.get(ping_url, timeout=15)
            except: pass
        else: break
        time.sleep(300)
    keep_alive_running = False

def start_keep_alive():
    global keep_alive_running, keep_alive_thread
    if not keep_alive_running:
        keep_alive_running = True
        keep_alive_thread = threading.Thread(target=smart_keep_alive, daemon=True)
        keep_alive_thread.start()
        logs.append("> [SYSTEM] Keep-alive activated")

def extract_video_id(url):
    tiktok_id = re.search(r'/video/(\d+)', url)
    if tiktok_id: return tiktok_id.group(1)
    digits = re.findall(r'\d{10,}', url)
    return digits[0] if digits else None

def run_automation(service_id, service_name, video_link, target):
    task_id = str(service_id)
    if task_id in active_tasks and active_tasks[task_id].get('running'): return
    
    active_tasks[task_id] = {'running': True}
    logs.append(f"> [STARTING] {service_name}")
    start_keep_alive()

    session = requests.Session()
    video_id = ""
    try:
        res = session.post(CHECK_VIDEO_URL, data={"link": video_link}, headers=headers, timeout=15)
        video_id = res.json().get("data", {}).get("videoId", "")
    except: pass

    if not video_id: video_id = extract_video_id(video_link)

    if not video_id:
        logs.append("> [ERROR] Video ID fetch failed!")
        active_tasks.pop(task_id, None)
        return

    # ভিডিও আইডি শো করা
    logs.append(f"> [VIDEO ID] {video_id}")
    
    target_num = int(target) if target and target.isdigit() else 999999
    order_count = 0

    while active_tasks.get(task_id, {}).get('running') and order_count < target_num:
        try:
            payload = {"service": service_id, "link": video_link, "uuid": str(uuid.uuid4()), "videoId": video_id}
            res = session.post(ORDER_URL, data=payload, headers=headers, timeout=30)
            order = res.json()
            
            if order.get("success"):
                order_count += 1
                logs.append(f"> SUCCESS ({order_count}/{target_num}) {service_name}")
            else:
                msg = order.get("message", "Service Busy")
                logs.append(f"> WAIT: {msg}")
            
            # ওয়েটিং টাইম বা কোoldown শো করা
            next_av = order.get("data", {}).get("nextAvailable")
            wait_time = max(int(next_av) - int(time.time()), 20) if next_av else 60
            
            logs.append(f"> WAITING: {wait_time}s for next order")
            
            for _ in range(wait_time):
                if not active_tasks.get(task_id, {}).get('running'): break
                time.sleep(1)
        except: 
            logs.append("> [ERROR] Retrying in 30s...")
            time.sleep(30)
            
    active_tasks.pop(task_id, None)

@app.route('/')
def index():
    global site_public_url
    if not site_public_url:
        site_public_url = request.host_url.rstrip('/')
        logs.append(f"> Domain Sync: {site_public_url}")

    processed = []
    try:
        api_res = requests.get(API_URL, headers=headers, timeout=15)
        api_data = api_res.json().get('data', {})
        for platform in ['tiktok', 'instagram', 'facebook', 'youtube']:
            if platform in api_data:
                processed.append({"id": "", "name": f"--- {platform.upper()} ---", "clickable": False})
                for s in api_data[platform].get('services', []):
                    name = clean_and_translate(s.get('name', ''))
                    if platform == 'tiktok' and (not name or name.lower() == "service"):
                        name = "Views"
                    elif not name:
                        name = "Service"
                    timer = get_timer_display(s.get('timerSeconds', 0))
                    processed.append({
                        "id": s.get('id'),
                        "name": f"   {platform.capitalize()} {name} [Qty: {s.get('quantity', '?')}] ({timer})",
                        "clickable": True
                    })
    except:
        processed = [{"id": "229", "name": "   Tiktok Views [Qty: 100] (5m)", "clickable": True}]
    return render_template('index.html', services=processed)

@app.route('/start', methods=['POST'])
def start_bot():
    threading.Thread(target=run_automation, args=(
        request.form.get('service_id'), request.form.get('service_name'),
        request.form.get('video_link'), request.form.get('target')
    ), daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/get_logs')
def get_logs():
    return jsonify({"logs": logs[-20:], "running_count": len(active_tasks)})

@app.route('/stop_all', methods=['POST'])
def stop_all():
    global keep_alive_running
    for tid in list(active_tasks.keys()): active_tasks[tid]['running'] = False
    active_tasks.clear()
    keep_alive_running = False
    return jsonify({"status": "stopped"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10307)))
