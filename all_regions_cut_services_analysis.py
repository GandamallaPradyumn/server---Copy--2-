"""
Script to extract and format Predicted vs Actual CUT services for ALL REGIONS across TGSRTC.
Exports a multi-sheet Excel file where each Sheet is a Region (Sheet 1: 1st Region, Sheet 2: 2nd Region, etc.).

Format per Region Sheet:
       DATE  |            DEPOT 1            |            DEPOT 2            | ...
             |    PREDIC    |     ACTUAL     |    PREDIC    |     ACTUAL     | ...
  2026-09-01 | 2 (RPL1,..)  | 2 (RPL1,..)    | 4 (MS01,..)  | 2 Cut / 2 Ran  | ...
"""

import os
import sys
import json
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Paths & Defaults ───────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.join(BASE_DIR, "dynamic_scheduling_master") if os.path.exists(os.path.join(BASE_DIR, "dynamic_scheduling_master")) else BASE_DIR

DEFAULT_SCHEDULE_DIR = os.path.join(PROJECT_ROOT, "output", "dynamic_schedule")
DEFAULT_GOLD_PATH = os.path.join(PROJECT_ROOT, "data", "processed", "ops_daily_service_gold.parquet")
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_OUTPUT_EXCEL = os.path.join(BASE_DIR, "all_regions_cut_services_analysis.xlsx")

# Legacy aliases for backwards compatibility
SCHEDULE_DIR = DEFAULT_SCHEDULE_DIR
GOLD_PATH = DEFAULT_GOLD_PATH
CONFIG_PATH = DEFAULT_CONFIG_PATH
OUTPUT_EXCEL = DEFAULT_OUTPUT_EXCEL

# ── Fallback Region-Depot Mapping ──────────────────────────────────────────────
FALLBACK_REGION_DEPOTS = {
    'ADILABAD': ['ADILABAD', 'ASIFABAD', 'BHAINSA', 'MANCHERIAL', 'NIRMAL', 'UTNOOR'],
    'HYDERABAD': ['BANDLAGUDA', 'BARKATPURA', 'DILSHUKNAGAR', 'FALAKNUMA', 'FAROOQNAGAR', 'HYDERABAD-I', 'HYDERABAD-II', 'IBRAHIMPATNAM', 'KACHEGUDA', 'MAHESWARAM', 'MEHDIPATNAM', 'MIDHANI', 'MUSHIRABAD', 'RAJENDRANAGAR'],
    'KARIMNAGAR': ['GODAVARIKHANI', 'HUSNABAD', 'HUZURABAD', 'JAGITYAL', 'KARIMNAGAR-I', 'KARIMNAGAR-II', 'KORUTLA', 'MANTHANI', 'METPALLY', 'SIRCILLA', 'VEMULAWADA'],
    'KHAMMAM': ['BADRACHALAM', 'KHAMMAM', 'KOTHAGUDEM', 'MADHIRA', 'MANUGURU', 'SATTUPALLY', 'YELLANDU'],
    'MAHABOOBNAGAR': ['ACHAMPET', 'GADWAL', 'KALVAKURTHY', 'KOLLAPUR', 'KOSGI', 'MAHABOOBNAGAR', 'NAGARKURNOOL', 'NARAYANPET', 'SHADNAGAR', 'WANAPARTHI'],
    'MEDAK': ['DUBBAKA', 'GWL-PRGPR', 'MEDAK', 'NARSAPUR', 'NARAYANKHED', 'SANGAREDDY', 'SIDDIPET', 'ZAHIRABAD'],
    'NALGONDA': ['DEVARAKONDA', 'KODAD', 'MIRYALAGUDA', 'NALGONDA', 'NARKATPALLY', 'SURYAPET', 'YADAGIRIGUTTA'],
    'NIZAMABAD': ['ARMOOR', 'BANSWADA', 'BODHAN', 'KAMAREDDY', 'NIZAMABAD-I', 'NIZAMABAD-II'],
    'RANGAREDDY': ['BHEL', 'HAYATHNAGAR-I', 'HAYATHNAGAR-II', 'HCU', 'KUKATPALLY', 'MIYAPUR-I', 'MIYAPUR-II', 'PARGI'],
    'SECUNDERABAD': ['CHENGICHERLA', 'CONTONMENT', 'HAKIMPET', 'JEEDIMETLA', 'KUSHAIGUDA', 'MEDCHAL', 'PICKET', 'RANIGUNJ-I', 'RANIGUNJ-II', 'TANDUR', 'UPPAL', 'VIKARABAD'],
    'WARANGAL': ['BHUPALAPALLAY', 'HANAMKONDA', 'JANGAON', 'MAHABOOBABAD', 'NARSAMPET', 'PARKAL', 'THORROR', 'WARANGAL-I', 'WARANGAL-II']
}

def get_region_depot_mapping(config_path=DEFAULT_CONFIG_PATH):
    """Fetch region-to-depots mapping from MySQL TS_ADMIN, or fallback."""
    if os.path.exists(config_path):
        try:
            import pymysql
            with open(config_path, "r") as f:
                cfg = json.load(f).get("db", {})
            conn = pymysql.connect(
                host=cfg.get("host", "localhost"),
                user=cfg.get("user", "root"),
                password=cfg.get("password", ""),
                database=cfg.get("database", "tgsrtc_new"),
                connect_timeout=3
            )
            cur = conn.cursor()
            cur.execute("SELECT region, depot_name FROM TS_ADMIN ORDER BY region, depot_name")
            rows = cur.fetchall()
            conn.close()

            reg_map = defaultdict(list)
            for r, d in rows:
                reg_name = r.strip().upper()
                dep_name = d.strip().upper()
                if dep_name not in reg_map[reg_name]:
                    reg_map[reg_name].append(dep_name)
            if reg_map:
                return dict(sorted(reg_map.items()))
        except Exception:
            pass
    return FALLBACK_REGION_DEPOTS

def generate_matrix_cut_report(
    days=30,
    schedule_dir=DEFAULT_SCHEDULE_DIR,
    gold_path=DEFAULT_GOLD_PATH,
    output_excel=DEFAULT_OUTPUT_EXCEL,
    config_path=DEFAULT_CONFIG_PATH
):
    region_depots = get_region_depot_mapping(config_path)
    total_depots = sum(len(d) for d in region_depots.values())
    print(f"[*] Starting Analysis for {len(region_depots)} Regions and {total_depots} Depots...")

    if not os.path.exists(schedule_dir):
        raise FileNotFoundError(f"Schedule directory not found at: {schedule_dir}")

    if not os.path.exists(gold_path):
        raise FileNotFoundError(f"Gold parquet not found at: {gold_path}")

    # 1. Load Gold Actuals
    print("[+] Loading actual operational data from gold parquet...")
    gold = pd.read_parquet(gold_path)
    gold.columns = [c.strip().lower() for c in gold.columns]
    gold['date'] = pd.to_datetime(gold['date']).dt.strftime('%Y-%m-%d')
    gold['service_number'] = gold['service_number'].astype(str).str.strip()
    gold['depot'] = gold['depot'].astype(str).str.upper().str.strip()
    gold['actual_kms'] = pd.to_numeric(gold['actual_kms'], errors='coerce').fillna(0)

    # 2. Determine Date Range (Last 1 Month from Present Date)
    today = datetime.now().date()
    cutoff_from_today = (today - timedelta(days=days)).strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    all_schedule_dates = sorted([
        d for d in os.listdir(schedule_dir) 
        if os.path.isdir(os.path.join(schedule_dir, d)) and len(d) == 10 and d.startswith("20")
    ])

    if not all_schedule_dates:
        print("[-] No schedule directories found.")
        return

    # Filter dates within last 30 days up to today
    selected_dates = [d for d in all_schedule_dates if d >= cutoff_from_today and d <= today_str]

    # Fallback to latest available 30 days if system time is ahead of data
    if len(selected_dates) < 5:
        max_date = pd.to_datetime(all_schedule_dates[-1])
        cutoff_max = (max_date - timedelta(days=days)).strftime('%Y-%m-%d')
        selected_dates = [d for d in all_schedule_dates if d >= cutoff_max]
        print(f"[*] Aligned window to latest available 30 days: {selected_dates[0]} to {selected_dates[-1]}")
    else:
        print(f"[*] Window: Last {days} days from present ({selected_dates[0]} to {selected_dates[-1]})")

    # 3. Pre-extract daily schedule and actual data
    print(f"\n[+] Extracting predictions across {len(selected_dates)} dates...")
    
    # Store: data_store[date][depot] = { 'predic': '...', 'actual': '...' }
    data_store = defaultdict(lambda: defaultdict(lambda: {'predic': '-', 'actual': '-'}))

    for date_str in selected_dates:
        date_folder = os.path.join(schedule_dir, date_str)
        consolidated_file = os.path.join(date_folder, f"epk_consolidated_schedule_{date_str}.xlsx")

        sched_df = pd.DataFrame()
        if os.path.exists(consolidated_file):
            try:
                sched_df = pd.read_excel(consolidated_file)
                sched_df.columns = [c.strip().lower() for c in sched_df.columns]
                sched_df['depot'] = sched_df['depot'].astype(str).str.upper().str.strip()
                sched_df['service_number'] = sched_df['service_number'].astype(str).str.strip()
                sched_df['action'] = sched_df['action'].astype(str).str.upper().str.strip()
            except Exception:
                sched_df = pd.DataFrame()

        date_gold = gold[gold['date'] == date_str]

        for region_name, depots in region_depots.items():
            for depot in depots:
                if not sched_df.empty and 'depot' in sched_df.columns:
                    depot_sched = sched_df[sched_df['depot'] == depot]
                else:
                    depot_file = os.path.join(date_folder, f"epk_schedule_{depot}_{date_str}.xlsx")
                    if os.path.exists(depot_file):
                        try:
                            depot_sched = pd.read_excel(depot_file)
                            depot_sched.columns = [c.strip().lower() for c in depot_sched.columns]
                            depot_sched['service_number'] = depot_sched['service_number'].astype(str).str.strip()
                            depot_sched['action'] = depot_sched['action'].astype(str).str.upper().str.strip()
                        except Exception:
                            depot_sched = pd.DataFrame()
                    else:
                        depot_sched = pd.DataFrame()

                # Predicted CUT services & all scheduled services
                if not depot_sched.empty and 'action' in depot_sched.columns:
                    cut_rows = depot_sched[depot_sched['action'] == 'CUT']
                    pred_cut_services = [s for s in cut_rows['service_number'].astype(str).str.strip().tolist() if s]
                    all_sched_svcs = set(depot_sched['service_number'].astype(str).str.strip().tolist())
                else:
                    pred_cut_services = []
                    all_sched_svcs = set()

                pred_cut_count = len(pred_cut_services)
                if pred_cut_count > 0:
                    predic_cell = f"{pred_cut_count} ({', '.join(pred_cut_services)})"
                else:
                    predic_cell = "0"

                # Actual operations
                act_depot = date_gold[date_gold['depot'] == depot]
                if len(act_depot) > 0:
                    operated_svcs = set(act_depot[act_depot['actual_kms'] > 0]['service_number'].astype(str).str.strip())

                    # Depot actual cuts: scheduled services that did NOT operate
                    if all_sched_svcs:
                        actual_cut_svcs = sorted(list(all_sched_svcs - operated_svcs))
                    else:
                        actual_cut_svcs = []

                    actual_cut_count = len(actual_cut_svcs)
                    matched_cuts = sorted([s for s in pred_cut_services if s in actual_cut_svcs])
                    extra_cuts = sorted([s for s in actual_cut_svcs if s not in pred_cut_services])
                    ran_ai_cuts = sorted([s for s in pred_cut_services if s in operated_svcs])

                    if actual_cut_count == 0:
                        if pred_cut_count == 0:
                            actual_cell = "0"
                        else:
                            actual_cell = f"0 Cut [Ran AI: {', '.join(ran_ai_cuts)}]"
                    else:
                        if pred_cut_count == 0:
                            actual_cell = f"{actual_cut_count} Cut ({', '.join(actual_cut_svcs)})"
                        else:
                            parts = []
                            if matched_cuts:
                                parts.append(f"{len(matched_cuts)} Matched: {', '.join(matched_cuts)}")
                            else:
                                parts.append("0 Matched")

                            if extra_cuts:
                                parts.append(f"{len(extra_cuts)} Extra: {', '.join(extra_cuts)}")

                            breakdown_str = " | ".join(parts)
                            actual_cell = f"{actual_cut_count} Cut [{breakdown_str}]"
                            if ran_ai_cuts:
                                actual_cell += f" | Ran AI: {', '.join(ran_ai_cuts)}"
                else:
                    actual_cell = "Pending" if (pred_cut_count > 0 or all_sched_svcs) else "0"

                data_store[date_str][depot] = {
                    'predic': predic_cell,
                    'actual': actual_cell
                }

    # 4. Generate Multi-Sheet Excel Workbook with Matrix Format
    print(f"\n[+] Building matrix layout in Excel: {output_excel}")
    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    font_header_top = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    font_header_sub = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Segoe UI", size=9)
    font_date = Font(name="Segoe UI", size=10, bold=True, color="1E293B")

    fill_top = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")       # Dark Navy
    fill_sub_pred = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")  # Blue
    fill_sub_act = PatternFill(start_color="0D9488", end_color="0D9488", fill_type="solid")   # Teal
    fill_date_header = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid") # Slate Dark
    
    fill_row_even = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_row_odd = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    border_thin = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    sheet_number = 1
    for region_name, depots in region_depots.items():
        ws = wb.create_sheet(title=f"{region_name}"[:31])
        ws.views.sheetView[0].showGridLines = True

        # Header Row 1 & 2: DATE Column
        ws.merge_cells("A1:A2")
        cell_date = ws["A1"]
        cell_date.value = "DATE"
        cell_date.font = font_header_top
        cell_date.fill = fill_date_header
        cell_date.alignment = align_center
        cell_date.border = border_thin
        ws["A2"].border = border_thin

        # Header Row 1 & 2 for each Depot:
        # DEPOT NAME (merged over 2 cols) -> Subheaders: PREDIC | ACTUAL
        col_idx = 2
        for depot_idx, depot in enumerate(depots, start=1):
            c1 = col_idx
            c2 = col_idx + 1

            # Row 1: Merged Depot Header (e.g., 1. GODAVARIKHANI)
            ws.merge_cells(start_row=1, start_column=c1, end_row=1, end_column=c2)
            top_cell = ws.cell(row=1, column=c1, value=f"{depot_idx}. {depot}")
            top_cell.font = font_header_top
            top_cell.fill = fill_top
            top_cell.alignment = align_center
            top_cell.border = border_thin
            ws.cell(row=1, column=c2).border = border_thin

            # Row 2: Sub-headers PREDIC | ACTUAL
            pred_cell = ws.cell(row=2, column=c1, value="PREDIC")
            pred_cell.font = font_header_sub
            pred_cell.fill = fill_sub_pred
            pred_cell.alignment = align_center
            pred_cell.border = border_thin

            act_cell = ws.cell(row=2, column=c2, value="ACTUAL")
            act_cell.font = font_header_sub
            act_cell.fill = fill_sub_act
            act_cell.alignment = align_center
            act_cell.border = border_thin

            col_idx += 2

        # Populate Date Rows
        row_num = 3
        for date_str in selected_dates:
            row_fill = fill_row_even if (row_num % 2 == 0) else fill_row_odd

            # Date cell
            d_cell = ws.cell(row=row_num, column=1, value=date_str)
            d_cell.font = font_date
            d_cell.fill = row_fill
            d_cell.alignment = align_center
            d_cell.border = border_thin

            # Depot cells
            col_idx = 2
            for depot in depots:
                dep_data = data_store[date_str][depot]

                # PREDIC cell
                p_cell = ws.cell(row=row_num, column=col_idx, value=dep_data['predic'])
                p_cell.font = font_data
                p_cell.fill = row_fill
                p_cell.alignment = align_center if dep_data['predic'] == "0" else align_left
                p_cell.border = border_thin

                # ACTUAL cell
                a_cell = ws.cell(row=row_num, column=col_idx + 1, value=dep_data['actual'])
                a_cell.font = font_data
                a_cell.fill = row_fill
                a_cell.alignment = align_center if dep_data['actual'] == "0" else align_left
                a_cell.border = border_thin

                col_idx += 2

            ws.row_dimensions[row_num].height = 28
            row_num += 1

        # Formatting Sheet Dimensions
        ws.row_dimensions[1].height = 28
        ws.row_dimensions[2].height = 22
        ws.column_dimensions['A'].width = 14

        for col in range(2, ws.max_column + 1):
            col_letter = get_column_letter(col)
            # PREDIC (width 20) and ACTUAL (width 38 for comprehensive breakdown)
            if col % 2 == 0:
                ws.column_dimensions[col_letter].width = 20
            else:
                ws.column_dimensions[col_letter].width = 38

        # Freeze panes so DATE and Headers remain visible on scroll
        ws.freeze_panes = "B3"

        print(f"    - Sheet {sheet_number}: {region_name} ({len(depots)} depots, {len(selected_dates)} dates)")
        sheet_number += 1

    wb.save(output_excel)
    print(f"\n[SUCCESS] Matrix formatted Excel saved successfully to:\n{output_excel}")
    return output_excel

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate TGSRTC All-Regions Cut Services Analysis Report.")
    parser.add_argument("--days", type=int, default=30, help="Number of days to analyze (default: 30)")
    parser.add_argument("--schedule-dir", type=str, default=DEFAULT_SCHEDULE_DIR, help="Path to dynamic schedule output directory")
    parser.add_argument("--gold-path", type=str, default=DEFAULT_GOLD_PATH, help="Path to ops_daily_service_gold.parquet")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT_EXCEL, help="Output Excel file path")
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG_PATH, help="Path to config.json (optional)")

    args = parser.parse_args()

    generate_matrix_cut_report(
        days=args.days,
        schedule_dir=args.schedule_dir,
        gold_path=args.gold_path,
        output_excel=args.output,
        config_path=args.config
    )
