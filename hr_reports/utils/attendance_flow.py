# attendance_flow.py
import frappe
import os
import json
import time
from hr_reports.utils.clean_format.clean_crystal_excel import clean_crystal_excel
from hr_reports.utils.clean_format.clean_daily_inout24 import clean_daily_inout24
from hr_reports.utils.clean_format.clean_daily_inout14 import clean_daily_inout14
from hr_reports.utils.clean_format.clean_daily_inout4 import clean_daily_inout4
from hr_reports.utils.clean_format.clean_daily_inout13 import clean_daily_inout13
from hr_reports.utils.clean_format.clean_daily_inout11 import clean_daily_inout11
from hr_reports.utils.clean_format.clean_daily_inout10 import clean_daily_inout10
from hr_reports.utils.clean_format.clean_daily_inout2 import clean_daily_inout2
from hr_reports.utils.clean_format.clean_daily_inout12 import clean_daily_inout12
from hr_reports.utils.clean_format.clean_daily_inout29 import clean_daily_inout29
from hr_reports.utils.clean_format.clean_daily_inout30 import clean_daily_inout30
from hr_reports.utils.clean_format.clean_daily_inout30_2 import clean_daily_inout30_2
from hr_reports.utils.clean_format.clean_daily_inout7 import clean_daily_inout7
from hr_reports.utils.clean_format.clean_daily_inout7_1 import clean_daily_inout7_1
from hr_reports.utils.clean_format.clean_daily_inout7_2 import clean_daily_inout7_2
from hr_reports.utils.clean_format.clean_daily_inout15 import clean_daily_inout15
from hr_reports.utils.clean_format.clean_daily_inout_matrix import clean_daily_inout_matrix
from hr_reports.utils.clean_format.clean_daily_inout_matrix_2 import clean_daily_inout_matrix_2
from hr_reports.utils.clean_format.clean_daily_inout16 import clean_daily_inout16
from hr_reports.utils.clean_format.clean_daily_inout17 import clean_daily_inout17
from hr_reports.utils.clean_format.clean_daily_inout18 import clean_daily_inout18
from hr_reports.utils.clean_format.clean_daily_inout_pdf import clean_daily_inout_pdf
from frappe.core.doctype.data_import.data_import import start_import



def append_log(doc, message):
    """Append log line to processing_log field with timestamp"""
    new_log = (doc.processing_log or "") + f"\n{frappe.utils.now()} - {message}"
    doc.db_set("processing_log", new_log, update_modified=False)


def get_import_status_summary(data_import_name):
    """Get import status summary"""
    try:
        data_import = frappe.get_doc("Data Import", data_import_name)
        status = data_import.status or "Pending"
        
        # Get log counts
        logs = frappe.get_all(
            "Data Import Log",
            fields=["count(*) as count", "success"],
            filters={"data_import": data_import_name},
            group_by="success",
        )
        
        total_payload = data_import.payload_count or 0
        success_count = 0
        failed_count = 0
        
        for log in logs:
            if log.get("success"):
                success_count = log.get("count", 0)
            else:
                failed_count = log.get("count", 0)
        
        return {
            "status": status,
            "total": total_payload,
            "success": success_count,
            "failed": failed_count
        }
    except Exception as e:
        return {
            "status": "Error",
            "total": 0,
            "success": 0,
            "failed": 0,
            "error": str(e)
        }


def get_import_logs_detailed(data_import_name, limit=100):
    """Get detailed import logs with errors"""
    try:
        logs = frappe.get_all(
            "Data Import Log",
            fields=["success", "docname", "messages", "exception", "row_indexes", "log_index"],
            filters={"data_import": data_import_name},
            limit_page_length=limit,
            order_by="log_index",
        )
        return logs
    except Exception as e:
        return []


def log_import_results(crystal_upload_name, data_import_name):
    """Monitor and log Data Import results"""
    try:
        # Wait a bit for import to start
        time.sleep(2)
        
        max_wait_time = 1800  # 30 minutes max wait for large imports
        check_interval = 5  # Check every 5 seconds
        status_update_interval = 30  # Log status update every 30 seconds
        elapsed_time = 0
        last_status_update = 0
        
        crystal_upload = frappe.get_doc("Crystal Attendance Upload", crystal_upload_name)
        
        while elapsed_time < max_wait_time:
            try:
                status_summary = get_import_status_summary(data_import_name)
                status = status_summary.get("status", "Pending")
                
                # Log periodic status updates while waiting
                if elapsed_time - last_status_update >= status_update_interval:
                    total = status_summary.get('total', 0)
                    success = status_summary.get('success', 0)
                    failed = status_summary.get('failed', 0)
                    minutes_elapsed = elapsed_time // 60
                    seconds_elapsed = elapsed_time % 60
                    
                    if status == "Pending":
                        append_log(crystal_upload, f"⏳ Still processing... ({minutes_elapsed}m {seconds_elapsed}s elapsed)")
                        if total > 0:
                            append_log(crystal_upload, f"   Progress: {success + failed}/{total} records processed")
                    else:
                        # Status changed, log it
                        append_log(crystal_upload, f"📊 Status changed to: {status}")
                    
                    last_status_update = elapsed_time
                
                # If import is complete (Success, Partial Success, Error, Timed Out)
                if status in ["Success", "Partial Success", "Error", "Timed Out"]:
                    append_log(crystal_upload, f"\n📊 Data Import Status: {status}")
                    append_log(crystal_upload, f"   Total Records: {status_summary.get('total', 0)}")
                    append_log(crystal_upload, f"   ✅ Successful: {status_summary.get('success', 0)}")
                    append_log(crystal_upload, f"   ❌ Failed: {status_summary.get('failed', 0)}")
                    
                    # Get detailed logs for failures
                    if status_summary.get("failed", 0) > 0:
                        append_log(crystal_upload, f"\n📋 Failed Import Details:")
                        failed_logs = get_import_logs_detailed(data_import_name, limit=50)
                        
                        error_count = 0
                        for log in failed_logs:
                            if not log.get("success"):
                                error_count += 1
                                if error_count <= 20:  # Limit to first 20 errors to avoid log spam
                                    row_indexes = json.loads(log.get("row_indexes") or "[]")
                                    messages = json.loads(log.get("messages") or "[]")
                                    
                                    # Extract error messages
                                    error_msgs = []
                                    for msg in messages:
                                        if isinstance(msg, dict):
                                            if msg.get("title"):
                                                error_msgs.append(msg.get("title"))
                                            if msg.get("message"):
                                                error_msgs.append(msg.get("message"))
                                        elif isinstance(msg, str):
                                            error_msgs.append(msg)
                                    
                                    error_text = " | ".join(error_msgs[:3])  # Limit to first 3 messages
                                    if not error_text and log.get("exception"):
                                        # Extract first line of exception
                                        exception_lines = log.get("exception", "").split("\n")
                                        error_text = exception_lines[0] if exception_lines else "Unknown error"
                                    
                                    row_str = ", ".join(map(str, row_indexes[:5]))  # Show first 5 row indexes
                                    if len(row_indexes) > 5:
                                        row_str += f" ... (+{len(row_indexes) - 5} more)"
                                    
                                    append_log(crystal_upload, f"   Row {row_str}: {error_text[:200]}")
                        
                        if error_count > 20:
                            append_log(crystal_upload, f"   ... ({error_count - 20} more errors - check Data Import {data_import_name} for full details)")
                    
                    # Log common errors summary
                    if status == "Error":
                        append_log(crystal_upload, f"\n⚠️ Import Failed Completely - All records failed")
                    elif status == "Partial Success":
                        append_log(crystal_upload, f"\n⚠️ Partial Import - Some records failed. Review failed records above.")
                    elif status == "Success":
                        append_log(crystal_upload, f"\n✅ Full Import Success - All records imported successfully")
                    
                    break
                
                # Still pending, wait and check again
                time.sleep(check_interval)
                elapsed_time += check_interval
                
            except frappe.DoesNotExistError:
                append_log(crystal_upload, f"⚠️ Data Import {data_import_name} not found")
                break
            except Exception as e:
                append_log(crystal_upload, f"⚠️ Error checking import status: {str(e)[:200]}")
                time.sleep(check_interval)
                elapsed_time += check_interval
        
        # If we timed out waiting
        if elapsed_time >= max_wait_time:
            status_summary = get_import_status_summary(data_import_name)
            status = status_summary.get('status', 'Unknown')
            total = status_summary.get('total', 0)
            success = status_summary.get('success', 0)
            failed = status_summary.get('failed', 0)
            
            append_log(crystal_upload, f"\n⏱️ Import monitoring timed out after {max_wait_time // 60} minutes")
            append_log(crystal_upload, f"   Current Status: {status}")
            if total > 0:
                append_log(crystal_upload, f"   Progress: {success + failed}/{total} records processed")
            append_log(crystal_upload, f"   Use 'Refresh Import Status' button to check final status")
            append_log(crystal_upload, f"   Or check Data Import {data_import_name} manually")
    
    except Exception as e:
        try:
            crystal_upload = frappe.get_doc("Crystal Attendance Upload", crystal_upload_name)
            append_log(crystal_upload, f"❌ Error logging import results: {str(e)[:300]}")
        except:
            pass


@frappe.whitelist()
def refresh_import_status(crystal_upload_name):
    """Manually refresh import status - can be called from UI"""
    try:
        # Get the linked Data Import
        data_imports = frappe.get_all(
            "Data Import",
            filters={"custom_crystal_upload_ref": crystal_upload_name},
            fields=["name"],
            limit=1,
            order_by="creation desc"
        )
        
        if not data_imports:
            return {"error": "No Data Import found for this upload"}
        
        data_import_name = data_imports[0].name
        crystal_upload = frappe.get_doc("Crystal Attendance Upload", crystal_upload_name)
        
        status_summary = get_import_status_summary(data_import_name)
        status = status_summary.get("status", "Pending")
        
        append_log(crystal_upload, f"\n🔄 Manual Status Refresh:")
        append_log(crystal_upload, f"   Status: {status}")
        append_log(crystal_upload, f"   Total Records: {status_summary.get('total', 0)}")
        append_log(crystal_upload, f"   ✅ Successful: {status_summary.get('success', 0)}")
        append_log(crystal_upload, f"   ❌ Failed: {status_summary.get('failed', 0)}")
        
        # If complete, log full details
        if status in ["Success", "Partial Success", "Error", "Timed Out"]:
            # Get detailed logs for failures
            if status_summary.get("failed", 0) > 0:
                append_log(crystal_upload, f"\n📋 Failed Import Details:")
                failed_logs = get_import_logs_detailed(data_import_name, limit=50)
                
                error_count = 0
                for log in failed_logs:
                    if not log.get("success"):
                        error_count += 1
                        if error_count <= 20:
                            row_indexes = json.loads(log.get("row_indexes") or "[]")
                            messages = json.loads(log.get("messages") or "[]")
                            
                            error_msgs = []
                            for msg in messages:
                                if isinstance(msg, dict):
                                    if msg.get("title"):
                                        error_msgs.append(msg.get("title"))
                                    if msg.get("message"):
                                        error_msgs.append(msg.get("message"))
                                elif isinstance(msg, str):
                                    error_msgs.append(msg)
                            
                            error_text = " | ".join(error_msgs[:3])
                            if not error_text and log.get("exception"):
                                exception_lines = log.get("exception", "").split("\n")
                                error_text = exception_lines[0] if exception_lines else "Unknown error"
                            
                            row_str = ", ".join(map(str, row_indexes[:5]))
                            if len(row_indexes) > 5:
                                row_str += f" ... (+{len(row_indexes) - 5} more)"
                            
                            append_log(crystal_upload, f"   Row {row_str}: {error_text[:200]}")
                
                if error_count > 20:
                    append_log(crystal_upload, f"   ... ({error_count - 20} more errors - check Data Import {data_import_name} for full details)")
            
            # Log summary
            if status == "Error":
                append_log(crystal_upload, f"\n⚠️ Import Failed Completely - All records failed")
            elif status == "Partial Success":
                append_log(crystal_upload, f"\n⚠️ Partial Import - Some records failed. Review failed records above.")
            elif status == "Success":
                append_log(crystal_upload, f"\n✅ Full Import Success - All records imported successfully")
        else:
            append_log(crystal_upload, f"   ⏳ Import still in progress...")
        
        return {
            "status": status,
            "total": status_summary.get('total', 0),
            "success": status_summary.get('success', 0),
            "failed": status_summary.get('failed', 0)
        }
    
    except Exception as e:
        frappe.log_error(f"Error refreshing import status: {str(e)}")
        return {"error": str(e)}


def process_uploaded_file(doc, method):
    """Triggered when Crystal Attendance Upload is submitted"""
    try:
        # ------------------------
        # Step 1: Get uploaded file
        # ------------------------
        if not doc.crystal_format:
            frappe.throw("No file found in Crystal Format field.")

        file_doc = frappe.get_doc("File", {"file_url": doc.crystal_format})
        file_name = os.path.basename(file_doc.file_url)
        local_path = frappe.get_site_path("private", "files", file_name)

        append_log(doc, f"Step 1: Found raw file at {local_path}")

        # ------------------------
        # Step 2: Clean the file
        # ------------------------
        cleaned_dir = frappe.get_site_path("private", "files", "cleaned_reports")
        os.makedirs(cleaned_dir, exist_ok=True)
        cleaned_path = os.path.join(cleaned_dir, f"cleaned_{os.path.splitext(file_name)[0]}.xlsx")
        hzl = ["HZL SK MILL","HZL RD PASTEFILL","HZL Debari O&M","HZL Debari MH","HZL Zawar Stores","HZL SKM Shaft","HZL SKM MH","HZL SKM Conveyor","HZL RDM MH","HZL Ram MH","HZL Pyro O&M","HZL Kayad MH","HZL Debari MCTP", "Dariba CPP","HZL Dariba MH","HZL Chanderia MH","HZL Silver Pantnagar","HZL Pantnagar","HZL Haridwar","Agucha"]

        # Choose cleaning function based on Branch
        if doc.branch in ["Vedanta Jharsuguda P2","Vedanta Jharsuguda P1"]:
            clean_daily_inout14(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout14 (multi-punch merge) for Vedanta Plant II")

        elif doc.branch == "Vedanta Lanjigarh":
            clean_daily_inout24(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout24 for Lanjigarh")

            # doc.branch == "HZL Pantnagar" or doc.branch == "HZL Debari O&M" :
        elif doc.branch in hzl:
            clean_daily_inout4(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout4 for Rudrapur")
            
        elif doc.branch in ["DOLVI","JSW DOLVI","JSW Dolvi BF"]:
            clean_daily_inout13(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout13 for DOLVI")

        elif doc.branch == "Kakinada":
            clean_daily_inout11(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout11 for Kakinada")

        elif doc.branch in ["Balco", "Balco CH"]:
            clean_daily_inout10(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, f"Step 2: Used clean_daily_inout10 for Balco")

        elif doc.branch in ["STL Jharsuguda"]:
            clean_daily_inout2(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout2 for Jharsuguda")

        elif doc.branch in ["Bellari obp2","Bellari (JVML & STEEL)","JVML Bellari - VEIL","JSW Bellari"]:
            clean_daily_inout30(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout30 for Bellary")

        elif doc.branch in ["KCL MUNDRA - VEIL"]:
            clean_daily_inout30_2(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout30_2 for KCL Mundra")

        elif doc.branch in ["PARADIP", "JSW Paradeep"]:
            clean_daily_inout29(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout29 for PARADIP")

        elif doc.branch in ["Tata Kalinganagar", "Tata Steel Jamshedpur", "JAMSHEDPUR"]:
            clean_daily_inout7(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout7 for Tata")

        elif doc.branch in ["Tata Angul"]:
            clean_daily_inout7_1(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout7 for Tata Angul")

        elif doc.branch in ["JSW Jharsuguda"]:
            clean_daily_inout12(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Use JSW Jharsugudad clean_daily_inout12 for JSW Jharsuguda")

        elif doc.branch in ["Jsol Angul", "JSPL Angul Sinter O&M", "Jspl & Jsol angul", "JSPL Angul BF 2 JSOL - VEIL"]:
            clean_daily_inout7_2(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout7 for Tata jspl & jsol Angul")

        elif doc.branch in ["hindalco lapanga", "Hindalco Lapanga", "HINDALCO LAPANGA"]:
            append_log(doc, "Step 2: Starting clean_daily_inout15 (Scrum Report format) for Hindalco Lapanga")
            try:
                import sys
                from io import StringIO

                # Capture stdout to log it
                old_stdout = sys.stdout
                sys.stdout = captured_output = StringIO()

                clean_daily_inout15(
                    input_path=local_path,
                    output_path=cleaned_path,
                    company=doc.company,
                    branch=doc.branch
                )

                # Restore stdout and log captured output
                sys.stdout = old_stdout
                output = captured_output.getvalue()

                # Log the debug output
                for line in output.split('\n'):
                    if line.strip():
                        append_log(doc, f"  {line}")

                append_log(doc, "Step 2: ✅ Clean completed successfully")

            except Exception as e:
                # Restore stdout
                sys.stdout = old_stdout

                # Log any captured output before the error
                output = captured_output.getvalue()
                if output:
                    append_log(doc, "  Debug output before error:")
                    for line in output.split('\n')[-50:]:  # Last 50 lines
                        if line.strip():
                            append_log(doc, f"  {line}")

                append_log(doc, f"❌ Error in clean_daily_inout15: {str(e)}")
                raise

        elif doc.branch in ["Walunj OFC Aurangabad","stl aurangabad ofc", "STL Aurangabad OFC"]:
            clean_daily_inout_matrix(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout_matrix for Matrix Report format")

        elif doc.branch in ["STL Shendra", "STL Walunj", "stl walunj", "stl shendra"]:
            clean_daily_inout_matrix_2(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout_matrix_2 for Monthly Status Report format")

        elif doc.branch in ["polycab", "Polycab OFC Halol", "Polycab WRM Halol"]:
            clean_daily_inout16(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout16 for Polycab rptDAttendanceReg format")

        elif doc.branch in ["Hirakud FRP","Hirakud Smelter"]:
            clean_daily_inout17(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout17 for Hirakud FRP row-based format")

        elif doc.branch in [""]:
            clean_daily_inout18(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_daily_inout18 for Hirakud Smelter PUNCH TIMING format")

        elif doc.branch in ["AMNS Surat"]:
            clean_daily_inout_pdf(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch,
                pdf_method="auto"
            )
            append_log(doc, "Step 2: Used clean_manhour_vertical for AMNS Surat ManHour Report (PDF)")

        else:
            clean_crystal_excel(
                input_path=local_path,
                output_path=cleaned_path,
                company=doc.company,
                branch=doc.branch
            )
            append_log(doc, "Step 2: Used clean_crystal_excel for default format")

        append_log(doc, f"Step 2: Cleaned file saved at {cleaned_path}")

        # ------------------------
        # Step 3: Create Data Import doc
        # ------------------------
        with open(cleaned_path, "rb") as f:
            file_data = f.read()
        cleaned_file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": os.path.basename(cleaned_path),
            "is_private": 1,
            "content": file_data
        })
        cleaned_file_doc.save(ignore_permissions=True)
        frappe.db.commit()

        data_import = frappe.get_doc({
            "doctype": "Data Import",
            "import_type": "Insert New Records",
            "reference_doctype": "Attendance",
            "import_file": cleaned_file_doc.file_url,
            "submit_after_import": 1,   # set to 1 if you want Attendance auto-submitted
            "mute_emails": 1
        })
        data_import.save(ignore_permissions=True)
        data_import.db_set("custom_crystal_upload_ref", doc.name, update_modified=False)

        frappe.db.commit()

        append_log(doc, f"Step 3: Data Import {data_import.name} created and linked")

        # ------------------------
        # Step 4: Trigger the Import
        # ------------------------
        try:
            frappe.flags.current_crystal_upload = doc.name

            start_import(data_import.name)
            append_log(doc, f"Step 4: Import started for {data_import.name}")
            append_log(doc, f"   Monitoring import status...")
            
            # Enqueue background job to monitor and log import results
            frappe.enqueue(
                "hr_reports.utils.attendance_flow.log_import_results",
                crystal_upload_name=doc.name,
                data_import_name=data_import.name,
                queue="default",
                timeout=600  # 10 minutes timeout
            )
            
        except Exception as e:
            append_log(doc, f"❌ Import failed to start: {str(e)}")
            import traceback
            append_log(doc, f"   Traceback: {traceback.format_exc()[:500]}")
            raise
        finally:
            frappe.flags.current_crystal_upload = None  # always clear


        # ------------------------
        # Done
        # ------------------------
        append_log(doc, "✅ Process complete: Upload → Clean → Auto Import triggered")
        append_log(doc, "   Import results will be logged here once processing completes...")

    except Exception as e:
        append_log(doc, f"❌ ERROR: {str(e)}")
        raise


def cancel_uploaded_file(doc, method):
    """Triggered when Crystal Attendance Upload is cancelled"""
    try:
        # Debug: Log that function was called
        frappe.logger().info(f"[CANCEL HOOK] cancel_uploaded_file called for {doc.name} (docstatus: {doc.docstatus})")
        append_log(doc, f"Cancel triggered → rolling back imported attendance for {doc.name}")
        
        deleted_count = 0
        failed_count = 0

        # 1. Get total count first
        total_count = frappe.db.count("Attendance", {"custom_crystal_upload_ref": doc.name})
        append_log(doc, f"Found {total_count} Attendance records to delete")
        
        if total_count == 0:
            append_log(doc, "No Attendance records found with this upload reference")
        elif total_count > 5000:
            # For very large datasets, use bulk SQL deletion for better performance
            append_log(doc, f"Large dataset detected ({total_count} records). Using bulk SQL deletion for efficiency...")
            try:
                # First, try to cancel submitted records in batches
                submitted_count = frappe.db.count("Attendance", {
                    "custom_crystal_upload_ref": doc.name,
                    "docstatus": 1
                })
                
                if submitted_count > 0:
                    append_log(doc, f"Cancelling {submitted_count} submitted records...")
                    # Get submitted records in batches and cancel them
                    cancel_batch_size = 500
                    cancel_start = 0
                    while cancel_start < submitted_count:
                        submitted_att = frappe.get_all(
                            "Attendance",
                            filters={
                                "custom_crystal_upload_ref": doc.name,
                                "docstatus": 1
                            },
                            fields=["name"],
                            limit_start=cancel_start,
                            limit_page_length=cancel_batch_size
                        )
                        if not submitted_att:
                            break
                        for att in submitted_att:
                            try:
                                att_doc = frappe.get_doc("Attendance", att.name)
                                att_doc.cancel()
                                frappe.db.commit()
                            except:
                                frappe.db.rollback()
                        cancel_start += cancel_batch_size
                
                # Bulk delete using SQL
                result = frappe.db.sql("""
                    DELETE FROM `tabAttendance` 
                    WHERE custom_crystal_upload_ref = %s
                """, (doc.name,), as_dict=False)
                frappe.db.commit()
                deleted_count = total_count
                append_log(doc, f"✅ Bulk deleted {deleted_count} Attendance records via SQL")
            except Exception as bulk_err:
                append_log(doc, f"⚠️ Bulk deletion failed, falling back to individual deletion: {str(bulk_err)[:200]}")
                # Fall through to individual deletion
                total_count = frappe.db.count("Attendance", {"custom_crystal_upload_ref": doc.name})
                if total_count > 0:
                    # Process in batches using pagination
                    batch_size = 1000
                    batch_num = 0

                    while True:
                        # Get batch of attendance records (always from start since we're deleting)
                        attendances = frappe.get_all(
                            "Attendance",
                            filters={"custom_crystal_upload_ref": doc.name},
                            fields=["name", "docstatus"],
                            limit_start=0,  # Always query from 0 since records are being deleted
                            limit_page_length=batch_size,
                            order_by="name"
                        )

                        if not attendances:
                            break

                        batch_num += 1
                        append_log(doc, f"Processing batch {batch_num}: {len(attendances)} records (Total deleted so far: {deleted_count}/{total_count})")

                        for att in attendances:
                            try:
                                # Check if document still exists
                                if not frappe.db.exists("Attendance", att.name):
                                    continue

                                att_doc = frappe.get_doc("Attendance", att.name)

                                # Cancel if submitted
                                if att_doc.docstatus == 1:
                                    try:
                                        att_doc.cancel()
                                        frappe.db.commit()
                                    except Exception as cancel_err:
                                        append_log(doc, f"⚠️ Could not cancel {att.name}: {str(cancel_err)[:200]}")
                                        # Continue to try deletion anyway

                                # Delete the attendance
                                frappe.delete_doc("Attendance", att.name, force=1, ignore_permissions=True)
                                frappe.db.commit()
                                deleted_count += 1

                                if deleted_count % 100 == 0:  # Log progress every 100 records
                                    append_log(doc, f"Progress: Deleted {deleted_count}/{total_count} attendances...")

                            except frappe.DoesNotExistError:
                                # Already deleted, skip
                                continue
                            except Exception as e:
                                failed_count += 1
                                error_msg = str(e)[:200]

                                # Try SQL-based deletion as fallback
                                try:
                                    frappe.db.sql("""
                                        DELETE FROM `tabAttendance`
                                        WHERE name = %s
                                    """, (att.name,))
                                    frappe.db.commit()
                                    deleted_count += 1
                                    failed_count -= 1
                                except Exception as sql_err:
                                    # Log but continue
                                    if failed_count <= 10:  # Only log first 10 failures to avoid spam
                                        append_log(doc, f"❌ Failed to remove {att.name}: {str(sql_err)[:200]}")
                                    frappe.db.rollback()
                                continue

                        # Commit after each batch
                        frappe.db.commit()

                    append_log(doc, f"✅ Deleted {deleted_count} Attendance records (Failed: {failed_count} out of {total_count} total)")
        else:
            # For smaller datasets (< 5000), use individual deletion with pagination
            batch_size = 1000
            batch_num = 0

            while True:
                # Get batch of attendance records (always from start since we're deleting)
                attendances = frappe.get_all(
                    "Attendance",
                    filters={"custom_crystal_upload_ref": doc.name},
                    fields=["name", "docstatus"],
                    limit_start=0,  # Always query from 0 since records are being deleted
                    limit_page_length=batch_size,
                    order_by="name"
                )

                if not attendances:
                    break

                batch_num += 1
                append_log(doc, f"Processing batch {batch_num}: {len(attendances)} records (Total deleted so far: {deleted_count}/{total_count})")

                for att in attendances:
                    try:
                        # Check if document still exists
                        if not frappe.db.exists("Attendance", att.name):
                            continue

                        att_doc = frappe.get_doc("Attendance", att.name)

                        # Cancel if submitted
                        if att_doc.docstatus == 1:
                            try:
                                att_doc.cancel()
                                frappe.db.commit()
                            except Exception as cancel_err:
                                append_log(doc, f"⚠️ Could not cancel {att.name}: {str(cancel_err)[:200]}")
                                # Continue to try deletion anyway

                        # Delete the attendance
                        frappe.delete_doc("Attendance", att.name, force=1, ignore_permissions=True)
                        frappe.db.commit()
                        deleted_count += 1

                        if deleted_count % 100 == 0:  # Log progress every 100 records
                            append_log(doc, f"Progress: Deleted {deleted_count}/{total_count} attendances...")

                    except frappe.DoesNotExistError:
                        # Already deleted, skip
                        continue
                    except Exception as e:
                        failed_count += 1
                        error_msg = str(e)[:200]

                        # Try SQL-based deletion as fallback
                        try:
                            frappe.db.sql("""
                                DELETE FROM `tabAttendance`
                                WHERE name = %s
                            """, (att.name,))
                            frappe.db.commit()
                            deleted_count += 1
                            failed_count -= 1
                        except Exception as sql_err:
                            # Log but continue
                            if failed_count <= 10:  # Only log first 10 failures to avoid spam
                                append_log(doc, f"❌ Failed to remove {att.name}: {str(sql_err)[:200]}")
                            frappe.db.rollback()
                        continue

                # Commit after each batch
                frappe.db.commit()

            append_log(doc, f"✅ Deleted {deleted_count} Attendance records (Failed: {failed_count} out of {total_count} total)")
    
        # 2. Delete Data Import if exists
        data_imports = frappe.get_all(
            "Data Import",
            filters={"custom_crystal_upload_ref": doc.name},
            pluck="name",
            limit_page_length=1000
        )
        
        append_log(doc, f"Found {len(data_imports)} Data Import records to delete")
        
        for di in data_imports:
            try:
                if frappe.db.exists("Data Import", di):
                    frappe.delete_doc("Data Import", di, force=1, ignore_permissions=True)
                    frappe.db.commit()
                    append_log(doc, f"Removed Data Import {di}")
            except Exception as e:
                append_log(doc, f"❌ Failed to remove Data Import {di}: {str(e)[:200]}")

        # 3. Remove cleaned report file
        try:
            cleaned_dir = frappe.get_site_path("private", "files", "cleaned_reports")
            if os.path.exists(cleaned_dir):
                for f in os.listdir(cleaned_dir):
                    if f"cleaned_{doc.name}" in f or f"cleaned_{os.path.splitext(doc.name)[0]}" in f:
                        try:
                            file_path = os.path.join(cleaned_dir, f)
                            os.remove(file_path)
                            append_log(doc, f"Removed cleaned file {f}")
                        except Exception as file_err:
                            append_log(doc, f"⚠️ Could not remove file {f}: {str(file_err)[:100]}")
        except Exception as dir_err:
            append_log(doc, f"⚠️ Could not access cleaned_reports directory: {str(dir_err)[:100]}")

        append_log(doc, f"✅ Cancel complete: {deleted_count} Attendance records + {len(data_imports)} Data Imports removed")

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        append_log(doc, f"❌ Cancel error: {str(e)[:500]}")
        append_log(doc, f"Traceback: {error_trace[:1000]}")
        frappe.log_error(error_trace, f"Crystal Attendance Upload Cancel Error: {doc.name}")
        # Don't raise - allow cancellation to proceed even if cleanup fails

def after_insert_attendance(doc, method):
    """Automatically stamp Attendance with current Crystal Upload ref if available"""
    if frappe.flags.current_crystal_upload:
        frappe.logger().debug(f"[DEBUG] Stamping {doc.name} with {frappe.flags.current_crystal_upload}")
        doc.db_set("custom_crystal_upload_ref", frappe.flags.current_crystal_upload, update_modified=False)
    else:
        frappe.logger().debug(f"[DEBUG] No crystal_upload_ref set for {doc.name}")
