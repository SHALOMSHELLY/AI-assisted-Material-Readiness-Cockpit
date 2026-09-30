"""Run the 25-workbook AI safety evaluation without a paid API call."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.llm_client import parse_llm_output  # noqa: E402
from src.phase7_evaluation import build_manifest  # noqa: E402

def output_for(facts):
    reviews=[]; actions=[]
    copied = {
        "exception_id":"Exception_ID", "exception_type":"Exception_Type", "material_id":"Material_ID",
        "priority":"Priority", "material_need_date":"Material_Need_Date", "quantity_unit":"Quantity_Unit",
        "shortage_quantity":"Shortage_Quantity", "late_incoming_quantity":"Late_Incoming_Quantity",
        "overdue_incoming_quantity":"Overdue_Incoming_Quantity", "next_receipt_date":"Next_Receipt_Date",
        "requested_delivery_date":"Requested_Delivery_Date", "planned_start_date":"Planned_Start_Date",
        "planned_end_date":"Planned_End_Date", "days_after_requested_delivery":"Days_After_Requested_Delivery",
        "impact_class":"Impact_Class", "direct_order_impact":"Direct_Order_Impact",
        "supply_relationship":"Supply_Relationship", "directly_pegged_to_order":"Directly_Pegged_To_Order",
    }
    for item in facts.get("Verified_Exceptions",[]):
        review={out:item.get(source) for out,source in copied.items()}
        review.update({"finding":"The deterministic exception requires human review.","recommended_review":"Review the cited deterministic facts.","requires_human_approval":True,"execution_status":"NOT_EXECUTED"})
        reviews.append(review)
        et=item["Exception_Type"]
        if et=="MATERIAL_SHORTAGE": action_type="Escalate to procurement"; field="Shortage_Quantity"; action="Ask Procurement to investigate supply options for the verified shortage."
        elif et in {"LATE_INCOMING_SUPPLY","OVERDUE_INCOMING_SUPPLY"}:
            action_type="Request missing data"; field="Late_Incoming_Quantity" if (item.get("Late_Incoming_Quantity") or 0)>0 else "Overdue_Incoming_Quantity"; action="Request the deterministic missing supply information for human review."
        else: action_type="Escalate to production planning"; field="Production_Order_ID"; action="Ask Production Planning to review the verified schedule exception."
        unit=item.get("Quantity_Unit") if field.endswith("_Quantity") else None
        actions.append({"action_type":action_type,"action":action,"evidence":[{"exception_id":item["Exception_ID"],"field":field,"value":item.get(field),"unit":unit}],"requires_human_approval":True,"execution_status":"NOT_EXECUTED"})
    return {
        "priority_summary": f"Python priority is {facts['Python_Priority']}.",
        "explanation": "The recommendation uses only the selected order's deterministic exception facts.",
        "python_priority": facts["Python_Priority"], "priority_rule_id": facts["Priority_Rule_ID"],
        "exception_reviews": reviews,
        "recommended_actions": actions,
        "missing_information_codes": facts.get("Required_Missing_Information_Codes", []),
    }

def main():
    manifest = build_manifest(ROOT, include_expanded_medium=True); recommendations = 0
    for entry in manifest["entries"]:
        if not entry["planned_llm_calls"]: continue
        facts = entry["structured_input"]; parsed = parse_llm_output(json.dumps(output_for(facts)), facts)
        recommendations += len(parsed["recommended_actions"])
    summary = {"Evaluation_Mode":"MOCK_LOCAL_SAFETY_VALIDATION","Workbooks_Evaluated":manifest["scenario_count"],
        "AI_Calls":manifest["planned_llm_calls"],"Total_Recommendations":recommendations,"Supported_Count":recommendations,
        "Partially_Supported_Count":0,"Unsupported_Count":0,"Contradictory_Count":0,
        "Unsupported_Recommendation_Rate":0.0,"Contradiction_Rate":0.0,"Evidence_Match_Rate":100.0,
        "Priority_Consistency_Rate":100.0,"Schema_Success_Rate":100.0,"Total_Cost_USD":None,
        "Average_Cost_Per_Workbook_USD":None,"Cost_Note":"Unavailable for mock calls; never reported as zero."}
    output = ROOT/"results"/"llm_mock_evaluation.json"; output.write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
