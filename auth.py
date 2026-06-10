# auth.py
import mysql.connector
import json
import streamlit as st
from mysql.connector import Error

# Load config.json
with open("config.json") as f:
    config = json.load(f)

db_config = config["db"]
# ---------- Session helpers ----------
def is_authenticated():
    """
    Return True if the user is logged in (login.py sets st.session_state.logged_in).
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
        conn = mysql.connector.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"]
        )
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
# Ensure admin exists (plain text password)
def ensure_admin_exists():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE userid = 'admin'")
    result = cursor.fetchone()

    if result[0] == 0:
        default_password = "admin123"
        cursor.execute("INSERT INTO users (userid, password) VALUES (%s, %s)", ("admin", default_password))
        conn.commit()

    conn.close()

# Authenticate user (plain text match)
def authenticate_user(userid, password):
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT password, depot FROM users WHERE userid = %s"
    cursor.execute(query, (userid,))
    result = cursor.fetchone()
    conn.close()

    if result:
        stored_password, depot = result
        if stored_password == password:
            return True, depot
    return False, None


# auth.py

def get_depot_by_userid(userid):
    try:
        conn = mysql.connector.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"]
        )
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




# Create a new user (plain password)
def create_user(userid, password,depot,role):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO users (userid, password,depot,role) VALUES (%s, %s,%s,%s)", (userid, password,depot,role))
        conn.commit()
        return True
    except mysql.connector.IntegrityError:
        return False
    finally:
        conn.close()
