"""Build catalog and frozen independent oracles without importing production engines."""
from __future__ import annotations

from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "expanded_scenarios"
ANALYSIS_DATE = date(2026, 9, 25)
sys.path.insert(0, str(ROOT))
from data.expanded_scenarios.generators import ALL_SCENARIOS  # noqa: E402
from data.expanded_scenarios.generators.expected_oracle import build_full_expected  # noqa: E402

ACTIVE_PROD = {"CREATED", "RELEASED", "PARTIALLY_CONFIRMED"}
ACTIVE_ORDER = {"OPEN", "CREATED", "RELEASED", "PARTIALLY_CONFIRMED"}
ACTIVE_PO = {"OPEN", "PARTIALLY_RECEIVED"}

def text(value):
    return None if value is None or pd.isna(value) else str(value)

def priority(shortage, need):
    days = (need - ANALYSIS_DATE).days
    if shortage > 0 and days <= 2: return "Critical"
    if shortage > 0 and days <= 7: return "High"
    if shortage > 0: return "Medium"
    return "Low"

def independent_oracle(path: Path) -> dict:
    sheets = pd.read_excel(path, sheet_name=None)
    missing = sorted(set(("Orders", "BOM", "Inventory", "Incoming_PO", "Production_Orders")) - set(sheets))
    errors = [f"MISSING_SHEET:{name}" for name in missing]
    if not missing and sheets["Inventory"].duplicated(["Material_ID", "Plant", "Storage_Location", "Stock_Type", "Base_Unit"]).any():
        errors.append("DUPLICATE_KEY:Inventory")
    base = {"Expected Validation Outcome": "BLOCKED" if errors else "PASS", "Expected Data Error Codes": errors,
            "Whether Analysis Must Be Blocked": bool(errors)}
    if errors: return {**base, "Expected Exception Counts by Type": {}, "Expected Exception Total": 0}
    orders, bom, inv, pos, prods = (sheets[n] for n in ("Orders", "BOM", "Inventory", "Incoming_PO", "Production_Orders"))
    inv_pools = {}
    for key, group in inv[inv.Stock_Type.astype(str).str.upper() == "UNRESTRICTED"].groupby(["Material_ID", "Plant", "Base_Unit"]):
        inv_pools[tuple(map(str, key))] = max(0.0, float(group.Quantity.sum()) - float(group.Safety_Stock.max()))
    receipts = []
    overdue = 0
    for row in pos.itertuples():
        active = str(row.PO_Status).upper() in ACTIVE_PO and not bool(row.Deletion_Flag) and not bool(row.Completely_Delivered_Flag) and float(row.Open_Quantity) > 0
        if not active: continue
        receipt_date = pd.Timestamp(row.Expected_Receipt_Date).date()
        if receipt_date < ANALYSIS_DATE: overdue += 1
        receipts.append({"key": (str(row.Material_ID), str(row.Plant), str(row.Quantity_Unit)), "date": receipt_date,
                         "qty": float(row.Open_Quantity), "overdue": receipt_date < ANALYSIS_DATE})
    requirements = []
    for prod in prods.itertuples():
        if str(prod.Order_Status).upper() not in ACTIVE_PROD or float(prod.Remaining_Quantity) <= 0: continue
        need = pd.Timestamp(prod.Planned_Start_Date).date()
        valid_from = pd.to_datetime(bom.Valid_From).apply(lambda value: value.date() if pd.notna(value) else None)
        valid_to = pd.to_datetime(bom.Valid_To).apply(lambda value: value.date() if pd.notna(value) else None)
        effective = bom[(bom.Parent_Product_ID.astype(str) == str(prod.Product_ID)) & (bom.Plant.astype(str) == str(prod.Plant)) & (valid_from <= need) & (valid_to.isna() | valid_to.apply(lambda value: value is not None and value >= need))]
        for component in effective.itertuples():
            requirements.append({"so": text(prod.Source_Sales_Order_ID), "so_item": text(prod.Source_Sales_Order_Item),
                "po": str(prod.Production_Order_ID), "po_item": str(prod.Production_Order_Item), "product": str(prod.Product_ID),
                "material": str(component.Component_Material_ID), "plant": str(prod.Plant), "unit": str(component.Component_Unit), "need": need,
                "required": float(prod.Remaining_Quantity) * float(component.Component_Quantity) / float(component.Base_Quantity)})
    requirements.sort(key=lambda r: (r["need"], r["po"], r["po_item"], r["material"]))
    exception_types = Counter(); priorities = Counter(); affected_orders=set(); affected_prods=set(); affected_materials=set(); shortage_total=0.0
    for req in requirements:
        key=(req["material"], req["plant"], req["unit"]); need=req["required"]; allocated=min(need, inv_pools.get(key,0)); inv_pools[key]=inv_pools.get(key,0)-allocated; remaining=need-allocated
        matching=sorted([r for r in receipts if r["key"]==key and not r["overdue"] and r["date"]<=req["need"] and r["qty"]>0], key=lambda r:r["date"])
        for receipt in matching:
            take=min(remaining,receipt["qty"]); receipt["qty"]-=take; remaining-=take
            if remaining<=0: break
        shortage=max(0,remaining)
        if shortage>0:
            exception_types["MATERIAL_SHORTAGE"]+=1; shortage_total+=shortage; priorities[priority(shortage,req["need"])]+=1
            if req["so"]: affected_orders.add(req["so"])
            affected_prods.add(req["po"]); affected_materials.add(req["material"])
        if any(r["key"]==key and not r["overdue"] and r["date"]>req["need"] and r["qty"]>0 for r in receipts): exception_types["LATE_INCOMING_SUPPLY"]+=1
        if any(r["key"]==key and r["overdue"] and r["qty"]>0 for r in receipts): exception_types["OVERDUE_INCOMING_SUPPLY"]+=1
    linked={(text(r.Source_Sales_Order_ID),text(r.Source_Sales_Order_Item)) for r in prods.itertuples() if text(r.Source_Sales_Order_ID) and ((str(r.Order_Status).upper() in ACTIVE_PROD and float(r.Remaining_Quantity)>0) or float(r.Remaining_Quantity)<=0 or str(r.Order_Status).upper() in {"CONFIRMED","COMPLETED","CLOSED","TECO"})}
    for row in orders.itertuples():
        if str(row.Order_Status).upper() in ACTIVE_ORDER and float(row.Requested_Quantity)>0 and (text(row.Sales_Order_ID),text(row.Sales_Order_Item)) not in linked:
            exception_types["UNSCHEDULED_ORDER"]+=1; affected_orders.add(str(row.Sales_Order_ID))
    backlog=0; planned_after=0; zero_buffer=0
    due_dates={(text(r.Sales_Order_ID),text(r.Sales_Order_Item)):pd.Timestamp(r.Requested_Delivery_Date).date() for r in orders.itertuples()}
    for row in prods.itertuples():
        if str(row.Order_Status).upper() not in ACTIVE_PROD or float(row.Remaining_Quantity)<=0: continue
        end=pd.Timestamp(row.Planned_End_Date).date()
        if end<ANALYSIS_DATE: backlog+=1
        key=(text(row.Source_Sales_Order_ID),text(row.Source_Sales_Order_Item))
        if key in due_dates:
            if end>due_dates[key]: planned_after+=1
            elif end==due_dates[key]: zero_buffer+=1
    exception_types["PRODUCTION_BACKLOG"] += backlog
    exception_types["PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY"] += planned_after
    exception_types["ZERO_SCHEDULE_BUFFER"] += zero_buffer
    exception_types["OVERDUE_INCOMING_PO"] += overdue
    exception_types += Counter()
    counts={k:v for k,v in exception_types.items() if v}
    return {**base, "Expected Exception Counts by Type": counts, "Expected Affected Sales Orders": sorted(affected_orders),
            "Expected Affected Production Orders": sorted(affected_prods), "Expected Affected Materials": sorted(affected_materials),
            "Expected Key Shortage Quantities": {"Total": shortage_total}, "Expected Priorities": dict(priorities),
            "Expected Responsible Roles": sorted(({"Procurement"} if counts.get("MATERIAL_SHORTAGE") or counts.get("OVERDUE_INCOMING_PO") or counts.get("LATE_INCOMING_SUPPLY") or counts.get("OVERDUE_INCOMING_SUPPLY") else set()) | ({"Production Planning"} if counts.get("UNSCHEDULED_ORDER") or counts.get("PRODUCTION_BACKLOG") or counts.get("PLANNED_COMPLETION_AFTER_REQUESTED_DELIVERY") or counts.get("ZERO_SCHEDULE_BUFFER") else set())),
            "Expected Unscheduled Orders": counts.get("UNSCHEDULED_ORDER",0), "Expected Backlog Production Orders": counts.get("PRODUCTION_BACKLOG",0),
            "Expected Overdue Incoming Cases": counts.get("OVERDUE_INCOMING_PO",0), "Expected Late Incoming Cases": counts.get("LATE_INCOMING_SUPPLY",0),
            "Expected Order-Level Highest Priority": "See per-scenario JSON evidence", "Expected Exception Total": sum(counts.values())}

def main():
    oracle_dir=DATA/"expected"/"scenarios"; oracle_dir.mkdir(parents=True, exist_ok=True); catalog=[]; csv_rows=[]
    for sid, scenario in sorted(ALL_SCENARIOS.items()):
        path=DATA/"generated"/scenario.category/f"{sid}.xlsx"; oracle=independent_oracle(path); oracle["Scenario ID"]=sid
        descriptions = {row["Component_Material_ID"]: (row.get("Component_Material_Description", row["Component_Material_ID"]), row.get("Material_Category", "Not classified")) for row in scenario.sheets["BOM"]}
        expected_rows = []
        for row in build_full_expected(scenario):
            if row["Shortage_Quantity"] <= 0: continue
            description, category = descriptions.get(row["Material_ID"], (row["Material_ID"], "Not classified"))
            expected_rows.append({**row, "Material_Description": description, "Material_Category": category})
        oracle["Expected Shortage Rows"] = expected_rows
        oracle["Expected Shortage Row Count"] = len(expected_rows)
        (oracle_dir/f"{sid}.json").write_text(json.dumps(oracle,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
        csv_rows.append({"Scenario_ID":sid,"Validation":oracle["Expected Validation Outcome"],"Exception_Total":oracle["Expected Exception Total"],"Counts":json.dumps(oracle["Expected Exception Counts by Type"],sort_keys=True)})
        catalog.append({"scenario_id":sid,"category":scenario.category,"Scenario ID":sid,"Size":scenario.category.title(),"Title":scenario.purpose,"Business Purpose":scenario.purpose,"Main Exception Types":sorted(oracle["Expected Exception Counts by Type"]),"Expected Result Summary":f"{oracle['Expected Exception Total']} exceptions; {oracle['Expected Validation Outcome']}","Workbook Path":path.relative_to(ROOT).as_posix(),"Oracle Path":(oracle_dir/f'{sid}.json').relative_to(ROOT).as_posix(),"Recommended for Demo":sid=="M08","Estimated Row Counts":scenario.row_counts})
    (DATA/"scenario_catalog.json").write_text(json.dumps({"analysis_date":ANALYSIS_DATE.isoformat(),"scenarios":catalog},indent=2,ensure_ascii=False),encoding="utf-8")
    pd.DataFrame(csv_rows).to_csv(DATA/"expected"/"oracle_summary.csv",index=False,encoding="utf-8-sig")
    print(f"Built {len(catalog)} independent scenario oracles: Small=9 Medium=8 Large=8")
if __name__ == "__main__": raise SystemExit(main())
