import pandas as pd
#CHECK 22:41
import streamlit as st
import plotly.express as px
import uuid
from sqlalchemy import create_engine
from urllib.parse import quote_plus
import itertools
import hashlib
import datetime
import re
import calendar
import mysql.connector
import json
from auth import get_role_by_userid, get_depot_by_userid  # cleaned: removed get_depot_settings, get_connection

from mysql.connector import Error
import pymysql
from datetime import datetime, timedelta, time

# ---------------------- CONFIG --------------------------
with open("config.json") as f:
    config = json.load(f)
DB_CONFIG = config.get("db", {})

def get_connection():
    try:
        return pymysql.connect(
            host=DB_CONFIG.get("host", ""),
            user=DB_CONFIG.get("user", ""),
            password=DB_CONFIG.get("password", ""),
            database=DB_CONFIG.get("database", ""),
        )
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None    

# ---------------------- CONSTANTS --------------------------
DATE_SRD_COL = "operations_date"
KM_COL = "opd_kms"
HOURS_COL = "hours"
EARNINGS_COL = "daily_earnings"
DEPOT_COL = "depot"
EMP_COL = "employee_id"
LEAVE_TYPE_COL = "leave_type"
LSA_DATE_COL = "date"

# ---------------------- REGION-DEPOT MAPPING --------------------------
def get_region_depot_mapping(mysql_conn):
    """
    Builds a {region: [list of depots]} dictionary from TS_ADMIN.
    All names are normalized (upper, strip spaces).
    """
    REGION_DEPOTS = {}
    try:
        cursor = mysql_conn.cursor()
        cursor.execute("SELECT region, depot_name FROM TS_ADMIN")
        for region, depot in cursor.fetchall():
            reg = region.strip().upper()
            dep = depot.strip().upper()
            if reg not in REGION_DEPOTS:
                REGION_DEPOTS[reg] = []
            if dep not in REGION_DEPOTS[reg]:
                REGION_DEPOTS[reg].append(dep)
        cursor.close()
    except Exception as e:
        st.error(f"Failed to build region-depot mapping: {e}")
        return {}

    return REGION_DEPOTS

# Usage at the start of your script
mysql_conn = get_connection()
REGION_DEPOTS = get_region_depot_mapping(mysql_conn)

def get_depot_color(depot_name):
    hex_digest = hashlib.md5(depot_name.encode()).hexdigest()
    return f'#{hex_digest[:6]}'

def get_region_for_user_fixed(conn, user_id):
    cursor = conn.cursor()
    cursor.execute("SELECT depot FROM users WHERE userid=%s", (user_id,))
    row = cursor.fetchone()
    if not row:
        return None
    user_depot_or_region = row[0].strip().upper()
    # Check if this value exists as a region in TS_ADMIN
    cursor.execute("SELECT DISTINCT region FROM TS_ADMIN WHERE UPPER(TRIM(region))=%s LIMIT 1", (user_depot_or_region,))
    region_row = cursor.fetchone()
    if region_row:
        return region_row[0].strip().upper()
    # Otherwise fallback: treat it as a depot and fetch its region
    cursor.execute("SELECT region FROM TS_ADMIN WHERE UPPER(TRIM(depot_name))=%s LIMIT 1", (user_depot_or_region,))
    region_row = cursor.fetchone()
    if region_row:
        return region_row[0].strip().upper()
    return None

role = None
if "userid" in st.session_state:
    role = get_role_by_userid(st.session_state.userid)

def get_depots_in_region(_conn, region, user_depot_prefix=None):
    try:
        cursor = _conn.cursor()
        if user_depot_prefix:
            like_pattern = user_depot_prefix.strip().upper() + '%'
            query = "SELECT depot_name FROM TS_ADMIN WHERE region = %s AND depot_name LIKE %s ORDER BY depot_name"
            cursor.execute(query, (region, like_pattern))
        else:
            query = "SELECT depot_name FROM TS_ADMIN WHERE region = %s ORDER BY depot_name"
            cursor.execute(query, (region,))
        rows = cursor.fetchall()
        cursor.close()
        return [row[0] for row in rows] if rows else []
    except Exception as e:
        st.error(f"Error fetching depots for region {region}: {e}")
        return []

def get_depot_settings(_conn):
    """
    Fetches depot configuration settings (depot_name and category) from the TS_ADMIN table.
    The connection object _conn is passed from the main.
    """
    if _conn is None:
        st.error("Database connection not available for fetching depot settings.")
        return {}

    cursor = None
    try:
        cursor = _conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT depot_name, category FROM TS_ADMIN")
        rows = cursor.fetchall()
        return {row["depot_name"]: row["category"] for row in rows if "depot_name" in row and "category" in row}
    except Exception as e:
        st.error(f"Error fetching depot settings: {e}")
        return {}
    finally:
        if cursor:
            cursor.close()

def get_all_regions(_conn):
    """
    Return a list of all distinct regions from TS_ADMIN (normalized to UPPER).
    Used for corporation-wide view.
    """
    try:
        cursor = _conn.cursor()
        cursor.execute("""
            SELECT DISTINCT region 
            FROM TS_ADMIN 
            WHERE region IS NOT NULL AND TRIM(region) <> ''
            ORDER BY region
        """)
        rows = cursor.fetchall()
        cursor.close()
        return [r[0].strip().upper() for r in rows if r[0]]
    except Exception as e:
        st.error(f"Error fetching regions: {e}")
        return []

# ---------------------- REGION AVERAGE HELPERS --------------------------
def compute_region_averages(mysql_conn, region, year_sel="All", debug=False):
    """
    Compute region averages (per-depot-per-month) for total_km, total_hours, total_earnings, absenteeism.
    """
    if mysql_conn is None:
        return None

    cursor = None
    try:
        cursor = mysql_conn.cursor()
        # 1) get depots in region
        cursor.execute("SELECT depot_name FROM TS_ADMIN WHERE region = %s ORDER BY depot_name", (region,))
        rows = cursor.fetchall()
        depots = [r[0].strip().upper() for r in rows] if rows else []

        if not depots:
            return {"total_km": None, "total_hours": None, "total_earnings": None, "absenteeism": None,
                    "num_depots": 0, "months": 0, "depots": []}
        num_depots = len(depots)

        # 2) months_count / date-range
        if year_sel != "All":
            year = int(year_sel)
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"
            months_count = 12
        else:
            format_placeholders = ",".join(["%s"] * len(depots))
            q_months = f"""
                SELECT COUNT(DISTINCT DATE_FORMAT(operations_date, '%%Y-%%m')) as months_count
                FROM daily_operations
                WHERE UPPER(TRIM(depot)) IN ({format_placeholders})
            """
            cursor.execute(q_months, tuple(depots))
            months_row = cursor.fetchone()
            months_count = int(months_row[0]) if months_row and months_row[0] else 0
            months_count = months_count if months_count > 0 else 1
            start_date = None
            end_date = None

        # 3) Try fast SQL aggregate (expects hours column present)
        format_placeholders = ",".join(["%s"] * len(depots))
        try:
            if start_date and end_date:
                q_ops = f"""
                    SELECT
                        COALESCE(SUM(opd_kms),0) AS total_km,
                        COALESCE(SUM(hours),0) AS total_hours,
                        COALESCE(SUM(daily_earnings),0) AS total_earnings
                    FROM daily_operations
                    WHERE UPPER(TRIM(depot)) IN ({format_placeholders})
                      AND operations_date BETWEEN %s AND %s
                """
                params = tuple(depots) + (start_date, end_date)
            else:
                q_ops = f"""
                    SELECT
                        COALESCE(SUM(opd_kms),0) AS total_km,
                        COALESCE(SUM(hours),0) AS total_hours,
                        COALESCE(SUM(daily_earnings),0) AS total_earnings
                    FROM daily_operations
                    WHERE UPPER(TRIM(depot)) IN ({format_placeholders})
                """
                params = tuple(depots)

            cursor.execute(q_ops, params)
            ops_row = cursor.fetchone() or (0, 0, 0)
            total_km = float(ops_row[0]) if len(ops_row) > 0 and ops_row[0] is not None else 0.0
            total_hours = float(ops_row[1]) if len(ops_row) > 1 and ops_row[1] is not None else 0.0
            total_earnings = float(ops_row[2]) if len(ops_row) > 2 and ops_row[2] is not None else 0.0

        except Exception as sql_err:
            # ---- Python fallback ----
            try:
                placeholders = ",".join(["%s"] * len(depots))
                if start_date and end_date:
                    q_rows = f"""
                        SELECT * FROM daily_operations
                        WHERE UPPER(TRIM(depot)) IN ({placeholders})
                          AND operations_date BETWEEN %s AND %s
                    """
                    params_rows = tuple(depots) + (start_date, end_date)
                else:
                    q_rows = f"""
                        SELECT * FROM daily_operations
                        WHERE UPPER(TRIM(depot)) IN ({placeholders})
                    """
                    params_rows = tuple(depots)

                import pandas as _pd
                rtc_df = _pd.read_sql(q_rows, mysql_conn, params=params_rows)
                
                if rtc_df.empty:
                    total_km = total_hours = total_earnings = 0.0
                else:
                    rtc_df['depot'] = rtc_df['depot'].astype(str).str.strip().str.upper()
                    rtc_df['service_number'] = rtc_df.get('service_number', rtc_df.columns[0]).astype(str).str.strip().str.upper()

                    km_raw = rtc_df.get('opd_kms', 0).astype(str).str.strip()
                    km_clean = km_raw.str.replace(',', '', regex=False).replace('', '0')
                    rtc_df['opd_kms'] = _pd.to_numeric(km_clean, errors='coerce').fillna(0.0)

                    rtc_df['daily_earnings'] = _pd.to_numeric(rtc_df.get('daily_earnings', 0), errors='coerce').fillna(0)

                    svc_q = "SELECT service_number, dept_time, arr_time, day_night_code, depot FROM service_master"
                    svc_df = _pd.read_sql(svc_q, mysql_conn)
                    if not svc_df.empty:
                        svc_df['service_number'] = svc_df['service_number'].astype(str).str.strip().str.upper()
                        svc_df['depot'] = svc_df['depot'].astype(str).str.strip().str.upper()
                    else:
                        svc_df = _pd.DataFrame(columns=['service_number', 'dept_time', 'arr_time', 'day_night_code', 'depot'])

                    from datetime import datetime as _dt, timedelta as _td
                    import datetime as _py_dt

                    def _convert_time(x):
                        if _pd.isnull(x):
                            return None
                        if isinstance(x, _py_dt.time):
                            return x
                        if isinstance(x, _py_dt.timedelta):
                            return (_dt.min + x).time()
                        if isinstance(x, str):
                            try:
                                return _dt.strptime(x, "%H:%M:%S").time()
                            except Exception:
                                try:
                                    return _dt.strptime(x, "%H:%M").time()
                                except Exception:
                                    return None
                        return None

                    svc_df['dept_time'] = svc_df['dept_time'].apply(_convert_time)
                    svc_df['arr_time'] = svc_df['arr_time'].apply(_convert_time)

                    merged = _pd.merge(
                        rtc_df,
                        svc_df[['depot', 'service_number', 'dept_time', 'arr_time', 'day_night_code']],
                        left_on=['depot', 'service_number'],
                        right_on=['depot', 'service_number'],
                        how='left'
                    )

                    def _compute_hours(row):
                        dep = row.get('dept_time')
                        arr = row.get('arr_time')
                        dnc = row.get('day_night_code')
                        if dep is None or arr is None:
                            return 0.0
                        try:
                            dummy_date = _dt.today().date()
                            dep_dt = _dt.combine(dummy_date, dep)
                            arr_dt = _dt.combine(dummy_date, arr)
                            if str(dnc).upper() == 'N':
                                arr_dt += _td(days=1)
                                duration = arr_dt - dep_dt
                                if duration.total_seconds() < 6 * 3600:
                                    arr_dt += _td(days=1)
                                    duration = arr_dt - dep_dt
                            else:
                                if arr_dt < dep_dt:
                                    arr_dt += _td(days=1)
                                duration = arr_dt - dep_dt
                            return duration.total_seconds() / 3600.0
                        except Exception:
                            return 0.0

                    merged['hours_calc'] = merged.apply(_compute_hours, axis=1)

                    total_km = float(merged['opd_kms'].sum() or 0.0)
                    total_hours = float(merged['hours_calc'].sum() or 0.0)
                    total_earnings = float(merged['daily_earnings'].sum() or 0.0)

            except Exception as fallback_err:
                try:
                    st.error(f"compute_region_averages fallback error: {fallback_err}")
                except Exception:
                    pass
                total_km = total_hours = total_earnings = 0.0

        # 4) absenteeism
        try:
            if start_date and end_date:
                q_abs = f"""
                    SELECT COUNT(*) FROM driver_absenteeism
                    WHERE UPPER(TRIM(depot)) IN ({format_placeholders})
                      AND date BETWEEN %s AND %s
                """
                params_abs = tuple(depots) + (start_date, end_date)
            else:
                q_abs = f"""
                    SELECT COUNT(*) FROM driver_absenteeism
                    WHERE UPPER(TRIM(depot)) IN ({format_placeholders})
                """
                params_abs = tuple(depots)

            cursor.execute(q_abs, params_abs)
            abs_row = cursor.fetchone()
            total_abs = int(abs_row[0]) if abs_row and abs_row[0] is not None else 0
        except Exception:
            total_abs = 0

        months_count = months_count if months_count > 0 else 1
        num_depots_safe = num_depots if num_depots > 0 else 1

        region_avg_km = total_km / num_depots_safe / months_count
        region_avg_hours = total_hours / num_depots_safe / months_count
        region_avg_earn = total_earnings / num_depots_safe / months_count
        region_avg_abs = total_abs / num_depots_safe / months_count

        return {
            "total_km": region_avg_km,
            "total_hours": region_avg_hours,
            "total_earnings": region_avg_earn,
            "absenteeism": region_avg_abs,
            "num_depots": num_depots,
            "months": months_count,
            "depots": depots
        }

    except Exception as e:
        try:
            st.error(f"Error computing region averages: {e}")
        except Exception:
            pass
        return {"total_km": None, "total_hours": None, "total_earnings": None, "absenteeism": None,
                "num_depots": 0, "months": 0, "depots": []}
    finally:
        if cursor:
            cursor.close()
# ---------------------- PREAGGREGATE FUNCTION --------------------------
@st.cache_data(show_spinner="Loading data …")
def preaggregate(selected_depot, config):
    """
    Prepares depot and driver monthly data, LSA data, and GHC for the selected depot.
    Returns: depot_monthly, driver_monthly, lsa_valid, ghc_2024
    """
    # fallback column-names
    km_col = globals().get('KM_COL', 'opd_kms')
    date_col = globals().get('DATE_SRD_COL', 'operations_date')
    depot_col = globals().get('DEPOT_COL', 'depot')
    hours_col = globals().get('HOURS_COL', 'hours')
    earnings_col = globals().get('EARNINGS_COL', 'earnings')
    emp_col = globals().get('EMP_COL', 'employee_id')
    lsa_date_col = globals().get('LSA_DATE_COL', 'date')
    leave_type_col = globals().get('LEAVE_TYPE_COL', 'leave_type')

    if not selected_depot:
        st.warning("⚠️ No depot selected for current user.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    selected_depot = selected_depot.strip().upper()

    # ------------------- DB Connection -------------------
    db_user = config['db']['user']
    db_password = quote_plus(config['db']['password'])
    db_host = config['db']['host']
    db_name = config['db']['database']

    engine = create_engine(f"mysql+pymysql://{db_user}:{db_password}@{db_host}/{db_name}")

    depot_monthly = driver_monthly = lsa_valid = ghc_2024 = pd.DataFrame()

    # ------------------- Daily Operations -------------------
    try:
        rtc = pd.read_sql(
            "SELECT * FROM daily_operations WHERE UPPER(TRIM(depot)) = %s",
            engine,
            params=(selected_depot,)
        )
        rtc = rtc[rtc['depot'].astype(str).str.strip().str.upper() == selected_depot]
        if rtc.empty:
            st.warning(f"No data found for depot {selected_depot}")
    except Exception as e:
        st.error(f"❌ Database error while reading 'daily_operations': {e}")
        rtc = pd.DataFrame()

    # ------------------- Service Master -------------------
    try:
        service_master = pd.read_sql(
            "SELECT service_number, dept_time, arr_time, day_night_code, depot FROM service_master",
            engine
        )
    except Exception as e:
        st.error(f"❌ Database error while reading 'service_master': {e}")
        service_master = pd.DataFrame()

    # ------------------- Driver Absenteeism -------------------
    try:
        lsa = pd.read_sql("SELECT * FROM driver_absenteeism", engine)
    except Exception as e:
        st.error(f"❌ Database error while reading 'driver_absenteeism': {e}")
        lsa = pd.DataFrame()

    # ------------------- GHC Data -------------------
    try:
        ghc_2024 = pd.read_sql("SELECT * FROM ghc_2024", engine)
    except Exception as e:
        st.error(f"❌ Database error while reading 'ghc_2024': {e}")
        ghc_2024 = pd.DataFrame()

    # ------------------- Normalize Keys -------------------
    if not rtc.empty:
        rtc["service_number"] = rtc["service_number"].astype(str).str.strip().str.upper()
        rtc[depot_col] = rtc[depot_col].astype(str).str.strip().str.upper()

    if not service_master.empty:
        service_master["service_number"] = service_master["service_number"].astype(str).str.strip().str.upper()
        service_master["depot"] = service_master["depot"].astype(str).str.strip().str.upper()

    # ------------------- Convert Times -------------------
    def convert_time(x):
        if pd.isnull(x):
            return None
        if isinstance(x, pd.Timedelta):
            return (datetime.min + x).time()
        if isinstance(x, datetime):
            return x.time()
        if isinstance(x, str):
            try:
                return datetime.strptime(x, "%H:%M:%S").time()
            except:
                try:
                    return datetime.strptime(x, "%H:%M").time()
                except:
                    return None
        return None

    if not service_master.empty:
        service_master['dept_time'] = service_master['dept_time'].apply(convert_time)
        service_master['arr_time'] = service_master['arr_time'].apply(convert_time)
    else:
        for c in ['dept_time', 'arr_time', 'day_night_code']:
            if c not in service_master.columns:
                service_master[c] = None

    # ------------------- Calculate Hours -------------------
    def time_cal(dep, arr, day_night_code):
        dummy_date = datetime.today().date()
        if not isinstance(dep, time) or not isinstance(arr, time):
            return None
        DEP_TIME_dt = datetime.combine(dummy_date, dep)
        ARR_TIME_dt = datetime.combine(dummy_date, arr)
        if day_night_code == 'N':
            ARR_TIME_dt += timedelta(days=1)
            duration = ARR_TIME_dt - DEP_TIME_dt
            if duration.total_seconds() < 6 * 3600:
                ARR_TIME_dt += timedelta(days=1)
                duration = ARR_TIME_dt - DEP_TIME_dt
        else:
            if ARR_TIME_dt < DEP_TIME_dt:
                ARR_TIME_dt += timedelta(days=1)
            duration = ARR_TIME_dt - DEP_TIME_dt
        return duration.total_seconds() / 3600

    # ------------------- Merge Data -------------------
    if not rtc.empty and not service_master.empty:
        rtc['depot'] = rtc['depot'].astype(str).str.strip().str.upper()
        service_master['depot'] = service_master['depot'].astype(str).str.strip().str.upper()

        service_master_unique = service_master.drop_duplicates(subset=['depot', 'service_number'], keep='first')

        merged_df = pd.merge(
            rtc,
            service_master_unique[['depot', 'service_number', 'dept_time', 'arr_time', 'day_night_code']],
            on=['depot', 'service_number'],
            how='left',
            suffixes=('_rtc', '_master')
        )

        merged_df['hours'] = merged_df.apply(
            lambda row: time_cal(row.get('dept_time'), row.get('arr_time'), row.get('day_night_code')),
            axis=1
        )

        rtc = merged_df
        rtc[DEPOT_COL] = rtc['depot'].astype(str).str.strip().str.upper()

    # ------------------- Normalize GHC -------------------
    if not ghc_2024.empty:
        ghc_2024 = ghc_2024.rename(columns=lambda x: x.strip().lower().replace(" ", "_"))
        ghc_2024["depot"] = ghc_2024["depot"].astype(str).str.strip().str.upper()

    # ------------------- Normalize RTC -------------------
    if not rtc.empty:
        rtc[DATE_SRD_COL] = pd.to_datetime(rtc[DATE_SRD_COL], errors="coerce")
        rtc[KM_COL] = pd.to_numeric(rtc[KM_COL], errors="coerce")
        rtc[HOURS_COL] = pd.to_numeric(rtc[HOURS_COL], errors="coerce")
        rtc[EARNINGS_COL] = pd.to_numeric(rtc[EARNINGS_COL], errors="coerce")
        rtc["month"] = rtc[DATE_SRD_COL].dt.to_period("M").dt.to_timestamp()
        rtc["year"] = rtc[DATE_SRD_COL].dt.year

        depot_monthly = rtc.groupby([DEPOT_COL, "year", "month"]).agg(
            total_km=(KM_COL, "sum"),
            total_hours=(HOURS_COL, "sum"),
            total_earnings=(EARNINGS_COL, "sum")
        ).reset_index()

        driver_monthly = rtc.groupby([DEPOT_COL, EMP_COL, "year", "month"]).agg(
            total_km=(KM_COL, "sum"),
            total_hours=(HOURS_COL, "sum"),
            total_earnings=(EARNINGS_COL, "sum")
        ).reset_index()

    # ------------------- Normalize LSA -------------------
    if not lsa.empty:
        lsa[LSA_DATE_COL] = pd.to_datetime(lsa[LSA_DATE_COL], errors="coerce")
        lsa[DEPOT_COL] = lsa[DEPOT_COL].astype(str).str.strip().str.upper()
        lsa_valid = lsa.dropna(subset=[LEAVE_TYPE_COL]).copy()
        lsa_valid["month"] = lsa_valid[LSA_DATE_COL].dt.to_period("M").dt.to_timestamp()
        lsa_valid["year"] = lsa_valid[LSA_DATE_COL].dt.year

        depot_abs = lsa_valid.groupby([DEPOT_COL, "year", "month"]).size().rename("absenteeism").reset_index()
        driver_abs = lsa_valid.groupby([DEPOT_COL, EMP_COL, "year", "month"]).size().rename("absenteeism").reset_index()

        depot_monthly = pd.merge(depot_monthly, depot_abs, on=[DEPOT_COL, "year", "month"], how="left").fillna(0)
        driver_monthly = pd.merge(driver_monthly, driver_abs, on=[DEPOT_COL, EMP_COL, "year", "month"], how="left").fillna(0)
    else:
        lsa_valid = pd.DataFrame()

    return depot_monthly, driver_monthly, lsa_valid, ghc_2024

def format_indian(num):
    """Format number in Indian numbering system (Lakhs, Crores)."""
    try:
        num = int(round(num))
    except (ValueError, TypeError):
        return str(num)

    s = str(num)
    if len(s) <= 3:
        return s

    last3 = s[-3:]
    rest = s[:-3]

    parts = []
    while len(rest) > 2:
        parts.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.append(rest)

    return ",".join(parts[::-1]) + "," + last3

# ------------------------------------------
def plot_comparison_bar(combined_df, ycol, avg1, avg2, depot1, depot2, title, ytitle, compare_with_region=False, region_avg=None):
    depot1 = depot1.strip()
    depot2 = depot2.strip()

    depots = combined_df["Depot"].unique().tolist()

    color_map = {}
    for depot in depots:
        if depot == depot1:
            color_map[depot] = "#1f77b4"  # Primary depot blue
        elif depot == depot2 and not compare_with_region:
            color_map[depot] = "#add8e6"  # Compare depot light blue
        else:
            color_map[depot] = "#d3d3d3"  # Others grey

    if compare_with_region:
        if depot2 not in color_map:
            color_map[depot2] = "#B62929"  # Red for region average

    chart_df = (
        combined_df.groupby(['Depot', 'year', 'month'])
        .agg(total=(ycol, 'sum'))
        .reset_index()
        .sort_values(['year', 'month'])
    )
    chart_df['month_label'] = chart_df['month'].dt.strftime('%b-%y')

    fig = px.bar(
        chart_df,
        x='month_label',
        y='total',
        color='Depot',
        barmode='group',
        labels={'total': ytitle, 'month_label': 'Month-Year'},
        text_auto=True,
        color_discrete_map=color_map,
    )

    if depot1 in color_map:
        fig.add_hline(
            y=avg1,
            line_dash="dot",
            line_color=color_map[depot1],
            annotation_text=f"{depot1} Avg: {avg1:,.0f}",
            annotation_position="top left"
        )

    if compare_with_region and region_avg is not None:
        fig.add_hline(
            y=region_avg,
            line_dash="dot",
            line_color="#B62929",
            annotation_text=f"{depot2} Region Avg: {region_avg:,.0f}",
            annotation_position="top right"
        )
    elif depot2 in color_map:
        fig.add_hline(
            y=avg2,
            line_dash="dot",
            line_color=color_map[depot2],
            annotation_text=f"{depot2} Avg: {avg2:,.0f}",
            annotation_position="top right"
        )

    fig.update_layout(
        title=title,
        yaxis_tickformat=',',
        xaxis_title="Month-Year",
        yaxis_title=ytitle,
        legend=dict(
            title="Depot",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            font=dict(size=10),
        ),
    )

    st.plotly_chart(fig, use_container_width=True, key=str(uuid.uuid4()))

def plot_bar(df, ycol, depot_avg, title, ytitle, depot=None, region_avg=None):
    chart_df = (
        df.groupby(["year", "month"])
        .agg(total=(ycol, "sum"))
        .reset_index()
        .sort_values(["year", "month"])
    )
    chart_df["month_label"] = chart_df["month"].dt.strftime("%b-%y")

    default_color = "#1f77b4"

    bar_color = default_color
    line_color = default_color

    if depot:
        color_palette = itertools.cycle([
            "#1f77b4", "#b3ebf5", "#ff7f0e", "#2ca02c",
            "#d62728", "#9467bd", "#8c564b"
        ])
        if 'Depot' in df.columns:
            color_map = {name: next(color_palette) for name in df['Depot'].unique()}
            bar_color = color_map.get(depot, default_color)
            line_color = bar_color

    fig = px.bar(
        chart_df,
        x="month_label",
        y="total",
        labels={"total": ytitle, "month_label": "Month-Year"},
        color_discrete_sequence=[bar_color],
        text_auto=True
    )

    if depot_avg is not None:
        fig.add_hline(
            y=depot_avg,
            line_dash="dot",
            line_color="#b41f1f",
            annotation_text=f"Depot Avg: {depot_avg:,.0f}",
            annotation_position="top left",
            annotation_font_color="black",
            annotation_font_size=13
        )

    if region_avg is not None:
        fig.add_hline(
            y=region_avg,
            line_dash="dash",
            line_color="#45B629",
            annotation_text=f"Region Avg: {region_avg:,.0f}",
            annotation_position="bottom right",
            annotation_font_color="black",
            annotation_font_size=13
        )

    fig.update_traces(
        texttemplate='%{y:,.0f}', 
        textposition='inside', 
        textfont=dict(color='black', size=14, family='Arial')
    )

    fig.update_layout(
        title=title,
        yaxis_tickformat=',',
        xaxis_title="Month-Year",
        yaxis_title=ytitle,
    )

    st.plotly_chart(fig, use_container_width=True, key=str(uuid.uuid4()))

def show_main_bar_line_charts(df1, depot, region_avgs=None, show_region=False):
    """
    Draw KMs / Hours / Earnings / Absenteeism bar charts for a depot.
    """
    depot = str(depot or "").strip()
    is_region_all = depot.upper().startswith("ALL")

    def safe_mean(df, col):
        try:
            return float(df[col].mean()) if (col in df.columns and not df[col].isna().all()) else None
        except Exception:
            return None

    depot_avg_km = safe_mean(df1, "total_km") if not is_region_all else None
    depot_avg_hours = safe_mean(df1, "total_hours") if not is_region_all else None
    depot_avg_earn = safe_mean(df1, "total_earnings") if not is_region_all else None
    depot_avg_abs = safe_mean(df1, "absenteeism") if not is_region_all else None

    if show_region and region_avgs:
        region_avg_km = region_avgs.get("total_km")
        region_avg_hours = region_avgs.get("total_hours")
        region_avg_earn = region_avgs.get("total_earnings")
        region_avg_abs = region_avgs.get("absenteeism")
    else:
        region_avg_km = region_avg_hours = region_avg_earn = region_avg_abs = None

    if df1 is None or df1.empty:
        st.info(f"🚫 No monthly data to plot for **{depot or 'Depot'}**.")
        return

    col1, col2, col3 = st.columns([1, 6, 1])
    with col2:
        plot_bar(
            df1, "total_km", depot_avg_km,
            f"{depot} – Total KMs", "KMs",
            depot=depot,
            region_avg=region_avg_km
        )

    col1, col2, col3 = st.columns([1, 6, 1])
    with col2:
        plot_bar(
            df1, "total_hours", depot_avg_hours,
            f"{depot} – Total Hours", "Hours",
            depot=depot,
            region_avg=region_avg_hours
        )

    col1, col2, col3 = st.columns([1, 6, 1])
    with col2:
        plot_bar(
            df1, "total_earnings", depot_avg_earn,
            f"{depot} – Total Earnings", "Earnings",
            depot=depot,
            region_avg=region_avg_earn
        )

    col1, col2, col3 = st.columns([1, 6, 1])
    with col2:
        plot_bar(
            df1, "absenteeism", depot_avg_abs,
            f"{depot} – Absenteeism", "Absenteeism",
            depot=depot,
            region_avg=region_avg_abs
        )

def show_depot_metrics(df, depot_name, is_region=False):
    """
    Display summary metrics for a depot (or a region when is_region=True).
    """
    def safe_title(name):
        try:
            return (name or "").title()
        except Exception:
            return str(name)

    display_name = safe_title(depot_name) if depot_name is not None else "Depot"

    if df is not None and not df.empty:
        avg_kms_month = df['total_km'].mean()
        num_years = len(df['year'].unique())

        years = df['year'].unique()
        total_days = sum(366 if calendar.isleap(int(y)) else 365 for y in years)
        total_days = total_days if total_days > 0 else 1

        avg_kms_day = df['total_km'].mean() * (12 / 365) if num_years > 0 else df['total_km'].sum() / total_days
        avg_hours = df['total_hours'].mean()
        avg_hours_day = df['total_hours'].mean() * (12 / 365) if num_years > 0 else df['total_hours'].sum() / total_days
        avg_earnings = df['total_earnings'].mean()
        avg_earnings_day = df['total_earnings'].mean() * (12 / 365) if num_years > 0 else df['total_earnings'].sum() / total_days
        avg_absenteeism = df['absenteeism'].mean()
        avg_absenteeism_day = df['absenteeism'].mean() * (12 / 365) if num_years > 0 else df['absenteeism'].sum() / total_days

        label_prefix = "Region" if is_region else display_name

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(f"{display_name} Avg KMs/Month", format_indian(avg_kms_month))
        with col2:
            st.metric(f"{display_name} Avg Hours/Month", format_indian(avg_hours))
        with col3:
            st.metric(f"{display_name} Avg Earnings/Month", format_indian(avg_earnings))
        with col4:
            st.metric(f"{label_prefix} Avg Absenteeism/Month", format_indian(avg_absenteeism))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(f"{display_name} Avg KMs/Day", format_indian(avg_kms_day))
        with col2:
            st.metric(f"{display_name} Avg Hours/Day", format_indian(avg_hours_day))
        with col3:
            st.metric(f"{display_name} Avg Earnings/Day", format_indian(avg_earnings_day))
        with col4:
            st.metric(f"{label_prefix} Avg Absenteeism/Day", format_indian(avg_absenteeism_day))
    else:
        st.info(f"🚫 No valid data for **{display_name}**.")

def persistent_checkbox(label, key):
    if key not in st.session_state:
        st.session_state[key] = False
    return st.checkbox(label, key=key)
# ========================= MAIN DASHBOARD FUNCTION =========================
def depot_ui():
    import datetime as dt_mod

    st.title("TGSRTC – Depot Productivity Dashboard")

    # ------------------- Database Connection -------------------
    mysql_conn = get_connection()
    if not mysql_conn:
        st.stop()

    userid = st.session_state.get("userid", None)
    if not userid:
        st.error("User not logged in.")
        st.stop()

    role = get_role_by_userid(userid)
    depot_settings = get_depot_settings(mysql_conn)

    # ------------------- REGION DROPDOWN (Always visible) -------------------
    all_regions = get_all_regions(mysql_conn)
    if not all_regions:
        st.error("No regions found in TS_ADMIN.")
        mysql_conn.close()
        st.stop()

    region1 = st.selectbox(
        "Select Region",
        all_regions,
        key="select_region"
    )

    st.markdown(f"### Region: **{region1}**")

    # ------------------- DEPOT DROPDOWN (based on selected region) -------------------
    depots_in_region1 = get_depots_in_region(mysql_conn, region1)
    depots_in_region1 = [d.strip().upper() for d in depots_in_region1]

    if not depots_in_region1:
        st.error(f"No depots found for region {region1}.")
        mysql_conn.close()
        st.stop()

    depot1 = st.selectbox(
        "Select Depot",
        depots_in_region1,
        key="select_depot"
    )

    depot1 = depot1.strip().upper()
    depot_category1 = depot_settings.get(depot1, "Unknown")

    # ------------------- Compare Depots -------------------
    col1, col2, col3, col4 = st.columns(4)
    with col4:
        compare_regions = st.checkbox("🔁 Compare Depots")
    depot2 = None
    depot_category2 = None
    if compare_regions:
        depots_for_depot2 = [d for d in depots_in_region1 if d != depot1]
        if depots_for_depot2:
            col1, col2, col3, col4 = st.columns(4)
            with col4:
                depot2 = st.selectbox("Depot to compare in this region", depots_for_depot2, key="depot2")
                depot2 = depot2.strip().upper()
                depot_category2 = depot_settings.get(depot2, "Unknown")
        else:
            st.warning("No other depots available to compare in this region.")
            compare_regions = False

    # ------------------- Load Data for Depot1 -------------------
    depot1_monthly, driver_monthly1, lsavalid1, ghc1 = preaggregate(selected_depot=depot1, config=config)
    if not depot1_monthly.empty and DEPOT_COL in depot1_monthly.columns:
        depot1_monthly[DEPOT_COL] = depot1_monthly[DEPOT_COL].astype(str).str.strip().str.upper()
    depot1_monthly["Category"] = depot1_monthly.get(DEPOT_COL, pd.Series()).map(depot_settings).fillna("Unknown")

    # ------------------- Load Data for Depot2 (if comparing) -------------------
    depot2_monthly = pd.DataFrame(columns=["year", "month", "total_km", "total_hours", "total_earnings", "absenteeism"])
    driver_monthly2 = pd.DataFrame()
    lsavalid2 = pd.DataFrame()
    ghc2 = pd.DataFrame()

    if compare_regions and depot2:
        try:
            depot2_monthly, driver_monthly2, lsavalid2, ghc2 = preaggregate(selected_depot=depot2, config=config)
        except Exception:
            depot2_monthly = pd.DataFrame(columns=["year", "month", "total_km", "total_hours", "total_earnings", "absenteeism"])
            driver_monthly2 = pd.DataFrame()
            lsavalid2 = pd.DataFrame()
            ghc2 = pd.DataFrame()

    # ------------------- Year Filter -------------------
    years1 = sorted(depot1_monthly["year"].dropna().unique()) if not depot1_monthly.empty else []
    years2 = sorted(depot2_monthly["year"].dropna().unique()) if (compare_regions and depot2_monthly is not None and not depot2_monthly.empty) else []

    all_years = sorted(list(set(years1 + years2)))
    year_options = ["All"] + [str(y) for y in all_years]
    current_year = dt_mod.datetime.now().year
    default_index = year_options.index(str(current_year)) if str(current_year) in year_options else 0

    col = st.columns([3, 7, 1])
    with col[0]:
        year_sel = st.selectbox("Year", year_options, index=default_index, key="year_sel")

    # ------------------- APPLY YEAR FILTER TO PREAGGREGATED DATA -------------------
    def apply_year_filter_monthly(df_monthly, year_sel):
        if df_monthly is None or df_monthly.empty:
            return pd.DataFrame(columns=["year", "month", "total_km", "total_hours", "total_earnings", "absenteeism", "Depot"])
        if year_sel == "All":
            return df_monthly
        try:
            return df_monthly[df_monthly["year"] == int(year_sel)].copy()
        except Exception:
            return df_monthly

    depot1_monthly = apply_year_filter_monthly(depot1_monthly, year_sel)
    driver_monthly1 = apply_year_filter_monthly(driver_monthly1, year_sel)
    if not lsavalid1.empty and year_sel != "All":
        lsavalid1 = lsavalid1[lsavalid1["year"] == int(year_sel)].copy()

    if compare_regions and depot2:
        depot2_monthly = apply_year_filter_monthly(depot2_monthly, year_sel)
        driver_monthly2 = apply_year_filter_monthly(driver_monthly2, year_sel)
        if not lsavalid2.empty and year_sel != "All":
            lsavalid2 = lsavalid2[lsavalid2["year"] == int(year_sel)].copy()

        if depot2_monthly is None or depot2_monthly.empty:
            try:
                if year_sel == "All":
                    query = """
                        SELECT 
                            YEAR(operations_date) AS year,
                            MONTH(operations_date) AS month,
                            SUM(opd_kms) AS total_km,
                            SUM(daily_earnings) AS total_earnings,
                            COUNT(*) AS absenteeism
                        FROM daily_operations
                        WHERE UPPER(TRIM(depot)) = %s
                        GROUP BY YEAR(operations_date), MONTH(operations_date)
                        ORDER BY YEAR(operations_date), MONTH(operations_date)
                    """
                    params = (depot2.upper().strip(),)
                else:
                    query = """
                        SELECT 
                            YEAR(operations_date) AS year,
                            MONTH(operations_date) AS month,
                            SUM(opd_kms) AS total_km,
                            SUM(daily_earnings) AS total_earnings,
                            COUNT(*) AS absenteeism
                        FROM daily_operations
                        WHERE UPPER(TRIM(depot)) = %s
                          AND YEAR(operations_date) = %s
                        GROUP BY YEAR(operations_date), MONTH(operations_date)
                        ORDER BY YEAR(operations_date), MONTH(operations_date)
                    """
                    params = (depot2.upper().strip(), int(year_sel))

                depot2_monthly = pd.read_sql(query, mysql_conn, params=params)
            except Exception as e:
                st.error(f"Error loading monthly data for {depot2}: {e}")
                depot2_monthly = pd.DataFrame(columns=["year", "month", "total_km", "total_hours", "total_earnings", "absenteeism"])

        if not depot2_monthly.empty and DEPOT_COL in depot2_monthly.columns:
            depot2_monthly[DEPOT_COL] = depot2_monthly[DEPOT_COL].astype(str).str.strip().str.upper()
        if "Depot" not in depot2_monthly.columns:
            depot2_monthly = depot2_monthly.assign(Depot=depot2 if depot2 else None)

    # ------------------- Final safety for depot_monthly DFs -------------------
    required_cols = ["year", "month", "total_km", "total_hours", "total_earnings", "absenteeism", "Depot"]
    for df_name, df in [("depot1_monthly", depot1_monthly), ("depot2_monthly", depot2_monthly)]:
        if df is None or not isinstance(df, pd.DataFrame):
            if df_name == "depot1_monthly":
                depot1_monthly = pd.DataFrame(columns=required_cols)
                depot1_monthly["Depot"] = depot1
            else:
                depot2_monthly = pd.DataFrame(columns=required_cols)
                depot2_monthly["Depot"] = depot2

    # ------------------- Check Data -------------------
    if depot1_monthly.empty:
        st.warning(f"No data found for {depot1} ({depot_category1}) in the selected year.")
        mysql_conn.close()
        st.stop()

    if compare_regions and (depot2_monthly is None or depot2_monthly.empty):
        st.warning(f"No data found for {depot2} ({depot_category2}) in the selected year.")
        compare_regions = False

    # ------------------- Display Metrics & Charts -------------------
    st.markdown(f"### Depot Selected: **{depot1}** ({depot_category1})")

    if not compare_regions or not depot2:
        show_depot_metrics(depot1_monthly, depot1)

        show_region_checkbox = persistent_checkbox("Show Region Average", "show_region_checkbox")

        region_avgs = None
        region_depots = None
        if show_region_checkbox:
            try:
                region_avgs = compute_region_averages(mysql_conn, region1, year_sel=year_sel)
                region_depots = region_avgs.get("depots") if region_avgs else None
            except Exception:
                region_avgs = None
                region_depots = None

        show_main_bar_line_charts(depot1_monthly, depot1, region_avgs=region_avgs, show_region=show_region_checkbox)
        show_absenteeism_pie(depot1, lsavalid1, year_sel, is_region=show_region_checkbox, region_depots=region_depots)
        show_health_grade_distribution(depot1, ghc1, is_region=show_region_checkbox, region_depots=region_depots)
        show_top_bottom_drivers(depot1, driver_monthly1, years1, DEPOT_COL, EMP_COL, is_region=show_region_checkbox, region_depots=region_depots)
        show_mu_sl_reasons(depot1, config['db'], is_region=show_region_checkbox, region_depots=region_depots)
    else:
        if depot2 is None:
            st.info("Select a depot to compare.")
        else:
            st.markdown(f"#### {depot1} Metrics")
            show_depot_metrics(depot1_monthly, depot1)

            st.markdown(f"#### {depot2} Metrics")
            show_depot_metrics(depot2_monthly if depot2_monthly is not None else pd.DataFrame(), depot2)

            show_region_checkbox = persistent_checkbox("Show Region Average", "show_region_checkbox")

            region_avgs = None
            region_depots = None
            if show_region_checkbox:
                try:
                    region_avgs = compute_region_averages(mysql_conn, region1, year_sel=year_sel)
                    region_depots = region_avgs.get("depots") if region_avgs else None
                except Exception:
                    region_avgs = None
                    region_depots = None

            def ensure_monthly_df(df, depot_name):
                if df is None:
                    df = pd.DataFrame(columns=["year", "month", "total_km", "total_hours", "total_earnings", "absenteeism"])
                for c in ["total_km", "total_hours", "total_earnings", "absenteeism"]:
                    if c not in df.columns:
                        df[c] = 0.0
                if "Depot" not in df.columns:
                    df = df.assign(Depot=depot_name)
                if "month" in df.columns:
                    try:
                        df["month"] = pd.to_datetime(df["month"], errors="coerce")
                    except Exception:
                        pass
                else:
                    df["month"] = pd.NaT
                return df

            depot1_monthly_safe = ensure_monthly_df(depot1_monthly, depot1)
            depot2_monthly_safe = ensure_monthly_df(depot2_monthly, depot2)

            if depot1_monthly_safe.empty or depot2_monthly_safe.empty:
                st.warning("Comparison requires data for both depots in the selected year. Adjust Year or depot selection.")
            else:
                has_months = not (depot1_monthly_safe["month"].isna().all() or depot2_monthly_safe["month"].isna().all())
                if has_months:
                    min_month = min(depot1_monthly_safe["month"].min(), depot2_monthly_safe["month"].min())
                    max_month = max(depot1_monthly_safe["month"].max(), depot2_monthly_safe["month"].max())
                    all_months = pd.date_range(start=min_month, end=max_month, freq="MS")

                    def normalize(df):
                        grouped = df.groupby(["Depot", "month"], dropna=False).agg({
                            "total_km": "sum",
                            "total_hours": "sum",
                            "total_earnings": "sum",
                            "absenteeism": "sum"
                        }).reset_index()
                        frames = []
                        for dname in grouped["Depot"].unique():
                            sub = grouped[grouped["Depot"] == dname].set_index("month").reindex(all_months).fillna(0).reset_index()
                            sub = sub.rename(columns={"index": "month"})
                            sub["Depot"] = dname
                            sub["year"] = sub["month"].dt.year
                            frames.append(sub)
                        return pd.concat(frames, ignore_index=True, sort=False)

                    d1 = normalize(depot1_monthly_safe)
                    d2 = normalize(depot2_monthly_safe)
                    combined_df = pd.concat([d1, d2], ignore_index=True, sort=False).fillna(0)
                else:
                    combined_df = pd.concat([depot1_monthly_safe, depot2_monthly_safe], ignore_index=True, sort=False).fillna(0)

                def safe_mean(df, col):
                    if col not in df.columns:
                        return 0.0
                    vals = df[col].dropna()
                    return float(vals.mean()) if not vals.empty else 0.0

                for metric, title, unit in [
                    ("total_km", "Total KMs", "KMs"),
                    ("total_hours", "Total Hours", "Hours"),
                    ("total_earnings", "Total Earnings", "Earnings"),
                    ("absenteeism", "Absenteeism", "Absenteeism")
                ]:
                    avg1 = safe_mean(depot1_monthly_safe, metric)
                    avg2 = safe_mean(depot2_monthly_safe, metric)

                    region_line = None
                    if region_avgs and metric in region_avgs and show_region_checkbox:
                        region_line = region_avgs.get(metric)

                    try:
                        plot_comparison_bar(
                            combined_df, metric,
                            avg1, avg2,
                            depot1, depot2,
                            f"Comparison – {title}", unit,
                            compare_with_region=True,
                            region_avg=region_line
                        )
                    except TypeError:
                        plot_comparison_bar(
                            combined_df, metric,
                            avg1, avg2,
                            depot1, depot2,
                            f"Comparison – {title}", unit,
                            compare_with_region=True
                        )

# alias for login.py import: from depot_UI import depot_UI
def depot_UI():
    depot_ui()
#  ------------------------------------------
# 📊 PIE CHART (Leave Type Distribution)
# ------------------------------------------
def show_absenteeism_pie(entity_name, lsa_df, year_sel="All", is_region=False, region_depots=None):
    """
    Show absenteeism reasons distribution as a pie chart.
    Works for both depot-level and region-level ("All" selection).
    """
    st.markdown("## 5. Absenteeism Reasons Distribution")

    if lsa_df is None or lsa_df.empty:
        st.info(f"🚫 No leave data found for **{entity_name}**.")
        return

    lsa_df['depot'] = lsa_df['depot'].astype(str).str.strip().str.upper()

    if is_region and region_depots:
        depots_upper = [d.upper() for d in region_depots]
        lsa_df = lsa_df[lsa_df['depot'].isin(depots_upper)]
    else:
        lsa_df = lsa_df[lsa_df['depot'] == entity_name.strip().upper()]

    if lsa_df.empty:
        st.info(f"🚫 No records for **{entity_name}** after filtering.")
        return

    lsa_df['date'] = pd.to_datetime(lsa_df['date'], errors="coerce")
    lsa_df['year'] = lsa_df['date'].dt.year

    lsa_valid = lsa_df.dropna(subset=['leave_type']).copy()
    if lsa_valid.empty:
        st.info(f"🚫 No valid leave types for **{entity_name}**.")
        return

    if year_sel != "All":
        lsa_valid = lsa_valid[lsa_valid["year"] == int(year_sel)]

    if lsa_valid.empty:
        st.info(f"🚫 No leave data for **{entity_name}** in year {year_sel}.")
        return

    leave_counts = (
        lsa_valid['leave_type']
        .value_counts()
        .reset_index(name="Count")
        .rename(columns={"index": "leave_type"})
    )

    fig = px.pie(
        leave_counts,
        names="leave_type",
        values="Count",
        title=f"<b>Leave Type Distribution – {entity_name}</b>",
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")

    st.plotly_chart(fig, use_container_width=True)

def show_health_grade_distribution(entity_name, ghc_2024, is_region=False, region_depots=None):
    """
    Show employee health grade distribution.
    Works for both depot-level and region-level ("All" selection).
    """
    st.markdown("## 6. Employee Health Grade Distribution")

    ghc_2024.columns = ghc_2024.columns.str.strip().str.lower().str.replace(" ", "_")

    if "final_grading" not in ghc_2024.columns:
        st.error("❌ 'final_grading' column not found.")
        return

    if "depot" not in ghc_2024.columns:
        st.error("❌ 'depot' column not found.")
        return

    ghc_2024["depot"] = ghc_2024["depot"].astype(str).str.strip().str.upper()

    if is_region and region_depots:
        depots_upper = [d.upper() for d in region_depots]
        ghc3_filtered = ghc_2024[ghc_2024["depot"].isin(depots_upper)].copy()
    else:
        ghc3_filtered = ghc_2024[ghc_2024["depot"] == entity_name.strip().upper()].copy()

    if ghc3_filtered.empty:
        st.warning(f"⚠️ No health grade data found for **{entity_name}**.")
        return

    ghc3_filtered.rename(columns={"final_grading": "grade"}, inplace=True)
    ghc3_filtered = ghc3_filtered[ghc3_filtered["grade"].notna()]
    ghc3_filtered["grade"] = ghc3_filtered["grade"].astype(str).str.strip()

    if ghc3_filtered.empty:
        st.warning(f"⚠️ No valid health grade data for **{entity_name}**.")
        return

    grade_counts = ghc3_filtered.groupby("grade").size().reset_index(name="num_employees")
    if grade_counts.empty:
        st.info(f"ℹ️ No Health Grade data available for {entity_name}.")
        return

    fig = px.bar(
        grade_counts.sort_values("grade"),
        x="grade",
        y="num_employees",
        labels={"grade": "Health Grade", "num_employees": "Number of Employees"},
        color_discrete_sequence=["#1172a5"],
        text_auto=True,
    )
    fig.update_traces(texttemplate='%{y}', textposition='outside')
    fig.update_layout(
        title={'text': f"<b>Employee Health Grades – {entity_name}</b>",
               'y': 0.9, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top'},
        xaxis_title="Health Grade",
        yaxis_title="Number of Employees",
        plot_bgcolor="white",
        bargap=0.3,
        showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, zeroline=True),
        margin=dict(l=40, r=40, t=80, b=40)
    )

    col1, col2, col3 = st.columns([1, 6, 1])
    with col2:
        st.plotly_chart(fig, use_container_width=True)

#TOP & BOTTOM DRIVERS
def show_top_bottom_drivers(entity_name, driver_monthly, years, DEPOT_COL, EMP_COL, is_region=False, region_depots=None):
    """
    Show Top & Bottom 5 drivers for either a depot or all depots in a region.
    """
    st.markdown("## Top & Bottom 5 Drivers")

    if is_region and region_depots:
        depot_keys = [d.strip().lower() for d in region_depots]
        df = driver_monthly[driver_monthly[DEPOT_COL].str.strip().str.lower().isin(depot_keys)].copy()
    else:
        df = driver_monthly[driver_monthly[DEPOT_COL].str.strip().str.lower() == entity_name.strip().lower()].copy()

    if df.empty:
        st.info(f"🚫 No driver data for **{entity_name}**.")
        return

    df["month_label"] = df["month"].dt.strftime("%b-%y")

    col1, col2, col3 = st.columns(3)

    year_list = sorted(df["year"].dropna().unique())
    year_options = ["All"] + [str(y) for y in year_list]
    default_year_index = year_options.index(str(max(year_list))) if len(year_list) > 0 else 0

    top_year = col1.selectbox(
        "Year",
        year_options,
        index=default_year_index,
        key="top_driver_year"
    )

    if top_year == "All":
        month_options = sorted(df["month_label"].unique(), key=lambda x: pd.to_datetime(x, format="%b-%y"))
    else:
        month_options = sorted(
            df[df["year"] == int(top_year)]["month_label"].unique(),
            key=lambda x: pd.to_datetime(x, format="%b-%y")
        )

    month_options_display = ["All"] + month_options
    default_month_index = month_options_display.index(month_options[-1]) if month_options else 0

    top_month = col2.selectbox(
        "Month",
        month_options_display,
        index=default_month_index,
        key="top_driver_month"
    )

    rank_by = col3.selectbox("Rank by", ["KMs", "Hours", "Earnings", "Absenteeism"])

    if top_year != "All":
        df = df[df["year"] == int(top_year)]
    if top_month != "All":
        df = df[df["month_label"] == top_month]

    if df.empty:
        st.info("🚫 No driver data for selected filters.")
        return

    rank_col_map = {
        "KMs": "total_km",
        "Hours": "total_hours",
        "Earnings": "total_earnings",
        "Absenteeism": "absenteeism",
    }
    rank_col = rank_col_map[rank_by]

    summary = df.groupby(EMP_COL).agg(
        total_km=('total_km', 'sum'),
        total_hours=('total_hours', 'sum'),
        total_earnings=('total_earnings', 'sum'),
        absenteeism=('absenteeism', 'sum')
    ).reset_index()

    if summary.empty:
        st.info("🚫 No data after grouping.")
        return

    if rank_by == "Absenteeism":
        top5 = summary.sort_values(rank_col, ascending=True).head(5)
        bottom5 = summary.sort_values(rank_col, ascending=False).head(5)
    else:
        top5 = summary.sort_values(rank_col, ascending=False).head(5)
        bottom5 = summary.sort_values(rank_col, ascending=True).head(5)

    top5.insert(0, "Rank", range(1, len(top5) + 1))
    bottom5.insert(0, "Rank", range(1, len(bottom5) + 1))
    top5 = top5.set_index("Rank")
    bottom5 = bottom5.set_index("Rank")

    colA, colB = st.columns(2)
    colA.subheader(f"7. Top 5 by {rank_by} ({'Region' if is_region else 'Depot'})")
    colA.dataframe(top5)
    colB.subheader(f"8. Bottom 5 by {rank_by} ({'Region' if is_region else 'Depot'})")
    colB.dataframe(bottom5)

#MU/SL Reasons
def show_mu_sl_reasons(entity_name, db_config, is_region=False, region_depots=None):
    st.markdown("## 9. Medical Unfit (MU) & Sick Leave (SL) Reasons")
    db_user = config['db']['user']
    db_password = quote_plus(config['db']['password'])
    db_host = config['db']['host']
    db_name = config['db']['database']

    engine = create_engine(f"mysql+pymysql://{db_user}:{db_password}@{db_host}/{db_name}")
    df = pd.read_sql("SELECT * FROM input_data", con=engine)
    df.columns = df.columns.str.strip().str.replace(" ", "_")

    if "depot_name" not in df.columns or "data_date" not in df.columns:
        st.error("❌ Required columns ('depot_name' or 'data_date') missing in input_data.")
        return

    df["depot_name"] = df["depot_name"].astype(str).str.strip().str.lower()

    if is_region and region_depots:
        region_keys = [d.strip().lower() for d in region_depots]
        df = df[df["depot_name"].isin(region_keys)]
    else:
        df = df[df["depot_name"] == entity_name.strip().lower()]

    if df.empty:
        st.info(f"🚫 No MU/SL data found for **{entity_name.title()}**.")
        return

    df["data_date"] = pd.to_datetime(df["data_date"], errors="coerce")
    today = pd.Timestamp.today().normalize()
    df = df[df["data_date"].notna() & (df["data_date"] <= today)]
    df["year"] = df["data_date"].dt.year
    df["month_period"] = df["data_date"].dt.to_period("M")

    col1, col2 = st.columns(2)

    years = sorted(df["year"].dropna().unique())
    year_options = ["All"] + [str(y) for y in years]
    default_year_index = year_options.index(str(max(years))) if len(years) > 0 else 0

    selected_year = col1.selectbox(
        "Year", year_options,
        index=default_year_index,
        key="year_selectbox"
    )

    filtered_df = df if selected_year == "All" else df[df["year"] == int(selected_year)]

    month_display = [m.strftime("%b-%Y") for m in sorted(filtered_df["month_period"].unique())]

    if month_display:
        default_month = month_display[-1]
        month_options = ["All"] + month_display
        default_month_index = month_options.index(default_month)

        selected_month = col2.selectbox(
            "Month", month_options,
            index=default_month_index,
            key="month_selectbox"
        )
    else:
        selected_month = "All"

    if selected_month != "All":
        selected_period = pd.Period(pd.to_datetime(selected_month, format="%b-%Y"), freq="M")
        filtered_df = filtered_df[filtered_df["month_period"] == selected_period]

    if filtered_df.empty:
        st.info("🚫 No MU/SL data available for the selected filters.")
        return

    mu_cols = [
        'Spondilitis', 'Spinal_Disc', 'Vision_Color_Blindness',
        'Neuro_Paralysis_Medical', 'Ortho', 'Diff_MU_Reasons', 'Total_Drivers_MU_Reasons'
    ]
    sl_cols = [
        'Flu_Fever', 'BP', 'Orthopedic', 'Heart', 'Weakness', 'Eye',
        'Accident_Injuries', 'Neuro_Paralysis_Sick_Leave', 'Piles', 'Diabetes',
        'Thyroid', 'Gas', 'Dental', 'Ear', 'Skin_Allergy', 'General_Surgery',
        'Obesity', 'Cancer', 'Total_Drivers_SL_Reasons', 'Diff_SL_Reasons'
    ]

    missing_cols = [c for c in mu_cols + sl_cols if c not in filtered_df.columns]
    if missing_cols:
        st.error(f"❌ Missing expected columns: {missing_cols}")
        return

    mu_totals = filtered_df[mu_cols].sum()
    sl_totals = filtered_df[sl_cols].sum()

    mu_df = mu_totals.drop(['Diff_MU_Reasons', 'Total_Drivers_MU_Reasons'], errors="ignore").reset_index()
    mu_df.columns = ['Reason', 'Count']
    mu_df = mu_df[mu_df['Count'] > 0]

    sl_df = sl_totals.drop(['Diff_SL_Reasons', 'Total_Drivers_SL_Reasons'], errors="ignore").reset_index()
    sl_df.columns = ['Reason', 'Count']
    sl_df = sl_df[sl_df['Count'] > 0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total MU Drivers", int(mu_totals.get('Total_Drivers_MU_Reasons', 0)))
    c2.metric("MU Reasons Count", len(mu_df))
    c3.metric("Total SL Drivers", int(sl_totals.get('Total_Drivers_SL_Reasons', 0)))
    c4.metric("SL Reasons Count", len(sl_df))

    col_mu, col_sl = st.columns(2)
    with col_mu:
        if not mu_df.empty:
            fig_mu = px.bar(
                mu_df.sort_values('Count', ascending=False),
                x='Reason',
                y='Count',
                color_discrete_sequence=['#1172a5'],
                text='Count',
                title=f"Medical Unfit (MU) Reasons – {entity_name.title()}"
            )
            fig_mu.update_traces(texttemplate='%{text}', textposition='outside')
            fig_mu.update_layout(xaxis_title='Reason', yaxis_title='Count')
            st.plotly_chart(fig_mu, use_container_width=True)

    with col_sl:
        if not sl_df.empty:
            fig_sl = px.bar(
                sl_df.sort_values('Count', ascending=False),
                x='Reason',
                y='Count',
                color_discrete_sequence=['#1172a5'],
                text='Count',
                title=f"Sick Leave (SL) Reasons – {entity_name.title()}"
            )
            fig_sl.update_traces(texttemplate='%{text}', textposition='outside')
            fig_sl.update_layout(xaxis_title='Reason', yaxis_title='Count')
            st.plotly_chart(fig_sl, use_container_width=True)


# Add background watermark
st.markdown(
    """
    <style>
    .watermark {
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%) rotate(-30deg);
        font-size: 120px;
        color: rgba(200, 200, 200, 0.15);  /* light gray and transparent */
        z-index: 0;  /* ensures it's behind content */
        pointer-events: none;  /* allows clicking on content */
        user-select: none;
    }
    </style>
    <div class="watermark">AI TEAM</div>
    """,
    unsafe_allow_html=True
)

if __name__ == "__main__":
    depot_UI()
