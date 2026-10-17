from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import json

# ============================================================
# TARGET DATE
# ============================================================

TARGET_DATE = "2026-05-19"

# ============================================================
# AUTO FIND PROJECT ROOT
# ============================================================

HERE = Path(__file__).resolve().parent

SEARCH_ROOTS = [
    HERE.parent.parent.parent,
    HERE.parent.parent,
    HERE.parent,
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
    raise FileNotFoundError("config.json not found")

print(f"\nFOUND CONFIG: {CONFIG_PATH}")

# ============================================================
# BASE DIR
# ============================================================

if (PROJECT_ROOT / "dynamic_scheduling_master").exists():

    BASE_DIR = PROJECT_ROOT / "dynamic_scheduling_master"

else:

    BASE_DIR = PROJECT_ROOT

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

# ============================================================
# DB CONNECTION
# ============================================================

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

DB = cfg.get("db", cfg)

password = quote_plus(DB["password"])

engine = create_engine(
    f"mysql+mysqlconnector://{DB['user']}:{password}"
    f"@{DB['host']}:{DB.get('port',3306)}/{DB['database']}"
)

# ============================================================
# HELPERS
# ============================================================

def check_parquet(parquet_path, date_column):

    print(f"\nCHECKING: {parquet_path.name}")

    if not parquet_path.exists():

        print("FILE NOT FOUND")
        return

    try:

        df = pd.read_parquet(parquet_path)

        if date_column not in df.columns:

            print(f"DATE COLUMN '{date_column}' NOT FOUND")
            return

        df[date_column] = pd.to_datetime(
            df[date_column],
            errors="coerce"
        )

        check = df[
            df[date_column]
            .dt
            .strftime("%Y-%m-%d")
            == TARGET_DATE
        ]

        print(f"ROWS FOUND: {len(check)}")

        if len(check) > 0:
            print(check.head())

    except Exception as e:

        print(f"ERROR: {e}")

# ============================================================
# START CHECKING
# ============================================================

print("\n===================================")
print(f"CHECKING ALL DATA FOR {TARGET_DATE}")
print("===================================\n")

# ============================================================
# MYSQL
# ============================================================

print("\n===================================")
print("MYSQL TABLES")
print("===================================")

try:

    with engine.begin() as conn:

        result1 = conn.execute(text(f"""
            SELECT COUNT(*) 
            FROM ops_daily_raw
            WHERE date = '{TARGET_DATE}'
        """))

        count1 = list(result1)[0][0]

        print(f"\nops_daily_raw -> {count1} rows")

        result2 = conn.execute(text(f"""
            SELECT COUNT(*) 
            FROM ops_daily_service_raw
            WHERE date = '{TARGET_DATE}'
        """))

        count2 = list(result2)[0][0]

        print(f"ops_daily_service_raw -> {count2} rows")

except Exception as e:

    print(f"MYSQL ERROR: {e}")

# ============================================================
# PARQUETS
# ============================================================

print("\n===================================")
print("PARQUET FILES")
print("===================================")

processed_dir = DATA_DIR / "processed"

check_parquet(
    processed_dir / "ops_daily_gold.parquet",
    "date"
)

check_parquet(
    processed_dir / "ops_daily_service_gold.parquet",
    "date"
)

check_parquet(
    OUTPUT_DIR / "predictions" / "daily_predictions.parquet",
    "prediction_date"
)

# ============================================================
# SERVICE GOLD FOLDER
# ============================================================

print("\n===================================")
print("SERVICE GOLD FOLDER")
print("===================================")

service_gold_folder = (
    processed_dir
    / "service_gold"
    / TARGET_DATE
)

print(
    f"EXISTS: {service_gold_folder.exists()}"
)

# ============================================================
# DYNAMIC SCHEDULE FOLDER
# ============================================================

print("\n===================================")
print("DYNAMIC SCHEDULE FOLDER")
print("===================================")

schedule_folder = (
    OUTPUT_DIR
    / "dynamic_schedule"
    / TARGET_DATE
)

print(
    f"EXISTS: {schedule_folder.exists()}"
)

# ============================================================
# INBOUND FILES
# ============================================================

print("\n===================================")
print("INBOUND FILES")
print("===================================")

inbound_dir = DATA_DIR / "inbound_daily"

inbound_files = list(
    inbound_dir.glob(f"*{TARGET_DATE}*")
)

print(f"FILES FOUND: {len(inbound_files)}")

for f in inbound_files:
    print(f.name)

# ============================================================
# ARCHIVE FILES
# ============================================================

print("\n===================================")
print("ARCHIVE FILES")
print("===================================")

archive_dir = (
    DATA_DIR
    / "archive"
    / "inbound_daily"
)

archive_files = list(
    archive_dir.glob(f"*{TARGET_DATE}*")
)

print(f"FILES FOUND: {len(archive_files)}")

for f in archive_files:
    print(f.name)

# ============================================================
# FINAL STATUS
# ============================================================

print("\n===================================")
print("FINAL STATUS")
print("===================================\n")

issues = []

if count1 > 0:
    issues.append("ops_daily_raw")

if count2 > 0:
    issues.append("ops_daily_service_raw")

if service_gold_folder.exists():
    issues.append("service_gold folder")

if schedule_folder.exists():
    issues.append("dynamic_schedule folder")

if len(inbound_files) > 0:
    issues.append("inbound files")

if len(archive_files) > 0:
    issues.append("archive files")

if len(issues) == 0:

    print("SUCCESS")
    print(f"ALL DATA FOR {TARGET_DATE} IS FULLY DELETED")

else:

    print("NOT FULLY DELETED")
    print("\nRemaining data found in:\n")

    for i in issues:
        print(f"- {i}")

print("\n===================================\n")
