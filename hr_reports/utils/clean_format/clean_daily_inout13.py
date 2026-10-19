# hr_reports/utils/clean_format/clean_daily_inout13.py
import os
import tempfile
import pandas as pd
import frappe
import xlrd
from openpyxl import Workbook
from datetime import datetime, timedelta
from typing import Optional

# =========================
# .xls -> .xlsx conversion
# =========================
def convert_xls_to_xlsx(xls_path: str) -> str:
    print(f"[convert_xls_to_xlsx] Converting .xls to .xlsx: {xls_path}")
    book = xlrd.open_workbook(xls_path, formatting_info=False)
    sheet = book.sheet_by_index(0)
    wb = Workbook()
    ws = wb.active
    for r in range(sheet.nrows):
        for c in range(sheet.ncols):
            cell_value = sheet.cell_value(r, c)
            if sheet.cell_type(r, c) == xlrd.XL_CELL_DATE:
                try:
                    cell_value = xlrd.xldate_as_datetime(cell_value, book.datemode)
                except Exception:
                    pass
            ws.cell(row=r + 1, column=c + 1).value = cell_value
    temp_xlsx = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx").name
    wb.save(temp_xlsx)
    print(f"[convert_xls_to_xlsx] Saved temporary .xlsx: {temp_xlsx}")
    return temp_xlsx

def parse_date_dd_mm_yyyy(date_val):
    """Parse date string in DD/MM/YYYY format"""
    if pd.isna(date_val):
        return None
    
    # If already a datetime object, return it
    if isinstance(date_val, (datetime, pd.Timestamp)):
        return date_val
    
    try:
        date_str = str(date_val).strip()
        if not date_str or date_str.lower() in ["nan", "none", ""]:
            return None
        
        # Try DD/MM/YYYY format first
        try:
            return pd.to_datetime(date_str, format="%d/%m/%Y", errors="raise")
        except (ValueError, TypeError):
            pass
        
        # Try DD-MM-YYYY format
        try:
            return pd.to_datetime(date_str, format="%d-%m-%Y", errors="raise")
        except (ValueError, TypeError):
            pass
        
        # Try other common formats
        try:
            return pd.to_datetime(date_str, format="%Y-%m-%d", errors="raise")
        except (ValueError, TypeError):
            pass
        
        # Last resort: let pandas infer (but this might cause the issue)
        return pd.to_datetime(date_str, errors="coerce")
    except Exception:
        return None

def format_datetime(date_val, time_val):
    if pd.isna(date_val):
        return None

    # Parse date using DD/MM/YYYY format
    if not isinstance(date_val, (datetime, pd.Timestamp)):
        date_val = parse_date_dd_mm_yyyy(date_val)
    if pd.isna(date_val) or date_val is None:
        return None

    if isinstance(time_val, timedelta):
        total_seconds = int(time_val.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
    else:
        try:
            t_str = str(time_val).strip()
            if not t_str or t_str.lower() in ["nan", "none"]:
                return None
            parts = t_str.replace(".", ":").split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            seconds = int(parts[2]) if len(parts) > 2 else 0
        except Exception:
            return None

    return date_val.strftime("%Y-%m-%d") + f" {hours:02d}:{minutes:02d}:{seconds:02d}"

def _to_float_workhrs(time_str):
    if not time_str or str(time_str).lower() in ["nan", "none"]:
        return 0.0
    try:
        parts = str(time_str).split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
        return round(h + m/60 + s/3600, 2)
    except Exception:
        return 0.0

def map_status(raw_status) -> str:
    s = "" if pd.isna(raw_status) else str(raw_status).strip()
    mapping = {
        "P": "Present", "POW": "Present", "RL": "Present", "TU": "Present", "QL": "Present",
        "A": "Absent", "AB": "Absent", "O": "Absent",
        "WO": "Holiday", "H": "Holiday",
        "CL": "On Leave", "PL": "On Leave", "SL": "On Leave", "EL": "On Leave", "AP": "On Leave", 
        "LWP": "On Leave", "SDL": "On Leave",
        "CO": "On Leave", "TR": "On Leave", "OH": "On Leave",
        "ML": "On Leave",
        "MIS": "Half Day", "HD": "Half Day", "HALF": "Half Day",
        "E": "Work From Home"
    }
    return mapping.get(s, s if s else "Absent")


def _calculate_overtime(work_hrs_str, shift):
    default_shift_hrs = {"A": 8, "B": 8, "C": 8, "G": 7}
    shift_hrs = default_shift_hrs.get(str(shift).upper(), 0)

    work_float = _to_float_workhrs(work_hrs_str)
    overtime_val = round(work_float - shift_hrs - 0.60, 2)

    # If OT is negative, return blank
    return "" if overtime_val < 0 else overtime_val

def detect_shift(in_time: Optional[str], out_time: Optional[str]) -> str:
    def get_hour(ts: Optional[str]) -> Optional[int]:
        if not ts or str(ts).strip() == "" or pd.isna(ts):
            return None
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").hour
        except Exception:
            return None

    in_hour = get_hour(in_time)
    out_hour = get_hour(out_time)

    hour = in_hour if in_hour is not None else out_hour
    if hour is None:
        return "G"

    if 6 <= hour < 14:
        return "A"
    elif 14 <= hour < 22:
        return "B"
    elif hour >= 22 or hour < 6:
        return "C"
    elif 10 <= hour < 17:
        return "G"
    return "G"

def clean_daily_inout13(input_path: str, output_path: str, company: str = None, branch: str = None) -> pd.DataFrame:
    print("=" * 80)
    print("[clean_daily_inout13] Starting")
    print(f"[clean_daily_inout13] Input: {input_path}")
    print(f"[clean_daily_inout13] Output: {output_path}")
    print(f"[clean_daily_inout13] Company: {company}")
    print(f"[clean_daily_inout13] Branch: {branch}")
    print("=" * 80)

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Check if .xls file needs conversion
    working_file = input_path
    temp_created = False
    if input_path.lower().endswith(".xls"):
        working_file = convert_xls_to_xlsx(input_path)
        temp_created = True

    df_raw = pd.read_excel(working_file, engine="openpyxl")
    print(f"[clean_daily_inout13] Loaded raw DataFrame shape: {df_raw.shape}")

    required_cols = ["Employee ID", "Attand Date", "Employee Name", "Status", "In Time", "Out Time", "Total Hour"]
    missing = [c for c in required_cols if c not in df_raw.columns]
    if missing:
        raise ValueError(f"Missing required columns in input: {missing}")

    records = []
    for _, row in df_raw.iterrows():
        emp_id = str(row.get("Employee ID")).strip() if pd.notna(row.get("Employee ID")) else None
        emp_name = str(row.get("Employee Name")).strip() if pd.notna(row.get("Employee Name")) else None
        att_date_raw = row.get("Attand Date")
        time_in = row.get("In Time")
        time_out = row.get("Out Time")
        work_hrs = str(row.get("Total Hour")).strip() if pd.notna(row.get("Total Hour")) else None
        status_raw = row.get("Status")

        # Parse attendance date in DD/MM/YYYY format first
        parsed_att_date = parse_date_dd_mm_yyyy(att_date_raw)
        if parsed_att_date is None or pd.isna(parsed_att_date):
            print(f"[clean_daily_inout13] WARNING: Could not parse date {att_date_raw} for {emp_id} {emp_name}, skipping row")
            continue
        
        att_date_str = parsed_att_date.strftime("%Y-%m-%d")

        # Calculate working hours as decimal
        work_hrs_decimal = _to_float_workhrs(work_hrs)

        # Apply working hours threshold logic for ALL statuses
        if work_hrs_decimal >= 7.0:
            status = "Present"
        elif work_hrs_decimal >= 4.5:
            status = "Half Day"
        else:
            status = "Absent"

        print(f"[clean_daily_inout13] Calculated status based on working hours for {emp_id} {emp_name} on {att_date_str}: {work_hrs_decimal}h -> {status}")

        # Skip holidays and blank/empty rows
        if status == "Holiday":
            print(f"[clean_daily_inout13] Skipping {emp_id} {emp_name} on {att_date_str} (Holiday)")
            continue
        if (pd.isna(time_in) or str(time_in).strip() == "") and \
            (pd.isna(time_out) or str(time_out).strip() == "") and \
            (pd.isna(work_hrs) or str(work_hrs).strip() == "") and \
            (pd.isna(status_raw) or str(status_raw).strip() == ""):
            print(f"[clean_daily_inout13] Skipping {emp_id} {emp_name} on {att_date_str} (Empty Row)")
            continue


        # Map Employee ID (Gate Pass No) → Employee
        employee_id = None
        if emp_id:
            try:
                emp_doc = frappe.get_doc("Employee", {"attendance_device_id": emp_id})
                employee_id = emp_doc.name
            except Exception:
                print(f"[clean_daily_inout13] WARNING: Employee not found for GP No {emp_id}")
        
        in_time_fmt = format_datetime(parsed_att_date, time_in)
        out_time_fmt = format_datetime(parsed_att_date, time_out)
        shift = detect_shift(in_time_fmt, out_time_fmt)
        overtime_val = _calculate_overtime(work_hrs, shift)

        rec = {
            "Attendance Date": att_date_str,
            "Employee": employee_id if employee_id else "",
            "Employee Name": emp_name,
            "Status": status,
            "In Time": in_time_fmt,
            "Out Time": out_time_fmt,
            "Company": company if company else "",
            "Branch": branch if branch else "",
            "Working Hours": work_hrs_decimal,
            "Shift": shift,
            "Over Time": overtime_val,
            "Leave Type": "",
        }
        records.append(rec)

    df_final = pd.DataFrame.from_records(records)
    df_final = df_final.dropna(subset=["Attendance Date", "Employee"], how="any")
    print(f"[clean_daily_inout13] Built final DataFrame with {len(df_final)} rows")

    if df_final.empty:
        raise ValueError("No attendance records parsed from Daily In-Out report.")

    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    df_final.to_excel(output_path, index=False)
    print(f"[clean_daily_inout13] Saved output to: {output_path}")

    # Clean up temporary file if created
    if temp_created and os.path.exists(working_file):
        try:
            os.unlink(working_file)
            print(f"[clean_daily_inout13] Removed temporary file: {working_file}")
        except Exception:
            pass

    print("[clean_daily_inout13] Done ✅")

    return df_final
