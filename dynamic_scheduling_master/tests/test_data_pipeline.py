"""Tests for data_pipeline.py — inbound validation, RAW upsert, GOLD build."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date, datetime

from dynamic_scheduling.data_pipeline import (
    validate_filename_format,
    extract_date_from_filename,
    validate_not_future_date,
    validate_date_consistency,
    validate_depot_inbound,
    validate_service_inbound,
    coerce_depot_types,
    coerce_service_types,
    upsert_depot_raw_master,
    upsert_service_raw_master,
    build_depot_gold,
    build_service_gold,
    load_holiday_calendar_long,
    update_predictions_with_actuals,
    load_service_raw_master,
    INBOUND_COLUMNS,
    SERVICE_INBOUND_COLUMNS,
    SERVICE_RAW_COLUMNS,
    SERVICE_GOLD_COLUMNS,
    SERVICE_BOUNDS,
    ALLOWED_DEPOTS,
    GOLD_COLUMNS,
    RAW_COLUMNS,
)


# =========================================================================
# Filename validation
# =========================================================================


class TestFilenameValidation:

    def test_valid_depot_filename(self, tmp_path):
        fp = tmp_path / "ops_daily_2025-11-30.csv"
        fp.touch()
        ok, ftype, err = validate_filename_format(fp)
        assert ok is True
        assert ftype == "depot"
        assert err is None

    def test_valid_service_filename(self, tmp_path):
        fp = tmp_path / "ops_daily_service_2025-11-30.csv"
        fp.touch()
        ok, ftype, err = validate_filename_format(fp)
        assert ok is True
        assert ftype == "service"

    def test_invalid_filename_rejected(self, tmp_path):
        fp = tmp_path / "random_data.csv"
        fp.touch()
        ok, ftype, err = validate_filename_format(fp)
        assert ok is False
        assert ftype == "unknown"
        assert err is not None

    def test_extract_date_depot(self):
        d = extract_date_from_filename("ops_daily_2025-03-15.csv", "depot")
        assert d == date(2025, 3, 15)

    def test_extract_date_service(self):
        d = extract_date_from_filename("ops_daily_service_2025-03-15.csv", "service")
        assert d == date(2025, 3, 15)

    def test_extract_date_bad_format(self):
        d = extract_date_from_filename("bad_filename.csv", "depot")
        assert d is None


# =========================================================================
# Date validation
# =========================================================================


class TestDateValidation:

    def test_past_date_valid(self):
        ok, err = validate_not_future_date(date(2020, 1, 1))
        assert ok is True
        assert err is None

    def test_future_date_rejected(self):
        future = date.today() + pd.Timedelta(days=5).to_pytimedelta()
        ok, err = validate_not_future_date(future)
        assert ok is False
        assert "Future date" in err

    def test_date_consistency_match(self, tmp_path):
        fp = tmp_path / "ops_daily_2025-06-01.csv"
        fp.touch()
        ok, err = validate_date_consistency(fp, date(2025, 6, 1), "depot")
        assert ok is True

    def test_date_consistency_mismatch(self, tmp_path):
        fp = tmp_path / "ops_daily_2025-06-01.csv"
        fp.touch()
        ok, err = validate_date_consistency(fp, date(2025, 6, 2), "depot")
        assert ok is False
        assert "mismatch" in err.lower()


# =========================================================================
# Depot inbound validation
# =========================================================================


class TestDepotInboundValidation:

    def test_valid_depot_inbound_passes(self, inbound_depot_df):
        errors = validate_depot_inbound(inbound_depot_df)
        assert errors == []

    def test_missing_column_detected(self, inbound_depot_df):
        df = inbound_depot_df.drop(columns=["occupancy_ratio"])
        errors = validate_depot_inbound(df)
        assert any("Missing" in e for e in errors)

    def test_null_depot_detected(self, inbound_depot_df):
        df = inbound_depot_df.copy()
        df.loc[0, "depot"] = None
        errors = validate_depot_inbound(df)
        assert any("Null depot" in e for e in errors)

    def test_unknown_depot_detected(self):
        df = pd.DataFrame({
            "depot": ["CONTONMENT", "UNKNOWN_DEPOT", "NIZAMABAD-I", "WARANGAL-I"],
            "date": pd.to_datetime("2025-11-30"),
            "passengers_per_day": [1, 2, 3, 4],
            "actual_kms": [1, 2, 3, 4],
            "occupancy_ratio": [0.8, 0.8, 0.8, 0.8],
        })
        errors = validate_depot_inbound(df)
        assert any("Unknown depots" in e for e in errors)

    def test_multiple_dates_rejected(self, depot_list):
        df = pd.DataFrame({
            "depot": depot_list,
            "date": pd.to_datetime(["2025-11-30", "2025-12-01", "2025-11-30", "2025-11-30"]),
            "passengers_per_day": [1, 2, 3, 4],
            "actual_kms": [1, 2, 3, 4],
            "occupancy_ratio": [0.8, 0.8, 0.8, 0.8],
        })
        errors = validate_depot_inbound(df)
        assert any("exactly one date" in e for e in errors)

    def test_negative_passengers_flagged(self, inbound_depot_df):
        df = inbound_depot_df.copy()
        df.loc[0, "passengers_per_day"] = -100
        errors = validate_depot_inbound(df)
        assert any("passengers_per_day" in e for e in errors)

    def test_occupancy_above_bound_flagged(self, inbound_depot_df):
        df = inbound_depot_df.copy()
        df.loc[0, "occupancy_ratio"] = 2.5
        errors = validate_depot_inbound(df)
        assert any("occupancy_ratio" in e for e in errors)


# =========================================================================
# Service inbound validation
# =========================================================================


class TestServiceInboundValidation:

    def _make_service_df(self):
        return pd.DataFrame({
            "depot": ["CONTONMENT"] * 2,
            "date": pd.to_datetime("2025-11-30"),
            "service_number": ["SVC-001", "SVC-002"],
            "actual_kms": [200.0, 300.0],
            "actual_trips": [4, 5],
            "seat_kms": [9000.0, 13500.0],
            "passenger_kms": [6750.0, 10125.0],
            "occupancy_ratio": [0.75, 0.75],
        })

    def test_valid_service_inbound_passes(self):
        df = self._make_service_df()
        errors = validate_service_inbound(df)
        assert errors == []

    def test_missing_service_column(self):
        df = self._make_service_df().drop(columns=["service_number"])
        errors = validate_service_inbound(df)
        assert any("Missing" in e for e in errors)

    def test_duplicate_service_key_detected(self):
        df = self._make_service_df()
        df.loc[1, "service_number"] = "SVC-001"  # duplicate key
        errors = validate_service_inbound(df)
        assert any("Duplicate" in e for e in errors)


# =========================================================================
# Type coercion
# =========================================================================


class TestTypeCoercion:

    def test_coerce_depot_types_parses_date(self):
        df = pd.DataFrame({
            "depot": ["CONTONMENT"],
            "date": ["30/11/2025"],
            "passengers_per_day": ["100000"],
            "actual_kms": ["40000"],
            "occupancy_ratio": ["0.82"],
        })
        out = coerce_depot_types(df)
        assert pd.api.types.is_datetime64_any_dtype(out["date"])
        assert np.issubdtype(out["passengers_per_day"].dtype, np.number)

    def test_coerce_service_types_strips_whitespace(self):
        df = pd.DataFrame({
            "depot": [" CONTONMENT "],
            "date": ["30/11/2025"],
            "service_number": [" SVC-001 "],
            "actual_kms": [200],
            "actual_trips": [4],
            "seat_kms": [9000],
            "passenger_kms": [6750],
            "occupancy_ratio": [0.75],
        })
        out = coerce_service_types(df)
        assert out["depot"].iloc[0] == "CONTONMENT"
        assert out["service_number"].iloc[0] == "SVC-001"


# =========================================================================
# RAW master upsert
# =========================================================================


class TestDepotUpsert:

    def test_insert_into_empty_master(self, inbound_depot_df):
        master = pd.DataFrame(columns=RAW_COLUMNS)
        master["date"] = pd.to_datetime(master["date"])
        updated, inserted, corrected = upsert_depot_raw_master(master, inbound_depot_df)
        assert inserted == 4
        assert corrected == 0
        assert len(updated) == 4

    def test_upsert_replaces_existing_rows(self, inbound_depot_df):
        master = inbound_depot_df.copy()
        new_inbound = inbound_depot_df.copy()
        new_inbound["passengers_per_day"] = 999
        updated, inserted, corrected = upsert_depot_raw_master(master, new_inbound)
        assert corrected == 4
        assert inserted == 0
        assert (updated["passengers_per_day"] == 999).all()

    def test_upsert_preserves_other_dates(self, inbound_depot_df, depot_list):
        earlier = pd.DataFrame({
            "depot": depot_list,
            "date": pd.to_datetime("2025-11-29"),
            "passengers_per_day": [1, 2, 3, 4],
            "actual_kms": [1, 2, 3, 4],
            "occupancy_ratio": [0.5, 0.5, 0.5, 0.5],
        })
        master = earlier.copy()
        updated, inserted, corrected = upsert_depot_raw_master(master, inbound_depot_df)
        assert inserted == 4
        assert len(updated) == 8  # 4 old + 4 new


class TestServiceUpsert:

    def _make_master(self):
        return pd.DataFrame({
            "depot": ["CONTONMENT", "CONTONMENT"],
            "date": pd.to_datetime("2025-11-29"),
            "service_number": ["SVC-001", "SVC-002"],
            "actual_kms": [200.0, 300.0],
            "actual_trips": [4, 5],
            "seat_kms": [9000.0, 13500.0],
            "passenger_kms": [6750.0, 10125.0],
            "occupancy_ratio": [0.75, 0.75],
        })

    def test_insert_new_service_rows(self):
        master = self._make_master()
        inbound = master.copy()
        inbound["date"] = pd.to_datetime("2025-11-30")
        updated, inserted, corrected = upsert_service_raw_master(master, inbound)
        assert inserted == 2
        assert len(updated) == 4


# =========================================================================
# GOLD layer building
# =========================================================================


class TestBuildDepotGold:

    def test_gold_has_expected_columns(self, telugu_calendar_df, holiday_long_df):
        raw = pd.DataFrame({
            "depot": ["CONTONMENT"],
            "date": pd.to_datetime("2025-10-20"),
            "passengers_per_day": [120000],
            "actual_kms": [48000],
            "occupancy_ratio": [0.82],
        })
        gold = build_depot_gold(raw, telugu_calendar_df, holiday_long_df)
        for col in GOLD_COLUMNS:
            assert col in gold.columns, f"Missing column: {col}"

    def test_holiday_merged_correctly(self, telugu_calendar_df, holiday_long_df):
        raw = pd.DataFrame({
            "depot": ["CONTONMENT"],
            "date": pd.to_datetime("2025-10-20"),  # Dussehra in fixture
            "passengers_per_day": [120000],
            "actual_kms": [48000],
            "occupancy_ratio": [0.82],
        })
        gold = build_depot_gold(raw, telugu_calendar_df, holiday_long_df)
        assert gold["is_fes_hol"].iloc[0] == 1
        assert gold["fes_hol_code"].iloc[0] == 10

    def test_non_holiday_date(self, telugu_calendar_df, holiday_long_df):
        raw = pd.DataFrame({
            "depot": ["CONTONMENT"],
            "date": pd.to_datetime("2025-10-15"),  # not a holiday
            "passengers_per_day": [110000],
            "actual_kms": [44000],
            "occupancy_ratio": [0.78],
        })
        gold = build_depot_gold(raw, telugu_calendar_df, holiday_long_df)
        assert gold["is_fes_hol"].iloc[0] == 0
        assert gold["fes_hol_code"].iloc[0] == 0

    def test_duplicate_depot_date_raises(self, telugu_calendar_df, holiday_long_df):
        raw = pd.DataFrame({
            "depot": ["CONTONMENT", "CONTONMENT"],
            "date": pd.to_datetime("2025-10-20"),
            "passengers_per_day": [120000, 120000],
            "actual_kms": [48000, 48000],
            "occupancy_ratio": [0.82, 0.82],
        })
        with pytest.raises(ValueError, match="duplicate"):
            build_depot_gold(raw, telugu_calendar_df, holiday_long_df)


class TestBuildServiceGold:

    def test_service_gold_columns(self, telugu_calendar_df, holiday_long_df):
        raw = pd.DataFrame({
            "depot": ["CONTONMENT"],
            "date": pd.to_datetime("2025-10-20"),
            "service_number": ["SVC-001"],
            "actual_kms": [200.0],
            "actual_trips": [4],
            "seat_kms": [9000.0],
            "passenger_kms": [6750.0],
            "occupancy_ratio": [0.75],
        })
        gold = build_service_gold(raw, telugu_calendar_df, holiday_long_df)
        assert "is_fes_hol" in gold.columns
        assert "service_number" in gold.columns


# =========================================================================
# Predictions update
# =========================================================================


class TestUpdatePredictionsWithActuals:

    def test_pending_predictions_completed(self):
        preds = pd.DataFrame({
            "run_date": pd.to_datetime("2025-11-28"),
            "prediction_date": pd.to_datetime("2025-11-30"),
            "depot": ["CONTONMENT"],
            "predicted_passenger_kms": [1600000.0],
            "actual_passenger_kms": [None],
            "assumed_or": [0.85],
            "actual_or": [None],
            "estimated_kms": [50000.0],
            "actual_kms": [None],
            "bus_capacity": [45],
            "estimated_buses": [200],
            "actual_buses": [None],
            "pkm_error": [None],
            "pkm_error_pct": [None],
            "km_error": [None],
            "km_error_pct": [None],
            "status": ["pending"],
        })
        gold = pd.DataFrame({
            "depot": ["CONTONMENT"],
            "date": pd.to_datetime("2025-11-30"),
            "passengers_per_day": [115000],
            "actual_kms": [46000],
            "occupancy_ratio": [0.80],
            "passenger_kms": [0.80 * 46000 * 45],
        })
        updated, count = update_predictions_with_actuals(preds, gold)
        assert count == 1
        assert updated.loc[0, "status"] == "completed"
        assert updated.loc[0, "actual_passenger_kms"] == 0.80 * 46000 * 45

    def test_no_matching_actuals_stays_pending(self):
        preds = pd.DataFrame({
            "run_date": pd.to_datetime("2025-11-28"),
            "prediction_date": pd.to_datetime("2025-12-05"),  # no gold data for this
            "depot": ["CONTONMENT"],
            "predicted_passenger_kms": [1600000.0],
            "actual_passenger_kms": [None],
            "assumed_or": [0.85],
            "actual_or": [None],
            "estimated_kms": [50000.0],
            "actual_kms": [None],
            "bus_capacity": [45],
            "estimated_buses": [200],
            "actual_buses": [None],
            "pkm_error": [None],
            "pkm_error_pct": [None],
            "km_error": [None],
            "km_error_pct": [None],
            "status": ["pending"],
        })
        gold = pd.DataFrame({
            "depot": ["CONTONMENT"],
            "date": pd.to_datetime("2025-11-30"),
            "passengers_per_day": [115000],
            "actual_kms": [46000],
            "occupancy_ratio": [0.80],
            "passenger_kms": [0.80 * 46000 * 45],
        })
        updated, count = update_predictions_with_actuals(preds, gold)
        assert count == 0
        assert updated.loc[0, "status"] == "pending"

    def test_empty_predictions_returns_zero(self):
        preds = pd.DataFrame(columns=[
            "run_date", "prediction_date", "depot", "predicted_passenger_kms",
            "actual_passenger_kms", "status",
        ])
        gold = pd.DataFrame({
            "depot": ["CONTONMENT"], "date": pd.to_datetime("2025-11-30"),
            "passengers_per_day": [1], "occupancy_ratio": [0.8],
            "passenger_kms": [0.8 * 1 * 45],
        })
        updated, count = update_predictions_with_actuals(preds, gold)
        assert count == 0


# =========================================================================
# Revenue column handling
# =========================================================================


class TestRevenueColumnHandling:
    """Tests for optional revenue column flowing through inbound → RAW → GOLD."""

    def _make_service_df(self, with_revenue=False):
        data = {
            "depot": ["CONTONMENT"] * 2,
            "date": pd.to_datetime("2025-11-30"),
            "service_number": ["SVC-001", "SVC-002"],
            "actual_kms": [200.0, 300.0],
            "actual_trips": [4, 5],
            "seat_kms": [9000.0, 13500.0],
            "passenger_kms": [6750.0, 10125.0],
            "occupancy_ratio": [0.75, 0.75],
        }
        if with_revenue:
            data["revenue"] = [5000.0, 8000.0]
        return pd.DataFrame(data)

    def test_inbound_passes_without_revenue(self):
        """Backward compat: inbound without revenue still validates."""
        df = self._make_service_df(with_revenue=False)
        errors = validate_service_inbound(df)
        assert errors == []

    def test_inbound_passes_with_revenue(self):
        """Inbound with revenue column also validates (revenue is optional)."""
        df = self._make_service_df(with_revenue=True)
        errors = validate_service_inbound(df)
        assert errors == []

    def test_negative_revenue_flagged_by_bounds(self):
        """Negative revenue should be caught by SERVICE_BOUNDS."""
        df = self._make_service_df(with_revenue=True)
        df.loc[0, "revenue"] = -100.0
        errors = validate_service_inbound(df)
        assert any("revenue" in e for e in errors)

    def test_revenue_coerced_to_numeric(self):
        """String revenue is coerced to numeric by coerce_service_types."""
        df = self._make_service_df(with_revenue=False)
        df["revenue"] = ["5000.5", "8000.0"]
        out = coerce_service_types(df)
        assert np.issubdtype(out["revenue"].dtype, np.number)

    def test_service_gold_includes_revenue_column(self, telugu_calendar_df, holiday_long_df):
        """SERVICE_GOLD_COLUMNS now contains 'revenue'."""
        assert "revenue" in SERVICE_GOLD_COLUMNS
        raw = self._make_service_df(with_revenue=True)
        gold = build_service_gold(raw, telugu_calendar_df, holiday_long_df)
        assert "revenue" in gold.columns

    def test_service_gold_preserves_revenue_values(self, telugu_calendar_df, holiday_long_df):
        """Revenue values survive through gold build."""
        raw = self._make_service_df(with_revenue=True)
        gold = build_service_gold(raw, telugu_calendar_df, holiday_long_df)
        assert gold["revenue"].iloc[0] == 5000.0
        assert gold["revenue"].iloc[1] == 8000.0

    def test_raw_master_backfills_revenue_as_none(self, tmp_path):
        """Old CSV rows without revenue get None when loaded into RAW master."""
        csv_path = tmp_path / "ops_daily_service_master.csv"
        df_no_rev = self._make_service_df(with_revenue=False)
        df_no_rev.to_csv(csv_path, index=False)
        loaded = load_service_raw_master(csv_path)
        assert "revenue" in loaded.columns
        assert loaded["revenue"].isna().all()
