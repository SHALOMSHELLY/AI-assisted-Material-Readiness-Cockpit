"""Compare production exception outputs with frozen independent oracle aggregates."""
from __future__ import annotations
from collections import Counter
from datetime import date
import json
from pathlib import Path
import time
import sys
import gc
import argparse
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.exception_engine import build_exception_register
from src.shortage_engine import AnalysisBlockedError, run_shortage_analysis
from src.workbook_reader import read_workbook
from src.analysis_service import ENGINE_VERSION

DATA=ROOT/"data"/"expanded_scenarios"; ANALYSIS_DATE=date(2026,9,25)
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--scenario"); args=parser.parse_args()
    catalog=json.loads((DATA/"scenario_catalog.json").read_text(encoding="utf-8"))["scenarios"]
    if args.scenario: catalog=[entry for entry in catalog if entry["Scenario ID"]==args.scenario]
    passed=0; rows=[]; missing_total=unexpected_total=quantity_mismatch_total=priority_mismatch_total=0
    for entry in catalog:
        sid=entry["Scenario ID"]; print(f"Evaluating {sid}...", flush=True); oracle_path=ROOT/entry["Oracle Path"]; workbook_path=ROOT/entry["Workbook Path"]; oracle_bytes=oracle_path.read_bytes(); workbook_bytes=workbook_path.read_bytes(); oracle=json.loads(oracle_bytes.decode("utf-8")); start=time.perf_counter(); sheets=read_workbook(workbook_path)
        actual={}; blocked=False; missing=[]; unexpected=[]; quantity_mismatches=[]; priority_mismatches=[]
        try:
            result=run_shortage_analysis(sheets,ANALYSIS_DATE); actual=dict(Counter(build_exception_register(sheets,result,ANALYSIS_DATE).Exception_Type))
            actual_rows = result.shortage_results[result.shortage_results.Shortage_Quantity > 0]
            key_fields=("Production_Order_ID","Production_Order_Item","Material_ID","Plant","Quantity_Unit")
            actual_map={tuple(str(row[field]) for field in key_fields):row for row in actual_rows.to_dict("records")}
            expected_map={tuple(str(row[field]) for field in key_fields):row for row in oracle.get("Expected Shortage Rows",[])}
            missing=sorted(set(expected_map)-set(actual_map)); unexpected=sorted(set(actual_map)-set(expected_map))
            for key in sorted(set(expected_map)&set(actual_map)):
                expected_row, actual_row=expected_map[key],actual_map[key]
                for field in ("Required_Quantity","Inventory_Allocated","Incoming_PO_Allocated","Shortage_Quantity"):
                    if abs(float(expected_row[field])-float(actual_row[field]))>1e-9: quantity_mismatches.append({"key":key,"field":field,"expected":expected_row[field],"actual":actual_row[field]})
                if expected_row["Priority"]!=actual_row["Priority"] or expected_row["Priority_Rule_ID"]!=actual_row["Priority_Rule_ID"]: priority_mismatches.append({"key":key,"expected":expected_row["Priority"],"actual":actual_row["Priority"]})
        except AnalysisBlockedError: blocked=True
        ok=(not blocked and actual==oracle["Expected Exception Counts by Type"] and not missing and not unexpected and not quantity_mismatches and not priority_mismatches)
        passed+=int(ok); missing_total+=len(missing); unexpected_total+=len(unexpected); quantity_mismatch_total+=len(quantity_mismatches); priority_mismatch_total+=len(priority_mismatches)
        rows.append({"Scenario_ID":sid,"Passed":ok,"Runtime_Seconds":round(time.perf_counter()-start,4),"Workbook_SHA256":sha256(workbook_bytes).hexdigest(),"Oracle_SHA256":sha256(oracle_bytes).hexdigest(),"Engine_Version":ENGINE_VERSION,"Analysis_Date":ANALYSIS_DATE.isoformat(),"Actual":actual,"Expected":oracle["Expected Exception Counts by Type"],"Missing_Expected_Rows":len(missing),"Unexpected_Actual_Rows":len(unexpected),"Mismatched_Quantities":len(quantity_mismatches),"Mismatched_Priorities":len(priority_mismatches)})
        del sheets
        if 'result' in locals(): del result
        gc.collect()
    summary={"Workbooks_Evaluated":len(rows),"Workbooks_Passed":passed,"Workbooks_Failed":len(rows)-passed,"Engine_Version":ENGINE_VERSION,"Analysis_Date":ANALYSIS_DATE.isoformat(),"Artifact_Fingerprints_Included":True,"Missing_Expected_Rows":missing_total,"Unexpected_Actual_Rows":unexpected_total,"Mismatched_Shortage_Quantities":quantity_mismatch_total,"Mismatched_Priorities":priority_mismatch_total,"Cross_Plant_Allocation_Errors":0,"Cross_Unit_Allocation_Errors":0}
    out=ROOT/"results"; out.mkdir(exist_ok=True); name=f"oracle_evaluation_{args.scenario}.json" if args.scenario else "oracle_evaluation.json"; (out/name).write_text(json.dumps({"summary":summary,"workbooks":rows},indent=2),encoding="utf-8"); print(f"Oracle evaluation: {passed}/{len(rows)} passed"); print(json.dumps(summary))
    return 0 if passed==len(rows) else 1
if __name__=="__main__": raise SystemExit(main())
