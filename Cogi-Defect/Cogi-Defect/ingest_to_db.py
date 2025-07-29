#!/usr/bin/env python3
"""
ingest_to_db.py
---------------
Batch-process all AOI export workbooks in the current directory (or those
passed on the command line), classify each pad-defect combo into its Outcome
bucket, and upsert the results into a local SQLite database so the
Streamlit dashboard can query a single consolidated source.

Duplicates (same SerialNumber + Ref_Id + DefectCode) are automatically
REPLACEd rather than appended, so re-processing the same file won’t create
multiple copies.

Usage
-----
$ python ingest_to_db.py               # scans for all matching xlsx files
$ python ingest_to_db.py file1.xlsx ...
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import List

import pandas as pd

from aoi_classify import classify  # reuse helper

DB_PATH = Path("aoi_defects.db")
DATA_PATTERN = "Defect RawData - *.xlsx"
PRIMARY_KEY = ("SerialNumber", "Ref_Id", "DefectCode")

def find_xlsx_files(pattern: str = DATA_PATTERN) -> List[Path]:
    return sorted(Path.cwd().glob(pattern))


def process_file(path: Path) -> pd.DataFrame:
    """Read *path*, collapse loops, classify, return final DataFrame."""
    # Read first sheet
    df = pd.read_excel(path, sheet_name=0)

    # Identify keys and metadata
    base_keys = ["SerialNumber", "Ref_Id", "DefectCode"]
    skip_cols = set(base_keys + ["ReworkStatus"])
    meta_cols = [c for c in df.columns if c not in skip_cols]

    meta = (
        df.groupby(base_keys, dropna=False)[meta_cols]
        .first()
        .reset_index()
    )

    # Count dispositions
    grp = (
        df.groupby(base_keys + ["ReworkStatus"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    for col in ["False call", "Overridden", "Reworkable"]:
        if col not in grp:
            grp[col] = 0

    grp["Outcome"] = grp.apply(classify, axis=1)
    final = grp[grp["Outcome"] != "None"].merge(meta, on=base_keys, how="left")
    return final


def ensure_table(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    cur = conn.cursor()
    # Create table if it doesn’t exist (dynamic columns)
    columns_sql = ", ".join(
        [
            *(f"`{pk}` TEXT" for pk in PRIMARY_KEY),
            *(
                f"`{col}` TEXT" if df[col].dtype == "O" else f"`{col}` REAL"
                for col in df.columns
                if col not in PRIMARY_KEY
            ),
            f"PRIMARY KEY ({', '.join(PRIMARY_KEY)})"
        ]
    )
    cur.execute(f"CREATE TABLE IF NOT EXISTS defects ({columns_sql});")

    # Add any missing columns
    cur.execute("PRAGMA table_info(defects);")
    existing_cols = {row[1] for row in cur.fetchall()}
    for col in df.columns:
        if col not in existing_cols:
            col_type = "TEXT" if df[col].dtype == "O" else "REAL"
            cur.execute(f"ALTER TABLE defects ADD COLUMN `{col}` {col_type};")

    conn.commit()


def upsert_df(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    cols = df.columns.tolist()
    placeholders = ",".join(["?"] * len(cols))
    col_names_sql = ",".join(f"`{c}`" for c in cols)
    sql = f"INSERT OR REPLACE INTO defects ({col_names_sql}) VALUES ({placeholders});"
    conn.executemany(sql, df.values.tolist())
    conn.commit()


def main(paths: List[Path]) -> None:
    if not paths:
        paths = find_xlsx_files()
        if not paths:
            print("[WARN] No Excel files found to process.")
            return

    print(f"[INFO] Processing {len(paths)} file(s)…")

    with sqlite3.connect(DB_PATH) as conn:
        for p in paths:
            print(f"  → {p.name}")
            df = process_file(p)
            ensure_table(conn, df)
            upsert_df(conn, df)

    print(f"[DONE] Database updated: {DB_PATH.resolve()}")


if __name__ == "__main__":
    files = [Path(x) for x in sys.argv[1:]]
    main(files) 