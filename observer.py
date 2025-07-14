import os
import time
import json
import logging
from flask import Flask, request, jsonify, make_response
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import threading
from datetime import datetime, timedelta
from algorithm import write

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("observer.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN_FILE = 'fcm_tokens.json'
SERVICE_ACCOUNT_FILE = '.kappa-dav-firebase-adminsdk.json'
SCOPES = ['https://www.googleapis.com/auth/firebase.messaging']
PROJECT_ID = 'kappa-dav'
WATCH_DIR = '/home/mykhailo/.var/lib/radicale/collections/collection-root'
KNOWN_FILES_FILE = 'known_files.json'
DELIVERY_CACHE_FILE = 'delivery_cache.json'


def load_json(file):
    if os.path.exists(file):
        try:
            with open(file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            log.warning(f"Не вдалося прочитати JSON з {file}")
    return {}


def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)


def send_fcm_message(token, data):
    log.info(f"Надсилається FCM-повідомлення до токену: {token} з даними: {data}")
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        creds.refresh(Request())

        headers = {
            'Authorization': f'Bearer {creds.token}',
            'Content-Type': 'application/json; UTF-8',
        }
        url = f'https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send'
        message = {"message": {"token": token, "data": data}}

        resp = requests.post(url, headers=headers, json=message)
        log.info(f"Відповідь FCM: {resp.status_code} {resp.text}")
    except Exception as e:
        log.error(f"Помилка надсилання FCM: {e}")


def scan_calendar_files():
    result = {}
    for user in os.listdir(WATCH_DIR):
        user_path = os.path.join(WATCH_DIR, user)
        if not os.path.isdir(user_path):
            continue
        for cal in os.listdir(user_path):
            cal_path = os.path.join(user_path, cal)
            if not os.path.isdir(cal_path):
                continue
            files = [f for f in os.listdir(cal_path) if f.endswith('.ics')]
            if files:
                result.setdefault(user, {})[cal] = files
    return result


def remove_outdated_files(known_files):
    now = datetime.now()
    cutoff = now - timedelta(days=1)
    to_remove = {}

    for user, cals in known_files.items():
        for cal, files in cals.items():
            cal_path = os.path.join(WATCH_DIR, user, cal)
            for f in files:
                try:
                    dt = datetime.strptime(f.replace('.ics', ''), "%Y%m%dT%H%M%S")
                    if dt < cutoff:
                        full_path = os.path.join(cal_path, f)
                        os.remove(full_path)
                        to_remove.setdefault(user, {}).setdefault(cal, []).append(f)
                        log.info(f"[AUTO-REMOVE] Видалено застарілий файл: {full_path}")
                except Exception as e:
                    log.warning(f"Не вдалося обробити дату файлу {f}: {e}")

    return to_remove


@app.route('/extKGP', methods=['POST', 'OPTIONS'])
def ext_kgp():
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    data = request.get_json()
    word = data.get("text", "").strip()
    calName = data.get("calName", "default")
    write(word, calName, 3, 1.288)

    response = make_response(f"Слово «{word}» додано до календаря «{calName}»", 200)
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


@app.route('/ping')
def ping():
    return "pong", 200


@app.route('/confirm_delivery', methods=['POST'])
def confirm_delivery():
    data = request.get_json(force=True)
    msg_type = data.get("type")
    files = data.get("files", [])

    if msg_type and files:
        delivered_key = f"{msg_type}:{json.dumps(files, sort_keys=True)}"
        cache = load_json(DELIVERY_CACHE_FILE)
        cache[delivered_key] = True
        save_json(DELIVERY_CACHE_FILE, cache)
        log.info(f"[CONFIRM] Отримано підтвердження: {delivered_key}")
        return jsonify({"status": "confirmed"}), 200
    return jsonify({"error": "Invalid confirmation"}), 400


@app.route('/register_token', methods=['POST'])
def register_token():
    data = request.get_json(force=True)
    token, cal_id = data.get('fcm_token'), data.get('calendar_id')
    if not token or not cal_id:
        return jsonify({'error': 'Missing fcm_token or calendar_id'}), 400

    tokens = load_json(TOKEN_FILE)
    tokens = {t: c for t, c in tokens.items() if not (c == cal_id and t != token)}
    tokens[token] = cal_id

    save_json(TOKEN_FILE, tokens)
    log.info(f"Зареєстровано токен: {token} для календаря: {cal_id}")
    return jsonify({'status': 'Token and calendar_id saved'})


def watch_and_notify():
    log.info("[Watcher] Старт відстеження змін")
    known_files = load_json(KNOWN_FILES_FILE)

    while True:
        outdated_removed = remove_outdated_files(known_files)
        current_files = scan_calendar_files()
        toCreate = {}
        toRemove = outdated_removed

        for user, cals in current_files.items():
            for cal, files in cals.items():
                known_set = set(known_files.get(user, {}).get(cal, []))
                current_set = set(files)
                new_files = current_set - known_set
                if new_files:
                    toCreate.setdefault(user, {}).setdefault(cal, []).extend(new_files)

        tokens_map = load_json(TOKEN_FILE)
        delivery_cache = load_json(DELIVERY_CACHE_FILE)

        for action, changes in [('toCreate', toCreate), ('toRemove', toRemove)]:
            for user, cals in changes.items():
                for cal, files in cals.items():
                    calendar_id = f"{user}/{cal}"
                    tokens_for_cal = [t for t, cid in tokens_map.items() if cid == calendar_id]
                    if not tokens_for_cal:
                        continue

                    file_paths = [os.path.join(user, cal, f) for f in files]
                    data_payload = {"type": action, "files": json.dumps(file_paths)}

                    for token in tokens_for_cal:
                        delivered_key = f"{action}:{json.dumps(file_paths, sort_keys=True)}"
                        if delivery_cache.get(delivered_key) is True:
                            log.info(f"[SKIP] Повідомлення вже підтверджено: {delivered_key}")
                            continue
                        send_fcm_message(token, data_payload)

        for user, cals in toRemove.items():
            for cal, files in cals.items():
                if user in known_files and cal in known_files[user]:
                    known_files[user][cal] = [f for f in known_files[user][cal] if f not in files]

        known_files = current_files
        save_json(KNOWN_FILES_FILE, known_files)
        time.sleep(10)


if __name__ == '__main__':
    threading.Thread(target=watch_and_notify, daemon=True).start()
    log.info("Сервер запущено на порту 7100")
    app.run(host='0.0.0.0', port=7100)
