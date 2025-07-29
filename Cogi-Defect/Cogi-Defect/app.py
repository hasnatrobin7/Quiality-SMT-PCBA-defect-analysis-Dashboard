#!/usr/bin/env python3
"""
Streamlit dashboard for AOI defect data
======================================
Run with:
    streamlit run app.py

Requirements (see requirements.txt):
    streamlit, altair, pandas, numpy, openpyxl
"""
from __future__ import annotations

import io
import datetime as dt
from pathlib import Path
from typing import List
import json

import altair as alt
import logging  # NEW: silence verbose websockets tracebacks

# ---------------------------------------------------------------------------
# Reduce log verbosity coming from Tornado WebSocket pings and Streamlit reruns
# ---------------------------------------------------------------------------
# These tracebacks are harmless but clutter the terminal whenever a browser
# tab refreshes or a user disconnects.  Setting the affected loggers to ERROR
# level hides them while still surfacing real problems.

logging.getLogger("tornado").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime").setLevel(logging.ERROR)

# Try importing sortable function from streamlit_sortables with various names
sortable = None
try:
    import streamlit_sortables as _sts
    for fn_name in ("sortable", "st_sortable", "sort_items", "sortable_list"):
        if hasattr(_sts, fn_name):
            sortable = getattr(_sts, fn_name)
            break
except ImportError:
    pass

# Try Gridstack
gridstack_available = False
try:
    from st_gridstack import gridstack, Card
    gridstack_available = True
except ImportError:
    gridstack_available = False

import pandas as pd
import streamlit as st
import sqlite3

# NEW: Add session state management for debounced filtering
if "filter_applied" not in st.session_state:
    st.session_state.filter_applied = False
if "last_filter_hash" not in st.session_state:
    st.session_state.last_filter_hash = None

# NEW: -------------------------------------------------------------
# Cache database read so the entire table isn't loaded on every
# Streamlit script re-run (which happens on every widget change).
# This dramatically improves UI responsiveness for large datasets.
@st.cache_data(show_spinner=False)
def load_db(path: Path) -> pd.DataFrame:
    """Read the *defects* table from the SQLite database once and cache it."""
    with sqlite3.connect(path) as conn:
        df = pd.read_sql("SELECT * FROM defects", conn)
        # Pre-process datetime columns once during caching
        datetime_cols = [c for c in df.columns 
                        if pd.api.types.is_datetime64_any_dtype(df[c]) or 
                        any(substr in c.lower() for substr in ["date", "time"])]
        for col in datetime_cols:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        return df

# NEW: Cache expensive operations
@st.cache_data(show_spinner=False)
def get_unique_values(df: pd.DataFrame, column: str) -> list:
    """Get sorted unique values for a column, cached."""
    if column in df.columns:
        return sorted(df[column].dropna().unique())
    return []

@st.cache_data(show_spinner=False) 
def apply_filters_cached(df: pd.DataFrame, filter_hash: str, filters: dict, 
                        datetime_col: str = None, start_dt=None, end_dt=None, 
                        outcome_sel=None) -> pd.DataFrame:
    """Apply all filters to dataframe, cached by filter hash."""
    mask = pd.Series(True, index=df.index)
    
    # Outcome filter
    if outcome_sel:
        mask &= df["Outcome"].isin(outcome_sel)
    
    # Column filters  
    for col, sel in filters.items():
        if sel:  # only filter if user selected something
            mask &= df[col].isin(sel)
    
    # Date/time filtering
    if datetime_col and start_dt and end_dt:
        mask &= df[datetime_col].between(start_dt, end_dt)
    
    return df[mask].copy()
# ------------------------------------------------------------------

# NEW: Cache chart data computation
@st.cache_data(show_spinner=False)
def compute_chart_data(filtered_df: pd.DataFrame, top_n: int = 20, dedup: bool = True) -> pd.DataFrame:
    """Compute top Ref_Id counts. If *dedup* true treat pin-level refs as one."""
    if filtered_df.empty or "Ref_Id" not in filtered_df.columns:
        return pd.DataFrame()

    df = filtered_df.copy()

    if dedup:
        df["RF_Base"] = df["Ref_Id"].str.split(".").str[0]
        base_col = "RF_Base"
        # Deduplicate by SerialNumber + RF_Base + DefectCode (if exists)
        dedup_cols = ["SerialNumber", base_col]
        # Include timestamp bucket (minute) to avoid collapsing distinct runs hours apart
        if "EventDate" in df.columns:
            df["_event_min"] = pd.to_datetime(df["EventDate"]).dt.floor("T")
            dedup_cols.append("_event_min")
        if "DefectCode" in df.columns:
            dedup_cols.append("DefectCode")
        df = df.drop_duplicates(dedup_cols)
    else:
        base_col = "Ref_Id"

    return (
        df.groupby(base_col)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .head(top_n)
    )
# ------------------------------------------------------------------

# Locate database: current dir or parent dir
SCRIPT_DIR = Path(__file__).resolve().parent
POSSIBLE_DB_PATHS = [Path.cwd() / "aoi_defects.db", SCRIPT_DIR / "aoi_defects.db", SCRIPT_DIR.parent / "aoi_defects.db"]
DB_PATH = next((p for p in POSSIBLE_DB_PATHS if p.exists()), POSSIBLE_DB_PATHS[0])
DATA_PATTERN = "AOI_defect_status*.xlsx"  # fallback

# configuration file for layout persistence
CONFIG_FILE = SCRIPT_DIR / "layout.json"

# ---------------------------------------------------
# Helper to persist layout immediately
# ---------------------------------------------------

def save_layout():
    cfg = {
        "order": st.session_state.layout_order,
        "widths": st.session_state.section_widths,
        "heights": st.session_state.section_heights,
        "colors": st.session_state.section_colors,
    }
    CONFIG_FILE.write_text(json.dumps(cfg))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_data_files(pattern: str = DATA_PATTERN) -> List[Path]:
    """Return list of matching Excel files sorted newest first."""
    return sorted(Path.cwd().glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)


@st.cache_data(show_spinner=False)
def load_excel(path: Path) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=0)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="AOI Defect Dashboard", layout="wide")

st.title("🪄 AOI Defect Dashboard")

# ---------------------------------------------------------------------------
# Load saved layout config if any
# ---------------------------------------------------------------------------

# (The early load logic supersedes previous block; remove obsolete reload.)

# ----------------------------------------------------------------------------
# Layout customization toggle
# ----------------------------------------------------------------------------

SECTIONS = ["summary", "chart_ref", "chart_comp", "table"]

# ---------------------------------------------------------------------------
# Load saved layout JSON (if present) BEFORE initializing session defaults
# ---------------------------------------------------------------------------

saved_cfg = {}
if CONFIG_FILE.exists():
    try:
        saved_cfg = json.loads(CONFIG_FILE.read_text())
    except Exception:
        saved_cfg = {}

# Initialize session state using saved config if available

if "layout_order" not in st.session_state:
    st.session_state.layout_order = saved_cfg.get("order", SECTIONS.copy())

# Sanitize
st.session_state.layout_order = [s for s in st.session_state.layout_order if s in SECTIONS]
for sec in SECTIONS:
    if sec not in st.session_state.layout_order:
        st.session_state.layout_order.append(sec)

if "section_widths" not in st.session_state:
    st.session_state.section_widths = saved_cfg.get("widths", {s:6 for s in SECTIONS})
else:
    st.session_state.section_widths.update(saved_cfg.get("widths", {}))

if "section_heights" not in st.session_state:
    st.session_state.section_heights = saved_cfg.get("heights", {"chart_ref":400, "chart_comp":400, "table":400})
else:
    st.session_state.section_heights.update(saved_cfg.get("heights", {}))

if "section_colors" not in st.session_state:
    st.session_state.section_colors = saved_cfg.get("colors", {"chart":"#5E8BFF"})
else:
    st.session_state.section_colors.update(saved_cfg.get("colors", {}))

customize_mode = False
if sortable is not None:
    customize_mode = st.sidebar.checkbox("Customize layout", False)
else:
    st.sidebar.info("Install 'streamlit-sortables' to enable drag-and-drop layout customization.")

if DB_PATH.exists():
    st.sidebar.success(f"Using database: {DB_PATH.name}")  # data source indicator
    # CHANGED: Use cached DB loader instead of querying every run
    df = load_db(DB_PATH)
else:
    st.sidebar.warning("Database not found – falling back to Excel files.")
    files = find_data_files()
    if not files:
        st.error("No processed Excel data found. Run `aoi_classify.py` or `ingest_to_db.py` first.")
        st.stop()

    st.sidebar.header("Data source")
    file_choice = st.sidebar.selectbox("Select Excel file", options=[f.name for f in files])
    source_path = next(p for p in files if p.name == file_choice)

    df = load_excel(source_path)

# Show basic info once data is loaded
st.caption(f"Loaded rows: {len(df)}")

# Add a small stability buffer to prevent rapid re-renders
import time
if "last_interaction" not in st.session_state:
    st.session_state.last_interaction = time.time()

# Small delay between interactions to improve stability  
current_time = time.time()
if current_time - st.session_state.last_interaction < 0.1:
    time.sleep(0.05)
st.session_state.last_interaction = current_time

###########################################################################
# Filter UI (center container) - OPTIMIZED
###########################################################################

left_pad, filter_col, right_pad = st.columns([1, 4, 1])

with filter_col:
    st.subheader("Filters")

    # Outcome filter (full width) - use cached unique values
    outcomes = get_unique_values(df, "Outcome")
    outcome_sel = st.multiselect("Outcome", outcomes, default=outcomes, key="outcome")

    # Toggle for pin-level ref-id deduplication
    dedup_pins = st.checkbox("Deduplicate pin-level Ref IDs", value=True, help="Treat C100, C100.1, C100.2 as one Ref")

    # ------------------------------------------------------------------
    # Row 1: Date/Time controls (preset + range) side-by-side
    # ------------------------------------------------------------------
    row1_col1, row1_col2, row1_col3, row1_col4 = st.columns([1, 2, 1, 1])

    # Use cached datetime column detection
    datetime_col = None
    start_date = end_date = None
    start_t = end_t = None

    # Find datetime columns from cached data
    datetime_cols = [c for c in df.columns 
                    if pd.api.types.is_datetime64_any_dtype(df[c])]

    if datetime_cols:
        datetime_col = datetime_cols[0]
        latest_date = df[datetime_col].dt.date.max()

        # Initialize session state for date widgets to prevent re-render issues
        if "preset_mode" not in st.session_state:
            st.session_state.preset_mode = "Daily"
        if "ref_date_value" not in st.session_state:
            st.session_state.ref_date_value = latest_date
        if "date_range_value" not in st.session_state:
            st.session_state.date_range_value = (latest_date, latest_date)

        with row1_col1:
            preset = st.selectbox("Preset", ["Daily", "Weekly", "Monthly", "Custom"], 
                                index=["Daily", "Weekly", "Monthly", "Custom"].index(st.session_state.preset_mode),
                                key="preset")
            st.session_state.preset_mode = preset

        # Date / Date-range selector occupies second column
        with row1_col2:
            # Create a stable container for date widgets
            date_container = st.container()
            with date_container:
                if preset == "Custom":
                    # Use session state to maintain calendar state
                    date_range = st.date_input("Date range", 
                                             value=st.session_state.date_range_value, 
                                             key="date_range",
                                             help="Click to select date range")
                    if isinstance(date_range, tuple) and len(date_range) == 2:
                        start_date, end_date = date_range
                        st.session_state.date_range_value = date_range
                    elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
                        start_date = end_date = date_range[0]
                        st.session_state.date_range_value = (date_range[0], date_range[0])
                    else:
                        start_date = end_date = date_range
                        st.session_state.date_range_value = (date_range, date_range)
                else:
                    # Use session state for reference date
                    ref_date = st.date_input("Reference date", 
                                           value=st.session_state.ref_date_value, 
                                           key="ref_date",
                                           help="Click to select reference date")
                    st.session_state.ref_date_value = ref_date
                    
                    if preset == "Daily":
                        start_date = end_date = ref_date
                    elif preset == "Weekly":
                        start_date = ref_date - dt.timedelta(days=6)
                        end_date = ref_date
                    elif preset == "Monthly":
                        first_day = ref_date.replace(day=1)
                        next_month = (first_day + dt.timedelta(days=32)).replace(day=1)
                        last_day = next_month - dt.timedelta(days=1)
                        start_date, end_date = first_day, last_day

        with row1_col3:
            start_t = st.time_input("Start", dt.time(0, 0), key="start_time")
        with row1_col4:
            end_t = st.time_input("End", dt.time(23, 59), key="end_time")

    # ------------------------------------------------------------------
    # Row 2: PN filters (PartNumber | ComponentPN) - CACHED & OPTIMIZED
    # ------------------------------------------------------------------
    filters = {}
    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        opts_pn = get_unique_values(df, "PartNumber")
        if opts_pn:
            # Limit to first 100 options for UI responsiveness
            display_opts_pn = opts_pn[:100] if len(opts_pn) > 100 else opts_pn
            sel_pn = st.multiselect("Part Number", display_opts_pn, default=[], key="pn_filter")
            if len(opts_pn) > 100:
                st.caption(f"Showing first 100 of {len(opts_pn)} options")
            filters["PartNumber"] = sel_pn
    with row2_col2:
        opts_cpn = get_unique_values(df, "ComponentPN") 
        if opts_cpn:
            display_opts_cpn = opts_cpn[:100] if len(opts_cpn) > 100 else opts_cpn
            sel_cpn = st.multiselect("Component PN", display_opts_cpn, default=[], key="cpn_filter")
            if len(opts_cpn) > 100:
                st.caption(f"Showing first 100 of {len(opts_cpn)} options")
            filters["ComponentPN"] = sel_cpn

    # ------------------------------------------------------------------
    # Row 3: Serial / Ref filters - CACHED & OPTIMIZED
    # ------------------------------------------------------------------
    row3_col1, row3_col2 = st.columns(2)
    with row3_col1:
        opts_sn = get_unique_values(df, "SerialNumber")
        if opts_sn:
            display_opts_sn = opts_sn[:100] if len(opts_sn) > 100 else opts_sn
            sel_sn = st.multiselect("Serial Number", display_opts_sn, default=[], key="sn_filter")
            if len(opts_sn) > 100:
                st.caption(f"Showing first 100 of {len(opts_sn)} options")
            filters["SerialNumber"] = sel_sn
    with row3_col2:
        opts_ref = get_unique_values(df, "Ref_Id")
        if opts_ref:
            display_opts_ref = opts_ref[:100] if len(opts_ref) > 100 else opts_ref
            sel_ref = st.multiselect("Ref Id", display_opts_ref, default=[], key="ref_filter")
            if len(opts_ref) > 100:
                st.caption(f"Showing first 100 of {len(opts_ref)} options")
            filters["Ref_Id"] = sel_ref

    # ------------------------------------------------------------------
    # Row 4: Machine / Operation / Line filters - CACHED & OPTIMIZED
    # ------------------------------------------------------------------
    row4_col1, row4_col2, row4_col3 = st.columns(3)

    with row4_col1:
        opts_machine = get_unique_values(df, "MachineName")
        if opts_machine:
            sel_machine = st.multiselect("Machine Name", opts_machine, default=[], key="machine_filter")
            filters["MachineName"] = sel_machine

    with row4_col2:
        opts_operation = get_unique_values(df, "OperationName")
        if opts_operation:
            sel_operation = st.multiselect("Operation Name", opts_operation, default=[], key="operation_filter")
            filters["OperationName"] = sel_operation

    with row4_col3:
        opts_line = get_unique_values(df, "LineName")
        if opts_line:
            sel_line = st.multiselect("Line Name", opts_line, default=[], key="line_filter")
            filters["LineName"] = sel_line

# ---------------------------------------------------------------------------
# Apply filters using cached function
# ---------------------------------------------------------------------------

# Build datetime range
start_dt = end_dt = None
if datetime_col and start_date and end_date:
    start_dt = dt.datetime.combine(start_date, start_t or dt.time(0,0))
    end_dt = dt.datetime.combine(end_date, end_t or dt.time(23,59))

# Create a hash of current filter state for caching
import hashlib
filter_state = {
    "outcomes": tuple(sorted(outcome_sel)) if outcome_sel else (),
    "filters": {k: tuple(sorted(v)) if v else () for k, v in filters.items()},
    "datetime": (datetime_col, start_dt, end_dt) if start_dt and end_dt else None
}
filter_hash = hashlib.md5(str(filter_state).encode()).hexdigest()

# Only recompute if filters actually changed
if st.session_state.last_filter_hash != filter_hash:
    st.session_state.last_filter_hash = filter_hash
    st.session_state.filter_applied = True

# Use cached filtering with hash
filtered = apply_filters_cached(df, filter_hash, filters, datetime_col, start_dt, end_dt, outcome_sel)

# ---------------------------------------------------------------------------
# Section rendering helpers
# ---------------------------------------------------------------------------

def render_summary():
    st.subheader("Summary counts")
    cols = st.columns(len(outcomes))
    for i, outcome in enumerate(outcomes):
        count = int(filtered[filtered["Outcome"] == outcome].shape[0])
        cols[i].metric(outcome, f"{count}")


# Separate chart renderers

def render_chart_ref():
    if "Ref_Id" not in filtered.columns:
        return
    if len(outcome_sel) == len(outcomes):
        title_suffix = "All outcomes"
    else:
        title_suffix = ", ".join(outcome_sel)
    h_px = st.session_state.section_heights.get("chart_ref",400)
    st.subheader(f"Defect distribution – Top 20 Ref_Id ({title_suffix})")
    ref_data = compute_chart_data(filtered, top_n=20, dedup=dedup_pins)
    if ref_data.empty:
        st.info("No data to display")
        return
    bar_color = st.session_state.section_colors.get("chart", "#5E8BFF")
    y_field = "RF_Base" if dedup_pins else "Ref_Id"
    bar = (
        alt.Chart(ref_data)
        .mark_bar(color=bar_color)
        .encode(x=alt.X("count:Q", title="Defects"), y=alt.Y(f"{y_field}:N", sort="-x", title=y_field))
        .properties(height=h_px)
    )
    st.altair_chart(bar, use_container_width=True)


def render_chart_comp():
    if "ComponentPN" not in filtered.columns:
        return
    h_px = st.session_state.section_heights.get("chart_comp",400)
    st.subheader("Defect distribution – Top 20 Component PN")
    comp_data = (
        filtered.groupby("ComponentPN").size().reset_index(name="count").sort_values("count", ascending=False).head(20)
    )
    if comp_data.empty:
        st.info("No data to display")
        return
    bar = (
        alt.Chart(comp_data)
        .mark_bar(color="#A28BFF")
        .encode(x=alt.X("count:Q", title="Defects"), y=alt.Y("ComponentPN:N", sort="-x", title="Component PN"))
        .properties(height=h_px)
    )
    st.altair_chart(bar, use_container_width=True)


def render_suspect():
    sus = filtered[filtered["Outcome"] == "Suspect"]
    if sus.empty:
        st.info("No suspect items")
        return
    st.subheader("Suspect queue (awaiting operator review)")
    
    # Limit display for performance - show only first 500 rows
    display_sus = sus.head(500) if len(sus) > 500 else sus
    if len(sus) > 500:
        st.warning(f"Showing first 500 of {len(sus)} suspect items for performance")
    
    st.dataframe(
        display_sus.sort_values("SerialNumber") if not display_sus.empty else display_sus,
        use_container_width=True,
        height=st.session_state.section_heights.get("suspect",300),
        hide_index=True,
    )


def render_table():
    with st.expander("📑 Full filtered data table"):
        # Show only first 1000 rows for performance
        display_df = filtered.head(1000) if len(filtered) > 1000 else filtered
        if len(filtered) > 1000:
            st.warning(f"Showing first 1000 of {len(filtered)} rows for performance")
            
        st.dataframe(display_df, use_container_width=True, hide_index=True, 
                    height=st.session_state.section_heights.get("table",400))
        
        # Download button for full dataset
        if not filtered.empty:
            buf = io.BytesIO()
            filtered.to_excel(buf, index=False)
            st.download_button("Download filtered data (Excel)", data=buf.getvalue(), 
                              file_name="filtered_aoi_defect_status.xlsx")

    # Pivot table
    with st.expander("📊 Pivot – Count of SerialNumber by Part › Component › Ref vs DefectCode"):
        if not filtered.empty and "SerialNumber" in filtered.columns and "ComponentPN" in filtered.columns:
            df_piv = filtered.copy()

            # -------------------------------------------------------------
            # Limit to TOP-5 Component PN **within current filter context**
            # -------------------------------------------------------------
            top_pns = (
                df_piv["ComponentPN"].value_counts().nlargest(5).index.tolist()
            )
            df_piv = df_piv[df_piv["ComponentPN"].isin(top_pns)]

            # Ensure RF_Base column present
            if "RF_Base" not in df_piv.columns:
                if "Ref_Id" in df_piv.columns:
                    df_piv["RF_Base"] = df_piv["Ref_Id"].astype(str).str.split(".").str[0]
                else:
                    df_piv["RF_Base"] = "N/A"

            index_cols = [c for c in ("PartNumber","ComponentPN","RF_Base") if c in df_piv.columns]
            col_field = "DefectCode" if "DefectCode" in df_piv.columns else "Outcome"

            pivot = pd.pivot_table(
                df_piv,
                index=index_cols,
                columns=col_field,
                values="SerialNumber",
                aggfunc="nunique",
                fill_value=0,
            )
            st.dataframe(pivot, use_container_width=True)
            # Download
            buf2 = io.BytesIO()
            pivot.to_excel(buf2)
            st.download_button("Download pivot (Excel)", data=buf2.getvalue(), file_name="pivot_defects.xlsx")
        else:
            st.info("Pivot not available – required columns missing.")


section_map = {
    "summary": render_summary,
    "chart_ref": render_chart_ref,
    "chart_comp": render_chart_comp,
    "table": render_table,
}

# ---------------------------------------------------------------------------
# Orderable layout using streamlit-sortable when customize mode enabled
# ---------------------------------------------------------------------------

if customize_mode and sortable is not None:
    st.write("### Order blocks")
    new_order = sortable(st.session_state.layout_order, direction="vertical", key="order_sort")
    st.session_state.layout_order = new_order
    save_layout()

    st.write("### Customize selected block")
    sel_sec = st.selectbox("Block", st.session_state.layout_order, key="custom_block")

    st.session_state.section_widths[sel_sec] = st.slider("Width (1-12)", 1, 12, st.session_state.section_widths.get(sel_sec,6), key="width_slider", on_change=save_layout)

    if sel_sec in ("chart_ref","chart_comp","suspect","table"):
        st.session_state.section_heights[sel_sec] = st.slider("Height (px)", 200, 800, st.session_state.section_heights.get(sel_sec,400), 50, key="height_slider")
        save_layout()

    if sel_sec == "chart_ref":
        st.session_state.section_colors["chart"] = st.color_picker("Bar color", st.session_state.section_colors.get("chart", "#5E8BFF"), key="color_picker")
        save_layout()

# Removed Auto organize button to prevent accidental reset

if gridstack_available:
    LAYOUT_FILE = Path("layout.json")

    # default positions if file absent
    default_layout = {
        "summary": dict(x=0, y=0, w=6, h=2),
        "chart_ref": dict(x=6, y=0, w=6, h=3),
        "chart_comp": dict(x=0, y=2, w=6, h=3),
        "suspect": dict(x=6, y=3, w=6, h=4),
    }

    if "grid_layout" not in st.session_state:
        if LAYOUT_FILE.exists():
            st.session_state.grid_layout = json.loads(LAYOUT_FILE.read_text())
        else:
            st.session_state.grid_layout = default_layout

    # Build grid cards list from saved layout
    cards = []
    for key, pos in st.session_state.grid_layout.items():
        cards.append(Card(key=key, **pos))

    # Render gridstack
    updated = gridstack(
        cards,
        draggable=customize_mode,
        resizable=customize_mode,
        cols=12,
        row_height=90,
        save_layout=customize_mode,
    )

    # If layout changed, persist
    if customize_mode and updated is not None:
        # updated is list of Card objects
        new_layout = {card.key: dict(x=card.x, y=card.y, w=card.w, h=card.h) for card in updated}
        st.session_state.grid_layout = new_layout
        LAYOUT_FILE.write_text(json.dumps(new_layout))
        save_layout()

    # Render sections inside cards (Gridstack renders children automatically)
    for card in updated or cards:
        with card:
            section_map[card.key]()
else:
    # Fallback to two-column rendering
    # Render sections based on order and widths (packing 12-column rows)
    row_sections = []
    row_widths = []
    row_acc = 0

    def flush_row():
        if not row_sections:
            return
        cols = st.columns(row_widths)
        for c, sec in zip(cols, row_sections):
            with c:
                section_map[sec]()

    for sec in st.session_state.layout_order:
        w = st.session_state.section_widths.get(sec,6)
        if row_acc + w > 12:
            flush_row()
            row_sections, row_widths, row_acc = [], [], 0
        row_sections.append(sec)
        row_widths.append(w)
        row_acc += w

    flush_row()

# ---------------------------------------------------------------------------
# Persist config at end of run (ensures saved even when customize mode off)
# ---------------------------------------------------------------------------
cfg_final = {
    "order": st.session_state.layout_order,
    "widths": st.session_state.section_widths,
    "heights": st.session_state.section_heights,
    "colors": st.session_state.section_colors,
}
CONFIG_FILE.write_text(json.dumps(cfg_final)) 