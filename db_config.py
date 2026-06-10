# db_config.py
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session
from contextlib import contextmanager
import urllib.parse
import re
import sys

# ------------------------------
# Load Configuration
# ------------------------------
try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    sys.exit("❌ ERROR: config.json not found. Please create it in the project root.")

db = config.get("db", {})
host = db.get("host", "localhost")
user = db.get("user", "")
password = db.get("password", "")
database = db.get("database", "")

# ------------------------------
# 🧠 Smart Host Correction
# ------------------------------
# Detect wrong pattern like "9347@localhost" → should be "localhost"
if "@" in host and not host.endswith("localhost"):
    print(f"⚠️ Detected malformed host value '{host}'. Auto-correcting to 'localhost'.")
    host = "localhost"

# 🧠 Ensure password special characters are URL-safe (for @, #, etc.)
encoded_password = urllib.parse.quote_plus(password)

# ------------------------------
# Database URL
# ------------------------------
DATABASE_URL = f"mysql+pymysql://{user}:{encoded_password}@{host}/{database}?charset=utf8mb4"

# ------------------------------
# Engine & Session
# ------------------------------
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,  # Set True for debugging SQL queries
    pool_recycle=3600
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
SessionLocal = scoped_session(SessionFactory)

# ------------------------------
# Base Class for ORM Models
# ------------------------------
Base = declarative_base()

# ------------------------------
# Context Manager for Safe Sessions
# ------------------------------
@contextmanager
def get_session():
    """
    Provides a transactional scope for ORM operations.

    Usage:
        with get_session() as db:
            results = db.query(ActionPlan).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        print("❌ DB Transaction Error:", e)
        raise
    finally:
        db.close()

# ------------------------------
# Initialize Database (if needed)
# ------------------------------
def init_db():
    """Create all ORM tables if they don't exist."""
    import models  # Ensures all models are loaded
    Base.metadata.create_all(bind=engine)
    print("✅ All tables verified/created successfully.")

# ------------------------------
# Test Connection Utility
# ------------------------------
def test_connection():
    print(f"🔍 Testing database connection for '{user}' on '{database}'...")
    try:
        conn = engine.connect()
        print(f"✅ Connected successfully as {user}@{host}")
        conn.close()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)

# ------------------------------
# Run directly to test
# ------------------------------
if __name__ == "__main__":
    test_connection()
    init_db()
