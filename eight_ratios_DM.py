import streamlit as st
import pandas as pd
import altair as alt
import mysql.connector
from mysql.connector import Error
import pandas as pd
import pymysql
from datetime import timedelta, date
import calendar
import json
from mysql.connector import Error
with open("config.json") as f:
    config = json.load(f)

DB_CONFIG = config.get("db", {})
# Define the table name and columns from your MySQL database
MYSQL_TABLE_NAME = 'input_data'
MYSQL_COLUMNS = config.get("db_columns", [])

# Example usage in a DataFrame
DB_CONFIG = config.get("db", {})
MYSQL_TABLE_NAME = 'input_data'
MYSQL_COLUMNS = config.get("db_columns", [])


# Example usage in insert SQL
columns_str = ", ".join(MYSQL_COLUMNS)
placeholders = ", ".join(["%s"] * len(MYSQL_COLUMNS))
sql = f"INSERT INTO action_plan ({columns_str}) VALUES ({placeholders})"


# --- Database Connection Function (NO CACHING) ---
def get_connection():
    """Establishes and returns a MySQL database connection using pymysql."""
    try:
        conn = pymysql.connect(
            host=DB_CONFIG.get("host", "localhost"),
            user=DB_CONFIG.get("user", "root"),
            password=DB_CONFIG.get("password", ""),
            database=DB_CONFIG.get("database", "")
        )
        return conn
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

# --- Function to fetch user depot from 'users' table (UPDATED) ---
def get_user_depot(_conn, userid):
    if not userid:
        return ""
    try:
        cursor = _conn.cursor()
        # Changed column name from depot_name to depot as per 'users' schema
        cursor.execute("SELECT depot FROM users WHERE userid = %s", (userid,))
        result = cursor.fetchone()
        return result[0] if result else ""
    except Error as e:
        st.error(f"Error fetching depot for user {userid} from 'users' table: {e}")
        return ""
    finally:
        cursor.close()

# --- Function to fetch depot settings from TS_ADMIN (This remains correct for categories) ---
def get_depot_settings(_conn):
    """
    Fetches depot configuration settings (depot_name and category) from the TS_ADMIN table.
    The connection object is passed.
    """
    if _conn is None:
        st.error("Database connection not available for fetching depot settings. Cannot proceed.")
        return {}
    cursor = None
    try:
        cursor = _conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT depot_name, category FROM TS_ADMIN")
        rows = cursor.fetchall()
        return {row["depot_name"]: row["category"] for row in rows if "depot_name" in row and "category" in row}
    except Error as e:
        st.error(f"Error fetching depot settings from TS_ADMIN: {e}")
        return {}
    finally:
        if cursor:
            cursor.close()

# --- Data Loading and Preprocessing Function (NO CACHING) ---
def load_data(depot_settings, _conn):
    """
    Loads data directly from MySQL database and enriches it with 'Category' from TS_ADMIN settings.
    The connection object is passed.
    """
    df = pd.DataFrame()
    if _conn is None:
        st.error("Database connection not available for loading main data. Cannot proceed.")
        st.stop()

    try:
        query = f"SELECT {', '.join(MYSQL_COLUMNS)} FROM {MYSQL_TABLE_NAME}"
        df = pd.read_sql(query, _conn)
        df["data_date"] = pd.to_datetime(df["data_date"], errors="coerce")

        if 'data_date' in df.columns:
            df.rename(columns={'data_date': 'Date'}, inplace=True)
        if 'depot_name' in df.columns:
            df.rename(columns={'depot_name': 'Depot'}, inplace=True)
        else:
            st.error("Error: 'depot_name' column not found in database results. Cannot proceed without depot information.")
            st.stop()

    except Exception as e:
        st.error(f"Error fetching or processing data from MySQL: {e}")
        st.error("Dashboard cannot load data. Please check your database table schema and data.")
        st.stop()

    if df.empty:
        return pd.DataFrame()

    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df.dropna(subset=['Date'], inplace=True)
    else:
        st.error("Error: 'Date' column ('data_date' in DB) not found after data loading. Please check your data source.")
        return pd.DataFrame()

    df.columns = df.columns.str.strip()

    if 'Category' not in df.columns:
        df['Category'] = df['Depot'].map(depot_settings).fillna('Unknown')

    if df.empty:
        st.stop()

    return df


def eight_ratios_DM():
    # --- Main application execution starts here ---

    # 1. Establish the MySQL connection for this run
    mysql_conn = get_connection()
    # Check if connection was successful
    if mysql_conn is None:
        st.stop()

    # --- MODIFIED LOGIC HERE to always update session_state.depot based on current userid ---
    if "userid" in st.session_state and st.session_state.userid != "admin":
        st.session_state.depot = get_user_depot(mysql_conn, st.session_state.userid)
    elif st.session_state.userid == "admin":
        # Admin doesn't have a fixed depot, they select it from the dropdown
        # Ensure it's empty so the selectbox works correctly if no default is set
        if "depot" not in st.session_state:  # Initialize if not present
            st.session_state.depot = ""
    else:
        # No userid or other case, default to empty depot
        st.session_state.depot = ""

    # 2. Fetch depot settings using the connection (still from TS_ADMIN for categories)
    depot_settings = get_depot_settings(mysql_conn)

    # 3. Load the main data using the connection and depot settings
    df = load_data(depot_settings, mysql_conn)

    # === NEW: Create Drivers_per_Schedule column from Total_Drivers & Planned_Schedules ===
    if not df.empty and {'Planned_Schedules', 'Total_Drivers'}.issubset(df.columns):
        # Avoid division by zero
        schedules_non_zero = df['Planned_Schedules'].replace(0, pd.NA)
        df['Drivers_per_Schedule'] = df['Total_Drivers'] / schedules_non_zero
    else:
        # If columns missing, we won't plot this ratio
        df['Drivers_per_Schedule'] = pd.NA

    # --- CRITICAL CHECK: If df is empty after loading, stop here ---
    if df.empty:
        st.error("No data loaded from the database. Please ensure your input_data table has data and your DB_CONFIG is correct.")
        if mysql_conn:
            mysql_conn.close()
        st.stop()

    # Define benchmarks for Urban and Rural categories
    # === UPDATED: added Drivers_per_Schedule benchmark (from Ratios_DM) ===
    benchmarks = {
        'Urban': {
            'Pct_Weekly_Off_National_Off': 14,
            'Pct_Special_Off_Night_Out_IC_Online': 27.4,
            'Pct_Others': 1,
            'Pct_Leave_Absent': 6,
            'Pct_Sick_Leave': 2,
            'Pct_Spot_Absent': 2,
            'Pct_Double_Duty': 8,
            'Pct_Off_Cancellation': 2,
            'Drivers_per_Schedule': 2.18  # Urban benchmark
        },
        'Rural': {
            'Pct_Weekly_Off_National_Off': 14,
            'Pct_Special_Off_Night_Out_IC_Online': 25,
            'Pct_Others': 1.7,
            'Pct_Leave_Absent': 2,
            'Pct_Sick_Leave': 2,
            'Pct_Spot_Absent': 1,
            'Pct_Double_Duty': 16,
            'Pct_Off_Cancellation': 2,
            'Drivers_per_Schedule': 2.43  # Rural benchmark
        }
    }

    # --- Manual Mapping for Ratio Headings ---
    # === UPDATED: added heading for Drivers_per_Schedule ===
    RATIO_HEADINGS = {
        'Pct_Weekly_Off_National_Off': 'Weekly Off + National Off %',
        'Pct_Others': 'Others + OD %',
        'Pct_Sick_Leave': 'Sick Leave %',
        'Pct_Spot_Absent': 'Spot Absent%',
        'Pct_Off_Cancellation': 'Off Cancellation %',
        'Pct_Special_Off_Night_Out_IC_Online': 'Special Off/Night Out/IC Online %',
        'Pct_Double_Duty': 'Double Duty %',
        'Pct_Leave_Absent': 'Leave Absent %',
        'Drivers_per_Schedule': 'Drivers / Schedule Ratio'  # NEW
    }

    # --- Dashboard Title ---
    st.markdown("<h1 style='text-align: center; color: white; font-size: 50px;background-color: #19bc9c; border-radius: 12px;{* padding:0px;margin:0px}'>Productivity Budget Ratios vs Actual 8 Ratios Dashboard</h1>", unsafe_allow_html=True)
    st.markdown("---")

    # --- Filter Options (Below Title, Side-by-Side) ---
    st.markdown("<h2 style='font-size: 1.8em;'>DEPOT</h2>", unsafe_allow_html=True)

    # Depot and Time Period Selectors
    col1, col2 = st.columns(2)
    with col1:
        selected_depot = None

        if st.session_state.userid == "admin":
            if not df.empty and 'Depot' in df.columns:
                all_depots_available = sorted(df['Depot'].unique().tolist())
                # Ensure the default selection aligns with session_state if previously set by admin
                if st.session_state.depot in all_depots_available:
                    default_index = all_depots_available.index(st.session_state.depot)
                else:
                    default_index = 0
                selected_depot = st.selectbox("Select Depot", all_depots_available, index=default_index)
                st.session_state.depot = selected_depot  # Update session state for admin's selection
            else:
                st.selectbox("Select Depot", ["No depots found in data"], disabled=True)
                st.session_state.depot = ""  # Ensure depot state is empty if no data
        else:
            selected_depot = st.session_state.get("depot", "")  # Get the depot set by the modified logic above
            st.markdown(f" <span style='font-size: 1.5em;'><b>{selected_depot}</b></span>", unsafe_allow_html=True)

    with col2:
        time_period = st.selectbox("Select Time Period", ["Daily", "Monthly", "Year"])

    # Determine the effective category for benchmarks based on the selected depot's category from TS_ADMIN
    effective_category_for_benchmarks = 'Urban'  # Default benchmark category
    depot_display_category = "N/A"  # For display beside depot name

    if selected_depot and selected_depot in depot_settings:
        depot_category_from_ts_admin = depot_settings[selected_depot]
        depot_display_category = depot_category_from_ts_admin
        if depot_category_from_ts_admin in benchmarks:
            effective_category_for_benchmarks = depot_category_from_ts_admin
    else:
        # Fallback to check category from df itself if selected_depot not in depot_settings
        if selected_depot:
            if not df.empty and 'Depot' in df.columns and 'Category' in df.columns:
                depot_category_from_df_series = df[df['Depot'] == selected_depot]['Category']
                if not depot_category_from_df_series.empty:
                    depot_category_from_df = depot_category_from_df_series.iloc[0]
                    depot_display_category = depot_category_from_df
                    if depot_category_from_df in benchmarks:
                        effective_category_for_benchmarks = depot_category_from_df
                else:
                    depot_display_category = 'Unknown'
            else:
                depot_display_category = 'Unknown'

    # --- Date Range Filters (Conditional based on time_period) ---
    start_date_filter = None
    end_date_filter = None

    if time_period == "Daily":
        st.markdown("<h3 style='font-size: 1.4em;'>Date Range (Daily)</h3>", unsafe_allow_html=True)
        if not df.empty and 'Date' in df.columns:
            max_date_available = df['Date'].max()
            default_daily_end_date = max_date_available.date()
            default_daily_start_date = (max_date_available - timedelta(days=29)).date()

            col_daily_from, col_daily_to = st.columns(2)
            with col_daily_from:
                daily_from_date = st.date_input(
                    "From Date",
                    value=default_daily_start_date,
                    min_value=df['Date'].min().date(),
                    max_value=default_daily_end_date,
                    key="daily_from_date"
                )
            with col_daily_to:
                daily_to_date = st.date_input(
                    "To Date",
                    value=default_daily_end_date,
                    min_value=daily_from_date,
                    max_value=default_daily_end_date,
                    key="daily_to_date"
                )

            start_date_filter = pd.to_datetime(daily_from_date)
            end_date_filter = pd.to_datetime(daily_to_date) + timedelta(days=1) - timedelta(microseconds=1)

            if start_date_filter > end_date_filter:
                st.warning("From Date cannot be after To Date. Please adjust your selection.")
                start_date_filter = None
                end_date_filter = None
        else:
            st.info("Date data not available for Daily filter. Please check your database data.")

    elif time_period == "Monthly":
        st.markdown("<h3 style='font-size: 1.4em;'>Month Range (Monthly)</h3>", unsafe_allow_html=True)
        if not df.empty and 'Date' in df.columns:
            min_year = df['Date'].min().year
            max_year = df['Date'].max().year
            all_years = sorted(list(set(range(min_year, max_year + 1)).union({date.today().year})))
            all_months = list(calendar.month_name)[1:]
            month_to_num = {month: i + 1 for i, month in enumerate(all_months)}

            current_year = date.today().year

            default_from_year_idx = all_years.index(min_year) if min_year in all_years else 0
            default_to_year_idx = all_years.index(current_year) if current_year in all_years else len(all_years) - 1

            col_from_group, col_to_group = st.columns(2)

            with col_from_group:
                st.markdown("<p style='font-size: 1.1em; font-weight: bold;'>From:</p>", unsafe_allow_html=True)
                col_from_month_inner, col_from_year_inner = st.columns(2)
                with col_from_month_inner:
                    from_month = st.selectbox("Month", all_months, index=0, key="from_month_monthly")
                with col_from_year_inner:
                    from_year = st.selectbox("Year", all_years, index=default_from_year_idx, key="from_year_monthly")

            with col_to_group:
                st.markdown("<p style='font-size: 1.1em; font-weight: bold;'>To:</p>", unsafe_allow_html=True)
                col_to_month_inner, col_to_year_inner = st.columns(2)
                with col_to_month_inner:
                    to_month = st.selectbox("Month", all_months, index=len(all_months) - 1, key="to_month_monthly")
                with col_to_year_inner:
                    to_year = st.selectbox("Year", all_years, index=default_to_year_idx, key="to_year_monthly")

            start_date_filter = pd.to_datetime(f"{from_year}-{month_to_num[from_month]}-01")
            end_date_filter = pd.to_datetime(f"{to_year}-{month_to_num[to_month]}-01") + pd.DateOffset(months=1) - pd.DateOffset(days=1)

            if start_date_filter > end_date_filter:
                st.warning("From Month/Year cannot be after To Month/Year. Please adjust your selection.")
                start_date_filter = None
                end_date_filter = None
        else:
            st.info("Date data not available for Monthly filter. Please check your database data.")

    elif time_period == "Year":
        st.markdown("<h3 style='font-size: 1.4em;'>Year Range (Year)</h3>", unsafe_allow_html=True)
        if not df.empty and 'Date' in df.columns:
            min_year = df['Date'].min().year
            max_year = df['Date'].max().year
            all_years = sorted(list(set(range(min_year, max_year + 1)).union({date.today().year})))

            col_from_Year_year, col_to_Year_year = st.columns(2)
            with col_from_Year_year:
                from_year_Year = st.selectbox(
                    "From Year",
                    all_years,
                    index=0,
                    key="from_year_Year"
                )
            with col_to_Year_year:
                to_year_Year = st.selectbox(
                    "To Year",
                    all_years,
                    index=len(all_years) - 1,
                    key="to_year_Year"
                )

            start_date_filter = pd.to_datetime(f"{from_year_Year}-01-01")

            current_date_this_year = pd.Timestamp.now()
            end_of_selected_to_year = pd.to_datetime(f"{to_year_Year}-12-31")

            if pd.Timestamp(to_year_Year, 1, 1).year == current_date_this_year.year:
                end_date_filter = current_date_this_year
            else:
                end_date_filter = end_of_selected_to_year

            if start_date_filter.year > end_date_filter.year:
                st.warning("From Year cannot be after To Year. Please adjust your selection.")
                start_date_filter = None
                end_date_filter = None
        else:
            st.info("Date data not available for Year filter. Please check your database data.")

    st.markdown("---")

    # Display selected filters prominently, including the depot's category
    st.markdown(f"### Data for: *{selected_depot if selected_depot else 'N/A'}* Depot ({depot_display_category})")
    st.markdown(f"*Time Period:* {time_period}")
    date_range_info = ""
    if not df.empty and start_date_filter is not None and end_date_filter is not None:
        if time_period == "Daily":
            if 'daily_from_date' in locals() and 'daily_to_date' in locals():
                date_range_info = f"*Date Range:* {daily_from_date.strftime('%Y-%m-%d')} to {daily_to_date.strftime('%Y-%m-%d')}"
        elif time_period == "Monthly":
            if 'from_month' in locals() and 'from_year' in locals() and 'to_month' in locals() and 'to_year' in locals():
                date_range_info = f"*Month Range:* {from_month} {from_year} to {to_month} {to_year}"
        elif time_period == "Year":
            if 'from_year_Year' in locals() and 'to_year_Year' in locals():
                date_range_info = f"*Year Range:* {from_year_Year} to {to_year_Year} (Year)"
    st.markdown(date_range_info)
    st.markdown("---")

    filtered_df = df.copy()

    if selected_depot and 'Depot' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['Depot'] == selected_depot]
    else:
        filtered_df = pd.DataFrame(columns=df.columns if not df.empty else [])

    if start_date_filter is not None and end_date_filter is not None and 'Date' in filtered_df.columns:
        filtered_df = filtered_df[(filtered_df['Date'] >= start_date_filter) & (filtered_df['Date'] <= end_date_filter)]
    else:
        # If filters are not set or invalid, clear filtered_df
        if not filtered_df.empty:  # Only clear if it actually contains data
            filtered_df = pd.DataFrame(columns=df.columns if not df.empty else [])

    if filtered_df.empty:
        st.warning("NO DATA FOUND FOR SELECTED FILTERS. Please adjust your selections or check your database.")
    else:
        # Loop over all ratios including Drivers_per_Schedule
        for selected_ratio in benchmarks[effective_category_for_benchmarks].keys():
            actual_column = selected_ratio
            current_benchmark = benchmarks[effective_category_for_benchmarks][selected_ratio]

            ratio_display_name = RATIO_HEADINGS.get(selected_ratio, selected_ratio.replace('Pct_', '').replace('_', ' '))

            st.markdown(f"<h3 style='font-size: 1.5em;'> <b>{ratio_display_name}</b></h3>", unsafe_allow_html=True)

            if actual_column not in filtered_df.columns:
                st.warning(f"Column '{actual_column}' not found in the filtered data for calculations. Skipping this ratio.")
                st.markdown("---")
                continue

            aggregated_df = filtered_df.copy()

            if time_period == "Daily":
                group_cols = ['Depot', 'Date']
                aggregated_df = aggregated_df.groupby(group_cols).agg(
                    **{actual_column: (actual_column, 'mean')}
                ).reset_index()
                aggregated_df = aggregated_df.sort_values(by='Date').reset_index(drop=True)

            elif time_period == "Monthly":
                group_cols = ['Depot', pd.Grouper(key='Date', freq='MS')]
                aggregated_df = aggregated_df.groupby(group_cols).agg(
                    **{actual_column: (actual_column, 'mean')}
                ).reset_index()
                aggregated_df = aggregated_df.sort_values(by='Date').reset_index(drop=True)

            elif time_period == "Year":
                group_cols = ['Depot', filtered_df['Date'].dt.year.rename('Year')]
                aggregated_df = filtered_df.groupby(group_cols).agg(
                    **{actual_column: (actual_column, 'mean')}
                ).reset_index()
                aggregated_df['Date'] = aggregated_df['Year'].apply(lambda y: pd.Timestamp(y, 1, 1))
                aggregated_df = aggregated_df.sort_values(by='Date').reset_index(drop=True)

            if aggregated_df.empty:
                st.info(f"No data available for {ratio_display_name} for the selected time period after aggregation.")
                st.markdown("---")
                continue

            col_kpi_actual, col_kpi_benchmark = st.columns(2)

            with col_kpi_actual:
                current_actual = aggregated_df[actual_column].mean()

                # === DIFFERENT DISPLAY FOR DRIVERS/SCHEDULE (not %) ===
                if selected_ratio == 'Drivers_per_Schedule':
                    st.metric(label=f"Average {ratio_display_name}", value=f"{current_actual:.2f}")
                else:
                    st.metric(label=f"Average {ratio_display_name}", value=f"{current_actual:.1f}%")

            with col_kpi_benchmark:
                current_benchmark = benchmarks[effective_category_for_benchmarks][selected_ratio]
                if selected_ratio == 'Drivers_per_Schedule':
                    st.metric(label=f"Benchmark {ratio_display_name}", value=f"{current_benchmark:.2f}")
                else:
                    st.metric(label=f"Benchmark {ratio_display_name}", value=f"{current_benchmark:.1f}%")

            st.markdown(f"<h4 style='font-size: 1.2em;'>{time_period} Trend: {ratio_display_name} vs. Benchmark</h4>", unsafe_allow_html=True)

            chart_df_actual = aggregated_df.copy()
            chart_df_actual['Type'] = f"{ratio_display_name}"

            chart_df_benchmark = aggregated_df.copy()
            chart_df_benchmark['Type'] = f"Benchmark {ratio_display_name}"

            # === VALUE & AXIS FORMAT HANDLING ===
            if selected_ratio == 'Drivers_per_Schedule':
                # Raw ratio values
                chart_df_actual['Value'] = chart_df_actual[actual_column]
                chart_df_benchmark['Value'] = current_benchmark
                y_axis_format = '.2f'
            else:
                # Percentages
                chart_df_actual['Value'] = chart_df_actual[actual_column] / 100
                chart_df_benchmark['Value'] = current_benchmark / 100
                y_axis_format = '.1%'

            combined_chart_df = pd.concat([chart_df_actual, chart_df_benchmark], ignore_index=True)

            x_axis_format = '%Y-%m-%d'
            label_angle = 0
            x_axis_title = 'Date'
            tick_count = 'day'
            tooltip_date_format = '%Y-%m-%d'

            if time_period == "Daily":
                x_axis_format = '%a %Y-%m-%d'
                label_angle = -90
                tooltip_date_format = '%A %Y-%m-%d'
                x_axis_title = 'Date'
                tick_count = 'day'
            elif time_period == "Monthly":
                x_axis_format = '%b %Y'
                label_angle = -45
                tooltip_date_format = '%B %Y'
                x_axis_title = 'Month'
                tick_count = 'month'
            elif time_period == "Year":
                x_axis_format = '%Y'
                label_angle = 0
                tooltip_date_format = '%Y'
                x_axis_title = 'Year'
                tick_count = 'year'

            combined_chart = alt.Chart(combined_chart_df).encode(
                x=alt.X(
                    'Date',
                    type='temporal',
                    title=x_axis_title,
                    axis=alt.Axis(format=x_axis_format, labelAngle=label_angle, tickCount=tick_count)
                ),
                y=alt.Y(
                    'Value',
                    title=f'{ratio_display_name}',
                    axis=alt.Axis(titleAngle=270, titlePadding=10, format=y_axis_format)
                ),
                color=alt.Color(
                    'Type',
                    scale=alt.Scale(
                        domain=[f"{ratio_display_name}", f"Benchmark {ratio_display_name}"],
                        range=['steelblue', 'red']
                    ),
                    legend=alt.Legend(
                        title=None,
                        orient="top",
                        direction="horizontal",
                        titleOrient="top",
                    )
                ),
                strokeDash=alt.StrokeDash(
                    'Type',
                    scale=alt.Scale(
                        domain=[f"{ratio_display_name}", f"Benchmark {ratio_display_name}"],
                        range=[[0, 0], [5, 5]]
                    )
                ),
                tooltip=[
                    alt.Tooltip('Date', format=tooltip_date_format),
                    alt.Tooltip('Value', title='Value', format=y_axis_format),
                    alt.Tooltip('Type', title='Metric')
                ]
            ).mark_line(point=True)

            st.altair_chart(combined_chart, use_container_width=True)
            st.markdown("---")

    if mysql_conn:
        mysql_conn.close()
    st.markdown("", unsafe_allow_html=True)
