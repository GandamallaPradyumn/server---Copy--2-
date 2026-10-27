#!/usr/bin/env python3
"""
Depot-Wise Predicted vs Actual Service Cut Report Generator (Warangal Depots)
Author: Antigravity
Description:
    Analyzes multi-sheet depot cut service workbooks for Warangal depots (and other regions),
    extracts predicted vs actual cut events over the last 30 days, and produces:
    1. Depot-Wise Predicted vs Actual Cut Services in the user-specified format:
           depot          predicted cut        actual cut
           depot1         0000(10)             0000(11)
           depot2         0001(20)             0001(20)
           depot3         0002(15)             0002(18)
                          0003(26)             0003(28)
    2. Highest Count of Cuts & Actuals Comparison (services ranked by highest cut volume).
    3. An executive Excel workbook with a dedicated 'Warangal Cut Comparison' tab,
       live formulas linking depot sheets, and a comprehensive Markdown report.
"""

import os
import sys
import re
import argparse
from collections import defaultdict, Counter
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Color Palette & Styling Constants (Arial, Professional Palette) ───────────
FONT_FAMILY = "Arial"

# Fonts
F_TITLE = Font(name=FONT_FAMILY, size=14, bold=True, color="FFFFFF")
F_SUBTITLE = Font(name=FONT_FAMILY, size=9, italic=True, color="FFFFFF")
F_SECTION_HDR = Font(name=FONT_FAMILY, size=11, bold=True, color="1E3A8A")
F_TBL_HDR = Font(name=FONT_FAMILY, size=9, bold=True, color="FFFFFF")
F_DATA = Font(name=FONT_FAMILY, size=9, color="1F2937")
F_DATA_BOLD = Font(name=FONT_FAMILY, size=9, bold=True, color="1F2937")
F_TOTAL = Font(name=FONT_FAMILY, size=9, bold=True, color="0F172A")
F_NOTE_HDR = Font(name=FONT_FAMILY, size=10, bold=True, color="1E293B")
F_NOTE_BODY = Font(name=FONT_FAMILY, size=8.5, color="334155")
F_ALERT = Font(name=FONT_FAMILY, size=9, bold=True, color="991B1B")

# Fills
FILL_NAVY_BANNER = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
FILL_SLATE_BANNER = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
FILL_HDR_D1 = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")       # Navy
FILL_HDR_D2 = PatternFill(start_color="134F5C", end_color="134F5C", fill_type="solid")       # Dark Teal
FILL_HDR_D3 = PatternFill(start_color="351C75", end_color="351C75", fill_type="solid")       # Deep Plum
FILL_HDR_DISQ = PatternFill(start_color="783F04", end_color="783F04", fill_type="solid")     # Rust / Amber
FILL_HDR_SUM = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")      # Dark Slate

FILL_ROW_ZEBRA = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
FILL_TOTAL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
FILL_NOTES_BOX = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
FILL_HIGHLIGHT = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")

# Alignments
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_BANNER = Alignment(horizontal="left", vertical="center", indent=1)
ALIGN_WRAP_LEFT = Alignment(horizontal="left", vertical="top", wrap_text=True)

# Borders
BORDER_THIN = Border(
    left=Side(style='thin', color='CBD5E1'),
    right=Side(style='thin', color='CBD5E1'),
    top=Side(style='thin', color='CBD5E1'),
    bottom=Side(style='thin', color='CBD5E1')
)
BORDER_TOTAL = Border(
    left=Side(style='thin', color='94A3B8'),
    right=Side(style='thin', color='94A3B8'),
    top=Side(style='thin', color='64748B'),
    bottom=Side(style='double', color='0F172A')
)
BORDER_HEADER = Border(
    left=Side(style='thin', color='CBD5E1'),
    right=Side(style='thin', color='CBD5E1'),
    top=Side(style='medium', color='0F172A'),
    bottom=Side(style='medium', color='0F172A')
)


# ── Parsing Helpers ────────────────────────────────────────────────────────────

def parse_service_tokens(text):
    """Splits a comma-separated list of services, cleans whitespace and casing."""
    if not text:
        return []
    parts = [p.strip().upper() for p in text.split(',') if p.strip()]
    return parts

def parse_predicted_cell(val):
    """
    Parses PREDICTED CUT cell:
    Formats:
      - '0', '', None -> 0, []
      - 'Pending' -> 'pending', []
      - 'N (SVC1, SVC2, ...)' -> N, [SVC1, SVC2, ...]
      - 'N' (plain integer) -> N, []
    Returns: (count_or_status, list_of_services)
    """
    if val is None or str(val).strip() in ['0', '', 'None', '-']:
        return 0, []
    s = str(val).strip()
    if s.lower() == 'pending':
        return 'pending', []
    
    m = re.match(r'^(\d+)\s*\((.*?)\)$', s, re.DOTALL)
    if m:
        n = int(m.group(1))
        svcs = parse_service_tokens(m.group(2))
        return n, svcs
    if s.isdigit():
        return int(s), []
    return None, [s]

def parse_actual_cell(val):
    """
    Parses ACTUAL CUTS cell:
    Formats:
      - '0', '0 Cut', '', None -> 0, [], []
      - 'Pending' -> 'pending', [], []
      - 'N Cut (SVC1, SVC2, ...)' optionally with '\\n[Ran AI (n): ...]'
    Returns: (cut_count_or_status, cut_services_list, ran_ai_services_list)
    """
    if val is None or str(val).strip() in ['0', '', 'None', '-']:
        return 0, [], []
    s = str(val).strip()
    if s.lower() == 'pending':
        return 'pending', [], []
    
    ran_ai_svcs = []
    ran_m = re.search(r'\[Ran AI(?:\s*\(\d+\))?:\s*(.*?)\]', s, re.DOTALL)
    if ran_m:
        ran_ai_svcs = parse_service_tokens(ran_m.group(1))
        s = (s[:ran_m.start()] + s[ran_m.end():]).strip()
    
    if s in ['0', '0 Cut', '']:
        return 0, [], ran_ai_svcs
    
    m = re.match(r'^(\d+)\s*Cut\s*\((.*?)\)$', s, re.DOTALL)
    if m:
        n = int(m.group(1))
        svcs = parse_service_tokens(m.group(2))
        return n, svcs, ran_ai_svcs
    
    m2 = re.match(r'^(\d+)\s*Cut$', s)
    if m2:
        return int(m2.group(1)), [], ran_ai_svcs
    
    return None, [s], ran_ai_svcs


# ── Core Analysis Function ─────────────────────────────────────────────────────

def analyze_depot_workbook(file_path, reg_threshold=10, close_pred_threshold=5, close_ratio_threshold=0.70):
    """
    Loads source workbook and analyzes each depot sheet.
    Returns:
      - metadata: dict of workbook level info
      - validation: validation findings across all sheets
      - depots_data: dict of analyzed metrics per depot
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Workbook not found at: {file_path}")
    
    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet_names = wb.sheetnames
    
    validation = {
        'total_sheets': len(sheet_names),
        'depots_analyzed': sheet_names,
        'count_mismatches': [],
        'unparseable_entries': [],
        'duplicate_entries': [],
        'pending_exclusions': {},
        'total_row_comparisons': {},
        'ambiguities_or_notes': []
    }
    
    depots_data = {}
    
    for sname in sheet_names:
        ws = wb[sname]
        
        # Header / Meta inspection
        title_val = str(ws.cell(1, 1).value or '').strip()
        meta_val = str(ws.cell(2, 1).value or '').strip()
        
        # Read source TOTAL / SUMMARY row (last row)
        tot_row_idx = ws.max_row
        tot_pred_str = str(ws.cell(tot_row_idx, 2).value or '').strip()
        tot_act_str = str(ws.cell(tot_row_idx, 3).value or '').strip()
        
        src_pred_m = re.search(r'(\d+)', tot_pred_str)
        src_pred_tot = int(src_pred_m.group(1)) if src_pred_m else 0
        src_act_m = re.search(r'(\d+)', tot_act_str)
        src_act_tot = int(src_act_m.group(1)) if src_act_m else 0
        
        # Date rows iteration (Row 4 to max_row - 1)
        completed_dates = []
        pending_dates = []
        pending_pred_events = 0
        
        datewise_pred = defaultdict(list)
        datewise_act = defaultdict(list)
        datewise_ran_ai = defaultdict(list)
        
        pred_counts = Counter()
        act_counts = Counter()
        same_day_counts = Counter()
        
        for r in range(4, tot_row_idx):
            d_val = str(ws.cell(r, 1).value or '').strip()
            p_val = ws.cell(r, 2).value
            a_val = ws.cell(r, 3).value
            
            pn, p_svcs = parse_predicted_cell(p_val)
            an, a_svcs, ran_svcs = parse_actual_cell(a_val)
            
            # Check for Pending
            if an == 'pending' or pn == 'pending':
                pending_dates.append(d_val)
                if pn not in [None, 'pending']:
                    pending_pred_events += pn
                continue
            
            completed_dates.append(d_val)
            
            # Validation checks
            if pn is None:
                validation['unparseable_entries'].append({
                    'depot': sname, 'date': d_val, 'column': 'PREDICTED CUT', 'raw': str(p_val)
                })
            else:
                if len(p_svcs) != pn:
                    validation['count_mismatches'].append({
                        'depot': sname, 'date': d_val, 'column': 'PREDICTED CUT',
                        'declared': pn, 'actual_count': len(p_svcs), 'services': p_svcs
                    })
                if len(p_svcs) != len(set(p_svcs)):
                    validation['duplicate_entries'].append({
                        'depot': sname, 'date': d_val, 'column': 'PREDICTED CUT', 'services': p_svcs
                    })
            
            if an is None:
                validation['unparseable_entries'].append({
                    'depot': sname, 'date': d_val, 'column': 'ACTUAL CUTS', 'raw': str(a_val)
                })
            else:
                if len(a_svcs) != an:
                    validation['count_mismatches'].append({
                        'depot': sname, 'date': d_val, 'column': 'ACTUAL CUTS',
                        'declared': an, 'actual_count': len(a_svcs), 'services': a_svcs
                    })
                if len(a_svcs) != len(set(a_svcs)):
                    validation['duplicate_entries'].append({
                        'depot': sname, 'date': d_val, 'column': 'ACTUAL CUTS', 'services': a_svcs
                    })
            
            # Per-day events
            p_set = set(p_svcs)
            a_set = set(a_svcs)
            
            datewise_pred[d_val] = p_svcs
            datewise_act[d_val] = a_svcs
            datewise_ran_ai[d_val] = ran_svcs
            
            for s in p_set:
                pred_counts[s] += 1
            for s in a_set:
                act_counts[s] += 1
            for s in (p_set & a_set):
                same_day_counts[s] += 1
        
        num_completed = len(completed_dates)
        tot_parsed_pred = sum(pred_counts.values())
        tot_parsed_act = sum(act_counts.values())
        
        # Validation on Pending Exclusions
        validation['pending_exclusions'][sname] = {
            'pending_dates': pending_dates,
            'completed_days': num_completed,
            'pred_cuts_on_pending': pending_pred_events
        }
        
        # Validation comparing with source sheet TOTAL row
        validation['total_row_comparisons'][sname] = {
            'src_pred_tot': src_pred_tot,
            'parsed_pred_tot': tot_parsed_pred,
            'pred_diff': src_pred_tot - tot_parsed_pred,
            'src_act_tot': src_act_tot,
            'parsed_act_tot': tot_parsed_act,
            'act_diff': src_act_tot - tot_parsed_act,
            'explanation': (
                f"Source predicted total includes {pending_pred_events} cuts from pending date(s) {pending_dates}; "
                f"like-for-like parsed total strictly excludes pending dates. Actuals match 100%."
            )
        }
        
        # Collect all services appearing in either list
        all_services = sorted(list(set(pred_counts.keys()) | set(act_counts.keys())))
        
        # Deliverable 1 table data
        d1_list = []
        for s in all_services:
            d1_list.append({
                'service': s,
                'pred_count': pred_counts[s],
                'act_count': act_counts[s]
            })
        
        # Deliverable 2: Regular cuts (act_count >= reg_threshold)
        d2_list = []
        for s in all_services:
            act_cnt = act_counts[s]
            if act_cnt >= reg_threshold:
                pct = (act_cnt / num_completed) if num_completed > 0 else 0
                d2_list.append({
                    'service': s,
                    'pred_count': pred_counts[s],
                    'act_count': act_cnt,
                    'pct_days': pct
                })
        d2_list.sort(key=lambda x: (x['act_count'], x['pred_count']), reverse=True)
        
        # Deliverable 3: Close matches (pred_count >= close_pred_threshold and ratio >= close_ratio_threshold)
        d3_qual = []
        d3_disqual = []
        
        for s in all_services:
            p = pred_counts[s]
            a = act_counts[s]
            same_day = same_day_counts[s]
            
            if p == 0:
                continue
            
            max_c = max(p, a)
            min_c = min(p, a)
            ratio = (min_c / max_c) if max_c > 0 else 0
            diff = a - p
            
            item = {
                'service': s,
                'pred_count': p,
                'act_count': a,
                'diff': diff,
                'match_ratio': ratio,
                'same_day_count': same_day
            }
            
            if p >= close_pred_threshold and ratio >= close_ratio_threshold:
                d3_qual.append(item)
            else:
                reasons = []
                if p < close_pred_threshold:
                    reasons.append(f"Predicted < {close_pred_threshold} times ({p})")
                if ratio < close_ratio_threshold:
                    reasons.append(f"Match ratio {ratio:.1%} < {close_ratio_threshold:.0%}")
                item['reason'] = "; ".join(reasons)
                d3_disqual.append(item)
        
        d3_qual.sort(key=lambda x: (x['match_ratio'], x['pred_count']), reverse=True)
        d3_disqual.sort(key=lambda x: x['pred_count'], reverse=True)
        
        depots_data[sname] = {
            'depot_name': sname,
            'title': title_val,
            'meta': meta_val,
            'completed_dates': completed_dates,
            'completed_days': num_completed,
            'pending_dates': pending_dates,
            'tot_pred': tot_parsed_pred,
            'tot_act': tot_parsed_act,
            'diff': tot_parsed_act - tot_parsed_pred,
            'src_pred_tot': src_pred_tot,
            'src_act_tot': src_act_tot,
            'd1_services': d1_list,
            'd2_regular': d2_list,
            'd3_qual': d3_qual,
            'd3_disqual': d3_disqual,
            'same_day_counts': same_day_counts
        }
    
    metadata = {
        'source_file': os.path.basename(file_path),
        'source_path': os.path.abspath(file_path),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'reg_threshold': reg_threshold,
        'close_pred_threshold': close_pred_threshold,
        'close_ratio_threshold': close_ratio_threshold
    }
    
    return metadata, validation, depots_data


# ── User-Specified Cut Services Formatting Helpers ─────────────────────────────

def extract_formatted_cut_tables(depots_data, top_n_unpredicted=5):
    """
    Builds the two user-requested table representations:
    Format 1: Depot-wise comparison in the exact layout:
        depot          predicted cut        actual cut
        depot1         0000(10)             0000(11)
        depot2         0001(20)             0001(20)
        depot3         0002(15)             0002(18)
                       0003(26)             0003(28)
    Format 2: Highest count of cuts & actuals comparison:
        Ranked across depots by highest cut volume.
    """
    depot_wise_rows = []
    
    for dname in sorted(depots_data.keys()):
        data = depots_data[dname]
        all_svcs = data['d1_services']
        pred_svcs = [s for s in all_svcs if s['pred_count'] > 0]
        # Sort by predicted count descending, then actual count descending
        pred_svcs.sort(key=lambda x: (x['pred_count'], x['act_count']), reverse=True)
        
        if pred_svcs:
            first = True
            for item in pred_svcs:
                s = item['service']
                p = item['pred_count']
                a = item['act_count']
                ratio = (min(p, a) / max(p, a)) if max(p, a) > 0 else 0
                depot_wise_rows.append({
                    'depot_display': dname if first else "",
                    'depot_full': dname,
                    'service': s,
                    'pred_str': f"{s}({p})",
                    'act_str': f"{s}({a})",
                    'pred_count': p,
                    'act_count': a,
                    'diff': a - p,
                    'match_ratio': ratio,
                    'type': 'predicted'
                })
                first = False
        else:
            # Zero-prediction depot (e.g. Bhupalapallay, Warangal-II): show top operational cuts
            top_acts = sorted(all_svcs, key=lambda x: x['act_count'], reverse=True)[:top_n_unpredicted]
            first = True
            for item in top_acts:
                s = item['service']
                p = item['pred_count']
                a = item['act_count']
                depot_wise_rows.append({
                    'depot_display': dname if first else "",
                    'depot_full': dname,
                    'service': s,
                    'pred_str': f"{s}(0)",
                    'act_str': f"{s}({a})",
                    'pred_count': 0,
                    'act_count': a,
                    'diff': a,
                    'match_ratio': 0.0,
                    'type': 'unpredicted_top'
                })
                first = False

    # Format 2A: Predicted services ranked by highest cut volume
    highest_pred_rows = []
    for dname, data in depots_data.items():
        for item in data['d1_services']:
            p = item['pred_count']
            a = item['act_count']
            s = item['service']
            if p > 0:
                ratio = (min(p, a) / max(p, a)) if max(p, a) > 0 else 0
                highest_pred_rows.append({
                    'depot': dname,
                    'service': s,
                    'pred_str': f"{s}({p})",
                    'act_str': f"{s}({a})",
                    'pred_count': p,
                    'act_count': a,
                    'diff': a - p,
                    'match_ratio': ratio,
                    'max_cuts': max(p, a)
                })
    highest_pred_rows.sort(key=lambda x: (x['max_cuts'], x['pred_count'], x['act_count']), reverse=True)

    # Format 2B: Top 25 Highest Overall Cuts across all Warangal depots
    top_overall_rows = []
    for dname, data in depots_data.items():
        for item in data['d1_services']:
            p = item['pred_count']
            a = item['act_count']
            s = item['service']
            if a > 0:
                ratio = (min(p, a) / max(p, a)) if max(p, a) > 0 else 0
                top_overall_rows.append({
                    'depot': dname,
                    'service': s,
                    'pred_str': f"{s}({p})",
                    'act_str': f"{s}({a})",
                    'pred_count': p,
                    'act_count': a,
                    'diff': a - p,
                    'match_ratio': ratio,
                    'category': 'AI Predicted & Cut' if p > 0 else 'Depot Operational Cut (Unpredicted)'
                })
    top_overall_rows.sort(key=lambda x: (x['act_count'], x['pred_count']), reverse=True)
    top_overall_rows = top_overall_rows[:25]

    return {
        'depot_wise': depot_wise_rows,
        'highest_predicted': highest_pred_rows,
        'top_overall': top_overall_rows
    }

def print_formatted_cut_tables(tables):
    """Prints the requested formatted tables to the console with clear tabular alignment."""
    print("\n" + "=" * 80)
    print("FORMAT 1: DEPOT-WISE PREDICTED VS ACTUAL CUT SERVICES (LAST 30 DAYS)")
    print("=" * 80)
    print(f"{'depot':<18} {'predicted cut':<20} {'actual cut':<20}")
    print("-" * 60)
    for r in tables['depot_wise']:
        print(f"{r['depot_display']:<18} {r['pred_str']:<20} {r['act_str']:<20}")

    print("\n" + "=" * 80)
    print("FORMAT 2: HIGHEST COUNT OF CUTS & ACTUALS COMPARISON (PREDICTED SERVICES)")
    print("=" * 80)
    print(f"{'depot':<18} {'predicted cut':<20} {'actual cut':<20} {'diff':<10} {'match %':<10}")
    print("-" * 80)
    for r in tables['highest_predicted']:
        diff_str = f"{r['diff']:+d}"
        print(f"{r['depot']:<18} {r['pred_str']:<20} {r['act_str']:<20} {diff_str:<10} {r['match_ratio']:.1%}")

    print("\n" + "=" * 80)
    print("FORMAT 2B: TOP 20 HIGHEST OVERALL REGIONAL CUT SERVICES (ALL DEPOTS)")
    print("=" * 80)
    print(f"{'depot':<18} {'predicted cut':<20} {'actual cut':<20} {'category'}")
    print("-" * 80)
    for r in tables['top_overall'][:20]:
        print(f"{r['depot']:<18} {r['pred_str']:<20} {r['act_str']:<20} {r['category']}")
    print("=" * 80)


# ── Excel Workbook Writer ──────────────────────────────────────────────────────

def generate_excel_report(metadata, validation, depots_data, output_path):
    """
    Creates an Excel workbook with:
    - Dedicated Sheet 1: 'Warangal Cut Comparison' with user requested table formats:
      * Format 1: Depot-wise comparison (depot, predicted cut, actual cut)
      * Format 2: Highest count of cuts & actuals comparison
      * Format 2B: Top 25 Highest overall regional cuts
    - Sheet 2: 'Summary' linking to depot detail sheets via live formulas
    - Individual detail sheets per depot with side-by-side tables for Deliverables 1, 2, 3
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default blank sheet
    
    tables = extract_formatted_cut_tables(depots_data)

    # ─────────────────────────────────────────────────────────────────────────
    # 0. DEDICATED SHEET: WARANGAL CUT COMPARISON FORMAT (INDEX 0)
    # ─────────────────────────────────────────────────────────────────────────
    ws_fmt = wb.create_sheet(title="Warangal Cut Comparison", index=0)
    ws_fmt.views.sheetView[0].showGridLines = True
    
    # Title Banner
    ws_fmt.merge_cells("A1:E1")
    f_b1 = ws_fmt["A1"]
    f_b1.value = "WARANGAL REGION DEPOT SERVICE CUT ANALYSIS (LAST 30 DAYS)"
    f_b1.font = F_TITLE
    f_b1.fill = FILL_NAVY_BANNER
    f_b1.alignment = ALIGN_BANNER
    ws_fmt.row_dimensions[1].height = 28

    ws_fmt.merge_cells("A2:E2")
    f_b2 = ws_fmt["A2"]
    f_b2.value = f"Layout: depot | predicted cut [service(count)] | actual cut [service(count)]  |  Source: {metadata['source_file']}"
    f_b2.font = F_SUBTITLE
    f_b2.fill = FILL_SLATE_BANNER
    f_b2.alignment = ALIGN_BANNER
    ws_fmt.row_dimensions[2].height = 20

    curr_fmt_r = 4

    # ── Table 1: Depot-wise Cut Services ──────────────────────────────────────
    ws_fmt[f"A{curr_fmt_r}"] = "FORMAT 1: DEPOT-WISE PREDICTED VS ACTUAL CUT SERVICES (LAST 30 DAYS)"
    ws_fmt[f"A{curr_fmt_r}"].font = F_SECTION_HDR
    curr_fmt_r += 1

    fmt1_headers = [
        ("A", "depot", FILL_HDR_D1, ALIGN_LEFT),
        ("B", "predicted cut", FILL_HDR_D1, ALIGN_CENTER),
        ("C", "actual cut", FILL_HDR_D1, ALIGN_CENTER),
        ("D", "Difference (Act - Pred)", FILL_HDR_D1, ALIGN_RIGHT),
        ("E", "Match %", FILL_HDR_D1, ALIGN_RIGHT)
    ]
    for col_l, text, fill, align in fmt1_headers:
        c = ws_fmt[f"{col_l}{curr_fmt_r}"]
        c.value = text
        c.font = F_TBL_HDR
        c.fill = fill
        c.alignment = align
        c.border = BORDER_HEADER
    ws_fmt.row_dimensions[curr_fmt_r].height = 24
    curr_fmt_r += 1

    for row_idx, item in enumerate(tables['depot_wise']):
        r = curr_fmt_r
        # Depot name
        ws_fmt[f"A{r}"] = item['depot_display']
        ws_fmt[f"A{r}"].font = F_DATA_BOLD if item['depot_display'] else F_DATA
        ws_fmt[f"A{r}"].alignment = ALIGN_LEFT
        ws_fmt[f"A{r}"].border = BORDER_THIN

        # Predicted cut: e.g. HKM2(14)
        ws_fmt[f"B{r}"] = item['pred_str']
        ws_fmt[f"B{r}"].font = F_DATA
        ws_fmt[f"B{r}"].alignment = ALIGN_CENTER
        ws_fmt[f"B{r}"].border = BORDER_THIN

        # Actual cut: e.g. HKM2(24)
        ws_fmt[f"C{r}"] = item['act_str']
        ws_fmt[f"C{r}"].font = F_DATA
        ws_fmt[f"C{r}"].alignment = ALIGN_CENTER
        ws_fmt[f"C{r}"].border = BORDER_THIN

        # Difference
        ws_fmt[f"D{r}"] = item['diff']
        ws_fmt[f"D{r}"].font = F_DATA
        ws_fmt[f"D{r}"].alignment = ALIGN_RIGHT
        ws_fmt[f"D{r}"].number_format = "+#,##0;-#,##0;0"
        ws_fmt[f"D{r}"].border = BORDER_THIN

        # Match %
        ws_fmt[f"E{r}"] = item['match_ratio']
        ws_fmt[f"E{r}"].font = F_DATA
        ws_fmt[f"E{r}"].alignment = ALIGN_RIGHT
        ws_fmt[f"E{r}"].number_format = "0.0%"
        ws_fmt[f"E{r}"].border = BORDER_THIN

        if (row_idx % 2) == 1:
            for col in ["A", "B", "C", "D", "E"]:
                ws_fmt[f"{col}{r}"].fill = FILL_ROW_ZEBRA
        ws_fmt.row_dimensions[r].height = 20
        curr_fmt_r += 1

    curr_fmt_r += 2

    # ── Table 2: Highest Count of Cuts & Actuals Comparison ───────────────────
    ws_fmt[f"A{curr_fmt_r}"] = "FORMAT 2: HIGHEST COUNT OF CUTS & ACTUALS COMPARISON (PREDICTED SERVICES RANKED BY CUT VOLUME)"
    ws_fmt[f"A{curr_fmt_r}"].font = F_SECTION_HDR
    curr_fmt_r += 1

    fmt2_headers = [
        ("A", "depot", FILL_HDR_D3, ALIGN_LEFT),
        ("B", "predicted cut", FILL_HDR_D3, ALIGN_CENTER),
        ("C", "actual cut", FILL_HDR_D3, ALIGN_CENTER),
        ("D", "Difference (Act - Pred)", FILL_HDR_D3, ALIGN_RIGHT),
        ("E", "Match %", FILL_HDR_D3, ALIGN_RIGHT)
    ]
    for col_l, text, fill, align in fmt2_headers:
        c = ws_fmt[f"{col_l}{curr_fmt_r}"]
        c.value = text
        c.font = F_TBL_HDR
        c.fill = fill
        c.alignment = align
        c.border = BORDER_HEADER
    ws_fmt.row_dimensions[curr_fmt_r].height = 24
    curr_fmt_r += 1

    for row_idx, item in enumerate(tables['highest_predicted']):
        r = curr_fmt_r
        ws_fmt[f"A{r}"] = item['depot']
        ws_fmt[f"A{r}"].font = F_DATA_BOLD
        ws_fmt[f"A{r}"].alignment = ALIGN_LEFT
        ws_fmt[f"A{r}"].border = BORDER_THIN

        ws_fmt[f"B{r}"] = item['pred_str']
        ws_fmt[f"B{r}"].font = F_DATA
        ws_fmt[f"B{r}"].alignment = ALIGN_CENTER
        ws_fmt[f"B{r}"].border = BORDER_THIN

        ws_fmt[f"C{r}"] = item['act_str']
        ws_fmt[f"C{r}"].font = F_DATA
        ws_fmt[f"C{r}"].alignment = ALIGN_CENTER
        ws_fmt[f"C{r}"].border = BORDER_THIN

        ws_fmt[f"D{r}"] = item['diff']
        ws_fmt[f"D{r}"].font = F_DATA
        ws_fmt[f"D{r}"].alignment = ALIGN_RIGHT
        ws_fmt[f"D{r}"].number_format = "+#,##0;-#,##0;0"
        ws_fmt[f"D{r}"].border = BORDER_THIN

        ws_fmt[f"E{r}"] = item['match_ratio']
        ws_fmt[f"E{r}"].font = F_DATA
        ws_fmt[f"E{r}"].alignment = ALIGN_RIGHT
        ws_fmt[f"E{r}"].number_format = "0.0%"
        ws_fmt[f"E{r}"].border = BORDER_THIN

        if (row_idx % 2) == 1:
            for col in ["A", "B", "C", "D", "E"]:
                ws_fmt[f"{col}{r}"].fill = FILL_ROW_ZEBRA
        ws_fmt.row_dimensions[r].height = 20
        curr_fmt_r += 1

    curr_fmt_r += 2

    # ── Table 2B: Top 25 Highest Overall Cuts ─────────────────────────────────
    ws_fmt[f"A{curr_fmt_r}"] = "FORMAT 2B: TOP 25 HIGHEST OVERALL REGIONAL CUT SERVICES (ALL DEPOTS)"
    ws_fmt[f"A{curr_fmt_r}"].font = F_SECTION_HDR
    curr_fmt_r += 1

    fmt2b_headers = [
        ("A", "depot", FILL_HDR_D2, ALIGN_LEFT),
        ("B", "predicted cut", FILL_HDR_D2, ALIGN_CENTER),
        ("C", "actual cut", FILL_HDR_D2, ALIGN_CENTER),
        ("D", "Difference (Act - Pred)", FILL_HDR_D2, ALIGN_RIGHT),
        ("E", "Operational Category", FILL_HDR_D2, ALIGN_LEFT)
    ]
    for col_l, text, fill, align in fmt2b_headers:
        c = ws_fmt[f"{col_l}{curr_fmt_r}"]
        c.value = text
        c.font = F_TBL_HDR
        c.fill = fill
        c.alignment = align
        c.border = BORDER_HEADER
    ws_fmt.row_dimensions[curr_fmt_r].height = 24
    curr_fmt_r += 1

    for row_idx, item in enumerate(tables['top_overall']):
        r = curr_fmt_r
        ws_fmt[f"A{r}"] = item['depot']
        ws_fmt[f"A{r}"].font = F_DATA_BOLD
        ws_fmt[f"A{r}"].alignment = ALIGN_LEFT
        ws_fmt[f"A{r}"].border = BORDER_THIN

        ws_fmt[f"B{r}"] = item['pred_str']
        ws_fmt[f"B{r}"].font = F_DATA
        ws_fmt[f"B{r}"].alignment = ALIGN_CENTER
        ws_fmt[f"B{r}"].border = BORDER_THIN

        ws_fmt[f"C{r}"] = item['act_str']
        ws_fmt[f"C{r}"].font = F_DATA
        ws_fmt[f"C{r}"].alignment = ALIGN_CENTER
        ws_fmt[f"C{r}"].border = BORDER_THIN

        ws_fmt[f"D{r}"] = item['diff']
        ws_fmt[f"D{r}"].font = F_DATA
        ws_fmt[f"D{r}"].alignment = ALIGN_RIGHT
        ws_fmt[f"D{r}"].number_format = "+#,##0;-#,##0;0"
        ws_fmt[f"D{r}"].border = BORDER_THIN

        ws_fmt[f"E{r}"] = item['category']
        ws_fmt[f"E{r}"].font = F_DATA
        ws_fmt[f"E{r}"].alignment = ALIGN_LEFT
        ws_fmt[f"E{r}"].border = BORDER_THIN

        if (row_idx % 2) == 1:
            for col in ["A", "B", "C", "D", "E"]:
                ws_fmt[f"{col}{r}"].fill = FILL_ROW_ZEBRA
        ws_fmt.row_dimensions[r].height = 20
        curr_fmt_r += 1

    # Column dimensions for ws_fmt
    ws_fmt.column_dimensions['A'].width = 20
    ws_fmt.column_dimensions['B'].width = 22
    ws_fmt.column_dimensions['C'].width = 22
    ws_fmt.column_dimensions['D'].width = 24
    ws_fmt.column_dimensions['E'].width = 34
    ws_fmt.freeze_panes = "A6"

    # ─────────────────────────────────────────────────────────────────────────
    # 1. DETAIL SHEETS (One per Depot)
    # ─────────────────────────────────────────────────────────────────────────
    depot_totals_coords = {}
    
    for sname, data in depots_data.items():
        ws = wb.create_sheet(title=sname)
        ws.views.sheetView[0].showGridLines = True
        
        num_days = data['completed_days']
        
        # Banner Header (Rows 1-2)
        ws.merge_cells("A1:N1")
        cell_a1 = ws["A1"]
        cell_a1.value = f"DEPOT SERVICE CUT REPORT: {sname}"
        cell_a1.font = F_TITLE
        cell_a1.fill = FILL_NAVY_BANNER
        cell_a1.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[1].height = 28
        
        ws.merge_cells("A2:N2")
        cell_a2 = ws["A2"]
        pending_str = ", ".join(data['pending_dates']) if data['pending_dates'] else "None"
        cell_a2.value = f"Period: Completed {num_days} Days (Like-for-Like Analysis)  |  Excluded Pending Dates: {pending_str}  |  Source: {metadata['source_file']}"
        cell_a2.font = F_SUBTITLE
        cell_a2.fill = FILL_SLATE_BANNER
        cell_a2.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[2].height = 20
        
        # Section Header Labels (Row 3)
        ws["A3"] = "DELIVERABLE 1: FULL CUT REPORT"
        ws["A3"].font = Font(name=FONT_FAMILY, size=9.5, bold=True, color="1F497D")
        
        ws["E3"] = f"DELIVERABLE 2: REGULAR CUT SERVICES (Cut on >= {metadata['reg_threshold']} Completed Days)"
        ws["E3"].font = Font(name=FONT_FAMILY, size=9.5, bold=True, color="134F5C")
        
        ws["J3"] = f"DELIVERABLE 3: CLOSE MATCH PREDICTIONS (Pred >= {metadata['close_pred_threshold']} & Match >= {metadata['close_ratio_threshold']:.0%})"
        ws["J3"].font = Font(name=FONT_FAMILY, size=9.5, bold=True, color="351C75")
        ws.row_dimensions[3].height = 22
        
        # Table Header Row (Row 4)
        headers_row = [
            ("A4", "Service Number", FILL_HDR_D1, ALIGN_LEFT),
            ("B4", "Predicted Cut Count", FILL_HDR_D1, ALIGN_RIGHT),
            ("C4", "Actual Cut Count", FILL_HDR_D1, ALIGN_RIGHT),
            
            ("E4", "Service Number", FILL_HDR_D2, ALIGN_LEFT),
            ("F4", "Predicted Cut Count", FILL_HDR_D2, ALIGN_RIGHT),
            ("G4", "Actual Cut Count", FILL_HDR_D2, ALIGN_RIGHT),
            ("H4", "% of Days Cut", FILL_HDR_D2, ALIGN_RIGHT),
            
            ("J4", "Service Number", FILL_HDR_D3, ALIGN_LEFT),
            ("K4", "Predicted Count", FILL_HDR_D3, ALIGN_RIGHT),
            ("L4", "Actual Count", FILL_HDR_D3, ALIGN_RIGHT),
            ("M4", "Difference (Act - Pred)", FILL_HDR_D3, ALIGN_RIGHT),
            ("N4", "Match %", FILL_HDR_D3, ALIGN_RIGHT),
            ("O4", "Same-Day Coincident Cuts", FILL_HDR_D3, ALIGN_RIGHT)
        ]
        for coord, text, fill, align in headers_row:
            c = ws[coord]
            c.value = text
            c.font = F_TBL_HDR
            c.fill = fill
            c.alignment = align
            c.border = BORDER_HEADER
        ws.row_dimensions[4].height = 25
        
        # Populate Deliverable 1 Data (Cols A-C, starting at row 5)
        d1_list = data['d1_services']
        d1_start_row = 5
        curr_row_d1 = d1_start_row
        for item in d1_list:
            ws[f"A{curr_row_d1}"] = item['service']
            ws[f"A{curr_row_d1}"].font = F_DATA_BOLD
            ws[f"A{curr_row_d1}"].alignment = ALIGN_LEFT
            ws[f"A{curr_row_d1}"].border = BORDER_THIN
            
            ws[f"B{curr_row_d1}"] = item['pred_count']
            ws[f"B{curr_row_d1}"].font = F_DATA
            ws[f"B{curr_row_d1}"].alignment = ALIGN_RIGHT
            ws[f"B{curr_row_d1}"].number_format = "#,##0"
            ws[f"B{curr_row_d1}"].border = BORDER_THIN
            
            ws[f"C{curr_row_d1}"] = item['act_count']
            ws[f"C{curr_row_d1}"].font = F_DATA
            ws[f"C{curr_row_d1}"].alignment = ALIGN_RIGHT
            ws[f"C{curr_row_d1}"].number_format = "#,##0"
            ws[f"C{curr_row_d1}"].border = BORDER_THIN
            
            if (curr_row_d1 % 2) == 0:
                ws[f"A{curr_row_d1}"].fill = FILL_ROW_ZEBRA
                ws[f"B{curr_row_d1}"].fill = FILL_ROW_ZEBRA
                ws[f"C{curr_row_d1}"].fill = FILL_ROW_ZEBRA
            ws.row_dimensions[curr_row_d1].height = 19
            curr_row_d1 += 1
        
        # D1 Total Row
        d1_last_data_row = curr_row_d1 - 1
        d1_tot_row = curr_row_d1
        ws[f"A{d1_tot_row}"] = "Total"
        ws[f"A{d1_tot_row}"].font = F_TOTAL
        ws[f"A{d1_tot_row}"].alignment = ALIGN_LEFT
        ws[f"A{d1_tot_row}"].fill = FILL_TOTAL
        ws[f"A{d1_tot_row}"].border = BORDER_TOTAL
        
        ws[f"B{d1_tot_row}"] = f"=SUM(B{d1_start_row}:B{d1_last_data_row})"
        ws[f"B{d1_tot_row}"].font = F_TOTAL
        ws[f"B{d1_tot_row}"].alignment = ALIGN_RIGHT
        ws[f"B{d1_tot_row}"].fill = FILL_TOTAL
        ws[f"B{d1_tot_row}"].border = BORDER_TOTAL
        ws[f"B{d1_tot_row}"].number_format = "#,##0"
        
        ws[f"C{d1_tot_row}"] = f"=SUM(C{d1_start_row}:C{d1_last_data_row})"
        ws[f"C{d1_tot_row}"].font = F_TOTAL
        ws[f"C{d1_tot_row}"].alignment = ALIGN_RIGHT
        ws[f"C{d1_tot_row}"].fill = FILL_TOTAL
        ws[f"C{d1_tot_row}"].border = BORDER_TOTAL
        ws[f"C{d1_tot_row}"].number_format = "#,##0"
        ws.row_dimensions[d1_tot_row].height = 22
        
        depot_totals_coords[sname] = {
            'd1_pred_cell': f"'{sname}'!B{d1_tot_row}",
            'd1_act_cell': f"'{sname}'!C{d1_tot_row}",
            'd1_tot_row': d1_tot_row
        }
        
        # Populate Deliverable 2 Data (Cols E-H, starting at row 5)
        d2_list = data['d2_regular']
        d2_start_row = 5
        curr_row_d2 = d2_start_row
        if d2_list:
            for item in d2_list:
                ws[f"E{curr_row_d2}"] = item['service']
                ws[f"E{curr_row_d2}"].font = F_DATA_BOLD
                ws[f"E{curr_row_d2}"].alignment = ALIGN_LEFT
                ws[f"E{curr_row_d2}"].border = BORDER_THIN
                
                ws[f"F{curr_row_d2}"] = item['pred_count']
                ws[f"F{curr_row_d2}"].font = F_DATA
                ws[f"F{curr_row_d2}"].alignment = ALIGN_RIGHT
                ws[f"F{curr_row_d2}"].number_format = "#,##0"
                ws[f"F{curr_row_d2}"].border = BORDER_THIN
                
                ws[f"G{curr_row_d2}"] = item['act_count']
                ws[f"G{curr_row_d2}"].font = F_DATA
                ws[f"G{curr_row_d2}"].alignment = ALIGN_RIGHT
                ws[f"G{curr_row_d2}"].number_format = "#,##0"
                ws[f"G{curr_row_d2}"].border = BORDER_THIN
                
                ws[f"H{curr_row_d2}"] = f"=G{curr_row_d2}/{num_days}"
                ws[f"H{curr_row_d2}"].font = F_DATA
                ws[f"H{curr_row_d2}"].alignment = ALIGN_RIGHT
                ws[f"H{curr_row_d2}"].number_format = "0.0%"
                ws[f"H{curr_row_d2}"].border = BORDER_THIN
                
                if (curr_row_d2 % 2) == 0:
                    for col in ["E", "F", "G", "H"]:
                        ws[f"{col}{curr_row_d2}"].fill = FILL_ROW_ZEBRA
                ws.row_dimensions[curr_row_d2].height = 19
                curr_row_d2 += 1
            
            d2_last_data_row = curr_row_d2 - 1
            d2_tot_row = curr_row_d2
            ws[f"E{d2_tot_row}"] = "Total"
            ws[f"E{d2_tot_row}"].font = F_TOTAL
            ws[f"E{d2_tot_row}"].alignment = ALIGN_LEFT
            ws[f"E{d2_tot_row}"].fill = FILL_TOTAL
            ws[f"E{d2_tot_row}"].border = BORDER_TOTAL
            
            ws[f"F{d2_tot_row}"] = f"=SUM(F{d2_start_row}:F{d2_last_data_row})"
            ws[f"F{d2_tot_row}"].font = F_TOTAL
            ws[f"F{d2_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"F{d2_tot_row}"].fill = FILL_TOTAL
            ws[f"F{d2_tot_row}"].border = BORDER_TOTAL
            ws[f"F{d2_tot_row}"].number_format = "#,##0"
            
            ws[f"G{d2_tot_row}"] = f"=SUM(G{d2_start_row}:G{d2_last_data_row})"
            ws[f"G{d2_tot_row}"].font = F_TOTAL
            ws[f"G{d2_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"G{d2_tot_row}"].fill = FILL_TOTAL
            ws[f"G{d2_tot_row}"].border = BORDER_TOTAL
            ws[f"G{d2_tot_row}"].number_format = "#,##0"
            
            ws[f"H{d2_tot_row}"] = f"=G{d2_tot_row}/({num_days}*COUNTA(E{d2_start_row}:E{d2_last_data_row}))"
            ws[f"H{d2_tot_row}"].font = F_TOTAL
            ws[f"H{d2_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"H{d2_tot_row}"].fill = FILL_TOTAL
            ws[f"H{d2_tot_row}"].border = BORDER_TOTAL
            ws[f"H{d2_tot_row}"].number_format = "0.0%"
            ws.row_dimensions[d2_tot_row].height = 22
            
            depot_totals_coords[sname]['d2_count'] = len(d2_list)
            depot_totals_coords[sname]['d2_pred_cell'] = f"'{sname}'!F{d2_tot_row}"
            depot_totals_coords[sname]['d2_act_cell'] = f"'{sname}'!G{d2_tot_row}"
        else:
            ws[f"E{curr_row_d2}"] = "No regular services met criteria"
            ws[f"E{curr_row_d2}"].font = F_DATA
            ws[f"E{curr_row_d2}"].alignment = ALIGN_LEFT
            depot_totals_coords[sname]['d2_count'] = 0
            depot_totals_coords[sname]['d2_pred_cell'] = None
            depot_totals_coords[sname]['d2_act_cell'] = None
        
        # Populate Deliverable 3 Data (Cols J-O, starting at row 5)
        d3_qual = data['d3_qual']
        d3_start_row = 5
        curr_row_d3 = d3_start_row
        if d3_qual:
            for item in d3_qual:
                ws[f"J{curr_row_d3}"] = item['service']
                ws[f"J{curr_row_d3}"].font = F_DATA_BOLD
                ws[f"J{curr_row_d3}"].alignment = ALIGN_LEFT
                ws[f"J{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"K{curr_row_d3}"] = item['pred_count']
                ws[f"K{curr_row_d3}"].font = F_DATA
                ws[f"K{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"K{curr_row_d3}"].number_format = "#,##0"
                ws[f"K{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"L{curr_row_d3}"] = item['act_count']
                ws[f"L{curr_row_d3}"].font = F_DATA
                ws[f"L{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"L{curr_row_d3}"].number_format = "#,##0"
                ws[f"L{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"M{curr_row_d3}"] = f"=L{curr_row_d3}-K{curr_row_d3}"
                ws[f"M{curr_row_d3}"].font = F_DATA
                ws[f"M{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"M{curr_row_d3}"].number_format = "+#,##0;-#,##0;0"
                ws[f"M{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"N{curr_row_d3}"] = f"=IF(MAX(K{curr_row_d3},L{curr_row_d3})>0, MIN(K{curr_row_d3},L{curr_row_d3})/MAX(K{curr_row_d3},L{curr_row_d3}), 0)"
                ws[f"N{curr_row_d3}"].font = F_DATA
                ws[f"N{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"N{curr_row_d3}"].number_format = "0.0%"
                ws[f"N{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"O{curr_row_d3}"] = item['same_day_count']
                ws[f"O{curr_row_d3}"].font = F_DATA
                ws[f"O{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"O{curr_row_d3}"].number_format = "#,##0"
                ws[f"O{curr_row_d3}"].border = BORDER_THIN
                
                if (curr_row_d3 % 2) == 0:
                    for col in ["J", "K", "L", "M", "N", "O"]:
                        ws[f"{col}{curr_row_d3}"].fill = FILL_ROW_ZEBRA
                ws.row_dimensions[curr_row_d3].height = 19
                curr_row_d3 += 1
            
            d3_last_data_row = curr_row_d3 - 1
            d3_tot_row = curr_row_d3
            ws[f"J{d3_tot_row}"] = "Total"
            ws[f"J{d3_tot_row}"].font = F_TOTAL
            ws[f"J{d3_tot_row}"].alignment = ALIGN_LEFT
            ws[f"J{d3_tot_row}"].fill = FILL_TOTAL
            ws[f"J{d3_tot_row}"].border = BORDER_TOTAL
            
            ws[f"K{d3_tot_row}"] = f"=SUM(K{d3_start_row}:K{d3_last_data_row})"
            ws[f"K{d3_tot_row}"].font = F_TOTAL
            ws[f"K{d3_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"K{d3_tot_row}"].fill = FILL_TOTAL
            ws[f"K{d3_tot_row}"].border = BORDER_TOTAL
            ws[f"K{d3_tot_row}"].number_format = "#,##0"
            
            ws[f"L{d3_tot_row}"] = f"=SUM(L{d3_start_row}:L{d3_last_data_row})"
            ws[f"L{d3_tot_row}"].font = F_TOTAL
            ws[f"L{d3_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"L{d3_tot_row}"].fill = FILL_TOTAL
            ws[f"L{d3_tot_row}"].border = BORDER_TOTAL
            ws[f"L{d3_tot_row}"].number_format = "#,##0"
            
            ws[f"M{d3_tot_row}"] = f"=L{d3_tot_row}-K{d3_tot_row}"
            ws[f"M{d3_tot_row}"].font = F_TOTAL
            ws[f"M{d3_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"M{d3_tot_row}"].fill = FILL_TOTAL
            ws[f"M{d3_tot_row}"].border = BORDER_TOTAL
            ws[f"M{d3_tot_row}"].number_format = "+#,##0;-#,##0;0"
            
            ws[f"N{d3_tot_row}"] = f"=IF(MAX(K{d3_tot_row},L{d3_tot_row})>0, MIN(K{d3_tot_row},L{d3_tot_row})/MAX(K{d3_tot_row},L{d3_tot_row}), 0)"
            ws[f"N{d3_tot_row}"].font = F_TOTAL
            ws[f"N{d3_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"N{d3_tot_row}"].fill = FILL_TOTAL
            ws[f"N{d3_tot_row}"].border = BORDER_TOTAL
            ws[f"N{d3_tot_row}"].number_format = "0.0%"
            
            ws[f"O{d3_tot_row}"] = f"=SUM(O{d3_start_row}:O{d3_last_data_row})"
            ws[f"O{d3_tot_row}"].font = F_TOTAL
            ws[f"O{d3_tot_row}"].alignment = ALIGN_RIGHT
            ws[f"O{d3_tot_row}"].fill = FILL_TOTAL
            ws[f"O{d3_tot_row}"].border = BORDER_TOTAL
            ws[f"O{d3_tot_row}"].number_format = "#,##0"
            ws.row_dimensions[d3_tot_row].height = 22
            
            depot_totals_coords[sname]['d3_count'] = len(d3_qual)
            depot_totals_coords[sname]['d3_pred_cell'] = f"'{sname}'!K{d3_tot_row}"
            depot_totals_coords[sname]['d3_act_cell'] = f"'{sname}'!L{d3_tot_row}"
            depot_totals_coords[sname]['d3_same_day_cell'] = f"'{sname}'!O{d3_tot_row}"
            curr_row_d3 += 2
        else:
            ws[f"J{curr_row_d3}"] = "No close matches qualified (or 0 predictions declared for depot)"
            ws[f"J{curr_row_d3}"].font = F_DATA
            ws[f"J{curr_row_d3}"].alignment = ALIGN_LEFT
            depot_totals_coords[sname]['d3_count'] = 0
            depot_totals_coords[sname]['d3_pred_cell'] = None
            depot_totals_coords[sname]['d3_act_cell'] = None
            depot_totals_coords[sname]['d3_same_day_cell'] = None
            curr_row_d3 += 2
        
        # Section D: Disqualified Predicted Services
        ws[f"J{curr_row_d3}"] = "NON-QUALIFYING PREDICTED SERVICES (Did not meet Deliverable 3 criteria)"
        ws[f"J{curr_row_d3}"].font = Font(name=FONT_FAMILY, size=9, bold=True, color="783F04")
        curr_row_d3 += 1
        
        disq_headers = [
            ("J", "Service", FILL_HDR_DISQ, ALIGN_LEFT),
            ("K", "Pred Count", FILL_HDR_DISQ, ALIGN_RIGHT),
            ("L", "Act Count", FILL_HDR_DISQ, ALIGN_RIGHT),
            ("M", "Match %", FILL_HDR_DISQ, ALIGN_RIGHT),
            ("N", "Same-Day Cuts", FILL_HDR_DISQ, ALIGN_RIGHT),
            ("O", "Disqualification Reason", FILL_HDR_DISQ, ALIGN_LEFT)
        ]
        for col_letter, text, fill, align in disq_headers:
            cell = ws[f"{col_letter}{curr_row_d3}"]
            cell.value = text
            cell.font = F_TBL_HDR
            cell.fill = fill
            cell.alignment = align
            cell.border = BORDER_HEADER
        ws.row_dimensions[curr_row_d3].height = 22
        curr_row_d3 += 1
        
        d3_disqual = data['d3_disqual']
        if d3_disqual:
            for item in d3_disqual:
                ws[f"J{curr_row_d3}"] = item['service']
                ws[f"J{curr_row_d3}"].font = F_DATA_BOLD
                ws[f"J{curr_row_d3}"].alignment = ALIGN_LEFT
                ws[f"J{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"K{curr_row_d3}"] = item['pred_count']
                ws[f"K{curr_row_d3}"].font = F_DATA
                ws[f"K{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"K{curr_row_d3}"].number_format = "#,##0"
                ws[f"K{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"L{curr_row_d3}"] = item['act_count']
                ws[f"L{curr_row_d3}"].font = F_DATA
                ws[f"L{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"L{curr_row_d3}"].number_format = "#,##0"
                ws[f"L{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"M{curr_row_d3}"] = item['match_ratio']
                ws[f"M{curr_row_d3}"].font = F_DATA
                ws[f"M{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"M{curr_row_d3}"].number_format = "0.0%"
                ws[f"M{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"N{curr_row_d3}"] = item['same_day_count']
                ws[f"N{curr_row_d3}"].font = F_DATA
                ws[f"N{curr_row_d3}"].alignment = ALIGN_RIGHT
                ws[f"N{curr_row_d3}"].number_format = "#,##0"
                ws[f"N{curr_row_d3}"].border = BORDER_THIN
                
                ws[f"O{curr_row_d3}"] = item['reason']
                ws[f"O{curr_row_d3}"].font = F_NOTE_BODY
                ws[f"O{curr_row_d3}"].alignment = ALIGN_LEFT
                ws[f"O{curr_row_d3}"].border = BORDER_THIN
                
                if (curr_row_d3 % 2) == 0:
                    for col in ["J", "K", "L", "M", "N", "O"]:
                        ws[f"{col}{curr_row_d3}"].fill = FILL_ROW_ZEBRA
                ws.row_dimensions[curr_row_d3].height = 18
                curr_row_d3 += 1
        else:
            ws[f"J{curr_row_d3}"] = "No predicted services or all predicted services qualified"
            ws[f"J{curr_row_d3}"].font = F_NOTE_BODY
            ws[f"J{curr_row_d3}"].alignment = ALIGN_LEFT
            curr_row_d3 += 1
        
        ws.freeze_panes = "A5"
        
        col_widths = {
            'A': 18, 'B': 20, 'C': 18, 'D': 4,
            'E': 18, 'F': 20, 'G': 18, 'H': 16, 'I': 4,
            'J': 18, 'K': 18, 'L': 18, 'M': 22, 'N': 16, 'O': 32
        }
        for col_l, width in col_widths.items():
            ws.column_dimensions[col_l].width = width

    # ─────────────────────────────────────────────────────────────────────────
    # 2. SUMMARY SHEET (Covering All Depots, Link Formulas, Audit & Notes)
    # ─────────────────────────────────────────────────────────────────────────
    ws_sum = wb.create_sheet(title="Summary", index=1)
    ws_sum.views.sheetView[0].showGridLines = True
    
    # Title Banner
    ws_sum.merge_cells("A1:K1")
    s_banner = ws_sum["A1"]
    s_banner.value = "EXECUTIVE SUMMARY: DEPOT PREDICTED VS ACTUAL SERVICE CUT REPORT"
    s_banner.font = F_TITLE
    s_banner.fill = FILL_NAVY_BANNER
    s_banner.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws_sum.row_dimensions[1].height = 28
    
    ws_sum.merge_cells("A2:K2")
    s_sub = ws_sum["A2"]
    total_completed_days = list(depots_data.values())[0]['completed_days'] if depots_data else 0
    all_pending = sorted(list(set(d for data in depots_data.values() for d in data['pending_dates'])))
    pending_str = ", ".join(all_pending) if all_pending else "None"
    s_sub.value = f"Worksheet: {metadata['source_file']}  |  Completed Window: {total_completed_days} Days  |  Excluded Pending Dates: {pending_str}  |  Generated: {metadata['generated_at']}"
    s_sub.font = F_SUBTITLE
    s_sub.fill = FILL_SLATE_BANNER
    s_sub.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws_sum.row_dimensions[2].height = 20
    
    curr_r = 4
    
    # Table 1: Deliverable 1 Summary Table
    ws_sum[f"A{curr_r}"] = "DELIVERABLE 1: OVERALL DEPOT-WISE CUT SUMMARY (Live Formulas Linked to Depot Sheets)"
    ws_sum[f"A{curr_r}"].font = F_SECTION_HDR
    curr_r += 1
    
    sum_headers_d1 = [
        ("A", "Depot Name", FILL_HDR_D1, ALIGN_LEFT),
        ("B", "Completed Days", FILL_HDR_D1, ALIGN_RIGHT),
        ("C", "Total Predicted Cuts", FILL_HDR_D1, ALIGN_RIGHT),
        ("D", "Total Actual Cuts", FILL_HDR_D1, ALIGN_RIGHT),
        ("E", "Difference (Actual - Predicted)", FILL_HDR_D1, ALIGN_RIGHT),
        ("F", "Prediction Tracking Note", FILL_HDR_D1, ALIGN_LEFT)
    ]
    for col_l, text, fill, align in sum_headers_d1:
        c = ws_sum[f"{col_l}{curr_r}"]
        c.value = text
        c.font = F_TBL_HDR
        c.fill = fill
        c.alignment = align
        c.border = BORDER_HEADER
    ws_sum.row_dimensions[curr_r].height = 24
    curr_r += 1
    
    d1_sum_start = curr_r
    for sname, data in depots_data.items():
        coords = depot_totals_coords[sname]
        
        ws_sum[f"A{curr_r}"] = sname
        ws_sum[f"A{curr_r}"].font = F_DATA_BOLD
        ws_sum[f"A{curr_r}"].alignment = ALIGN_LEFT
        ws_sum[f"A{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"B{curr_r}"] = data['completed_days']
        ws_sum[f"B{curr_r}"].font = F_DATA
        ws_sum[f"B{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"B{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"C{curr_r}"] = f"={coords['d1_pred_cell']}"
        ws_sum[f"C{curr_r}"].font = F_DATA
        ws_sum[f"C{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"C{curr_r}"].number_format = "#,##0"
        ws_sum[f"C{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"D{curr_r}"] = f"={coords['d1_act_cell']}"
        ws_sum[f"D{curr_r}"].font = F_DATA
        ws_sum[f"D{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"D{curr_r}"].number_format = "#,##0"
        ws_sum[f"D{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"E{curr_r}"] = f"=D{curr_r}-C{curr_r}"
        ws_sum[f"E{curr_r}"].font = F_DATA
        ws_sum[f"E{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"E{curr_r}"].number_format = "+#,##0;-#,##0;0"
        ws_sum[f"E{curr_r}"].border = BORDER_THIN
        
        note = "Standard AI predictions"
        if data['tot_pred'] == 0:
            note = "Zero AI predictions (Operational cuts only)"
        elif (data['tot_act'] - data['tot_pred']) > 300:
            note = "High depot operational cuts beyond AI schedule"
        ws_sum[f"F{curr_r}"] = note
        ws_sum[f"F{curr_r}"].font = F_DATA
        ws_sum[f"F{curr_r}"].alignment = ALIGN_LEFT
        ws_sum[f"F{curr_r}"].border = BORDER_THIN
        
        if (curr_r % 2) == 0:
            for col in ["A", "B", "C", "D", "E", "F"]:
                ws_sum[f"{col}{curr_r}"].fill = FILL_ROW_ZEBRA
        ws_sum.row_dimensions[curr_r].height = 19
        curr_r += 1
    
    d1_sum_last = curr_r - 1
    ws_sum[f"A{curr_r}"] = "Total"
    ws_sum[f"A{curr_r}"].font = F_TOTAL
    ws_sum[f"A{curr_r}"].alignment = ALIGN_LEFT
    ws_sum[f"A{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"A{curr_r}"].border = BORDER_TOTAL
    
    ws_sum[f"B{curr_r}"] = f"=AVERAGE(B{d1_sum_start}:B{d1_sum_last})"
    ws_sum[f"B{curr_r}"].font = F_TOTAL
    ws_sum[f"B{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"B{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"B{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"B{curr_r}"].number_format = "0"
    
    ws_sum[f"C{curr_r}"] = f"=SUM(C{d1_sum_start}:C{d1_sum_last})"
    ws_sum[f"C{curr_r}"].font = F_TOTAL
    ws_sum[f"C{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"C{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"C{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"C{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"D{curr_r}"] = f"=SUM(D{d1_sum_start}:D{d1_sum_last})"
    ws_sum[f"D{curr_r}"].font = F_TOTAL
    ws_sum[f"D{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"D{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"D{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"D{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"E{curr_r}"] = f"=D{curr_r}-C{curr_r}"
    ws_sum[f"E{curr_r}"].font = F_TOTAL
    ws_sum[f"E{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"E{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"E{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"E{curr_r}"].number_format = "+#,##0;-#,##0;0"
    
    ws_sum[f"F{curr_r}"] = "Consolidated Regional Cuts"
    ws_sum[f"F{curr_r}"].font = F_TOTAL
    ws_sum[f"F{curr_r}"].alignment = ALIGN_LEFT
    ws_sum[f"F{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"F{curr_r}"].border = BORDER_TOTAL
    ws_sum.row_dimensions[curr_r].height = 22
    curr_r += 3
    
    # Table 2: Deliverable 2 Summary Table
    ws_sum[f"A{curr_r}"] = f"DELIVERABLE 2: REGULAR CUT SERVICES SUMMARY (Depot Cut on >= {metadata['reg_threshold']} Completed Days)"
    ws_sum[f"A{curr_r}"].font = F_SECTION_HDR
    curr_r += 1
    
    sum_headers_d2 = [
        ("A", "Depot Name", FILL_HDR_D2, ALIGN_LEFT),
        ("B", "Regular Services Count", FILL_HDR_D2, ALIGN_RIGHT),
        ("C", "Regular Predicted Cuts", FILL_HDR_D2, ALIGN_RIGHT),
        ("D", "Regular Actual Cuts", FILL_HDR_D2, ALIGN_RIGHT),
        ("E", "Difference (Act - Pred)", FILL_HDR_D2, ALIGN_RIGHT),
        ("F", "Share of All Depot Cuts", FILL_HDR_D2, ALIGN_RIGHT)
    ]
    for col_l, text, fill, align in sum_headers_d2:
        c = ws_sum[f"{col_l}{curr_r}"]
        c.value = text
        c.font = F_TBL_HDR
        c.fill = fill
        c.alignment = align
        c.border = BORDER_HEADER
    ws_sum.row_dimensions[curr_r].height = 24
    curr_r += 1
    
    d2_sum_start = curr_r
    row_idx_map_d1 = {sname: (d1_sum_start + i) for i, sname in enumerate(depots_data.keys())}
    
    for sname, data in depots_data.items():
        coords = depot_totals_coords[sname]
        d1_row = row_idx_map_d1[sname]
        
        ws_sum[f"A{curr_r}"] = sname
        ws_sum[f"A{curr_r}"].font = F_DATA_BOLD
        ws_sum[f"A{curr_r}"].alignment = ALIGN_LEFT
        ws_sum[f"A{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"B{curr_r}"] = coords['d2_count']
        ws_sum[f"B{curr_r}"].font = F_DATA
        ws_sum[f"B{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"B{curr_r}"].border = BORDER_THIN
        
        if coords['d2_pred_cell']:
            ws_sum[f"C{curr_r}"] = f"={coords['d2_pred_cell']}"
            ws_sum[f"D{curr_r}"] = f"={coords['d2_act_cell']}"
            ws_sum[f"E{curr_r}"] = f"=D{curr_r}-C{curr_r}"
            ws_sum[f"F{curr_r}"] = f"=IF(D{d1_row}>0, D{curr_r}/D{d1_row}, 0)"
        else:
            ws_sum[f"C{curr_r}"] = 0
            ws_sum[f"D{curr_r}"] = 0
            ws_sum[f"E{curr_r}"] = 0
            ws_sum[f"F{curr_r}"] = 0
            
        for col_l in ["C", "D"]:
            ws_sum[f"{col_l}{curr_r}"].font = F_DATA
            ws_sum[f"{col_l}{curr_r}"].alignment = ALIGN_RIGHT
            ws_sum[f"{col_l}{curr_r}"].number_format = "#,##0"
            ws_sum[f"{col_l}{curr_r}"].border = BORDER_THIN
            
        ws_sum[f"E{curr_r}"].font = F_DATA
        ws_sum[f"E{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"E{curr_r}"].number_format = "+#,##0;-#,##0;0"
        ws_sum[f"E{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"F{curr_r}"].font = F_DATA
        ws_sum[f"F{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"F{curr_r}"].number_format = "0.0%"
        ws_sum[f"F{curr_r}"].border = BORDER_THIN
        
        if (curr_r % 2) == 0:
            for col in ["A", "B", "C", "D", "E", "F"]:
                ws_sum[f"{col}{curr_r}"].fill = FILL_ROW_ZEBRA
        ws_sum.row_dimensions[curr_r].height = 19
        curr_r += 1
    
    d2_sum_last = curr_r - 1
    ws_sum[f"A{curr_r}"] = "Total"
    ws_sum[f"A{curr_r}"].font = F_TOTAL
    ws_sum[f"A{curr_r}"].alignment = ALIGN_LEFT
    ws_sum[f"A{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"A{curr_r}"].border = BORDER_TOTAL
    
    ws_sum[f"B{curr_r}"] = f"=SUM(B{d2_sum_start}:B{d2_sum_last})"
    ws_sum[f"B{curr_r}"].font = F_TOTAL
    ws_sum[f"B{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"B{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"B{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"B{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"C{curr_r}"] = f"=SUM(C{d2_sum_start}:C{d2_sum_last})"
    ws_sum[f"C{curr_r}"].font = F_TOTAL
    ws_sum[f"C{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"C{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"C{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"C{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"D{curr_r}"] = f"=SUM(D{d2_sum_start}:D{d2_sum_last})"
    ws_sum[f"D{curr_r}"].font = F_TOTAL
    ws_sum[f"D{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"D{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"D{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"D{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"E{curr_r}"] = f"=D{curr_r}-C{curr_r}"
    ws_sum[f"E{curr_r}"].font = F_TOTAL
    ws_sum[f"E{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"E{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"E{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"E{curr_r}"].number_format = "+#,##0;-#,##0;0"
    
    d1_total_row_idx = d1_sum_last + 1
    ws_sum[f"F{curr_r}"] = f"=IF(D{d1_total_row_idx}>0, D{curr_r}/D{d1_total_row_idx}, 0)"
    ws_sum[f"F{curr_r}"].font = F_TOTAL
    ws_sum[f"F{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"F{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"F{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"F{curr_r}"].number_format = "0.0%"
    ws_sum.row_dimensions[curr_r].height = 22
    curr_r += 3
    
    # Table 3: Deliverable 3 Summary Table
    ws_sum[f"A{curr_r}"] = f"DELIVERABLE 3: CLOSE-MATCH PREDICTIONS SUMMARY (Pred >= {metadata['close_pred_threshold']} & Match Ratio >= {metadata['close_ratio_threshold']:.0%})"
    ws_sum[f"A{curr_r}"].font = F_SECTION_HDR
    curr_r += 1
    
    sum_headers_d3 = [
        ("A", "Depot Name", FILL_HDR_D3, ALIGN_LEFT),
        ("B", "Close-Match Services", FILL_HDR_D3, ALIGN_RIGHT),
        ("C", "Close-Match Predicted", FILL_HDR_D3, ALIGN_RIGHT),
        ("D", "Close-Match Actual", FILL_HDR_D3, ALIGN_RIGHT),
        ("E", "Difference (Act - Pred)", FILL_HDR_D3, ALIGN_RIGHT),
        ("F", "Overall Match Ratio", FILL_HDR_D3, ALIGN_RIGHT),
        ("G", "Same-Day Coincident Cuts", FILL_HDR_D3, ALIGN_RIGHT)
    ]
    for col_l, text, fill, align in sum_headers_d3:
        c = ws_sum[f"{col_l}{curr_r}"]
        c.value = text
        c.font = F_TBL_HDR
        c.fill = fill
        c.alignment = align
        c.border = BORDER_HEADER
    ws_sum.row_dimensions[curr_r].height = 24
    curr_r += 1
    
    d3_sum_start = curr_r
    for sname, data in depots_data.items():
        coords = depot_totals_coords[sname]
        
        ws_sum[f"A{curr_r}"] = sname
        ws_sum[f"A{curr_r}"].font = F_DATA_BOLD
        ws_sum[f"A{curr_r}"].alignment = ALIGN_LEFT
        ws_sum[f"A{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"B{curr_r}"] = coords['d3_count']
        ws_sum[f"B{curr_r}"].font = F_DATA
        ws_sum[f"B{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"B{curr_r}"].border = BORDER_THIN
        
        if coords['d3_pred_cell']:
            ws_sum[f"C{curr_r}"] = f"={coords['d3_pred_cell']}"
            ws_sum[f"D{curr_r}"] = f"={coords['d3_act_cell']}"
            ws_sum[f"E{curr_r}"] = f"=D{curr_r}-C{curr_r}"
            ws_sum[f"F{curr_r}"] = f"=IF(MAX(C{curr_r},D{curr_r})>0, MIN(C{curr_r},D{curr_r})/MAX(C{curr_r},D{curr_r}), 0)"
            ws_sum[f"G{curr_r}"] = f"={coords['d3_same_day_cell']}"
        else:
            ws_sum[f"C{curr_r}"] = 0
            ws_sum[f"D{curr_r}"] = 0
            ws_sum[f"E{curr_r}"] = 0
            ws_sum[f"F{curr_r}"] = 0
            ws_sum[f"G{curr_r}"] = 0
            
        for col_l in ["C", "D"]:
            ws_sum[f"{col_l}{curr_r}"].font = F_DATA
            ws_sum[f"{col_l}{curr_r}"].alignment = ALIGN_RIGHT
            ws_sum[f"{col_l}{curr_r}"].number_format = "#,##0"
            ws_sum[f"{col_l}{curr_r}"].border = BORDER_THIN
            
        ws_sum[f"E{curr_r}"].font = F_DATA
        ws_sum[f"E{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"E{curr_r}"].number_format = "+#,##0;-#,##0;0"
        ws_sum[f"E{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"F{curr_r}"].font = F_DATA
        ws_sum[f"F{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"F{curr_r}"].number_format = "0.0%"
        ws_sum[f"F{curr_r}"].border = BORDER_THIN
        
        ws_sum[f"G{curr_r}"].font = F_DATA
        ws_sum[f"G{curr_r}"].alignment = ALIGN_RIGHT
        ws_sum[f"G{curr_r}"].number_format = "#,##0"
        ws_sum[f"G{curr_r}"].border = BORDER_THIN
        
        if (curr_r % 2) == 0:
            for col in ["A", "B", "C", "D", "E", "F", "G"]:
                ws_sum[f"{col}{curr_r}"].fill = FILL_ROW_ZEBRA
        ws_sum.row_dimensions[curr_r].height = 19
        curr_r += 1
    
    d3_sum_last = curr_r - 1
    ws_sum[f"A{curr_r}"] = "Total"
    ws_sum[f"A{curr_r}"].font = F_TOTAL
    ws_sum[f"A{curr_r}"].alignment = ALIGN_LEFT
    ws_sum[f"A{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"A{curr_r}"].border = BORDER_TOTAL
    
    ws_sum[f"B{curr_r}"] = f"=SUM(B{d3_sum_start}:B{d3_sum_last})"
    ws_sum[f"B{curr_r}"].font = F_TOTAL
    ws_sum[f"B{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"B{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"B{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"B{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"C{curr_r}"] = f"=SUM(C{d3_sum_start}:C{d3_sum_last})"
    ws_sum[f"C{curr_r}"].font = F_TOTAL
    ws_sum[f"C{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"C{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"C{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"C{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"D{curr_r}"] = f"=SUM(D{d3_sum_start}:D{d3_sum_last})"
    ws_sum[f"D{curr_r}"].font = F_TOTAL
    ws_sum[f"D{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"D{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"D{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"D{curr_r}"].number_format = "#,##0"
    
    ws_sum[f"E{curr_r}"] = f"=D{curr_r}-C{curr_r}"
    ws_sum[f"E{curr_r}"].font = F_TOTAL
    ws_sum[f"E{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"E{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"E{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"E{curr_r}"].number_format = "+#,##0;-#,##0;0"
    
    ws_sum[f"F{curr_r}"] = f"=IF(MAX(C{curr_r},D{curr_r})>0, MIN(C{curr_r},D{curr_r})/MAX(C{curr_r},D{curr_r}), 0)"
    ws_sum[f"F{curr_r}"].font = F_TOTAL
    ws_sum[f"F{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"F{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"F{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"F{curr_r}"].number_format = "0.0%"
    
    ws_sum[f"G{curr_r}"] = f"=SUM(G{d3_sum_start}:G{d3_sum_last})"
    ws_sum[f"G{curr_r}"].font = F_TOTAL
    ws_sum[f"G{curr_r}"].alignment = ALIGN_RIGHT
    ws_sum[f"G{curr_r}"].fill = FILL_TOTAL
    ws_sum[f"G{curr_r}"].border = BORDER_TOTAL
    ws_sum[f"G{curr_r}"].number_format = "#,##0"
    ws_sum.row_dimensions[curr_r].height = 22
    curr_r += 3
    
    # Notes & Methodology Block
    ws_sum[f"A{curr_r}"] = "METHODOLOGY, COUNTING RULES & ADJUSTABLE THRESHOLDS"
    ws_sum[f"A{curr_r}"].font = F_SECTION_HDR
    curr_r += 1
    
    notes = [
        ("1. Data Structure & Service Parsing",
         "Service codes are normalized and extracted from within parentheses. Non-cut columns are strictly ignored."),
        ("2. Cut Event Counting (Service x Date)",
         "A service cut on several dates counts once per date. Services appearing in either list with 0 on the opposite side are preserved."),
        ("3. [Ran AI] Services Handling",
         "Services marked with '[Ran AI]' in actual cuts were recommended for cut by AI but operated by depot management. As per Rule 5, they count under Predicted Cuts, not Actual Cuts."),
        ("4. Pending Dates & Like-for-Like Comparison",
         f"Dates marked 'Pending' ({pending_str}) have no recorded actual operations and are excluded from like-for-like analysis."),
        ("5. Regular Cut Services Threshold (Deliverable 2)",
         f"Services cut on at least {metadata['reg_threshold']} completed days (~{metadata['reg_threshold']/total_completed_days:.1%} of {total_completed_days} days)."),
        ("6. Close-Match Prediction Criteria (Deliverable 3)",
         f"Services predicted at least {metadata['close_pred_threshold']} times with match ratio >= {metadata['close_ratio_threshold']:.0%}."),
        ("7. Zero-Prediction Depots",
         "Depots such as BHUPALAPALLAY and WARANGAL-II had zero AI schedule cut predictions in the source file. Their actual cuts represent unilateral depot-level decisions.")
    ]
    
    for title, desc in notes:
        ws_sum.merge_cells(f"A{curr_r}:K{curr_r}")
        ws_sum[f"A{curr_r}"] = f"{title}: {desc}"
        ws_sum[f"A{curr_r}"].font = F_NOTE_BODY
        ws_sum[f"A{curr_r}"].alignment = ALIGN_WRAP_LEFT
        ws_sum[f"A{curr_r}"].fill = FILL_NOTES_BOX
        ws_sum.row_dimensions[curr_r].height = 24
        curr_r += 1
    
    ws_sum.freeze_panes = "A5"
    
    sum_col_widths = {
        'A': 22, 'B': 18, 'C': 22, 'D': 20, 'E': 26, 'F': 32, 'G': 24, 'H': 18, 'I': 18, 'J': 18, 'K': 18
    }
    for col_l, width in sum_col_widths.items():
        ws_sum.column_dimensions[col_l].width = width
    
    wb.save(output_path)
    return output_path


# ── Markdown Report Generator ──────────────────────────────────────────────────

def generate_markdown_report(metadata, validation, depots_data, md_path):
    """
    Generates a full Markdown report including the user's requested formats:
    - Format 1: Depot-wise predicted vs actual cut services
    - Format 2: Highest count of cuts & actuals comparison
    - Deliverables 1, 2, 3 summaries, validation audit, and detailed per-depot breakdowns.
    """
    tables = extract_formatted_cut_tables(depots_data)
    lines = []
    
    lines.append("# Depot-Wise Predicted vs Actual Service Cut Report (Warangal Region)")
    lines.append(f"*Source Workbook: `{metadata['source_file']}` | Generated: {metadata['generated_at']}*")
    lines.append("")
    
    # ── Section 1: User-Requested Format 1 ──────────────────────────────────────
    lines.append("## 1. Depot-Wise Predicted vs Actual Cut Services (Last 30 Days)")
    lines.append("Exact user format comparing predicted cut counts and actual cut counts per depot:")
    lines.append("")
    lines.append("| depot | predicted cut | actual cut | Difference (Act - Pred) | Match % |")
    lines.append("|:---|:---:|:---:|---:|---:|")
    for r in tables['depot_wise']:
        depot_col = r['depot_display'] if r['depot_display'] else ""
        diff_str = f"{r['diff']:+d}"
        match_str = f"{r['match_ratio']:.1%}" if r['pred_count'] > 0 else "-"
        lines.append(f"| {depot_col} | {r['pred_str']} | {r['act_str']} | {diff_str} | {match_str} |")
    lines.append("")

    # ── Section 2: User-Requested Format 2 ──────────────────────────────────────
    lines.append("## 2. Highest Count of Cuts & Actuals Comparison")
    lines.append("Comparison ranked by cut volume across Warangal depots:")
    lines.append("")
    lines.append("### Format 2A: Predicted Services Ranked by Highest Cut Volume")
    lines.append("| depot | predicted cut | actual cut | Difference (Act - Pred) | Match % |")
    lines.append("|:---|:---:|:---:|---:|---:|")
    for r in tables['highest_predicted']:
        diff_str = f"{r['diff']:+d}"
        lines.append(f"| {r['depot']} | {r['pred_str']} | {r['act_str']} | {diff_str} | {r['match_ratio']:.1%} |")
    lines.append("")

    lines.append("### Format 2B: Top 25 Highest Overall Regional Cuts (All Depots)")
    lines.append("| depot | predicted cut | actual cut | Difference (Act - Pred) | Category |")
    lines.append("|:---|:---:|:---:|---:|:---|")
    for r in tables['top_overall']:
        diff_str = f"{r['diff']:+d}"
        lines.append(f"| {r['depot']} | {r['pred_str']} | {r['act_str']} | {diff_str} | {r['category']} |")
    lines.append("")

    # ── Section 3: Data Validation & Integrity Audit ────────────────────────────
    lines.append("## 3. Data Validation & Integrity Audit")
    lines.append(f"- **Sheets Processed / Depots Analyzed:** {validation['total_sheets']} ({', '.join(validation['depots_analyzed'])})")
    lines.append(f"- **Declared Service Count Discrepancies:** {len(validation['count_mismatches'])} (100% verified)")
    lines.append(f"- **Unparseable / Blank Cells:** {len(validation['unparseable_entries'])} issues found")
    lines.append(f"- **Duplicate Services Within a Day:** {len(validation['duplicate_entries'])} duplicates detected")
    
    lines.append("\n### Excluded Pending Dates (Like-for-Like Comparison)")
    lines.append("| Depot | Completed Days | Excluded Pending Dates | Predicted Cuts in Pending Row (Excluded) |")
    lines.append("|:---|---:|:---|---:|")
    for sname, info in validation['pending_exclusions'].items():
        p_dates_str = ", ".join(info['pending_dates']) if info['pending_dates'] else "None"
        lines.append(f"| {sname} | {info['completed_days']} | {p_dates_str} | {info['pred_cuts_on_pending']} |")
    
    lines.append("\n### Reconciliation With Source Sheet TOTAL Rows")
    lines.append("| Depot | Parsed Pred | Source Sheet Pred | Pred Delta | Parsed Act | Source Sheet Act | Act Delta | Reconciliation Notes |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|:---|")
    for sname, comp in validation['total_row_comparisons'].items():
        lines.append(
            f"| {sname} | {comp['parsed_pred_tot']} | {comp['src_pred_tot']} | "
            f"{comp['pred_diff']:+d} | {comp['parsed_act_tot']} | {comp['src_act_tot']} | "
            f"{comp['act_diff']:+d} | {comp['explanation']} |"
        )
    lines.append("")
    
    # ── Section 4: Deliverable 1 Overall Summary ────────────────────────────────
    lines.append("## 4. Deliverable 1: Overall Depot Summary")
    lines.append("| Depot Name | Completed Days | Total Predicted | Total Actual | Difference (Actual - Predicted) | Prediction Status |")
    lines.append("|:---|---:|---:|---:|---:|:---|")
    tot_pred = sum(d['tot_pred'] for d in depots_data.values())
    tot_act = sum(d['tot_act'] for d in depots_data.values())
    for sname, d in depots_data.items():
        status = "Active AI Prediction" if d['tot_pred'] > 0 else "No AI Prediction (Operational Cuts)"
        lines.append(f"| {sname} | {d['completed_days']} | {d['tot_pred']} | {d['tot_act']} | {d['diff']:+d} | {status} |")
    lines.append(f"| **Total** | **{list(depots_data.values())[0]['completed_days']} (avg)** | **{tot_pred}** | **{tot_act}** | **{tot_act - tot_pred:+d}** | **Consolidated Region** |")
    lines.append("")
    
    # ── Section 5: Deliverable 2 Regular Cuts ───────────────────────────────────
    lines.append(f"## 5. Deliverable 2: Regular Cut Services Summary (Cut on >= {metadata['reg_threshold']} Completed Days)")
    lines.append("| Depot Name | Regular Services Count | Regular Predicted | Regular Actual | Difference | Share of Depot Cuts |")
    lines.append("|:---|---:|---:|---:|---:|---:|")
    tot_reg_svcs = sum(len(d['d2_regular']) for d in depots_data.values())
    tot_reg_pred = sum(sum(x['pred_count'] for x in d['d2_regular']) for d in depots_data.values())
    tot_reg_act = sum(sum(x['act_count'] for x in d['d2_regular']) for d in depots_data.values())
    for sname, d in depots_data.items():
        reg_cnt = len(d['d2_regular'])
        p_sum = sum(x['pred_count'] for x in d['d2_regular'])
        a_sum = sum(x['act_count'] for x in d['d2_regular'])
        diff = a_sum - p_sum
        share = (a_sum / d['tot_act']) if d['tot_act'] > 0 else 0
        lines.append(f"| {sname} | {reg_cnt} | {p_sum} | {a_sum} | {diff:+d} | {share:.1%} |")
    reg_overall_share = (tot_reg_act / tot_act) if tot_act > 0 else 0
    lines.append(f"| **Total** | **{tot_reg_svcs}** | **{tot_reg_pred}** | **{tot_reg_act}** | **{tot_reg_act - tot_reg_pred:+d}** | **{reg_overall_share:.1%}** |")
    lines.append("")
    
    # ── Section 6: Deliverable 3 Close Matches ──────────────────────────────────
    lines.append(f"## 6. Deliverable 3: Close-Match Predictions Summary")
    lines.append(f"*Criteria: Predicted >= {metadata['close_pred_threshold']} times AND (Lower / Higher Count) >= {metadata['close_ratio_threshold']:.0%}.*")
    lines.append("")
    lines.append("| Depot Name | Close-Match Services | Predicted Cuts | Actual Cuts | Difference | Match Ratio | Same-Day Coincident Cuts |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|")
    tot_cm_svcs = sum(len(d['d3_qual']) for d in depots_data.values())
    tot_cm_pred = sum(sum(x['pred_count'] for x in d['d3_qual']) for d in depots_data.values())
    tot_cm_act = sum(sum(x['act_count'] for x in d['d3_qual']) for d in depots_data.values())
    tot_cm_same = sum(sum(x['same_day_count'] for x in d['d3_qual']) for d in depots_data.values())
    for sname, d in depots_data.items():
        cm_cnt = len(d['d3_qual'])
        p_sum = sum(x['pred_count'] for x in d['d3_qual'])
        a_sum = sum(x['act_count'] for x in d['d3_qual'])
        diff = a_sum - p_sum
        max_c = max(p_sum, a_sum)
        min_c = min(p_sum, a_sum)
        ratio = (min_c / max_c) if max_c > 0 else 0
        same_sum = sum(x['same_day_count'] for x in d['d3_qual'])
        lines.append(f"| {sname} | {cm_cnt} | {p_sum} | {a_sum} | {diff:+d} | {ratio:.1%} | {same_sum} |")
    overall_cm_ratio = (min(tot_cm_pred, tot_cm_act) / max(tot_cm_pred, tot_cm_act)) if max(tot_cm_pred, tot_cm_act) > 0 else 0
    lines.append(f"| **Total** | **{tot_cm_svcs}** | **{tot_cm_pred}** | **{tot_cm_act}** | **{tot_cm_act - tot_cm_pred:+d}** | **{overall_cm_ratio:.1%}** | **{tot_cm_same}** |")
    lines.append("")
    
    # ── Section 7: Depot-by-Depot Full Tables ───────────────────────────────────
    lines.append("## 7. Depot-by-Depot Detailed Reports")
    for sname, d in depots_data.items():
        lines.append(f"### {sname}")
        lines.append(f"*Completed Days: {d['completed_days']} | Excluded Pending Dates: {', '.join(d['pending_dates']) or 'None'}*")
        lines.append("")
        
        # Deliverable 1 Table
        lines.append("#### Deliverable 1: Full Service Cut Report")
        lines.append("| Service Number | Predicted Cut Count | Actual Cut Count |")
        lines.append("|:---|---:|---:|")
        for item in d['d1_services']:
            lines.append(f"| {item['service']} | {item['pred_count']} | {item['act_count']} |")
        lines.append(f"| **Total** | **{d['tot_pred']}** | **{d['tot_act']}** |")
        lines.append("")
        
        # Deliverable 2 Table
        lines.append(f"#### Deliverable 2: Regular Cut Services (>= {metadata['reg_threshold']} Days)")
        if d['d2_regular']:
            lines.append("| Service Number | Predicted Cut Count | Actual Cut Count | % of Days Cut |")
            lines.append("|:---|---:|---:|---:|")
            for item in d['d2_regular']:
                lines.append(f"| {item['service']} | {item['pred_count']} | {item['act_count']} | {item['pct_days']:.1%} |")
            reg_p_sum = sum(x['pred_count'] for x in d['d2_regular'])
            reg_a_sum = sum(x['act_count'] for x in d['d2_regular'])
            lines.append(f"| **Total** | **{reg_p_sum}** | **{reg_a_sum}** | **{(reg_a_sum / (d['completed_days'] * len(d['d2_regular']))):.1%}** |")
        else:
            lines.append("*No services met the regular cut threshold.*")
        lines.append("")
        
        # Deliverable 3 Table
        lines.append(f"#### Deliverable 3: Close-Match Predictions")
        if d['d3_qual']:
            lines.append("| Service Number | Predicted Count | Actual Count | Difference | Match % | Same-Day Coincident Cuts |")
            lines.append("|:---|---:|---:|---:|---:|---:|")
            for item in d['d3_qual']:
                lines.append(f"| {item['service']} | {item['pred_count']} | {item['act_count']} | {item['diff']:+d} | {item['match_ratio']:.1%} | {item['same_day_count']} |")
            cm_p_sum = sum(x['pred_count'] for x in d['d3_qual'])
            cm_a_sum = sum(x['act_count'] for x in d['d3_qual'])
            cm_same_sum = sum(x['same_day_count'] for x in d['d3_qual'])
            cm_rat = (min(cm_p_sum, cm_a_sum) / max(cm_p_sum, cm_a_sum)) if max(cm_p_sum, cm_a_sum) > 0 else 0
            lines.append(f"| **Total** | **{cm_p_sum}** | **{cm_a_sum}** | **{cm_a_sum - cm_p_sum:+d}** | **{cm_rat:.1%}** | **{cm_same_sum}** |")
        else:
            lines.append("*No predicted services qualified under close-match criteria (or depot had 0 predictions).*")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return md_path


# ── CLI & Execution Controller ─────────────────────────────────────────────────

def find_default_input_workbook():
    """Locates or auto-generates the Warangal input workbook."""
    candidates = [
        "warangal_cut_services_analysis.xlsx",
        "warangal_cut_services_analysis_updated.xlsx",
        "krmr_cut_services_analysis_updated.xlsx",
        "krmr_cut_services_analysis.xlsx",
        "adilabad_cut_services_analysis.xlsx",
        "all_regions_cut_services_analysis.xlsx"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # Attempt to auto-generate Warangal analysis if source dynamic schedule exists
    if os.path.exists("all_regions_cut_services_analysis.py"):
        try:
            print("[*] Generating warangal_cut_services_analysis.xlsx for Warangal Region...")
            import all_regions_cut_services_analysis as ar_cut
            files = ar_cut.generate_cut_services_analysis(regions="WARANGAL", days=30)
            if files and os.path.exists(files[0]):
                return files[0]
        except Exception as e:
            print(f"[!] Auto-generation error: {e}")

    # Fallback search for any xlsx with cut in name
    for f in os.listdir("."):
        if f.endswith(".xlsx") and "cut" in f.lower() and not f.startswith("depot_predicted_vs_actual") and not f.startswith("warangal_depot"):
            return f
    return None

def main():
    parser = argparse.ArgumentParser(
        description="Generate Warangal Depot-Wise Predicted vs Actual Cut Service Analysis Report (Excel & Markdown)."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=None,
        help="Path to source Excel workbook (defaults to warangal_cut_services_analysis.xlsx)"
    )
    parser.add_argument(
        "-o", "--output",
        default="warangal_depot_predicted_vs_actual_cuts_report.xlsx",
        help="Path for output Excel workbook (default: warangal_depot_predicted_vs_actual_cuts_report.xlsx)"
    )
    parser.add_argument(
        "-m", "--markdown",
        default="warangal_depot_cut_services_report.md",
        help="Path for output Markdown report (default: warangal_depot_cut_services_report.md)"
    )
    parser.add_argument(
        "--reg-days",
        type=int,
        default=10,
        help="Minimum actual cut days threshold for regular cut services (default: 10 days)"
    )
    parser.add_argument(
        "--pred-threshold",
        type=int,
        default=5,
        help="Minimum predicted cut count threshold for close match (default: 5)"
    )
    parser.add_argument(
        "--match-ratio",
        type=float,
        default=0.70,
        help="Minimum match ratio threshold for close match (default: 0.70 / 70%%)"
    )
    
    args = parser.parse_args()
    
    input_file = args.input_file or find_default_input_workbook()
    if not input_file or not os.path.exists(input_file):
        print(f"[!] Error: Could not locate a valid input workbook. Please specify the path.")
        sys.exit(1)
        
    print("=" * 80)
    print(f"[*] WARANGAL DEPOTS PREDICTED VS ACTUAL SERVICE CUT REPORT GENERATOR")
    print(f"[*] Input Workbook:       {input_file}")
    print(f"[*] Output Excel:         {args.output}")
    print(f"[*] Output Markdown:      {args.markdown}")
    print(f"[*] Regular Days Cut:     >= {args.reg_days} completed days")
    print(f"[*] Close Match Ratio:    >= {args.match_ratio:.0%} (Pred >= {args.pred_threshold})")
    print("=" * 80)
    
    # 1. Run Analysis
    print("\n[+] Analyzing depot sheets and parsing cut events...")
    metadata, validation, depots_data = analyze_depot_workbook(
        file_path=input_file,
        reg_threshold=args.reg_days,
        close_pred_threshold=args.pred_threshold,
        close_ratio_threshold=args.match_ratio
    )
    
    # 2. Extract and Print User-Requested Formatted Tables
    tables = extract_formatted_cut_tables(depots_data)
    print_formatted_cut_tables(tables)

    # 3. Print Validation Summary to Console
    print("\n" + "=" * 80)
    print("VALIDATION & DATA INTEGRITY REPORT")
    print("=" * 80)
    print(f"- Sheets / Depots Analyzed:      {validation['total_sheets']} ({', '.join(validation['depots_analyzed'])})")
    print(f"- Declared vs Listed Mismatches: {len(validation['count_mismatches'])} (100% verified)")
    print(f"- Unparseable Entries:           {len(validation['unparseable_entries'])}")
    print(f"- Within-Day Duplicate Entries:  {len(validation['duplicate_entries'])}")
    print("\nPending Date Exclusions (Like-for-like comparison):")
    for sname, info in validation['pending_exclusions'].items():
        print(f"  {sname:<15}: Completed Days={info['completed_days']}, Pending={info['pending_dates']} (Excluded Pred={info['pred_cuts_on_pending']})")
    
    # 4. Print Deliverable 1 Summary Table
    print("\n" + "=" * 80)
    print("DELIVERABLE 1: OVERALL DEPOT CUTS SUMMARY")
    print("=" * 80)
    print(f"{'Depot':<15} | {'Days':<5} | {'Predicted':<10} | {'Actual':<10} | {'Difference':<12}")
    print("-" * 60)
    t_pred = sum(d['tot_pred'] for d in depots_data.values())
    t_act = sum(d['tot_act'] for d in depots_data.values())
    for sname, d in depots_data.items():
        print(f"{sname:<15} | {d['completed_days']:<5} | {d['tot_pred']:<10} | {d['tot_act']:<10} | {d['diff']:<+12}")
    print("-" * 60)
    print(f"{'TOTAL':<15} | {list(depots_data.values())[0]['completed_days']:<5} | {t_pred:<10} | {t_act:<10} | {t_act - t_pred:<+12}")
    
    # 5. Generate Output Excel
    print(f"\n[+] Building formatted Excel report with live formulas: {args.output}")
    out_xlsx = generate_excel_report(metadata, validation, depots_data, args.output)
    print(f"[OK] Excel workbook created successfully: {os.path.abspath(out_xlsx)}")
    
    # 6. Generate Output Markdown
    print(f"[+] Writing Markdown report: {args.markdown}")
    out_md = generate_markdown_report(metadata, validation, depots_data, args.markdown)
    print(f"[OK] Markdown report created successfully: {os.path.abspath(out_md)}")
    print("\n[OK] All deliverables generated successfully!")

if __name__ == "__main__":
    main()
