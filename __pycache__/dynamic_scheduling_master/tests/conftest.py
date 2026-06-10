"""Shared fixtures for the dynamic_scheduling test suite."""

import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta, time
from pathlib import Path


# ---------------------------------------------------------------------------
# Depot / gold data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def depot_list():
    return ["CONTONMENT", "KARIMNAGAR-I", "NIZAMABAD-I", "WARANGAL-I"]


@pytest.fixture()
def gold_df(depot_list):
    """Synthetic gold-layer DataFrame spanning 60 days for 4 depots.

    Includes a 3-day festival cluster on Oct 20-22 (Mon-Wed) to test
    post_festival_days, festival_cluster_len, and related features.
    """
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-10-01", periods=60, freq="D")
    # Festival dates: Oct 20 (Mon), Oct 21 (Tue), Oct 22 (Wed)
    festival_dates = {
        pd.Timestamp("2025-10-20"): (10, "Dussehra", "Festival"),
        pd.Timestamp("2025-10-21"): (10, "Dussehra-2", "Festival"),
        pd.Timestamp("2025-10-22"): (10, "Dussehra-3", "Festival"),
    }
    rows = []
    for depot in depot_list:
        base = {"CONTONMENT": 120_000, "KARIMNAGAR-I": 55_000,
                "NIZAMABAD-I": 50_000, "WARANGAL-I": 60_000}[depot]
        for d in dates:
            occ = round(rng.uniform(0.6, 0.95), 2)
            akms = base * 0.4 + rng.integers(-1000, 1000)
            fes_info = festival_dates.get(d)
            rows.append({
                "depot": depot,
                "date": d,
                "passengers_per_day": base + rng.integers(-5000, 5000),
                "actual_kms": akms,
                "occupancy_ratio": occ,
                "passenger_kms": occ * akms * 45,
                "fes_hol_code": fes_info[0] if fes_info else 0,
                "Holiday_Festival": fes_info[1] if fes_info else "NONE",
                "fes_hol_category": fes_info[2] if fes_info else "NONE",
                "is_fes_hol": 1 if fes_info else 0,
            })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ---------------------------------------------------------------------------
# Service-master / daily-ops fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gold_df_multi_festival(depot_list):
    """Synthetic gold-layer DataFrame spanning 90 days (Sep 1 - Nov 29) for 4 depots.

    Contains two festival clusters so post/pre festival intensity tests
    have expanding history from the first cluster to learn from.

    Festival 1: Oct 2-4  (fes_hol_code=10, "Dussehra")
    Festival 2: Nov 1-3  (fes_hol_code=11, "Diwali")
    """
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-09-01", periods=90, freq="D")
    festival_dates = {
        pd.Timestamp("2025-10-02"): (10, "Dussehra", "Festival"),
        pd.Timestamp("2025-10-03"): (10, "Dussehra-2", "Festival"),
        pd.Timestamp("2025-10-04"): (10, "Dussehra-3", "Festival"),
        pd.Timestamp("2025-11-01"): (11, "Diwali", "Festival"),
        pd.Timestamp("2025-11-02"): (11, "Diwali-2", "Festival"),
        pd.Timestamp("2025-11-03"): (11, "Diwali-3", "Festival"),
    }
    rows = []
    for depot in depot_list:
        base = {"CONTONMENT": 120_000, "KARIMNAGAR-I": 55_000,
                "NIZAMABAD-I": 50_000, "WARANGAL-I": 60_000}[depot]
        for d in dates:
            occ = round(rng.uniform(0.6, 0.95), 2)
            akms = base * 0.4 + rng.integers(-1000, 1000)
            fes_info = festival_dates.get(d)
            # Give post-festival rebound days higher PKM
            pkm_mult = 1.0
            for fd in festival_dates:
                delta = (d - fd).days
                if 1 <= delta <= 4 and festival_dates[fd][0] == 10:
                    pkm_mult = 1.3 if depot == "WARANGAL-I" else 1.15
                elif 1 <= delta <= 4 and festival_dates[fd][0] == 11:
                    pkm_mult = 1.25 if depot == "WARANGAL-I" else 1.10
            rows.append({
                "depot": depot,
                "date": d,
                "passengers_per_day": base + rng.integers(-5000, 5000),
                "actual_kms": akms,
                "occupancy_ratio": occ,
                "passenger_kms": occ * akms * 45 * pkm_mult,
                "fes_hol_code": fes_info[0] if fes_info else 0,
                "Holiday_Festival": fes_info[1] if fes_info else "NONE",
                "fes_hol_category": fes_info[2] if fes_info else "NONE",
                "is_fes_hol": 1 if fes_info else 0,
            })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


@pytest.fixture()
def service_master_df():
    """Minimal service master for two depots with 3 services each."""
    rows = []
    for depot in ["CONTONMENT", "KARIMNAGAR-I"]:
        for i in range(1, 4):
            rows.append({
                "depot": depot,
                "service_number": f"SVC-{depot[:3]}-{i}",
                "route": f"R{i}",
                "product": "EXPRESS",
                "dep_time": f"{6 + i * 2}:00",
                "planned_trips": 4,
                "planned_kms": 200.0,
                "km_per_trip": 50.0,
                "avg_seats_per_bus": 45,
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def daily_ops_df():
    """Synthetic service-level ops for the last 10 days."""
    rng = np.random.default_rng(99)
    dates = pd.date_range("2025-11-20", periods=10, freq="D")
    rows = []
    for depot in ["CONTONMENT", "KARIMNAGAR-I"]:
        for i in range(1, 4):
            for d in dates:
                rows.append({
                    "depot": depot,
                    "date": d,
                    "service_number": f"SVC-{depot[:3]}-{i}",
                    "actual_kms": rng.uniform(150, 250),
                    "actual_trips": rng.integers(3, 6),
                    "seat_kms": rng.uniform(5000, 10000),
                    "passenger_kms": rng.uniform(3000, 8000),
                    "occupancy_ratio": round(rng.uniform(0.5, 1.0), 2),
                })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ---------------------------------------------------------------------------
# Inbound data helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def inbound_depot_df(depot_list):
    """A valid single-day inbound depot CSV as DataFrame."""
    return pd.DataFrame({
        "depot": depot_list,
        "date": pd.to_datetime("2025-11-30"),
        "passengers_per_day": [120000, 55000, 50000, 60000],
        "actual_kms": [48000, 22000, 20000, 24000],
        "occupancy_ratio": [0.82, 0.78, 0.74, 0.80],
    })


@pytest.fixture()
def telugu_calendar_df():
    """Minimal telugu calendar covering the fixture date range."""
    dates = pd.date_range("2025-10-01", periods=70, freq="D")
    return pd.DataFrame({
        "date": dates,
        "telugu_thithi": "Prathama",
        "telugu_paksham": "Shukla",
        "marriage_day": 0.0,
        "telugu_month": "Ashvija",
        "moudyami_day": 0.0,
    })


@pytest.fixture()
def holiday_long_df():
    """Minimal long-format holiday calendar."""
    return pd.DataFrame({
        "date": pd.to_datetime(["2025-10-20", "2025-11-01"]),
        "fes_hol_code": pd.array([10, 11], dtype="Int64"),
        "Holiday_Festival": ["Dussehra", "Diwali"],
        "fes_hol_category": ["Festival", "Festival"],
    })


# ---------------------------------------------------------------------------
# Tmp output directory
# ---------------------------------------------------------------------------


@pytest.fixture()
def service_master_with_route_df():
    """Service master with 5 SIDDIPET route services, varying dep_times and breakeven_cpk."""
    rows = [
        {"depot": "SIDDIPET", "service_number": "SP-1", "route": "SDPT-HYD",
         "product": "EXPRESS", "dep_time": "06:00", "planned_trips": 4,
         "planned_kms": 400.0, "km_per_trip": 100.0, "avg_seats_per_bus": 45,
         "breakeven_cpk": 25.0},
        {"depot": "SIDDIPET", "service_number": "SP-2", "route": "SDPT-HYD",
         "product": "EXPRESS", "dep_time": "08:00", "planned_trips": 3,
         "planned_kms": 300.0, "km_per_trip": 100.0, "avg_seats_per_bus": 45,
         "breakeven_cpk": 25.0},
        {"depot": "SIDDIPET", "service_number": "SP-3", "route": "SDPT-HYD",
         "product": "DELUXE", "dep_time": "10:00", "planned_trips": 2,
         "planned_kms": 200.0, "km_per_trip": 100.0, "avg_seats_per_bus": 45,
         "breakeven_cpk": 30.0},
        {"depot": "SIDDIPET", "service_number": "SP-4", "route": "SDPT-WGL",
         "product": "PALLEVELUGU", "dep_time": "07:00", "planned_trips": 3,
         "planned_kms": 150.0, "km_per_trip": 50.0, "avg_seats_per_bus": 50,
         "breakeven_cpk": 20.0},
        {"depot": "SIDDIPET", "service_number": "SP-5", "route": "SDPT-WGL",
         "product": "PALLEVELUGU", "dep_time": "14:00", "planned_trips": 2,
         "planned_kms": 100.0, "km_per_trip": 50.0, "avg_seats_per_bus": 50,
         "breakeven_cpk": 20.0},
    ]
    return pd.DataFrame(rows)


@pytest.fixture()
def daily_ops_with_revenue_df():
    """15 days × 5 SIDDIPET services with revenue column."""
    rng = np.random.default_rng(77)
    dates = pd.date_range("2025-11-15", periods=15, freq="D")
    services = ["SP-1", "SP-2", "SP-3", "SP-4", "SP-5"]
    rows = []
    for svc in services:
        for d in dates:
            pkm = rng.uniform(3000, 12000)
            rows.append({
                "depot": "SIDDIPET",
                "date": d,
                "service_number": svc,
                "actual_kms": rng.uniform(80, 200),
                "actual_trips": rng.integers(2, 5),
                "seat_kms": rng.uniform(4000, 10000),
                "passenger_kms": pkm,
                "occupancy_ratio": round(rng.uniform(0.4, 1.0), 2),
                "revenue": round(pkm * rng.uniform(0.5, 2.0), 2),
            })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


@pytest.fixture()
def daily_ops_no_revenue_df():
    """15 days × 3 services without revenue column."""
    rng = np.random.default_rng(55)
    dates = pd.date_range("2025-11-15", periods=15, freq="D")
    services = ["SP-1", "SP-2", "SP-3"]
    rows = []
    for svc in services:
        for d in dates:
            rows.append({
                "depot": "SIDDIPET",
                "date": d,
                "service_number": svc,
                "actual_kms": rng.uniform(80, 200),
                "actual_trips": rng.integers(2, 5),
                "seat_kms": rng.uniform(4000, 10000),
                "passenger_kms": rng.uniform(3000, 8000),
                "occupancy_ratio": round(rng.uniform(0.5, 1.0), 2),
            })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


@pytest.fixture()
def tmp_output(tmp_path):
    """Create and return a temporary output directory tree."""
    (tmp_path / "predictions").mkdir()
    (tmp_path / "evaluations").mkdir()
    (tmp_path / "dynamic_schedule").mkdir()
    return tmp_path
