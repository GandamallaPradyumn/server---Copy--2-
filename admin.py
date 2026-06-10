import streamlit as st
import mysql.connector
import pandas as pd
import mysql.connector
from mysql.connector import Error
import json
import streamlit as st
def admin():
    # Load DB config once
    with open("config.json") as f:
        config = json.load(f)

    db_config = config.get("db", {})

    def get_connection():
        """Establishes a connection to the MySQL database."""
        try:
            conn = mysql.connector.connect(
                host=db_config.get("host", "localhost"),
                user=db_config.get("user", "root"),
                password=db_config.get("password", ""),
                database=db_config.get("database", "")
            )
            return conn
        except Error as e:
            st.error(f"Error connecting to MySQL: {e}")
            return None


    def get_all_depots():
            conn = get_connection()
            df = pd.read_sql("SELECT * FROM TS_ADMIN", conn)
            conn.close()
            return df

    def add_or_update_depot(name, category):
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO TS_ADMIN (depot_name,category)
                VALUES (%s,%s)
                ON DUPLICATE KEY UPDATE
                    category = VALUES(category)
            """, (name,  category))
            conn.commit()
            conn.close()

        # Streamlit UI
    st.markdown("<h1 style='text-align: center; color: BLACK;'>✍️ Add or Update Depot Settings</h1>", unsafe_allow_html=True)
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])  # center the form
        with col2:
                depot_name = st.text_input("🏢 Depot Name")
                category = st.selectbox("🏷️ Depot Type", ["Select Category", "Rural", "Urban"])

        if st.button("💾 Save Depot Settings"):
                if depot_name and category != "Select Category":
                    add_or_update_depot(depot_name, category)
                    st.success(f"✅ Depot '{depot_name}' settings saved.")
                else:
                    st.warning("⚠️ Please enter both depot name and valid category.")

        st.markdown("### 📋 All Depots")
        df = get_all_depots()
        st.dataframe(df, use_container_width=True)
