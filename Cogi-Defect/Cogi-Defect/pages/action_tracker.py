#!/usr/bin/env python3
"""
action_tracker.py
-----------------
Comprehensive SMT issue tracking dashboard following 8D methodology and best practices.
Features issue categorization, 5W2H analysis, action tracking, and trend monitoring.

Usage (auto-discovered by Streamlit when placed in *pages/*):
    streamlit run app.py   # then pick "Action Tracker" from sidebar
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import List, Dict, Any

import altair as alt
# Plotly imports removed – using Altair for consistency
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# DB helpers (re-use same DB path logic as the main dashboard)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent  # → Cogi-Defect/
POSSIBLE_DB_PATHS = [
    Path.cwd() / "aoi_defects.db",
    ROOT_DIR / "aoi_defects.db",
    ROOT_DIR.parent / "aoi_defects.db",
]
DB_PATH = next((p for p in POSSIBLE_DB_PATHS if p.exists()), POSSIBLE_DB_PATHS[0])

# Issue categories for dropdown
ISSUE_CATEGORIES = [
    "Component-related",
    "Process-related", 
    "Machine-related",
    "Operator error",
    "Other"
]

ISSUE_TYPES = {
    "Component-related": ["Wrong polarity", "Missing component", "Tombstoning", "Wrong value", "Damaged component"],
    "Process-related": ["Solder paste issues", "Placement offset", "Reflow profile", "Insufficient paste", "Paste bridging"],
    "Machine-related": ["Mispick", "Misfeed", "Vision alignment", "Nozzle issues", "Feeder jam"],
    "Operator error": ["Manual touch-up damage", "Mislabeling", "Wrong setup", "Handling damage", "Process deviation"],
    "Other": ["Unknown", "Environmental", "Material quality", "Design issue"]
}

STATUS_OPTIONS = ["Open", "In Progress", "Closed", "On Hold", "Reopened"]

# In-memory caches for performance
@st.cache_data(show_spinner=False)
def load_defects() -> pd.DataFrame:
    """Load AOI defects once, parse EventDate to datetime."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql("SELECT * FROM defects", conn)
    if "EventDate" in df.columns:
        df["EventDate"] = pd.to_datetime(df["EventDate"], errors="coerce")
        # Add ISO work week column (e.g. 2025-W27)
        df["ISO_Week"] = df["EventDate"].dt.strftime('%G-W%V')
    return df

# ---------------------------------------------------------------------------
# Cached slicer for AOI defects (date, machine, part filters)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def slice_defects(df: pd.DataFrame, start: dt.date, end: dt.date,
                  machines: tuple[str], parts: tuple[str], weeks: tuple[str]|None=None, enable_filters: bool = True) -> pd.DataFrame:
    """Return a filtered copy of *df* based on date + optional machine / part / ISO week filters."""
    if df.empty:
        return df
    out = df[df["EventDate"].dt.date.between(start, end)].copy()
    if enable_filters and machines:
        out = out[out["MachineName"].isin(machines)]
    if enable_filters and parts:
        out = out[out["PartNumber"].isin(parts)]
    if enable_filters and weeks:
        out = out[out["ISO_Week"].isin(weeks)]
    return out.copy()

# ---------------------------------------------------------------------------
# Helper: AOI outcome counts per selected date range
# ---------------------------------------------------------------------------

def get_defect_counts(df: pd.DataFrame, start: dt.date, end: dt.date) -> dict[str, int]:
    """Return counts of AOI outcomes within *start*→*end*."""
    if df.empty or "Outcome" not in df.columns:
        return {"False": 0, "Real": 0, "Fixed": 0, "Suspect": 0}

    rng = filter_defects_by_range(df, start, end)
    counts = rng["Outcome"].value_counts() if not rng.empty else pd.Series(dtype=int)
    return {
        "False": int(counts.get("False", 0)),
        "Real": int(counts.get("Real", 0)),
        "Fixed": int(counts.get("Fixed from previously caught", 0)),
        "Suspect": int(counts.get("Suspect", 0)),
    }

# Helper: filter defects to the selected date range
def filter_defects_by_range(df: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Return *df* limited to rows whose date column falls within *start*→*end*."""
    if df.empty:
        return df

    # Detect first plausible date column
    date_col = None
    for col in df.columns:
        if "date" in col.lower() or "time" in col.lower():
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce")
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    date_col = col
                    break
            except Exception:
                continue

    if date_col is None:
        return df  # no date information available

    return df[df[date_col].dt.date.between(start, end)].copy()

def ensure_issues_table(conn: sqlite3.Connection) -> None:
    """Create comprehensive issues tracking table"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date_reported       TEXT NOT NULL,
            line_name           TEXT,
            shift               TEXT,
            serial_number       TEXT,
            component_pn        TEXT,
            ref_id              TEXT,
            issue_category      TEXT,
            issue_type          TEXT,
            description         TEXT,
            
            -- 5W2H Framework
            what_issue          TEXT,
            where_occurred      TEXT,
            why_preliminary     TEXT,
            when_happened       TEXT,
            who_detected        TEXT,
            how_detected        TEXT,
            how_much_impact     TEXT,
            
            -- Action tracking
            short_term_fix      TEXT,
            long_term_action    TEXT,
            responsible_person  TEXT,
            due_date           TEXT,
            status             TEXT,
            
            -- RCA tracking
            rca_completed      INTEGER DEFAULT 0,
            rca_method         TEXT,
            root_cause_final   TEXT,
            effectiveness_check INTEGER DEFAULT 0,
            
            -- Rework/Scrap
            disposition        TEXT,
            rework_time_mins   REAL,
            rework_cost        REAL,

            -- AOI outcome counts for selected date range
            aoi_false          INTEGER DEFAULT 0,
            aoi_real           INTEGER DEFAULT 0,
            aoi_fixed          INTEGER DEFAULT 0,
            aoi_suspect        INTEGER DEFAULT 0,
            
            -- Timestamps
            created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at         TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    # Ensure AOI columns exist even on older DB versions
    cur.execute("PRAGMA table_info(issues);")
    existing_cols = {row[1] for row in cur.fetchall()}
    for col in ["aoi_false", "aoi_real", "aoi_fixed", "aoi_suspect"]:
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE issues ADD COLUMN {col} INTEGER DEFAULT 0;")
    conn.commit()

def ensure_changelog_table(conn: sqlite3.Connection) -> None:
    """Create changelog table for tracking changes"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS issue_changelog (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id           INTEGER NOT NULL,
            field_name         TEXT NOT NULL,
            old_value          TEXT,
            new_value          TEXT,
            changed_by         TEXT,
            changed_at         TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (issue_id) REFERENCES issues (id)
        );
    """)
    conn.commit()

def log_change(conn: sqlite3.Connection, issue_id: int, field_name: str, old_value: str, new_value: str, changed_by: str = "System") -> None:
    """Log a field change to the changelog"""
    ensure_changelog_table(conn)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO issue_changelog (issue_id, field_name, old_value, new_value, changed_by)
        VALUES (?, ?, ?, ?, ?)
    """, (issue_id, field_name, str(old_value), str(new_value), changed_by))
    conn.commit()

def save_issue(conn: sqlite3.Connection, data: Dict[str, Any]) -> int:
    """Save or update issue record with changelog"""
    ensure_issues_table(conn)
    ensure_changelog_table(conn)
    
    # Clean data - remove None values and convert to strings where needed
    clean_data = {}
    for key, value in data.items():
        if value is not None:
            clean_data[key] = str(value) if not isinstance(value, (int, float)) else value
        else:
            clean_data[key] = ""
    
    if 'id' in clean_data and clean_data['id']:
        # Update existing - track changes
        issue_id = clean_data['id']
        
        # Get current values for changelog
        cur = conn.cursor()
        cur.execute("SELECT * FROM issues WHERE id = ?", (issue_id,))
        existing = cur.fetchone()
        
        if existing:
            # Get column names
            columns = [description[0] for description in cur.description]
            existing_dict = dict(zip(columns, existing))
            
            # Compare and log changes
            for key, new_value in clean_data.items():
                if key != 'id' and key in existing_dict:
                    old_value = existing_dict[key]
                    if str(old_value) != str(new_value):
                        log_change(conn, issue_id, key, old_value, new_value)
        
        # Update the record
        cols = [k for k in clean_data.keys() if k != 'id']
        set_clause = ", ".join([f"`{col}` = ?" for col in cols])
        sql = f"UPDATE issues SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        values = [clean_data[col] for col in cols] + [issue_id]
        conn.execute(sql, values)
        conn.commit()
        return issue_id
    else:
        # Insert new record
        cols = [k for k in clean_data.keys() if k != 'id']
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join([f"`{col}`" for col in cols])
        sql = f"INSERT INTO issues ({col_names}) VALUES ({placeholders})"
        
        # Debug the SQL
        print(f"SQL: {sql}")
        print(f"Values: {[clean_data[col] for col in cols]}")
        
        cur = conn.execute(sql, [clean_data[col] for col in cols])
        issue_id = cur.lastrowid
        conn.commit()
        
        # Log creation
        log_change(conn, issue_id, "status", "", "Created", "System")
        
        return issue_id

@st.cache_data(show_spinner=False)
def load_issues() -> pd.DataFrame:
    """Load all issues from database"""
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        ensure_issues_table(conn)
        return pd.read_sql("SELECT * FROM issues ORDER BY date_reported DESC", conn)

# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------
st.set_page_config(page_title="SMT Issue Tracker", layout="wide")
st.title("🔧 SMT Issue Tracker")

if not DB_PATH.exists():
    st.error("Database not found. Please run the ingestion step first (see main dashboard).")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar filters and controls
# ---------------------------------------------------------------------------
st.sidebar.header("📊 Dashboard Controls")

# Determine default ISO week (latest in data) on first load
def latest_iso_week_dates(df: pd.DataFrame):
    if df.empty or "ISO_Week" not in df.columns:
        today = dt.date.today()
        start = today - dt.timedelta(days=today.weekday())
        end = start + dt.timedelta(days=6)
        return start, end
    latest_week_str = df["ISO_Week"].max()  # e.g. "2025-W27"
    year, week = map(int, latest_week_str.split("-W"))
    start = dt.date.fromisocalendar(year, week, 1)  # Monday
    end = start + dt.timedelta(days=6)
    return start, end

# Set default date range only once
if "date_default_set" not in st.session_state:
    def_start, def_end = latest_iso_week_dates(load_defects())
    st.session_state.date_from_default = def_start
    st.session_state.date_to_default = def_end
    st.session_state.date_default_set = True

start_date = st.date_input("From", value=st.session_state.date_from_default)
end_date = st.date_input("To", value=st.session_state.date_to_default)

# Load issues data
issues_df = load_issues()

# ---------------------------------------------------------------------------
# Universal AOI defect filters (date + sidebar machine/part)
# ---------------------------------------------------------------------------

defects_df = load_defects()

# Collect sidebar machine / part filters dynamically (after date filter applied for options)
temp_df = defects_df[defects_df["EventDate"].dt.date.between(start_date, end_date)] if not defects_df.empty else pd.DataFrame()

machines = []
parts = []
weeks = []

if not temp_df.empty and "MachineName" in temp_df.columns:
    machines = st.sidebar.multiselect("Machines", options=sorted(temp_df["MachineName"].dropna().unique()))

if not temp_df.empty and "PartNumber" in temp_df.columns:
    parts = st.sidebar.multiselect("Part Numbers", options=sorted(temp_df["PartNumber"].dropna().unique()))

# Enable/Disable universal filters
enable_filters = st.sidebar.checkbox("Enable filters", True)

# ISO Week filter
if not temp_df.empty and "ISO_Week" in temp_df.columns:
    week_options = sorted(temp_df["ISO_Week"].unique())
    # Default to most recent ISO week on first load (when session state empty)
    default_week = []
    if "default_iso_week_set" not in st.session_state:
        if week_options:
            default_week = [week_options[-1]]  # latest week
        st.session_state.default_iso_week_set = True
    weeks = st.sidebar.multiselect("ISO Work Weeks", options=week_options, default=default_week)

# Slice using cached helper
if not enable_filters:
    machines = parts = weeks = tuple()
defects_filtered = slice_defects(defects_df, start_date, end_date, tuple(machines), tuple(parts), tuple(weeks), enable_filters=enable_filters)

# ---------------------------------------------------------------------------
# Optional pin-level Ref_Id deduplication (C100, C100.1 → C100)
# ---------------------------------------------------------------------------

def deduplicate_pins(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Ref_Id" not in df.columns:
        return df
    d = df.copy()
    d["RF_Base"] = d["Ref_Id"].str.split(".").str[0]
    cols = ["SerialNumber", "RF_Base"]
    if "DefectCode" in d.columns:
        cols.append("DefectCode")
    if "EventDate" in d.columns:
        d["_event_min"] = pd.to_datetime(d["EventDate"]).dt.floor("T")
        cols.append("_event_min")
    return d.drop_duplicates(cols)

dedup_pins = st.sidebar.checkbox("Deduplicate pin-level Ref IDs", value=True, help="Treat C100, C100.1 as one ref toward counts")

if dedup_pins:
    defects_filtered = deduplicate_pins(defects_filtered)

st.session_state['defects_filtered'] = defects_filtered

# Debug info in sidebar
with st.sidebar:
    st.markdown("---")
    st.markdown("**Debug Info:**")
    if not issues_df.empty:
        st.write(f"📊 Total issues in DB: {len(issues_df)}")
        st.write(f"🔄 Filtered issues: {len(filtered_issues) if 'filtered_issues' in locals() else 0}")
    else:
        st.write("❌ No issues found in database")
        # Try to check if database exists and has the table
        if DB_PATH.exists():
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='issues';")
                    table_exists = cur.fetchone()
                    if table_exists:
                        cur.execute("SELECT COUNT(*) FROM issues")
                        count = cur.fetchone()[0]
                        st.write(f"🔍 Issues table exists with {count} records")
                    else:
                        st.write("⚠️ Issues table does not exist")
            except Exception as e:
                st.write(f"❌ Database error: {e}")

if not issues_df.empty:
    # Convert date column
    issues_df['date_reported'] = pd.to_datetime(issues_df['date_reported']).dt.date

    # Filter by date range
    mask = issues_df['date_reported'].between(start_date, end_date)
    filtered_issues = issues_df.loc[mask].copy()
    
    # Sidebar filters
    if 'line_name' in filtered_issues.columns:
        lines = st.sidebar.multiselect("Lines", options=sorted(filtered_issues['line_name'].dropna().unique()))
        if lines:
            filtered_issues = filtered_issues[filtered_issues['line_name'].isin(lines)]
    
    if 'issue_category' in filtered_issues.columns:
        categories = st.sidebar.multiselect("Issue Categories", options=ISSUE_CATEGORIES)
        if categories:
            filtered_issues = filtered_issues[filtered_issues['issue_category'].isin(categories)]
    
    status_filter = st.sidebar.multiselect("Status", options=STATUS_OPTIONS)
    if status_filter:
        filtered_issues = filtered_issues[filtered_issues['status'].isin(status_filter)]
else:
    filtered_issues = pd.DataFrame()

# ---------------------------------------------------------------------------
# Main dashboard tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(["📈 Dashboard", "➕ Add Issue", "📋 Issue List", "📊 Analytics"])

with tab1:
    # Use globally filtered AOI defects data
    defects_df = st.session_state.get('defects_filtered', pd.DataFrame())
    
    # Dashboard overview
    col1, col2, col3, col4 = st.columns(4)
    
    # AOI Defects metrics (filtered by date range)
    if not defects_df.empty:
        ranged_defects = filter_defects_by_range(defects_df, start_date, end_date)
        with col1:
            st.metric("AOI Defects (Range)", len(ranged_defects))
        with col2:
            if 'Outcome' in ranged_defects.columns:
                real_defects = len(ranged_defects[ranged_defects['Outcome'] == 'Real'])
                st.metric("Real Defects", real_defects)
        with col3:
            if 'Outcome' in ranged_defects.columns:
                false_calls = len(ranged_defects[ranged_defects['Outcome'] == 'False'])
                st.metric("False Calls", false_calls)
        with col4:
            if not filtered_issues.empty:
                st.metric("Tracked Issues", len(filtered_issues))
            else:
                st.metric("Tracked Issues", 0)
    
    # AOI Defects charts (filtered by date range)
    if not defects_df.empty:
        # Restrict to sidebar date range for component analysis
        ranged_defects = filter_defects_by_range(defects_df, start_date, end_date)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("AOI Outcomes Distribution")
            if 'Outcome' in ranged_defects.columns:
                outcome_counts = ranged_defects['Outcome'].value_counts()
                if not outcome_counts.empty:
                    chart = alt.Chart(outcome_counts.reset_index()).mark_arc().encode(
                        theta=alt.Theta('count:Q'),
                        color=alt.Color('Outcome:N', 
                            scale=alt.Scale(range=['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4'])),
                        tooltip=['Outcome', 'count']
                    )
                    st.altair_chart(chart, use_container_width=True)
        
        with col2:
            st.subheader("Top 5 Components by Outcome")
            if 'ComponentPN' in ranged_defects.columns and 'Outcome' in ranged_defects.columns:
                tab_real, tab_false = st.tabs(["Real", "False"])

                # --- Top REAL defects — Altair bar chart
                real_df = ranged_defects[ranged_defects['Outcome'] == 'Real']
                if not real_df.empty:
                    top_real = real_df['ComponentPN'].value_counts().head(5)
                    real_df_chart = top_real.reset_index(name='count').rename(columns={'index':'ComponentPN'})
                    real_chart = (
                        alt.Chart(real_df_chart)
                        .mark_bar(color="#ff6b6b")
                        .encode(
                            x=alt.X('count:Q', title='Count'),
                            y=alt.Y('ComponentPN:N', sort='-x', title='Component PN'),
                            tooltip=['ComponentPN', 'count']
                        )
                        .properties(height=300)
                    )
                    with tab_real:
                        st.altair_chart(real_chart, use_container_width=True)

                # --- Top FALSE calls — Altair bar chart
                false_df = ranged_defects[ranged_defects['Outcome'] == 'False']
                if not false_df.empty:
                    top_false = false_df['ComponentPN'].value_counts().head(5)
                    false_df_chart = top_false.reset_index(name='count').rename(columns={'index':'ComponentPN'})
                    false_chart = (
                        alt.Chart(false_df_chart)
                        .mark_bar(color="#4ecdc4")
                        .encode(
                            x=alt.X('count:Q', title='Count'),
                            y=alt.Y('ComponentPN:N', sort='-x', title='Component PN'),
                            tooltip=['ComponentPN', 'count']
                        )
                        .properties(height=300)
                    )
                    with tab_false:
                        st.altair_chart(false_chart, use_container_width=True)
    
    # Issue tracking overview removed from dashboard (moved to Issue List)

with tab2:
    # Add new issue form
    st.subheader("➕ Report New Issue")

    # --- AOI outcome overview for the selected date range ---
    defect_counts = get_defect_counts(load_defects(), start_date, end_date)
    col_f, col_r, col_fix, col_s = st.columns(4)
    with col_f:
        st.metric("False Calls", defect_counts["False"])
    with col_r:
        st.metric("Real Defects", defect_counts["Real"])
    with col_fix:
        st.metric("Fixed", defect_counts["Fixed"])
    with col_s:
        st.metric("Suspect", defect_counts["Suspect"])

    with st.form("new_issue_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            issue_date = st.date_input("Date Reported", value=dt.date.today())
            line_name = st.text_input("Line Name")
            # Shift selection removed
            
        with col2:
            # Check for prefilled data from Quick Actions
            prefill_serial = st.session_state.get('prefill_serial', '')
            prefill_component = st.session_state.get('prefill_component', '')
            prefill_ref_id = st.session_state.get('prefill_ref_id', '')
            
            # Serial Number input removed
            component_pn = st.text_input("Component Part Number", value=prefill_component)
            ref_id = st.text_input("Reference Designator", value=prefill_ref_id)
            
            # Clear prefill data after use
            if prefill_component:
                for key in ['prefill_serial', 'prefill_component', 'prefill_ref_id']:
                    if key in st.session_state:
                        del st.session_state[key]
            
        with col3:
            issue_category = st.selectbox("Issue Category", ISSUE_CATEGORIES)
            issue_type = st.selectbox("Issue Type", ISSUE_TYPES.get(issue_category, []))
            status = st.selectbox("Status", STATUS_OPTIONS, index=0)
        
        prefill_description = st.session_state.pop('prefill_description', '')
        description = st.text_area("Issue Description", value=prefill_description)
        
        # 5W2H Framework
        st.markdown("### 5W2H Analysis")
        col1, col2 = st.columns(2)
        
        with col1:
            what_issue = st.text_area("What was the issue?")
            where_occurred = st.text_input("Where did it occur?")
            why_preliminary = st.text_area("Why (preliminary cause)?")
            prefill_week = st.session_state.pop('prefill_workweek', '')
            when_happened = st.text_input("When did it happen?", value=prefill_week)
            
        with col2:
            who_detected = st.text_input("Who detected it?")
            how_detected = st.text_input("How was it detected?")
            how_much_impact = st.text_area("How much impact? (time/cost)")
            
        # Actions
        st.markdown("### Action Planning")
        col1, col2 = st.columns(2)
        
        with col1:
            short_term_fix = st.text_area("Short-term Fix (Containment)")
            long_term_action = st.text_area("Long-term Corrective Action")
            
        with col2:
            responsible_person = st.text_input("Responsible Person")
            due_date = st.date_input("Due Date")
        
        # RCA section
        st.markdown("### Root Cause Analysis")
        col1, col2 = st.columns(2)
        
        with col1:
            rca_completed = st.checkbox("RCA Completed")
            rca_method = st.selectbox("RCA Method", ["5 Whys", "Fishbone", "8D", "FMEA", "Other"])
            
        with col2:
            root_cause_final = st.text_area("Final Root Cause")
            effectiveness_check = st.checkbox("Effectiveness Verified")
            
        # Disposition inputs removed per requirement
        
        submitted = st.form_submit_button("💾 Save Issue", type="primary")
        
        if submitted:
            issue_data = {
                'date_reported': issue_date.isoformat(),
                'line_name': line_name,
                # shift and serial_number removed per requirements
                'component_pn': component_pn,
                'ref_id': ref_id,
                'issue_category': issue_category,
                'issue_type': issue_type,
                'description': description,
                'what_issue': what_issue,
                'where_occurred': where_occurred,
                'why_preliminary': why_preliminary,
                'when_happened': when_happened,
                'who_detected': who_detected,
                'how_detected': how_detected,
                'how_much_impact': how_much_impact,
                'short_term_fix': short_term_fix,
                'long_term_action': long_term_action,
                'responsible_person': responsible_person,
                'due_date': due_date.isoformat() if due_date else '',
                'status': status,
                'rca_completed': int(rca_completed),
                'rca_method': rca_method,
                'root_cause_final': root_cause_final,
                'effectiveness_check': int(effectiveness_check),
                # disposition inputs removed
            }

            # Attach AOI outcome counts for the current date range
            defect_counts = get_defect_counts(load_defects(), start_date, end_date)
            issue_data.update({
                'aoi_false': defect_counts['False'],
                'aoi_real': defect_counts['Real'],
                'aoi_fixed': defect_counts['Fixed'],
                'aoi_suspect': defect_counts['Suspect'],
            })
            
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    # Debug: Check if table exists
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='issues';")
                    table_exists = cur.fetchone()
                    
                    if not table_exists:
                        st.info("Creating issues table...")
                        ensure_issues_table(conn)
                    
                    issue_id = save_issue(conn, issue_data)
                    
                    # Verify the save worked
                    cur.execute("SELECT COUNT(*) FROM issues WHERE id=?", (issue_id,))
                    count = cur.fetchone()[0]
                    
                    if count > 0:
                        st.success(f"✅ Issue saved successfully with ID: {issue_id}")
                        # Clear the cache to refresh data
                        load_issues.clear()
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("Issue was not saved properly")
                        
            except Exception as e:
                st.error(f"Error saving issue: {str(e)}")
                st.write("Debug info:", str(e))

with tab3:
    # Issue list with editing capabilities
    st.subheader("📋 Issue Management")
    
    if not filtered_issues.empty:
        # Quick stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Filtered Issues", len(filtered_issues))
        with col2:
            overdue = 0
            if 'due_date' in filtered_issues.columns:
                filtered_issues = filtered_issues.assign(
                    due_date_parsed=pd.to_datetime(filtered_issues['due_date'], errors='coerce')
                )
                overdue = len(filtered_issues[
                    (filtered_issues['due_date_parsed'] < pd.Timestamp.now()) & 
                    (filtered_issues['status'].isin(['Open', 'In Progress']))
                ])
            st.metric("⚠️ Overdue", overdue)
        with col3:
            avg_resolution = "N/A"
            if 'created_at' in filtered_issues.columns:
                closed_issues = filtered_issues[filtered_issues['status'] == 'Closed']
                if not closed_issues.empty:
                    closed_issues['created_parsed'] = pd.to_datetime(closed_issues['created_at'])
                    closed_issues['updated_parsed'] = pd.to_datetime(closed_issues['updated_at'])
                    resolution_times = (closed_issues['updated_parsed'] - closed_issues['created_parsed']).dt.days
                    avg_resolution = f"{resolution_times.mean():.1f} days"
            st.metric("Avg Resolution", avg_resolution)

        # --- AOI outcomes on the same date range ---
        defect_counts = get_defect_counts(load_defects(), start_date, end_date)
        col_f, col_r, col_fix, col_s = st.columns(4)
        with col_f:
            st.metric("False Calls", defect_counts["False"])
        with col_r:
            st.metric("Real Defects", defect_counts["Real"])
        with col_fix:
            st.metric("Fixed", defect_counts["Fixed"])
        with col_s:
            st.metric("Suspect", defect_counts["Suspect"])
        
        # Display issues table
        display_columns = [
            'id', 'date_reported', 'line_name', 'shift', 'serial_number', 
            'issue_category', 'issue_type', 'description', 'status', 
            'responsible_person', 'due_date'
        ]
        display_columns = [col for col in display_columns if col in filtered_issues.columns]
        
        if display_columns:
            # Display issues table with action buttons
            for idx, row in filtered_issues.iterrows():
                col1, col2, col3, col4, col5, col6 = st.columns([1, 2, 2, 2, 1, 1])
                
                with col1:
                    primary_name = row.get('component_pn') or f"Issue #{row['id']}"
                    st.write(f"**{primary_name}**  (#{row['id']})")
                with col2:
                    st.write(f"📅 {row['date_reported']}")
                    st.write(f"🏭 {row.get('line_name', 'N/A')}")
                with col3:
                    st.write(f"📦 {row.get('component_pn', 'N/A')}")
                    st.write(f"🔧 {row['issue_category']}")
                with col4:
                    st.write(f"📝 {row['description'][:50]}..." if len(str(row['description'])) > 50 else row['description'])
                    status_color = {"Open": "🔴", "In Progress": "🟡", "Closed": "🟢", "On Hold": "⏸️", "Reopened": "🔄"}
                    st.write(f"{status_color.get(row['status'], '⚪')} {row['status']}")
                with col5:
                    if st.button("✏️ Edit", key=f"edit_{row['id']}"):
                        st.session_state.edit_issue_id = row['id']
                        st.rerun()
                with col6:
                    if st.button("📜 History", key=f"history_{row['id']}"):
                        st.session_state.view_history_id = row['id']
                        st.rerun()
                
                st.markdown("---")
         
        # Interactive Edit Form
        if 'edit_issue_id' in st.session_state and st.session_state.edit_issue_id:
             edit_issue_id = st.session_state.edit_issue_id
             edit_issue = filtered_issues[filtered_issues['id'] == edit_issue_id].iloc[0]
             
             st.markdown("### ✏️ Edit Issue")
             
             # Get full issue data from database
             with sqlite3.connect(DB_PATH) as conn:
                 full_issue = pd.read_sql("SELECT * FROM issues WHERE id = ?", conn, params=(edit_issue_id,)).iloc[0]
             
             with st.form(f"edit_issue_form_{edit_issue_id}", clear_on_submit=False):
                 col1, col2, col3 = st.columns(3)
                 
                 with col1:
                     issue_date = st.date_input("Date Reported", 
                         value=dt.datetime.fromisoformat(full_issue['date_reported']).date() if full_issue['date_reported'] else dt.date.today())
                     line_name = st.text_input("Line Name", value=full_issue.get('line_name', ''))
                     # Shift selection removed
                     
                 with col2:
                     # Serial Number input removed
                     component_pn = st.text_input("Component Part Number", value=full_issue.get('component_pn', ''))
                     ref_id = st.text_input("Reference Designator", value=full_issue.get('ref_id', ''))
                     
                 with col3:
                     issue_category = st.selectbox("Issue Category", ISSUE_CATEGORIES,
                         index=ISSUE_CATEGORIES.index(full_issue.get('issue_category', ISSUE_CATEGORIES[0])) if full_issue.get('issue_category') in ISSUE_CATEGORIES else 0)
                     issue_type = st.selectbox("Issue Type", ISSUE_TYPES.get(issue_category, []),
                         index=ISSUE_TYPES.get(issue_category, []).index(full_issue.get('issue_type', '')) if full_issue.get('issue_type') in ISSUE_TYPES.get(issue_category, []) else 0)
                     status = st.selectbox("Status", STATUS_OPTIONS,
                         index=STATUS_OPTIONS.index(full_issue.get('status', STATUS_OPTIONS[0])) if full_issue.get('status') in STATUS_OPTIONS else 0)
                 
                 description = st.text_area("Issue Description", value=full_issue.get('description', ''))
                 
                 # 5W2H Framework
                 st.markdown("### 5W2H Analysis")
                 col1, col2 = st.columns(2)
                 
                 with col1:
                     what_issue = st.text_area("What was the issue?", value=full_issue.get('what_issue', ''))
                     where_occurred = st.text_input("Where did it occur?", value=full_issue.get('where_occurred', ''))
                     why_preliminary = st.text_area("Why (preliminary cause)?", value=full_issue.get('why_preliminary', ''))
                     when_happened = st.text_input("When did it happen?", value=full_issue.get('when_happened', ''))
                     
                 with col2:
                     who_detected = st.text_input("Who detected it?", value=full_issue.get('who_detected', ''))
                     how_detected = st.text_input("How was it detected?", value=full_issue.get('how_detected', ''))
                     how_much_impact = st.text_area("How much impact? (time/cost)", value=full_issue.get('how_much_impact', ''))
                     
                 # Actions
                 st.markdown("### Action Planning")
                 col1, col2 = st.columns(2)
                 
                 with col1:
                     short_term_fix = st.text_area("Short-term Fix (Containment)", value=full_issue.get('short_term_fix', ''))
                     long_term_action = st.text_area("Long-term Corrective Action", value=full_issue.get('long_term_action', ''))
                     
                 with col2:
                     responsible_person = st.text_input("Responsible Person", value=full_issue.get('responsible_person', ''))
                     due_date = st.date_input("Due Date", 
                         value=dt.datetime.fromisoformat(full_issue['due_date']).date() if full_issue.get('due_date') else dt.date.today())
                 
                 # RCA section
                 st.markdown("### Root Cause Analysis")
                 col1, col2 = st.columns(2)
                 
                 with col1:
                     rca_completed = st.checkbox("RCA Completed", value=bool(full_issue.get('rca_completed', False)))
                     rca_method = st.selectbox("RCA Method", ["5 Whys", "Fishbone", "8D", "FMEA", "Other"],
                         index=["5 Whys", "Fishbone", "8D", "FMEA", "Other"].index(full_issue.get('rca_method', '5 Whys')) if full_issue.get('rca_method') in ["5 Whys", "Fishbone", "8D", "FMEA", "Other"] else 0)
                     
                 with col2:
                     root_cause_final = st.text_area("Final Root Cause", value=full_issue.get('root_cause_final', ''))
                     effectiveness_check = st.checkbox("Effectiveness Verified", value=bool(full_issue.get('effectiveness_check', False)))
                     
                 # Disposition inputs removed per requirement
                 
                 col1, col2 = st.columns(2)
                 with col1:
                     update_submitted = st.form_submit_button("💾 Update Issue", type="primary")
                 with col2:
                     cancel_edit = st.form_submit_button("❌ Cancel")
                 
                 if update_submitted:
                     # Keep existing value when the user leaves a field blank
                     def keep(original, new):
                         return new if str(new).strip() != "" else original

                     update_data = {
                         'id': edit_issue_id,
                         'date_reported': issue_date.isoformat(),
                         'line_name': keep(full_issue.get('line_name',''), line_name),
                         'component_pn': keep(full_issue.get('component_pn',''), component_pn),
                         'ref_id': keep(full_issue.get('ref_id',''), ref_id),
                         'issue_category': issue_category,
                         'issue_type': issue_type,
                         'description': keep(full_issue.get('description',''), description),
                         'what_issue': keep(full_issue.get('what_issue',''), what_issue),
                         'where_occurred': keep(full_issue.get('where_occurred',''), where_occurred),
                         'why_preliminary': keep(full_issue.get('why_preliminary',''), why_preliminary),
                         'when_happened': keep(full_issue.get('when_happened',''), when_happened),
                         'who_detected': keep(full_issue.get('who_detected',''), who_detected),
                         'how_detected': keep(full_issue.get('how_detected',''), how_detected),
                         'how_much_impact': keep(full_issue.get('how_much_impact',''), how_much_impact),
                         'short_term_fix': keep(full_issue.get('short_term_fix',''), short_term_fix),
                         'long_term_action': keep(full_issue.get('long_term_action',''), long_term_action),
                         'responsible_person': keep(full_issue.get('responsible_person',''), responsible_person),
                         'due_date': due_date.isoformat() if due_date else full_issue.get('due_date',''),
                         'status': status,
                         'rca_completed': int(rca_completed),
                         'rca_method': rca_method,
                         'root_cause_final': keep(full_issue.get('root_cause_final',''), root_cause_final),
                         'effectiveness_check': int(effectiveness_check),
                         # disposition inputs removed
                     }
                     
                     try:
                         with sqlite3.connect(DB_PATH) as conn:
                             save_issue(conn, update_data)
                             st.success("✅ Issue updated successfully!")
                             load_issues.clear()
                             del st.session_state.edit_issue_id
                             st.rerun()
                     except Exception as e:
                         st.error(f"Error updating issue: {str(e)}")
                 
                 if cancel_edit:
                     del st.session_state.edit_issue_id
                     st.rerun()

        # ---------------- Issue History Modal ----------------
        if 'view_history_id' in st.session_state and st.session_state.view_history_id:
            hist_id = st.session_state.view_history_id
            st.markdown(f"### 📜 Change History for Issue #{hist_id}")

            with sqlite3.connect(DB_PATH) as conn:
                ensure_changelog_table(conn)
                hist_df = pd.read_sql(
                    "SELECT field_name AS field, old_value AS old, new_value AS new, changed_by AS user, changed_at AS time "
                    "FROM issue_changelog WHERE issue_id = ? ORDER BY changed_at DESC",
                    conn,
                    params=(hist_id,),
                )

            if hist_df.empty:
                st.info("No changes recorded for this issue yet.")
            else:
                st.dataframe(hist_df, use_container_width=True, hide_index=True)

            if st.button("Close History"):
                del st.session_state.view_history_id
                st.rerun()
    else:
        st.info("No issues found for the selected filters.")

with tab4:
    # Analytics and trends
    st.subheader("📊 Trend Analysis")
    
    if not filtered_issues.empty and len(filtered_issues) > 1:
        # Issues over time
        if 'date_reported' in filtered_issues.columns:
            st.subheader("Issues Over Time")
            daily_issues = filtered_issues.groupby('date_reported').size().reset_index(name='count')
            daily_issues['date_reported'] = pd.to_datetime(daily_issues['date_reported'])
            
            chart = alt.Chart(daily_issues).mark_line(point=True).encode(
                x=alt.X('date_reported:T', title='Date'),
                y=alt.Y('count:Q', title='Number of Issues'),
                tooltip=['date_reported:T', 'count:Q']
            )
            st.altair_chart(chart, use_container_width=True)
        
        # Closure rate trend
        if 'status' in filtered_issues.columns:
            st.subheader("Weekly Closure Rate")
            filtered_issues['week'] = pd.to_datetime(filtered_issues['date_reported']).dt.to_period('W')
            weekly_stats = filtered_issues.groupby('week').agg({
                'status': ['count', lambda x: (x == 'Closed').sum()]
            }).round(2)
            weekly_stats.columns = ['total', 'closed']
            weekly_stats['closure_rate'] = (weekly_stats['closed'] / weekly_stats['total'] * 100).fillna(0)
            weekly_stats = weekly_stats.reset_index()
            weekly_stats['week_str'] = weekly_stats['week'].astype(str)
            
            chart = alt.Chart(weekly_stats).mark_bar().encode(
                x=alt.X('week_str:N', title='Week'),
                y=alt.Y('closure_rate:Q', title='Closure Rate (%)', scale=alt.Scale(domain=[0, 100])),
                color=alt.condition(
                    alt.datum.closure_rate >= 80,
                    alt.value('#28a745'),  # Green for good performance
                    alt.value('#dc3545')   # Red for poor performance
                ),
                tooltip=['week_str', 'closure_rate', 'total', 'closed']
            )
            st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Need more data points for trend analysis.")

# ---------------------------------------------------------------------------
# Footer with quick actions
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("💡 **Quick Tips:** Use filters to focus on specific lines or categories. Regular review of recurring issues helps identify systemic problems.") 