import os
import time
import json
from flask import Flask, request, jsonify
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import threading

app = Flask(__name__)

TOKEN_FILE = 'fcm_tokens.json'
SERVICE_ACCOUNT_FILE = '.kappa-dav-firebase-adminsdk.json'
SCOPES = ['https://www.googleapis.com/auth/firebase.messaging']
PROJECT_ID = 'kappa-dav'
WATCH_DIR = '/home/mykhailo/.var/lib/radicale/collections/collection-root'
KNOWN_FILES_FILE = 'known_files.json'


@app.route('/ping')
def ping():
    return "pong", 200


@app.route('/register_token', methods=['POST'])
def register_token():
    data = request.get_json(force=True)
    token, cal_id = data.get('fcm_token'), data.get('calendar_id')
    if not token or not cal_id:
        return jsonify({'error': 'Missing fcm_token or calendar_id'}), 400

    tokens = {}
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE) as f:
                tokens = json.load(f)
        except json.JSONDecodeError:
            tokens = {}

    tokens = {t: c for t, c in tokens.items() if not (c == cal_id and t != token)}

    tokens[token] = cal_id

    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f, indent=2)

    return jsonify({'status': 'Token and calendar_id saved'})



def load_json(file):
    if os.path.exists(file):
        try:
            with open(file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}


def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)


def send_fcm_message(token, data):
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
    print(f'\tFCM response: {resp.status_code} {resp.text}')


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


def watch_and_notify():
    print("[Watcher] Started")
    known_files = load_json(KNOWN_FILES_FILE)

    while True:
        current_files = scan_calendar_files()

        new_files = {}
        for user, cals in current_files.items():
            for cal, files in cals.items():
                known_set = set(known_files.get(user, {}).get(cal, []))
                current_set = set(files)
                diff = current_set - known_set
                if diff:
                    new_files.setdefault(user, {}).setdefault(cal, []).extend(diff)

        if new_files:
            print(f"\t[Watcher] New files detected: {new_files}")

            tokens_map = load_json(TOKEN_FILE)

            for user, cals in new_files.items():
                for cal, files in cals.items():
                    calendar_id = f"{user}/{cal}"
                    tokens_for_cal = [t for t, cid in tokens_map.items() if cid == calendar_id]
                    if not tokens_for_cal:
                        continue

                    file_paths = [os.path.join(user, cal, f) for f in files]
                    data_payload = {"type": "new_files", "files": json.dumps(file_paths)}

                    for token in tokens_for_cal:
                        send_fcm_message(token, data_payload)

            # Оновити відомі файли та зберегти
            known_files = current_files
            save_json(KNOWN_FILES_FILE, known_files)

        time.sleep(10)


if __name__ == '__main__':
    threading.Thread(target=watch_and_notify, daemon=True).start()
    app.run(host='0.0.0.0', port=6000)
