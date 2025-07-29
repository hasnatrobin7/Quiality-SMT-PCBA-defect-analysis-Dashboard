#!/usr/bin/env python3
"""
📥 Data Ingestion
=================
Standalone page that lets the user ingest new AOI Excel exports into the
SQLite database.  Uses the existing helper functions from *ingest_to_db.py*
so no business logic is duplicated.
"""
from __future__ import annotations

import io
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

from ingest_to_db import find_xlsx_files, process_file, ensure_table, upsert_df

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DB_PATH = ROOT_DIR / "aoi_defects.db"

st.set_page_config(page_title="Data Ingestion", layout="wide")
st.title("📥 AOI Data Ingestion")

if not DB_PATH.exists():
    st.error("Database not found – create or import one first.")
    st.stop()

# ---------------------------------------------------------------------------
# 1. Upload new Excel files (optional)
# ---------------------------------------------------------------------------

st.header("Upload Excel files")
uploaded_files = st.file_uploader("Select one or more Excel files (.xlsx)", 
                                 type=["xlsx"], accept_multiple_files=True)

uploaded_paths = []
if uploaded_files:
    temp_dir = ROOT_DIR / "uploads"
    temp_dir.mkdir(exist_ok=True)
    for up_file in uploaded_files:
        temp_path = temp_dir / up_file.name
        with open(temp_path, "wb") as f:
            f.write(up_file.getvalue())
        uploaded_paths.append(temp_path)
    st.success(f"Uploaded {len(uploaded_files)} file(s) to {temp_dir}.")

# ---------------------------------------------------------------------------
# 2. Existing Excel files in project folder
# ---------------------------------------------------------------------------

st.header("Existing Excel exports found on disk")
existing_files = find_xlsx_files()
all_files = existing_files + uploaded_paths

if all_files:
    file_names = [f.name for f in all_files]
    selected = st.multiselect("Select Excel files to ingest", options=file_names, default=file_names)

    if selected and st.button("🚀 Run Ingestion", type="primary"):
        sel_paths = [p for p in all_files if p.name in selected]
        progress = st.progress(0.0)
        status = st.empty()

        with sqlite3.connect(DB_PATH) as conn:
            total = len(sel_paths)
            for idx, path in enumerate(sel_paths, start=1):
                status.info(f"Processing {path.name} ({idx}/{total})…")
                df_new = process_file(path)
                ensure_table(conn, df_new)
                upsert_df(conn, df_new)
                progress.progress(idx/total)

        status.success("✅ Ingestion complete. Database updated.")
        # Clear cached defects in whichever module defines load_defects
        try:
            from pages.action_tracker import load_defects  # running via Streamlit page package
        except ModuleNotFoundError:
            from action_tracker import load_defects  # fallback when module is top-level
        load_defects.clear()
        st.balloons()
else:
    st.info("No Excel files found. Upload new files above or copy them into the project directory.") 