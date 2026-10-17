"""Tests for supply_scheduling.py — policy engine, service adjustments."""

import pytest
import pandas as pd
import numpy as np
from datetime import date, time, timedelta
from pathlib import Path

from dynamic_scheduling.supply_scheduling import (
    clean_service_master,
    clean_daily_ops,
    parse_time_safe,
    is_peak_hour,
    compute_recent_or,
    compute_depot_planned_kms,
    compute_target_kms,
    run_policy_engine,
    run_all_depots,
    compute_service_weights,
    compute_rev_per_pkm,
    find_slot_midpoint,
    run_epk_policy_engine,
    run_all_depots_epk,
    load_epk_policy,
    classify_epk_or_quadrant,
    POLICY,
    EPK_POLICY,
)


# =========================================================================
# Data cleaning
# =========================================================================


class TestCleanServiceMaster:

    def test_fills_missing_depot(self):
        df = pd.DataFrame({
            "service_number": ["S1"],
            "planned_trips": [4],
            "planned_kms": [200],
            "avg_seats_per_bus": [45],
        })
        out = clean_service_master(df)
        assert out["depot"].iloc[0] == "DEFAULT"

    def test_computes_km_per_trip(self):
        df = pd.DataFrame({
            "depot": ["D1"],
            "service_number": ["S1"],
            "planned_trips": [4],
            "planned_kms": [200.0],
            "avg_seats_per_bus": [45],
        })
        out = clean_service_master(df)
        assert out["km_per_trip"].iloc[0] == pytest.approx(50.0)

    def test_handles_zero_planned_trips(self):
        df = pd.DataFrame({
            "depot": ["D1"],
            "service_number": ["S1"],
            "planned_trips": [0],
            "planned_kms": [0.0],
            "avg_seats_per_bus": [45],
        })
        out = clean_service_master(df)
        # km_per_trip should be 0 or NaN→0 (from fillna)
        assert np.isfinite(out["km_per_trip"].iloc[0])

    def test_strips_whitespace(self):
        df = pd.DataFrame({
            "depot": [" D1 "],
            "service_number": [" S1 "],
            "planned_trips": [4],
            "planned_kms": [200],
            "avg_seats_per_bus": [45],
        })
        out = clean_service_master(df)
        assert out["depot"].iloc[0] == "D1"
        assert out["service_number"].iloc[0] == "S1"


class TestCleanDailyOps:

    def test_coerces_numeric_columns(self):
        df = pd.DataFrame({
            "depot": ["D1"],
            "service_number": ["S1"],
            "date": ["2025-11-30"],
            "actual_kms": ["200.5"],
            "actual_trips": ["4"],
            "seat_kms": ["9000"],
            "passenger_kms": ["6750"],
            "occupancy_ratio": ["0.75"],
        })
        out = clean_daily_ops(df)
        assert out["actual_kms"].dtype == np.float64
        assert pd.api.types.is_datetime64_any_dtype(out["date"])


# =========================================================================
# Time helpers
# =========================================================================


class TestParseTimeSafe:

    def test_parses_string(self):
        assert parse_time_safe("08:30") == time(8, 30)

    def test_returns_time_object_unchanged(self):
        t = time(14, 0)
        assert parse_time_safe(t) is t

    def test_returns_none_for_na(self):
        assert parse_time_safe(None) is None
        assert parse_time_safe(np.nan) is None

    def test_returns_none_for_bad_string(self):
        assert parse_time_safe("not_a_time") is None


class TestIsPeakHour:

    def test_morning_peak(self):
        assert is_peak_hour("07:00", POLICY) is True
        assert is_peak_hour("09:30", POLICY) is True

    def test_evening_peak(self):
        assert is_peak_hour("17:00", POLICY) is True
        assert is_peak_hour("20:00", POLICY) is True

    def test_off_peak(self):
        assert is_peak_hour("12:00", POLICY) is False
        assert is_peak_hour("15:00", POLICY) is False

    def test_none_is_not_peak(self):
        assert is_peak_hour(None, POLICY) is False


# =========================================================================
# Occupancy ratio computation
# =========================================================================


class TestComputeRecentOR:

    def test_returns_mean_per_service(self, daily_ops_df):
        result = compute_recent_or(daily_ops_df, "CONTONMENT", date(2025, 11, 30), 7)
        assert isinstance(result, pd.Series)
        assert len(result) > 0
        # All values should be between 0 and 1
        assert (result >= 0).all()
        assert (result <= 1.5).all()

    def test_empty_for_unknown_depot(self, daily_ops_df):
        result = compute_recent_or(daily_ops_df, "NONEXISTENT", date(2025, 11, 30), 7)
        assert len(result) == 0


# =========================================================================
# KM computations
# =========================================================================


class TestComputeDepotPlannedKms:

    def test_sums_trips_times_kmpt(self, service_master_df):
        kms = compute_depot_planned_kms(service_master_df, "CONTONMENT")
        # 3 services × 4 trips × 50 km_per_trip = 600
        assert kms == pytest.approx(600.0)

    def test_zero_for_unknown_depot(self, service_master_df):
        kms = compute_depot_planned_kms(service_master_df, "NONEXISTENT")
        assert kms == 0.0


class TestComputeTargetKms:

    def test_basic_calculation(self):
        # predicted_pkm=100000, avg_seats=45, target_or=0.75
        # target_seat_km = 100000 / 0.75 = 133333.33
        # target_kms = 133333.33 / 45 = 2962.96
        result = compute_target_kms(100000.0, 45.0, 0.75)
        assert result == pytest.approx(2962.96, rel=0.01)

    def test_zero_seats_uses_default(self):
        result = compute_target_kms(100000.0, 0.0, 0.75)
        expected = 100000.0 / 0.75 / 45.0  # falls back to 45
        assert result == pytest.approx(expected, rel=0.01)

    def test_zero_or_safe(self):
        # target_or near zero should not crash
        result = compute_target_kms(100000.0, 45.0, 0.0)
        assert np.isfinite(result)


# =========================================================================
# Policy engine
# =========================================================================


class TestRunPolicyEngine:

    def test_no_change_within_tolerance(self, service_master_df, daily_ops_df):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)

        # Set predicted PKM so that target_kms ≈ planned_kms → within tolerance
        depot = "CONTONMENT"
        planned_kms = compute_depot_planned_kms(sm, depot)
        avg_seats = sm[sm["depot"] == depot]["avg_seats_per_bus"].mean()
        # Reverse-engineer PKM that produces exactly planned_kms as target
        predicted_pkm = planned_kms * avg_seats * POLICY["target_or"]

        schedule, summary = run_policy_engine(
            sm, ops, depot, date(2025, 11, 30), predicted_pkm, POLICY,
        )
        assert summary["action_taken"] is False
        assert (schedule["action"] == "NO_CHANGE").all()

    def test_increase_when_demand_high(self, service_master_df, daily_ops_df):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        depot = "CONTONMENT"

        # Huge demand → engine should try adding trips
        schedule, summary = run_policy_engine(
            sm, ops, depot, date(2025, 11, 30),
            predicted_depot_pkm=50_000_000.0,
            policy=POLICY,
        )
        assert summary["action_taken"] is True
        assert summary["delta_kms"] > 0
        if summary["count_increase"] > 0:
            assert (schedule[schedule["action"] == "INCREASE"]["trip_change"] > 0).all()

    def test_decrease_when_demand_low(self, service_master_df, daily_ops_df):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        depot = "CONTONMENT"

        # Tiny demand → engine should try cutting trips
        schedule, summary = run_policy_engine(
            sm, ops, depot, date(2025, 11, 30),
            predicted_depot_pkm=1.0,
            policy=POLICY,
        )
        assert summary["action_taken"] is True
        assert summary["delta_kms"] < 0

    def test_empty_depot_returns_error(self, service_master_df, daily_ops_df):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        schedule, summary = run_policy_engine(
            sm, ops, "NONEXISTENT", date(2025, 11, 30), 100000.0, POLICY,
        )
        assert "error" in summary

    def test_max_trip_change_respected(self, service_master_df, daily_ops_df):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        depot = "CONTONMENT"

        schedule, summary = run_policy_engine(
            sm, ops, depot, date(2025, 11, 30),
            predicted_depot_pkm=50_000_000.0,
            policy=POLICY,
        )
        max_change = POLICY["max_trip_change_per_service"]
        assert schedule["trip_change"].abs().max() <= max_change + schedule["planned_trips"].max()

    def test_output_columns(self, service_master_df, daily_ops_df):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        schedule, _ = run_policy_engine(
            sm, ops, "CONTONMENT", date(2025, 11, 30), 100000.0, POLICY,
        )
        for col in ["service_number", "planned_trips", "suggested_trips",
                     "trip_change", "kms_change", "action", "reason"]:
            assert col in schedule.columns

    def test_summary_keys(self, service_master_df, daily_ops_df):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        _, summary = run_policy_engine(
            sm, ops, "CONTONMENT", date(2025, 11, 30), 100000.0, POLICY,
        )
        for key in ["depot", "target_date", "predicted_depot_pkm",
                     "depot_planned_kms", "depot_target_kms", "delta_kms",
                     "action_taken", "total_kms_change",
                     "count_increase", "count_decrease", "count_stop", "count_no_change"]:
            assert key in summary


# =========================================================================
# Multi-depot runner
# =========================================================================


class TestRunAllDepots:

    def test_produces_schedules_for_all_depots(self, service_master_df, daily_ops_df, tmp_output):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        depot_predictions = {"CONTONMENT": 500_000.0, "KARIMNAGAR-I": 300_000.0}
        target = date(2025, 11, 30)
        output_dir = tmp_output / "dynamic_schedule"

        summaries, consolidated = run_all_depots(
            sm, ops, target, depot_predictions, POLICY, output_dir,
        )
        assert len(summaries) == 2
        assert "CONTONMENT" in summaries
        assert "KARIMNAGAR-I" in summaries
        assert len(consolidated) > 0
        assert "depot" in consolidated.columns

    def test_writes_xlsx_and_json(self, service_master_df, daily_ops_df, tmp_output):
        sm = clean_service_master(service_master_df)
        ops = clean_daily_ops(daily_ops_df)
        depot_predictions = {"CONTONMENT": 500_000.0}
        target = date(2025, 11, 30)
        output_dir = tmp_output / "dynamic_schedule"

        run_all_depots(sm, ops, target, depot_predictions, POLICY, output_dir)
        date_dir = output_dir / "2025-11-30"
        assert date_dir.exists()
        xlsx_files = list(date_dir.glob("schedule_*.xlsx"))
        json_files = list(date_dir.glob("summary_*.json"))
        assert len(xlsx_files) >= 1
        assert len(json_files) >= 1

    def test_skips_depot_with_no_services(self, daily_ops_df, tmp_output):
        sm = clean_service_master(pd.DataFrame({
            "depot": ["ONLY_DEPOT"],
            "service_number": ["S1"],
            "planned_trips": [4],
            "planned_kms": [200],
            "avg_seats_per_bus": [45],
        }))
        ops = clean_daily_ops(daily_ops_df)
        depot_predictions = {"CONTONMENT": 500_000.0}  # no services for this depot in sm
        target = date(2025, 11, 30)
        output_dir = tmp_output / "dynamic_schedule"

        summaries, consolidated = run_all_depots(
            sm, ops, target, depot_predictions, POLICY, output_dir,
        )
        # CONTONMENT not in service master → error → skipped
        assert "CONTONMENT" not in summaries


# =========================================================================
# Policy configuration sanity
# =========================================================================


class TestPolicyConfig:

    def test_policy_has_required_keys(self):
        required = [
            "target_or", "tolerance_pct", "lookback_days",
            "max_trip_change_per_service", "min_trips_per_service",
            "underutilized_or", "overloaded_or", "stop_or",
            "morning_peak", "evening_peak",
            "prefer_peak_when_adding", "protect_peak_when_cutting",
            "max_changes_per_route", "max_services_changed",
        ]
        for key in required:
            assert key in POLICY, f"Missing policy key: {key}"

    def test_target_or_in_valid_range(self):
        assert 0 < POLICY["target_or"] < 1.0

    def test_stop_or_below_target(self):
        assert POLICY["stop_or"] < POLICY["target_or"]

    def test_peak_times_are_time_tuples(self):
        for key in ["morning_peak", "evening_peak"]:
            start, end = POLICY[key]
            assert isinstance(start, time)
            assert isinstance(end, time)
            assert start < end


# =========================================================================
# EPK-OR quadrant classifier
# =========================================================================


class TestClassifyEpkOrQuadrant:

    def test_undersupply(self):
        """Profitable + high OR → UNDERSUPPLY."""
        assert classify_epk_or_quadrant(epk=30, cpk=25, or_val=0.80) == "UNDERSUPPLY"

    def test_oversupply(self):
        """Profitable + low OR → OVERSUPPLY."""
        assert classify_epk_or_quadrant(epk=30, cpk=25, or_val=0.50) == "OVERSUPPLY"

    def test_social_obligation(self):
        """Unprofitable + high OR → SOCIAL_OBLIGATION."""
        assert classify_epk_or_quadrant(epk=20, cpk=25, or_val=0.80) == "SOCIAL_OBLIGATION"

    def test_inefficient(self):
        """Unprofitable + low OR → INEFFICIENT."""
        assert classify_epk_or_quadrant(epk=20, cpk=25, or_val=0.50) == "INEFFICIENT"

    def test_boundary_epk_equals_cpk(self):
        """EPK == CPK is considered profitable (>=)."""
        assert classify_epk_or_quadrant(epk=25, cpk=25, or_val=0.80) == "UNDERSUPPLY"

    def test_boundary_or_equals_boundary(self):
        """OR == boundary is considered high OR (>=)."""
        assert classify_epk_or_quadrant(epk=30, cpk=25, or_val=0.70) == "UNDERSUPPLY"

    def test_custom_or_boundary(self):
        """Custom or_boundary changes classification."""
        # With boundary=0.60, OR=0.65 is high
        assert classify_epk_or_quadrant(epk=30, cpk=25, or_val=0.65, or_boundary=0.60) == "UNDERSUPPLY"
        # With boundary=0.80, OR=0.65 is low
        assert classify_epk_or_quadrant(epk=30, cpk=25, or_val=0.65, or_boundary=0.80) == "OVERSUPPLY"


# =========================================================================
# EPK engine — service weights
# =========================================================================


class TestComputeServiceWeights:

    def test_weights_sum_to_one(self, daily_ops_with_revenue_df):
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        weights = compute_service_weights(ops, "SIDDIPET", date(2025, 11, 30), 15)
        assert len(weights) > 0
        assert weights.sum() == pytest.approx(1.0, abs=1e-9)

    def test_weights_non_negative(self, daily_ops_with_revenue_df):
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        weights = compute_service_weights(ops, "SIDDIPET", date(2025, 11, 30), 15)
        assert (weights >= 0).all()

    def test_empty_depot_returns_empty(self, daily_ops_with_revenue_df):
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        weights = compute_service_weights(ops, "NONEXISTENT", date(2025, 11, 30), 15)
        assert len(weights) == 0

    def test_zero_pkm_returns_zero_weights(self):
        """If all passenger_kms are 0, weights should all be 0."""
        df = pd.DataFrame({
            "depot": ["D1"] * 4,
            "date": pd.to_datetime(["2025-11-28", "2025-11-28", "2025-11-29", "2025-11-29"]),
            "service_number": ["S1", "S2", "S1", "S2"],
            "passenger_kms": [0.0, 0.0, 0.0, 0.0],
        })
        weights = compute_service_weights(df, "D1", date(2025, 11, 30), 15)
        assert (weights == 0).all()


# =========================================================================
# EPK engine — revenue per pkm
# =========================================================================


class TestComputeRevPerPkm:

    def test_returns_series(self, daily_ops_with_revenue_df):
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        result = compute_rev_per_pkm(ops, "SIDDIPET", date(2025, 11, 30), 15)
        assert isinstance(result, pd.Series)
        assert len(result) > 0

    def test_no_revenue_column_returns_empty(self, daily_ops_no_revenue_df):
        ops = clean_daily_ops(daily_ops_no_revenue_df)
        result = compute_rev_per_pkm(ops, "SIDDIPET", date(2025, 11, 30), 15)
        assert len(result) == 0

    def test_zero_pkm_excluded(self):
        """Services with 0 passenger_kms should be excluded from rev/pkm calc."""
        df = pd.DataFrame({
            "depot": ["D1", "D1"],
            "date": pd.to_datetime(["2025-11-28", "2025-11-28"]),
            "service_number": ["S1", "S2"],
            "passenger_kms": [0.0, 1000.0],
            "revenue": [500.0, 2000.0],
        })
        result = compute_rev_per_pkm(df, "D1", date(2025, 11, 30), 15)
        # S1 (pkm=0) should not be in result
        assert "S1" not in result.index
        assert "S2" in result.index


# =========================================================================
# EPK engine — find slot midpoint
# =========================================================================


class TestFindSlotMidpoint:

    def test_midpoint_between_services(self, service_master_with_route_df):
        sm = clean_service_master(service_master_with_route_df)
        # SP-1 departs 06:00, SP-2 departs 08:00 → midpoint 07:00
        mid = find_slot_midpoint(sm, "SIDDIPET", "SDPT-HYD", "06:00")
        assert mid == time(7, 0)

    def test_last_departure_returns_none(self, service_master_with_route_df):
        sm = clean_service_master(service_master_with_route_df)
        # SP-3 is last departure (10:00) on SDPT-HYD route
        mid = find_slot_midpoint(sm, "SIDDIPET", "SDPT-HYD", "10:00")
        assert mid is None

    def test_single_service_returns_none(self):
        sm = clean_service_master(pd.DataFrame({
            "depot": ["D1"],
            "service_number": ["S1"],
            "route": ["R1"],
            "product": ["EXP"],
            "dep_time": ["08:00"],
            "planned_trips": [4],
            "planned_kms": [200],
            "avg_seats_per_bus": [45],
        }))
        mid = find_slot_midpoint(sm, "D1", "R1", "08:00")
        assert mid is None

    def test_different_route_not_found(self, service_master_with_route_df):
        sm = clean_service_master(service_master_with_route_df)
        mid = find_slot_midpoint(sm, "SIDDIPET", "NO_ROUTE", "06:00")
        assert mid is None


# =========================================================================
# EPK engine — run_epk_policy_engine
# =========================================================================


class TestRunEpkPolicyEngine:

    def test_expected_columns(self, service_master_with_route_df, daily_ops_with_revenue_df):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        schedule, _ = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 500_000.0, EPK_POLICY,
        )
        for col in ["service_number", "allocated_pkm", "revenue", "epk",
                     "or", "cpk", "quadrant", "contribution",
                     "action", "suggested_new_slot", "reason"]:
            assert col in schedule.columns, f"Missing column: {col}"

    def test_quadrant_column_values(self, service_master_with_route_df, daily_ops_with_revenue_df):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        schedule, _ = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 500_000.0, EPK_POLICY,
        )
        valid = {"UNDERSUPPLY", "OVERSUPPLY", "SOCIAL_OBLIGATION", "INEFFICIENT"}
        assert set(schedule["quadrant"].unique()).issubset(valid)

    def test_contribution_column(self, service_master_with_route_df, daily_ops_with_revenue_df):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        schedule, _ = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 500_000.0, EPK_POLICY,
        )
        assert "contribution" in schedule.columns
        # contribution = revenue - cpk * planned_kms — should be finite
        assert schedule["contribution"].notna().all()

    def test_summary_keys(self, service_master_with_route_df, daily_ops_with_revenue_df):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        _, summary = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 500_000.0, EPK_POLICY,
        )
        for key in ["depot", "target_date", "predicted_depot_pkm",
                     "total_services", "count_add_slot", "count_cut",
                     "count_no_change", "total_allocated_pkm",
                     "quadrant_counts", "quadrant_pcts",
                     "total_revenue", "total_contribution", "total_planned_kms",
                     "depot_avg_epk", "depot_avg_or",
                     "revenue_by_quadrant", "contribution_by_quadrant"]:
            assert key in summary, f"Missing summary key: {key}"

    def test_quadrant_counts_in_summary(self, service_master_with_route_df, daily_ops_with_revenue_df):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        _, summary = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 500_000.0, EPK_POLICY,
        )
        qc = summary["quadrant_counts"]
        assert isinstance(qc, dict)
        assert sum(qc.values()) == summary["total_services"]

    def test_empty_depot(self, service_master_with_route_df, daily_ops_with_revenue_df):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        _, summary = run_epk_policy_engine(
            sm, ops, "NONEXISTENT", date(2025, 11, 30), 500_000.0, EPK_POLICY,
        )
        assert "error" in summary

    def test_allocated_pkm_sums_to_forecast(self, service_master_with_route_df, daily_ops_with_revenue_df):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        forecast = 500_000.0
        schedule, _ = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), forecast, EPK_POLICY,
        )
        # allocated_pkm should sum to forecast (since weights sum to 1)
        assert schedule["allocated_pkm"].sum() == pytest.approx(forecast, rel=0.01)

    def test_no_revenue_fallback(self, service_master_with_route_df, daily_ops_no_revenue_df):
        """Without revenue data, rev_per_pkm defaults to 0 → EPK=0 → no ADD_SLOT."""
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_no_revenue_df)
        schedule, summary = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 500_000.0, EPK_POLICY,
        )
        # With EPK=0, no service should be ADD_SLOT
        assert summary["count_add_slot"] == 0

    def test_high_or_and_epk_triggers_add_slot(self, service_master_with_route_df):
        """Craft data so that OR > threshold_add and EPK > premium*CPK → ADD_SLOT."""
        sm = clean_service_master(service_master_with_route_df)
        # Build ops where SP-1 has very high pkm and very high revenue
        dates = pd.date_range("2025-11-15", periods=15, freq="D")
        rows = []
        for d in dates:
            rows.append({
                "depot": "SIDDIPET", "date": d, "service_number": "SP-1",
                "passenger_kms": 50000.0, "revenue": 200000.0,
                "actual_kms": 200, "actual_trips": 4,
                "seat_kms": 9000, "occupancy_ratio": 0.9,
            })
            # Other services have minimal data
            for svc in ["SP-2", "SP-3", "SP-4", "SP-5"]:
                rows.append({
                    "depot": "SIDDIPET", "date": d, "service_number": svc,
                    "passenger_kms": 100.0, "revenue": 10.0,
                    "actual_kms": 100, "actual_trips": 2,
                    "seat_kms": 4500, "occupancy_ratio": 0.2,
                })
        ops = clean_daily_ops(pd.DataFrame(rows))
        ops["date"] = pd.to_datetime(ops["date"])
        # Large forecast so SP-1 gets most allocation
        schedule, summary = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 5_000_000.0, EPK_POLICY,
        )
        assert summary["count_add_slot"] >= 1
        add_rows = schedule[schedule["action"] == "ADD_SLOT"]
        assert len(add_rows) >= 1

    def test_low_or_and_epk_triggers_cut(self, service_master_with_route_df):
        """Craft data so that OR < threshold_cut and EPK < discount*CPK → CUT."""
        sm = clean_service_master(service_master_with_route_df)
        dates = pd.date_range("2025-11-15", periods=15, freq="D")
        rows = []
        for d in dates:
            for svc in ["SP-1", "SP-2", "SP-3", "SP-4", "SP-5"]:
                rows.append({
                    "depot": "SIDDIPET", "date": d, "service_number": svc,
                    "passenger_kms": 10.0, "revenue": 1.0,
                    "actual_kms": 100, "actual_trips": 2,
                    "seat_kms": 4500, "occupancy_ratio": 0.1,
                })
        ops = clean_daily_ops(pd.DataFrame(rows))
        ops["date"] = pd.to_datetime(ops["date"])
        # Tiny forecast → very low OR and EPK
        schedule, summary = run_epk_policy_engine(
            sm, ops, "SIDDIPET", date(2025, 11, 30), 100.0, EPK_POLICY,
        )
        assert summary["count_cut"] >= 1
        cut_rows = schedule[schedule["action"] == "CUT"]
        assert len(cut_rows) >= 1


# =========================================================================
# EPK engine — run_all_depots_epk
# =========================================================================


class TestRunAllDepotsEpk:

    def test_produces_output(self, service_master_with_route_df, daily_ops_with_revenue_df, tmp_output):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        depot_predictions = {"SIDDIPET": 500_000.0}
        target = date(2025, 11, 30)
        output_dir = tmp_output / "dynamic_schedule"

        summaries, consolidated = run_all_depots_epk(
            sm, ops, target, depot_predictions, EPK_POLICY, output_dir,
        )
        assert "SIDDIPET" in summaries
        assert len(consolidated) > 0

    def test_writes_xlsx_and_json(self, service_master_with_route_df, daily_ops_with_revenue_df, tmp_output):
        sm = clean_service_master(service_master_with_route_df)
        ops = clean_daily_ops(daily_ops_with_revenue_df)
        depot_predictions = {"SIDDIPET": 500_000.0}
        target = date(2025, 11, 30)
        output_dir = tmp_output / "dynamic_schedule"

        run_all_depots_epk(sm, ops, target, depot_predictions, EPK_POLICY, output_dir)
        date_dir = output_dir / "2025-11-30"
        assert date_dir.exists()
        xlsx_files = list(date_dir.glob("epk_schedule_*.xlsx"))
        json_files = list(date_dir.glob("epk_summary_*.json"))
        assert len(xlsx_files) >= 1
        assert len(json_files) >= 1
