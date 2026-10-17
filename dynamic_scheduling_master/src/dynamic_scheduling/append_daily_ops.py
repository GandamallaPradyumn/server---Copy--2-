"""
append_daily_ops.py
--------------------
Loads a single day's raw ops CSV and appends it to the gold parquet.
Handles:
  - Large files (>50MB) via chunked reading
  - Unix ms timestamps and regular date strings
  - Revenue stored as string
  - Duplicate date rows (drops existing rows for that date before appending)
  - null actual_trips
  - dtype mismatch between existing parquet and new CSV
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# ✏️  SET THESE TWO PATHS BEFORE RUNNING
# ---------------------------------------------------------------------------

RAW_CSV_PATH = Path(r"/home/git/server/dynamic_scheduling_master/data/inbound_daily/ops_daily_service_2026-05-10.csv")
PARQUET_PATH = Path(r"/home/git/server/dynamic_scheduling_master/data/processed/ops_daily_service_gold.parquet")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHUNKSIZE   = 50_000
TARGET_DATE = "2026-05-10"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date_column(series: pd.Series) -> pd.Series:
    sample = series.dropna().iloc[0] if len(series.dropna()) > 0 else None
    if sample is not None:
        try:
            val = float(str(sample))
            if val > 1e10:
                return pd.to_datetime(series, unit="ms", errors="coerce")
        except (ValueError, TypeError):
            pass
    return pd.to_datetime(series, errors="coerce", dayfirst=False)


def clean_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    chunk = chunk.copy()
    if "date" in chunk.columns:
        chunk["date"] = parse_date_column(chunk["date"])
    force_numeric = [
        "actual_kms", "actual_trips", "seat_kms",
        "passenger_kms", "occupancy_ratio", "revenue",
        "marriage_day", "moudyami_day", "fes_hol_code", "is_fes_hol",
    ]
    for col in force_numeric:
        if col in chunk.columns:
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce")
    if "actual_trips" in chunk.columns:
        chunk["actual_trips"] = chunk["actual_trips"].fillna(0)
    for col in ["depot", "service_number"]:
        if col in chunk.columns:
            chunk[col] = chunk[col].astype(str).str.strip()
    return chunk


def align_dtypes(existing: pd.DataFrame, new_data: pd.DataFrame) -> tuple:
    """
    Align dtypes between existing parquet and new CSV so concat
    does not produce mixed-type columns that break Arrow serialization.
    """
    for col in existing.columns:
        if col not in new_data.columns:
            continue
        ex_dtype = existing[col].dtype
        nw_dtype = new_data[col].dtype

        if ex_dtype == nw_dtype:
            continue

        try:
            if pd.api.types.is_datetime64_any_dtype(ex_dtype):
                new_data[col] = pd.to_datetime(new_data[col], errors="coerce")

            elif hasattr(pd.api.types, 'is_categorical_dtype') and pd.api.types.is_categorical_dtype(ex_dtype):
                existing[col] = existing[col].astype(str)
                new_data[col] = new_data[col].astype(str)

            elif pd.api.types.is_float_dtype(ex_dtype):
                new_data[col] = pd.to_numeric(new_data[col], errors="coerce").astype(ex_dtype)

            elif pd.api.types.is_integer_dtype(ex_dtype):
                new_data[col] = pd.to_numeric(new_data[col], errors="coerce")
                if not new_data[col].isna().any():
                    new_data[col] = new_data[col].astype(ex_dtype)
                else:
                    # NaNs present — cast both to float (int can't hold NaN)
                    existing[col] = existing[col].astype(float)
                    new_data[col] = new_data[col].astype(float)

            else:
                existing[col] = existing[col].astype(str)
                new_data[col] = new_data[col].astype(str)

        except Exception as e:
            print(f"  ⚠️  Could not align '{col}' ({ex_dtype} vs {nw_dtype}): {e}")
            print(f"      Falling back to object for '{col}'")
            existing[col] = existing[col].astype(object)
            new_data[col] = new_data[col].astype(object)

    return existing, new_data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"RAW CSV  : {RAW_CSV_PATH}")
    print(f"PARQUET  : {PARQUET_PATH}")
    print(f"Target date: {TARGET_DATE}\n")

    if not RAW_CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found: {RAW_CSV_PATH}")

    file_mb = RAW_CSV_PATH.stat().st_size / (1024 * 1024)
    print(f"CSV file size : {file_mb:.1f} MB")
    print(f"Reading in chunks of {CHUNKSIZE:,} rows...\n")

    # --- Load CSV ---
    chunks = []
    for i, chunk in enumerate(pd.read_csv(RAW_CSV_PATH, chunksize=CHUNKSIZE, low_memory=False)):
        chunk = clean_chunk(chunk)
        chunks.append(chunk)
        print(f"  Chunk {i+1}: {len(chunk):,} rows loaded")

    new_data = pd.concat(chunks, ignore_index=True)
    print(f"\nTotal rows loaded from CSV : {len(new_data):,}")

    if "date" in new_data.columns:
        print(f"Dates found in CSV         : {sorted(new_data['date'].dt.date.unique())}")

    # --- Load existing parquet ---
    if PARQUET_PATH.exists():
        print(f"\nLoading existing parquet...")
        existing = pd.read_parquet(PARQUET_PATH)
        print(f"Existing parquet rows      : {len(existing):,}")

        if "date" in existing.columns:
            target_ts = pd.Timestamp(TARGET_DATE)
            before_drop = len(existing)
            existing = existing[existing["date"].dt.date != target_ts.date()].copy()
            dropped = before_drop - len(existing)
            if dropped > 0:
                print(f"Dropped {dropped:,} existing rows for {TARGET_DATE} (replacing with new data)")
            else:
                print(f"No existing rows found for {TARGET_DATE} — clean append")

        # --- Align dtypes ---
        print("\nAligning column dtypes...")
        existing, new_data = align_dtypes(existing, new_data)

        combined = pd.concat([existing, new_data], ignore_index=True)
    else:
        print(f"\nNo existing parquet found — creating new file")
        combined = new_data

    # --- Sort ---
    if "date" in combined.columns:
        combined = combined.sort_values(
            ["date", "depot", "service_number"]
        ).reset_index(drop=True)

    # --- Save ---
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving parquet...")
    combined.to_parquet(PARQUET_PATH, compression="snappy", index=False)

    print(f"\n✅ Done.")
    print(f"   New rows appended         : {len(new_data):,}")
    print(f"   Total parquet rows now    : {len(combined):,}")
    print(f"   Saved to                  : {PARQUET_PATH}")

    # --- Sanity check ---
    if "date" in combined.columns:
        sample = combined[combined["date"].dt.date == pd.Timestamp(TARGET_DATE).date()]
        print(f"\n--- Sanity check: {TARGET_DATE} ---")
        print(f"   Rows for date             : {len(sample):,}")
        cols = [c for c in ["depot","service_number","date","actual_kms","passenger_kms","occupancy_ratio","revenue"] if c in sample.columns]
        print(sample[cols].head(3).to_string(index=False))


if __name__ == "__main__":
    main()
