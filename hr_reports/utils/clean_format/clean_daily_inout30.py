# clean_daily_inout30.py
"""
Cleaner for Transaction IN OUT Report (vertical format). Groups punches by
employee + date, pairs first IN with last OUT (resolving night shifts that
cross midnight back onto the start day), then derives Shift, Working Hours,
Overtime, and Status from that span.
"""

import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import frappe
import pandas as pd


# -------------------------
# Config
# -------------------------
NIGHT_CLOSE_CUTOFF_HOUR = 8   # used by _compute_span's same-row overnight-wrap guard
NIGHT_MAX_SPAN_HOURS = 30     # sanity cap for a cross-day orphan IN/OUT pairing - covers
                              # a single C shift up to a chained multi-shift run (e.g.
                              # G-C-A); anything longer is treated as unrelated punches,
                              # not a real continuous shift


# -------------------------
# Helpers
# -------------------------
def parse_date(date_str) -> Optional[str]:
    """Parse date from various formats to YYYY-MM-DD"""
    if pd.isna(date_str) or str(date_str).strip() == "":
        return None

    try:
        for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"]:
            try:
                dt = datetime.strptime(str(date_str).strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except:
                continue

        dt = pd.to_datetime(date_str, errors='coerce')
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"[parse_date] Error parsing date '{date_str}': {e}")

    return None


def parse_datetime(date_str: str, time_val) -> Optional[datetime]:
    """
    Parse a time value against a given 'YYYY-MM-DD' date string into a full
    datetime. Handles HH:MM:SS / HH:MM strings and datetime/Timestamp values.
    """
    if time_val is None or pd.isna(time_val) or str(time_val).strip() == "":
        return None

    try:
        if isinstance(time_val, (datetime, pd.Timestamp)):
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            return date_obj.replace(hour=time_val.hour, minute=time_val.minute, second=time_val.second)

        time_str = str(time_val).strip()
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) >= 2:
                h = int(parts[0])
                m = int(parts[1])
                s = int(parts[2]) if len(parts) > 2 else 0
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                return date_obj.replace(hour=h, minute=m, second=s)

    except Exception as e:
        print(f"[parse_datetime] Error parsing time '{time_val}' on '{date_str}': {e}")

    return None


def calculate_working_hours(in_dt: Optional[datetime], out_dt: Optional[datetime]) -> float:
    """
    Calculate working hours between two datetimes that are already on their
    correct calendar dates (overnight/night-shift resolution happens before
    this is called). Returns 0.0 if either side is missing or OUT isn't
    after IN.
    """
    if not in_dt or not out_dt or out_dt <= in_dt:
        return 0.0
    return round((out_dt - in_dt).total_seconds() / 3600, 2)


def detect_shift(in_dt: Optional[datetime]) -> str:
    """
    Detect shift code based on punch-in time windows.

    Shift definitions (punch-in time windows):
    - A shift: punch between 5-7 (05:00 to 07:00)
    - G shift: punch between 8-10 (08:00 to 10:00)
    - B shift: punch between 13-15 (13:00 to 15:00)
    - C shift: punch between 21-23 (21:00 to 23:00)

    If punch time is outside these windows, returns nearest shift.
    """
    if not in_dt:
        return "G"

    try:
        hour = in_dt.hour

        if 5 <= hour <= 7:
            return "A"
        elif 8 <= hour <= 10:
            return "G"
        elif 13 <= hour <= 15:
            return "B"
        elif 21 <= hour <= 23:
            return "C"
        else:
            distances = {
                "A": abs(hour - 6),
                "G": abs(hour - 9),
                "B": abs(hour - 14),
                "C": abs(hour - 22) if hour > 12 else abs(hour + 24 - 22)
            }
            return min(distances, key=distances.get)

    except Exception:
        return "G"


def calculate_overtime(work_hours: float) -> str:
    """
    Calculate overtime hours.

    Logic:
    - Standard shift hours: 9 hours (hardcoded)
    - Formula: OT = Working Hours - 9
    - Rules:
      - If OT < 1 hour -> return blank (empty string)
      - If OT >= 1 hour -> return OT value rounded to 2 decimals
      - If working_hours is 0 or None -> return blank
    """
    if not work_hours or work_hours <= 0:
        return ""

    shift_hours = 9
    overtime = round(work_hours - shift_hours, 2)

    if overtime < 1:
        return ""

    return str(overtime)


def determine_status(working_hours: float) -> str:
    """
    Determine attendance status based on working hours thresholds.

    Logic based on Working Hours thresholds:
    - >= 7.0 hours -> "Present"
    - >= 4.5 hours (but < 7.0) -> "Half Day"
    - < 4.5 hours -> "Absent"
    """
    if working_hours >= 7.0:
        return "Present"
    elif working_hours >= 4.5:
        return "Half Day"
    else:
        return "Absent"


def _format_output_datetime(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _compute_span(in_times: list, out_times: list) -> tuple:
    """
    First-IN / last-OUT span across a set of same-date punches, with a
    guard on the OUT-before-IN case: only treat it as a genuine overnight
    wrap when it actually looks like one (late-evening IN, early-morning
    OUT) - not two unrelated punches a few seconds apart, which previously
    produced bogus ~24h "shifts"
.

    Returns (first_in, last_out, working_hours).
    """
    first_in = min(in_times) if in_times else None
    last_out = max(out_times) if out_times else None

    if first_in and last_out and last_out < first_in:
        looks_overnight = first_in.hour >= 18 and last_out.hour < NIGHT_CLOSE_CUTOFF_HOUR
        if looks_overnight:
            last_out = last_out + timedelta(days=1)
        else:
            first_in, last_out = None, None

    return first_in, last_out, calculate_working_hours(first_in, last_out)


def resolve_night_shift_pairs(punch_rows: dict, emp_dates: dict) -> dict:
    """
    Walk each employee's dates in order and pair a punch-in on day D that
    has no closing punch that day with its closing punch-out on day D+1 -
    covering any crossing shift or back-to-back shift chain (C, B+C, G-C-A,
    etc.), not just a fixed set of shift-hour windows.

    A day D is a candidate if it has an orphan IN (no OUT on the same row),
    as long as D has no other row that is already a *complete* shift (IN and
    OUT both present) - duplicate/stray punches around the night IN are
    fine, only a genuine finished shift blocks pairing (that's a separate
    double-shift/long-day case, left untouched rather than guessed at). If D
    has more than one such orphan IN (duplicate taps), the FIRST (earliest)
    is used as the true start.

    It is closed by day D+1's leading run of orphan OUTs (no IN) - i.e.
    whatever OUT punch(es) come next chronologically, before any new IN
    activity starts that day. The LAST OUT in that leading run is used as
    the true close (in case of duplicate taps), and the whole run is
    removed from D+1's own punches so D+1's own activity (e.g. a following
    shift) is computed independently. The pair is credited to day D. The
    gap must be within NIGHT_MAX_SPAN_HOURS as a sanity bound.

    Returns: {(emp_id, date_str): (in_dt, out_dt)}
    """
    night_pairs = {}

    for emp_id, dates in emp_dates.items():
        for date_str in sorted(dates):
            rows = punch_rows[(emp_id, date_str)]

            # Only resolve a night-shift crossing when day D has no separate
            # completed shift already (a row with both IN and OUT). That is
            # a double-shift / long-day case that needs its own separate
            # policy decision - leave it untouched rather than guess how to
            # combine the two. Other incomplete/duplicate punches that day
            # do not block pairing.
            if any(r["in"] and r["out"] for r in rows):
                continue

            candidate_rows = [r for r in rows if r["in"] and not r["out"]]
            if not candidate_rows:
                continue
            night_row = min(candidate_rows, key=lambda r: r["in"])  # first IN
            night_in = night_row["in"]

            next_date_str = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            next_rows = punch_rows.get((emp_id, next_date_str))
            if not next_rows:
                continue

            # Walk D+1's punches in chronological order, collecting the
            # leading run of orphan OUTs (no IN) - that run is the (possibly
            # duplicated) closing scan. The moment a row with an IN shows up,
            # D+1's own new activity has started, so stop there.
            ordered_next = sorted(next_rows, key=lambda r: r["out"] or r["in"])
            closing_run = []
            for r in ordered_next:
                if r["in"]:
                    break
                closing_run.append(r)

            if not closing_run:
                continue
            closing_out = closing_run[-1]["out"]  # last OUT in the run

            span_hours = (closing_out - night_in).total_seconds() / 3600
            if span_hours <= 0 or span_hours > NIGHT_MAX_SPAN_HOURS:
                continue

            rows.remove(night_row)
            for r in closing_run:
                next_rows.remove(r)
            night_pairs[(emp_id, date_str)] = (night_in, closing_out)
            print(
                f"[clean_daily_inout30] Night shift closed: {emp_id} {date_str} "
                f"{night_in.strftime('%H:%M:%S')} -> {next_date_str} {closing_out.strftime('%H:%M:%S')} "
                f"({span_hours:.2f}h)"
            )

    return night_pairs


# -------------------------
# Main cleaning function
# -------------------------
def clean_daily_inout30(input_path: str, output_path: str, company: str = None, branch: str = None) -> pd.DataFrame:
    print("=" * 80)
    print("[clean_daily_inout30] Starting - Transaction IN OUT Report")
    print(f"[clean_daily_inout30] Input: {input_path}")
    print(f"[clean_daily_inout30] Output: {output_path}")
    print("=" * 80)

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    df = pd.read_excel(input_path, dtype=object)
    print(f"[clean_daily_inout30] Raw shape: {df.shape}")
    print(f"[clean_daily_inout30] Columns: {df.columns.tolist()}")

    required_cols = ['Date', 'Ramco EMP ID', 'Contractor Workers Name', 'IN PUNCH', 'OUT PUNCH']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Step 1: Collect raw per-row punches grouped by employee and date
    print("[clean_daily_inout30] Collecting punch records...")
    punch_rows = defaultdict(list)   # (ramco_emp_id, date_str) -> [{"in": dt|None, "out": dt|None}, ...]
    emp_dates = defaultdict(set)     # ramco_emp_id -> {date_str, ...}
    emp_names = {}                   # ramco_emp_id -> Contractor Workers Name

    for idx, row in df.iterrows():
        date_val = row.get('Date')
        ramco_emp_id = row.get('Ramco EMP ID')
        emp_name = row.get('Contractor Workers Name')
        in_punch = row.get('IN PUNCH')
        out_punch = row.get('OUT PUNCH')

        if pd.isna(date_val) or pd.isna(ramco_emp_id):
            continue

        date_str = parse_date(date_val)
        if not date_str:
            continue

        ramco_emp_id = str(ramco_emp_id).strip()
        emp_name = str(emp_name).strip() if pd.notna(emp_name) else ""
        emp_names[ramco_emp_id] = emp_name

        in_dt = parse_datetime(date_str, in_punch)
        out_dt = parse_datetime(date_str, out_punch)
        if not in_dt and not out_dt:
            continue

        punch_rows[(ramco_emp_id, date_str)].append({"in": in_dt, "out": out_dt})
        emp_dates[ramco_emp_id].add(date_str)

        if (idx + 1) % 100 == 0:
            print(f"[clean_daily_inout30] Processed {idx + 1} raw rows...")

    print(f"[clean_daily_inout30] Found {len(punch_rows)} unique employee-date combinations")

    # Step 2: Resolve night-shift (C shift) punches that cross midnight
    print("[clean_daily_inout30] Resolving night-shift punches crossing midnight...")
    night_pairs = resolve_night_shift_pairs(punch_rows, emp_dates)
    print(f"[clean_daily_inout30] Resolved {len(night_pairs)} night-shift day(s)")

    # Step 3: Process each employee-date combination
    print("[clean_daily_inout30] Processing attendance records (first IN, last OUT)...")
    records = []
    duplicate_count = 0

    for key, rows in punch_rows.items():
        ramco_emp_id, date_str = key
        emp_name = emp_names.get(ramco_emp_id, "")

        if len(rows) > 1:
            duplicate_count += 1

        is_night = key in night_pairs
        if is_night:
            # The whole day's hours are just this one cross-midnight shift;
            # any other stray/duplicate punches left in `rows` for day D
            # (which didn't block pairing) are not separately counted.
            first_in, last_out = night_pairs[key]
            work_hours_decimal = calculate_working_hours(first_in, last_out)
            # Shift by punch-in time: a 21-23h start is a genuine C shift; a
            # 13-15h start that runs past midnight is a B+C double shift, so
            # tag it by where it started (B), not by where it happened to end.
            shift_code = detect_shift(first_in)
        else:
            in_times = [r["in"] for r in rows if r["in"]]
            out_times = [r["out"] for r in rows if r["out"]]
            first_in, last_out, work_hours_decimal = _compute_span(in_times, out_times)
            shift_code = detect_shift(first_in)

        status = determine_status(work_hours_decimal)
        overtime = calculate_overtime(work_hours_decimal)

        try:
            emp_code = frappe.db.get_value("Employee", {"attendance_device_id": ramco_emp_id}, "name")
            if not emp_code:
                emp_code = ""
        except Exception:
            emp_code = ""

        record = {
            "Attendance Date": date_str,
            "Employee": emp_code,
            "Employee Name": emp_name,
            "Status": status,
            "In Time": _format_output_datetime(first_in),
            "Out Time": _format_output_datetime(last_out),
            "Working Hours": work_hours_decimal,
            "Over Time": overtime,
            "Shift": shift_code,
            "Company": company if company else "Vaaman Engineers India Limited",
            "Branch": branch if branch else "",
        }

        records.append(record)

    if duplicate_count > 0:
        print(f"[clean_daily_inout30] ⚠️  Handled {duplicate_count} employee-date(s) with multiple punches (using first IN, last OUT)")

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
            "Please check that the uploaded file matches the selected Branch "
            "and that the file format is correct."
        )

    print(f"[clean_daily_inout30] Total records parsed: {len(df_final)}")

    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    df_final.to_excel(output_path, index=False)
    print(f"[clean_daily_inout30] Saved cleaned file: {output_path}")
    print("[clean_daily_inout30] Done ✅")

    return df_final
