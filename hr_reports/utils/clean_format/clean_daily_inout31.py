# clean_daily_inout31.py
"""
Cleaner for KCL MUNDRA PUNCH REPORT (monthly matrix format).

Source file layout:
  - Row 0: "Name of the Principal Employer : ..." (title)
  - Row 1: "For the Month of : Jul-2026"  (also carries the period range)
  - Row 2: headers - Sl.No., Entry Pass No, Name of Workman,
    Father's/Husband's Name, Contractor name, Department, Sub Area,
    Work Order, EIC, Trade, Skill, then one column per day of the month
    (e.g. "01-Wed", "02-Thu", ...), followed by Total Present Days /
    Total Leave Days / Total C-Off / Total Holidays / Total Weekly-Off /
    Total Paid Days / Total Unpaid Days summary columns.
  - Row 3+: one row per workman. Each day column holds a status code.

This is a pure attendance-status report - there are no in/out punch times
anywhere in the file, so In Time / Out Time / Working Hours / Shift /
Over Time are always left blank for every record.

Status mapping (source code -> Attendance Status), derived by reverse
engineering the Total Present Days / Total Unpaid Days summary columns:
  - P     -> Present   (full day, paid)
  - HD    -> Half Day  (half paid, half unpaid)
  - UHD   -> Half Day  (present half day, but fully unpaid)
  - A     -> Absent
  - SP    -> Absent    (single punch, no checkout recorded)
  - LHD   -> Absent    (despite the "HD" in the name, contributes 0 to
    Total Present Days - it's a full unpaid day, not a worked half day)
  - ULHD  -> Absent    (same reasoning as LHD)
"""

import os
import re
from datetime import datetime
from typing import Optional

import frappe
import pandas as pd


# -------------------------
# Helpers
# -------------------------
def parse_month_year(input_path: str) -> Optional[datetime]:
    """
    Parse the report month/year from the "For the Month of : Jul-2026" row.
    Returns a datetime set to the 1st of that month, or None if not found.
    """
    try:
        raw = pd.read_excel(input_path, header=None, nrows=3)
        for i in range(len(raw)):
            for val in raw.iloc[i].tolist():
                if pd.isna(val):
                    continue
                text = str(val)
                m = re.search(r'([A-Za-z]{3,9})[\s\-]+(\d{4})', text)
                if m and "month" in text.lower():
                    return datetime.strptime(f"{m.group(1)[:3]}-{m.group(2)}", "%b-%Y")
    except Exception as e:
        print(f"[parse_month_year] Error: {e}")
    return None


def normalize_id(id_val) -> str:
    """Normalize an Entry Pass No (may come in as int64) to a plain string."""
    if id_val is None or (isinstance(id_val, float) and pd.isna(id_val)):
        return ""
    if isinstance(id_val, float) and id_val.is_integer():
        return str(int(id_val))
    return str(id_val).strip()


STATUS_MAP = {
    "P": "Present",
    "HD": "Half Day",
    "UHD": "Half Day",
    "A": "Absent",
    "SP": "Absent",
    "LHD": "Absent",
    "ULHD": "Absent",
}


def map_status(status_code: str) -> Optional[str]:
    """
    Map the source day-cell status code to an Attendance Status.
    Returns None for unrecognized/blank codes so the caller can skip them.
    """
    code = str(status_code).strip().upper() if pd.notna(status_code) else ""
    if not code:
        return None

    if code in STATUS_MAP:
        return STATUS_MAP[code]

    print(f"[map_status] Unrecognized status code '{status_code}' - skipping cell")
    return None


# -------------------------
# Main cleaning function
# -------------------------
def clean_daily_inout31(input_path: str, output_path: str, company: str = None, branch: str = None) -> pd.DataFrame:
    print("=" * 80)
    print("[clean_daily_inout31] Starting - KCL MUNDRA PUNCH REPORT (monthly matrix)")
    print(f"[clean_daily_inout31] Input: {input_path}")
    print(f"[clean_daily_inout31] Output: {output_path}")
    print("=" * 80)

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    month_start = parse_month_year(input_path)
    if not month_start:
        raise ValueError("Could not determine report month from 'For the Month of : ...' row")
    print(f"[clean_daily_inout31] Report month: {month_start:%B %Y}")

    df = pd.read_excel(input_path, header=2)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"[clean_daily_inout31] Raw shape: {df.shape}")
    print(f"[clean_daily_inout31] Columns: {df.columns.tolist()}")

    required_cols = ["Entry Pass No", "Name of Workman", "Contractor name"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in input: {missing}")

    day_cols = [c for c in df.columns if re.match(r'^\d{1,2}-[A-Za-z]{3}$', c)]
    if not day_cols:
        raise ValueError("No day columns (e.g. '01-Wed') found in input")

    # Pre-compute date string for each day column, skipping days that don't
    # exist in this month (e.g. a "31-..." column in a 30-day month).
    date_for_col = {}
    for col in day_cols:
        day_num = int(col.split("-")[0])
        try:
            date_for_col[col] = datetime(month_start.year, month_start.month, day_num).strftime("%Y-%m-%d")
        except ValueError:
            continue

    print(f"[clean_daily_inout31] Found {len(date_for_col)} valid day columns")

    records = []

    for idx, row in df.iterrows():
        try:
            entry_pass = row.get("Entry Pass No")
            if pd.isna(entry_pass):
                continue

            token = normalize_id(entry_pass)
            workmen = str(row.get("Name of Workman", "")).strip() if pd.notna(row.get("Name of Workman")) else ""
            contractor = str(row.get("Contractor name", "")).strip() if pd.notna(row.get("Contractor name")) else ""

            try:
                emp_code = frappe.db.get_value("Employee", {"attendance_device_id": token}, "name")
                if not emp_code:
                    emp_code = ""
                    print(f"[clean_daily_inout31] Warning: No Employee found for Entry Pass No {token} - keeping blank")
            except Exception as e:
                emp_code = ""
                print(f"[clean_daily_inout31] Error looking up Entry Pass No {token}: {e} - keeping blank")

            for col, date_str in date_for_col.items():
                status = map_status(row.get(col))
                if status is None:
                    continue

                record = {
                    "Attendance Date": date_str,
                    "Employee": emp_code,
                    "Employee Name": workmen,
                    "Status": status,
                    "In Time": "",
                    "Out Time": "",
                    "Working Hours": 0.0,
                    "Over Time": "",
                    "Shift": "",
                    "Company": company if company else contractor,
                    "Branch": branch if branch else "",
                }
                records.append(record)

        except Exception as e:
            print(f"[clean_daily_inout31] Error processing row {idx}: {e}")
            continue

    df_final = pd.DataFrame.from_records(
        records,
        columns=[
            "Attendance Date",
            "Employee",
            "Employee Name",
            "Status",
            "In Time",
            "Out Time",
            "Working Hours",
            "Over Time",
            "Shift",
            "Company",
            "Branch",
        ],
    )

    if df_final.empty:
        raise ValueError(
            "❌ No attendance records could be parsed. "
            "Please check that the file format is correct."
        )

    print(f"[clean_daily_inout31] Total records parsed: {len(df_final)}")

    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    df_final.to_excel(output_path, index=False)
    print(f"[clean_daily_inout31] Saved cleaned file: {output_path}")
    print("[clean_daily_inout31] Done ✅")

    return df_final
