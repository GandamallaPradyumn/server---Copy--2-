"""
Script to extract and analyze Predicted vs Actual CUT services for the KRMR (Karimnagar) Region.

Columns outputted:
- DEPOT
- DATE
- PREDICTED CUT COUNT
- PREDICTED CUT SERVICE NUMBERS
- ACTUAL CUT COUNT (Depot adhered to AI recommendation and did not operate)
- ACTUAL CUT SERVICE NUMBERS
- OPERATED ANYWAY COUNT (Depot overrode AI recommendation and operated the service)
- OPERATED ANYWAY SERVICE NUMBERS
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Check if inside server root or dynamic_scheduling_master
if os.path.exists(os.path.join(BASE_DIR, "dynamic_scheduling_master")):
    PROJECT_ROOT = os.path.join(BASE_DIR, "dynamic_scheduling_master")
else:
    PROJECT_ROOT = BASE_DIR

SCHEDULE_DIR = os.path.join(PROJECT_ROOT, "output", "dynamic_schedule")
GOLD_PATH = os.path.join(PROJECT_ROOT, "data", "processed", "ops_daily_service_gold.parquet")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ── 1. Fetch KRMR Depots (from DB TS_ADMIN or Fallback) ─────────────────────────
DEFAULT_KRMR_DEPOTS = [
    'KARIMNAGAR-I', 'KARIMNAGAR-II', 'HUZURABAD', 'GODAVARIKHANI',
    'MANTHANI', 'HUSNABAD', 'JAGITYAL', 'KORUTLA', 'METPALLY',
    'SIRCILLA', 'VEMULAWADA'
]

def get_krmr_depots():
    """Fetch depots for Karimnagar region from TS_ADMIN table if DB is available."""
    if os.path.exists(CONFIG_PATH):
        try:
            import pymysql
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f).get("db", {})
            conn = pymysql.connect(
                host=cfg.get("host", "localhost"),
                user=cfg.get("user", "root"),
                password=cfg.get("password", ""),
                database=cfg.get("database", "tgsrtc_new"),
                connect_timeout=3
            )
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT depot_name 
                FROM TS_ADMIN 
                WHERE UPPER(region) LIKE '%KARIM%' OR UPPER(region) LIKE '%KRMR%'
                ORDER BY depot_name
            """)
            rows = cur.fetchall()
            conn.close()
            if rows:
                return [r[0].strip().upper() for r in rows]
        except Exception:
            pass
    return DEFAULT_KRMR_DEPOTS

# ── 2. Main Extraction Function ────────────────────────────────────────────────
def analyze_krmr_cut_services(days=30, output_csv="krmr_cut_services_analysis.csv"):
    depots = get_krmr_depots()
    print(f"[*] Analyzing KRMR Region Depots ({len(depots)} depots):")
    print(", ".join(depots))

    # Check Schedule Directory
    if not os.path.exists(SCHEDULE_DIR):
        raise FileNotFoundError(f"Schedule directory not found at: {SCHEDULE_DIR}")

    # Check Gold Parquet
    if not os.path.exists(GOLD_PATH):
        raise FileNotFoundError(f"Gold actuals parquet not found at: {GOLD_PATH}")

    # 1. Load Gold Actuals
    print("\n[+] Loading actual operations data from gold parquet...")
    gold = pd.read_parquet(GOLD_PATH)
    gold.columns = [c.strip().lower() for c in gold.columns]
    gold['date'] = pd.to_datetime(gold['date']).dt.strftime('%Y-%m-%d')
    gold['service_number'] = gold['service_number'].astype(str).str.strip()
    gold['depot'] = gold['depot'].astype(str).str.upper().str.strip()
    gold['actual_kms'] = pd.to_numeric(gold['actual_kms'], errors='coerce').fillna(0)

    # 2. Get Available Schedule Dates
    all_dates = sorted([
        d for d in os.listdir(SCHEDULE_DIR) 
        if os.path.isdir(os.path.join(SCHEDULE_DIR, d)) and len(d) == 10 and d.startswith("20")
    ])

    if not all_dates:
        print("[-] No schedule date folders found.")
        return pd.DataFrame()

    # Determine last 1 month window based on latest available schedule date
    latest_date = pd.to_datetime(all_dates[-1])
    cutoff_date = (latest_date - timedelta(days=days)).strftime('%Y-%m-%d')
    selected_dates = [d for d in all_dates if d >= cutoff_date]

    print(f"[*] Schedule Date Range: {selected_dates[0]} to {selected_dates[-1]} ({len(selected_dates)} days)")

    records = []

    # 3. Process Each Date and Depot
    for date_str in selected_dates:
        for depot in depots:
            sched_file = os.path.join(SCHEDULE_DIR, date_str, f"epk_schedule_{depot}_{date_str}.xlsx")
            if not os.path.exists(sched_file):
                continue

            try:
                sched_df = pd.read_excel(sched_file)
                sched_df.columns = [c.strip().lower() for c in sched_df.columns]

                if 'action' not in sched_df.columns or 'service_number' not in sched_df.columns:
                    continue

                sched_df['service_number'] = sched_df['service_number'].astype(str).str.strip()

                # Filter services where AI predicted CUT
                cut_sched = sched_df[sched_df['action'].astype(str).str.upper().str.strip() == 'CUT'].copy()
                pred_cut_services = cut_sched['service_number'].tolist()
                pred_cut_count = len(pred_cut_services)

                # Filter actual operations for this depot on this date
                act_subset = gold[(gold['depot'] == depot) & (gold['date'] == date_str)]

                if len(act_subset) > 0:
                    # Services that actually operated (kms > 0)
                    operated_svcs = set(act_subset[act_subset['actual_kms'] > 0]['service_number'])

                    # Actual CUT: services predicted CUT that were NOT operated by depot
                    actual_cut_svcs = [s for s in pred_cut_services if s not in operated_svcs]
                    # Operated Anyway: services predicted CUT that depot operated anyway
                    operated_anyway_svcs = [s for s in pred_cut_services if s in operated_svcs]
                else:
                    # If actuals are not yet available for that date
                    actual_cut_svcs = []
                    operated_anyway_svcs = []

                # Add row to results
                records.append({
                    'DEPOT': depot,
                    'DATE': date_str,
                    'PREDICTED_CUT_COUNT': pred_cut_count,
                    'PREDICTED_CUT_SERVICES': ", ".join(pred_cut_services) if pred_cut_services else "None",
                    'ACTUAL_CUT_COUNT': len(actual_cut_svcs) if len(act_subset) > 0 else "Actuals Pending",
                    'ACTUAL_CUT_SERVICES': ", ".join(actual_cut_svcs) if actual_cut_svcs else ("None" if len(act_subset) > 0 else "Actuals Pending"),
                    'OPERATED_ANYWAY_COUNT': len(operated_anyway_svcs) if len(act_subset) > 0 else "Actuals Pending",
                    'OPERATED_ANYWAY_SERVICES': ", ".join(operated_anyway_svcs) if operated_anyway_svcs else ("None" if len(act_subset) > 0 else "Actuals Pending"),
                })

            except Exception as e:
                # Silently catch corrupt files or format mismatches
                continue

    result_df = pd.DataFrame(records)

    # Save to CSV
    if not result_df.empty:
        csv_path = os.path.join(BASE_DIR, output_csv)
        result_df.to_csv(csv_path, index=False)
        print(f"\n[+] Analysis complete! Saved {len(result_df)} records to: {csv_path}")

    return result_df

if __name__ == "__main__":
    df = analyze_krmr_cut_services(days=30)
    if not df.empty:
        # Display sample output
        print("\n--- SAMPLE OUTPUT (First 20 records) ---")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        print(df.head(20).to_string(index=False))
