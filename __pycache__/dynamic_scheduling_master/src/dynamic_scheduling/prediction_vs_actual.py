import streamlit as st
import pandas as pd
import numpy as np
import os
import re
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dynamic_scheduling_master.src.dynamic_scheduling.ops_dashboard import load_schedule_for_date

def render_prediction_vs_actual(
        selected_depot,
        schedule_dates,
        selected_schedule_date,
        schedules,
        SCHEDULE_DIR
):
    
    st.subheader("Prediction vs Actual Monitoring")
    
    # ── Helper: classify a service number ────────────────────────────────────
    def _pva_classify(svc_str, scheduled_services):
        s = str(svc_str).strip()
        if s in scheduled_services:
            return "Scheduled"
        if re.fullmatch(r"[89]\d{3}", s):
            return "Extra Service"
        return "New Service"

    # ── Helper: load actuals from gold parquet ────────────────────────────────
    @st.cache_data(ttl=300)
    def _pva_load_actuals(date_str, gold_path):
        if not os.path.exists(gold_path):
            return pd.DataFrame(), f"File not found: {gold_path}"
        try:
            df = pd.read_parquet(gold_path)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            date_col = next((c for c in ["date", "ops_date", "service_date"] if c in df.columns), None)
            if date_col is None:
                return pd.DataFrame(), f"No date column found. Columns: {df.columns.tolist()}"
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
            result = df[df[date_col] == date_str].copy()
            return result, None
        except Exception as e:
            return pd.DataFrame(), str(e)

    # ── Helper: load historical data for trend ─────────────────────────────────
    @st.cache_data(ttl=300)
    def _pva_load_historical(gold_path, days=60):
        if not os.path.exists(gold_path):
            return pd.DataFrame()
        try:
            df = pd.read_parquet(gold_path)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            date_col = next((c for c in ["date", "ops_date", "service_date"] if c in df.columns), None)
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                cutoff_date = datetime.now() - timedelta(days=days)
                df = df[df[date_col] >= cutoff_date]
            return df
        except Exception:
            return pd.DataFrame()

    # ── Gold parquet path (relative to project root) ──────────────────────────
    _sched_dir_str = str(SCHEDULE_DIR).rstrip("/\\")
    _project_root  = os.path.dirname(os.path.dirname(_sched_dir_str))
    GOLD_SERVICE_PATH  = os.path.join(_project_root, "data", "processed", "ops_daily_service_gold.parquet")
    GOLD_DEPOT_PATH    = os.path.join(_project_root, "data", "processed", "ops_daily_gold.parquet")
    PREDICTIONS_PATH   = os.path.join(_project_root, "output", "predictions", "daily_predictions.parquet")

    # ── Helper: load depot-level PKM from depot gold (matches demand prediction tab) ──
    @st.cache_data(ttl=300)
    def _pva_load_depot_actual_pkm(date_str, depot, gold_path):
        if not os.path.exists(gold_path):
            return None
        try:
            df = pd.read_parquet(gold_path)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            date_col = next((c for c in ["date", "ops_date", "service_date"] if c in df.columns), None)
            depot_col = next((c for c in ["depot", "depot_name", "depot_code"] if c in df.columns), None)
            if not date_col or not depot_col:
                return None
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
            row = df[
                (df[date_col] == date_str) &
                (df[depot_col].astype(str).str.upper().str.strip() == depot.upper().strip())
            ]
            if row.empty or "passenger_kms" not in row.columns:
                return None
            return pd.to_numeric(row["passenger_kms"], errors="coerce").sum()
        except Exception:
            return None

    # ── Helper: load predicted PKM from daily_predictions.parquet (matches demand prediction tab) ──
    @st.cache_data(ttl=300)
    def _pva_load_predicted_pkm(date_str, depot, predictions_path):
        if not os.path.exists(predictions_path):
            return None
        try:
            df = pd.read_parquet(predictions_path)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            date_col = next((c for c in ["prediction_date", "date"] if c in df.columns), None)
            depot_col = next((c for c in ["depot", "depot_name"] if c in df.columns), None)
            if not date_col or not depot_col:
                return None
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
            row = df[
                (df[date_col] == date_str) &
                (df[depot_col].astype(str).str.upper().str.strip() == depot.upper().strip())
            ]
            if row.empty:
                return None
            if "predicted_passenger_kms" in row.columns and row["predicted_passenger_kms"].notna().any():
                return pd.to_numeric(row["predicted_passenger_kms"], errors="coerce").iloc[0]
            return None
        except Exception:
            return None

    # ── Date selector ──────────────────────────────────────────────────────────
    if not schedule_dates:
        st.info("No schedule dates found. Run Supply Scheduling from the sidebar first.")
    else:
        # Check which dates also have actuals in gold
        @st.cache_data(ttl=300)
        def _pva_dates_status(sched_dates, gold_path):
            status = {}
            if not os.path.exists(gold_path):
                return {d: False for d in sched_dates}
            try:
                df = pd.read_parquet(gold_path)
                df.columns = [c.strip().lower() for c in df.columns]
                date_col = next((c for c in ["date", "ops_date", "service_date"] if c in df.columns), None)
                available = set(
                    pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d").dropna().unique()
                ) if date_col else set()
            except Exception:
                available = set()
            return {d: d in available for d in sched_dates}

        dates_status = _pva_dates_status(tuple(schedule_dates), GOLD_SERVICE_PATH)

        pva_sel_idx = st.selectbox(
            "Select Date",
            range(len(schedule_dates)),
            format_func=lambda i: (
                f"{schedule_dates[i]}  Both available ✅"
                if dates_status.get(schedule_dates[i])
                else f"{schedule_dates[i]}  Predictions only"
            ),
            key="pva_date_select",
        )
        pva_date_str = schedule_dates[pva_sel_idx]
        has_actuals  = dates_status.get(pva_date_str, False)

        # ── Status banner ─────────────────────────────────────────────────────
        if not has_actuals:
            st.warning(
                f" Schedule exists for **{pva_date_str}** but actuals have not been processed yet. "
                "Upload the actuals CSV via the **Files Upload** tab, then run the Data Pipeline."
            )
            st.stop()

        st.success(f"✅ Both predictions and actuals available for **{pva_date_str}**.")

        # ── Load schedule ──────────────────────────────────────────────────────
        if pva_date_str == selected_schedule_date and selected_depot in schedules:
            pva_sched_df = schedules[selected_depot].copy()
        else:
            pva_schedules, _ = load_schedule_for_date(pva_date_str, SCHEDULE_DIR)
            if selected_depot not in pva_schedules:
                st.warning(f"No schedule found for depot **{selected_depot}** on {pva_date_str}.")
                st.stop()
            pva_sched_df = pva_schedules[selected_depot].copy()

        if pva_sched_df.empty:
            st.warning(f"Schedule for {selected_depot} on {pva_date_str} is empty.")
            st.stop()

        # ── Load actuals ───────────────────────────────────────────────────────
        actuals_all, err = _pva_load_actuals(pva_date_str, GOLD_SERVICE_PATH)
	
        if err:
            st.error(f"Could not load actuals: {err}")
            st.stop()
        if actuals_all.empty:
            st.warning(f"Gold parquet loaded but no rows found for date {pva_date_str}.")
            st.stop()

        # Filter actuals to selected depot
        depot_col = next((c for c in ["depot", "depot_name", "depot_code"] if c in actuals_all.columns), None)
        if depot_col:
            act_df = actuals_all[
                actuals_all[depot_col].astype(str).str.upper().str.strip() == selected_depot.upper().strip()
            ].copy()
            if act_df.empty:
                avail = actuals_all[depot_col].unique().tolist()
                st.warning(
                    f"No actuals for depot **{selected_depot}** on {pva_date_str}. "
                    f"Depots found in gold parquet: `{avail}`"
                )
                st.stop()
        else:
            act_df = actuals_all.copy()

        # ── Normalise service_number ───────────────────────────────────────────
        pva_sched_df["service_number"] = pva_sched_df["service_number"].astype(str).str.strip()
        act_df["service_number"]       = act_df["service_number"].astype(str).str.strip()

        # ── Calculate actual EPK = revenue / actual_kms ───────────────────────
        if "revenue" in act_df.columns and "actual_kms" in act_df.columns:
            act_df["actual_epk"] = np.where(
                pd.to_numeric(act_df["actual_kms"], errors="coerce") > 0,
                pd.to_numeric(act_df["revenue"], errors="coerce") / pd.to_numeric(act_df["actual_kms"], errors="coerce"),
                np.nan
            )

        # ── Calculate actual Contribution = revenue - (cpk * actual_kms) ──
        # Merge CPK from schedule into actuals
        if "cpk" in pva_sched_df.columns:
            cpk_lookup = pva_sched_df[["service_number", "cpk"]].copy()
            act_df = act_df.merge(cpk_lookup, on="service_number", how="left")
            if "revenue" in act_df.columns and "actual_kms" in act_df.columns:
                act_df["actual_contribution"] = np.where(
                    act_df["cpk"].notna() & (pd.to_numeric(act_df["actual_kms"], errors="coerce") > 0),
                    pd.to_numeric(act_df["revenue"], errors="coerce") - (
                        pd.to_numeric(act_df["cpk"], errors="coerce") *
                        pd.to_numeric(act_df["actual_kms"], errors="coerce")
                    ),
                    np.nan
                )

        scheduled_svcs = set(pva_sched_df["service_number"])
        act_df["_category"] = act_df["service_number"].apply(lambda s: _pva_classify(s, scheduled_svcs))

        # ── Detect actual columns ──────────────────────────────────────────────
        actual_pkm_col      = next((c for c in ["passenger_kms","passenger_km","pkm","actual_pkm"]   if c in act_df.columns), None)
        actual_kms_col      = next((c for c in ["actual_kms","actual_km","kms"]                      if c in act_df.columns), None)
        actual_trips_col    = next((c for c in ["actual_trips","trips"]                              if c in act_df.columns), None)
        actual_or_col       = next((c for c in ["occupancy_ratio","or"]                              if c in act_df.columns), None)
        actual_revenue_col  = next((c for c in ["revenue","earnings","actual_revenue","actual_earnings"] if c in act_df.columns), None)
        actual_epk_col      = next((c for c in ["actual_epk","epk"]                                  if c in act_df.columns), None)
        actual_contrib_col  = next((c for c in ["actual_contribution","contribution"]                 if c in act_df.columns), None)

        # ── Detect predicted columns ───────────────────────────────────────────
        pred_epk_col        = next((c for c in ["epk", "allocated_epk"]                              if c in pva_sched_df.columns), None)
        pred_or_col         = next((c for c in ["or", "planned_or"]                                  if c in pva_sched_df.columns), None)

        # ── Compute modified schedule metrics (mirrors app.py Tab 3 logic) ──
        # Planned values (all services as-is)
        _s = pva_sched_df.copy()
        _has_action     = "action" in _s.columns
        _has_contrib    = "contribution" in _s.columns
        _has_kms        = "planned_kms" in _s.columns
        _has_revenue    = "revenue" in _s.columns
        _has_cpk        = "cpk" in _s.columns
        _has_epk        = pred_epk_col is not None
        _has_or         = pred_or_col is not None

        planned_contrib = pd.to_numeric(_s["contribution"], errors="coerce").sum() if _has_contrib else 0
        planned_kms_val = pd.to_numeric(_s["planned_kms"], errors="coerce").sum()  if _has_kms    else 0
        planned_revenue = pd.to_numeric(_s["revenue"], errors="coerce").sum()       if _has_revenue else 0

        # ADD_SLOT adjustments (revenue scaled 0.8, new slot added)
        _add = _s[_s["action"] == "ADD_SLOT"].copy() if _has_action else pd.DataFrame()
        if len(_add) > 0 and _has_contrib and _has_revenue and _has_cpk and _has_kms:
            _orig_add_contrib  = pd.to_numeric(_add["contribution"], errors="coerce").sum()
            _mod_contrib_each  = (pd.to_numeric(_add["revenue"], errors="coerce") * 0.80) \
                                 - (pd.to_numeric(_add["cpk"], errors="coerce") * pd.to_numeric(_add["planned_kms"], errors="coerce"))
            added_contrib = (2 * _mod_contrib_each.sum()) - _orig_add_contrib
            added_kms     = pd.to_numeric(_add["planned_kms"], errors="coerce").sum()
            # Revenue: 2 rows at 0.8x each → net added = 2*0.8*rev - orig_rev = 0.6*orig_rev
            added_revenue = (2 * pd.to_numeric(_add["revenue"], errors="coerce") * 0.80).sum() \
                            - pd.to_numeric(_add["revenue"], errors="coerce").sum()
        else:
            added_contrib = 0
            added_kms     = 0
            added_revenue = 0

        # CUT adjustments
        _cut = _s[_s["action"] == "CUT"].copy() if _has_action else pd.DataFrame()
        cut_contrib = pd.to_numeric(_cut["contribution"], errors="coerce").sum() if len(_cut) > 0 and _has_contrib else 0
        cut_kms     = pd.to_numeric(_cut["planned_kms"],   errors="coerce").sum() if len(_cut) > 0 and _has_kms    else 0
        cut_revenue = pd.to_numeric(_cut["revenue"],       errors="coerce").sum() if len(_cut) > 0 and _has_revenue else 0

        # Modified totals
        modified_contrib  = planned_contrib  + added_contrib  - cut_contrib
        modified_kms_val  = planned_kms_val  + added_kms      - cut_kms
        modified_revenue  = planned_revenue  + added_revenue   - cut_revenue

        # Modified EPK and OR – from modified_schedule rows (NO_CHANGE + scaled ADD_SLOT + new slots)
        _no_change = _s[_s["action"] == "NO_CHANGE"].copy() if _has_action else _s.copy()
        if len(_add) > 0:
            _mod_orig          = _add.copy()
            _mod_orig["epk"]   = pd.to_numeric(_add[pred_epk_col], errors="coerce") * 0.80 if _has_epk else 0
            _mod_orig["or"]    = pd.to_numeric(_add[pred_or_col],  errors="coerce") * 0.80 if _has_or  else 0
            _new_slot          = _mod_orig.copy()
            _mod_schedule      = pd.concat([_no_change, _mod_orig, _new_slot], ignore_index=True)
        else:
            _mod_schedule = _no_change.copy()

        modified_epk = pd.to_numeric(_mod_schedule[pred_epk_col], errors="coerce").mean() \
                       if _has_epk and len(_mod_schedule) > 0 else None
        modified_or  = pd.to_numeric(_mod_schedule[pred_or_col],  errors="coerce").mean() \
                       if _has_or  and len(_mod_schedule) > 0 else None

        # ══════════════════════════════════════════════════════════════════════
        # ═══ SECTION 1: ACTUALS vs PREDICTED METRICS CARDS ═══════════════════
        # ══════════════════════════════════════════════════════════════════════
        
        st.markdown("---")
        st.markdown("Actuals vs Predicted Metrics")
        
        col_pred, col_actual  = st.columns(2)

        # ── ACTUALS CARD ───────────────────────────────────────────────────────
        with col_actual:
            st.markdown("#### Actuals")
            actual_card = st.container(border=True)
            with actual_card:
                metric_cols = st.columns(3)
                
                # Row 1 – Actual PKM from depot-level gold (matches Demand Prediction tab)
                with metric_cols[0]:
                    depot_actual_pkm = _pva_load_depot_actual_pkm(pva_date_str, selected_depot, GOLD_DEPOT_PATH)
                    if depot_actual_pkm is not None:
                        st.metric("Actual PKM", f"{depot_actual_pkm:,.0f}")
                    elif actual_pkm_col:
                        val = pd.to_numeric(act_df[actual_pkm_col], errors="coerce").sum()
                        st.metric("Actual PKM", f"{val:,.0f}")
                    else:
                        st.metric("Actual PKM", "—")
                
                with metric_cols[1]:
                    if actual_epk_col:
                        val = pd.to_numeric(act_df[actual_epk_col], errors="coerce").mean()
                        st.metric("Depot Avg EPK", f"{val:.2f}")
                    else:
                        st.metric("Depot Avg EPK", "—")
                
                with metric_cols[2]:
                    # Weighted OR = sum(passenger_kms) / sum(seat_kms) – matches data_pipeline logic
                    if "passenger_kms" in act_df.columns and "seat_kms" in act_df.columns:
                        total_pkm  = pd.to_numeric(act_df["passenger_kms"], errors="coerce").sum()
                        total_skm  = pd.to_numeric(act_df["seat_kms"],      errors="coerce").sum()
                        weighted_or = (total_pkm / total_skm) if total_skm > 0 else None
                        if weighted_or is not None:
                            st.metric("Depot Avg OR", f"{weighted_or:.1%}")
                        else:
                            st.metric("Depot Avg OR", "—")
                    elif actual_or_col:
                        # fallback to simple mean if seat_kms not available
                        val = pd.to_numeric(act_df[actual_or_col], errors="coerce").mean()
                        st.metric("Depot Avg OR", f"{val:.1%}")
                    else:
                        st.metric("Depot Avg OR", "—")
                
                st.markdown("")
                metric_cols2 = st.columns(3)
                
                # Row 2
                with metric_cols2[0]:
                    if actual_kms_col:
                        val = pd.to_numeric(act_df[actual_kms_col], errors="coerce").sum()
                        st.metric("Actual KMs", f"{val:,.0f}")
                    else:
                        st.metric("Actual KMs", "—")
                
                with metric_cols2[1]:
                    if actual_revenue_col:
                        val = pd.to_numeric(act_df[actual_revenue_col], errors="coerce").sum()
                        st.metric("Total Revenue", f"₹{val/100000:,.2f}L")
                    else:
                        st.metric("Total Revenue", "—")

                with metric_cols2[2]:
                    if actual_contrib_col:
                        val = pd.to_numeric(act_df[actual_contrib_col], errors="coerce").sum()
                        st.metric("Contribution", f"₹{val/100000:,.2f}L")
                    else:
                        st.metric("Contribution", "—")
                

        # ── PREDICTED CARD – all values from Modified Schedule (mirrors Tab 3) ──
        with col_pred:
            st.markdown("#### Predicted (Modified Schedule)")
            pred_card = st.container(border=True)
            with pred_card:
                metric_cols = st.columns(3)

                # Row 1
                with metric_cols[0]:
                    # PKM from daily_predictions.parquet (matches Demand Prediction tab)
                    pred_pkm = _pva_load_predicted_pkm(pva_date_str, selected_depot, PREDICTIONS_PATH)
                    if pred_pkm is not None:
                        st.metric("Predicted PKM", f"{pred_pkm:,.0f}")
                    elif "allocated_pkm" in pva_sched_df.columns:
                        val = pva_sched_df["allocated_pkm"].sum()
                        st.metric("Predicted PKM", f"{val:,.0f}")
                    else:
                        st.metric("Predicted PKM", "—")

                with metric_cols[1]:
                    # Depot Avg EPK from modified schedule rows
                    if modified_epk is not None:
                        st.metric("Depot Avg EPK", f"{modified_epk:.2f}")
                    else:
                        st.metric("Depot Avg EPK", "—")

                with metric_cols[2]:
                    # Depot Avg OR from modified schedule rows
                    if modified_or is not None:
                        st.metric("Depot Avg OR", f"{modified_or:.1%}")
                    else:
                        st.metric("Depot Avg OR", "—")

                st.markdown("")
                metric_cols2 = st.columns(3)

                # Row 2
                with metric_cols2[0]:
                    # Modified KMs = planned + added - cut (same as Tab 3)
                    if _has_kms:
                        st.metric("Modified KMs", f"{modified_kms_val:,.0f}")
                    else:
                        st.metric("Modified KMs", "—")
                        
                with metric_cols2[1]:
                    # Modified Revenue = planned + added(0.8 scaled) - cut
                    if _has_revenue:
                        st.metric("Total Revenue", f"₹{modified_revenue/100000:,.2f}L")
                    else:
                        st.metric("Total Revenue", "—")

                with metric_cols2[2]:
                    # Modified Contribution = planned + added - cut (same as Tab 3)
                    if _has_contrib:
                        st.metric("Contribution", f"₹{modified_contrib/100000:,.2f}L")
                    else:
                        st.metric("Contribution", "—")

        # ══════════════════════════════════════════════════════════════════════
        # ═══ SECTION 2: EXPANDABLE SERVICE SECTIONS ═══════════════════════════
        # ══════════════════════════════════════════════════════════════════════
        
        st.markdown("---")
        st.markdown("Services by Action Type")

        # ── Prepare merge data ─────────────────────────────────────────────────
        sched_cols = ["service_number", "action"]
        for _c in ["route", "product", "dep_time", "allocated_pkm", "planned_kms", "revenue", "cpk", "contribution", "epk", "or"]:
            if _c in pva_sched_df.columns:
                sched_cols.append(_c)
        sched_slim = pva_sched_df[sched_cols].copy()
        # Deduplicate schedule at source – schedule may have same service on multiple rows
        sched_slim = sched_slim.drop_duplicates(subset=["service_number"], keep="first")

        # Load planned_trips from service master
        _svc_master_path = os.path.join(_project_root, "data", "master", "service_master.csv")
        if os.path.exists(_svc_master_path):
            try:
                _svc_master = pd.read_csv(_svc_master_path)
                _svc_master.columns = [c.strip().lower().replace(" ", "_") for c in _svc_master.columns]
                _trips_col = next((c for c in ["planned_trips", "trips", "no_of_trips", "num_trips"] if c in _svc_master.columns), None)
                if _trips_col:
                    _svc_slim = _svc_master[["service_number", _trips_col]].copy()
                    _svc_slim["service_number"] = _svc_slim["service_number"].astype(str).str.strip()
                    _svc_slim = _svc_slim.rename(columns={_trips_col: "planned_trips"})
                    # Deduplicate service master too before merging
                    _svc_slim = _svc_slim.drop_duplicates(subset=["service_number"], keep="first")
                    sched_slim = sched_slim.merge(_svc_slim, on="service_number", how="left")
            except Exception:
                pass

        act_cols = ["service_number", "_category"]
        for _c in [actual_pkm_col, actual_kms_col, actual_trips_col, actual_or_col, actual_revenue_col, actual_epk_col, actual_contrib_col]:
            if _c:
                act_cols.append(_c)
        act_slim = act_df[act_cols].copy()
        # Deduplicate actuals at source
        act_slim = act_slim.drop_duplicates(subset=["service_number"], keep="first")
        # Rename revenue in each side before merge to avoid _x/_y suffix collision
        if "revenue" in sched_slim.columns:
            sched_slim = sched_slim.rename(columns={"revenue": "predicted_revenue"})
        if actual_revenue_col == "revenue" and "revenue" in act_slim.columns:
            act_slim = act_slim.rename(columns={"revenue": "actual_revenue"})

        # ── Final safety dedup before merge ────────────────────────────────────
        sched_slim = sched_slim.drop_duplicates(subset=["service_number"], keep="first")
        act_slim   = act_slim.drop_duplicates(subset=["service_number"], keep="first")

        # ── Merge ──────────────────────────────────────────────────────────────
        merged = pd.merge(sched_slim, act_slim, on="service_number", how="outer")
        merged["_category"] = merged["_category"].fillna("Scheduled (No Actuals)")
        # Final safety dedup on merged result
        merged = merged.drop_duplicates(subset=["service_number"], keep="first")

        # Add "Predicted Action" and "Actual Action" columns based on merged data
        if "action" in merged.columns:
            merged["action"] = merged["action"].fillna("—")
            merged["predicted_action"] = merged["action"]
        else:
            merged["predicted_action"] = ""
        
        # ── Derive actual_action – what really happened vs what was predicted ──
        def _derive_actual_action(row):
            action      = str(row.get("action", "")).strip()
            category    = str(row.get("_category", "")).strip()
            has_actuals = pd.notna(row.get("actual_kms")) and pd.to_numeric(row.get("actual_kms"), errors="coerce") > 0

            # Check Extra/New Service category first – these are not in the schedule
            if category == "Extra Service":
                return "Extra Run ➕" if has_actuals else "Not Operated ❌"
            elif category == "New Service":
                return "New Run ➕" if has_actuals else "Not Operated ❌"

            # No actuals at all – service was not operated (except CUT which is expected)
            if not has_actuals:
                return "Cut Executed ✅" if action in ["CUT", "DECREASE", "STOP"] else "Not Operated ❌"

            # Has actuals – now check what actually happened
            if action == "ADD_SLOT":
                actual_trips  = pd.to_numeric(row.get("actual_trips"),  errors="coerce")
                planned_trips = pd.to_numeric(row.get("planned_trips"), errors="coerce")
                if pd.notna(actual_trips) and pd.notna(planned_trips):
                    if actual_trips > planned_trips:
                        return "Slot Added ✅"
                    elif actual_trips < planned_trips:
                        return "Under Operated ⚠️"
                    else:
                        return "Slot Not Added ❌"
                return "Slot Not Added ❌"
            elif action in ["CUT", "DECREASE", "STOP"]:
                return "Not Cut ⚠️"
            elif action == "NO_CHANGE":
                return "Operated ✅"
            elif action == "INCREASE":
                return "Increased ✅"
            else:
                return "Operated ✅"

        merged["actual_action"] = merged.apply(_derive_actual_action, axis=1)

        # ── Helper: format table with Diff % columns ──────────────────────────
        # Column order:
        #   Predicted col | Actual col | Diff %
        # Diff % formula: (Predicted - Actual) / |Predicted| * 100
        #   Positive (▲) → Actual < Predicted  (shortfall)
        #   Negative (▼) → Actual > Predicted  (exceeded prediction)

        def _fmt_expander_table(df_input, include_actions=False, predictions_only=False):
            """Format dataframe for expander tables with Diff % columns.
            
            predictions_only: when True, omits Diff % and actual columns
            since there are no actuals to compare against.
            """
            d = df_input.copy()

            # ── Rename raw columns to display names ────────────────────────────
            rename_map = {
                "service_number":      "Service No.",
                "route":               "Route",
                "product":             "Product",
                "dep_time":            "Dep Time",
                "action":              "Action Taken",
                "actual_action":       "Actual Action",
                "predicted_action":    "Predicted Action",
                "actual_kms":          "Actual KMs",
                "planned_kms":         "Planned KMs",
                "passenger_kms":       "Actual PKM",
                "allocated_pkm":       "Allocated PKM (Predicted)",
                "occupancy_ratio":     "Actual OR",
                "or":                  "Predicted OR",
                "actual_epk":          "Actual EPK",
                "epk":                 "Predicted EPK",
                "actual_contribution": "Actual Contribution",
                "contribution":        "Predicted Contribution",
                "actual_revenue":      "Actual Revenue",
                "predicted_revenue":   "Predicted Revenue",
            }
            # Handle any residual _x/_y suffixes
            if "revenue_x" in d.columns:
                d = d.rename(columns={"revenue_x": "Actual Revenue", "revenue_y": "Predicted Revenue"})
            d = d.rename(columns={k: v for k, v in rename_map.items() if k in d.columns})

            if predictions_only:
                # ── Predictions-only layout: full column set, actual/diff cols injected as blank ──
                full_order = [
                    "Service No.", "Route", "Product", "Dep Time",
                    "Action Taken",
                    "Allocated PKM (Predicted)", "Actual PKM",          "PKM Diff %",
                    "Planned KMs",               "Actual KMs",
                    "Predicted OR",              "Actual OR",           "OR Diff %",
                    "Predicted EPK",             "Actual EPK",          "EPK Diff %",
                    "Predicted Contribution",    "Actual Contribution", "Contribution Diff %",
                    "Predicted Revenue",         "Actual Revenue",      "Revenue Diff %",
                ]
                # Inject any missing columns (actual + diff) as empty strings
                for col in full_order:
                    if col not in d.columns:
                        d[col] = ""
                final_order = [c for c in full_order if c in d.columns]
                d = d[final_order]

                # Format predicted numerics; actual/diff columns stay blank ("")
                int_cols   = ["Planned KMs", "Allocated PKM (Predicted)", "Predicted Contribution", "Predicted Revenue"]
                pct_cols   = ["Predicted OR"]
                float_cols = ["Predicted EPK"]

                for col in d.columns:
                    if col in int_cols:
                        d[col] = pd.to_numeric(d[col], errors="coerce")
                        d[col] = d[col].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "")
                    elif col in pct_cols:
                        d[col] = pd.to_numeric(d[col], errors="coerce")
                        d[col] = d[col].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "")
                    elif col in float_cols:
                        d[col] = pd.to_numeric(d[col], errors="coerce")
                        d[col] = d[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "")

                return d

            # ── Compute Difference % columns BEFORE any formatting ────────────
            diff_pairs = [
                ("Actual PKM",          "Allocated PKM (Predicted)",  "PKM Diff %"),
                ("Actual OR",           "Predicted OR",              "OR Diff %"),
                ("Actual EPK",          "Predicted EPK",             "EPK Diff %"),
                ("Actual Contribution", "Predicted Contribution",    "Contribution Diff %"),
                ("Actual Revenue",      "Predicted Revenue",         "Revenue Diff %"),
            ]

            for actual_col, pred_col, diff_col in diff_pairs:
                if actual_col in d.columns and pred_col in d.columns:
                    act_num  = pd.to_numeric(d[actual_col], errors="coerce")
                    pred_num = pd.to_numeric(d[pred_col],   errors="coerce")
                    d[diff_col] = np.where(
                        pred_num.notna() & act_num.notna() & (pred_num.abs() > 0),
                        (pred_num - act_num) / pred_num.abs() * 100,
                        np.nan
                    )

            # ── Column order – Predicted | Actual | Diff % for each metric ──
            if include_actions:
                base_order = [
                    "Service No.", "Route", "Product", "Dep Time",
                    "Action Taken",
                    "Allocated PKM (Predicted)", "Actual PKM",          "PKM Diff %",
                    "Planned KMs",               "Actual KMs",
                    "Predicted OR",              "Actual OR",           "OR Diff %",
                    "Predicted EPK",             "Actual EPK",          "EPK Diff %",
                    "Predicted Contribution",    "Actual Contribution", "Contribution Diff %",
                    "Predicted Revenue",         "Actual Revenue",      "Revenue Diff %",
                ]
            else:
                base_order = [
                    "Service No.", "Route", "Product", "Dep Time",
                    "Action Taken",
                    "Allocated PKM (Predicted)", "Actual PKM",          "PKM Diff %",
                    "Planned KMs",               "Actual KMs",
                    "Predicted OR",              "Actual OR",           "OR Diff %",
                    "Predicted EPK",             "Actual EPK",          "EPK Diff %",
                    "Predicted Contribution",    "Actual Contribution", "Contribution Diff %",
                    "Predicted Revenue",         "Actual Revenue",      "Revenue Diff %",
                ]

            # Only keep columns that exist in the dataframe
            final_order = [c for c in base_order if c in d.columns]
            d = d[final_order]

            # ── Format numerics ────────────────────────────────────────────────
            int_cols = [
                "Actual KMs", "Planned KMs", "Actual PKM",
                "Allocated PKM (Predicted)", "Actual Contribution",
                "Predicted Contribution", "Predicted Revenue", "Actual Revenue"
            ]
            pct_cols   = ["Actual OR", "Predicted OR"]
            float_cols = ["Actual EPK", "Predicted EPK"]
            diff_cols  = [c for c in d.columns if c.endswith("Diff %")]

            for col in d.columns:
                if col in int_cols:
                    d[col] = pd.to_numeric(d[col], errors="coerce")
                    d[col] = d[col].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "—")
                elif col in pct_cols:
                    d[col] = pd.to_numeric(d[col], errors="coerce")
                    d[col] = d[col].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "—")
                elif col in float_cols:
                    d[col] = pd.to_numeric(d[col], errors="coerce")
                    d[col] = d[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
                elif col in diff_cols:
                    d[col] = pd.to_numeric(d[col], errors="coerce")
                    d[col] = d[col].apply(
                        lambda x: (
                            f" +{x:.1f}%" if pd.notna(x) and x > 0
                            else (f" {x:.1f}%" if pd.notna(x) and x < 0
                            else ("— 0.0%" if pd.notna(x) else "—"))
                        )
                    )

            return d

        # ── Prepare data for each action category ──────────────────────────────
        def get_action_df(action_list):
            return merged[merged["action"].isin(action_list)].copy() if "action" in merged.columns else pd.DataFrame()

        add_slot_data     = get_action_df(["ADD_SLOT", "INCREASE"])
        cut_data          = get_action_df(["CUT", "DECREASE", "STOP"])
        no_change_data    = get_action_df(["NO_CHANGE"])
        extra_svc_data    = merged[merged["_category"] == "Extra Service"].copy()
        new_services_data = merged[merged["_category"] == "New Service"].copy()
        all_combined_data = merged.copy()

        # ── Predictions-only: scheduled services with no actuals recorded ──────
        # These are services present in the schedule but absent from the actuals
        # gold parquet — i.e. they came from sched_slim but not act_slim in the
        # outer merge, leaving all actual-side columns as NaN.
        _actual_indicator_cols = [
            c for c in [actual_kms_col, actual_pkm_col, actual_revenue_col]
            if c is not None and c in merged.columns
        ]
        if _actual_indicator_cols:
            # A row has no actuals when ALL actual indicator columns are NaN
            _no_actuals_mask = merged[_actual_indicator_cols].isnull().all(axis=1)
        else:
            # Fallback: rely on the _category sentinel set during the outer merge
            _no_actuals_mask = merged["_category"] == "Scheduled (No Actuals)"

        # Only include services that came from the schedule (have an action), 
        # not unmatched actuals-only rows
        _has_schedule_mask = merged["action"].notna() & (merged["action"] != "—") \
            if "action" in merged.columns else pd.Series(True, index=merged.index)

        predictions_only_data = merged[_no_actuals_mask & _has_schedule_mask].copy()

        # ── Expanders ──────────────────────────────────────────────────────────

        with st.expander(f"Add Slot  ({len(add_slot_data)} services)", expanded=True):
            if not add_slot_data.empty:
                st.dataframe(_fmt_expander_table(add_slot_data), use_container_width=True, height=300, hide_index=True)
            else:
                st.info("No services in this category.")

        with st.expander(f"Cut({len(cut_data)} services)", expanded=True):
            if not cut_data.empty:
                st.dataframe(_fmt_expander_table(cut_data), use_container_width=True, height=300, hide_index=True)
            else:
                st.info("No services in this category.")

        with st.expander(f"No Change ({len(no_change_data)} services)", expanded=True):
            if not no_change_data.empty:
                st.dataframe(_fmt_expander_table(no_change_data), use_container_width=True, height=300, hide_index=True)
            else:
                st.info("No services in this category.")

        with st.expander(f"Extra Services ({len(extra_svc_data)} services)", expanded=True):
            if not extra_svc_data.empty:
                st.dataframe(_fmt_expander_table(extra_svc_data), use_container_width=True, height=300, hide_index=True)
            else:
                st.info("No extra services found.")

        with st.expander(f"New Services ({len(new_services_data)} services)", expanded=True):
            if not new_services_data.empty:
                st.dataframe(_fmt_expander_table(new_services_data), use_container_width=True, height=300, hide_index=True)
            else:
                st.info("No new services found.")

        # ── NEW: Predictions Only (no actuals received yet) ────────────────────
        with st.expander(
            f"NO Actuals Services ({len(predictions_only_data)} services)",
            expanded=True,
        ):
            if not predictions_only_data.empty:
                st.dataframe(
                    _fmt_expander_table(predictions_only_data, predictions_only=True),
                    use_container_width=True,
                    height=300,
                    hide_index=True,
                )
            else:
                st.info("All scheduled services have actuals recorded. ✅")

        with st.expander(f"Total All Combined ({len(all_combined_data)} services)", expanded=True):
            if not all_combined_data.empty:
                st.dataframe(_fmt_expander_table(all_combined_data, include_actions=True), use_container_width=True, height=400, hide_index=True)
            else:
                st.info("No services available.")

        # ══════════════════════════════════════════════════════════════════════
        # ═══ SECTION 3: HISTORICAL TREND WITH SERVICE SELECTION ═══════════════
        # ══════════════════════════════════════════════════════════════════════

        st.markdown("---")
        st.markdown("Historical Trend (Last 15 Days)")

        # Load historical data
        hist_df = _pva_load_historical(GOLD_SERVICE_PATH, days=15)

        if not hist_df.empty:
            # Detect columns
            date_col_hist    = next((c for c in ["date", "ops_date", "service_date"] if c in hist_df.columns), None)
            depot_col_hist   = next((c for c in ["depot", "depot_name", "depot_code"] if c in hist_df.columns), None)
            service_col_hist = next((c for c in ["service_number", "service_num"]     if c in hist_df.columns), None)

            if date_col_hist and depot_col_hist and service_col_hist:
                # Filter to selected depot
                hist_depot = hist_df[
                    hist_df[depot_col_hist].astype(str).str.upper().str.strip() == selected_depot.upper().strip()
                ].copy()

                if not hist_depot.empty:
                    # ── Calculate EPK on historical data ──────────────────────────
                    if "revenue" in hist_depot.columns and "actual_kms" in hist_depot.columns:
                        hist_depot["actual_epk"] = np.where(
                            pd.to_numeric(hist_depot["actual_kms"], errors="coerce") > 0,
                            pd.to_numeric(hist_depot["revenue"],    errors="coerce") /
                            pd.to_numeric(hist_depot["actual_kms"], errors="coerce"),
                            np.nan
                        )

                    # ── BUG FIX 1 & 2: CPK merge – always join on "service_number",
                    #    drop any pre-existing cpk column first to avoid _x/_y collision ──
                    if "cpk" in pva_sched_df.columns:
                        cpk_lookup_hist = (
                            pva_sched_df[["service_number", "cpk"]]
                            .drop_duplicates(subset=["service_number"])
                            .rename(columns={"service_number": service_col_hist})  # align key name
                        )
                        # Drop cpk if it already exists in hist_depot to prevent _x/_y
                        if "cpk" in hist_depot.columns:
                            hist_depot = hist_depot.drop(columns=["cpk"])
                        hist_depot = hist_depot.merge(cpk_lookup_hist, on=service_col_hist, how="left")
                        if "revenue" in hist_depot.columns and "actual_kms" in hist_depot.columns:
                            hist_depot["actual_contribution"] = np.where(
                                hist_depot["cpk"].notna() &
                                (pd.to_numeric(hist_depot["actual_kms"], errors="coerce") > 0),
                                pd.to_numeric(hist_depot["revenue"],    errors="coerce") - (
                                    pd.to_numeric(hist_depot["cpk"],        errors="coerce") *
                                    pd.to_numeric(hist_depot["actual_kms"], errors="coerce")
                                ),
                                np.nan
                            )

                    hist_depot[date_col_hist] = pd.to_datetime(hist_depot[date_col_hist], errors="coerce")
                    hist_depot = hist_depot.sort_values(date_col_hist)

                    # ── Shared metric selector ─────────────────────────────────────
                    value_options = ["PKM", "EPK", "OR", "Contribution", "KMs", "Revenue"]

                    # ── Helper: map metric name → column in a dataframe ────────────
                    def _metric_col(df, metric):
                        return {
                            "PKM":          next((c for c in ["passenger_kms", "passenger_km", "pkm"] if c in df.columns), None),
                            "EPK":          "actual_epk"          if "actual_epk"          in df.columns else None,
                            "OR":           next((c for c in ["occupancy_ratio", "or"]       if c in df.columns), None),
                            "Contribution": "actual_contribution" if "actual_contribution"  in df.columns else None,
                            "KMs":          next((c for c in ["actual_kms", "actual_km", "kms"] if c in df.columns), None),
                            "Revenue":      next((c for c in ["revenue", "earnings"]          if c in df.columns), None),
                        }.get(metric)

                    # ────────────────────────────────────────────────────────────────
                    # ── PER-SERVICE TREND ─────────────────────────────────────────
                    # ────────────────────────────────────────────────────────────────

                    # Helper: extract predicted value for one service from a schedule df
                    def _get_pred_val(sched_df, svc_str, metric, epk_col, or_col):
                        col_map = {
                            "PKM":          "allocated_pkm",
                            "EPK":          epk_col,
                            "OR":           or_col,
                            "Contribution": "contribution",
                            "KMs":          "planned_kms",
                            "Revenue":      "revenue",
                        }
                        col = col_map.get(metric)
                        if not col or col not in sched_df.columns:
                            return None
                        row = sched_df[sched_df["service_number"].astype(str).str.strip() == svc_str]
                        if row.empty:
                            return None
                        vals = pd.to_numeric(row[col], errors="coerce")
                        v = vals.sum() if metric in ("PKM", "KMs", "Contribution", "Revenue") else vals.mean()
                        return v if pd.notna(v) else None

                    all_services = sorted(hist_depot[service_col_hist].astype(str).unique())

                    col_svc, col_value = st.columns(2)
                    with col_svc:
                        selected_service = st.selectbox(
                            "Select Service Number",
                            all_services,
                            key="trend_service_select"
                        )
                    with col_value:
                        selected_value = st.selectbox(
                            "Select Value Metric",
                            value_options,
                            key="trend_value_select"
                        )

                    _svc_str  = str(selected_service).strip()
                    _is_extra = re.fullmatch(r"[89]\d{3}", _svc_str) is not None
                    _is_new   = _svc_str not in scheduled_svcs and not _is_extra

                    if _is_extra or _is_new:
                        _svc_type = "Extra" if _is_extra else "New"
                        st.info(
                            f"Service **{selected_service}** is an {_svc_type} Service — "
                            "no predicted data is available for this service."
                        )
                    else:
                        svc_hist = hist_depot[
                            hist_depot[service_col_hist].astype(str).str.strip() == _svc_str
                        ].copy()

                        if not svc_hist.empty:
                            actual_col = _metric_col(svc_hist, selected_value)

                            if actual_col and actual_col in svc_hist.columns:
                                chart_data = svc_hist[[date_col_hist, actual_col]].copy()
                                chart_data[actual_col] = pd.to_numeric(chart_data[actual_col], errors="coerce")
                                chart_data = chart_data.dropna(subset=[actual_col])

                                if not chart_data.empty:
                                    # Build predicted series – one value per date by loading each schedule file
                                    pred_dates, pred_values = [], []
                                    for d in chart_data[date_col_hist]:
                                        d_str = pd.Timestamp(d).strftime("%Y-%m-%d")
                                        try:
                                            day_scheds, _ = load_schedule_for_date(d_str, SCHEDULE_DIR, depot=selected_depot)
                                            if selected_depot in day_scheds:
                                                _df = day_scheds[selected_depot].copy()
                                                _df.columns = [c.strip().lower().replace(" ", "_") for c in _df.columns]
                                                _epk = next((c for c in ["epk", "allocated_epk"] if c in _df.columns), None)
                                                _or  = next((c for c in ["or", "planned_or"]     if c in _df.columns), None)
                                                v = _get_pred_val(_df, _svc_str, selected_value, _epk, _or)
                                                if v is not None:
                                                    pred_dates.append(d)
                                                    pred_values.append(v)
                                        except Exception:
                                            continue

                                    fig_svc = go.Figure()

                                    # Actual line – orange
                                    fig_svc.add_trace(go.Scatter(
                                        x=chart_data[date_col_hist],
                                        y=chart_data[actual_col],
                                        mode="lines+markers",
                                        name="Actual",
                                        line=dict(color="#dd8452", width=2),
                                        marker=dict(size=6),
                                    ))

                                    # Predicted line – blue dashed, one point per date
                                    if pred_dates:
                                        fig_svc.add_trace(go.Scatter(
                                            x=pred_dates,
                                            y=pred_values,
                                            mode="lines+markers",
                                            name="Predicted",
                                            line=dict(color="#4c72b0", width=2, dash="dash"),
                                            marker=dict(size=6),
                                        ))

                                    fig_svc.update_layout(
                                        title=f"Service {selected_service} — {selected_value} (Last 15 Days)",
                                        xaxis_title="Date",
                                        yaxis_title=selected_value,
                                        hovermode="x unified",
                                        legend=dict(
                                            orientation="v",
                                            yanchor="middle",
                                            y=0.5,
                                            xanchor="left",
                                            x=1.02,
                                            font=dict(size=12),
                                            bgcolor="rgba(255,255,255,0.8)",
                                            bordercolor="#cccccc",
                                            borderwidth=1,
                                        ),
                                        height=480,
                                        margin=dict(l=60, r=180, t=60, b=60),
                                        template="plotly_white"
                                    )
                                    st.plotly_chart(fig_svc, use_container_width=True)
                                else:
                                    st.warning(f"No actual data available for service {selected_service} — {selected_value}.")
                            else:
                                st.warning(f"Metric {selected_value} not available for service {selected_service}.")
                        else:
                            st.warning(f"No historical data found for service {selected_service}.")

                else:
                    st.info("No historical data available for the selected depot.")
            else:
                st.info("Historical data structure not compatible.")
        else:
            st.info("Historical data not available. Please ensure historical records are processed.")
