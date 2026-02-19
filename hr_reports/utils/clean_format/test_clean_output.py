"""
Validate any cleaning script's output — one test file for all 22 scripts.

Usage:
  Test one output:     python test_clean_output.py /path/to/output.xlsx
  Test many at once:   python test_clean_output.py file1.xlsx file2.xlsx ...
  Test a folder:       python test_clean_output.py /path/to/outputs/
  Run pytest:          python -m pytest test_clean_output.py -v
"""

# command for run the testcases: /home/mital/frappe-bench/env/bin/python3 apps/hr_reports/hr_reports/utils/clean_format/test_clean_output.py


import sys, os, glob
from datetime import datetime, timedelta

import pandas as pd
import pytest

# ── Rules (single source of truth) ──────────────────────────

EXPECTED_COLUMNS = [
    "Attendance Date", "Employee", "Employee Name", "Status",
    "In Time", "Out Time", "Company", "Branch",
    "Working Hours", "Shift", "Over Time",
]
VALID_STATUSES = ["Present", "Half Day", "Absent"]
SHIFT_RANGES = {"A": (5, 7), "G": (8, 10), "B": (13, 15), "C": (21, 23)}
OT_THRESHOLD = 9
OT_MIN_DISPLAY = 1

# ── Helpers ──────────────────────────────────────────────────

def _parse_wh(wh):
    if pd.isna(wh) or str(wh).strip() == "":
        return None
    s = str(wh).strip()
    if ":" in s:
        p = s.split(":")
        try: return int(p[0]) + int(p[1]) / 60.0
        except: return None
    try: return float(s)
    except: return None

def _dt(val):
    if pd.isna(val) or str(val).strip() == "": return None
    try: return pd.to_datetime(val)
    except: return None

def _is_blank(val):
    return pd.isna(val) or str(val).strip() == ""

def expected_status(h):
    return "Present" if h >= 7.0 else "Half Day" if h >= 4.5 else "Absent"

def expected_shift(hour):
    for code, (lo, hi) in SHIFT_RANGES.items():
        if lo <= hour <= hi: return code
    return ""

def expected_ot(h):
    ot = round(h - OT_THRESHOLD, 2)
    return "" if ot < OT_MIN_DISPLAY else ot

# ── Validators (each returns list of error strings) ─────────

def check_columns(df):
    errs = []
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    extra   = [c for c in df.columns if c not in EXPECTED_COLUMNS]
    if missing: errs.append(f"Missing columns: {missing}")
    if extra:   errs.append(f"Extra columns: {extra}")
    actual = [c for c in df.columns if c in EXPECTED_COLUMNS]
    if actual != EXPECTED_COLUMNS:
        errs.append(f"Wrong order. Expected: {EXPECTED_COLUMNS}")
    return errs

def check_status(df):
    errs = []
    for i, r in df.iterrows():
        st = str(r.get("Status", "")).strip()
        if st not in VALID_STATUSES: continue
        wh = _parse_wh(r.get("Working Hours"))
        if wh is None:
            if st != "Absent":
                errs.append(f"Row {i}: WH blank but Status='{st}' (need Absent)")
            continue
        exp = expected_status(wh)
        if st != exp:
            errs.append(f"Row {i}: WH={wh:.2f}h → need '{exp}', got '{st}'")
    return errs

def check_inout(df):
    errs = []
    for i, r in df.iterrows():
        ind, outd = _dt(r.get("In Time")), _dt(r.get("Out Time"))
        if ind is None or outd is None: continue
        eff = outd + timedelta(days=1) if outd <= ind else outd
        hrs = (eff - ind).total_seconds() / 3600
        if hrs <= 0:
            errs.append(f"Row {i}: In >= Out even after overnight adjust")
        elif hrs > 16:
            errs.append(f"Row {i}: {hrs:.1f}h duration exceeds 16h limit")
    return errs

def check_overtime(df):
    errs = []
    for i, r in df.iterrows():
        if str(r.get("Status", "")).strip() not in VALID_STATUSES: continue
        wh = _parse_wh(r.get("Working Hours"))
        ot_raw = r.get("Over Time")
        blank = _is_blank(ot_raw)
        if wh is None:
            if not blank: errs.append(f"Row {i}: WH blank but OT='{ot_raw}'")
            continue
        exp = expected_ot(wh)
        if exp == "":
            if not blank: errs.append(f"Row {i}: WH={wh:.2f}h, OT should be blank, got '{ot_raw}'")
        elif blank:
            errs.append(f"Row {i}: WH={wh:.2f}h, need OT={exp}, got blank")
        else:
            try:
                if abs(float(ot_raw) - exp) > 0.15:
                    errs.append(f"Row {i}: WH={wh:.2f}h, need OT={exp}, got {ot_raw}")
            except: errs.append(f"Row {i}: Cannot parse OT '{ot_raw}'")
    return errs

def check_shift(df):
    errs = []
    for i, r in df.iterrows():
        st = str(r.get("Status", "")).strip()
        if st not in VALID_STATUSES: continue
        sh = "" if _is_blank(r.get("Shift")) else str(r["Shift"]).strip()
        if st == "Absent":
            if sh != "": errs.append(f"Row {i}: Absent but Shift='{sh}' (need blank)")
            continue
        ind = _dt(r.get("In Time"))
        if ind is None:
            if sh != "": errs.append(f"Row {i}: No In Time but Shift='{sh}' (need blank)")
            continue
        exp = expected_shift(ind.hour)
        if sh != exp:
            errs.append(f"Row {i}: hour={ind.hour} → need '{exp}', got '{sh}'")
    return errs

def check_dates(df):
    errs = []
    for i, r in df.iterrows():
        att = r.get("Attendance Date")
        if _is_blank(att): continue
        att_dt = _dt(att)
        if att_dt is None:
            errs.append(f"Row {i}: Cannot parse date '{att}'"); continue
        raw = str(att).strip()[:10]
        if len(raw) == 10 and raw[2] == "/" and raw[5] == "/":
            errs.append(f"Row {i}: DD/MM/YYYY found ('{raw}'), need YYYY-MM-DD")
        att_s = att_dt.strftime("%Y-%m-%d")
        nxt_s = (att_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        for col, allowed in [("In Time", {att_s}), ("Out Time", {att_s, nxt_s})]:
            ts = _dt(r.get(col))
            if ts and ts.strftime("%Y-%m-%d") not in allowed:
                errs.append(f"Row {i}: {col} date {ts.strftime('%Y-%m-%d')} != {att_s}")
    return errs

def check_wh_calc(df):
    errs = []
    for i, r in df.iterrows():
        ind, outd, wh = _dt(r.get("In Time")), _dt(r.get("Out Time")), _parse_wh(r.get("Working Hours"))
        if ind is None or outd is None or wh is None: continue
        if outd < ind: outd += timedelta(days=1)
        calc = round((outd - ind).total_seconds() / 3600, 2)
        if abs(calc - wh) > 0.17:
            errs.append(f"Row {i}: calc={calc:.2f}h but WH={wh:.2f}h")
    return errs

def check_employee(df):
    """
    Flag rows where Employee column is not blank and does not match the
    expected ERPNext employee code pattern: starts with 'v' or 'V' followed
    by digits (e.g. v38721, V12356).
    A purely numeric value (e.g. 112222) means the raw Gate Pass number leaked
    into the Employee column because the GP was not found in ERPNext master.
    """
    import re
    pattern = re.compile(r'^[vV]\d+$')
    errs = []
    for i, r in df.iterrows():
        emp = r.get("Employee", "")
        if _is_blank(emp):
            continue
        emp_str = str(emp).strip()
        if not pattern.match(emp_str):
            errs.append(
                f"Row {i}: Employee='{emp_str}' does not match expected pattern "
                f"(must be blank or start with 'v'/'V' followed by digits, e.g. v38721)"
            )
    return errs


ALL_CHECKS = dict(columns=check_columns, status=check_status, inout=check_inout,
                  overtime=check_overtime, shift=check_shift, dates=check_dates,
                  wh_calc=check_wh_calc, employee=check_employee)

def validate(df):
    return {n: fn(df) for n, fn in ALL_CHECKS.items()}

def report(results, path=""):
    total = sum(len(e) for e in results.values())
    fails = sum(1 for e in results.values() if e)
    print(f"\n{'='*60}\n  {path or 'DataFrame'}\n{'='*60}")
    for name, errs in results.items():
        tag = "PASS" if not errs else f"FAIL({len(errs)})"
        print(f"  [{tag}] {name}")
        for e in errs[:5]: print(f"      {e}")
        if len(errs) > 5: print(f"      ... +{len(errs)-5} more")
    print(f"{'='*60}\n  {fails} failed, {total} errors\n{'='*60}\n")
    return total == 0

# ── CLI ──────────────────────────────────────────────────────

def _find_latest():
    """Find the most recently modified cleaned_*.xlsx in frappe sites folder."""
    d = os.path.dirname(os.path.abspath(__file__))
    while d != "/":
        if os.path.isdir(os.path.join(d, "sites")) and os.path.isdir(os.path.join(d, "apps")):
            break
        d = os.path.dirname(d)
    found = glob.glob(os.path.join(d, "sites/*/private/files/cleaned_*.xlsx"))
    if not found:
        return None
    return max(found, key=os.path.getmtime)

# Filename keywords → script name (checked in order, first match wins)
_SCRIPT_MAP = [
    (["BALCO"],                          "clean_daily_inout10"),
    (["Lanjigarh"],                      "clean_daily_inout24"),
    (["VEDANTA", "Jharsuguda P"],        "clean_daily_inout14"),
    (["DOLVI", "FirstInLastOut"],         "clean_daily_inout13"),
    (["KAKINADA", "Monthly Punching"],   "clean_daily_inout11"),
    (["STL Jharsuguda"],                 "clean_daily_inout2"),
    (["JSW Jharsuguda"],                 "clean_daily_inout12"),
    (["JSPL", "Jsol"],                   "clean_daily_inout7_2"),
    (["Tata Angul"],                     "clean_daily_inout7_1"),
    (["Tata", "Kalinganagar", "JAMSHEDPUR"], "clean_daily_inout7"),
    (["Bellari obp2"],                   "clean_daily_inout30"),
    (["Bellari"],                        "clean_daily_inout30_2"),
    (["PARADIP", "Paradeep"],            "clean_daily_inout29"),
    (["Scrum", "Lapanga", "Hindalco"],   "clean_daily_inout15"),
    (["MATRIX", "Monthly Status"],       "clean_daily_inout_matrix"),
    (["Shendra", "Waluj"],               "clean_daily_inout_matrix_2"),
    (["rptDAttendanceReg", "Polycab", "Halol"], "clean_daily_inout16"),
    (["Hirakud Smelter", "SMELTER PUNCH", "PUNCH TIMING"], "clean_daily_inout18"),
    (["Hirakud FRP", "Hirakud"],         "clean_daily_inout17"),
    (["ManHour", "AMNS"],                "clean_daily_inout_pdf"),
    (["Performance_Register", "Debari", "HZL", "Pantnagar", "SK MILL",
      "Chanderia", "Dariba", "Agucha", "Zawar", "Kayad", "Haridwar"], "clean_daily_inout4"),
    (["Punch Report", "Daily Punch"],    "clean_daily_inout7"),
    (["Punching report"],                "clean_daily_inout11"),
]

def _detect_script(filename):
    name = filename.lower()
    for keywords, script in _SCRIPT_MAP:
        if any(kw.lower() in name for kw in keywords):
            return script
    return "clean_crystal_excel (default)"

import re as _re
from datetime import datetime as _datetime

def _file_age(path):
    mtime = os.path.getmtime(path)
    diff = _datetime.now() - _datetime.fromtimestamp(mtime)
    if diff.days > 0: return f"{diff.days}d ago"
    hrs = diff.seconds // 3600
    if hrs > 0: return f"{hrs}h ago"
    return f"{diff.seconds // 60}m ago"

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        path = sys.argv[1]
    else:
        path = _find_latest()
        if not path:
            print("No cleaned_*.xlsx found in sites/"); sys.exit(1)
    name = os.path.basename(path)
    script = _detect_script(name)
    age = _file_age(path)
    print(f"\n  File:   {name}")
    print(f"  Script: {script}.py")
    print(f"  Age:    {age}\n")
    ok = report(validate(pd.read_excel(path)), name)
    sys.exit(0 if ok else 1)

# ── Test data builder ────────────────────────────────────────

D = "2025-01-15"  # default date

def _r(**kw):
    base = {"Attendance Date": D, "Employee": "v38721", "Employee Name": "Test",
            "Status": "Present", "In Time": f"{D} 09:00:00", "Out Time": f"{D} 17:00:00",
            "Company": "X", "Branch": "M", "Working Hours": 8.0, "Shift": "G", "Over Time": ""}
    base.update(kw)
    return pd.DataFrame([base])[EXPECTED_COLUMNS]

def _good_df():
    R = lambda **kw: {**{"Attendance Date": D, "Employee": "v38721", "Employee Name": "T",
                         "Company": "X", "Branch": "M"}, **kw}
    return pd.DataFrame([
        R(Status="Present",  **{"In Time": f"{D} 09:00:00", "Out Time": f"{D} 17:00:00", "Working Hours": 8.0,  "Shift": "G", "Over Time": ""}),
        R(Status="Present",  **{"In Time": f"{D} 06:00:00", "Out Time": f"{D} 16:30:00", "Working Hours": 10.5, "Shift": "A", "Over Time": 1.5}),
        R(Status="Half Day", **{"In Time": f"{D} 09:00:00", "Out Time": f"{D} 14:00:00", "Working Hours": 5.0,  "Shift": "G", "Over Time": ""}),
        R(Status="Absent",   **{"In Time": "", "Out Time": "", "Working Hours": "", "Shift": "", "Over Time": ""}),
        R(Status="Present",  **{"In Time": f"{D} 22:00:00", "Out Time": f"{D} 06:00:00", "Working Hours": 8.0,  "Shift": "C", "Over Time": ""}),
        R(Status="Present",  **{"In Time": f"{D} 14:00:00", "Out Time": f"{D} 22:00:00", "Working Hours": 8.0,  "Shift": "B", "Over Time": ""}),
    ])[EXPECTED_COLUMNS]

# ── Pytest: rule helpers ─────────────────────────────────────

class TestRules:
    @pytest.mark.parametrize("h,exp", [(7,"Present"),(12,"Present"),(4.5,"Half Day"),
                                        (6.99,"Half Day"),(4.49,"Absent"),(0,"Absent")])
    def test_status(self, h, exp):
        assert expected_status(h) == exp

    @pytest.mark.parametrize("hr,exp", [(5,"A"),(6,"A"),(7,"A"),(8,"G"),(9,"G"),(10,"G"),
                                         (13,"B"),(14,"B"),(15,"B"),(21,"C"),(22,"C"),(23,"C")])
    def test_shift_in_range(self, hr, exp):
        assert expected_shift(hr) == exp

    @pytest.mark.parametrize("hr", [0,1,2,3,4,11,12,16,17,18,19,20])
    def test_shift_blank_outside(self, hr):
        assert expected_shift(hr) == ""

    @pytest.mark.parametrize("h,exp", [(8,""),(9.5,""),(9.99,""),(10,1.0),(11.5,2.5)])
    def test_overtime(self, h, exp):
        assert expected_ot(h) == exp

# ── Pytest: validator checks with real rows ──────────────────

class TestValidators:
    # --- status ---
    def test_status_wrong_flagged(self):
        assert check_status(_r(**{"Working Hours": 8.0, "Status": "Absent"}))

    def test_status_blank_wh_needs_absent(self):
        assert check_status(_r(**{"Working Hours": "", "Status": "Present", "In Time": "", "Out Time": ""}))

    # --- shift ---
    def test_shift_absent_must_blank(self):
        assert check_shift(_r(Status="Absent", Shift="G", **{"In Time":"","Out Time":"","Working Hours":"","Over Time":""}))

    def test_shift_absent_blank_ok(self):
        assert not check_shift(_r(Status="Absent", Shift="", **{"In Time":"","Out Time":"","Working Hours":"","Over Time":""}))

    @pytest.mark.parametrize("hr,wrong_shift", [(11,"G"),(20,"B"),(4,"A"),(0,"C"),(12,"A")])
    def test_shift_no_default_no_nearest(self, hr, wrong_shift):
        """Hours outside all ranges must be blank, not defaulted or nearest."""
        assert check_shift(_r(**{"In Time": f"{D} {hr:02d}:00:00", "Out Time": f"{D} {(hr+8)%24:02d}:00:00",
                                  "Working Hours": 8.0, "Shift": wrong_shift}))

    # --- overtime ---
    def test_ot_blank_ok(self):
        assert not check_overtime(_r(**{"Working Hours": 8.0, "Over Time": ""}))

    def test_ot_value_ok(self):
        assert not check_overtime(_r(**{"Working Hours": 10.5, "Over Time": 1.5}))

    def test_ot_shown_when_should_blank(self):
        assert check_overtime(_r(**{"Working Hours": 9.5, "Over Time": 0.5}))

    def test_ot_blank_when_should_show(self):
        assert check_overtime(_r(**{"Working Hours": 11.0, "Over Time": ""}))

    # --- dates ---
    def test_date_ok(self):
        assert not check_dates(_r(**{"Attendance Date":"2025-12-05","In Time":"2025-12-05 09:00:00","Out Time":"2025-12-05 17:00:00"}))

    def test_date_dd_mm_yyyy_fails(self):
        assert check_dates(_r(**{"Attendance Date":"05/12/2025","In Time":"2025-12-05 09:00:00","Out Time":"2025-12-05 17:00:00"}))

    def test_december_swap_caught(self):
        assert check_dates(_r(**{"Attendance Date":"2025-05-12","In Time":"2025-12-05 09:00:00","Out Time":"2025-12-05 17:00:00"}))

    def test_overnight_next_day_ok(self):
        assert not check_dates(_r(**{"Attendance Date":D,"In Time":f"{D} 22:00:00","Out Time":"2025-01-16 06:00:00","Shift":"C"}))

    # --- in/out ---
    def test_inout_ok(self):
        assert not check_inout(_r())

    def test_inout_same_time(self):
        assert check_inout(_r(**{"In Time": f"{D} 09:00:00", "Out Time": f"{D} 09:00:00"}))

    def test_inout_overnight_ok(self):
        assert not check_inout(_r(**{"In Time": f"{D} 22:00:00", "Out Time": f"{D} 06:00:00"}))

    def test_inout_excessive(self):
        assert check_inout(_r(**{"In Time": f"{D} 06:00:00", "Out Time": f"{D} 05:00:00"}))

    # --- wh calc ---
    def test_wh_correct(self):
        assert not check_wh_calc(_r())

    def test_wh_wrong(self):
        assert check_wh_calc(_r(**{"Working Hours": 6.0}))

    def test_wh_overnight(self):
        assert not check_wh_calc(_r(**{"In Time":f"{D} 22:00:00","Out Time":f"{D} 06:00:00","Working Hours":8.0,"Shift":"C"}))

    def test_wh_hhmm(self):
        assert not check_wh_calc(_r(**{"In Time":f"{D} 09:00:00","Out Time":f"{D} 17:30:00","Working Hours":"08:30"}))

    # --- employee code pattern ---
    def test_employee_gp_number_flagged(self):
        """Raw GP number in Employee column must be flagged."""
        assert check_employee(_r(**{"Employee": "112222"}))

    def test_employee_blank_ok(self):
        """Blank Employee is acceptable (GP not found in master)."""
        assert not check_employee(_r(**{"Employee": ""}))

    def test_employee_valid_lowercase_v(self):
        """Employee code starting with lowercase 'v' is valid."""
        assert not check_employee(_r(**{"Employee": "v38721"}))

    def test_employee_valid_uppercase_v(self):
        """Employee code starting with uppercase 'V' is valid."""
        assert not check_employee(_r(**{"Employee": "V12356"}))

    def test_employee_invalid_no_prefix(self):
        """Alphanumeric code without 'v' prefix must be flagged."""
        assert check_employee(_r(**{"Employee": "EMP-001"}))

    # --- columns ---
    def test_cols_ok(self):
        assert not check_columns(_good_df())

    def test_cols_missing_shift(self):
        assert any("Shift" in e for e in check_columns(_good_df().drop(columns=["Shift"])))

    # --- full pass ---
    def test_good_df_all_pass(self):
        r = validate(_good_df())
        errs = [e for v in r.values() for e in v]
        assert errs == [], errs
