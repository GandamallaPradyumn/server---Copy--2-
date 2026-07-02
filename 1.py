"""
TGSRTC — Day Service Report Transformer
Run with: streamlit run transform_app.py
"""

import os
import io
import re
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="TGSRTC Report Transformer", layout="wide")
st.title("TGSRTC — Day Service Report Transformer")

# ── Inbound folder ─────────────────────────────────────────────────────────
INBOUND_FOLDER = r"C:\Users\prady\OneDrive\Desktop\server\dynamic_scheduling_master\data\inbound_daily"

# ── Service Master path ────────────────────────────────────────────────────
SERVICE_MASTER_FILE = r"C:\Users\prady\OneDrive\Desktop\server\dynamic_scheduling_master\data\master\service_master.csv"

# ── Depot mapping — hardcoded (incorrect name in report → correct name) ───
DEPOT_LOOKUP = {
    "ACHAMPET":         "ACHAMPET",
    "ADILABAD":         "ADILABAD",
    "ARMOOR":           "ARMOOR",
    "ASIFABAD":         "ASIFABAD",
    "BANDLAGUDA":       "BANDLAGUDA",
    "BANSWADA":         "BANSWADA",
    "BARKATPURA":       "BARKATPURA",
    "BHADRACHALAM":     "BADRACHALAM",
    "BHAINSA":          "BHAINSA",
    "BHEL":             "BHEL",
    "BHUPALPALLY":      "BHUPALAPALLAY",
    "BODHAN":           "BODHAN",
    "CHENGICHERLA":     "CHENGICHERLA",
    "CONTONMENT":       "CONTONMENT",
    "DEVARAKONDA":      "DEVARAKONDA",
    "DILSUKHNAGAR":     "DILSHUKNAGAR",
    "DUBBAKA":          "DUBBAKA",
    "FALAKNUMA":        "FALAKNUMA",
    "FAROOQNAGAR":      "FAROOQNAGAR",
    "G.D.KHANI":        "GODAVARIKHANI",
    "GADWAL":           "GADWAL",
    "GAJWEL PRAGNAPUR": "GWL-PRGPR",
    "HAKIMPET":         "HAKIMPET",
    "HANUMAKONDA":      "HANAMKONDA",
    "HAYATNAGAR-1":     "HAYATHNAGAR-I",
    "HAYATNAGAR-2":     "HAYATHNAGAR-II",
    "HCU DEPOT":        "HCU",
    "HUSNABAD":         "HUSNABAD",
    "HUZURABAD":        "HUZURABAD",
    "HYDERABAD-I":      "HYDERABAD-I",
    "HYDERABAD-II":     "HYDERABAD-II",
    "IBRAHIMPATNAM":    "IBRAHIMPATNAM",
    "JAGTIAL":          "JAGITYAL",
    "JANAGAON":         "JANGAON",
    "JEEDIMATLA":       "JEEDIMETLA",
    "KACHIGUDA":        "KACHEGUDA",
    "KALVAKURTHY":      "KALVAKURTHY",
    "KAMAREDDI":        "KAMAREDDY",
    "KARIMNAGAR-1":     "KARIMNAGAR-I",
    "KARIMNAGAR-2":     "KARIMNAGAR-II",
    "KHAMMAM":          "KHAMMAM",
    "KODAD":            "KODAD",
    "KOLLAPUR":         "KOLLAPUR",
    "KORUTLA":          "KORUTLA",
    "KOSGI":            "KOSGI",
    "KOTHAGUDAM":       "KOTHAGUDEM",
    "KUKATPALLI":       "KUKATPALLY",
    "KUSHAIGUDA":       "KUSHAIGUDA",
    "MADIRA":           "MADHIRA",
    "MAHABOOBABAD":     "MAHABOOBABAD",
    "MAHABOOBNAGAR":    "MAHABOOBNAGAR",
    "MAHESWARAM":       "MAHESWARAM",
    "MANCHIRYAL":       "MANCHERIAL",
    "MANTHANI":         "MANTHANI",
    "MANUGUR":          "MANUGURU",
    "MEDAK":            "MEDAK",
    "MEDCHAL":          "MEDCHAL",
    "MEHDIPATNAM":      "MEHDIPATNAM",
    "METPALLY":         "METPALLY",
    "MIDHANI":          "MIDHANI",
    "MIRYALAGUDA":      "MIRYALAGUDA",
    "MIYAPUR":          "MIYAPUR-I",
    "MIYAPUR-2":        "MIYAPUR-II",
    "MUSHIRABAD-2":     "MUSHIRABAD",
    "NAGARKURNOOL":     "NAGARKURNOOL",
    "NALGONDA":         "NALGONDA",
    "NARASAMPET":       "NARSAMPET",
    "NARAYANKED":       "NARAYANKHEDA",
    "NARAYANPET":       "NARAYANPET",
    "NARKETPALLY":      "NARKATPALLY",
    "NARSAPUR":         "NARSAPUR",
    "NIRMAL":           "NIRMAL",
    "NIZAMABAD-I":      "NIZAMABAD-I",
    "NIZAMABAD-II":     "NIZAMABAD-II",
    "PARIGI":           "PARGI",
    "PARKAL":           "PARKAL",
    "PICKET":           "PICKET",
    "RAJENDERNAGAR":    "RAJENDRANAGAR",
    "RANIGUNJ-I":       "RANIGUNJ-I",
    "SANGAREDDY":       "SANGAREDDY",
    "SATTUPALLI":       "SATTUPALLY",
    "SHADNAGAR":        "SHADNAGAR",
    "SIDDIPET":         "SIDDIPET",
    "SIRCILLA":         "SIRCILLA",
    "SURYAPET":         "SURYAPET",
    "TANDUR":           "TANDUR",
    "THORROORU":        "THORROR",
    "UPPAL":            "UPPAL",
    "UTNOOR":           "UTNOOR",
    "VEMULAWADA":       "VEMULAWADA",
    "VIKARABAD":        "VIKARABAD",
    "WANAPARTHI":       "WANAPARTHI",
    "WARANGAL-I":       "WARANGAL-I",
    "WARANGAL-II":      "WARANGAL-II",
    "YADAGIRIGUTTA":    "YADAGIRIGUTTA",
    "YELLANDU":         "YELLANDU",
    "ZAHIRABAD":        "ZAHIRABAD",
}

# ── Allowed depots ─────────────────────────────────────────────────────────
ALLOWED_DEPOTS = {
    "ARMOOR", "BANSWADA", "BHUPALAPALLAY", "BODHAN", "CONTONMENT",
    "HAKIMPET", "HANAMKONDA", "HYDERABAD-I", "HYDERABAD-II", "IBRAHIMPATNAM",
    "JANGAON", "KARIMNAGAR-I", "KUKATPALLY", "MAHABOOBABAD", "NARSAMPET",
    "NIZAMABAD-I", "PARKAL", "THORROR", "WARANGAL-I", "WARANGAL-II",
}
# ══════════════════════════════════════════════════════════════════════════

def apply_depot_lookup(series: pd.Series) -> pd.Series:
    return series.str.strip().str.upper().map(lambda d: DEPOT_LOOKUP.get(d, d))


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False).encode("utf-8")


def derive_filename_service(df: pd.DataFrame) -> str:
    unique_dates = pd.to_datetime(df["date"], errors="coerce").dt.normalize().dropna().unique()
    if len(unique_dates) == 1:
        return f"ops_daily_service_{pd.Timestamp(unique_dates[0]).strftime('%Y-%m-%d')}.csv"
    return "ops_daily_service.csv"


def derive_filename_daily(df: pd.DataFrame) -> str:
    unique_dates = pd.to_datetime(df["date"], errors="coerce").dt.normalize().dropna().unique()
    if len(unique_dates) == 1:
        return f"ops_daily_{pd.Timestamp(unique_dates[0]).strftime('%Y-%m-%d')}.csv"
    return "ops_daily.csv"


def is_service_8000_to_8999(service_num):
    try:
        num = int(str(service_num).strip())
        return 8000 <= num <= 8999
    except (ValueError, TypeError):
        return False


# ══════════════════════════════════════════════════════════════════════════
# FILE 1 — Day Service Report (.xlsx / sheet001.htm)
# ══════════════════════════════════════════════════════════════════════════

def read_day_service_report(uploaded_file) -> pd.DataFrame:
    uploaded_file.seek(0)
    content = uploaded_file.read()

    try:
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        if not df.empty:
            return df
    except Exception:
        pass

    try:
        html_str = content.decode("utf-8")
    except UnicodeDecodeError:
        html_str = content.decode("latin-1")

    html_clean = re.sub(r' xmlns(?::\w+)?="[^"]*"', "", html_str)
    html_clean = re.sub(r"<html[^>]*>", "<html>", html_clean, count=1, flags=re.IGNORECASE)
    soup = BeautifulSoup(html_clean, "html.parser")
    rows = soup.find_all("tr")

    if rows:
        data = [[c.get_text(strip=True) for c in row.find_all(["th", "td"])] for row in rows]
        data = [r for r in data if any(c.strip() for c in r)]
        if data:
            df = pd.DataFrame(data[1:], columns=data[0])
            df = df.replace("", pd.NA).dropna(how="all").reset_index(drop=True)
            return df

    raise ValueError(
        "Could not read the file. Upload a .xlsx (Save As from Excel) or sheet001.htm."
    )


def transform_day_service(raw_df: pd.DataFrame, sm_df) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """
    Pipeline for Day Service Report.
    Returns: (transformed_df, stats_dict, duplicate_rows_df)
    """
    stats = {}
    df = raw_df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    df = df.rename(columns={
        "Depot":     "depot",
        "Date":      "date",
        "Ser No":    "service_number",
        "OPD Kms":   "actual_kms",
        "Engs":      "revenue",
        "Seat Cap":  "_seat_cap",
        "Occupancy": "_occupancy_raw",
    })

    keep = ["depot", "date", "service_number", "actual_kms", "revenue", "_seat_cap", "_occupancy_raw"]
    df = df[[c for c in keep if c in df.columns]].copy()
    for col in ["actual_kms", "revenue", "_seat_cap", "_occupancy_raw"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    stats["rows_after_load"] = len(df)

    # Fix depot names
    before = df["depot"].str.strip().str.upper().unique()
    df["depot"] = apply_depot_lookup(df["depot"])
    stats["depots_remapped"] = int(sum(1 for d in before if DEPOT_LOOKUP.get(d, d) != d))

    # Filter to allowed depots only
    before_filter = len(df)
    df = df[df["depot"].isin(ALLOWED_DEPOTS)].copy()
    stats["rows_filtered_out"] = before_filter - len(df)

    # Filter out service numbers 8000-8999
    before_8000_filter = len(df)
    df = df[~df["service_number"].apply(is_service_8000_to_8999)].copy()
    stats["service_8000_8999_removed"] = before_8000_filter - len(df)

    # Derived columns
    df["seat_kms"]        = df["actual_kms"] * df["_seat_cap"]
    df["occupancy_ratio"] = (df["_occupancy_raw"] / 100).fillna(0)
    df["passenger_kms"]   = df["seat_kms"] * df["occupancy_ratio"]

    # Blank OR > 3
    mask = df["occupancy_ratio"] > 3
    df.loc[mask, "occupancy_ratio"] = None
    df.loc[mask, "passenger_kms"]   = None
    stats["blanked_high_or"] = int(mask.sum())

    df = df.drop(columns=["_seat_cap", "_occupancy_raw"], errors="ignore")

    # actual_trips from service master (before groupby so we can sum it)
    df["actual_trips"] = None
    if sm_df is not None:
        sm_lookup = sm_df[["depot", "service_number", "planned_kms", "planned_trips"]].copy()
        df = df.merge(sm_lookup, on=["depot", "service_number"], how="left")
        df["actual_trips"] = df.apply(
            lambda r: round(r["actual_kms"] * r["planned_trips"] / r["planned_kms"], 2)
            if pd.notna(r.get("planned_kms")) and r["planned_kms"] != 0 else None, axis=1
        )
        df = df.drop(columns=["planned_kms", "planned_trips"], errors="ignore")
        stats["trips_calculated"] = int(df["actual_trips"].notna().sum())
    else:
        stats["trips_calculated"] = 0

    # ── Duplicate detection & aggregation ────────────────────────────────
    dup_mask = df.duplicated(subset=["depot", "date", "service_number"], keep=False)
    stats["duplicate_rows_found"] = int(dup_mask.sum())

    # Capture duplicate rows for display (before aggregation)
    duplicate_rows_df = df[dup_mask].copy().reset_index(drop=True)

    # Aggregate: sum numeric cols, then recalculate occupancy_ratio
    agg_dict = {k: "sum" for k in ["actual_kms", "actual_trips", "seat_kms", "passenger_kms", "revenue"]
                if k in df.columns}
    if agg_dict:
        df = df.groupby(["depot", "date", "service_number"], as_index=False).agg(agg_dict)
    else:
        df = df.drop_duplicates(subset=["depot", "date", "service_number"]).reset_index(drop=True)

    # Recalculate occupancy_ratio = passenger_kms / seat_kms after summing
    if "passenger_kms" in df.columns and "seat_kms" in df.columns:
        df["occupancy_ratio"] = df.apply(
            lambda r: (r["passenger_kms"] / r["seat_kms"])
            if pd.notna(r["seat_kms"]) and r["seat_kms"] != 0 else None,
            axis=1
        )
        # Blank recalculated OR > 3
        mask_or = df["occupancy_ratio"] > 3
        df.loc[mask_or, "occupancy_ratio"] = None
        df.loc[mask_or, "passenger_kms"]   = None
    # ─────────────────────────────────────────────────────────────────────

    final_cols = ["depot", "date", "service_number", "actual_kms",
                  "actual_trips", "seat_kms", "passenger_kms", "occupancy_ratio", "revenue"]
    df = df[[c for c in final_cols if c in df.columns]]
    df["date"]       = pd.to_datetime(df["date"], errors="coerce")
    df["actual_kms"] = pd.to_numeric(df["actual_kms"], errors="coerce").round(0).astype("Int64")

    stats["rows_final"] = len(df)
    return df, stats, duplicate_rows_df


# ══════════════════════════════════════════════════════════════════════════
# FILE 2 — Service Wise Report (.csv)
# ══════════════════════════════════════════════════════════════════════════

def transform_service_wise(uploaded_file) -> tuple[pd.DataFrame, dict]:
    stats = {}
    uploaded_file.seek(0)
    df = pd.read_csv(uploaded_file)
    df.columns = [str(c).strip() for c in df.columns]

    df = df.rename(columns={
        "Depot":      "depot",
        "RPT_DATE":   "date",
        "Psng_Total": "passengers_per_day",
        "OPD_KMS":    "actual_kms",
        "OR_Total":   "occupancy_ratio",
    })

    keep = ["depot", "date", "passengers_per_day", "actual_kms", "occupancy_ratio"]
    df = df[[c for c in keep if c in df.columns]].copy()

    for col in ["passengers_per_day", "actual_kms", "occupancy_ratio"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    stats["rows_after_load"] = len(df)

    before = df["depot"].str.strip().str.upper().unique()
    df["depot"] = apply_depot_lookup(df["depot"])
    stats["depots_remapped"] = int(sum(1 for d in before if DEPOT_LOOKUP.get(d, d) != d))

    before_filter = len(df)
    df = df[df["depot"].isin(ALLOWED_DEPOTS)].copy()
    stats["rows_filtered_out"] = before_filter - len(df)

    df["occupancy_ratio"] = df["occupancy_ratio"] / 100

    mask = df["occupancy_ratio"] > 2.0
    df.loc[mask, "occupancy_ratio"] = None
    stats["blanked_high_or"] = int(mask.sum())

    before_dup = len(df)
    df = df.drop_duplicates(subset=["depot", "date"], keep="first")
    stats["removed_duplicates"] = before_dup - len(df)

    df["date"]               = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df["actual_kms"]         = pd.to_numeric(df["actual_kms"], errors="coerce").round(0).astype("Int64")
    df["passengers_per_day"] = pd.to_numeric(df["passengers_per_day"], errors="coerce").round(0).astype("Int64")

    stats["rows_final"] = len(df)
    return df, stats


# ══════════════════════════════════════════════════════════════════════════
# HELPER — format a dataframe for display
# ══════════════════════════════════════════════════════════════════════════

def format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy().reset_index(drop=True)
    d.index = d.index + 1
    if "date" in d.columns:
        d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["seat_kms", "passenger_kms", "revenue"]:
        if col in d.columns:
            d[col] = d[col].apply(lambda x: f"{x:,.2f}" if pd.notna(x) else "—")
    for col in ["actual_kms", "actual_trips", "passengers_per_day"]:
        if col in d.columns:
            d[col] = d[col].apply(lambda x: str(int(x)) if pd.notna(x) else "—")
    if "occupancy_ratio" in d.columns:
        d["occupancy_ratio"] = d["occupancy_ratio"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) else "—"
        )
    return d


# ══════════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════════

st.subheader("1. Upload Files")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**📊 Ops_Daily_Service_Master**")
    xlsx_file = st.file_uploader(
        "day_service_report",
        type=["xlsx", "htm", "html"],
        label_visibility="collapsed",
        help="Open the .xls in Excel → File → Save As → Excel Workbook (.xlsx)",
    )

with col2:
    st.markdown("**📋 Ops_Daily**")
    csv_file = st.file_uploader(
        "service_wise_report",
        type=["csv"],
        label_visibility="collapsed",
        help="Upload the service_wise_report CSV file",
    )

# ── Load service master from disk ─────────────────────────────────────────
sm_df = None
if os.path.exists(SERVICE_MASTER_FILE):
    try:
        sm_df = pd.read_csv(SERVICE_MASTER_FILE)
        sm_df.columns = [c.strip().lower().replace(" ", "_") for c in sm_df.columns]
        st.caption(f"✅ Service master auto-loaded: {SERVICE_MASTER_FILE}  ({len(sm_df):,} rows)")
    except Exception:
        st.caption("⚠️ Service master found but could not be read — actual_trips will be blank.")
else:
    st.caption(f"⚠️ Service master not found at `{SERVICE_MASTER_FILE}` — actual_trips will be blank.")

st.divider()

if xlsx_file is None and csv_file is None:
    st.info("Upload at least one file above to enable transformation.")
    st.stop()

if st.button("⚙️ Run Transformation", type="primary", width="stretch"):
    with st.spinner("Running transformation pipeline…"):

        results = {}

        # ── Day Service Report ────────────────────────────────────────────
        if xlsx_file is not None:
            try:
                raw_df = read_day_service_report(xlsx_file)
                out_df, stats, dup_df = transform_day_service(raw_df, sm_df)
                filename = derive_filename_service(out_df)
                results["day_service"] = {
                    "df": out_df,
                    "filename": filename,
                    "stats": stats,
                    "duplicate_rows": dup_df,
                }
            except Exception as e:
                st.error(f"Day Service Report failed: {e}")
                st.exception(e)

        # ── Service Wise Report ───────────────────────────────────────────
        if csv_file is not None:
            try:
                out_df, stats = transform_service_wise(csv_file)
                filename = derive_filename_daily(out_df)
                results["service_wise"] = {
                    "df": out_df,
                    "filename": filename,
                    "stats": stats,
                    "duplicate_rows": pd.DataFrame(),
                }
            except Exception as e:
                st.error(f"Service Wise Report failed: {e}")
                st.exception(e)

        st.session_state["results"]     = results
        st.session_state["transformed"] = True

# ── Results ───────────────────────────────────────────────────────────────
if st.session_state.get("transformed"):

    results = st.session_state.get("results", {})
    if not results:
        st.stop()

    tab_labels = []
    if "day_service" in results:
        tab_labels.append("📊 Ops_Daily_Service_Master")
    if "service_wise" in results:
        tab_labels.append("📋 Ops_Daily")

    tabs = st.tabs(tab_labels)
    tab_keys = [k for k in ["day_service", "service_wise"] if k in results]

    for tab, key in zip(tabs, tab_keys):
        r        = results[key]
        out_df   = r["df"]
        filename = r["filename"]
        stats    = r["stats"]
        dup_df   = r.get("duplicate_rows", pd.DataFrame())

        with tab:
            st.divider()
            st.subheader("Transformation Summary")

            if key == "day_service":
                m1, m2, m3, m4, m5, m6 = st.columns(6)
                m1.metric("Rows Loaded",          f"{stats.get('rows_after_load', 0):,}")
                m2.metric("Depots Remapped",       f"{stats.get('depots_remapped', 0):,}")
                m3.metric("Filtered Out (Depot)",  f"{stats.get('rows_filtered_out', 0):,}")
                m4.metric("8000-8999 Removed",     f"{stats.get('service_8000_8999_removed', 0):,}")
                m5.metric("Blanked (High OR)",     f"{stats.get('blanked_high_or', 0):,}")
                m6.metric("Duplicate Rows Found",  f"{stats.get('duplicate_rows_found', 0):,}")

                m7, m8 = st.columns(2)
                m7.metric("Trips Calculated", f"{stats.get('trips_calculated', 0):,}")
                m8.metric("Final Rows",       f"{stats.get('rows_final', 0):,}")
            else:
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Rows Loaded",          f"{stats.get('rows_after_load', 0):,}")
                m2.metric("Depots Remapped",       f"{stats.get('depots_remapped', 0):,}")
                m3.metric("Filtered Out",          f"{stats.get('rows_filtered_out', 0):,}")
                m4.metric("Blanked (High OR)",     f"{stats.get('blanked_high_or', 0):,}")
                m5.metric("Removed (Duplicates)",  f"{stats.get('removed_duplicates', 0):,}")
                st.metric("Final Rows", f"{stats.get('rows_final', 0):,}")

            # ── Main preview ──────────────────────────────────────────────
            st.divider()
            st.subheader("Preview — Transformed Output")
            st.caption(f"Output filename: **{filename}**")
            st.dataframe(format_for_display(out_df), width="stretch", height=420)

            # ── Duplicates table (Day Service only) ───────────────────────
            if key == "day_service":
                st.divider()
                if dup_df is not None and not dup_df.empty:
                    st.subheader(f"🔁 Duplicate Rows — Original Values ({len(dup_df):,} rows)")
                    st.caption(
                        "These rows shared the same **depot + date + service_number**. "
                        "Their numeric values were **summed** in the output above, "
                        "and `occupancy_ratio` was recalculated as `passenger_kms / seat_kms`."
                    )

                    show_cols = [c for c in
                        ["depot", "date", "service_number", "actual_kms", "seat_kms",
                         "actual_trips", "passenger_kms", "occupancy_ratio", "revenue"]
                        if c in dup_df.columns]

                    st.dataframe(
                        format_for_display(dup_df[show_cols]),
                        width="stretch",
                        height=320,
                    )

                    dup_csv_bytes = dup_df[show_cols].copy()
                    dup_csv_bytes["date"] = pd.to_datetime(
                        dup_csv_bytes["date"], errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                    st.download_button(
                        label="⬇️ Download Duplicates CSV",
                        data=dup_csv_bytes.to_csv(index=False).encode("utf-8"),
                        file_name=filename.replace("ops_daily_service", "ops_daily_service_DUPLICATES"),
                        mime="text/csv",
                        key=f"dl_dup_{key}",
                    )
                else:
                    st.success("✅ No duplicate rows found for depot + date + service_number.")

            # ── Export ────────────────────────────────────────────────────
            st.divider()
            st.subheader("Export")

            csv_bytes = df_to_csv_bytes(out_df)
            col_dl, col_mv = st.columns(2)

            with col_dl:
                st.download_button(
                    label="⬇️ Download CSV",
                    data=csv_bytes,
                    file_name=filename,
                    mime="text/csv",
                    width="stretch",
                    key=f"dl_{key}",
                )

            with col_mv:
                if st.button("📁 Move to Inbound Folder", width="stretch", key=f"mv_{key}"):
                    if not os.path.isdir(INBOUND_FOLDER):
                        st.error(
                            f"Inbound folder not found:\n`{INBOUND_FOLDER}`\n\n"
                            "Update the `INBOUND_FOLDER` path at the top of this script."
                        )
                    else:
                        dest_path = os.path.join(INBOUND_FOLDER, filename)
                        try:
                            with open(dest_path, "wb") as f:
                                f.write(csv_bytes)
                            st.success(f"✅ Saved to:\n`{dest_path}`")
                        except Exception as e:
                            st.error(f"Failed: {e}")

            st.caption(
                f"Inbound folder: `{INBOUND_FOLDER}` — "
                "Update `INBOUND_FOLDER` at the top of the script if the path changes."
            )