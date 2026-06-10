"""
TGSRTC AI-Based Daily Dynamic Scheduling — Streamlit Application.

Run with: streamlit run app.py
"""

import pandas as pd
import streamlit as st
from dynamic_scheduling_master.src.dynamic_scheduling.data_pipeline import run_daily_pipeline
from dynamic_scheduling_master.src.dynamic_scheduling.demand_prediction import run_demand_prediction
from dynamic_scheduling_master.src.dynamic_scheduling.supply_scheduling import run_supply_scheduling
from dynamic_scheduling_master.src.dynamic_scheduling.prediction_vs_actual import render_prediction_vs_actual
from dynamic_scheduling_master.src.dynamic_scheduling.ops_dashboard import (
    load_dashboard_data,
    get_demand_accuracy_data,
    get_supply_accuracy_data,
    calculate_accuracy_metrics,
    build_demand_accuracy_chart,
    build_demand_error_chart,
    build_supply_accuracy_chart,
    build_supply_error_chart,
    list_schedule_dates,
    load_schedule_for_date,
    get_operations_overview_data,
    build_epk_or_scatter,
    build_quadrant_breakdown_chart,
    SCHEDULE_DIR,
)
from dynamic_scheduling_master.src.dynamic_scheduling import ops_dashboard
from auth import get_connection


def get_depots_by_region(region):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT depot_name FROM TS_ADMIN WHERE region=%s",
        (region,)
    )

    depots = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return depots
def run_pipeline():
    return run_daily_pipeline()

def run_prediction():
    return run_demand_prediction()

def run_scheduling():
    return run_supply_scheduling()
# ──────────────────────────────────────────────────────────────────────────
# Sidebar — Daily Operations
# ──────────────────────────────────────────────────────────────────────────
def render_dynamic_scheduling():
    st.title("TGSRTC AI-Based Daily Dynamic Scheduling")

    # ──────────────────────────────────────────────────────────────────────────
    # Main Panel — Data Loading
    # ──────────────────────────────────────────────────────────────────────────

    @st.cache_data(ttl=300)
    def load_data():
        return load_dashboard_data(lookback_days=60)


    predictions_df, gold_df, info = load_data()
    depots = info.get("depots", [])

    if not depots:
        st.info("No data available yet. Run the daily operations from the sidebar to generate data.")
        st.stop()

    # ──────────────────────────────────────────────────────────────────────────
    # Depot Selector (shared across tabs)
    # ──────────────────────────────────────────────────────────────────────────
    role = st.session_state.get("user_role")

    if role not in ["Depot Manager(DMs)", "Regional Manager(RMs)"]:
        st.error("Access denied.")
        st.stop()

    selector_cols = st.columns(2)

    # Define scope once
    if role == "Depot Manager(DMs)":

        scope_name = st.session_state.get("user_depot")
        scope_depots = [scope_name]

    elif role == "Regional Manager(RMs)":

        scope_name = st.session_state.get("user_region")
        # fetch depots for this region
        scope_depots = get_depots_by_region(scope_name)
        if not scope_depots:
            st.error(f"No depots found for region {scope_name}")
            st.stop()

    with selector_cols[0]:

        if role == "Depot Manager(DMs)":
            st.markdown(
                f"""
                <div style="font-weight:bold; padding-bottom:4px;">Depot:</div>
                <div style="background-color:#f0f2f6; padding:0.5em;
                            border-radius:4px; font-weight:bold;">
                    {scope_name}
                </div>
                """,
                unsafe_allow_html=True,
            )

        elif role == "Regional Manager(RMs)":

            st.markdown(
                f"""
                <div style="font-weight:bold; padding-bottom:4px;">Region:</div>
                <div style="background-color:#f0f2f6; padding:0.5em;
                            border-radius:4px; font-weight:bold;">
                    {scope_name}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Schedule dates
    if role == "Depot Manager(DMs)":
        schedule_dates = ops_dashboard.list_schedule_dates(
            SCHEDULE_DIR,
            depot=scope_name
        )

    elif role == "Regional Manager(RMs)":

        # For RM get dates from first depot (all depots share same date folders)
        first_depot = scope_depots[0]

        schedule_dates = ops_dashboard.list_schedule_dates(
            SCHEDULE_DIR,
            depot=first_depot
        )
    
    selected_schedule_date = selector_cols[1].selectbox(
        "Schedule Date",
        schedule_dates if schedule_dates else ["—"],
        disabled=not schedule_dates,
    )

    @st.cache_data(ttl=300)
    def _load_schedule(date_str: str,depot: str):
        return ops_dashboard.load_schedule_for_date(date_str, SCHEDULE_DIR, depot=depot)

    if schedule_dates and selected_schedule_date != "—":

        combined_schedules = {}
        schedule_date = selected_schedule_date

        for depot in scope_depots:

            schedules_temp, _ = _load_schedule(selected_schedule_date, depot)

            if depot in schedules_temp:

                df = schedules_temp[depot].copy()
                df["depot"] = depot

                combined_schedules[depot] = df

        schedules = combined_schedules
    else:
        schedules, schedule_date = {}, None

    # ──────────────────────────────────────────────────────────────────────────
    # Tabs
    # ──────────────────────────────────────────────────────────────────────────

    tab1, tab2, tab3,tab4 = st.tabs(["Demand Accuracy", "Operations Overview", "Modified Schedule","Prediction vs Actual"])

    # ── Tab 1: Demand Accuracy ───────────────────────────────────────────────

    with tab1:
        # Demand data based on role
        if role == "Depot Manager(DMs)":

            demand_df = get_demand_accuracy_data(
                predictions_df,
                scope_name
            )

        elif role == "Regional Manager(RMs)":

            demand_frames = []

            for depot in scope_depots:

                df_temp = get_demand_accuracy_data(
                    predictions_df,
                    depot
                )

                if len(df_temp) > 0:
                    demand_frames.append(df_temp)

            if demand_frames:

                demand_df = pd.concat(demand_frames, ignore_index=True)

                # REGION LEVEL AGGREGATION
                demand_df = (
                    demand_df
                    .groupby("Date", as_index=False)
                    .agg({
                        "Predicted Passenger-KMs": "sum",
                        "Actual Passenger-KMs": "sum"
                    })
                )

                demand_df["Passenger-KM Error %"] = (
                (demand_df["Predicted Passenger-KMs"] - demand_df["Actual Passenger-KMs"])
                / demand_df["Actual Passenger-KMs"].replace({0: pd.NA})
            ) * 100

            else:
                demand_df = pd.DataFrame()

        if len(demand_df) > 0:
            demand_df["Date"] = pd.to_datetime(demand_df["Date"], dayfirst=True)
            demand_df = demand_df.sort_values("Date")
            metrics = calculate_accuracy_metrics(demand_df["Passenger-KM Error %"])

            median_err = metrics.get('Median Abs Error %')
            accuracy = f"{100 - median_err:.1f}" if median_err is not None else '-'
            st.metric("Demand Prediction Accuracy %", f"{accuracy}%")

            # label for charts
            chart_label = scope_name
            st.plotly_chart(
                build_demand_accuracy_chart(demand_df, chart_label),
                use_container_width=True,
            )

            st.plotly_chart(
                build_demand_error_chart(demand_df, chart_label),
                use_container_width=True,
            )

            with st.expander("View Raw Data"):
                display_df = demand_df.copy()
                display_df["Date"] = display_df["Date"].dt.strftime("%d-%m-%Y")
                display_df["Predicted Passenger-KMs"] = display_df["Predicted Passenger-KMs"].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "-")
                display_df["Actual Passenger-KMs"] = display_df["Actual Passenger-KMs"].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "-")
                display_df["Passenger-KM Error %"] = display_df["Passenger-KM Error %"].apply(lambda x: f"{x:.0f}%" if pd.notna(x) else "-")
                display_df = display_df.drop(columns=["Passenger-KM Error"], errors="ignore")
                display_df = display_df.drop(columns=["Status"], errors="ignore")
                st.dataframe(display_df, use_container_width=True)
        else:
            st.info(f"No demand accuracy data available for {scope_name}.")

    # ── Tab 2: Operations Overview ─────────────────────────────────────────

    with tab2:
        # Operations overview based on role
        if role == "Depot Manager(DMs)":

            overview = get_operations_overview_data(
                schedules,
                scope_name
            )

        elif role == "Regional Manager(RMs)":

            if len(schedules) > 0:

                # combine all depot schedules
                combined_df = pd.concat(
                    schedules.values(),
                    ignore_index=True
                )

                overview = {
                    "financial_summary": {
                        "total_revenue": combined_df["revenue"].sum(),
                        "total_contribution": combined_df["contribution"].sum(),
                        "depot_avg_epk": combined_df["epk"].mean(),
                        "depot_avg_or": combined_df["or"].mean()
                    },
                    "quadrant_counts": combined_df["quadrant"].value_counts().to_dict(),
                    "quadrant_pcts": (
                        combined_df["quadrant"].value_counts(normalize=True) * 100
                    ).round(1).to_dict(),
                    "action_summary": {},
                    "schedule_df": combined_df
                }

            else:
                overview = None

        if overview is not None:
            st.subheader(f"Schedule Date: {schedule_date}")
            fin = overview["financial_summary"]
            qc = overview["quadrant_counts"]
            qp = overview["quadrant_pcts"]
            act = overview["action_summary"]
            sched_df = overview["schedule_df"]

            # Row 1: Revenue, Gross Profit & Planned KMs
            fcols = st.columns(3)
            fcols[0].metric("Total Revenue (Lakhs)", f"₹{fin['total_revenue'] / 100000:,.2f}")
            fcols[1].metric("Gross Profit (Lakhs)", f"₹{fin['total_contribution'] / 100000:,.2f}")
            total_planned_kms = sched_df["planned_kms"].sum() if "planned_kms" in sched_df.columns else 0
            fcols[2].metric("Total Planned KM", f"{total_planned_kms:,.0f}")

            # Row 2: Depot Averages
            acols = st.columns(2)
            acols[0].metric("Depot Avg EPK", f"{fin['depot_avg_epk']:.2f}")
            acols[1].metric("Depot Avg OR", f"{fin['depot_avg_or']:.2%}")

            # Row 3: Quadrant breakdown
            qcols = st.columns(4)
            for i, q in enumerate(["UNDERSUPPLY", "OVERSUPPLY", "SOCIAL_OBLIGATION", "INEFFICIENT"]):
                cnt = qc.get(q, 0)
                pct = qp.get(q, 0.0)
                qcols[i].metric(q, f"{cnt} ({pct}%)")

            # Row 3: EPK-OR scatter plot
            # label for charts
            chart_label = scope_name
            st.plotly_chart(
                build_epk_or_scatter(sched_df, chart_label),
                use_container_width=True,
            )

            # Row 5: Quadrant breakdown chart
            st.plotly_chart(
                build_quadrant_breakdown_chart(qc, chart_label),
                use_container_width=True,
            )

            # Expander: Full service-level data table
            with st.expander("View Full Service Data"):
                display_cols = [c for c in ["depot",
                    "service_number", "route", "product", "dep_time",
                    "allocated_pkm", "planned_kms", "revenue", "epk", "or",
                    "quadrant",
                ] if c in sched_df.columns]
                display_df = sched_df[display_cols].copy()
                for col in ["allocated_pkm", "revenue", "epk"]:
                    if col in display_df.columns:
                        display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
                if "or" in display_df.columns:
                    display_df["or"] = display_df["or"].apply(lambda x: f"{x:.0%}" if pd.notna(x) else "-")
                st.dataframe(display_df, use_container_width=True, height=500)
        else:
            if role == "Depot Manager(DMs)":
                label = scope_depots[0]
            else:
                label = st.session_state.get("user_region")

            st.info(
                f"No EPK schedule available for {scope_name}. "
                "Run Supply Scheduling from the sidebar to generate an EPK-based schedule."
            )

    # ── Tab 3: Daily Schedule ────────────────────────────────────────────────

    with tab3:
        if len(schedules) > 0:
            sched_df = pd.concat(schedules.values(), ignore_index=True)

            # Row 1: Schedule Date
            st.subheader(f"Schedule Date: {schedule_date}")

            is_epk = sched_df.get("_engine", pd.Series(dtype=str)).eq("epk").any()

            if is_epk:
                # Row 2: EPK action counts
                action_counts = sched_df["action"].value_counts() if "action" in sched_df.columns else pd.Series(dtype=int)
                acols = st.columns(4)
                acols[0].metric("Total Services", len(sched_df))
                acols[1].metric("Add Slot", int(action_counts.get("ADD_SLOT", 0)))
                acols[2].metric("Cut", int(action_counts.get("CUT", 0)))
                acols[3].metric("No Change", int(action_counts.get("NO_CHANGE", 0)))

                # Row 3: KM summary
                planned_kms = sched_df["planned_kms"].sum() if "planned_kms" in sched_df.columns else 0
                added_kms = sched_df.loc[sched_df["action"] == "ADD_SLOT", "planned_kms"].sum() if "planned_kms" in sched_df.columns and "action" in sched_df.columns else 0
                cut_kms = sched_df.loc[sched_df["action"] == "CUT", "planned_kms"].sum() if "planned_kms" in sched_df.columns and "action" in sched_df.columns else 0
                modified_kms = planned_kms + added_kms - cut_kms
                kcols = st.columns(4)
                kcols[0].metric("Planned KMs", f"{planned_kms:,.0f}")
                kcols[1].metric("Added KMs", f"{added_kms:,.0f}")
                kcols[2].metric("Cut KMs", f"{cut_kms:,.0f}")
                kcols[3].metric("Modified KMs", f"{modified_kms:,.0f}")

                # Row 4: Contribution summary
                planned_contrib = sched_df["contribution"].sum() if "contribution" in sched_df.columns else 0
                # Added contribution: for each ADD_SLOT service with original contribution x,
                # the implementable table has a modified original (0.8-scaled) and an _ADDED row
                # (also 0.8-scaled).  Net added = mod + added - original = 2*mod - original.
                _add_slot = sched_df.loc[sched_df["action"] == "ADD_SLOT"] if "action" in sched_df.columns else pd.DataFrame()
                if len(_add_slot) > 0 and "contribution" in sched_df.columns:
                    _orig_add_contrib = _add_slot["contribution"].sum()
                    _mod_contrib_each = (_add_slot["revenue"] * 0.80) - (_add_slot["cpk"] * _add_slot["planned_kms"])
                    added_contrib = (2 * _mod_contrib_each.sum()) - _orig_add_contrib
                else:
                    added_contrib = 0
                cut_contrib = sched_df.loc[sched_df["action"] == "CUT", "contribution"].sum() if "contribution" in sched_df.columns and "action" in sched_df.columns else 0
                modified_contrib = planned_contrib + added_contrib - cut_contrib
                ccols = st.columns(4)
                ccols[0].metric("Planned Contribution (Lakhs)", f"₹{planned_contrib / 100000:,.2f}")
                ccols[1].metric("Added Contribution (Lakhs)", f"₹{added_contrib / 100000:,.2f}")
                ccols[2].metric("Loss Avoided from CUT (Lakhs)", f"₹{abs(cut_contrib) / 100000:,.2f}")
                ccols[3].metric("Modified Contribution (Lakhs)", f"₹{modified_contrib / 100000:,.2f}")

                # Row 5: Total additional contribution (highlighted)
                total_additional_contrib = modified_contrib - planned_contrib
                st.markdown(
                    f"""
                    <div style="background-color: #d4edda; border: 2px solid #28a745; border-radius: 8px;
                                padding: 16px; text-align: center; margin: 10px 0;">
                        <span style="font-size: 16px; font-weight: 600; color: #155724;">
                            Total Additional Contribution for the Day (Lakhs)</span><br>
                        <span style="font-size: 32px; font-weight: 700; color: #155724;">
                            ₹{total_additional_contrib / 100000:,.2f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Save unfiltered schedule for building the implementable modified schedule
                full_sched_df = sched_df.copy()

                # Action filter
                action_options = ["All"] + sorted(sched_df["action"].unique().tolist()) if "action" in sched_df.columns else ["All"]
                selected_action = st.selectbox("Filter by Action", action_options, key="schedule_action_filter")
                if selected_action != "All":
                    sched_df = sched_df[sched_df["action"] == selected_action]

                # Schedule table — EPK columns
                display_cols = [
                    "depot","service_number", "route", "product", "dep_time",
                    "allocated_pkm", "planned_kms", "revenue", "epk", "or", "cpk", "contribution",
                    "quadrant",
                    "action", "suggested_new_slot", "reason",
                ]
            else:
                # Row 2: Planned KMs and Suggested KMs
                col1, col2 = st.columns(2)
                col1.metric(
                    "Planned KMs",
                    f"{sched_df['planned_kms_day'].sum():,.0f}" if "planned_kms_day" in sched_df.columns else "-",
                )
                col2.metric(
                    "Suggested KMs",
                    f"{sched_df['suggested_kms_day'].sum():,.0f}" if "suggested_kms_day" in sched_df.columns else "-",
                )

                # Row 3: Delta-KMs action counts
                action_counts = sched_df["action"].value_counts() if "action" in sched_df.columns else pd.Series(dtype=int)
                acols = st.columns(5)
                acols[0].metric("Total Services", len(sched_df))
                acols[1].metric("Increase Trips", int(action_counts.get("INCREASE", 0)))
                acols[2].metric("Decrease Trips", int(action_counts.get("DECREASE", 0)))
                acols[3].metric("Stop", int(action_counts.get("STOP", 0)))
                acols[4].metric("No Change", int(action_counts.get("NO_CHANGE", 0)))

                # Schedule table — delta-kms columns
                display_cols = [
                    "service_number", "route", "product", "dep_time", "is_peak",
                    "planned_trips", "suggested_trips", "action", "reason",
                ]

            display_cols = [c for c in display_cols if c in sched_df.columns]
            display_df = sched_df[display_cols].copy()
            for col in ["allocated_pkm", "revenue", "epk", "contribution"]:
                if col in display_df.columns:
                    display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
            if "or" in display_df.columns:
                display_df["or"] = display_df["or"].apply(lambda x: f"{x:.0%}" if pd.notna(x) else "-")
            st.dataframe(display_df, use_container_width=True, height=500)

            # ── Implementable Modified Schedule (EPK only) ─────────────────────
            if is_epk:
                st.subheader("Implementable Modified Schedule")

                mod_cols = ["depot","service_number", "route", "product", "dep_time",
                            "allocated_pkm", "planned_kms", "revenue", "epk", "or", "cpk", "contribution"]
                mod_cols = [c for c in mod_cols if c in full_sched_df.columns]

                # 1. NO_CHANGE rows — as-is
                no_change = full_sched_df[full_sched_df["action"] == "NO_CHANGE"][mod_cols].copy()

                # 2. ADD_SLOT rows — split into modified original + new _ADDED row
                add_slot = full_sched_df[full_sched_df["action"] == "ADD_SLOT"].copy()
                if len(add_slot) > 0:
                    # Modified original
                    mod_orig = add_slot[mod_cols].copy()
                    mod_orig["allocated_pkm"] = add_slot["allocated_pkm"] * 0.80
                    mod_orig["revenue"] = add_slot["revenue"] * 0.80
                    mod_orig["epk"] = add_slot["epk"] * 0.80
                    mod_orig["or"] = add_slot["or"] * 0.80
                    mod_orig["contribution"] = mod_orig["revenue"] - (mod_orig["cpk"] * mod_orig["planned_kms"])

                    # New _ADDED row (same values, different service_number)
                    new_slot = mod_orig.copy()
                    new_slot["service_number"] = add_slot["service_number"].astype(str).values + "_ADDED"
                    if "suggested_new_slot" in add_slot.columns:
                        new_slot["dep_time"] = add_slot["suggested_new_slot"].values

                    modified_schedule = pd.concat([no_change, mod_orig, new_slot], ignore_index=True)
                else:
                    modified_schedule = no_change

                # Sort by dep_time for readability
                if "dep_time" in modified_schedule.columns:
                    modified_schedule = modified_schedule.sort_values("dep_time").reset_index(drop=True)

                # Summary metrics
                mcols = st.columns(3)
                mcols[0].metric("Services", len(modified_schedule))
                mcols[1].metric("Total Planned KMs", f"{modified_schedule['planned_kms'].sum():,.0f}")
                mcols[2].metric("Total Contribution (Lakhs)",
                                f"₹{modified_schedule['contribution'].sum() / 100000:,.2f}")

                # Format and display
                mod_display = modified_schedule.copy()
                for col in ["allocated_pkm", "revenue", "epk", "contribution"]:
                    if col in mod_display.columns:
                        mod_display[col] = mod_display[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
                if "or" in mod_display.columns:
                    mod_display["or"] = mod_display["or"].apply(lambda x: f"{x:.0%}" if pd.notna(x) else "-")
                st.dataframe(mod_display, use_container_width=True, height=500)
        else:
            st.info(f"No schedule available for {scope_name}.")
    with tab4:

        if role == "Depot Manager(DMs)":

            render_prediction_vs_actual(
                selected_depot=scope_name,
                schedule_dates=schedule_dates,
                selected_schedule_date=selected_schedule_date,
                schedules=schedules,
                SCHEDULE_DIR=SCHEDULE_DIR
            )

        elif role == "Regional Manager(RMs)":

            st.info("Prediction vs Actual view is available only at Depot level.")

