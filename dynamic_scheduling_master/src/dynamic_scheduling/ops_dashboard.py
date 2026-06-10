"""
Operations dashboard data and chart builders for TGSRTC.

Extracted from notebooks/ops_dashboard.ipynb.
Uses Plotly only (no matplotlib) for Streamlit-native rendering.
"""

from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import warnings

import plotly.graph_objects as go
from plotly.subplots import make_subplots

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

PREDICTIONS_FILE = OUTPUT_DIR / "predictions" / "daily_predictions.parquet"
GOLD_MASTER_PARQ = DATA_DIR / "processed" / "ops_daily_gold.parquet"
SERVICE_GOLD_PARQ = DATA_DIR / "processed" / "ops_daily_service_gold.parquet"
SCHEDULE_DIR = OUTPUT_DIR / "dynamic_schedule"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_dashboard_data(lookback_days: int = 30) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Load all dashboard data.

    Returns (predictions_df, gold_df, depots_list_as_dict_with_key).
    Actually returns a tuple of (predictions_df, gold_df, info_dict)
    where info_dict has 'depots' key.
    """
    predictions_df = _load_predictions_data(PREDICTIONS_FILE, lookback_days)
    gold_df = _load_gold_data(GOLD_MASTER_PARQ, lookback_days)

    if len(predictions_df) > 0:
        depots = sorted(predictions_df["depot"].unique().tolist())
    elif len(gold_df) > 0:
        depots = sorted(gold_df["depot"].unique().tolist())
    else:
        depots = []

    info = {"depots": depots, "lookback_days": lookback_days}
    return predictions_df, gold_df, info


def _load_predictions_data(file_path: Path, lookback_days: int = 30) -> pd.DataFrame:
    if not file_path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(file_path)
    df["prediction_date"] = pd.to_datetime(df["prediction_date"])
    df["run_date"] = pd.to_datetime(df["run_date"])
    cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=lookback_days)
    df = df[df["prediction_date"] >= cutoff_date]
    return df.sort_values(["depot", "prediction_date"])


def _load_gold_data(file_path: Path, lookback_days: int = 30) -> pd.DataFrame:
    if not file_path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(file_path)
    df["date"] = pd.to_datetime(df["date"])
    cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=lookback_days)
    df = df[df["date"] >= cutoff_date]
    return df.sort_values(["depot", "date"])


# ---------------------------------------------------------------------------
# Accuracy data extraction
# ---------------------------------------------------------------------------


def get_demand_accuracy_data(predictions_df: pd.DataFrame, depot: str) -> pd.DataFrame:
    if len(predictions_df) == 0:
        return pd.DataFrame()
    df = predictions_df[
        (predictions_df["depot"] == depot)
        & (predictions_df["status"].isin(["completed", "pending"]))
    ].copy()
    if len(df) == 0:
        return pd.DataFrame()
    # Prefer new passenger-km columns; fall back to legacy passenger columns
    if "predicted_passenger_kms" in df.columns and df["predicted_passenger_kms"].notna().any():
        cols = ["prediction_date", "predicted_passenger_kms", "actual_passenger_kms",
                "pkm_error", "pkm_error_pct", "status"]
    elif "predicted_passengers" in df.columns and df["predicted_passengers"].notna().any():
        cols = ["prediction_date", "predicted_passengers", "actual_passengers",
                "passenger_error", "passenger_error_pct", "status"]
    else:
        return pd.DataFrame()
    df = df[cols].copy()
    df.columns = [
        "Date", "Predicted Passenger-KMs", "Actual Passenger-KMs",
        "Passenger-KM Error", "Passenger-KM Error %", "Status",
    ]
    df = df.sort_values("Date").reset_index(drop=True)
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%d-%m-%Y")
    return df


def get_supply_accuracy_data(predictions_df: pd.DataFrame, depot: str) -> pd.DataFrame:
    if len(predictions_df) == 0:
        return pd.DataFrame()
    df = predictions_df[
        (predictions_df["depot"] == depot)
        & (predictions_df["status"] == "completed")
    ].copy()
    if len(df) == 0:
        return pd.DataFrame()
    cols = ["prediction_date", "estimated_kms", "actual_kms", "km_error", "km_error_pct"]
    cols = [c for c in cols if c in df.columns]
    if "estimated_kms" not in cols or "actual_kms" not in cols:
        return pd.DataFrame()
    df = df[cols].copy()
    if "km_error" not in df.columns:
        df["km_error"] = df["estimated_kms"] - df["actual_kms"]
    if "km_error_pct" not in df.columns:
        df["km_error_pct"] = (df["km_error"] / df["actual_kms"] * 100).where(df["actual_kms"] > 0, 0)
    df.columns = ["Date", "Estimated KMs", "Actual KMs", "KM Error", "KM Error %"]
    df = df.sort_values("Date").reset_index(drop=True)
    df = df.dropna(subset=["Actual KMs"])
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%d-%m-%Y")
    return df


# ---------------------------------------------------------------------------
# Accuracy metrics
# ---------------------------------------------------------------------------


def calculate_accuracy_metrics(error_series: pd.Series) -> dict:
    errors = error_series.dropna()
    if len(errors) == 0:
        return {}
    return {
        "Records": len(errors),
        "Mean Error %": round(float(errors.mean()), 1),
        "Mean Abs Error %": round(float(errors.abs().mean()), 1),
        "Median Abs Error %": round(float(errors.abs().median()), 1),
        "Within +/-10%": round(float((errors.abs() <= 10).mean() * 100), 1),
        "Within +/-20%": round(float((errors.abs() <= 20).mean() * 100), 1),
    }


# ---------------------------------------------------------------------------
# Plotly chart builders
# ---------------------------------------------------------------------------


def build_demand_accuracy_chart(df: pd.DataFrame, depot: str) -> go.Figure:
    """Predicted vs Actual Passenger-KMs line chart."""
    if len(df) == 0:
        return _empty_figure("No demand accuracy data available")

    fig = go.Figure()

    completed = df[df["Status"] == "completed"] if "Status" in df.columns else df
    pending = df[df["Status"] == "pending"] if "Status" in df.columns else pd.DataFrame()

    fig.add_trace(
        go.Scatter(
            x=completed["Date"], y=completed["Predicted Passenger-KMs"],
            name="Predicted Passenger-KMs",
            mode="lines+markers", line=dict(color="blue", width=2),
            marker=dict(size=6),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=completed["Date"], y=completed["Actual Passenger-KMs"],
            name="Actual Passenger-KMs",
            mode="lines+markers", line=dict(color="green", width=2),
            marker=dict(size=6),
        )
    )

    if len(pending) > 0:
        # Connect pending predictions to the last completed point
        bridge = completed.tail(1) if len(completed) > 0 else pd.DataFrame()
        pending_with_bridge = pd.concat([bridge, pending], ignore_index=True)
        fig.add_trace(
            go.Scatter(
                x=pending_with_bridge["Date"],
                y=pending_with_bridge["Predicted Passenger-KMs"],
                name="Upcoming Predictions",
                mode="lines+markers",
                line=dict(color="blue", width=2, dash="dash"),
                marker=dict(size=8, symbol="diamond"),
            )
        )

    fig.update_layout(
        title=f"Predicted vs Actual Passenger-KMs — {depot}",
        xaxis_title="Date",
        yaxis_title="Passenger-KMs",
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_demand_error_chart(df: pd.DataFrame, depot: str) -> go.Figure:
    """Passenger-KM prediction error % bar chart with threshold lines."""
    if len(df) == 0:
        return _empty_figure("No demand error data available")

    df = df.dropna(subset=["Passenger-KM Error %"])
    if len(df) == 0:
        return _empty_figure("No demand error data available")
    colors = ["green" if x <= 0 else "red" for x in df["Passenger-KM Error %"]]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=df["Date"], y=df["Passenger-KM Error %"], name="Passenger-KM Error %",
               marker_color=colors, opacity=0.7)
    )
    fig.add_hline(y=10, line_dash="dash", line_color="orange", annotation_text="+10%")
    fig.add_hline(y=-10, line_dash="dash", line_color="orange", annotation_text="-10%")
    fig.add_hline(y=0, line_color="black", line_width=1)
    fig.update_layout(
        title=f"Passenger-KM Prediction Error % — {depot}",
        xaxis_title="Date",
        yaxis_title="Passenger-KM Error %",
        height=350,
        showlegend=False,
    )
    return fig


def build_supply_accuracy_chart(df: pd.DataFrame, depot: str) -> go.Figure:
    """Estimated vs Actual KMs line chart."""
    if len(df) == 0:
        return _empty_figure("No supply accuracy data available")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["Date"], y=df["Estimated KMs"], name="Estimated KMs",
            mode="lines+markers", line=dict(color="blue", width=2),
            marker=dict(size=6),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["Date"], y=df["Actual KMs"], name="Actual KMs",
            mode="lines+markers", line=dict(color="green", width=2),
            marker=dict(size=6),
        )
    )
    fig.update_layout(
        title=f"Estimated vs Actual KMs — {depot}",
        xaxis_title="Date",
        yaxis_title="Kilometers",
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_supply_error_chart(df: pd.DataFrame, depot: str) -> go.Figure:
    """KM error % bar chart with threshold lines."""
    if len(df) == 0:
        return _empty_figure("No supply error data available")

    df = df.dropna(subset=["KM Error %"])
    if len(df) == 0:
        return _empty_figure("No supply error data available")
    colors = ["green" if x <= 0 else "red" for x in df["KM Error %"]]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=df["Date"], y=df["KM Error %"], name="KM Error %",
               marker_color=colors, opacity=0.7)
    )
    fig.add_hline(y=10, line_dash="dash", line_color="orange", annotation_text="+10%")
    fig.add_hline(y=-10, line_dash="dash", line_color="orange", annotation_text="-10%")
    fig.add_hline(y=0, line_color="black", line_width=1)
    fig.update_layout(
        title=f"KM Error % — {depot}",
        xaxis_title="Date",
        yaxis_title="KM Error %",
        height=350,
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Operations Overview — EPK-OR quadrant analysis
# ---------------------------------------------------------------------------

QUADRANT_COLORS = {
    "UNDERSUPPLY": "#2ecc71",
    "OVERSUPPLY": "#3498db",
    "SOCIAL_OBLIGATION": "#f39c12",
    "INEFFICIENT": "#e74c3c",
}


def get_operations_overview_data(
    schedules: dict[str, pd.DataFrame],
    depot: str,
) -> dict | None:
    """Extract quadrant analysis from the latest EPK schedule for *depot*.

    If the loaded schedule lacks a ``quadrant`` column (pre-existing files),
    computes it on-the-fly from ``epk``, ``cpk``, ``or`` using
    :func:`classify_epk_or_quadrant`.

    Returns dict with ``schedule_df``, ``quadrant_counts``, ``quadrant_pcts``,
    ``financial_summary``, ``action_summary`` — or ``None`` if no EPK schedule
    is available.
    """
    if depot not in schedules:
        return None

    df = schedules[depot].copy()
    is_epk = df.get("_engine", pd.Series(dtype=str)).eq("epk").any()
    if not is_epk:
        return None

    # Compute quadrant on-the-fly if missing
    if "quadrant" not in df.columns:
        from dynamic_scheduling.supply_scheduling import classify_epk_or_quadrant

        or_boundary = 0.70
        if "epk" in df.columns and "cpk" in df.columns and "or" in df.columns:
            df["quadrant"] = df.apply(
                lambda r: classify_epk_or_quadrant(r["epk"], r["cpk"], r["or"], or_boundary),
                axis=1,
            )
        else:
            return None

    # Compute contribution on-the-fly if missing
    if "contribution" not in df.columns:
        if "revenue" in df.columns and "cpk" in df.columns and "planned_kms" in df.columns:
            df["contribution"] = df["revenue"] - (df["cpk"] * df["planned_kms"])
        else:
            df["contribution"] = 0.0

    total = len(df)
    quadrant_counts = df["quadrant"].value_counts().to_dict()
    quadrant_pcts = {q: round(c / total * 100, 1) if total > 0 else 0.0
                     for q, c in quadrant_counts.items()}

    total_revenue = float(df["revenue"].sum()) if "revenue" in df.columns else 0.0
    total_contribution = float(df["contribution"].sum())
    depot_avg_epk = float(df["epk"].mean()) if "epk" in df.columns and total > 0 else 0.0
    depot_avg_or = float(df["or"].mean()) if "or" in df.columns and total > 0 else 0.0

    action_counts = df["action"].value_counts().to_dict() if "action" in df.columns else {}

    return {
        "schedule_df": df,
        "quadrant_counts": quadrant_counts,
        "quadrant_pcts": quadrant_pcts,
        "financial_summary": {
            "total_revenue": total_revenue,
            "total_contribution": total_contribution,
            "depot_avg_epk": depot_avg_epk,
            "depot_avg_or": depot_avg_or,
        },
        "action_summary": {
            "total_services": total,
            "add_slot": action_counts.get("ADD_SLOT", 0),
            "cut": action_counts.get("CUT", 0),
            "no_change": action_counts.get("NO_CHANGE", 0),
        },
    }
def build_fleet_breakdown_table(summary: dict) -> pd.DataFrame:
    """Pivot ``summary['fleet_breakdown']`` into a per-product table.

    ``Suggested Additions`` is the total count of ADD signals
    (ADD_SLOT + ADD_CANDIDATE_NO_SPARE) — how many buses the engine wants
    to add. ``Fleet Added`` is how many were actually allocated against SPARE.
    """
    cols = [
        "product",
        "Available Fleet",
        "Planned Schedules",
        "Fleet under maintenance",
        "Schedules suggested to CUT",
        "Spare Fleet",
        "Suggested Additions",
        "Fleet Added",
    ]
    fb = (summary or {}).get("fleet_breakdown") or {}
    if not fb:
        return pd.DataFrame(columns=cols)
    rows = []
    for product, vals in fb.items():
        added = vals.get("added", 0)
        rows.append({
            "product": product,
            "Available Fleet": vals.get("available", 0),
            "Planned Schedules": vals.get("planned", 0),
            "Fleet under maintenance": vals.get("maintenance", 0),
            "Schedules suggested to CUT": vals.get("cut", 0),
            "Spare Fleet": vals.get("spare", 0),
            "Suggested Additions": vals.get("to_add", added),
            "Fleet Added": added,
        })
    return pd.DataFrame(rows, columns=cols).sort_values("product").reset_index(drop=True)

def build_epk_or_scatter(schedule_df: pd.DataFrame, depot: str) -> go.Figure:
    """Plotly scatter: Profit per KM (EPK − CPK) on Y vs OR on X, colored by
    quadrant, sized by allocated_pkm.

    Each service is plotted at its own profit (EPK minus its row-specific
    CPK), so the chart stays correct when products carry different CPKs.
    The profitability boundary is a single break-even line at y = 0.
    """
    if len(schedule_df) == 0 or "epk" not in schedule_df.columns or "or" not in schedule_df.columns:
        return _empty_figure("No EPK-OR data available")

    df = schedule_df.copy()

    # Per-service profit (EPK − that service's CPK). Falls back to 25 if cpk
    # is missing on a row.
    cpk_series = pd.to_numeric(df.get("cpk", 25.0), errors="coerce").fillna(25.0)
    df["_profit_per_km"] = df["epk"] - cpk_series

    or_boundary = 0.70

    # Size by allocated_pkm (normalize for display)
    if "allocated_pkm" in df.columns:
        max_pkm = df["allocated_pkm"].max()
        df["_size"] = np.where(max_pkm > 0, df["allocated_pkm"] / max_pkm * 30 + 5, 10)
    else:
        df["_size"] = 10

    fig = go.Figure()

    # Color by product (quadrants stay implicit via boundary lines + labels).
    # Plotly's qualitative palette gives distinct colors for up to ~10 products;
    # falls back gracefully for more.
    import plotly.express as px
    palette = px.colors.qualitative.Set2 + px.colors.qualitative.Set3
    if "product" in df.columns:
        products = sorted(df["product"].dropna().unique().tolist())
        for i, product in enumerate(products):
            sub = df[df["product"] == product]
            if len(sub) == 0:
                continue
            hover_text = sub.apply(
                lambda r: (
                    f"Service: {r.get('service_number', '?')}<br>"
                    f"Product: {r.get('product', '-')}<br>"
                    f"Quadrant: {r.get('quadrant', '-')}<br>"
                    f"Profit/KM: {r['_profit_per_km']:.2f}<br>"
                    f"EPK: {r['epk']:.2f}<br>CPK: {r.get('cpk', 0):.2f}<br>"
                    f"OR: {r['or']:.2f}<br>"
                    f"Action: {r.get('action', '-')}"
                ),
                axis=1,
            )
            fig.add_trace(go.Scatter(
                x=sub["or"], y=sub["_profit_per_km"],
                mode="markers",
                name=str(product),
                marker=dict(color=palette[i % len(palette)],
                            size=sub["_size"], opacity=0.75,
                            line=dict(color="rgba(0,0,0,0.3)", width=0.5)),
                text=hover_text,
                hoverinfo="text",
            ))
    else:
        fig.add_trace(go.Scatter(
            x=df["or"], y=df["_profit_per_km"],
            mode="markers",
            marker=dict(size=df["_size"], opacity=0.7),
        ))

    # Break-even horizontal line: profit/km == 0 means EPK == CPK regardless
    # of per-product CPK differences.
    fig.add_hline(y=0, line_dash="dash", line_color="red",
                  annotation_text="Break-even (EPK = CPK)")
    # OR boundary line (70%) — orange
    fig.add_vline(x=or_boundary, line_dash="dash", line_color="orange",
                  annotation_text=f"OR = {or_boundary:.0%}")
    # OR full-capacity line (100%) — red dotted
    fig.add_vline(x=1.0, line_dash="dot", line_color="red",
                  annotation_text="OR = 100%")

    # Quadrant label annotations — split around y=0 (profitable vs not).
    y_max = float(df["_profit_per_km"].max()) if len(df) > 0 else 10.0
    y_min = float(df["_profit_per_km"].min()) if len(df) > 0 else -10.0
    x_max = float(df["or"].max()) if len(df) > 0 else 1.0
    top_y = y_max * 0.95 if y_max > 0 else 1.0
    bot_y = y_min * 0.6 if y_min < 0 else -1.0
    # Quadrant labels are now plot-region labels (since color encodes
    # product), so use a muted neutral grey. Append each as its own
    # annotation so we don't clobber the boundary-line labels added by
    # add_hline / add_vline above.
    quadrant_label_color = "rgba(80,80,80,0.55)"
    for x_pos, y_pos, text in [
        (or_boundary + (x_max - or_boundary) / 2, top_y, "UNDERSUPPLY"),
        (or_boundary / 2, top_y, "OVERSUPPLY"),
        (or_boundary + (x_max - or_boundary) / 2, bot_y, "SOCIAL OBLIGATION"),
        (or_boundary / 2, bot_y, "INEFFICIENT"),
    ]:
        fig.add_annotation(
            x=x_pos, y=y_pos, text=text, showarrow=False,
            font=dict(color=quadrant_label_color, size=12),
        )

    fig.update_layout(
        title=f"Profit/KM vs OR Quadrant Analysis — {depot}",
        xaxis_title="Occupancy Ratio (OR)",
        yaxis_title="Profit per KM (EPK − CPK)",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    title="Product"),
    )
    return fig



def build_quadrant_breakdown_chart(quadrant_counts: dict, depot: str) -> go.Figure:
    """Horizontal bar chart showing service count per quadrant."""
    if not quadrant_counts:
        return _empty_figure("No quadrant data available")

    quadrant_order = ["UNDERSUPPLY", "OVERSUPPLY", "SOCIAL_OBLIGATION", "INEFFICIENT"]
    labels = [q for q in quadrant_order if q in quadrant_counts]
    values = [quadrant_counts[q] for q in labels]
    colors = [QUADRANT_COLORS.get(q, "#999999") for q in labels]

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker_color=colors,
        text=values,
        textposition="auto",
    ))
    fig.update_layout(
        title=f"Service Count by Quadrant — {depot}",
        xaxis_title="Number of Services",
        yaxis_title="",
        height=300,
    )
    return fig


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False, font=dict(size=16, color="gray"),
    )
    fig.update_layout(height=300)
    return fig


# ---------------------------------------------------------------------------
# Schedule loading
# ---------------------------------------------------------------------------


def list_schedule_dates(schedule_dir: Path = SCHEDULE_DIR, depot:str |None = None) -> list[str]:
    """Return available schedule date strings (newest first)."""
    if not schedule_dir.exists():
        return []
    # All date folders under output/dynamic_schedule/
    dates = sorted(
        [d.name for d in schedule_dir.iterdir() if d.is_dir()],
        reverse=True,
    )

    # If no depot (admin/corporation case), return all dates
    if not depot:
        return dates

    # === YOUR REAL FILE PATTERN ===
    # epk_schedule_<DEPOT>_<DATE>.xlsx
    filtered = []
    for d in dates:
        folder = schedule_dir / d
        expected_file = folder / f"epk_schedule_{depot.upper()}_{d}.xlsx"
        if expected_file.exists():
            filtered.append(d)

    return filtered

def list_dates_with_gold_actuals(
    depot: str | None = None,
    schedule_dir: Path = SCHEDULE_DIR,
) -> list[str]:
    """Return schedule dates whose date also has rows in the service gold
    parquet (i.e. accuracy comparisons are possible). If *depot* is given,
    filter further to dates where that depot has gold rows.
    """
    if not SERVICE_GOLD_PARQ.exists():
        return []
    gold = pd.read_parquet(SERVICE_GOLD_PARQ)
    gold["date"] = pd.to_datetime(gold["date"])
    if depot:
        gold = gold[gold["depot"] == depot]
    gold_dates = set(gold["date"].dt.strftime("%Y-%m-%d").unique())
    sched_dates = set(list_schedule_dates(schedule_dir))
    return sorted(gold_dates & sched_dates, reverse=True)


def load_epk_summary_for_depot(
    schedule_date: str,
    depot: str,
    schedule_dir: Path = SCHEDULE_DIR,
) -> dict:
    """Load the per-depot EPK summary JSON written by ``run_all_depots_epk``.

    Returns ``{}`` when the file is missing or unreadable.
    """
    import json
    depot_safe = str(depot).replace(" ", "_").replace("/", "_")
    path = schedule_dir / schedule_date / f"epk_summary_{depot_safe}_{schedule_date}.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_schedule_for_date(
    schedule_date: str, schedule_dir: Path = SCHEDULE_DIR, depot: str | None = None
) -> tuple[dict[str, pd.DataFrame], str | None]:
    """
    Load schedule files for a specific date folder.
    Filters out consolidated_*.xlsx files.
    Returns (dict of {depot_name: DataFrame}, schedule_date_string or None).
    """
    folder = schedule_dir / schedule_date
    schedules: dict[str, pd.DataFrame] = {}
    if not folder.exists():
        return schedules, None
    # -------- USER-SCOPED MODE (NORMAL CASE) --------
    if depot:
        file_path = folder / f"epk_schedule_{depot.upper()}_{schedule_date}.xlsx"

        if not file_path.exists():
            return {}, None

        try:
            df = pd.read_excel(file_path)
            df["_engine"] = "epk"
            return {depot: df}, schedule_date
        except Exception:
            return {}, None
        
    for f in sorted(folder.glob("*.xlsx")):
        if "consolidated_" in f.name:
            continue
        parts = f.stem.split("_")
        is_epk = f.name.startswith("epk_schedule_")
        if is_epk and len(parts) >= 3:
            depot = parts[2]
        elif f.name.startswith("schedule_") and len(parts) >= 2:
            depot = parts[1]
        else:
            continue
        if depot in schedules and not is_epk:
            existing_engine = schedules[depot].get("_engine", pd.Series(dtype=str))
            if existing_engine.eq("epk").any():
                continue
        try:
            df = pd.read_excel(f)
            df["_engine"] = "epk" if is_epk else "delta_kms"
            schedules[depot] = df
        except Exception:
            pass

    return schedules, schedule_date


def load_latest_schedule(schedule_dir: Path = SCHEDULE_DIR , depot: str | None = None
) -> tuple[dict[str, pd.DataFrame], str | None]:
    """
    Load the most recent schedule files for each depot.
    Filters out consolidated_*.xlsx files.
    Returns (dict of {depot_name: DataFrame}, schedule_date_string or None).
    """
    dates = list_schedule_dates(schedule_dir,depot=depot)
    if not dates:
        return {}, None
    return load_schedule_for_date(dates[0], schedule_dir, depot=depot)

# ---------------------------------------------------------------------------
# Schedule Accuracy — predicted vs actual comparison
# ---------------------------------------------------------------------------


def get_schedule_accuracy_data(
    schedules: dict[str, pd.DataFrame],
    depot: str,
    schedule_date: str,
) -> dict | None:
    """Compare predicted schedule against actual service-level gold data.

    Returns a dict with:
      - ``high_level``: predicted vs actual totals (passenger_kms, revenue, epk, or, profit)
      - ``by_action``: per-action (CUT, ADD_SLOT, NO_CHANGE) comparison tables
      - ``merged_df``: full merged dataframe
    Returns None if data is insufficient.
    """
    if depot not in schedules:
        return None

    sched = schedules[depot].copy()
    is_epk = sched.get("_engine", pd.Series(dtype=str)).eq("epk").any()
    if not is_epk:
        return None

    # Load service-level actuals
    if not SERVICE_GOLD_PARQ.exists():
        return None
    gold = pd.read_parquet(SERVICE_GOLD_PARQ)
    gold["date"] = pd.to_datetime(gold["date"])
    target_date = pd.to_datetime(schedule_date)
    gold = gold[(gold["depot"] == depot) & (gold["date"] == target_date)].copy()
    if len(gold) == 0:
        return None

    # Coerce revenue in gold from object to float
    gold["revenue"] = pd.to_numeric(gold["revenue"], errors="coerce").fillna(0.0)

    # Normalize service_number types
    sched["service_number"] = sched["service_number"].astype(str)
    gold["service_number"] = gold["service_number"].astype(str)

    # Ensure predicted contribution exists
    if "contribution" not in sched.columns:
        if "revenue" in sched.columns and "cpk" in sched.columns and "planned_kms" in sched.columns:
            sched["contribution"] = sched["revenue"] - (sched["cpk"] * sched["planned_kms"])
        else:
            sched["contribution"] = 0.0

    # Merge
    merged = sched.merge(
        gold[["service_number", "actual_kms", "passenger_kms", "occupancy_ratio", "revenue"]],
        on="service_number",
        how="left",
        suffixes=("_pred", "_actual"),
    )
    # Rename for clarity
    merged.rename(columns={
        "revenue_pred": "pred_revenue",
        "revenue_actual": "actual_revenue",
        "allocated_pkm": "pred_pkm",
        "passenger_kms": "actual_pkm",
        "planned_kms": "pred_kms",
        "or": "pred_or",
        "occupancy_ratio": "actual_or",
        "epk": "pred_epk",
        "contribution": "pred_profit",
    }, inplace=True)

    # Compute actual EPK and profit
    merged["actual_epk"] = np.where(
        merged["actual_kms"] > 0,
        merged["actual_revenue"] / merged["actual_kms"],
        0.0,
    )
    cpk = merged["cpk"] if "cpk" in merged.columns else 25.0
    merged["actual_profit"] = merged["actual_revenue"] - (cpk * merged["actual_kms"].fillna(0))

    # Mark whether service actually ran
    merged["actually_ran"] = merged["actual_kms"].notna() & (merged["actual_kms"] > 0)

    # High-level summary
    has_actual = merged["actually_ran"].any()
    high_level = {
        "pred_pkm": float(merged["pred_pkm"].sum()),
        "actual_pkm": float(merged["actual_pkm"].sum()) if has_actual else None,
        "pred_revenue": float(merged["pred_revenue"].sum()),
        "actual_revenue": float(merged["actual_revenue"].sum()) if has_actual else None,
        "pred_epk": float(merged["pred_epk"].mean()),
        "actual_epk": float(merged.loc[merged["actually_ran"], "actual_epk"].mean()) if has_actual else None,
        "pred_or": float(merged["pred_or"].mean()),
        "actual_or": float(merged.loc[merged["actually_ran"], "actual_or"].mean()) if has_actual else None,
        "pred_profit": float(merged["pred_profit"].sum()),
        "actual_profit": float(merged["actual_profit"].sum()) if has_actual else None,
    }

    # Per-action breakdown
    by_action = {}
    for action in ["CUT", "ADD_SLOT", "NO_CHANGE"]:
        subset = merged[merged["action"] == action].copy() if "action" in merged.columns else pd.DataFrame()
        if len(subset) == 0:
            by_action[action] = {
                "count": 0, "actually_ran": 0, "not_ran": 0,
                "pred_kms": 0, "actual_kms": 0,
                "pred_revenue": 0, "actual_revenue": 0,
                "pred_epk": 0, "actual_epk": 0,
                "pred_or": 0, "actual_or": 0,
                "pred_profit": 0, "actual_profit": 0,
                "services": pd.DataFrame(),
            }
            continue

        ran = subset["actually_ran"].sum()
        not_ran = len(subset) - ran

        by_action[action] = {
            "count": len(subset),
            "actually_ran": int(ran),
            "not_ran": int(not_ran),
            "pred_kms": float(subset["pred_kms"].sum()),
            "actual_kms": float(subset["actual_kms"].sum()),
            "pred_revenue": float(subset["pred_revenue"].sum()),
            "actual_revenue": float(subset["actual_revenue"].sum()),
            "pred_epk": float(subset["pred_epk"].mean()),
            "actual_epk": float(subset.loc[subset["actually_ran"], "actual_epk"].mean()) if ran > 0 else 0,
            "pred_or": float(subset["pred_or"].mean()),
            "actual_or": float(subset.loc[subset["actually_ran"], "actual_or"].mean()) if ran > 0 else 0,
            "pred_profit": float(subset["pred_profit"].sum()),
            "actual_profit": float(subset["actual_profit"].sum()),
            "services": subset,
        }

    return {
        "high_level": high_level,
        "by_action": by_action,
        "merged_df": merged,
    }