import pandas as pd
from datetime import datetime
import re

# ------------------------------------------------------------
# 1️⃣ Fixed column name mapping
# ------------------------------------------------------------
COLUMN_MAPPING = {
    "SLNO": None,
    "DEPOT": "depot",
    "DATE": "operations_date",
    "DRVNO": "employee_id",
    "VEHNO": "vehicle_number",
    "TYPE": "service_type",
    "SERNO": "service_number",
    "OPTDKMS": "opd_kms",
    "ENGS": "daily_earnings",
    "DNO": "day_night",
    "SCHS": "schedules_count",
    "LONGTYPE": "long_type",
    "ROUTE": "route_name",
}

# ------------------------------------------------------------
# 2️⃣ Depot normalization
# ------------------------------------------------------------
RAW_DEPOT_MAPPING = {
    "ACHAMPET": "ACHAMPET",
    "ADILABAD": "ADILABAD",
    "ARMOOR": "ARMOOR",
    "ASIFABAD": "ASIFABAD",
    "BHADRACHALAM": "BADRACHALAM",
    "BANDLAGUDA": "BANDLAGUDA",
    "BANSWADA": "BANSWADA",
    "BARKATPURA": "BARKATPURA",
    "BHAINSA": "BHAINSA",
    "BHEL": "BHEL",
    "BHUPALPALLY": "BHUPALAPALLAY",
    "BODHAN": "BODHAN",
    "CHENGICHERLA": "CHENGICHERLA",
    "CONTONMENT": "CONTONMENT",
    "DEVARAKONDA": "DEVARAKONDA",
    "DILSUKHNAGAR": "DILSHUKNAGAR",
    "DUBBAKA": "DUBBAKA",
    "FALAKNUMA": "FALAKNUMA",
    "FAROOQNAGAR": "FAROOQNAGAR",
    "GADWAL": "GADWAL",
    "G.D.KHANI": "GODAVARIKHANI",
    "GAJWEL PRAGNAPUR": "GWL-PRGPR",
    "HAKIMPET": "HAKIMPET",
    "HANUMAKONDA": "HANAMKONDA",
    "HAYATNAGAR-1": "HAYATHNAGAR-I",
    "HAYATNAGAR-2": "HAYATHNAGAR-II",
    "HCU DEPOT": "HCU",
    "HUSNABAD": "HUSNABAD",
    "HUZURABAD": "HUZURABAD",
    "HYDERABAD-I": "HYDERABAD-I",
    "HYDERABAD-II": "HYDERABAD-II",
    "IBRAHIMPATNAM": "IBRAHIMPATNAM",
    "JAGTIAL": "JAGITYAL",
    "JANAGAON": "JANGAON",
    "JEEDIMATLA": "JEEDIMETLA",
    "KACHIGUDA": "KACHEGUDA",
    "KALVAKURTHY": "KALVAKURTHY",
    "KAMAREDDI": "KAMAREDDY",
    "KARIMNAGAR-1": "KARIMNAGAR-I",
    "KARIMNAGAR-2": "KARIMNAGAR-II",
    "KHAMMAM": "KHAMMAM",
    "KODAD": "KODAD",
    "KOLLAPUR": "KOLLAPUR",
    "KORUTLA": "KORUTLA",
    "KOSGI": "KOSGI",
    "KOTHAGUDAM": "KOTHAGUDEM",
    "KUKATPALLI": "KUKATPALLY",
    "KUSHAIGUDA": "KUSHAIGUDA",
    "MADIRA": "MADHIRA",
    "MAHABOOBABAD": "MAHABOOBABAD",
    "MAHABOOBNAGAR": "MAHABOOBNAGAR",
    "MAHESWARAM": "MAHESWARAM",
    "MANCHIRYAL": "MANCHERIAL",
    "MANTHANI": "MANTHANI",
    "MANUGUR": "MANUGURU",
    "MEDAK": "MEDAK",
    "MEDCHAL": "MEDCHAL",
    "MEHDIPATNAM": "MEHDIPATNAM",
    "METPALLY": "METPALLY",
    "MIDHANI": "MIDHANI",
    "MIRYALAGUDA": "MIRYALAGUDA",
    "MIYAPUR": "MIYAPUR-I",
    "MIYAPUR-2": "MIYAPUR-II",
    "MUSHIRABAD-2": "MUSHIRABAD",
    "NAGARKURNOOL": "NAGARKURNOOL",
    "NALGONDA": "NALGONDA",
    "NARAYANKED": "NARAYANKHED",
    "NARAYANPET": "NARAYANPET",
    "NARKETPALLY": "NARKATPALLY",
    "NARASAMPET": "NARSAMPET",
    "NARSAPUR": "NARSAPUR",
    "NIRMAL": "NIRMAL",
    "NIZAMABAD-I": "NIZAMABAD-I",
    "NIZAMABAD-II": "NIZAMABAD-II",
    "PARIGI": "PARGI",
    "PARKAL": "PARKAL",
    "PICKET": "PICKET",
    "RAJENDERNAGAR": "RAJENDRANAGAR",
    "RANIGUNJ-I": "RANIGUNJ-I",
    "SANGAREDDY": "SANGAREDDY",
    "SATTUPALLI": "SATTUPALLY",
    "SHADNAGAR": "SHADNAGAR",
    "SIDDIPET": "SIDDIPET",
    "SIRCILLA": "SIRCILLA",
    "SURYAPET": "SURYAPET",
    "TANDUR": "TANDUR",
    "THORROORU": "THORROR",
    "UPPAL": "UPPAL",
    "UTNOOR": "UTNOOR",
    "VEMULAWADA": "VEMULAWADA",
    "VIKARABAD": "VIKARABAD",
    "WANAPARTHI": "WANAPARTHI",
    "WARANGAL-I": "WARANGAL-I",
    "WARANGAL-II": "WARANGAL-II",
    "YADAGIRIGUTTA": "YADAGIRIGUTTA",
    "YELLANDU": "YELLANDU",
    "ZAHIRABAD": "ZAHIRABAD",
}

# Only pairs where input != output (actual mapping)
DEPOT_VALUE_MAPPING = {k: v for k, v in RAW_DEPOT_MAPPING.items() if k != v}

# ------------------------------------------------------------
# 3️⃣ Helpers
# ------------------------------------------------------------
def normalize_header(col_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", col_name).upper().strip()

# ------------------------------------------------------------
# 4️⃣ Main Transformation
# ------------------------------------------------------------
def transform(df: pd.DataFrame):

    # Normalize headers
    df.columns = [normalize_header(col) for col in df.columns]

    # Map required columns
    mapped_columns = {
        col: COLUMN_MAPPING[col]
        for col in df.columns
        if col in COLUMN_MAPPING and COLUMN_MAPPING[col] is not None
    }

    df.rename(columns=mapped_columns, inplace=True)

    # Keep only mapped columns
    df = df[[col for col in mapped_columns.values()]]

    # Convert date
    if "operations_date" in df.columns:
        df["operations_date"] = (
            pd.to_datetime(df["operations_date"], format="%d-%m-%Y", errors="coerce")
            .dt.strftime("%Y-%m-%d")
        )

    # Numeric conversion
    for col in ["opd_kms", "daily_earnings", "schedules_count"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Clean strings (but DO NOT touch "NA")
    for col in ["depot", "vehicle_number", "service_number", "route_name",
                "service_type", "day_night", "long_type"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.upper()

    if "employee_id" in df.columns:
        df["employee_id"] = df["employee_id"].astype(str).str.strip()

    # --------------------------------------------------------
    # ⭐ Only treat EMPTY cells as NaN
    # --------------------------------------------------------
    df = df.applymap(lambda x: pd.NA if str(x).strip() == "" else x)

    # --------------------------------------------------------
    # Depot mapping
    # --------------------------------------------------------
    unmapped_depots = []
    if "depot" in df.columns:

        df["depot"] = df["depot"].astype(str).str.strip().str.upper()

        known_depots = set(RAW_DEPOT_MAPPING.keys())
        unique_depots = set(df["depot"].dropna().unique())

        unmapped_depots = sorted(list(unique_depots - known_depots))

        df["depot"] = df["depot"].replace(DEPOT_VALUE_MAPPING)

    # --------------------------------------------------------
    # Validate Missing Values
    # --------------------------------------------------------
    nan_mask = df.isna()
    missing_columns = nan_mask.columns[nan_mask.any()].tolist()

    if missing_columns:
        validation_report = {col: int(nan_mask[col].sum()) for col in missing_columns}
        raise ValueError(f"Missing values detected in transformed data: {validation_report}")

    return df, "daily_operations", {"unmapped_depots": unmapped_depots}
