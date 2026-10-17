# auth.py
import mysql.connector
import json
import hashlib
import secrets
import re
import bcrypt
from datetime import datetime, timedelta
import streamlit as st
from mysql.connector import Error
from pathlib import Path

# Load config.json reliably
config_path = Path(__file__).resolve().parent / "config.json"
if not config_path.exists():
    config_path = Path("config.json")

with open(config_path, encoding="utf-8") as f:
    config = json.load(f)

db_config = config["db"]

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# ---------- Password Hashing Helpers ----------
def hash_password(password: str) -> str:
    """Hashes a plain text password using bcrypt with salt."""
    salt = bcrypt.gensalt(12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, stored_hash_or_pw: str) -> bool:
    """Verifies a password against bcrypt, PBKDF2, or plain text."""
    if not password or not stored_hash_or_pw:
        return False
    try:
        if stored_hash_or_pw.startswith(("$2b$", "$2a$", "$2y$")):
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash_or_pw.encode('utf-8'))
        elif stored_hash_or_pw.startswith("pbkdf2_sha256$"):
            parts = stored_hash_or_pw.split("$")
            if len(parts) != 3:
                return False
            _, salt, expected_hash = parts
            computed_hash = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                100000
            ).hex()
            return secrets.compare_digest(computed_hash, expected_hash)
        else:
            return secrets.compare_digest(password, stored_hash_or_pw)
    except Exception as e:
        print("Password verification exception:", e)
        return False

# ---------- Input Sanitization & Validation Helpers ----------
def sanitize_input(input_val: str) -> str:
    """Sanitizes input text by trimming whitespace and stripping script tags and control characters."""
    if not isinstance(input_val, str):
        return ""
    # Strip HTML and script tags
    sanitized = re.sub(r'<[^>]*>', '', input_val)
    # Remove null bytes and control characters
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', sanitized)
    return sanitized.strip()

def validate_userid(userid: str) -> bool:
    """Validates User ID format (alphanumeric and special chars _@.-, length 3-30)."""
    if not userid:
        return False
    userid = sanitize_input(userid)
    if len(userid) < 3 or len(userid) > 30:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_@.-]+$", userid))


# ---------- Session helpers ----------
def is_authenticated():
    """
    Return True if the user is logged in.
    Keeps auth checks centralized so other modules can call auth.is_authenticated().
    """
    return bool(st.session_state.get("logged_in", False))

# DB Connection
def get_connection():
    return mysql.connector.connect(
        host=db_config["host"],
        user=db_config["user"],
        password=db_config["password"],
        database=db_config["database"]
    )

def fetch_depot_names():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT depot_name FROM TS_ADMIN")
        depot_list = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return depot_list
    except Exception as e:
        print("Error fetching depots:", e)
        return []

def get_depot_settings():
    """Fetches depot configuration settings from the TS_ADMIN table."""
    conn = get_connection()
    if conn is None:
        return {}
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM TS_ADMIN")
        rows = cursor.fetchall()
        return {row["depot_name"]: row for row in rows}
    except Error as e:
        st.error(f"Error fetching depot settings: {e}")
        return {}
    finally:
        if conn and conn.is_connected():
            conn.close()

# Ensure admin exists without modifying existing database passwords
def ensure_admin_exists():
    """Checks if admin account exists. Never overwrites existing DB passwords."""
    try:
        conn = get_connection()
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE userid = 'admin'")
        result = cursor.fetchone()

        # Only insert admin if it does NOT exist in the database yet
        if result and result[0] == 0:
            initial_password = "admin"  # Used only once when creating a brand new DB
            pw_hash = hash_password(initial_password)
            cursor.execute(
                "INSERT INTO users (userid, password, password_hash, role, failed_attempts, locked_until) VALUES (%s, %s, %s, %s, 0, NULL)",
                ("admin", initial_password, pw_hash, "Admin")
            )
            conn.commit()
            
        # NOTE: If admin already exists, do NOT touch or update the password!
        cursor.close()
        conn.close()
    except Exception as e:
        print("Error checking admin status:", e)


# Authenticate user (Supports hashed passwords, legacy fallback, and account lockout)
def authenticate_user(userid, password):
    userid = sanitize_input(userid) if userid else ""
    if not userid or not password:
        return False, None, "Please fill both User ID and Password fields with valid values."


    conn = get_connection()
    if not conn:
        return False, None, "Database connection error."

    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT password, password_hash, depot, failed_attempts, locked_until FROM users WHERE userid = %s"
        cursor.execute(query, (userid,))
        user_row = cursor.fetchone()

        if not user_row:
            cursor.close()
            conn.close()
            return False, None, "❌ Invalid User ID or Password"

        # Lockout check
        locked_until = user_row.get("locked_until")
        now = datetime.now()
        if locked_until and locked_until > now:
            remaining_mins = int((locked_until - now).total_seconds() // 60) + 1
            cursor.close()
            conn.close()
            return False, None, f"⚠️ Account locked due to failed attempts. Try again in {remaining_mins} min."

        stored_pw = user_row.get("password")
        stored_hash = user_row.get("password_hash")
        failed_attempts = user_row.get("failed_attempts") or 0

        # Determine password match
        is_valid = False
        if stored_hash:
            is_valid = verify_password(password, stored_hash)
        if not is_valid and stored_pw:
            is_valid = verify_password(password, stored_pw)

        if is_valid:
            # Upgrade legacy password to hash if missing
            new_hash = stored_hash if stored_hash else hash_password(password)
            session_token = secrets.token_urlsafe(32)
            session_expires = now + timedelta(hours=8)

            cursor.execute(
                "UPDATE users SET password_hash = %s, password = %s, failed_attempts = 0, locked_until = NULL, session_token = %s, session_expires_at = %s WHERE userid = %s",
                (new_hash, password, session_token, session_expires, userid)
            )
            conn.commit()
            cursor.close()
            conn.close()
            st.session_state["session_token"] = session_token
            return True, user_row.get("depot"), "Login successful"
        else:
            failed_attempts += 1
            new_locked_until = None
            if failed_attempts >= MAX_FAILED_ATTEMPTS:
                new_locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)

            cursor.execute(
                "UPDATE users SET failed_attempts = %s, locked_until = %s WHERE userid = %s",
                (failed_attempts, new_locked_until, userid)
            )
            conn.commit()
            cursor.close()
            conn.close()
            if new_locked_until:
                return False, None, f"⚠️ Account locked for {LOCKOUT_MINUTES} minutes due to failed login attempts."
            return False, None, "❌ Invalid User ID or Password"
    except Exception as e:
        if conn and conn.is_connected():
            conn.close()
        print("Authentication error:", e)
        return False, None, "❌ Authentication failed."

def invalidate_session(userid):
    """Invalidates the session token for a user upon logout."""
    if not userid:
        return
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET session_token = NULL, session_expires_at = NULL WHERE userid = %s",
            (userid,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print("Error invalidating session:", e)

def get_depot_by_userid(userid):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        query = "SELECT depot FROM users WHERE userid = %s"
        cursor.execute(query, (userid,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return result[0]
        return None
    except Exception as e:
        print("Error fetching depot for userid:", e)
        return None

def get_role_by_userid(userid):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        query = "SELECT role FROM users WHERE userid = %s"
        cursor.execute(query, (userid,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        return result[0] if result else None
    except Exception as e:
        print("Error fetching role for userid:", e)
        return None

# Create a new user (Secure password hashing)
def create_user(userid, password, depot, role):
    if not validate_userid(userid):
        return False
    conn = get_connection()
    cursor = conn.cursor()

    try:
        pw_hash = hash_password(password)
        cursor.execute(
            "INSERT INTO users (userid, password, password_hash, depot, role) VALUES (%s, %s, %s, %s, %s)",
            (userid, password, pw_hash, depot, role)
        )
        conn.commit()
        return True
    except mysql.connector.IntegrityError:
        return False
    finally:
        cursor.close()
        conn.close()

