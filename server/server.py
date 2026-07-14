import io
import json
import os
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import config
import roster
import sheets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "data", "checkins.json")
PUBLIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "public")
IS_HOSTED = "PORT" in os.environ  # Render (and most PaaS hosts) set this

app = Flask(__name__, static_folder=None)

_lock = threading.Lock()
_state = {}            # {event_key: {kid_id: ts_ms}}
_roster_cache = []     # refreshed on demand
_last_sheet_fetch = 0  # hosted mode only -- rate-limits reads from the Sheet


def _load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_state, f)
    os.replace(tmp, STATE_PATH)


def _refresh_roster():
    """Local/dev mode: reload the roster from the CSVs on disk."""
    global _roster_cache
    prefer_ids = set()
    for ev_state in _state.values():
        prefer_ids.update(ev_state.keys())
    _roster_cache = roster.load_roster(prefer_ids=prefer_ids)
    return _roster_cache


def _refresh_from_sheet(force=False):
    """Hosted mode: (re)build the roster + check-in state from the Sheet
    itself, since there are no local CSVs and no durable local disk here."""
    global _roster_cache, _state, _last_sheet_fetch
    if not force and time.time() - _last_sheet_fetch < 60:
        return
    result = sheets.fetch_roster_and_state()
    if result is None:
        return  # keep serving whatever we already have
    fetched_roster, fetched_state = result
    with _lock:
        _roster_cache = fetched_roster
        _state = fetched_state
    _last_sheet_fetch = time.time()


@app.before_request
def _require_passcode():
    if not request.path.startswith("/api/"):
        return None  # the page shell and /print carry no data, no need to gate them
    expected = config.get("access_passcode", "")
    if not expected:
        return None  # no passcode configured -- local/dev mode stays open
    given = request.headers.get("X-Checkin-Passcode", "")
    if given != expected:
        return jsonify({"error": "bad passcode"}), 401


@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/api/roster")
def api_roster():
    if IS_HOSTED:
        _refresh_from_sheet()
        return jsonify(_roster_cache)
    return jsonify(_refresh_roster())


@app.route("/api/state")
def api_state():
    with _lock:
        return jsonify(_state)


@app.route("/api/sheets-status")
def api_sheets_status():
    return jsonify(sheets.status())


@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    body = request.get_json(force=True)
    event_key = body.get("event")
    kid_id = body.get("id")
    if not event_key or not kid_id:
        return jsonify({"error": "event and id are required"}), 400

    with _lock:
        ev_state = _state.setdefault(event_key, {})
        if kid_id in ev_state:
            del ev_state[kid_id]
            ts = None
        else:
            ts = int(time.time() * 1000)
            ev_state[kid_id] = ts
        _save_state()
        state_snapshot = dict(_state)

    sheets.update_one(_roster_cache, event_key, kid_id, ts)
    return jsonify({"ok": True, "state": state_snapshot.get(event_key, {})})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    body = request.get_json(force=True)
    event_key = body.get("event")
    if not event_key:
        return jsonify({"error": "event is required"}), 400

    with _lock:
        _state[event_key] = {}
        _save_state()

    sheets.full_sync(_roster_cache, _state)
    return jsonify({"ok": True})


@app.route("/api/resync-sheet", methods=["POST"])
def api_resync_sheet():
    sheets.init()
    if IS_HOSTED:
        # Pull whatever's currently in the Sheet (e.g. a roster update someone
        # just pushed from their laptop) instead of pushing local CSVs, which
        # don't exist here.
        _refresh_from_sheet(force=True)
    else:
        _refresh_roster()
        sheets.full_sync(_roster_cache, _state)
    return jsonify(sheets.status())


@app.route("/print")
def print_page():
    if IS_HOSTED:
        url = request.url_root.rstrip("/")
    else:
        ip = _lan_ip()
        url = f"http://{ip}:5050" if ip else request.host_url.rstrip("/")

    qr_svg = ""
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
        buf = io.BytesIO()
        img.save(buf)
        qr_svg = buf.getvalue().decode()
    except ImportError:
        pass

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Check-In — Scan to Open</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex; align-items: center; justify-content: center; min-height: 100vh;
    margin: 0; background: #f4f5f7; color: #1a1d21;
  }}
  .card {{
    text-align: center; background: #fff; border: 1px solid #e3e6ea; border-radius: 16px;
    padding: 40px 48px; max-width: 480px;
  }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  p.sub {{ color: #6b7280; font-size: 14px; margin: 0 0 24px; }}
  .qr {{ width: 260px; height: 260px; margin: 0 auto 20px; }}
  .qr svg {{ width: 100%; height: 100%; }}
  .url {{ font-size: 14px; color: #374151; word-break: break-all; margin-bottom: 22px; }}
  .steps {{ text-align: left; font-size: 14px; color: #374151; line-height: 1.6; margin-bottom: 22px; }}
  .steps li {{ margin-bottom: 4px; }}
  button {{
    background: #2563eb; color: #fff; border: none; border-radius: 10px;
    padding: 10px 20px; font-size: 14px; font-weight: 600; cursor: pointer;
  }}
  @media print {{
    body {{ background: #fff; }}
    .card {{ border: none; padding: 0; }}
    button {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="card">
    <h1>Event Check-In</h1>
    <p class="sub">Scan with your phone's camera to open the check-in page</p>
    <div class="qr">{qr_svg}</div>
    <div class="url">{url}</div>
    <ol class="steps">
      <li>{"Open this on your phone or computer." if IS_HOSTED else "Make sure your phone is on the same WiFi as this laptop."}</li>
      <li>Scan the code above (or type the address into your browser).</li>
      <li>Search a name and tap Check In.</li>
    </ol>
    <button onclick="window.print()">Print this page</button>
  </div>
</body>
</html>"""


def _print_qr(url):
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print(f"\nScan to open {url} on another device:\n")
        qr.print_ascii(invert=True)
        print()
    except ImportError:
        print("(install `qrcode` -- pip3 install --user qrcode -- to show a scannable QR code here)")


def _lan_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


# Runs on import, so it happens both under `python3 server.py` (local dev) and
# under gunicorn/production servers that import `server:app` without executing
# the __main__ block below.
sheets.init()
if IS_HOSTED:
    # No local CSVs and no durable disk here -- the Sheet is the source of
    # truth for both roster and check-in state.
    _refresh_from_sheet(force=True)
else:
    _state = _load_state()
    _refresh_roster()
    sheets.full_sync(_roster_cache, _state)
print("Sheets sync:", sheets.status())


if __name__ == "__main__":
    lan_ip = _lan_ip()
    if lan_ip:
        _print_qr(f"http://{lan_ip}:5050")
    else:
        print("(couldn't detect a LAN IP -- make sure this machine is on the venue WiFi)")

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5050)), threaded=True)
