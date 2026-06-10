"""
create_tables.py — TGSRTC ops RAW master table setup
=====================================================

Run this ONCE to create the two tables in your existing MySQL database:
    ops_daily_raw          (depot-level daily data)
    ops_daily_service_raw  (service-level daily data)

Usage:
    python create_tables.py              # create tables + verify
    python create_tables.py --drop-first # ⚠ DROP then recreate (data loss!)

Reads DB credentials from config.json automatically.
"""

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load DB config from config.json
# ---------------------------------------------------------------------------

def load_config() -> dict:
    here = Path(__file__).resolve().parent
    search_paths = [
        here.parent.parent.parent / "config.json",   # server/  <- 3 levels up (correct)
        here.parent.parent / "config.json",           # dynamic_scheduling_master/
        here.parent / "config.json",                  # src/
        here / "config.json",                         # same folder as create_tables.py
    ]
    for p in search_paths:
        if p.exists():
            print(f"  ✓ Found config.json at: {p}")
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    print("  ✗ config.json not found. Searched:")
    for p in search_paths:
        print(f"      {p}")
    sys.exit(1)


def get_connection(db_cfg: dict):
    try:
        import mysql.connector
    except ImportError:
        print("  ✗ mysql-connector-python not installed.")
        print("    Run: pip install mysql-connector-python sqlalchemy")
        sys.exit(1)

    cfg = db_cfg.get("db", db_cfg)   # support both {"db": {...}} and flat dict
    conn = mysql.connector.connect(
        host     = cfg.get("host", "localhost"),
        port     = int(cfg.get("port", 3306)),
        database = cfg["database"],
        user     = cfg["user"],
        password = cfg["password"],
        charset  = cfg.get("charset", "utf8mb4"),
        autocommit = False,
    )
    return conn


# ---------------------------------------------------------------------------
# DDL statements
# ---------------------------------------------------------------------------

DDL_DEPOT = """
CREATE TABLE IF NOT EXISTS `ops_daily_raw` (
    `depot`              VARCHAR(100)   NOT NULL  COMMENT 'Depot name/code',
    `date`               DATE           NOT NULL  COMMENT 'Operational date',
    `passengers_per_day` DOUBLE                   COMMENT 'Total passengers carried',
    `actual_kms`         DOUBLE                   COMMENT 'Actual kilometres operated',
    `occupancy_ratio`    DOUBLE                   COMMENT 'Occupancy ratio (0‑2.0)',
    PRIMARY KEY (`depot`, `date`),
    INDEX `idx_date`  (`date`),
    INDEX `idx_depot` (`depot`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COMMENT='Depot-level daily operations RAW master (replaces ops_daily_master.csv)';
"""

DDL_SERVICE = """
CREATE TABLE IF NOT EXISTS `ops_daily_service_raw` (
    `depot`            VARCHAR(100)   NOT NULL  COMMENT 'Depot name/code',
    `date`             DATE           NOT NULL  COMMENT 'Operational date',
    `service_number`   VARCHAR(100)   NOT NULL  COMMENT 'Service/bus number',
    `actual_kms`       DOUBLE                   COMMENT 'Actual kilometres for this service',
    `actual_trips`     DOUBLE                   COMMENT 'Number of trips operated',
    `seat_kms`         DOUBLE                   COMMENT 'Seat-kilometres (capacity × kms)',
    `passenger_kms`    DOUBLE                   COMMENT 'Passenger-kilometres (PKM)',
    `occupancy_ratio`  DOUBLE                   COMMENT 'Occupancy ratio (0‑3.0)',
    `revenue`          DOUBLE                   COMMENT 'Revenue collected (₹)',
    PRIMARY KEY (`depot`, `date`, `service_number`),
    INDEX `idx_date`         (`date`),
    INDEX `idx_depot`        (`depot`),
    INDEX `idx_depot_date`   (`depot`, `date`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COMMENT='Service-level daily operations RAW master (replaces ops_daily_service_master.csv)';
"""

DROP_DEPOT   = "DROP TABLE IF EXISTS `ops_daily_raw`;"
DROP_SERVICE = "DROP TABLE IF EXISTS `ops_daily_service_raw`;"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_ddl(cursor, statement: str, label: str) -> bool:
    try:
        cursor.execute(statement)
        print(f"  ✓ {label}")
        return True
    except Exception as e:
        print(f"  ✗ {label} — {e}")
        return False


def verify_tables(cursor) -> None:
    print("\n── Verification ─────────────────────────────────────")
    for table in ("ops_daily_raw", "ops_daily_service_raw"):
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = cursor.fetchall()
        print(f"\n  Table: {table}  ({len(cols)} columns)")
        for col in cols:
            name, col_type, null, key, default, extra = col[:6]
            pk_flag  = " [PK]"  if key  == "PRI" else ""
            idx_flag = " [IDX]" if key  == "MUL" else ""
            print(f"    • {name:<22} {col_type:<20}{pk_flag}{idx_flag}")

        cursor.execute(f"SHOW INDEX FROM `{table}`")
        indexes = cursor.fetchall()
        index_names = sorted({r[2] for r in indexes})
        print(f"  Indexes: {', '.join(index_names)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Create TGSRTC ops RAW master tables in MySQL.")
    parser.add_argument(
        "--drop-first",
        action="store_true",
        help="⚠ DROP existing tables before recreating (destroys all data!)",
    )
    args = parser.parse_args()

    print("\n═══════════════════════════════════════════════════════")
    print("  TGSRTC — Create RAW master tables in MySQL")
    print("═══════════════════════════════════════════════════════\n")

    # 1. Load config
    print("── Loading config ────────────────────────────────────")
    config = load_config()
    db_cfg = config.get("db", config)
    print(f"  Database : {db_cfg['database']}")
    print(f"  Host     : {db_cfg.get('host', 'localhost')}:{db_cfg.get('port', 3306)}")
    print(f"  User     : {db_cfg['user']}")

    # 2. Connect
    print("\n── Connecting ────────────────────────────────────────")
    try:
        conn = get_connection(config)
        cursor = conn.cursor()
        print(f"  ✓ Connected to `{db_cfg['database']}`")
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        sys.exit(1)

    # 3. Optionally drop
    if args.drop_first:
        print("\n── ⚠ Dropping existing tables ───────────────────────")
        confirm = input("  This will DELETE ALL DATA. Type YES to continue: ").strip()
        if confirm != "YES":
            print("  Aborted.")
            sys.exit(0)
        run_ddl(cursor, DROP_SERVICE, "DROP ops_daily_service_raw")
        run_ddl(cursor, DROP_DEPOT,   "DROP ops_daily_raw")
        conn.commit()

    # 4. Create tables
    print("\n── Creating tables ───────────────────────────────────")
    ok1 = run_ddl(cursor, DDL_DEPOT,   "CREATE ops_daily_raw")
    ok2 = run_ddl(cursor, DDL_SERVICE, "CREATE ops_daily_service_raw")
    conn.commit()

    if not (ok1 and ok2):
        print("\n  Some tables failed to create. Check errors above.")
        sys.exit(1)

    # 5. Verify
    verify_tables(cursor)

    cursor.close()
    conn.close()

    print("\n═══════════════════════════════════════════════════════")
    print("  Done. Tables are ready.")
    print("  Next step: run migrate_csv_to_db() in data_pipeline.py")
    print("  to load your existing CSV data into the new tables.")
    print("═══════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
