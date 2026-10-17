import streamlit as st
import pandas as pd
import altair as alt
import mysql.connector
from mysql.connector import Error
import json
import calendar

# =========================
# Load Config
# =========================
try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    st.error("config.json not found")
    st.stop()

DB_CONFIG = config["db"]
MYSQL_TABLE_NAME = "input_data"

# =========================
# Ratio Headings
# =========================
RATIO_HEADINGS = {
    'Pct_Weekly_Off_National_Off': 'Weekly Off + National Off %',
    'Pct_Others': 'Others + OD %',
    'Pct_Sick_Leave': 'Sick Leave %',
    'Pct_Spot_Absent': 'Spot Absent %',
    'Pct_Off_Cancellation': 'Off Cancellation %',
    'Pct_Special_Off_Night_Out_IC_Online': 'Special Off / Night Out / IC Online %',
    'Pct_Double_Duty': 'Double Duty %',
    'Pct_Leave_Absent': 'Leave Absent %',
    'Driver_Schedule': 'Driver / Schedule Ratio'
}

# =========================
# Benchmarks
# =========================
BENCHMARKS = {
    'Urban': {
        'Pct_Weekly_Off_National_Off': 14,
        'Pct_Special_Off_Night_Out_IC_Online': 27.4,
        'Pct_Others': 1,
        'Pct_Leave_Absent': 6,
        'Pct_Sick_Leave': 2,
        'Pct_Spot_Absent': 2,
        'Pct_Double_Duty': 8,
        'Pct_Off_Cancellation': 2,
        'Driver_Schedule': 2.43
    },
    'Rural': {
        'Pct_Weekly_Off_National_Off': 14,
        'Pct_Special_Off_Night_Out_IC_Online': 25,
        'Pct_Others': 1.7,
        'Pct_Leave_Absent': 2,
        'Pct_Sick_Leave': 2,
        'Pct_Spot_Absent': 1,
        'Pct_Double_Duty': 16,
        'Pct_Off_Cancellation': 2,
        'Driver_Schedule': 2.18
    }
}

# =========================
# Database Connection
# =========================
def get_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        st.error(f"DB connection error: {e}")
        return None

# =========================
# Load Data
# =========================
def load_data(conn, region):
    query = f"""
        SELECT d.*, a.category
        FROM {MYSQL_TABLE_NAME} d
        JOIN TS_ADMIN a ON d.depot_name = a.depot_name
        WHERE a.region = %s
    """
    df = pd.read_sql(query, conn, params=(region,))
    df.rename(columns={"data_date": "Date", "depot_name": "Depot"}, inplace=True)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df

# =========================
# Main Dashboard
# =========================
def eight_ratios_RM():

    conn = get_connection()
    if not conn:
        st.stop()

    selected_region = st.session_state.get("user_region")
    if not selected_region:
        st.error("Region not found in session")
        st.stop()

    st.markdown(
        "<h1 style='text-align: center; color: white; font-size: 50px;background-color: #19bc9c; border-radius: 12px;{* padding:0px;margin:0px}'>Productivity Budget Ratios vs Actual 8 Ratios Dashboard</h1>",
        unsafe_allow_html=True
    )
    st.markdown("---")

    df = load_data(conn, selected_region)
    if df.empty:
        st.warning("No data available")
        st.stop()

    # =========================
    # Frequency Selection
    # =========================
    freq = st.selectbox("Select Frequency", ["Daily", "Monthly", "Yearly"])

    min_date, max_date = df["Date"].min(), df["Date"].max()

    if freq == "Daily":
        start_date = st.date_input("From Date", min_value=min_date.date(), max_value=max_date.date())
        end_date = st.date_input("To Date", min_value=min_date.date(), max_value=max_date.date())

    elif freq == "Monthly":
        months = list(calendar.month_name)[1:]
        years = list(range(min_date.year, max_date.year + 1))

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            fm = st.selectbox("From Month", months)
        with c2:
            fy = st.selectbox("From Year", years)
        with c3:
            tm = st.selectbox("To Month", months, index=len(months)-1)
        with c4:
            ty = st.selectbox("To Year", years, index=len(years)-1)

        start_date = pd.to_datetime(f"{fy}-{months.index(fm)+1}-01")
        end_date = pd.to_datetime(f"{ty}-{months.index(tm)+1}-01") + pd.offsets.MonthEnd(1)

    else:  # Yearly
        years = list(range(min_date.year, max_date.year + 1))
        fy, ty = st.columns(2)
        with fy:
            from_year = st.selectbox("From Year", years)
        with ty:
            to_year = st.selectbox("To Year", years, index=len(years)-1)

        start_date = pd.to_datetime(f"{from_year}-01-01")
        end_date = pd.to_datetime(f"{to_year}-12-31")

    # =========================
    # FIX: DATETIME COMPATIBILITY
    # =========================
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    df_region = df[
        (df["Date"] >= start_date) &
        (df["Date"] <= end_date)
    ]

    if df_region.empty:
        st.warning("No data for selected range")
        st.stop()

    st.markdown(f"## Region: {selected_region}")
    st.markdown("---")

    # =========================
    # KPI Loop
    # =========================
    for ratio_key, ratio_label in RATIO_HEADINGS.items():

        # ----- Driver / Schedule -----
        if ratio_key == "Driver_Schedule":

            if not {"Total_Drivers", "Planned_Schedules"}.issubset(df_region.columns):
                continue

            agg_df = (
                df_region
                .groupby("Depot")
                .agg(
                    Total_Drivers=("Total_Drivers", "sum"),
                    Planned_Schedules=("Planned_Schedules", "sum")
                )
                .reset_index()
            )

            agg_df["Value"] = agg_df.apply(
                lambda r: round(r["Total_Drivers"] / r["Planned_Schedules"], 2)
                if r["Planned_Schedules"] else 0,
                axis=1
            )

            y_axis = "Drivers per Schedule"

        # ----- Percentage Ratios -----
        else:
            if ratio_key not in df_region.columns:
                continue

            agg_df = (
                df_region
                .groupby("Depot")[ratio_key]
                .mean()
                .round(1)
                .reset_index(name="Value")
            )

            y_axis = "Percentage (%)"

        if agg_df.empty:
            continue

        # ----- Benchmark -----
        first_depot = agg_df["Depot"].iloc[0]
        category = (
            df_region[df_region["Depot"] == first_depot]["category"]
            .iloc[0]
            .capitalize()
        )

        benchmark = BENCHMARKS.get(category, BENCHMARKS["Urban"]).get(ratio_key, 0)
        avg_value = agg_df["Value"].mean()

        # ----- KPI Header -----
        st.markdown(f"### {ratio_label}")

        c1, c2 = st.columns(2)
        with c1:
            st.metric(
                "Region Average",
                f"{avg_value:.2f}" if ratio_key == "Driver_Schedule" else f"{avg_value:.1f}%"
            )
        with c2:
            st.metric(
                "Benchmark",
                f"{benchmark:.2f}" if ratio_key == "Driver_Schedule" else f"{benchmark:.1f}%"
            )

        # ----- Chart -----
        bar = alt.Chart(agg_df).mark_bar(color="steelblue").encode(
            x=alt.X("Depot:N", sort="-y", title="Depot"),
            y=alt.Y("Value:Q", title=y_axis),
            tooltip=["Depot", alt.Tooltip("Value:Q", format=".2f")]
        )

        text = bar.mark_text(dy=-4, fontWeight="bold").encode(
            text=alt.Text("Value:Q", format=".2f" if ratio_key == "Driver_Schedule" else ".1f")
        )

        benchmark_line = alt.Chart(
            pd.DataFrame({"y": [benchmark]})
        ).mark_rule(color="red", strokeDash=[6, 6], size=2).encode(y="y:Q")

        st.altair_chart(bar + text + benchmark_line, use_container_width=True)
        st.markdown("---")

    conn.close()
