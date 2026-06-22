#!/usr/bin/env python3
import os
import subprocess
import shlex
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, redirect

from app.config_manager import load_config, save_config, load_history, save_history
from app.mailcow_api import MailcowAPI
from app.doveadm_exec import preview as dove_preview, execute as dove_execute

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mailcow-cleaner-change-me')
app.permanent_session_lifetime = timedelta(hours=int(os.environ.get('SESSION_LIFETIME_HOURS', 24)))
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'admin')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Authentication required'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


def get_api() -> MailcowAPI | None:
    cfg = load_config()
    if not cfg.get('mailcow_url') or not cfg.get('api_key'):
        return None
    return MailcowAPI(cfg['mailcow_url'], cfg['api_key'])


@app.route('/login')
def login_page():
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if data.get('password') == APP_PASSWORD:
        session['authenticated'] = True
        session.permanent = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid password'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/check-auth')
def check_auth():
    return jsonify({'authenticated': session.get('authenticated', False)})


@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/api/config', methods=['GET', 'POST'])
@login_required
def config():
    if request.method == 'POST':
        data = request.get_json()
        cfg = load_config()
        cfg['mailcow_url'] = data.get('mailcow_url', '').rstrip('/')
        cfg['api_key'] = data.get('api_key', '')
        cfg['dovecot_container'] = data.get('dovecot_container', 'dovecot-mailcow')
        cfg['use_header'] = data.get('use_header', False)
        save_config(cfg)
        return jsonify({'success': True})
    cfg = load_config()
    return jsonify({
        'configured': bool(cfg.get('mailcow_url') and cfg.get('api_key')),
        'mailcow_url': cfg.get('mailcow_url', ''),
        'dovecot_container': cfg.get('dovecot_container', 'dovecot-mailcow'),
        'use_header': cfg.get('use_header', False),
    })


@app.route('/api/test', methods=['GET'])
@login_required
def test_connection():
    api = get_api()
    if not api:
        return jsonify({'success': False, 'error': 'Not configured'})
    ok, msg = api.test_connection()
    cfg = load_config()
    return jsonify({
        'success': ok,
        'message': msg,
        'dovecot_container': cfg.get('dovecot_container', 'dovecot-mailcow'),
    })


@app.route('/api/domains', methods=['GET'])
@login_required
def get_domains():
    api = get_api()
    if not api:
        return jsonify({'success': False, 'error': 'Not configured'})
    try:
        data = api.get_domains()
        domains = []
        for d in data:
            if isinstance(d, dict) and 'domain' in d:
                domains.append({'name': d['domain'], 'active': d.get('active', '1') == '1'})
            elif isinstance(d, str):
                domains.append({'name': d, 'active': True})
        return jsonify({'success': True, 'domains': sorted(domains, key=lambda x: x['name'])})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/mailboxes', methods=['GET'])
@login_required
def get_mailboxes():
    api = get_api()
    if not api:
        return jsonify({'success': False, 'error': 'Not configured'})
    domain = request.args.get('domain')
    try:
        data = api.get_mailboxes(domain)
        mailboxes = []
        for m in data:
            if isinstance(m, dict):
                mailboxes.append({
                    'email': m.get('username', m.get('local_part', '')),
                    'name': m.get('name', ''),
                    'quota': m.get('quota', 0),
                    'used': m.get('used_quota', 0),
                })
            elif isinstance(m, str):
                mailboxes.append({'email': m, 'name': '', 'quota': 0, 'used': 0})
        return jsonify({
            'success': True,
            'mailboxes': sorted(mailboxes, key=lambda x: x['email']),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/all-mailboxes', methods=['GET'])
@login_required
def get_all_mailboxes():
    api = get_api()
    if not api:
        return jsonify({'success': False, 'error': 'Not configured'})
    try:
        data = api.get_mailboxes(None)
        mailboxes = []
        for m in data:
            if isinstance(m, dict):
                mailboxes.append(m.get('username', ''))
            elif isinstance(m, str):
                mailboxes.append(m)
        return jsonify({
            'success': True,
            'mailboxes': sorted([m for m in mailboxes if m]),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/preview', methods=['POST'])
@login_required
def preview_cleanup():
    api = get_api()
    if not api:
        return jsonify({'success': False, 'error': 'Not configured'})
    data = request.get_json()
    mailboxes = data.get('mailboxes', [])
    folders = data.get('folders', ['INBOX'])
    from_addrs = [a.strip() for a in data.get('from', '').split(',') if a.strip()]
    subject = data.get('subject', '').strip() or None
    age_value = data.get('age_value')
    age_unit = data.get('age_unit', 'days')
    match_or = data.get('match_or', False)
    cfg = load_config()

    if not from_addrs and not subject and age_value is None:
        return jsonify({'success': False, 'error': 'At least one filter is required'})
    if not mailboxes:
        return jsonify({'success': False, 'error': 'At least one mailbox is required'})

    results = {}
    grand_total = 0

    for mb in mailboxes:
        res = dove_preview(
            mailbox=mb,
            folders=folders,
            from_addrs=from_addrs,
            subject=subject,
            age_value=age_value,
            age_unit=age_unit,
            match_or=match_or,
            use_header=cfg.get('use_header', False),
            dovecot_container=cfg.get('dovecot_container', 'dovecot-mailcow'),
        )
        if res.get('success'):
            results[mb] = res
            grand_total += res.get('total', 0)
        else:
            results[mb] = res

    return jsonify({
        'success': True,
        'grand_total': grand_total,
        'results': results,
    })


@app.route('/api/cleanup', methods=['POST'])
@login_required
def cleanup():
    api = get_api()
    if not api:
        return jsonify({'success': False, 'error': 'Not configured'})
    data = request.get_json()
    mailboxes = data.get('mailboxes', [])
    folders = data.get('folders', ['INBOX'])
    from_addrs = [a.strip() for a in data.get('from', '').split(',') if a.strip()]
    subject = data.get('subject', '').strip() or None
    age_value = data.get('age_value')
    age_unit = data.get('age_unit', 'days')
    match_or = data.get('match_or', False)
    confirmed = data.get('confirmed', False)
    cfg = load_config()

    if not confirmed:
        return jsonify({'success': False, 'error': 'Confirmation required'})
    if not mailboxes:
        return jsonify({'success': False, 'error': 'At least one mailbox is required'})

    results = {}
    all_ok = True

    for mb in mailboxes:
        res = dove_execute(
            mailbox=mb,
            folders=folders,
            from_addrs=from_addrs,
            subject=subject,
            age_value=age_value,
            age_unit=age_unit,
            match_or=match_or,
            use_header=cfg.get('use_header', False),
            dovecot_container=cfg.get('dovecot_container', 'dovecot-mailcow'),
        )
        if res.get('success'):
            results[mb] = res
        else:
            results[mb] = res
            all_ok = False

    entry = {
        'timestamp': datetime.now().isoformat(),
        'mailboxes': mailboxes,
        'folders': folders,
        'from': from_addrs,
        'subject': subject,
        'age': f'{age_value} {age_unit}' if age_value else None,
        'match_or': match_or,
        'success': all_ok,
        'results': results,
    }
    save_history(entry)

    return jsonify({
        'success': all_ok,
        'results': results,
    })


@app.route('/api/test-doveadm', methods=['POST'])
@login_required
def test_doveadm():
    data = request.get_json()
    mailbox = data.get('mailbox', '')
    folder = data.get('folder', 'INBOX')
    dovecot_container = data.get('dovecot_container', 'dovecot-mailcow')

    cmd = ['docker', 'exec', dovecot_container, 'doveadm', 'search', '-u', mailbox, 'mailbox', folder, 'ALL']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return jsonify({
            'success': result.returncode == 0,
            'returncode': result.returncode,
            'stdout': result.stdout.strip()[:2000],
            'stderr': result.stderr.strip()[:2000],
            'command': ' '.join(shlex.quote(c) for c in cmd),
        })
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Docker CLI not found in container', 'command': ' '.join(shlex.quote(c) for c in cmd)})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Command timed out', 'command': ' '.join(shlex.quote(c) for c in cmd)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'command': ' '.join(shlex.quote(c) for c in cmd)})


@app.route('/api/history', methods=['GET'])
@login_required
def get_history():
    return jsonify({'history': load_history()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'production') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)
