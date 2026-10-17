import streamlit as st
import mysql.connector
from mysql.connector import Error
import json
import pandas as pd
from datetime import datetime, timedelta

# ---------- DB Connection ----------
# Load configuration from config.json
with open("config.json") as f:
    config = json.load(f)

db_config = config.get("db", {})

def get_connection():
    """Establishes and returns a MySQL database connection."""
    return mysql.connector.connect(
        host=db_config["host"],
        user=db_config["user"],
        password=db_config["password"],
        database=db_config["database"]
    )
# ---------- Fetch Data ----------
def get_depot_status():
    """
    Fetches depot status and Depot Manager user IDs from the database.
    A depot is 'Updated' if its latest data date is yesterday or today.
    """
    conn = get_connection()
    query = """
        SELECT
            a.region,
            a.depot_name AS depot,
            MAX(i.data_date) AS latest_date,
            MAX(CASE WHEN u.role = 'Depot Manager' THEN u.userid END) AS userid
        FROM TS_ADMIN a
        LEFT JOIN input_data i
            ON a.depot_name = i.depot_name
        LEFT JOIN users u
            ON a.depot_name = u.depot
        GROUP BY a.region, a.depot_name
        ORDER BY a.region, a.depot_name;
    """
    df = pd.read_sql(query, conn)
    conn.close()

    df["latest_date"] = pd.to_datetime(df["latest_date"], errors="coerce").dt.date
    today = datetime.today().date()
    yesterday = today - timedelta(days=1)

    df["STATUS"] = df["latest_date"].apply(
        lambda d: "Updated" if pd.notnull(d) and (d == yesterday or d == today) else "Pending"
    )
    df["DATE_TEXT"] = df["latest_date"].apply(
        lambda d: f"({d.strftime('%d-%m-%Y')})" if pd.notnull(d) else ""
    )
    
    # Remove @AI if present
    df['userid'] = df['userid'].str.replace('@AI', '', regex=False)
    
    # Show Depot Manager userid if available, otherwise depot name
    df['display_name'] = df['userid'].fillna(df['depot'])

    return df

# ---------- Streamlit UI ----------
def depotlist():
    """
    Renders the Streamlit application for displaying depot status.
    """
    st.subheader("📋 Region-wise Depot Status")

    try:
        df = get_depot_status()
        if not df.empty:
            
            regions = df.groupby('region')
            region_list = list(regions.groups.keys())

            for i, region in enumerate(region_list):
                group = regions.get_group(region)
                
                st.header(f"{region}")
                
                # Use three columns to create a margin in the middle
                col1, col_spacer, col2 = st.columns([1, 0.2, 1])
                with col1:
                    st.markdown("#### *Updated Depots*")
                with col2:
                    st.markdown("#### *Not Updated Depots*")
                
                st.markdown("---")

                updated_depots = group[group["STATUS"] == "Updated"]["display_name"].tolist()
                not_updated_depots = group[group["STATUS"] == "Pending"]
                
                # Use three columns for the data rows as well
                row_col1, row_col_spacer, row_col2 = st.columns([1, 0.2, 1])
                
                with row_col1:
                    if updated_depots:
                        for depot in updated_depots:
                            st.markdown(f"<p style='color:green;font-weight:bold;font-size:18px;'>{depot}</p>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<p style='font-size:18px;'>--</p>", unsafe_allow_html=True)

                with row_col2:
                    if not not_updated_depots.empty:
                        for _, r in not_updated_depots.iterrows():
                            st.markdown(f"<p style='color:red;font-weight:bold;font-size:18px;'>{r['display_name']}{r['DATE_TEXT']}</p>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<p style='color:red;font-weight:bold;font-size:18px;'>--</p>", unsafe_allow_html=True)

                st.markdown("---")


            # Optional CSV download
            summary_df = pd.DataFrame({
                "Region": regions.groups.keys(),
                "Updated Depots": [
                    ", ".join(regions.get_group(r)[regions.get_group(r)["STATUS"] == "Updated"]["display_name"].tolist())
                    for r in regions.groups.keys()
                ],
                "Not Updated Depots": [
                    ", ".join(regions.get_group(r)[regions.get_group(r)["STATUS"] == "Pending"].apply(
                        lambda x: f"{x['display_name']}{x['DATE_TEXT']}", axis=1
                    ).tolist())
                    for r in regions.groups.keys()
                ]
            })

            csv = summary_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇ Download as CSV",
                csv,
                "depot_status_summary.csv",
                "text/csv",
                key="download-csv"
            )

        else:
            st.warning("No data found.")
    except Exception as e:
        st.error(f"Error fetching data: {e}")

if __name__ == "__main__":
    st.set_page_config(layout="wide")
    depotlist()
