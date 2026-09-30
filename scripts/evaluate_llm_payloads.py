"""Build bounded, no-cost order payload metrics for all formal workbooks."""

from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ai_action_plan import build_order_ai_input
from src.analysis_service import analyze_workbook_content


ANALYSIS_DATE = date(2026, 9, 25)
RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _stats(rows, field):
    values = [row[field] for row in rows]
    return {"average": statistics.mean(values), "median": statistics.median(values), "maximum": max(values)}


def main() -> int:
    catalog = json.loads((ROOT / "data/expanded_scenarios/scenario_catalog.json").read_text(encoding="utf-8"))["scenarios"]
    rows = []
    for item in catalog:
        scenario_id = item["Scenario ID"]
        analyzed = analyze_workbook_content((ROOT / item["Workbook Path"]).read_bytes(), ANALYSIS_DATE)
        summary = analyzed.order_summary
        if summary.empty:
            facts = analyzed.result.shortage_results
            selected = facts.assign(_rank=facts.Priority.map(RANK).fillna(99)).sort_values(
                ["_rank", "Shortage_Quantity"], ascending=[True, False], kind="stable").iloc[0]
            order_id = str(selected.Source_Sales_Order_ID or selected.Production_Order_ID)
            order_item = str(selected.Source_Sales_Order_Item or selected.Production_Order_Item)
        else:
            selected = summary.assign(_rank=summary.Highest_Priority.map(RANK).fillna(99)).sort_values(
                ["_rank", "Total_Shortage_Quantity"], ascending=[True, False], kind="stable").iloc[0]
            order_id, order_item = str(selected.Sales_Order_ID), str(selected.Sales_Order_Item)
        payload = build_order_ai_input(order_id, order_item, analyzed.exceptions,
                                       analyzed.result.shortage_results, analyzed.sheets)
        rows.append({
            "Workbook_ID": scenario_id, "Scale": scenario_id[0],
            "Selected_Order": f"{order_id}/{order_item}",
            "Payload_Bytes": payload["payload_json_bytes"],
            "Estimated_Input_Tokens": payload["estimated_input_tokens"],
            "Material_Detail_Count": len(payload["affected_material_facts"]),
            "PO_Detail_Count": len(payload["related_po_details"]),
            "Payload_Truncated": payload["llm_payload"]["payload_truncated"],
        })
    summary = {"workbooks": len(rows), "payload_bytes": _stats(rows, "Payload_Bytes"),
               "estimated_input_tokens": _stats(rows, "Estimated_Input_Tokens"),
               "by_scale": {scale: {"count": len(group), "payload_bytes": _stats(group, "Payload_Bytes"),
                                    "estimated_input_tokens": _stats(group, "Estimated_Input_Tokens")}
                            for scale in "SML" for group in [[row for row in rows if row["Scale"] == scale]]}}
    output = ROOT / "results"; output.mkdir(exist_ok=True)
    (output / "llm_payload_evaluation.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    with (output / "llm_payload_evaluation.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print(json.dumps(summary, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
