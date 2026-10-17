import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from urllib.parse import quote_plus
from models import (
    DailyOperations,
    DriverAbsenteeism,
    DriverDetails,
    ServiceMaster,
)
from db_config import Base  # Ensure same Base used for model definitions


# ------------------------------------------------------------
# 1️⃣ Create SQLAlchemy Engine (Safe for Special Characters)
# ------------------------------------------------------------
def get_mysql_engine(config):
    """Create SQLAlchemy engine safely from config.json."""
    try:
        db_conf = config["db"]

        # Encode password safely (important if it contains '@', '#', '$', etc.)
        encoded_password = quote_plus(db_conf["password"])

        conn_url = (
            f"mysql+mysqlconnector://{db_conf['user']}:{encoded_password}"
            f"@{db_conf['host']}/{db_conf['database']}"
        )

        engine = create_engine(conn_url, pool_pre_ping=True)
        st.success("✅ Database connection established successfully.")
        return engine

    except Exception as e:
        st.error(f"❌ Failed to create SQLAlchemy engine: {e}")
        return None


# ------------------------------------------------------------
# 2️⃣ CHUNKED ORM INSERT — FIXES MySQL 2055 Connection Lost
# ------------------------------------------------------------
def insert_to_mysql(engine, df: pd.DataFrame, table_name: str, chunk_size=5000):
    """
    Inserts pandas DataFrame into MySQL in safe chunks.
    Prevents MySQL 'Lost connection' (2055) due to huge bulk inserts.
    Strict Mode: Blocks insertion if missing values exist.
    """

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Map table_name → ORM model class
    table_map = {
        "daily_operations": DailyOperations,
        "driver_absenteeism": DriverAbsenteeism,
        "driver_details": DriverDetails,
        "service_master": ServiceMaster,
    }

    orm_class = table_map.get(table_name)
    if orm_class is None:
        st.error(f"⚠ No ORM model found for table: {table_name}")
        session.close()
        return

    # ------------------------------------------------------------
    # 🔍 Step 1: Validate for NaN / Null values
    # ------------------------------------------------------------
    nan_mask = df.isna()

    if nan_mask.any().any():
        st.error("❌ Missing values found in transformed data:")

        # Show column → rows having NaN
        for col in df.columns:
            missing_rows = nan_mask.index[nan_mask[col]].tolist()
            if missing_rows:
                st.markdown(f"- *Column:* `{col}` → Missing rows: {missing_rows[:10]}{' ...' if len(missing_rows) > 10 else ''}")

        st.warning("🚫 Data load aborted. Fix missing values and re-transform the CSV.")
        session.close()
        st.stop()

    # ------------------------------------------------------------
    # 🔥 Step 2: Clean DataFrame → Insert in Chunks Using bulk_insert_mappings
    # ------------------------------------------------------------
    try:
        total_rows = len(df)
        st.info(f"📦 Total rows to insert: {total_rows}")

        for start in range(0, total_rows, chunk_size):
            end = start + chunk_size
            chunk = df.iloc[start:end]

            # Convert chunk to list of dicts (ORM bulk insert compatible)
            records = chunk.to_dict(orient="records")

            # Insert this chunk
            session.bulk_insert_mappings(orm_class, records)
            session.commit()

            st.success(f"✅ Inserted rows {start + 1} → {min(end, total_rows)}")

        st.success(f"🎉 All {total_rows} rows inserted into `{table_name}` successfully.")

    except SQLAlchemyError as e:
        session.rollback()
        st.error(f"❌ ORM insert failed: {str(e)}")

    finally:
        session.close()
