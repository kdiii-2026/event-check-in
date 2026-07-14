import csv
import os
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EVENTS = [
    {
        "key": "vbs",
        "label": "VBS 2026 (KidsPoint)",
        "csv": os.path.join(BASE_DIR, "data", "source", "vbs.csv"),
        "attendee_type": "Child",
    },
    {
        "key": "rev",
        "label": "Youth Summer Revival 2026",
        "csv": os.path.join(BASE_DIR, "data", "source", "youth-revival.csv"),
        "attendee_type": "Student",
    },
]


def _norm_grade(raw):
    raw = (raw or "").strip()
    if not raw:
        return "—"
    if raw.startswith("Grades:"):
        raw = raw[len("Grades:"):].strip()
    elif raw.startswith("Grades"):
        raw = raw[len("Grades"):].strip()
    elif raw.startswith("Grade:"):
        raw = raw[len("Grade:"):].strip()
    if raw == "Pre-K - Kindergarten":
        return "Pre-K/K"
    return raw


def _age(birthday):
    if not birthday:
        return None
    try:
        y, m, d = (int(p) for p in birthday.split("/"))
    except ValueError:
        return None
    today = date.today()
    years = today.year - y - ((today.month, today.day) < (m, d))
    return years


def _load_event(event):
    with open(event["csv"], newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    attendee_emails = {
        row["Email"] for row in rows if row["Registration Type"] == event["attendee_type"]
    }

    kids = []
    for row in rows:
        reg_type = row["Registration Type"]
        flag = ""
        if reg_type == event["attendee_type"]:
            pass
        elif reg_type == "Parent/Guardian" and row["Email"] not in attendee_emails:
            flag = "Registered as Parent/Guardian — verify"
        else:
            continue

        kids.append({
            "id": f'{event["key"]}-{row["Response ID"]}',
            "first": row["First Name"].strip(),
            "last": row["Last Name"].strip(),
            "grade": _norm_grade(row.get("Grade Level", "")),
            "gender": (row.get("Gender") or "").upper(),
            "age": _age(row.get("Birthday", "")),
            "phone": row.get("Mobile Phone", "").strip(),
            "email": row.get("Email", "").strip(),
            "allergies": row.get("Food Allergies", "").strip(),
            "medical": row.get("Medical or Other Special Needs", "").strip(),
            "notes": row.get("Additional Information", "").strip(),
            "flag": flag,
        })

    kids.sort(key=lambda k: (k["last"].lower(), k["first"].lower()))
    return kids


def _dedupe(kids, prefer_ids):
    """Registrants who submitted more than once (same person, same phone)
    show up as separate CSV rows -- collapse each such group to one entry.

    Preference order when picking which duplicate to keep: whichever one is
    already checked in (prefer_ids), then whichever isn't a flagged
    Parent/Guardian guess, then the earliest submission (lowest response id).
    """
    groups = {}
    for k in kids:
        key = (k["first"].strip().lower(), k["last"].strip().lower(), k["phone"].strip())
        groups.setdefault(key, []).append(k)

    def score(k):
        return (
            0 if k["id"] in prefer_ids else 1,
            0 if not k["flag"] else 1,
            int(k["id"].rsplit("-", 1)[-1]),
        )

    out = [min(group, key=score) for group in groups.values()]
    out.sort(key=lambda k: (k["last"].lower(), k["first"].lower()))
    return out


def load_roster(prefer_ids=frozenset()):
    return [
        {"key": e["key"], "label": e["label"], "kids": _dedupe(_load_event(e), prefer_ids)}
        for e in EVENTS
    ]


# Just the key<->label mapping, safe to import even where the source CSVs
# (real family PII) don't exist on disk -- e.g. on a hosted deployment that
# reads its roster from the Sheet instead of local files.
EVENTS_META = [{"key": e["key"], "label": e["label"]} for e in EVENTS]
