"""
Data fetching layer for the Mochi Outreach Dashboard.
All DB queries, sheet fetching, and enrichment logic lives here.
"""

import csv
import io
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

MOCHI_DB = dict(
    host="db-prod.ourmochi.com",
    port=5432,
    dbname="postgres",
    user="bella_mahoney_prod",
    password="DHx8rBL8X9W5kKvF0Tw8",
    sslmode="require",
)

ANALYTICS_DB = dict(
    host="data-data.ourmochi.com",
    port=5432,
    dbname="postgres",
    user="bella_mahoney_data",
    password="7JaqMjzUk90TXE881rc4",
    sslmode="require",
)

NEW_SHEET_ID    = "1SjRvsyHCAM3ahdYamWwRGiTHPZtcpIAQmML1lBh6hlQ"
LEGACY_SHEET_ID = "12t4zFURUh4TMTDyqfwFw8eAczeSW_B-naMpSnRmYwNU"
LEGACY_CUTOFF   = "2026-04-06"
PHASE3_START    = "2026-04-08"
PHASE2_DATE_REMAP = {"2026-04-08": "2026-04-07"}

PT = ZoneInfo("America/Los_Angeles")

AGENT_NAMES = {
    "453b2691-f033-4d98-a789-fcf2720fb7b6": "AJ Ciar",
    "16e69c4d-5d99-4ea7-a0d7-adccc99ac1d6": "Marien Tolentino",
    "ddbbf780-0c6e-45e8-b5eb-2245fc035e63": "Bella Mahoney",
    "0644509e-6eae-4f50-9c68-3d6f23551880": "Madeleine Dailey",
}

ATTRIBUTION_OVERRIDES = {
    "ddbbf780-0c6e-45e8-b5eb-2245fc035e63": "Marien Tolentino",
    "0644509e-6eae-4f50-9c68-3d6f23551880": "AJ Ciar",
}
OVERRIDE_DATES = {"2026-04-06", "2026-04-07"}

DISPOSITION_OVERRIDES = {
    "2093806596|2026-04-01": "Voicemail Left",
    "5716415640|2026-04-06": "Voicemail Left",
    "7329256288|2026-04-03": "Voicemail Left",
    "2067180429|2026-04-07": "Voicemail Left",
    "7082637545|2026-04-08": "Voicemail Left",
    "3036016789|2026-04-09": "Voicemail Left",
    "2069097380|2026-04-09": "Voicemail Left",
    "4078214671|2026-04-14": "Voicemail Left",
    "4018644635|2026-04-14": "Voicemail Left",
    "8036825380|2026-04-15": "Voicemail Left",
    "8057229327|2026-04-15": "Voicemail Left",
    "5738870948|2026-04-10": "Voicemail Left",
    "2547445339|2026-04-13": "Voicemail Left",
    "4077614770|2026-04-14": "Voicemail Left",
    "4069303755|2026-04-14": "Voicemail Left",
    "3088830050|2026-04-20": "Voicemail Left",
    "6157791433|2026-04-24": "Voicemail Left",
    "9782391925|2026-04-21": "Call Answered",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else digits

def fmt_phone(phone10):
    if len(phone10) == 10:
        return f"({phone10[:3]}) {phone10[3:6]}-{phone10[6:]}"
    return phone10

def fmt_duration(secs):
    return f"{secs // 60}m {secs % 60}s"

def disposition_from_queue(result, secs):
    if result == "busy":      return "Inbox Full"
    if result == "no_answer": return "Phone Unavailable"
    if secs < 32:             return "Hung Up"
    if secs < 70:             return "Voicemail Left"
    return "Call Answered"

def parse_csv_line(line):
    reader = csv.reader(io.StringIO(line))
    for row in reader:
        return row
    return []

# ── Sheet fetching ────────────────────────────────────────────────────────────

def fetch_tab_dispositions(tab, date_remap=None):
    url = (
        f"https://docs.google.com/spreadsheets/d/{NEW_SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab)}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    result_map = {}
    for line in resp.text.strip().split("\n")[1:]:
        if not line.strip():
            continue
        cols = parse_csv_line(line)
        if len(cols) < 5:
            continue
        raw_date = cols[0].strip()
        phone10  = normalize_phone(cols[3])
        disp     = cols[4].strip()
        notes    = cols[5].strip() if len(cols) > 5 else ""
        parts = raw_date.split("/")
        if len(parts) != 3:
            continue
        try:
            iso_date = f"{parts[2]}-{int(parts[0]):02d}-{int(parts[1]):02d}"
        except ValueError:
            continue
        if date_remap:
            iso_date = date_remap.get(iso_date, iso_date)
        if not phone10 or not disp:
            continue
        is_cb = notes.startswith("Callback:")
        key = f"{phone10}|{iso_date}|cb" if is_cb else f"{phone10}|{iso_date}"
        result_map[key] = {"result": disp, "notes": notes}
    return result_map

def fetch_legacy_dispositions():
    url = f"https://docs.google.com/spreadsheets/d/{LEGACY_SHEET_ID}/gviz/tq?tqx=out:csv"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    result_map = {}
    for line in resp.text.strip().split("\n")[1:]:
        if not line.strip():
            continue
        cols = parse_csv_line(line)
        if len(cols) < 3:
            continue
        parts = cols[0].strip().split("/")
        if len(parts) != 3:
            continue
        try:
            iso_date = f"{parts[2]}-{int(parts[0]):02d}-{int(parts[1]):02d}"
        except ValueError:
            continue
        phone10 = normalize_phone(cols[1])
        disp    = cols[2].strip()
        if phone10 and disp:
            result_map[f"{phone10}|{iso_date}"] = disp
    return result_map

# ── Main data fetch ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_data(start_date: str, end_date: str):
    """Fetch and enrich all call data for the given date range. Cached 5 min."""

    # 1. Sheet dispositions
    needs_legacy = start_date < LEGACY_CUTOFF
    needs_phase2 = start_date <= "2026-04-07" and end_date >= LEGACY_CUTOFF
    needs_phase3 = end_date >= PHASE3_START

    legacy_disp    = fetch_legacy_dispositions() if needs_legacy else {}
    bella_disp     = fetch_tab_dispositions("Bella Mahoney",    PHASE2_DATE_REMAP) if needs_phase2 else {}
    madelaine_disp = fetch_tab_dispositions("Madeleine Dailey", PHASE2_DATE_REMAP) if needs_phase2 else {}
    marien_disp    = fetch_tab_dispositions("Marien Tolentino") if needs_phase3 else {}
    aj_disp        = fetch_tab_dispositions("AJ Ciar")          if needs_phase3 else {}

    phase2_disps = {
        "ddbbf780-0c6e-45e8-b5eb-2245fc035e63": bella_disp,
        "0644509e-6eae-4f50-9c68-3d6f23551880": madelaine_disp,
    }
    phase3_disps = {
        "16e69c4d-5d99-4ea7-a0d7-adccc99ac1d6": marien_disp,
        "453b2691-f033-4d98-a789-fcf2720fb7b6": aj_disp,
    }

    # Callback follow-ups: phone10 → {call_date, result, notes}
    cb_followups = {}
    for tab_disp in [marien_disp, aj_disp, bella_disp, madelaine_disp]:
        for key, val in tab_disp.items():
            if not key.endswith("|cb"):
                continue
            parts = key.split("|")
            phone10, call_date = parts[0], parts[1]
            if phone10 not in cb_followups or call_date > cb_followups[phone10]["call_date"]:
                cb_followups[phone10] = {"call_date": call_date, **val}

    # 2. DB queries
    mochi_conn = psycopg2.connect(**MOCHI_DB)
    mochi_conn.autocommit = True

    with mochi_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT q.id, q.first_name, q.last_name, q.phone,
                   q.assigned_agent_id, q.contacted_at, q.contact_result,
                   q.call_duration_seconds, q.patient_id, p.mrn,
                   DATE(q.contacted_at AT TIME ZONE 'America/Los_Angeles') AS call_date
            FROM outreach_call_queue q
            LEFT JOIN patients p ON p.id = q.patient_id
            WHERE DATE(q.contacted_at AT TIME ZONE 'America/Los_Angeles') BETWEEN %s AND %s
              AND q.contact_result IS NOT NULL
              AND q.assigned_agent_id = ANY(ARRAY[
                '453b2691-f033-4d98-a789-fcf2720fb7b6',
                '16e69c4d-5d99-4ea7-a0d7-adccc99ac1d6',
                'ddbbf780-0c6e-45e8-b5eb-2245fc035e63',
                '0644509e-6eae-4f50-9c68-3d6f23551880'
              ]::uuid[])
            ORDER BY q.contacted_at
        """, [start_date, end_date])
        raw_calls = cur.fetchall()

    if not raw_calls:
        mochi_conn.close()
        return [], {}, []

    all_phone10s = list({normalize_phone(c["phone"]) for c in raw_calls})

    with mochi_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT RIGHT(REGEXP_REPLACE(contact_phone_number,'[^0-9]','','g'),10) AS phone10,
                   start_at, talk_time
            FROM call_report_line_item
            WHERE RIGHT(REGEXP_REPLACE(contact_phone_number,'[^0-9]','','g'),10) = ANY(%s)
              AND start_at >= %s::date - interval '1 day'
              AND start_at <  %s::date + interval '2 days'
        """, [all_phone10s, start_date, end_date])
        call_start_map = {f"{r['phone10']}|{r['talk_time']}": r["start_at"] for r in cur.fetchall()}

    with mochi_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT DISTINCT RIGHT(REGEXP_REPLACE(phone,'[^0-9]','','g'),10) AS phone10, patient_id
            FROM outreach_call_queue
            WHERE RIGHT(REGEXP_REPLACE(phone,'[^0-9]','','g'),10) = ANY(%s)
              AND patient_id IS NOT NULL
        """, [all_phone10s])
        phone_to_pids = {}
        for row in cur.fetchall():
            phone_to_pids.setdefault(row["phone10"], set()).add(str(row["patient_id"]))

    all_known_pids = list({pid for pids in phone_to_pids.values() for pid in pids})
    subs_by_patient = {}
    if all_known_pids:
        with mochi_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT patient_id, created_at AS sub_at FROM subscriptions
                WHERE patient_id = ANY(%s) AND descriptor = 'HEALTH'
                ORDER BY created_at
            """, [all_known_pids])
            for row in cur.fetchall():
                subs_by_patient.setdefault(str(row["patient_id"]), []).append(row["sub_at"])

    phone_sub_list = {}
    for phone10, pids in phone_to_pids.items():
        for pid in pids:
            for sub_at in subs_by_patient.get(pid, []):
                phone_sub_list.setdefault(phone10, []).append({"pid": pid, "sub_at": sub_at})

    mochi_conn.close()

    # PSM funnel
    psm_funnel = {}
    try:
        analytics_conn = psycopg2.connect(**ANALYTICS_DB)
        analytics_conn.autocommit = True
        with analytics_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT patient_id,
                       scheduled_first_obesity_visit_at,
                       completed_first_obesity_visit_at,
                       first_refill_sent_to_pharmacy_at
                FROM patient_state_model
                WHERE RIGHT(REGEXP_REPLACE(phone,'[^0-9]','','g'),10) = ANY(%s)
                  AND patient_id IS NOT NULL
            """, [all_phone10s])
            for row in cur.fetchall():
                psm_funnel[str(row["patient_id"])] = {
                    "appt_booked":    bool(row["scheduled_first_obesity_visit_at"]),
                    "appt_completed": bool(row["completed_first_obesity_visit_at"]),
                    "refill_created": bool(row["first_refill_sent_to_pharmacy_at"]),
                }
        analytics_conn.close()
    except Exception:
        pass

    # 3. Enrich calls
    enriched = []
    for c in raw_calls:
        phone10   = normalize_phone(c["phone"])
        secs      = c["call_duration_seconds"] or 0
        agent_id  = str(c["assigned_agent_id"])
        call_date = str(c["call_date"])

        agent_name = (
            ATTRIBUTION_OVERRIDES.get(agent_id, AGENT_NAMES.get(agent_id, "Unknown"))
            if call_date in OVERRIDE_DATES
            else AGENT_NAMES.get(agent_id, "Unknown")
        )

        # Disposition
        override_disp     = DISPOSITION_OVERRIDES.get(f"{phone10}|{call_date}")
        sheet_entry       = None
        if call_date < LEGACY_CUTOFF:
            r = legacy_disp.get(f"{phone10}|{call_date}")
            sheet_entry = {"result": r, "notes": ""} if r else None
        elif call_date <= "2026-04-07":
            tab = phase2_disps.get(agent_id, {})
            sheet_entry = tab.get(f"{phone10}|{call_date}") or tab.get(f"{phone10}|{call_date}|cb")
        else:
            tab = phase3_disps.get(agent_id, {})
            sheet_entry = tab.get(f"{phone10}|{call_date}") or tab.get(f"{phone10}|{call_date}|cb")

        sheet_notes  = sheet_entry.get("notes", "") if sheet_entry else ""
        sheet_result = sheet_entry.get("result", "") if sheet_entry else ""
        if sheet_result == "No Answer":
            sheet_result = "Phone Unavailable"

        disp = override_disp or sheet_result or disposition_from_queue(c["contact_result"], secs)

        call_start = call_start_map.get(f"{phone10}|{secs}") or c["contacted_at"]
        if isinstance(call_start, datetime) and call_start.tzinfo is None:
            call_start = call_start.replace(tzinfo=timezone.utc)
        time_pt = call_start.astimezone(PT).strftime("%-I:%M %p") if call_start else ""

        subs_after = sorted(
            [s for s in phone_sub_list.get(phone10, []) if s["sub_at"] > call_start],
            key=lambda x: x["sub_at"]
        ) if call_start else []
        converting_sub  = subs_after[0] if subs_after else None
        converted       = bool(converting_sub)
        conv_via        = "Answered Call" if converted and disp == "Call Answered" else ("Other" if converted else "")
        activated_at    = converting_sub["sub_at"].astimezone(PT).strftime("%Y-%m-%d %-I:%M %p PT") if converting_sub else ""

        appt_booked = appt_completed = refill_created = False
        for pid in phone_to_pids.get(phone10, set()):
            f = psm_funnel.get(pid, {})
            appt_booked    = appt_booked    or f.get("appt_booked", False)
            appt_completed = appt_completed or f.get("appt_completed", False)
            refill_created = refill_created or f.get("refill_created", False)

        fu = cb_followups.get(phone10)
        name = f"{c['first_name'] or ''} {c['last_name'] or ''}".strip() or fmt_phone(phone10)

        enriched.append({
            "date":              call_date,
            "agent":             agent_name,
            "name":              name.title(),
            "phone":             fmt_phone(phone10),
            "phone10":           phone10,
            "time":              time_pt,
            "talk_secs":         secs,
            "talk":              fmt_duration(secs),
            "result":            disp,
            "notes":             sheet_notes,
            "converted":         converted,
            "conv_via":          conv_via,
            "activated_at":      activated_at,
            "mrn":               c.get("mrn") or "",
            "appt_booked":       appt_booked,
            "appt_completed":    appt_completed,
            "refill_created":    refill_created,
            "has_cb_request":    "Call Back Request:" in sheet_notes,
            "is_cb_result":      sheet_notes.startswith("Callback:"),
            "cb_followed_up":    bool(fu),
            "cb_followup_date":  fu["call_date"] if fu else "",
            "cb_followup_result":fu["result"] if fu else "",
        })

    # Dedupe conversion credit: only most recent call before sub gets credit
    from collections import defaultdict
    sub_groups = defaultdict(list)
    for i, c in enumerate(enriched):
        if c["converted"]:
            sub_groups[c["activated_at"]].append(i)
    for group_idxs in sub_groups.values():
        if len(group_idxs) > 1:
            group_idxs.sort(key=lambda i: enriched[i]["date"] + enriched[i]["time"], reverse=True)
            for i in group_idxs[1:]:
                enriched[i]["converted"]  = False
                enriched[i]["conv_via"]   = ""
                enriched[i]["activated_at"] = ""

    # Per-agent stats
    agent_stats = {}
    for c in enriched:
        a = c["agent"]
        if a not in agent_stats:
            agent_stats[a] = {"agent": a, "calls": 0, "answered": 0, "voicemail": 0,
                              "hung_up": 0, "cb_requests": 0, "conversions": 0}
        agent_stats[a]["calls"] += 1
        if c["result"] == "Call Answered":   agent_stats[a]["answered"] += 1
        if c["result"] == "Voicemail Left":  agent_stats[a]["voicemail"] += 1
        if c["result"] == "Hung Up":         agent_stats[a]["hung_up"] += 1
        if c["has_cb_request"]:              agent_stats[a]["cb_requests"] += 1
        if c["converted"]:                   agent_stats[a]["conversions"] += 1

    return enriched, agent_stats, list(agent_stats.keys())
