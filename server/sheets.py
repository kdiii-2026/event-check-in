import threading
from datetime import datetime

import requests

import config
from roster import EVENTS_META

# Column order written to (and read back from) each event's tab. The ID
# column is what lets the hosted deployment reconstruct the roster from the
# Sheet alone, with no local CSVs on disk.
HEADER = [
    "ID", "First Name", "Last Name", "Grade", "Gender", "Age", "Phone", "Email",
    "Allergies", "Medical Notes", "Additional Info", "Flag",
    "Status", "Checked-In At",
]
STATUS_COL = 13   # column M
TIME_FMT = "%Y-%m-%d %I:%M %p"

_lock = threading.Lock()
_webapp_url = None
_secret = None
_row_maps = {}  # event_key -> {kid_id: row_number}
_enabled = False
_init_error = None


def status():
    if _enabled:
        return {"enabled": True}
    return {"enabled": False, "reason": _init_error or "not configured"}


def init():
    """Best-effort setup. Never raises -- disables itself on any problem."""
    global _webapp_url, _secret, _enabled, _init_error

    _webapp_url = config.get("webapp_url", "").strip()
    _secret = config.get("webapp_secret", "").strip()

    if not _webapp_url:
        _init_error = "no webapp_url set (config.json or WEBAPP_URL env var)"
        _enabled = False
        return
    if not _secret:
        _init_error = "no webapp_secret set (config.json or WEBAPP_SECRET env var)"
        _enabled = False
        return

    try:
        r = requests.get(_webapp_url, params={"secret": _secret}, timeout=10)
        r.raise_for_status()
        r.json()  # just confirm it's reachable and returns JSON
        _enabled = True
        _init_error = None
    except Exception as e:  # noqa: BLE001 -- best-effort, log and disable
        _enabled = False
        _init_error = f"{type(e).__name__}: {e}"


def _kid_row(kid, state):
    ts = state.get(kid["id"])
    checked = "Checked In" if ts else "Not checked in"
    when = ""
    if ts:
        when = datetime.fromtimestamp(ts / 1000).strftime(TIME_FMT)
    return [
        kid["id"], kid["first"], kid["last"], kid["grade"], kid.get("gender", ""),
        kid.get("age", ""), kid["phone"], kid["email"],
        kid["allergies"], kid["medical"], kid["notes"], kid["flag"],
        checked, when,
    ]


def _post(payload, timeout=20):
    payload = dict(payload, secret=_secret)
    r = requests.post(_webapp_url, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "unknown error from web app"))
    return data


def _get(params, timeout=20):
    r = requests.get(_webapp_url, params=dict(params, secret=_secret), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "unknown error from web app"))
    return data


def full_sync(roster, all_state):
    """Rewrite every event's tab from scratch to match current roster + check-in state."""
    if not _enabled:
        return
    try:
        with _lock:
            events_payload = []
            for event in roster:
                state = all_state.get(event["key"], {})
                rows = [HEADER] + [_kid_row(k, state) for k in event["kids"]]
                events_payload.append({"label": event["label"], "rows": rows})
            _post({"action": "full_sync", "events": events_payload})
            for event in roster:
                _row_maps[event["key"]] = {
                    k["id"]: i + 2 for i, k in enumerate(event["kids"])
                }
    except Exception as e:  # noqa: BLE001
        global _init_error
        _init_error = f"full_sync failed: {type(e).__name__}: {e}"


def update_one(roster_by_key, event_key, kid_id, ts):
    """Push a single check-in/undo without rewriting the whole tab."""
    if not _enabled:
        return
    row_map = _row_maps.get(event_key)
    if row_map is None or kid_id not in row_map:
        # Fall back to a full resync so future single-row updates work.
        return
    row = row_map[kid_id]
    checked = "Checked In" if ts else "Not checked in"
    when = ""
    if ts:
        when = datetime.fromtimestamp(ts / 1000).strftime(TIME_FMT)
    label = next(e["label"] for e in roster_by_key if e["key"] == event_key)
    try:
        with _lock:
            _post({
                "action": "update_one",
                "label": label,
                "row": row,
                "col": STATUS_COL,
                "values": [checked, when],
            })
    except Exception as e:  # noqa: BLE001
        global _init_error
        _init_error = f"update_one failed: {type(e).__name__}: {e}"


def _row_to_kid(row):
    row = list(row) + [""] * (len(HEADER) - len(row))
    (kid_id, first, last, grade, gender, age, phone, email,
     allergies, medical, notes, flag, checked, when) = row[:len(HEADER)]
    age_val = None
    if str(age).strip().replace(".0", "").isdigit():
        age_val = int(float(age))
    kid = {
        "id": kid_id, "first": first, "last": last, "grade": grade,
        "gender": gender, "age": age_val, "phone": phone, "email": email,
        "allergies": allergies, "medical": medical, "notes": notes, "flag": flag,
    }
    ts = None
    if str(checked).strip() == "Checked In" and str(when).strip():
        try:
            ts = int(datetime.strptime(str(when).strip(), TIME_FMT).timestamp() * 1000)
        except ValueError:
            ts = 1
    return kid, ts


def fetch_roster_and_state():
    """Reconstruct the full roster + check-in state directly from the Sheet.

    Used by hosted deployments that have no local CSVs to read from -- the
    Sheet (kept current via full_sync/update_one) is their source of truth.
    Returns (roster, state) or None if the Sheet can't be reached/parsed.
    """
    if not _enabled:
        return None
    try:
        data = _get({"action": "get_data"})
        sheets_data = data["sheets"]
    except Exception as e:  # noqa: BLE001
        global _init_error
        _init_error = f"fetch_roster_and_state failed: {type(e).__name__}: {e}"
        return None

    roster_out = []
    state_out = {}
    with _lock:
        for meta in EVENTS_META:
            rows = sheets_data.get(meta["label"], [])
            kids = []
            state = {}
            for raw_row in rows[1:]:  # skip header row
                if not any(str(c).strip() for c in raw_row):
                    continue
                kid, ts = _row_to_kid(raw_row)
                if not kid["id"]:
                    continue
                kids.append(kid)
                if ts:
                    state[kid["id"]] = ts
            roster_out.append({"key": meta["key"], "label": meta["label"], "kids": kids})
            state_out[meta["key"]] = state
            _row_maps[meta["key"]] = {k["id"]: i + 2 for i, k in enumerate(kids)}

    return roster_out, state_out
