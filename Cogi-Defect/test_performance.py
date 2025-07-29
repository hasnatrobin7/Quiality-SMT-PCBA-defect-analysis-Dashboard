#!/usr/bin/env python3
"""
Quick performance test for the AOI dashboard
"""
import time
import sqlite3
import pandas as pd
from pathlib import Path

def test_db_load():
    """Test database loading performance"""
    db_path = Path("aoi_defects.db")
    if not db_path.exists():
        print("Database not found - skipping test")
        return
    
    print("Testing database load performance...")
    start = time.time()
    
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql("SELECT * FROM defects", conn)
    
    load_time = time.time() - start
    print(f"✓ Loaded {len(df):,} rows in {load_time:.2f}s")
    
    # Test datetime processing
    start = time.time()
    datetime_cols = [c for c in df.columns 
                    if pd.api.types.is_datetime64_any_dtype(df[c]) or 
                    any(substr in c.lower() for substr in ["date", "time"])]
    for col in datetime_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    
    datetime_time = time.time() - start
    print(f"✓ Processed {len(datetime_cols)} datetime columns in {datetime_time:.2f}s")
    
    # Test unique value extraction
    start = time.time()
    unique_counts = {}
    for col in ["Outcome", "PartNumber", "ComponentPN", "SerialNumber", "Ref_Id"]:
        if col in df.columns:
            unique_counts[col] = len(df[col].dropna().unique())
    
    unique_time = time.time() - start
    print(f"✓ Extracted unique values in {unique_time:.2f}s")
    for col, count in unique_counts.items():
        print(f"  {col}: {count:,} unique values")
    
    total_time = load_time + datetime_time + unique_time
    print(f"\n📊 Total processing time: {total_time:.2f}s")
    
    if total_time > 5:
        print("⚠️  Performance may be slow - consider optimizations")
    else:
        print("✅ Performance looks good!")

if __name__ == "__main__":
    test_db_load() 