import streamlit as st
import pandas as pd
import base64
import json
import mysql.connector
from datetime import date, timedelta
from mysql.connector import Error
import calendar
import html as pyhtml
import streamlit.components.v1 as components

# --------- Load config ----------
try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    st.error("Configuration file 'config.json' not found.")
    st.stop()

# --------- Benchmarks ----------
BENCHMARKS = {
    "Rural": {
      "% Weekly Off & National Off": 14,
      "% Special Off (Night Out/IC, Online)": 25,
      "% Others": 1.7,
      "% Leave & Absent": 2,
      "% Sick Leave": 2,
      "% Spot Absent": 1,
      "% Double Duty": 16,
      "% Off Cancellation": 2,
      "Drivers/Schedule": 2.18
    },
    "Urban": {
      "% Weekly Off & National Off": 14,
      "% Special Off (Night Out/IC, Online)": 27.4,
      "% Others": 1,
      "% Leave & Absent": 6,
      "% Sick Leave": 2,
      "% Spot Absent": 2,
      "% Double Duty": 8,
      "% Off Cancellation": 2,
      "Drivers/Schedule": 2.43
    }
}

# --------- DB connection helper ----------
def get_connection():
    try:
        return mysql.connector.connect(**config["db"])
    except Error as e:
        st.error(f"Error connecting to database: {e}")
        return None

# --------- Main class ----------
class prod_ratios_RM:
    def __init__(self, user_region):
        self.user_region = user_region
        self.display_table()

    def display_table(self):
        # --- prepare logo (base64) ---
        file_path = r"LOGO.png"
        try:
            with open(file_path, "rb") as img_file:
                b64_img = base64.b64encode(img_file.read()).decode()
        except FileNotFoundError:
            b64_img = ""  # no logo file

        # top page header (normal Streamlit display)
        st.markdown(f"""
            <div style="text-align: center; background-color: #19bc9c; border-radius: 12px; padding:10px;">
                {"<img src='data:image/png;base64," + b64_img + "' width='110' height='110' style='display:block; margin:0 auto;'>" if b64_img else ""}
                <h1 style="color: white; margin:6px 0 8px 0;">Telangana State Road Transport Corporation</h1>
            </div>
        """, unsafe_allow_html=True)

        st.markdown("<h1 style='text-align: center;'>🚍 Productivity Budget - All Depots Comparison</h1>", unsafe_allow_html=True)

        # --- Database connection & fetch ---
        conn = get_connection()
        if not conn:
            st.stop()

        try:
            query = """
                SELECT d.*, a.category
                FROM input_data d
                JOIN TS_ADMIN a ON d.depot_name = a.depot_name
                WHERE a.region = %s
            """
            df = pd.read_sql(query, conn, params=(self.user_region,))
            df['data_date'] = pd.to_datetime(df['data_date'], errors='coerce')
        except Exception as err:
            st.error(f"Error fetching data: {err}")
            conn.close()
            st.stop()

        if df.empty:
            st.warning("⚠ No data available for the selected region.")
            conn.close()
            st.stop()

        # --- Time Period Selection ---
        time_periods = ['Daily', 'Monthly', 'Quarterly', 'Yearly']
        selected_time_period = st.selectbox("Select Time Period:", time_periods)

        # initialize selectors (so they exist for subtitle logic)
        date_filter = None
        month_filter = None
        year_filter = None
        quarter_filter = None

        min_date = df["data_date"].min()
        max_date = df["data_date"].max()
        if pd.isna(min_date) or pd.isna(max_date):
            today = date.today()
            min_date = today - timedelta(days=30)
            max_date = today
        else:
            min_date = min_date.date() if hasattr(min_date, "date") else min_date
            max_date = max_date.date() if hasattr(max_date, "date") else max_date

        col_e, col_f = st.columns(2)
        filtered_df = pd.DataFrame()

        if selected_time_period == "Daily":
            with col_e:
                date_filter = st.date_input("Select Date", min_value=min_date, max_value=max_date, value=max_date)
            filtered_df = df[df['data_date'] == pd.to_datetime(date_filter)]

        elif selected_time_period == "Monthly":
            with col_e:
                year_filter = st.selectbox("Year:", sorted(df['data_date'].dt.year.dropna().unique(), reverse=True), key="monthly_year_all")
            with col_f:
                month_filter = st.selectbox(
                    "Month:",
                    options=list(range(1, 13)),
                    format_func=lambda x: ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][x-1],
                    key="monthly_month_all"
                )
            filtered_df = df[
                (df['data_date'].dt.year == year_filter) &
                (df['data_date'].dt.month == month_filter)
            ]

        elif selected_time_period == "Quarterly":
            with col_e:
                year_filter = st.selectbox("Year:", sorted(df['data_date'].dt.year.dropna().unique(), reverse=True), key="quarterly_year_all")
            with col_f:
                quarter_filter = st.selectbox("Quarter:", ["Q1 (Jan–Mar)","Q2 (Apr–Jun)","Q3 (Jul–Sep)","Q4 (Oct–Dec)"], key="quarter_all")
            quarter_map = {"Q1 (Jan–Mar)": (1,3), "Q2 (Apr–Jun)": (4,6), "Q3 (Jul–Sep)": (7,9), "Q4 (Oct–Dec)": (10,12)}
            start_month, end_month = quarter_map[quarter_filter]
            filtered_df = df[
                (df['data_date'].dt.year == year_filter) &
                (df['data_date'].dt.month >= start_month) &
                (df['data_date'].dt.month <= end_month)
            ]

        elif selected_time_period == "Yearly":
            with col_e:
                year_filter = st.selectbox("Year:", sorted(df['data_date'].dt.year.dropna().unique(), reverse=True), key="yearly_year_all")
            filtered_df = df[df['data_date'].dt.year == year_filter]

        if filtered_df.empty:
            st.warning("⚠ No data available for the selected filters.")
            conn.close()
            st.stop()

        # --- Build subtitle text based on selected period ---
        subtitle_text = selected_time_period
        try:
            if selected_time_period == "Daily" and date_filter:
                subtitle_text += f" – {date_filter.strftime('%d-%b-%Y')}"
            elif selected_time_period == "Monthly" and month_filter and year_filter:
                subtitle_text += f" – {calendar.month_name[month_filter]} {year_filter}"
            elif selected_time_period == "Quarterly" and quarter_filter and year_filter:
                # Make a friendly quarter label with range
                quarter_range = {
                    "Q1 (Jan–Mar)": "Jan–Mar",
                    "Q2 (Apr–Jun)": "Apr–Jun",
                    "Q3 (Jul–Sep)": "Jul–Sep",
                    "Q4 (Oct–Dec)": "Oct–Dec"
                }.get(quarter_filter, "")
                subtitle_text += f" –  {quarter_filter} {year_filter}"
            elif selected_time_period == "Yearly" and year_filter:
                subtitle_text += f" – {year_filter}"
        except Exception:
            pass

        # --- Build table rows safely ---
        metric_map = {
            "Planned Schedules": None,
            "Total Drivers": None,
            "Weekly Off & National Off (%)": "% Weekly Off & National Off",
            "Special Off (Night Out/IC, Online) (%)": "% Special Off (Night Out/IC, Online)",
            "Others (%)": "% Others",
            "Long Leave & Absent (%)": "% Leave & Absent",
            "Sick Leave (%)": "% Sick Leave",
            "Spot Absent (%)": "% Spot Absent",
            "Double Duty (%)": "% Double Duty",
            "Off Cancellation (%)": "% Off Cancellation",
            "Drivers/Schedule (Ratio)": "Drivers/Schedule"
        }

        depots = sorted(filtered_df["depot_name"].unique())
        html_rows = ""

        for metric, base_label in metric_map.items():
            # benchmark cell
            if base_label is None:
                benchmark_cell = "<td>---</td>"
            else:
                benchmarks = []
                for depot in depots:
                    try:
                        cat = filtered_df.loc[filtered_df["depot_name"] == depot, "category"].iloc[0].capitalize()
                        benchmark = BENCHMARKS.get(cat, {}).get(base_label, None)
                        if benchmark is not None:
                            benchmarks.append(benchmark)
                    except Exception:
                        pass
                benchmark_avg = round(sum(benchmarks)/len(benchmarks),1) if benchmarks else None
                benchmark_cell = f"<td class='yellow-bg'>{pyhtml.escape(str(benchmark_avg))}%</td>" if benchmark_avg is not None else "<td>---</td>"

            depot_cells = ""
            depot_values_for_avg = []
            for depot in depots:
                depot_df = filtered_df[filtered_df["depot_name"] == depot]
                if depot_df.empty:
                    depot_cells += "<td>---</td>"
                    continue

                try:
                    if metric == "Planned Schedules":
                        value = int(depot_df["Planned_Schedules"].sum())
                    elif metric == "Total Drivers":
                        value = int(depot_df["Total_Drivers"].sum())
                    elif metric == "Drivers/Schedule (Ratio)":
                        planned_schedules = depot_df["Planned_Schedules"].sum()
                        total_drivers = depot_df["Total_Drivers"].sum()
                        value = round(total_drivers / planned_schedules, 2) if planned_schedules else 0
                    else:
                        col_name = config.get("category_to_column", {}).get(base_label, None)
                        if col_name and col_name in depot_df.columns:
                            value = round(depot_df[col_name].mean(), 1)
                        else:
                            value = "---"
                except Exception:
                    value = "---"

                # record numeric values for avg
                try:
                    depot_values_for_avg.append(float(value))
                except Exception:
                    pass

                # color compare with benchmark if applicable
                if base_label and isinstance(value, (int, float)):
                    try:
                        cat = depot_df["category"].iloc[0].capitalize()
                        benchmark_val = BENCHMARKS.get(cat, {}).get(base_label, None)
                        if benchmark_val is not None:
                            delta = value - benchmark_val
                            color = "green" if delta <= 0 else "red"
                            depot_cells += f"<td style='color:{color}; font-weight:bold'>{pyhtml.escape(str(value))}</td>"
                        else:
                            depot_cells += f"<td>{pyhtml.escape(str(value))}</td>"
                    except Exception:
                        depot_cells += f"<td>{pyhtml.escape(str(value))}</td>"
                else:
                    depot_cells += f"<td>{pyhtml.escape(str(value))}</td>"

            region_avg = round(sum(depot_values_for_avg)/len(depot_values_for_avg), 1) if depot_values_for_avg else "---"
            region_avg_cell = f"<td style='font-weight:bold; background-color:#d3f8d3'>{pyhtml.escape(str(region_avg))}</td>"

            html_rows += f"<tr><td style='text-align:left'><strong>{pyhtml.escape(metric)}</strong></td>{benchmark_cell}{depot_cells}{region_avg_cell}</tr>"

        # --- safe headers ---
        safe_depots_headers = " ".join([f"<th>{pyhtml.escape(d)}</th>" for d in depots])

        # dynamic filename
        sel_date_str = ""
        if selected_time_period == "Daily" and date_filter:
            sel_date_str = date_filter.isoformat()
        elif selected_time_period == "Monthly" and month_filter and year_filter:
            sel_date_str = f"{year_filter}-{month_filter:02d}"
        elif selected_time_period == "Quarterly" and year_filter and quarter_filter:
            sel_date_str = f"{year_filter}-{quarter_filter.replace(' ', '_')}"
        elif selected_time_period == "Yearly" and year_filter:
            sel_date_str = str(year_filter)
        else:
            sel_date_str = date.today().isoformat()

        filename = f"{self.user_region}_{selected_time_period}_{sel_date_str}.png".replace(" ", "_")

        # estimate iframe height to fit the table
        num_rows = len(metric_map) + 6
        iframe_height = min(1800, 200 + num_rows * 50)

        # --- build the HTML (captured inside iframe) ---
        capture_html = f"""
        <!doctype html>
        <html>
        <head>
        <meta charset="utf-8"/>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 12px; }}
          .logo {{ display:block; margin: 0 auto 8px auto; }}
          .capture-heading {{ text-align:center; margin:6px 0 14px 0; }}
          .custom-table {{margin:auto; border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; border: 2px solid black;}}
          .custom-table th, .custom-table td {{border: 1px solid black; text-align: center; padding: 8px;}}
          .custom-table th {{background-color: #19bc9c; font-weight: bold; color:white;}}
          .yellow-bg {{background-color: yellow; font-weight: bold;}}
          #download-btn {{ margin-top: 12px; padding: 8px 14px; font-size: 14px; border-radius: 6px; cursor: pointer; background-color:#19bc9c; color:white; border:none; }}
        </style>
        </head>
        <body>
            <div id="capture-area" style="text-align:center;">
                <div class="capture-heading">
                    <h2 style="margin:0;">{pyhtml.escape(self.user_region)} REGION 8 KPI RATIOS</h2>
                    <div style="margin-top:4px; font-size:14px; color:#333;">{pyhtml.escape(subtitle_text)}</div>
                </div>

                <div style="overflow:auto;">
                <table class="custom-table" id="the-table">
                    <thead>
                        <tr>
                            <th>Metric</th>
                            <th>Benchmark</th>
                            {safe_depots_headers}
                            <th>Region Avg</th>
                        </tr>
                    </thead>
                    <tbody>
                        {html_rows}
                    </tbody>
                </table>
                </div>
            </div>

            <div style="text-align:center; margin-top:12px;">
              <button id="download-btn">📥 Download KPI Table as PNG</button>
            </div>

            <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>

            <script>
            window.addEventListener('load', function() {{
                const btn = document.getElementById("download-btn");
                btn.addEventListener("click", function() {{
                    const captureArea = document.getElementById("capture-area");
                    setTimeout(() => {{
                        if (typeof html2canvas === 'undefined') {{
                            alert("html2canvas not loaded. If you're offline or the CDN is blocked, place a local html2canvas.min.js and adjust the <script> source.");
                            return;
                        }}
                        html2canvas(captureArea, {{ scale: 2, useCORS: true }}).then(canvas => {{
                            const link = document.createElement("a");
                            link.download = "{pyhtml.escape(filename)}";
                            link.href = canvas.toDataURL('image/png');
                            link.click();
                        }}).catch(err => {{
                            console.error("capture error:", err);
                            alert("Failed to capture table. Check console for details.");
                        }});
                    }}, 150);
                }});
            }});
            </script>
        </body>
        </html>
        """

        # Render the HTML inside an iframe where JS can run
        components.html(capture_html, height=iframe_height, scrolling=True)

        st.info("Note: Green values indicate meeting benchmark or better; red values exceed benchmark.", icon="ℹ")
        conn.close()

# --------- Run ----------
if __name__ == "__main__":
    if 'user_region' in st.session_state:
        prod_ratios_RM(st.session_state['user_region'])
    else:
        st.warning("Please select a region first!")
