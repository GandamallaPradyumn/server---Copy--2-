from pathlib import Path
import pandas as pd
import shutil
import json
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

# ============================================================
# CONFIG
# ============================================================

TARGET_DATE = "2026-05-06"

# ============================================================
# AUTO-DETECT PROJECT ROOT
# ============================================================

HERE = Path(__file__).resolve().parent

SEARCH_ROOTS = [
    HERE.parent.parent.parent,   # server root
    HERE.parent.parent,          # dynamic_scheduling_master
    HERE.parent,                 # src
    HERE,
]

PROJECT_ROOT = None
CONFIG_PATH = None

for p in SEARCH_ROOTS:
    cfg = p / "config.json"
    if cfg.exists():
        PROJECT_ROOT = p
        CONFIG_PATH = cfg
        break

if CONFIG_PATH is None:
    raise FileNotFoundError(
        "config.json not found in any expected location"
    )

print(f"\nFOUND CONFIG: {CONFIG_PATH}")

# ============================================================
# PATHS
# ============================================================

# Handle both project structures safely
if (PROJECT_ROOT / "dynamic_scheduling_master").exists():

    BASE_DIR = PROJECT_ROOT / "dynamic_scheduling_master"

else:

    BASE_DIR = PROJECT_ROOT

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

# ============================================================
# LOAD DB CONFIG
# ============================================================

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

DB = cfg.get("db", cfg)

password = quote_plus(DB["password"])

engine = create_engine(
    f"mysql+mysqlconnector://{DB['user']}:{password}"
    f"@{DB['host']}:{DB.get('port',3306)}/{DB['database']}"
)

print(f"\nDeleting ALL records for: {TARGET_DATE}\n")

# ============================================================
# HELPERS
# ============================================================

def clean_parquet(parquet_path, date_column):

    if not parquet_path.exists():
        print(f"SKIP (not found): {parquet_path}")
        return

    try:

        df = pd.read_parquet(parquet_path)

        if date_column not in df.columns:
            print(
                f"SKIP: column '{date_column}' not found in "
                f"{parquet_path.name}"
            )
            return

        before = len(df)

        df[date_column] = pd.to_datetime(
            df[date_column],
            errors="coerce"
        )

        df = df[
            df[date_column]
            .dt
            .strftime("%Y-%m-%d") != TARGET_DATE
        ]

        removed = before - len(df)

        df.to_parquet(parquet_path, index=False)

        print(
            f"UPDATED: {parquet_path.name} "
            f"-> Removed {removed} rows"
        )

    except Exception as e:

        print(f"ERROR cleaning parquet {parquet_path}: {e}")


def delete_matching_files(folder, pattern):

    if not folder.exists():
        print(f"SKIP folder not found: {folder}")
        return

    files = list(folder.glob(pattern))

    if not files:
        print(f"No matching files in: {folder}")
        return

    for f in files:

        try:
            if f.is_file():
                f.unlink()
                print(f"DELETED FILE: {f.name}")

            elif f.is_dir():
                shutil.rmtree(f)
                print(f"DELETED FOLDER: {f.name}")

        except Exception as e:
            print(f"ERROR deleting {f}: {e}")

# ============================================================
# 1. MYSQL CLEANUP
# ============================================================

print("\n===================================")
print("MYSQL RAW TABLE CLEANUP")
print("===================================\n")

try:

    with engine.begin() as conn:

        result1 = conn.execute(text("""
            DELETE FROM ops_daily_raw
            WHERE date = :dt
        """), {"dt": TARGET_DATE})

        print(
            f"ops_daily_raw "
            f"-> {result1.rowcount} rows deleted"
        )

        result2 = conn.execute(text("""
            DELETE FROM ops_daily_service_raw
            WHERE date = :dt
        """), {"dt": TARGET_DATE})

        print(
            f"ops_daily_service_raw "
            f"-> {result2.rowcount} rows deleted"
        )

except Exception as e:

    print(f"MYSQL ERROR: {e}")

# ============================================================
# 2. PROCESSED PARQUETS
# ============================================================

print("\n===================================")
print("PROCESSED PARQUET CLEANUP")
print("===================================\n")

processed_dir = DATA_DIR / "processed"

clean_parquet(
    processed_dir / "ops_daily_gold.parquet",
    "date"
)

clean_parquet(
    processed_dir / "ops_daily_service_gold.parquet",
    "date"
)

# ============================================================
# 3. SERVICE GOLD DAILY FOLDERS
# ============================================================

print("\n===================================")
print("SERVICE GOLD DAILY CLEANUP")
print("===================================\n")

service_gold_dir = processed_dir / "service_gold"

target_folder = service_gold_dir / TARGET_DATE

if target_folder.exists():

    shutil.rmtree(target_folder)

    print(f"DELETED: {target_folder}")

else:

    print("No service_gold target folder found")

# ============================================================
# 4. PREDICTIONS PARQUET
# ============================================================

print("\n===================================")
print("PREDICTIONS CLEANUP")
print("===================================\n")

predictions_path = (
    OUTPUT_DIR
    / "predictions"
    / "daily_predictions.parquet"
)

clean_parquet(
    predictions_path,
    "prediction_date"
)

# ============================================================
# 5. DYNAMIC SCHEDULE OUTPUTS
# ============================================================

print("\n===================================")
print("DYNAMIC SCHEDULE CLEANUP")
print("===================================\n")

schedule_dir = OUTPUT_DIR / "dynamic_schedule"

target_schedule_folder = schedule_dir / TARGET_DATE

if target_schedule_folder.exists():

    shutil.rmtree(target_schedule_folder)

    print(f"DELETED: {target_schedule_folder}")

else:

    print("No dynamic schedule folder found")

# ============================================================
# 6. INBOUND FILES
# ============================================================

print("\n===================================")
print("INBOUND FILE CLEANUP")
print("===================================\n")

inbound_dir = DATA_DIR / "inbound_daily"

delete_matching_files(
    inbound_dir,
    f"*{TARGET_DATE}*"
)

# ============================================================
# 7. ARCHIVE FILES
# ============================================================

print("\n===================================")
print("ARCHIVE FILE CLEANUP")
print("===================================\n")

archive_dir = DATA_DIR / "archive" / "inbound_daily"

delete_matching_files(
    archive_dir,
    f"*{TARGET_DATE}*"
)

# ============================================================
# 8. LOG CLEANUP
# ============================================================

print("\n===================================")
print("LOG CLEANUP")
print("===================================\n")

logs_dir = DATA_DIR / "logs"

for log_file in [

    logs_dir / "ingest_log.csv",
    logs_dir / "ingest_errors.csv",

]:

    if not log_file.exists():
        continue

    try:

        df = pd.read_csv(log_file)

        before = len(df)

        cols_lower = [c.lower() for c in df.columns]

        if "date" in cols_lower:

            date_col = df.columns[
                cols_lower.index("date")
            ]

            df[date_col] = pd.to_datetime(
                df[date_col],
                errors="coerce"
            )

            df = df[
                df[date_col]
                .dt
                .strftime("%Y-%m-%d") != TARGET_DATE
            ]

            removed = before - len(df)

            df.to_csv(log_file, index=False)

            print(
                f"UPDATED: {log_file.name} "
                f"-> Removed {removed} rows"
            )

    except Exception as e:

        print(f"ERROR cleaning {log_file}: {e}")

# ============================================================
# COMPLETE
# ============================================================

print("\n===================================")
print(f"SUCCESSFULLY REMOVED: {TARGET_DATE}")
print("===================================\n")
