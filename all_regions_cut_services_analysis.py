"""
Script to extract and format Predicted vs Actual CUT services for TGSRTC Regions (KRMR, ADILABAD, and ALL).
Outputs an Excel workbook per Region where:
- Sheet 1: Depot 1
- Sheet 2: Depot 2
- Sheet 3: Depot 3
...

Format per Depot Sheet:
  Row 1 (Banner):  DEPOT CUT SERVICES ANALYSIS (<DEPOT NAME>)
  Row 2 (Meta):    Region: <REGION> | Period: Last 30 Days (<START> to <END>) | Master: Service Master
  Row 3 (Columns): DATE | PREDICTED CUT | ACTUAL CUTS FROM THAT DEPOT | IN SERVICE MASTER CAN BE CANCELLED (YES / NO) | EXTRA SERVICES | 9000 SERIES SERVICES
  Row 4+ (Data):   Daily rows from the last 1 month window
  Bottom (Total):  TOTAL / SUMMARY row with aggregated statistics
"""

import os
import sys
import re
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
DEFAULT_SERVICE_MASTER_PATH = os.path.join(PROJECT_ROOT, "data", "master", "service_master.csv")
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ── Region Aliases & Depot Mapping ─────────────────────────────────────────────
REGION_ALIASES = {
    'KRMR': 'KARIMNAGAR',
    'KARIMNAGAR': 'KARIMNAGAR',
    'KARIMNAGAR REGION': 'KARIMNAGAR',
    'ADB': 'ADILABAD',
    'ADILABAD': 'ADILABAD',
    'ADHILABAD': 'ADILABAD',
    'ADILABAD REGION': 'ADILABAD',
    'ADHILABAD REGION': 'ADILABAD',
    'HYD': 'HYDERABAD',
    'HYDERABAD': 'HYDERABAD',
    'SC': 'SECUNDERABAD',
    'SECUNDERABAD': 'SECUNDERABAD',
    'RR': 'RANGAREDDY',
    'RANGAREDDY': 'RANGAREDDY',
    'WL': 'WARANGAL',
    'WARANGAL': 'WARANGAL',
    'KHM': 'KHAMMAM',
    'KHAMMAM': 'KHAMMAM',
    'NLG': 'NALGONDA',
    'NALGONDA': 'NALGONDA',
    'MBNR': 'MAHABOOBNAGAR',
    'MAHABOOBNAGAR': 'MAHABOOBNAGAR',
    'MDK': 'MEDAK',
    'MEDAK': 'MEDAK',
    'NZB': 'NIZAMABAD',
    'NIZAMABAD': 'NIZAMABAD'
}

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

def normalize_service_number(s):
    """Normalize service numbers: purely numeric codes strip leading zeros; alphanumerics match as-is."""
    s = str(s).strip().upper()
    return str(int(s)) if s.isdigit() else s

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

def load_service_master_cancellable(service_master_path=DEFAULT_SERVICE_MASTER_PATH):
    """
    Load service_master.csv and build lookup map: (depot, service_number) -> can_be_cancelled (1 or 0).
    """
    cancellable_map = {}
    if not os.path.exists(service_master_path):
        print(f"[!] Warning: service_master.csv not found at: {service_master_path}. Defaults to 0 (NO).")
        return cancellable_map

    try:
        sm_df = pd.read_csv(service_master_path)
        sm_df.columns = [c.strip().lower() for c in sm_df.columns]
        
        if 'depot' in sm_df.columns and 'service_number' in sm_df.columns and 'can_be_cancelled' in sm_df.columns:
            sm_df['depot'] = sm_df['depot'].astype(str).str.strip().str.upper()
            sm_df['service_number'] = sm_df['service_number'].apply(normalize_service_number)
            sm_df['can_be_cancelled'] = pd.to_numeric(sm_df['can_be_cancelled'], errors='coerce').fillna(0).astype(int)

            for _, row in sm_df.iterrows():
                key = (row['depot'], row['service_number'])
                cancellable_map[key] = int(row['can_be_cancelled'])
            print(f"[+] Loaded {len(cancellable_map)} services from Service Master ({sum(cancellable_map.values())} marked can_be_cancelled=1)")
    except Exception as e:
        print(f"[!] Error loading service_master.csv: {e}")

    return cancellable_map

def resolve_target_regions(region_arg, all_available_regions):
    """Resolves region argument (e.g. 'krmr', 'adhilabad', 'krmr,adhilabad', 'all') to canonical names."""
    if not region_arg:
        # Default requested: KRMR and ADILABAD
        return ['KARIMNAGAR', 'ADILABAD']

    if region_arg.strip().upper() == 'ALL':
        return list(all_available_regions.keys())

    selected = []
    tokens = [t.strip().upper() for t in region_arg.split(',') if t.strip()]
    for token in tokens:
        canonical = REGION_ALIASES.get(token, token)
        if canonical in all_available_regions:
            if canonical not in selected:
                selected.append(canonical)
        else:
            # Fuzzy match
            matched = False
            for r in all_available_regions:
                if token in r or r in token:
                    if r not in selected:
                        selected.append(r)
                    matched = True
                    break
            if not matched:
                print(f"[!] Warning: Region '{token}' not recognized in available regions.")
    
    return selected if selected else ['KARIMNAGAR', 'ADILABAD']

def generate_cut_services_analysis(
    regions=None,
    days=30,
    schedule_dir=DEFAULT_SCHEDULE_DIR,
    gold_path=DEFAULT_GOLD_PATH,
    service_master_path=DEFAULT_SERVICE_MASTER_PATH,
    config_path=DEFAULT_CONFIG_PATH,
    output_dir=BASE_DIR
):
    """
    Main function to analyze and generate multi-sheet Excel files per Region.
    Each sheet inside the workbook is a Depot:
    Sheet 1: Depot 1
    Sheet 2: Depot 2
    ...
    """
    region_depot_map = get_region_depot_mapping(config_path)
    target_regions = resolve_target_regions(regions, region_depot_map)
    print(f"[*] Target Regions to process: {', '.join(target_regions)}")

    if not os.path.exists(schedule_dir):
        raise FileNotFoundError(f"Schedule directory not found at: {schedule_dir}")
    if not os.path.exists(gold_path):
        raise FileNotFoundError(f"Gold parquet not found at: {gold_path}")

    # 1. Load Service Master Cancellable Map
    cancellable_map = load_service_master_cancellable(service_master_path)

    # 2. Determine Date Range (Last 1 Month / 30 Days of available data)
    all_schedule_dates = sorted([
        d for d in os.listdir(schedule_dir)
        if os.path.isdir(os.path.join(schedule_dir, d)) and len(d) == 10 and d.startswith("20")
    ])

    if not all_schedule_dates:
        print("[-] No schedule date directories found.")
        return []

    # Take the latest available 30 days (1 month) of schedule operations
    selected_dates = all_schedule_dates[-days:] if len(all_schedule_dates) >= days else all_schedule_dates
    print(f"[*] Window: Last {len(selected_dates)} days of data ({selected_dates[0]} to {selected_dates[-1]})")

    # 3. Load Gold Actuals (optimized: read only required 4 columns and filter to selected window)
    print("[+] Loading actual operational data from gold parquet...")
    gold = pd.read_parquet(gold_path, columns=['depot', 'date', 'service_number', 'actual_kms'])
    gold.columns = [c.strip().lower() for c in gold.columns]
    gold['date'] = pd.to_datetime(gold['date']).dt.strftime('%Y-%m-%d')
    gold['service_number'] = gold['service_number'].astype(str).str.strip()
    gold['depot'] = gold['depot'].astype(str).str.upper().str.strip()
    gold['actual_kms'] = pd.to_numeric(gold['actual_kms'], errors='coerce').fillna(0)
    
    # Filter gold to selected date window
    gold = gold[gold['date'].isin(selected_dates)]

    # Gather all depots needed across target regions
    all_target_depots = set()
    for reg in target_regions:
        for dep in region_depot_map.get(reg, []):
            all_target_depots.add(dep)
    gold = gold[gold['depot'].isin(all_target_depots)]
    print(f"[+] Loaded gold operational records for {len(all_target_depots)} depots over {len(selected_dates)} dates.")

    # 4. Pre-extract Schedules per Date and Depot
    print(f"\n[+] Extracting predictions across {len(selected_dates)} dates...")
    # data_store[depot][date_str] = dict of metrics
    data_store = defaultdict(dict)

    for idx, date_str in enumerate(selected_dates, start=1):
        date_folder = os.path.join(schedule_dir, date_str)
        consolidated_file = os.path.join(date_folder, f"epk_consolidated_schedule_{date_str}.xlsx")

        sched_df = pd.DataFrame()
        if os.path.exists(consolidated_file):
            try:
                sched_df = pd.read_excel(consolidated_file, usecols=lambda c: str(c).strip().lower() in ['depot', 'service_number', 'action'])
                sched_df.columns = [c.strip().lower() for c in sched_df.columns]
                sched_df['depot'] = sched_df['depot'].astype(str).str.upper().str.strip()
                sched_df['service_number'] = sched_df['service_number'].astype(str).str.strip()
                sched_df['action'] = sched_df['action'].astype(str).str.upper().str.strip()
            except Exception:
                sched_df = pd.DataFrame()

        date_gold = gold[gold['date'] == date_str]

        for reg in target_regions:
            for depot in region_depot_map.get(reg, []):
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

                # Predicted CUT services
                if not depot_sched.empty and 'action' in depot_sched.columns:
                    cut_rows = depot_sched[depot_sched['action'] == 'CUT']
                    pred_cut_services = sorted(list(set(s for s in cut_rows['service_number'].astype(str).str.strip().tolist() if s)))
                    all_sched_svcs = set(depot_sched['service_number'].astype(str).str.strip().tolist())
                else:
                    pred_cut_services = []
                    all_sched_svcs = set()

                pred_cut_count = len(pred_cut_services)

                # Actual operational cuts
                act_depot = date_gold[date_gold['depot'] == depot]
                if len(act_depot) > 0:
                    operated_svcs = set(act_depot[act_depot['actual_kms'] > 0]['service_number'].astype(str).str.strip())
                    
                    if all_sched_svcs:
                        actual_cut_svcs = sorted(list(all_sched_svcs - operated_svcs))
                    else:
                        actual_cut_svcs = []

                    actual_cut_count = len(actual_cut_svcs)
                    matched_cuts = sorted([s for s in pred_cut_services if s in actual_cut_svcs])
                    extra_cuts = sorted([s for s in actual_cut_svcs if s not in pred_cut_services])
                    ran_ai_cuts = sorted([s for s in pred_cut_services if s in operated_svcs])
                    
                    # 9000-series / 8000-series specials operated
                    specials_operated = sorted([s for s in operated_svcs if re.fullmatch(r"[89]\d{3}", s)])

                    # In Service Master can be cancelled: YES / NO
                    yes_cuts = sorted([s for s in actual_cut_svcs if cancellable_map.get((depot, normalize_service_number(s)), 0) == 1])
                    no_cuts = sorted([s for s in actual_cut_svcs if cancellable_map.get((depot, normalize_service_number(s)), 0) == 0])

                    has_actuals = True
                else:
                    has_actuals = False
                    actual_cut_svcs = []
                    actual_cut_count = 0
                    matched_cuts = []
                    extra_cuts = []
                    ran_ai_cuts = []
                    specials_operated = []
                    yes_cuts = []
                    no_cuts = []

                # Format Cell 1: PREDICTED CUT
                if pred_cut_count > 0:
                    pred_cell = f"{pred_cut_count} ({', '.join(pred_cut_services)})"
                else:
                    pred_cell = "0"

                # Format Cell 2: ACTUAL CUTS FROM THAT DEPOT
                if not has_actuals:
                    act_cell = "Pending" if (pred_cut_count > 0 or all_sched_svcs) else "0"
                else:
                    if actual_cut_count == 0:
                        if ran_ai_cuts:
                            act_cell = f"0 Cut\n[Ran AI ({len(ran_ai_cuts)}): {', '.join(ran_ai_cuts)}]"
                        else:
                            act_cell = "0"
                    else:
                        act_cell = f"{actual_cut_count} Cut ({', '.join(actual_cut_svcs)})"
                        if ran_ai_cuts:
                            act_cell += f"\n[Ran AI ({len(ran_ai_cuts)}): {', '.join(ran_ai_cuts)}]"

                # Format Cell 3: IN SERVICE MASTER CAN BE CANCELLED (YES / NO)
                if not has_actuals:
                    can_cell = "Pending" if (pred_cut_count > 0 or all_sched_svcs) else "-"
                else:
                    if actual_cut_count == 0:
                        can_cell = "-"
                    else:
                        can_lines = []
                        if yes_cuts:
                            can_lines.append(f"YES ({len(yes_cuts)}): {', '.join(yes_cuts)}")
                        else:
                            can_lines.append("YES: 0")
                        
                        if no_cuts:
                            can_lines.append(f"NO ({len(no_cuts)}): {', '.join(no_cuts)}")
                        else:
                            can_lines.append("NO: 0")
                        can_cell = "\n".join(can_lines)

                # Format Cell 4: EXTRA SERVICES (Unpredicted extra cuts made by depot)
                if not has_actuals:
                    extra_cell = "Pending" if (pred_cut_count > 0 or all_sched_svcs) else "0"
                else:
                    if extra_cuts:
                        extra_cell = f"{len(extra_cuts)} ({', '.join(extra_cuts)})"
                    else:
                        extra_cell = "0"

                # Format Cell 5: 9000 SERIES SERVICES (Specials / Extra services operated by depot)
                if not has_actuals:
                    s9000_cell = "Pending" if (pred_cut_count > 0 or all_sched_svcs) else "0"
                else:
                    if specials_operated:
                        s9000_cell = f"{len(specials_operated)} ({', '.join(specials_operated)})"
                    else:
                        s9000_cell = "0"

                data_store[depot][date_str] = {
                    'has_actuals': has_actuals,
                    'pred_count': pred_cut_count,
                    'pred_services': pred_cut_services,
                    'pred_cell': pred_cell,
                    'act_count': actual_cut_count,
                    'act_services': actual_cut_svcs,
                    'act_cell': act_cell,
                    'yes_count': len(yes_cuts),
                    'no_count': len(no_cuts),
                    'can_cell': can_cell,
                    'extra_cuts_count': len(extra_cuts),
                    'extra_cell': extra_cell,
                    'specials_count': len(specials_operated),
                    's9000_cell': s9000_cell
                }

    # 5. Build Multi-Sheet Excel Workbook for each Region
    # Styles
    font_banner = Font(name="Segoe UI", size=12, bold=True, color="FFFFFF")
    font_subtitle = Font(name="Segoe UI", size=9, italic=True, color="FFFFFF")
    font_header = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    font_date = Font(name="Segoe UI", size=10, bold=True, color="0F172A")
    font_data = Font(name="Segoe UI", size=9)
    font_total = Font(name="Segoe UI", size=10, bold=True, color="0F172A")

    fill_banner = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")     # Deep Navy
    fill_subtitle = PatternFill(start_color="334155", end_color="334155", fill_type="solid")   # Slate Blue
    
    fill_hdr_date = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")   # Dark Slate
    fill_hdr_pred = PatternFill(start_color="1D4ED8", end_color="1D4ED8", fill_type="solid")   # Royal Blue
    fill_hdr_act = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")    # Teal
    fill_hdr_can = PatternFill(start_color="4338CA", end_color="4338CA", fill_type="solid")    # Indigo
    fill_hdr_extra = PatternFill(start_color="C2410C", end_color="C2410C", fill_type="solid")  # Rust Orange / Amber
    fill_hdr_9000 = PatternFill(start_color="7C3AED", end_color="7C3AED", fill_type="solid")   # Royal Violet

    fill_row_even = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_row_odd = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    fill_total = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")

    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    border_thin = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )
    border_total = Border(
        left=Side(style='thin', color='94A3B8'),
        right=Side(style='thin', color='94A3B8'),
        top=Side(style='medium', color='475569'),
        bottom=Side(style='double', color='1E293B')
    )

    generated_files = []

    for reg in target_regions:
        depots = region_depot_map.get(reg, [])
        if not depots:
            print(f"[!] Warning: No depots found for region {reg}. Skipping.")
            continue

        file_prefix = "krmr" if reg == "KARIMNAGAR" else reg.lower()
        output_file = os.path.join(output_dir, f"{file_prefix}_cut_services_analysis.xlsx")
        
        print(f"\n[+] Building Workbook for Region: {reg} ({len(depots)} Depots) -> {output_file}")
        wb = Workbook()
        wb.remove(wb.active)  # Remove initial blank sheet

        for depot_idx, depot in enumerate(depots, start=1):
            sheet_title = f"{depot}"[:31]
            ws = wb.create_sheet(title=sheet_title)
            ws.views.sheetView[0].showGridLines = True

            # ── Row 1: Merged Title Banner ────────────────────────────────────
            ws.merge_cells("A1:F1")
            banner_cell = ws["A1"]
            banner_cell.value = f"DEPOT CUT SERVICES ANALYSIS ({depot})"
            banner_cell.font = font_banner
            banner_cell.fill = fill_banner
            banner_cell.alignment = align_center
            ws.row_dimensions[1].height = 34
            for col in range(1, 7):
                ws.cell(row=1, column=col).border = border_thin

            # ── Row 2: Merged Subtitle Banner ─────────────────────────────────
            ws.merge_cells("A2:F2")
            sub_cell = ws["A2"]
            sub_cell.value = f"Region: {reg}  |  Period: Last {days} Days ({selected_dates[0]} to {selected_dates[-1]})  |  Source: Dynamic Schedule & Service Master"
            sub_cell.font = font_subtitle
            sub_cell.fill = fill_subtitle
            sub_cell.alignment = align_center
            ws.row_dimensions[2].height = 20
            for col in range(1, 7):
                ws.cell(row=2, column=col).border = border_thin

            # ── Row 3: Column Headers ─────────────────────────────────────────
            headers = [
                ("DATE", fill_hdr_date),
                ("PREDICTED CUT", fill_hdr_pred),
                ("ACTUAL CUTS FROM THAT DEPOT", fill_hdr_act),
                ("IN SERVICE MASTER CAN BE CANCELLED (YES / NO)", fill_hdr_can),
                ("EXTRA SERVICES", fill_hdr_extra),
                ("9000 SERIES SERVICES", fill_hdr_9000)
            ]

            ws.row_dimensions[3].height = 28
            for col_idx, (hdr_text, hdr_fill) in enumerate(headers, start=1):
                h_cell = ws.cell(row=3, column=col_idx, value=hdr_text)
                h_cell.font = font_header
                h_cell.fill = hdr_fill
                h_cell.alignment = align_center
                h_cell.border = border_thin

            # ── Rows 4 to N: Data Rows ────────────────────────────────────────
            tot_pred = 0
            tot_act = 0
            tot_yes = 0
            tot_no = 0
            tot_extra_cuts = 0
            tot_specials = 0

            row_num = 4
            for date_str in selected_dates:
                d_info = data_store[depot].get(date_str, {})
                row_fill = fill_row_even if (row_num % 2 == 0) else fill_row_odd

                tot_pred += d_info.get('pred_count', 0)
                tot_act += d_info.get('act_count', 0)
                tot_yes += d_info.get('yes_count', 0)
                tot_no += d_info.get('no_count', 0)
                tot_extra_cuts += d_info.get('extra_cuts_count', 0)
                tot_specials += d_info.get('specials_count', 0)

                # Col 1: DATE
                c1 = ws.cell(row=row_num, column=1, value=date_str)
                c1.font = font_date
                c1.fill = row_fill
                c1.alignment = align_center
                c1.border = border_thin

                # Col 2: PREDICTED CUT
                c2 = ws.cell(row=row_num, column=2, value=d_info.get('pred_cell', '0'))
                c2.font = font_data
                c2.fill = row_fill
                c2.alignment = align_center if d_info.get('pred_cell', '0') == '0' else align_left
                c2.border = border_thin

                # Col 3: ACTUAL CUTS FROM THAT DEPOT
                c3 = ws.cell(row=row_num, column=3, value=d_info.get('act_cell', '0'))
                c3.font = font_data
                c3.fill = row_fill
                c3.alignment = align_center if d_info.get('act_cell', '0') in ['0', 'Pending'] else align_left
                c3.border = border_thin

                # Col 4: IN SERVICE MASTER CAN BE CANCELLED (YES / NO)
                c4 = ws.cell(row=row_num, column=4, value=d_info.get('can_cell', '-'))
                c4.font = font_data
                c4.fill = row_fill
                c4.alignment = align_center if d_info.get('can_cell', '-') in ['-', 'Pending', '0'] else align_left
                c4.border = border_thin

                # Col 5: EXTRA SERVICES
                c5 = ws.cell(row=row_num, column=5, value=d_info.get('extra_cell', '0'))
                c5.font = font_data
                c5.fill = row_fill
                c5.alignment = align_center if d_info.get('extra_cell', '0') in ['0', 'Pending'] else align_left
                c5.border = border_thin

                # Col 6: 9000 SERIES SERVICES
                c6 = ws.cell(row=row_num, column=6, value=d_info.get('s9000_cell', '0'))
                c6.font = font_data
                c6.fill = row_fill
                c6.alignment = align_center if d_info.get('s9000_cell', '0') in ['0', 'Pending'] else align_left
                c6.border = border_thin

                # Dynamic row height based on content line breaks
                max_lines = max(
                    str(c2.value).count('\n') + 1,
                    str(c3.value).count('\n') + 1,
                    str(c4.value).count('\n') + 1,
                    str(c5.value).count('\n') + 1,
                    str(c6.value).count('\n') + 1
                )
                ws.row_dimensions[row_num].height = max(26, max_lines * 18)

                row_num += 1

            # ── Summary / Total Row ───────────────────────────────────────────
            ws.row_dimensions[row_num].height = 30

            t1 = ws.cell(row=row_num, column=1, value="TOTAL / SUMMARY")
            t1.font = font_total
            t1.fill = fill_total
            t1.alignment = align_center
            t1.border = border_total

            t2 = ws.cell(row=row_num, column=2, value=f"Total Predicted: {tot_pred}")
            t2.font = font_total
            t2.fill = fill_total
            t2.alignment = align_center
            t2.border = border_total

            t3 = ws.cell(row=row_num, column=3, value=f"Total Actual Cuts: {tot_act}")
            t3.font = font_total
            t3.fill = fill_total
            t3.alignment = align_center
            t3.border = border_total

            t4 = ws.cell(row=row_num, column=4, value=f"Total YES: {tot_yes} | Total NO: {tot_no}")
            t4.font = font_total
            t4.fill = fill_total
            t4.alignment = align_center
            t4.border = border_total

            t5 = ws.cell(row=row_num, column=5, value=f"Total Extra Cuts: {tot_extra_cuts}")
            t5.font = font_total
            t5.fill = fill_total
            t5.alignment = align_center
            t5.border = border_total

            t6 = ws.cell(row=row_num, column=6, value=f"Total 9000 Series: {tot_specials}")
            t6.font = font_total
            t6.fill = fill_total
            t6.alignment = align_center
            t6.border = border_total

            # Column dimensions
            ws.column_dimensions['A'].width = 14
            ws.column_dimensions['B'].width = 30
            ws.column_dimensions['C'].width = 46
            ws.column_dimensions['D'].width = 48
            ws.column_dimensions['E'].width = 46
            ws.column_dimensions['F'].width = 46

            # Freeze Panes at row 4 so headers stay visible
            ws.freeze_panes = "A4"

            print(f"    - Sheet {depot_idx}: {depot} ({len(selected_dates)} dates, {tot_pred} Pred Cuts, {tot_act} Act Cuts)")

        saved_path = output_file
        try:
            wb.save(output_file)
        except PermissionError:
            saved_path = output_file.replace(".xlsx", "_updated.xlsx")
            print(f"[!] Warning: '{output_file}' is currently open in Excel or locked. Saving to: {saved_path}")
            try:
                wb.save(saved_path)
            except PermissionError:
                saved_path = output_file.replace(".xlsx", f"_{datetime.now().strftime('%H%M%S')}.xlsx")
                wb.save(saved_path)

        generated_files.append(saved_path)
        print(f"[SUCCESS] Saved {reg} Region report to:\n{saved_path}\n")

    return generated_files

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TGSRTC Region Depot Cut Services Analysis (KRMR & ADILABAD).")
    parser.add_argument("--region", type=str, default="KARIMNAGAR,ADILABAD", help="Region(s) to process: 'KRMR', 'ADILABAD', 'KRMR,ADILABAD', or 'ALL' (default: KRMR,ADILABAD)")
    parser.add_argument("--days", type=int, default=30, help="Number of days to analyze from last 1 month (default: 30)")
    parser.add_argument("--schedule-dir", type=str, default=DEFAULT_SCHEDULE_DIR, help="Path to dynamic schedule directory")
    parser.add_argument("--gold-path", type=str, default=DEFAULT_GOLD_PATH, help="Path to ops_daily_service_gold.parquet")
    parser.add_argument("--service-master", type=str, default=DEFAULT_SERVICE_MASTER_PATH, help="Path to service_master.csv")
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG_PATH, help="Path to config.json (optional)")
    parser.add_argument("--output-dir", type=str, default=BASE_DIR, help="Directory to save generated Excel files")

    args = parser.parse_args()

    files = generate_cut_services_analysis(
        regions=args.region,
        days=args.days,
        schedule_dir=args.schedule_dir,
        gold_path=args.gold_path,
        service_master_path=args.service_master,
        config_path=args.config,
        output_dir=args.output_dir
    )

    print("[*] All completed successfully:")
    for f in files:
        print(f"  -> {f}")
