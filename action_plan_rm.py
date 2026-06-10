import streamlit as st
import pandas as pd
from sqlalchemy import extract
from datetime import date
from db_config import get_session
from models import ActionPlan, TSAdmin


# ---------------------- MAIN FUNCTION ----------------------
def action_rm():

    st.title("📊 Action Plan History (RM)")

    # ---------------------- SESSION VALIDATION ----------------------
    if "user_region" not in st.session_state or not st.session_state.user_region:
        st.error("❌ Session expired! Region not found. Login again.")
        st.stop()

    region = st.session_state.user_region

    # ---------------------- DEPOTS IN THIS REGION ----------------------
    with get_session() as db:
        depots = (
            db.query(TSAdmin.depot_name)
            .filter(TSAdmin.region == region)
            .order_by(TSAdmin.depot_name)
            .all()
        )

    depot_list = [d[0] for d in depots]

    if not depot_list:
        st.warning(f"No depots found for region: {region}")
        st.stop()

    # Depot dropdown for RM
    selected_depot = st.selectbox("Select Depot", depot_list)

    # ---------------------- YEAR + MONTH FILTER ----------------------
    col1, col2 = st.columns(2)

    with col1:
        current_year = date.today().year
        years = list(range(current_year - 5, current_year + 1))
        selected_year = st.selectbox("Select Year", years, index=len(years) - 1)

    with col2:
        months = {
            "January": 1, "February": 2, "March": 3,
            "April": 4, "May": 5, "June": 6,
            "July": 7, "August": 8, "September": 9,
            "October": 10, "November": 11, "December": 12
        }

        selected_month_name = st.selectbox(
            "Select Month",
            list(months.keys())
        )
        selected_month = months[selected_month_name]

    st.markdown("---")
    st.subheader("📅 Action Plan History Table")

    # ---------------------- FETCH HISTORY ----------------------
    try:
        with get_session() as db:
            records_raw = (
                db.query(ActionPlan)
                .filter(
                    ActionPlan.depot_name == selected_depot,
                    extract("year", ActionPlan.data_date) == selected_year,
                    extract("month", ActionPlan.data_date) == selected_month,
                )
                .order_by(ActionPlan.data_date.desc())
                .all()
            )

            # Convert SQLAlchemy objects → dicts BEFORE session closes
            records = []
            for r in records_raw:
                records.append({
                    "data_date": r.data_date,
                    "depot_name": r.depot_name,
                    "Weekly_Off_National_Off": r.Weekly_Off_National_Off,
                    "Special_Off_Night_Out_IC_Online": r.Special_Off_Night_Out_IC_Online,
                    "Other_s": r.Other_s,
                    "Leave_Absent": r.Leave_Absent,
                    "Sick_Leave": r.Sick_Leave,
                    "Spot_Absent": r.Spot_Absent,
                    "Double_Duty": r.Double_Duty,
                    "Off_Cancellation": r.Off_Cancellation,
                })

        # ---------------------- FORMAT HISTORY ----------------------
        data = []

        for r in records:
            month = r["data_date"].month

            # Determine quarter
            if 1 <= month <= 3:
                quarter = "Q1"
            elif 4 <= month <= 6:
                quarter = "Q2"
            elif 7 <= month <= 9:
                quarter = "Q3"
            else:
                quarter = "Q4"

            data.append({
                "Date": r["data_date"].strftime("%Y-%m-%d"),
                "DEPOT": r["depot_name"],
                "Quarter": quarter,
                "Weekly Off & National Off": r["Weekly_Off_National_Off"],
                "Special Off (Night Out IC & Online)": r["Special_Off_Night_Out_IC_Online"],
                "Others": r["Other_s"],
                "Leave & Absent": r["Leave_Absent"],
                "Sick Leave": r["Sick_Leave"],
                "Spot Absent": r["Spot_Absent"],
                "Double Duty": r["Double_Duty"],
                "Off Cancellation": r["Off_Cancellation"],
            })

        # ---------------------- DISPLAY TABLE ----------------------
        if data:
            df = pd.DataFrame(data)

            df = df[[   # reorder columns
                "Date", "DEPOT", "Quarter",
                "Weekly Off & National Off",
                "Special Off (Night Out IC & Online)",
                "Others", "Leave & Absent", "Sick Leave",
                "Spot Absent", "Double Duty", "Off Cancellation"
            ]]

            st.dataframe(df, use_container_width=True, hide_index=True)

        else:
            st.info("ℹ️ No Action Plan entries found for this month.")

    except Exception as e:
        st.error(f"Error fetching history: {e}")
