import streamlit as st
import pandas as pd
from sqlalchemy import extract
from datetime import date
from db_config import get_session
from models import ActionPlan, TSAdmin


# ------------------------------------------------------------------
# Convert SQLAlchemy objects → pure Python dict (inside session)
# ------------------------------------------------------------------
def convert_records(records):
    output = []
    for r in records:
        output.append({
            "Date": r.data_date.strftime("%Y-%m-%d"),
            "Depot": r.depot_name,
            "Weekly Off & National Off": r.Weekly_Off_National_Off,
            "Special Off (Night Out IC & Online)": r.Special_Off_Night_Out_IC_Online,
            "Others": r.Other_s,
            "Leave & Absent": r.Leave_Absent,
            "Sick Leave": r.Sick_Leave,
            "Spot Absent": r.Spot_Absent,
            "Double Duty": r.Double_Duty,
            "Off Cancellation": r.Off_Cancellation,
        })
    return output


# ==================================================================
# CORPORATION → REGION → DEPOT LEVEL ACTION PLAN HISTORY
# ==================================================================
def action_plan_corporation():

    st.title("🏢 Corporation Action Plan History")

    # ---------------------- Session Validation ----------------------
    if "logged_in" not in st.session_state or not st.session_state.logged_in:
        st.error("Please login first.")
        st.stop()

    # ---------------------- View Level Options ----------------------
    st.markdown("### 🔎 Select View Level")
    view_level = st.radio(
        "Choose View",
        ["All Depots", "Region Wise", "Individual Depot"],
        horizontal=True
    )

    # ---------------------- Year / Month Filters ----------------------
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
        selected_month_name = st.selectbox("Select Month", list(months.keys()))
        selected_month = months[selected_month_name]

    st.markdown("---")

    # ==================================================================
    # 1️⃣ ALL DEPOTS — CORPORATION LEVEL
    # ==================================================================
    if view_level == "All Depots":

        st.subheader("🏢 Corporation Level — All Depots")

        try:
            with get_session() as db:
                rows = (
                    db.query(ActionPlan)
                    .filter(
                        extract("year", ActionPlan.data_date) == selected_year,
                        extract("month", ActionPlan.data_date) == selected_month,
                    )
                    .order_by(ActionPlan.depot_name, ActionPlan.data_date.desc())
                    .all()
                )

                # CONVERT INSIDE SESSION → SAFE
                data = convert_records(rows)

            if not data:
                st.info("ℹ️ No data found.")
                return

            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Error: {e}")

        return

    # ==================================================================
    # 2️⃣ REGION WISE — SELECT REGION
    # ==================================================================
    if view_level == "Region Wise":

        st.subheader("🌍 Region Wise — Select Region")

        # Fetch region list first
        with get_session() as db:
            regions = db.query(TSAdmin.region).distinct().all()

        region_list = sorted([r[0] for r in regions if r[0]])

        selected_region = st.selectbox("Select Region", region_list)
        st.markdown("---")

        if selected_region:

            try:
                with get_session() as db:
                    rows = (
                        db.query(ActionPlan)
                        .join(TSAdmin, TSAdmin.depot_name == ActionPlan.depot_name)
                        .filter(
                            TSAdmin.region == selected_region,
                            extract("year", ActionPlan.data_date) == selected_year,
                            extract("month", ActionPlan.data_date) == selected_month,
                        )
                        .order_by(ActionPlan.depot_name, ActionPlan.data_date.desc())
                        .all()
                    )

                    # Convert inside session → SAFE
                    data = convert_records(rows)

                if not data:
                    st.info("ℹ️ No records found for this region.")
                    return

                st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Error: {e}")

        return

    # ==================================================================
    # 3️⃣ INDIVIDUAL DEPOT — SELECT DEPOT
    # ==================================================================
    if view_level == "Individual Depot":

        st.subheader("🏭 Individual Depot — Select Depot")

        # Get depot list
        with get_session() as db:
            depots = db.query(TSAdmin.depot_name).order_by(TSAdmin.depot_name).all()

        depot_list = [d[0] for d in depots]

        selected_depot = st.selectbox("Select Depot", depot_list)
        st.markdown("---")

        if selected_depot:

            try:
                with get_session() as db:
                    rows = (
                        db.query(ActionPlan)
                        .filter(
                            ActionPlan.depot_name == selected_depot,
                            extract("year", ActionPlan.data_date) == selected_year,
                            extract("month", ActionPlan.data_date) == selected_month,
                        )
                        .order_by(ActionPlan.data_date.desc())
                        .all()
                    )

                    # Convert inside session → SAFE
                    data = convert_records(rows)

                if not data:
                    st.info("ℹ️ No records found for this depot.")
                    return

                st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Error: {e}")

        return
