# TGSRTC Dynamic Scheduling

AI-based daily dynamic scheduling system for Telangana State Road Transport Corporation (TGSRTC). Ingests daily operational data, predicts passenger demand two days ahead using XGBoost, and generates policy-driven bus service schedules using one of two engines: a **delta-KMs trip-count** engine or an **EPK/OR-based supply** engine.

## Pipeline overview

The system runs three sequential stages each day:

```
1. Data Pipeline        Ingest CSVs -> RAW master -> GOLD parquet
2. Demand Prediction    Feature engineering -> XGBoost -> T+2 forecast
3. Supply Scheduling    Predicted demand -> policy engine -> per-depot schedules
```

A Streamlit dashboard (`app.py`) wraps all three stages and provides accuracy monitoring charts.

### Data flow

```
data/inbound_daily/*.csv
        |
        v
  data_pipeline.py          validate, upsert RAW, build GOLD, backfill actuals
        |
        v
data/processed/ops_daily_gold.parquet          (depot-level)
data/processed/ops_daily_service_gold.parquet   (service-level, includes revenue)
        |
        v
  demand_prediction.py       temporal + weather + lag + festival features
        |                    train XGBoost, predict T+2
        v
output/predictions/daily_predictions.parquet
        |
        v
  supply_scheduling.py       load predictions + service master
        |                    run policy engine per depot (delta_kms or epk)
        v
output/dynamic_schedule/<date>/*.xlsx + *.json
```

## Modules

### `data_pipeline.py` — Data ingestion and GOLD layer

Scans `data/inbound_daily/` for new CSV files, validates them against schema and business rules, upserts into RAW master CSVs, and rebuilds the GOLD parquet by joining with Telugu calendar and holiday calendar data.

Key functions:

| Function | Purpose |
|---|---|
| `run_daily_pipeline()` | Main entry point. Returns files processed and errors. |
| `scan_inbound_files()` | Detect depot and service CSVs in the inbound directory |
| `validate_depot_inbound()` | Schema, bounds, depot allowlist, date checks |
| `validate_service_inbound()` | Schema, bounds, duplicate key checks |
| `upsert_depot_raw_master()` | Insert-or-replace rows by (depot, date) |
| `upsert_service_raw_master()` | Insert-or-replace rows by (depot, date, service_number) |
| `build_depot_gold()` | Join RAW + Telugu calendar + holiday calendar -> GOLD |
| `build_service_gold()` | Same for service-level data (includes revenue when present) |
| `update_predictions_with_actuals()` | Backfill pending predictions once real data arrives |

File naming convention: `ops_daily_YYYY-MM-DD.csv` (depot) and `ops_daily_service_YYYY-MM-DD.csv` (service).

Allowed depots: `CONTONMENT`, `KARIMNAGAR-I`, `NIZAMABAD-I`, `WARANGAL-I`.

#### Revenue column

The `revenue` column is **optional** in inbound service CSVs. When present it flows through RAW into GOLD and is used by the EPK scheduling engine. Old CSVs without revenue continue to work — the column is backfilled as `None` in the RAW master and validation is unaffected since `validate_service_inbound()` only checks required columns (`SERVICE_INBOUND_COLUMNS`). The bounds check validates `revenue >= 0` when the column is present.

Schema progression:

```
SERVICE_INBOUND_COLUMNS   depot, date, service_number, actual_kms, actual_trips,
                          seat_kms, passenger_kms, occupancy_ratio

SERVICE_RAW_COLUMNS       SERVICE_INBOUND_COLUMNS + [revenue]

SERVICE_GOLD_COLUMNS      SERVICE_RAW_COLUMNS + calendar/holiday features + is_fes_hol
```

### `demand_prediction.py` — Demand forecasting

Builds features from the GOLD data, trains an XGBoost regressor, and generates a **T+2 forecast** (predict 2 days ahead; data available up to T, run on T+1, prediction target T+2).

Key functions:

| Function | Purpose |
|---|---|
| `run_demand_prediction()` | Main entry point. Returns prediction_date, per-depot predictions, metrics. |
| `add_lag_features()` | `shift(2)` lag, 7-day rolling stats, same-DOW median |
| `add_target_encoding()` | Expanding-mean depot encoding with `shift(2)` |
| `build_festival_features()` | Holiday proximity flags and intensity features |
| `merge_weather_features()` | Temperature, rainfall, derived flags |
| `fetch_weather_forecast()` | Open-Meteo Forecast API for future-date weather |
| `construct_future_features()` | Build model-ready feature rows for T+2 using only data up to T |

Feature engineering details:

- **Lags**: `pkm_lag_2` (shift 2), `pkm_lag_7` (shift 7), `pkm_roll7_mean/std` (7-day rolling on shift-2 series), `pkm_same_dow_3med` (same day-of-week median)
- **Target encoding**: `depot_te` — per-depot expanding mean with shift(2)
- **Weather**: historical from Open-Meteo Archive API (cached), forecast from Open-Meteo Forecast API for future dates, fallback to last known
- **Holidays**: proximity flags (`fes_hol_minus_1/2`, `fes_hol_plus_1/2`), festival intensity
- **Temporal**: day-of-week, is_weekend, month, Telugu calendar features

Model artifacts are saved to `model/xgb_v1/` (joblib model, features.json, config.yaml).

### `supply_scheduling.py` — Policy-based service scheduling

Takes predicted passenger-KMs per depot and adjusts bus services using one of two engines, selected via the `engine` parameter on `run_supply_scheduling()`.

#### Engine 1: Delta-KMs (`engine="delta_kms"`, default)

Compares target KMs (derived from predicted demand) against planned KMs and adds or removes trips to close the gap.

| Function | Purpose |
|---|---|
| `run_supply_scheduling()` | Main entry point. `engine` param selects the engine. |
| `run_policy_engine()` | Core single-depot logic: compare target KMs vs planned, add/cut trips |
| `run_all_depots()` | Run policy engine for all depots, write XLSX + JSON |
| `compute_recent_or()` | Mean occupancy ratio per service over last N days |
| `compute_target_kms()` | Convert predicted passenger-KMs to required vehicle-KMs |

Policy rules (configurable in `config.yaml` under `scheduling_policy`):

- **Target OR**: 0.75 occupancy ratio (per-depot override from `depot_master.csv`)
- **Tolerance**: 3% — no action if planned KMs are within tolerance of target
- **Adding trips**: prioritize peak hours, high-OR services, short km-per-trip routes
- **Cutting trips**: protect peak-hour services, cut lowest-OR services first
- **Stop threshold**: OR below 0.45 stops the service entirely
- **Limits**: max 1 trip change per service, max 2 changes per route, max 25 total changes

Actions per service: `INCREASE`, `DECREASE`, `STOP`, `NO_CHANGE`.

Output files: `schedule_<depot>_<date>.xlsx`, `summary_<depot>_<date>.json`

#### Engine 2: EPK/OR (`engine="epk"`)

Per-service earnings-based decision engine. Splits the depot forecast to individual services using 15-day passenger-KMs weights, computes Earnings Per KM (EPK) and Occupancy Ratio (OR), then decides whether to add a new departure slot or cut the service.

| Function | Purpose |
|---|---|
| `load_epk_policy()` | Load EPK thresholds from `config.yaml`, merge over defaults |
| `compute_service_weights()` | Weight = service_pkm_15d / depot_total_pkm_15d |
| `compute_rev_per_pkm()` | Mean(daily_revenue / daily_passenger_kms) per service |
| `find_slot_midpoint()` | Find next departure on same route, return midpoint time |
| `run_epk_policy_engine()` | Core single-depot EPK/OR decision engine |
| `run_all_depots_epk()` | Multi-depot orchestrator, writes XLSX + JSON |

**Core logic in `run_epk_policy_engine()`**:

1. Filter service_master to depot
2. Compute 15-day passenger_kms weights per service
3. Allocate depot forecast: `allocated_pkm = depot_forecast * weight`
4. Compute `rev_per_pkm` from ops history (revenue / passenger_kms)
5. Derive `revenue = allocated_pkm * rev_per_pkm`
6. Compute `EPK = revenue / planned_kms`
7. Read `CPK` (breakeven cost per km) from service_master
8. Compute `OR = allocated_pkm / (planned_kms * avg_seats_per_bus)`
9. Decide:
   - **ADD_SLOT**: `OR > 0.80` AND `EPK > 1.05 * CPK` — suggest new departure (midpoint time between this and next service on the route)
   - **CUT**: `OR < 0.50` AND `EPK < 0.90 * CPK` — flag service for removal
   - **NO_CHANGE**: otherwise

Policy thresholds (configurable in `config.yaml` under `epk_policy`):

| Parameter | Default | Description |
|---|---|---|
| `lookback_days` | 15 | Days of ops history for weight/revenue calculation |
| `or_threshold_add` | 0.80 | OR above this triggers ADD_SLOT consideration |
| `epk_premium_add` | 1.05 | EPK must exceed this multiple of CPK for ADD_SLOT |
| `or_threshold_cut` | 0.50 | OR below this triggers CUT consideration |
| `epk_discount_cut` | 0.90 | EPK must be below this multiple of CPK for CUT |
| `default_rev_per_pkm` | 0.0 | Fallback when no revenue data exists |
| `default_cpk` | 25.0 | Fallback breakeven cost per km |

Output columns: `service_number`, `route`, `product`, `dep_time`, `allocated_pkm`, `revenue`, `epk`, `or`, `cpk`, `action`, `suggested_new_slot`, `reason`

Output files: `epk_schedule_<depot>_<date>.xlsx`, `epk_summary_<depot>_<date>.json`

#### Edge cases

| Case | Handling |
|---|---|
| No revenue column in ops data | `rev_per_pkm` defaults to 0, EPK=0 — no ADD_SLOT, CUT only if OR<0.5 |
| Service has 0 passenger_kms in 15 days | weight=0, allocated_pkm=0, OR=0, EPK=0 — NO_CHANGE |
| Last departure on route (no next service) | `find_slot_midpoint()` returns None, ADD_SLOT flagged but no suggested time |
| Single service on route | Same as above |
| planned_kms = 0 | EPK=0, OR=0 (guarded by `np.where`) |
| breakeven_cpk missing | Falls back to `default_cpk` (25.0) |

### `ops_dashboard.py` — Streamlit dashboard utilities

Data loading and Plotly chart builders for the operations dashboard.

Key functions:

| Function | Purpose |
|---|---|
| `load_dashboard_data()` | Load predictions + gold data for last N days |
| `get_demand_accuracy_data()` | Extract predicted vs actual passengers per depot |
| `get_supply_accuracy_data()` | Extract estimated vs actual KMs per depot |
| `calculate_accuracy_metrics()` | MAE, MAPE, median error, % within thresholds |
| `build_demand_accuracy_chart()` | Predicted vs actual passengers line chart |
| `build_demand_error_chart()` | Prediction error % bar chart |
| `build_supply_accuracy_chart()` | Estimated vs actual KMs line chart |
| `build_supply_error_chart()` | KM error % bar chart |
| `load_latest_schedule()` | Load most recent schedule XLSX files by depot (auto-detects engine) |

`load_latest_schedule()` picks up both `schedule_*` (delta-KMs) and `epk_schedule_*` (EPK) files. When both exist for the same depot, the EPK schedule takes precedence. Each loaded DataFrame is tagged with an `_engine` column so the dashboard adapts its layout.

### `app.py` — Streamlit dashboard

Three tabs per depot:

1. **Demand Accuracy** — predicted vs actual passenger-KMs with error charts
2. **Supply Accuracy** — estimated vs actual KMs with error charts
3. **Daily Schedule** — latest schedule output, layout adapts to engine:
   - **Delta-KMs engine**: Planned/Suggested KMs metrics, INCREASE/DECREASE/STOP/NO_CHANGE counts, trip-change table
   - **EPK engine**: Allocated PKM/Revenue metrics, ADD_SLOT/CUT/NO_CHANGE counts, EPK/OR/CPK table with suggested new slots

## Project structure

```
├── app.py                          Streamlit dashboard
├── main.py                         CLI entry point (placeholder)
├── pyproject.toml                  Dependencies and project metadata
├── src/dynamic_scheduling/
│   ├── __init__.py                 Public API exports
│   ├── data_pipeline.py            Ingestion, validation, GOLD layer
│   ├── demand_prediction.py        Feature engineering, XGBoost, T+2 forecast
│   ├── supply_scheduling.py        Delta-KMs + EPK/OR scheduling engines
│   └── ops_dashboard.py            Dashboard data + chart builders
├── tests/
│   ├── conftest.py                 Shared pytest fixtures
│   ├── test_data_pipeline.py       42 tests — validation, upsert, GOLD build, revenue
│   ├── test_demand_prediction.py   30 tests — lags, encoding, features, inference
│   └── test_supply_scheduling.py   51 tests — policy engine, EPK engine, KM calc
├── data/
│   ├── inbound_daily/              New daily CSV files (scanned by pipeline)
│   ├── raw/                        Accumulated RAW master CSVs
│   ├── processed/                  GOLD parquet files
│   ├── master/                     Reference data (depot, calendar, holidays, services)
│   ├── features/                   Engineered feature parquet
│   ├── cache/                      Weather API cache
│   ├── archive/                    Processed inbound files
│   └── logs/                       Ingestion logs and errors
├── model/xgb_v1/                   Trained model artifacts
│   ├── xgb_model.joblib
│   ├── config.yaml                 Model, scheduling_policy, and epk_policy config
│   └── features.json
├── output/
│   ├── predictions/                daily_predictions.parquet
│   ├── evaluations/                Model metrics and test predictions
│   └── dynamic_schedule/<date>/    Per-date XLSX schedules and JSON summaries
└── notebooks/                      Development notebooks (source of .py modules)
```

## Setup

```bash
# Create virtual environment and install dependencies
uv sync

# Activate
source .venv/bin/activate
```

### Dependencies

- **ML**: xgboost, scikit-learn, numpy, pandas
- **Data**: pyarrow (parquet), openpyxl (xlsx), pyyaml (config)
- **Weather**: requests (Open-Meteo API)
- **Dashboard**: streamlit, plotly
- **Dev**: pytest, black, ruff

## Usage

### Run the Streamlit dashboard

```bash
streamlit run app.py
```

The sidebar provides buttons to run each pipeline stage in order. The main panel shows demand accuracy, supply accuracy, and daily schedule tabs.

### Run pipeline stages from Python

```python
from dynamic_scheduling import (
    run_daily_pipeline,
    run_demand_prediction,
    run_supply_scheduling,
)

# 1. Ingest new data files
pipeline_result = run_daily_pipeline()

# 2. Train model and predict T+2
prediction_result = run_demand_prediction()
print(prediction_result["prediction_date"])
print(prediction_result["depot_predictions"])

# 3a. Generate schedules using delta-KMs engine (default)
schedule_result = run_supply_scheduling()
print(schedule_result["summaries"])

# 3b. Generate schedules using EPK/OR engine
epk_result = run_supply_scheduling(engine="epk")
print(epk_result["engine"])      # "epk"
print(epk_result["summaries"])   # per-depot: count_add_slot, count_cut, count_no_change
```

### Run tests

```bash
# All tests (excluding demand prediction if import errors)
pytest tests/test_data_pipeline.py tests/test_supply_scheduling.py -v

# Revenue column tests only
pytest tests/test_data_pipeline.py -v -k "revenue"

# EPK engine tests only
pytest tests/test_supply_scheduling.py -v -k "epk or weights or rev_per_pkm or slot_midpoint"
```

## Configuration

All tunable parameters live in `model/xgb_v1/config.yaml`:

- `scheduling_policy` — delta-KMs engine thresholds (target_or, tolerance, peak hours, limits)
- `epk_policy` — EPK/OR engine thresholds (lookback_days, OR/EPK thresholds, defaults)
- `xgb` — XGBoost hyperparameters
- `prediction_defaults` — bus capacity, assumed OR, rolling window settings
- `feature_engineering` — outlier IQR, festival proximity, weather, lag windows

## Reference data

| File | Location | Description |
|---|---|---|
| `depot_master.csv` | `data/master/` | Depot names, bus capacity, target_or, lat/lon for weather API |
| `service_master.csv` | `data/master/` | Service definitions: routes, trips, KMs, departure times, breakeven_cpk |
| `telugu_calendar.csv` | `data/master/` | Telugu thithi, paksham, month, marriage/moudyami days |
| `holiday_calendar.csv` | `data/master/` | Festival/holiday codes and dates (2023-2026) |
