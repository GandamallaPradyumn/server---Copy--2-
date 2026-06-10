import streamlit as st
import mysql.connector
import pandas as pd
from datetime import datetime, timedelta

# ---------- DB Connection ----------
import mysql.connector
from mysql.connector import Error
import json

# Load config.json
with open("config.json") as f:
    config = json.load(f)

DB_CONFIG = config.get("db", {})

# --------- DB connection helper ----------
def get_connection():
    try:
        # allow only valid mysql args
        allowed_keys = {"host", "user", "password", "database", "port"}
        db_conf = {k: v for k, v in config["db"].items() if k in allowed_keys}
        return mysql.connector.connect(**db_conf)
    except Error as e:
        st.error(f"Error connecting to database: {e}")
        return None



# ---------- Fetch Data ----------
def get_depot_status():
    conn = get_connection()
    query = """
        SELECT 
            a.zone,
            a.region,
            a.depot_name AS depot,
            MAX(i.data_date) AS latest_date
        FROM TS_ADMIN  a
        LEFT JOIN input_data i 
            ON a.depot_name = i.depot_name
        GROUP BY a.zone, a.region, a.depot_name
        ORDER BY a.zone, a.region, a.depot_name
    """
    df = pd.read_sql(query, conn)
    conn.close()

    df["latest_date"] = pd.to_datetime(df["latest_date"], errors="coerce").dt.date
    yesterday = datetime.today().date() - timedelta(days=1)

    df["LAST DATE UPDATED"] = df["latest_date"].apply(
        lambda d: d.strftime("%d-%m-%Y") if pd.notnull(d) else "--"
    )
    df["NO. OF DAYS PENDING"] = df["latest_date"].apply(
        lambda d: (yesterday - d).days if pd.notnull(d) else None
    )
    df["STATUS"] = df["NO. OF DAYS PENDING"].apply(
        lambda x: "Updated" if x == 0 else "Pending"
    )

    return df[["zone", "region", "depot", "LAST DATE UPDATED", "STATUS", "NO. OF DAYS PENDING"]]

# ---------- Custom HTML Renderer ----------
def render_merged_table(df):
    html = """
    <table border='1' style='border-collapse: collapse; width:100%; text-align:center;'>
    <tr style='background-color:#f2f2f2;'>
    """
    for col in df.columns:
        html += f"<th>{col}</th>"
    html += "</tr>"

    zone_count = df['zone'].value_counts()
    region_count = df.groupby(['zone'])['region'].value_counts()
    zone_seen, region_seen = {}, {}

    for _, row in df.iterrows():
        html += "<tr>"
        if row['zone'] not in zone_seen:
            html += f"<td rowspan='{zone_count[row['zone']]}'>{row['zone']}</td>"
            zone_seen[row['zone']] = True
        if (row['zone'], row['region']) not in region_seen:
            html += f"<td rowspan='{region_count[row['zone']][row['region']]}'>{row['region']}</td>"
            region_seen[(row['zone'], row['region'])] = True
        html += f"<td>{row['depot']}</td>"
        html += f"<td>{row['LAST DATE UPDATED']}</td>"
        if "Pending" in row['STATUS']:
            html += f"<td style='color:red; font-weight:bold;'>{row['STATUS']}</td>"
        else:
            html += f"<td style='color:green; font-weight:bold;'>{row['STATUS']}</td>"
        html += f"<td>{row['NO. OF DAYS PENDING'] if row['NO. OF DAYS PENDING'] is not None else '--'}</td>"
        html += "</tr>"

    html += "</table>"
    return html

# ---------- Streamlit UI ----------
def pending_depot():
    st.markdown("### 📋 Latest Data per Depot")

    try:
        df = get_depot_status()

        # ⬇️ Download button placed immediately after header
        if not df.empty:
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Download as CSV",
                data=csv,
                file_name="latest_depot_data.csv",
                mime="text/csv",
            )

            # Render table
            st.markdown(render_merged_table(df), unsafe_allow_html=True)
        else:
            st.warning("No data found.")
    except Exception as e:
        st.error(f"Error fetching data: {e}")
