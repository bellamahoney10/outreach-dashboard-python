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

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.9rem; font-weight: 700; }
[data-testid="stMetricLabel"] { font-size: 0.72rem; text-transform: uppercase;
                                letter-spacing: .06em; color: #6e6e73; }
.section-header { display:flex; align-items:baseline; gap:10px; margin: 1.6rem 0 0.3rem; }
.section-header h3 { font-size:0.9rem; font-weight:700; text-transform:uppercase;
                     letter-spacing:.06em; color:#1d1d1f; margin:0; }
div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ────────────────────────────────────────────────────────────────────

RESULT_COLORS = {
    "Call Answered":     "#166534",
    "Voicemail Left":    "#5b21b6",
    "Screened/Declined": "#9d174d",
    "Hung Up":           "#475569",
    "Inbox Full":        "#854d0e",
    "Phone Unavailable": "#475569",
}

def color_result_col(val):
    raw = val.split(" ⚠")[0] if val else val
    fg = RESULT_COLORS.get(raw, "#475569")
    return f"color:{fg}; font-weight:700;"

def style_result(df, col):
    return df.style.applymap(color_result_col, subset=[col])

def fmt_ttc(secs):
    if secs is None or secs < 0: return "—"
    h = secs // 3600
    m = (secs % 3600) // 60
    if h >= 48: return f"{h // 24}d {h % 24}h"
    return f"{h}h {m}m"

def fmt_date_display(iso):
    try:
        y, m, d = iso.split("-")
        return f"{m}-{d}-{y}"
    except Exception:
        return iso

def fmt_date_long(d):
    """date object → 'May 6, 2026'"""
    return d.strftime("%B %-d, %Y")

PER_PAGE = 20

def paginate(df, key):
    total = len(df)
    total_pages = max(1, -(-total // PER_PAGE))
    page = st.session_state.get(f"_page_{key}", 0)
    page = min(page, total_pages - 1)
    sliced = df.iloc[page * PER_PAGE:(page + 1) * PER_PAGE]
    return sliced, page, total_pages, total

def page_controls(key, page, total_pages, total):
    if total_pages <= 1:
        return
    options = [f"{i*PER_PAGE+1}–{min((i+1)*PER_PAGE, total)}" for i in range(total_pages)]
    _, right = st.columns([5, 2])
    with right:
        chosen = st.selectbox(
            f"Page ({total} rows)",
            options, index=page, key=f"_sel_{key}"
        )
        st.session_state[f"_page_{key}"] = options.index(chosen)

# ── Sidebar ────────────────────────────────────────────────────────────────────

today_pt = date.today()

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
    start_date = col1.date_input("From", value=default_start,
                                  min_value=date(2026, 3, 30), max_value=today_pt,
                                  format="MM-DD-YYYY")
    end_date   = col2.date_input("To",   value=default_end,
                                  min_value=date(2026, 3, 30), max_value=today_pt,
                                  format="MM-DD-YYYY")

    if start_date > end_date:
        st.error("Start must be <= end date.")
        st.stop()

    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()

    st.divider()
    st.caption("Data refreshes automatically every 5 minutes.")

start_str = start_date.strftime("%Y-%m-%d")
end_str   = end_date.strftime("%Y-%m-%d")
is_range  = start_str != end_str

# ── Load data ──────────────────────────────────────────────────────────────────

with st.spinner("Loading call data…"):
    calls, agent_stats, agent_names = load_data(start_str, end_str)

if not calls:
    st.warning("No calls found for the selected date range.")
    st.stop()

df = pd.DataFrame(calls)

# ── Header ─────────────────────────────────────────────────────────────────────

st.title("Outreach Dashboard")
if is_range:
    st.caption(f"{fmt_date_long(start_date)} - {fmt_date_long(end_date)}")
else:
    st.caption(fmt_date_long(start_date))

# ── Stats row ──────────────────────────────────────────────────────────────────

total        = len(df)
answered     = (df["result"] == "Call Answered").sum()
voicemail    = (df["result"] == "Voicemail Left").sum()
conversions  = df["converted"].sum()
conv_call    = ((df["converted"]) & (df["conv_via"] == "Answered Call")).sum()
conv_other   = ((df["converted"]) & (df["conv_via"] == "Other")).sum()
answer_rate  = f"{answered/total*100:.1f}%" if total else "—"
conv_rate    = f"{conversions/total*100:.2f}%" if total else "—"

st.divider()
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Total Calls",         total)
c2.metric("Answered",            answered,       delta=answer_rate)
c3.metric("Voicemail",           voicemail)
c4.metric("Conversion (Call)",  int(conv_call),  delta=f"{conv_call/total*100:.2f}%" if total else "—")
c5.metric("Conversion (Other)", int(conv_other), delta=f"{conv_other/total*100:.2f}%" if total else "—")

# ── Trend charts (multi-day only) ──────────────────────────────────────────────

if is_range:
    st.markdown('<div class="section-header"><h3>Trends</h3></div>', unsafe_allow_html=True)
    daily = (
        df.groupby("date")
        .agg(
            total=("result", "count"),
            answered=("result", lambda x: (x == "Call Answered").sum()),
            converted=("converted", "sum"),
        )
        .reset_index()
        .sort_values("date")
    )
    daily["Answer Rate %"]     = (daily["answered"]  / daily["total"]  * 100).round(1)
    daily["Conversion Rate %"] = (daily["converted"] / daily["total"]  * 100).round(2)
    daily["Date"] = daily["date"].apply(fmt_date_display)
    daily = daily.set_index("Date")

    tc1, tc2 = st.columns(2)
    with tc1:
        st.caption("Answer Rate % by Day")
        st.line_chart(daily[["Answer Rate %"]], use_container_width=True)
    with tc2:
        st.caption("Conversion Rate % by Day")
        st.line_chart(daily[["Conversion Rate %"]], use_container_width=True)

# ── Agent breakdown ────────────────────────────────────────────────────────────

st.markdown('<div class="section-header"><h3>Agent Breakdown</h3></div>', unsafe_allow_html=True)
_ag = df.groupby("agent")
agent_df = pd.DataFrame({
    "Agent":       _ag["result"].count().index,
    "Calls":       _ag["result"].count().values,
    "Answered":    _ag["result"].apply(lambda x: (x == "Call Answered").sum()).values,
    "Voicemail":   _ag["result"].apply(lambda x: (x == "Voicemail Left").sum()).values,
    "Hung Up":     _ag["result"].apply(lambda x: (x == "Hung Up").sum()).values,
    "Inbox Full":  _ag["result"].apply(lambda x: (x == "Inbox Full").sum()).values,
    "Screened":    _ag["result"].apply(lambda x: (x == "Screened/Declined").sum()).values,
    "Phone Unavailable": _ag["result"].apply(lambda x: (x == "Phone Unavailable").sum()).values,
    "CONV (Call)":  _ag["conv_via"].apply(lambda x: (x == "Answered Call").sum()).values,
    "CONV (Other)": _ag["conv_via"].apply(lambda x: (x == "Other").sum()).values,
})
agent_df["Answer Rate"] = agent_df.apply(
    lambda r: f"{r['Answered']/r['Calls']*100:.1f}%" if r["Calls"] else "—", axis=1)
agent_df["CVR Rate"] = agent_df.apply(
    lambda r: f"{(r['CONV (Call)']+r['CONV (Other)'])/r['Calls']*100:.2f}%" if r["Calls"] else "—", axis=1)

st.dataframe(
    agent_df[["Agent","Calls","Answered","Answer Rate","Voicemail","Hung Up",
              "Inbox Full","Screened","Phone Unavailable"]],
    use_container_width=True, hide_index=True
)

st.markdown('<div class="section-header"><h3>Conversion Breakdown</h3></div>', unsafe_allow_html=True)
conv_breakdown = agent_df[["Agent","CONV (Call)","CONV (Other)","CVR Rate"]].copy()
conv_breakdown = conv_breakdown.rename(columns={
    "CONV (Call)":  "Conversion (Call)",
    "CONV (Other)": "Conversion (Other)",
    "CVR Rate":     "Conversion Rate",
})
st.dataframe(conv_breakdown, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# CONVERSIONS
# ══════════════════════════════════════════════════════════════════════════════

conv_df = df[df["converted"]].copy()
conv_df["ttc_display"] = conv_df["ttc_secs"].apply(fmt_ttc)
conv_df["result_display"] = conv_df.apply(
    lambda r: r["result"] + (" ⚠" if r["td_mismatch"] else ""), axis=1)

st.markdown('<div class="section-header"><h3>Conversions</h3></div>', unsafe_allow_html=True)

conv_search = st.text_input("Search Name Or MRN", placeholder="Search name or MRN…", key="conv_search")

with st.expander("Filters"):
    fc1, fc2, fc3 = st.columns(3)
    conv_agent  = fc1.selectbox("Agent",           ["All Agents"] + agent_names,          key="conv_agent")
    conv_via    = fc2.selectbox("Via",              ["All Types","Answered Call","Other"],  key="conv_via")
    conv_time   = fc3.selectbox("Time To Convert",  ["Any Time","Within 7 days","After 7 days"], key="conv_time")
    fc4, fc5, fc6 = st.columns(3)
    conv_booked = fc4.selectbox("Appt Booked",      ["All","Yes","No"],   key="conv_booked")
    conv_compl  = fc5.selectbox("Appt Completed",   ["All","Yes","No"],   key="conv_compl")
    conv_refill = fc6.selectbox("Refill Sent",      ["All","Yes","No"],   key="conv_refill")

if conv_search:
    conv_df = conv_df[conv_df["name"].str.contains(conv_search, case=False) |
                      conv_df["mrn"].astype(str).str.contains(conv_search)]
if conv_agent != "All Agents":     conv_df = conv_df[conv_df["agent"] == conv_agent]
if conv_via   == "Answered Call":  conv_df = conv_df[conv_df["conv_via"] == "Answered Call"]
elif conv_via == "Other":          conv_df = conv_df[conv_df["conv_via"] == "Other"]
if conv_time  == "Within 7 days":  conv_df = conv_df[conv_df["ttc_secs"].apply(lambda s: s is not None and s <= 7*24*3600)]
elif conv_time== "After 7 days":   conv_df = conv_df[conv_df["ttc_secs"].apply(lambda s: s is not None and s > 7*24*3600)]
if conv_booked == "Yes":  conv_df = conv_df[conv_df["appt_booked"]]
elif conv_booked == "No": conv_df = conv_df[~conv_df["appt_booked"]]
if conv_compl  == "Yes":  conv_df = conv_df[conv_df["appt_completed"]]
elif conv_compl == "No":  conv_df = conv_df[~conv_df["appt_completed"]]
if conv_refill == "Yes":  conv_df = conv_df[conv_df["refill_created"]]
elif conv_refill == "No": conv_df = conv_df[~conv_df["refill_created"]]

st.caption(f"{len(conv_df)} total")

conv_slice, conv_page, conv_pages, conv_total = paginate(conv_df, "conv")

conv_disp = conv_slice[["mrn","name","agent"] +
    (["date"] if is_range else []) +
    ["time","talk","activated_at","ttc_display","result_display",
     "appt_booked","appt_completed","refill_created"]].copy()
conv_disp.columns = (["MRN","Customer","Agent"] +
    (["Date"] if is_range else []) +
    ["Called At","Talk Time","Subscribed At","Time To Convert","Via",
     "Booked","Completed","Refill Sent"])
if is_range:
    conv_disp["Date"] = conv_disp["Date"].apply(fmt_date_display)
for col in ["Booked","Completed","Refill Sent"]:
    conv_disp[col] = conv_disp[col].map({True:"✓", False:"—"})

st.dataframe(style_result(conv_disp, "Via"), use_container_width=True, hide_index=True)
page_controls("conv", conv_page, conv_pages, conv_total)

# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

cb_df = df[df["has_cb_request"]].copy()

st.markdown('<div class="section-header"><h3>Callback Requests</h3></div>', unsafe_allow_html=True)

cb_search = st.text_input("Search Name Or Phone", placeholder="Search name or phone…", key="cb_search")

with st.expander("Filters"):
    cb1, cb2 = st.columns(2)
    cb_agent  = cb1.selectbox("Agent",        ["All Agents"] + agent_names,   key="cb_agent")
    cb_follow = cb2.selectbox("Followed Up",  ["All","Followed Up","Not Yet"], key="cb_follow")

if cb_search:
    cb_df = cb_df[cb_df["name"].str.contains(cb_search, case=False) |
                  cb_df["phone"].str.contains(cb_search)]
if cb_agent != "All Agents":   cb_df = cb_df[cb_df["agent"] == cb_agent]
if cb_follow == "Followed Up": cb_df = cb_df[cb_df["cb_followed_up"]]
elif cb_follow == "Not Yet":   cb_df = cb_df[~cb_df["cb_followed_up"]]

st.caption(f"{len(cb_df)} total")

cb_slice, cb_page, cb_pages, cb_total = paginate(cb_df, "cb")

cb_cols = (["date","name","phone","agent","time","talk","notes",
             "cb_followed_up","cb_followup_date","cb_followup_result"]
           if is_range else
           ["name","phone","agent","time","talk","notes",
            "cb_followed_up","cb_followup_date","cb_followup_result"])
cb_disp = cb_slice[cb_cols].copy()
cb_disp.columns = (["Date","Customer","Phone","Agent","Called At","Talk Time","Notes",
                     "Followed Up","Callback Date","Callback Result"]
                   if is_range else
                   ["Customer","Phone","Agent","Called At","Talk Time","Notes",
                    "Followed Up","Callback Date","Callback Result"])
if is_range:
    cb_disp["Date"] = cb_disp["Date"].apply(fmt_date_display)
cb_disp["Callback Date"] = cb_disp["Callback Date"].apply(lambda v: fmt_date_display(v) if v else "")
cb_disp["Followed Up"] = cb_disp["Followed Up"].map({True:"✓", False:"—"})
st.dataframe(style_result(cb_disp, "Callback Result"), use_container_width=True, hide_index=True)
page_controls("cb", cb_page, cb_pages, cb_total)

# ══════════════════════════════════════════════════════════════════════════════
# CALL LOG
# ══════════════════════════════════════════════════════════════════════════════

log_df = df[~df["is_cb_result"]].copy()
log_df["result_display"] = log_df.apply(
    lambda r: r["result"] + (" ⚠" if r["td_mismatch"] else ""), axis=1)

st.markdown('<div class="section-header"><h3>Call Log</h3></div>', unsafe_allow_html=True)

log_search = st.text_input("Search Name Or Phone", placeholder="Search name or phone…", key="log_search")

with st.expander("Filters"):
    ll1, ll2, ll3 = st.columns(3)
    log_agent  = ll1.selectbox("Agent",     ["All Agents"] + agent_names,         key="log_agent")
    log_result = ll2.selectbox("Result",    ["All Results","Call Answered","Voicemail Left",
                                             "Hung Up","Inbox Full","Phone Unavailable",
                                             "Screened/Declined"],                 key="log_result")
    log_conv   = ll3.selectbox("Converted", ["All","Converted","Not Converted"],   key="log_conv")

if log_search:
    log_df = log_df[log_df["name"].str.contains(log_search, case=False) |
                    log_df["phone"].str.contains(log_search)]
if log_agent  != "All Agents":     log_df = log_df[log_df["agent"]  == log_agent]
if log_result != "All Results":    log_df = log_df[log_df["result"] == log_result]
if log_conv   == "Converted":      log_df = log_df[log_df["converted"]]
elif log_conv == "Not Converted":  log_df = log_df[~log_df["converted"]]

st.caption(f"{len(log_df)} calls")

log_slice, log_page, log_pages, log_total = paginate(log_df, "log")

log_cols = (["date","name","phone","agent","time","talk","result_display","converted"]
            if is_range else
            ["name","phone","agent","time","talk","result_display","converted"])
log_disp = log_slice[log_cols].copy()
log_disp.columns = (["Date","Customer","Phone","Agent","Time (PT)","Talk Time","Result","Converted"]
                    if is_range else
                    ["Customer","Phone","Agent","Time (PT)","Talk Time","Result","Converted"])
if is_range:
    log_disp["Date"] = log_disp["Date"].apply(fmt_date_display)
log_disp["Converted"] = log_disp["Converted"].map({True:"✓", False:"—"})

st.dataframe(style_result(log_disp, "Result"), use_container_width=True, hide_index=True)
page_controls("log", log_page, log_pages, log_total)

# ── Download ───────────────────────────────────────────────────────────────────

st.divider()
export_df = df[[
    "date","agent","name","phone","time","talk","result","notes",
    "converted","conv_via","activated_at","mrn",
    "appt_booked","appt_completed","refill_created",
    "has_cb_request","cb_followed_up","cb_followup_date","cb_followup_result","td_mismatch","calc_disp",
]].copy()
export_df.columns = [
    "Date","Agent","Customer","Phone","Call Time (PT)","Talk Time","Result","Notes",
    "Converted","Conversion Via","Subscribed At","MRN",
    "Appt Booked","Appt Completed","Refill Sent",
    "Callback Request","Callback Followed Up","Callback Follow-up Date","Callback Result",
    "TD Mismatch","Calculated Disposition",
]
for col in ["Converted","Appt Booked","Appt Completed","Refill Sent",
            "Callback Request","Callback Followed Up","TD Mismatch"]:
    export_df[col] = export_df[col].map({True:"Yes", False:"No"})

csv_buf = io.StringIO()
export_df.to_csv(csv_buf, index=False)
filename = f"mochi-outreach-{start_str}{f'-to-{end_str}' if is_range else ''}.csv"
st.download_button("Download CSV", csv_buf.getvalue().encode("utf-8"),
                   file_name=filename, mime="text/csv")
