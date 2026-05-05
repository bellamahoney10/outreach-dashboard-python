"""
Mochi Outreach Dashboard — Streamlit
"""

import io
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data import load_data

PT = ZoneInfo("America/Los_Angeles")

st.set_page_config(
    page_title="Mochi Outreach Dashboard",
    page_icon="🩺",
    layout="wide",
)

# ── Styles ────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2rem; font-weight: 700; }
[data-testid="stMetricLabel"] { font-size: 0.8rem; text-transform: uppercase;
                                letter-spacing: .06em; color: #6e6e73; }
.section-title { font-size: 1rem; font-weight: 700; text-transform: uppercase;
                 letter-spacing: .06em; color: #1d1d1f; margin: 1.5rem 0 0.5rem; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar: date range ───────────────────────────────────────────────────────

today_pt = date.today()  # server-side; close enough for PT

with st.sidebar:
    st.title("Mochi Outreach")
    st.caption("Call results dashboard")
    st.divider()

    preset = st.radio("Quick range", ["Today", "This week", "All time"], horizontal=True)
    if preset == "Today":
        default_start = default_end = today_pt
    elif preset == "This week":
        default_start = today_pt - timedelta(days=today_pt.weekday())
        default_end   = today_pt
    else:
        default_start = date(2026, 3, 30)
        default_end   = today_pt

    col1, col2 = st.columns(2)
    start_date = col1.date_input("From", value=default_start, min_value=date(2026, 3, 30), max_value=today_pt)
    end_date   = col2.date_input("To",   value=default_end,   min_value=date(2026, 3, 30), max_value=today_pt)

    if start_date > end_date:
        st.error("Start must be ≤ end date.")
        st.stop()

    refresh = st.button("↻ Refresh data", use_container_width=True)
    if refresh:
        st.cache_data.clear()

    st.divider()
    st.caption("Data refreshes automatically every 5 minutes.")

start_str = start_date.strftime("%Y-%m-%d")
end_str   = end_date.strftime("%Y-%m-%d")
is_range  = start_str != end_str

# ── Load data ─────────────────────────────────────────────────────────────────

with st.spinner("Loading call data…"):
    calls, agent_stats, agent_names = load_data(start_str, end_str)

if not calls:
    st.warning("No calls found for the selected date range.")
    st.stop()

df = pd.DataFrame(calls)

# ── Header ────────────────────────────────────────────────────────────────────

label = end_str if not is_range else f"{start_str} – {end_str}"
st.title(f"Outreach — {label}")

# ── Stats row ─────────────────────────────────────────────────────────────────

total        = len(df)
answered     = (df["result"] == "Call Answered").sum()
voicemail    = (df["result"] == "Voicemail Left").sum()
conversions  = df["converted"].sum()
cb_requests  = df["has_cb_request"].sum()
cb_followed  = df["cb_followed_up"].sum()
answer_rate  = f"{answered / total * 100:.1f}%" if total else "—"
conv_rate    = f"{conversions / total * 100:.2f}%" if total else "—"

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Total Calls",       total)
c2.metric("Answered",          answered,   delta=answer_rate)
c3.metric("Voicemail",         voicemail)
c4.metric("Conversions",       conversions, delta=conv_rate)
c5.metric("Callback Requests", cb_requests)
c6.metric("Followed Up",       int(cb_followed))
c7.metric("Not Followed Up",   int(cb_requests - cb_followed))

# ── Agent breakdown ───────────────────────────────────────────────────────────

st.markdown('<div class="section-title">Agent Breakdown</div>', unsafe_allow_html=True)
agent_df = pd.DataFrame(list(agent_stats.values()))
agent_df["answer_rate"] = agent_df.apply(
    lambda r: f"{r['answered']/r['calls']*100:.1f}%" if r["calls"] else "—", axis=1
)
agent_df["conv_rate"] = agent_df.apply(
    lambda r: f"{r['conversions']/r['calls']*100:.2f}%" if r["calls"] else "—", axis=1
)
agent_df = agent_df.rename(columns={
    "agent": "Agent", "calls": "Calls", "answered": "Answered",
    "voicemail": "Voicemail", "hung_up": "Hung Up",
    "cb_requests": "Callback Requests", "conversions": "Conversions",
    "answer_rate": "Answer Rate", "conv_rate": "Conv Rate",
})
st.dataframe(agent_df[["Agent","Calls","Answered","Answer Rate","Voicemail","Hung Up",
                         "Callback Requests","Conversions","Conv Rate"]],
             use_container_width=True, hide_index=True)

# ── Callback Requests ─────────────────────────────────────────────────────────

st.markdown('<div class="section-title">Callback Requests</div>', unsafe_allow_html=True)

cb_df = df[df["has_cb_request"]].copy()

with st.expander("Filters", expanded=False):
    fc1, fc2, fc3 = st.columns(3)
    cb_search     = fc1.text_input("Search name / phone", key="cb_search")
    cb_agent      = fc2.selectbox("Agent", ["All"] + agent_names, key="cb_agent")
    cb_followed_f = fc3.selectbox("Followed up", ["All", "Yes ✓", "Not yet"], key="cb_followed")

if cb_search:
    cb_df = cb_df[cb_df["name"].str.contains(cb_search, case=False) |
                  cb_df["phone"].str.contains(cb_search)]
if cb_agent != "All":
    cb_df = cb_df[cb_df["agent"] == cb_agent]
if cb_followed_f == "Yes ✓":
    cb_df = cb_df[cb_df["cb_followed_up"]]
elif cb_followed_f == "Not yet":
    cb_df = cb_df[~cb_df["cb_followed_up"]]

cb_display = cb_df[[
    "date" if is_range else "name", "name", "phone", "agent",
    "time", "talk", "notes", "cb_followed_up", "cb_followup_date", "cb_followup_result"
]].copy()
cb_display.columns = (
    ["Date", "Customer", "Phone", "Agent", "Original Call", "Talk Time",
     "Notes", "Followed Up", "Callback Date", "Callback Result"]
    if is_range else
    ["Customer", "Phone", "Agent", "Original Call", "Talk Time",
     "Notes", "Followed Up", "Callback Date", "Callback Result"]
)
cb_display["Followed Up"] = cb_display["Followed Up"].map({True: "✓", False: "—"})

st.dataframe(cb_display, use_container_width=True, hide_index=True)

# ── Conversions ───────────────────────────────────────────────────────────────

st.markdown('<div class="section-title">Conversions</div>', unsafe_allow_html=True)

conv_df = df[df["converted"]].copy()

with st.expander("Filters", expanded=False):
    vc1, vc2, vc3 = st.columns(3)
    conv_search = vc1.text_input("Search name / phone", key="conv_search")
    conv_agent  = vc2.selectbox("Agent", ["All"] + agent_names, key="conv_agent")
    conv_via    = vc3.selectbox("Via", ["All", "Answered Call", "Other"], key="conv_via")

if conv_search:
    conv_df = conv_df[conv_df["name"].str.contains(conv_search, case=False) |
                      conv_df["phone"].str.contains(conv_search)]
if conv_agent != "All":
    conv_df = conv_df[conv_df["agent"] == conv_agent]
if conv_via != "All":
    conv_df = conv_df[conv_df["conv_via"] == conv_via]

conv_display = conv_df[["date","agent","name","phone","time","talk","result",
                          "activated_at","conv_via","mrn",
                          "appt_booked","appt_completed","refill_created"]].copy()
conv_display.columns = ["Date","Agent","Customer","Phone","Call Time","Talk Time",
                         "Result","Subscribed At","Via","MRN",
                         "Appt Booked","Appt Completed","Refill Sent"]
for col in ["Appt Booked","Appt Completed","Refill Sent"]:
    conv_display[col] = conv_display[col].map({True: "✓", False: "—"})

st.dataframe(conv_display, use_container_width=True, hide_index=True)

# ── Call Log ──────────────────────────────────────────────────────────────────

st.markdown('<div class="section-title">Call Log</div>', unsafe_allow_html=True)

log_df = df[~df["is_cb_result"]].copy()

with st.expander("Filters", expanded=False):
    lc1, lc2, lc3, lc4 = st.columns(4)
    log_search  = lc1.text_input("Search name / phone", key="log_search")
    log_agent   = lc2.selectbox("Agent", ["All"] + agent_names, key="log_agent")
    log_result  = lc3.selectbox("Result", ["All", "Call Answered", "Voicemail Left",
                                            "Hung Up", "Inbox Full", "Phone Unavailable",
                                            "Screened/Declined"], key="log_result")
    log_conv    = lc4.selectbox("Converted", ["All", "Yes", "No"], key="log_conv")

if log_search:
    log_df = log_df[log_df["name"].str.contains(log_search, case=False) |
                    log_df["phone"].str.contains(log_search)]
if log_agent != "All":
    log_df = log_df[log_df["agent"] == log_agent]
if log_result != "All":
    log_df = log_df[log_df["result"] == log_result]
if log_conv == "Yes":
    log_df = log_df[log_df["converted"]]
elif log_conv == "No":
    log_df = log_df[~log_df["converted"]]

log_display = log_df[["date","agent","name","phone","time","talk","result","notes"]].copy()
log_display.columns = ["Date","Agent","Customer","Phone","Time (PT)","Talk Time","Result","Notes"]

st.dataframe(log_display, use_container_width=True, hide_index=True)
st.caption(f"{len(log_df)} calls shown")

# ── Download ──────────────────────────────────────────────────────────────────

st.divider()
st.markdown("**Download all data**")

export_df = df[[
    "date","agent","name","phone","time","talk","result","notes",
    "converted","conv_via","activated_at","mrn",
    "appt_booked","appt_completed","refill_created",
    "has_cb_request","cb_followed_up","cb_followup_date","cb_followup_result",
]].copy()
export_df.columns = [
    "Date","Agent","Customer","Phone","Call Time (PT)","Talk Time","Result","Notes",
    "Converted","Conversion Via","Subscribed At","MRN",
    "Appt Booked","Appt Completed","Refill Sent",
    "Callback Request","Callback Followed Up","Callback Follow-up Date","Callback Result",
]
for col in ["Converted","Appt Booked","Appt Completed","Refill Sent",
            "Callback Request","Callback Followed Up"]:
    export_df[col] = export_df[col].map({True: "Yes", False: "No"})

csv_buf = io.StringIO()
export_df.to_csv(csv_buf, index=False)
filename = f"mochi-outreach-{start_str}{f'-to-{end_str}' if is_range else ''}.csv"

st.download_button(
    label="⬇ Download CSV",
    data=csv_buf.getvalue().encode("utf-8"),
    file_name=filename,
    mime="text/csv",
    use_container_width=False,
)
