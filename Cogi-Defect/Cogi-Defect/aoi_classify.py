#!/usr/bin/env python3
"""
aoi_classify.py
---------------
Classify AOI defects into four outcome buckets (Real, Fixed, Suspect, False)
for every SerialNumber + Ref_Id + DefectCode combination.

Usage
-----
$ python aoi_classify.py "Defect RawData - 2025-07-26T151030.489.xlsx" out.xlsx

If no arguments are supplied, it defaults to:
    src = "Defect RawData.xlsx"
    dst = "AOI_defect_status.xlsx"

This script mirrors the logic discussed:
    • False   – any "False call" row present (operator cleared it)
    • Fixed from previously caught
                – no Reworkable rows and at least one Overridden row (machine now misses it)
    • Suspect – Reworkable rows present, but no Overridden (awaiting review)
    • Real    – both Reworkable and Overridden rows present (confirmed defect)

The resulting table is written to *dst* and a tally is printed to stdout.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np  # noqa: F401 (imported for completeness, not strictly needed)
import pandas as pd


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def classify(row: pd.Series) -> str:
    """Return one of 4 outcomes for a Serial+Ref+DefectCode combo."""
    if row["False call"] > 0:
        return "False"          # operator said it's not a defect
    if row["Reworkable"] == 0 and row["Overridden"] > 0:
        return "Fixed from previously caught"  # previously bad → machine now misses it
    if row["Reworkable"] > 0 and row["Overridden"] == 0:
        return "Suspect"        # machine just flagged it, waiting review
    if row["Reworkable"] > 0 and row["Overridden"] > 0:
        return "Real"           # flagged + operator confirmed
    return "None"               # fallback (shouldn't happen)

# ---------------------------------------------------------------------------
# Utility: find latest export
# ---------------------------------------------------------------------------


def find_latest_rawdata(pattern: str = "Defect RawData - *.xlsx") -> str | None:
    """Return the newest XLSX matching *pattern* in CWD, or None if not found."""
    files = sorted(Path.cwd().glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main(src: str, dst: str) -> None:
    # 1) read first sheet (rename if yours is different)
    df = pd.read_excel(src, sheet_name=0)

    # Identify core keys and extra metadata columns to preserve
    base_keys = ["SerialNumber", "Ref_Id", "DefectCode"]
    skip_cols = set(base_keys + ["ReworkStatus"])  # columns we don’t want to copy blindly
    meta_cols = [c for c in df.columns if c not in skip_cols]

    # Collapse metadata (take *first* value per pad-defect combo)
    meta = (
        df.groupby(base_keys, dropna=False)[meta_cols]
        .first()
        .reset_index()
    )

    # 2) collapse all loops & dispositions into counts
    grp = (
        df.groupby([
            "SerialNumber",
            "Ref_Id",
            "DefectCode",
            "ReworkStatus",
        ], dropna=False)
        .size()
        .unstack(fill_value=0)        # → columns = False call / Overridden / Reworkable
        .reset_index()
    )

    # 3) ensure disposition columns exist even if absent in data
    for col in ["False call", "Overridden", "Reworkable"]:
        if col not in grp:
            grp[col] = 0

    # 4) assign the outcome
    grp["Outcome"] = grp.apply(classify, axis=1)

    # 5) drop rows classified as "None" (never happens, but tidy)
    final = grp[grp["Outcome"] != "None"].copy()

    # 6) merge back with metadata so downstream reporting keeps full context
    final = final.merge(meta, on=base_keys, how="left")

    # 7) save + quick console summary
    final.to_excel(dst, index=False)
    print("Written:", Path(dst).resolve())
    print("\nOutcome counts\n--------------")
    print(final["Outcome"].value_counts())


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Determine source & destination paths
    if len(sys.argv) > 1:
        src_file = sys.argv[1]
    else:
        src_file = find_latest_rawdata()
        if src_file is None:
            print(
                "[ERROR] No AOI export found in current directory. "
                "Please pass the XLSX as the first argument.",
                file=sys.stderr,
            )
            sys.exit(1)

    dst_file = sys.argv[2] if len(sys.argv) > 2 else "AOI_defect_status.xlsx"

    main(src_file, dst_file) 