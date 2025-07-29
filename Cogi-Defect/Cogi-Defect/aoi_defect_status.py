#!/usr/bin/env python3
"""
aoi_defect_status.py
--------------------
Utility script to post-process AOI defect exports and assign a single
"Outcome" (Real, False, Suspect) to every SerialNumber + Ref_Id + DefectCode
combo, based on the following shop-floor logic:

    • False    – any "False call" row present (operator cleared the call)
    • Real     – no false call, but at least one "Overridden" row present
    • Suspect  – only "Reworkable" rows present (awaiting operator review)

Usage
-----
$ python aoi_defect_status.py [input_file.xlsx] [--sheet Defects] [--out AOI_defect_status.xlsx]

    input_file.xlsx   Path to the AOI export. Defaults to the most recent
                      "Defect RawData - *.xlsx" in the current directory.
    --sheet NAME      Sheet to load (default: "Defects").
    --out PATH        Output file path (default: AOI_defect_status.xlsx)

The script prints a small summary to stdout and writes the collapsed table
with an "Outcome" column to the chosen output Excel file.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REWORK_STATUS_COLUMNS = ["False call", "Overridden", "Reworkable"]


def find_latest_rawdata(pattern: str = "Defect RawData - *.xlsx") -> Path | None:
    """Return the newest XLSX matching *pattern* in CWD or None if not found."""
    files = sorted(Path.cwd().glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify AOI defects into Real / False / Suspect")
    parser.add_argument("input", nargs="?", help="Path to AOI defect export .xlsx")
    parser.add_argument("--sheet", default="Defects", help="Sheet name to load (default: %(default)s)")
    parser.add_argument("--out", default="AOI_defect_status.xlsx", help="Output Excel file (default: %(default)s)")
    return parser.parse_args()


def load_data(xlsx_path: Path, sheet_name: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
    except ValueError as e:
        print(f"[ERROR] {e}\nAvailable sheets: {pd.ExcelFile(xlsx_path).sheet_names}", file=sys.stderr)
        raise
    return df


def collapse_loops(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse multiple inspection loops into 1 row per Serial+Ref+DefectCode+Status."""
    tbl = (
        df.groupby(["SerialNumber", "Ref_Id", "DefectCode", "ReworkStatus"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    # Ensure all expected ReworkStatus columns exist
    for col in REWORK_STATUS_COLUMNS:
        if col not in tbl:
            tbl[col] = 0

    return tbl


def assign_outcome(tbl: pd.DataFrame) -> pd.DataFrame:
    tbl["Outcome"] = np.select(
        [tbl["False call"] > 0, tbl["Overridden"] > 0, tbl["Reworkable"] > 0],
        ["False", "Real", "Suspect"],
        default="None",
    )
    return tbl[tbl["Outcome"] != "None"].copy()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input) if args.input else find_latest_rawdata()
    if input_path is None or not input_path.exists():
        print("[ERROR] No input file provided and none matching pattern found.", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Loading '{input_path}' (sheet='{args.sheet}')…")
    raw = load_data(input_path, args.sheet)

    collapsed = collapse_loops(raw)
    status = assign_outcome(collapsed)

    print("[INFO] Outcome distribution:\n", status["Outcome"].value_counts().to_string())

    out_path = Path(args.out)
    status.to_excel(out_path, index=False)
    print(f"[INFO] Saved result to '{out_path}'.")


if __name__ == "__main__":
    main() 