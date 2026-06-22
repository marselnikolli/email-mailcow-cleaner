import json
import os
import tempfile

DATA_DIR = os.environ.get('DATA_DIR', '')

if not DATA_DIR:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

if not os.access(DATA_DIR, os.W_OK):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except (OSError, PermissionError):
        DATA_DIR = os.path.join(tempfile.gettempdir(), 'mailcow-cleaner')
        os.makedirs(DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {
            'mailcow_url': '',
            'api_key': '',
            'dovecot_container': 'dovecot-mailcow',
            'use_header': False,
        }
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE) as f:
        return json.load(f)


def save_history(entry: dict):
    history = load_history()
    history.insert(0, entry)
    if len(history) > 200:
        history = history[:200]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2, default=str)
