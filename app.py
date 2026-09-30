"""AI-Assisted Supply Chain Exception Management Cockpit."""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
from html import escape
from pathlib import Path
import json
import os
import pandas as pd
import streamlit as st
import altair as alt

from src.ai_action_plan import build_order_ai_input, inventory_coverage_message
from src.analysis_service import ENGINE_VERSION, analyze_workbook_content
from src.exception_engine import PRIORITY_RANK
from src.export_results import results_to_csv, results_to_excel
from src.llm_client import LLMConfigurationError, LLMRequestError, configured_model, generate_explanation
from src.llm_prompt import FIXED_HUMAN_REVIEW_NOTICE, MISSING_INFORMATION, PROMPT_VERSION, SCHEMA_VERSION
from src.order_summary import build_order_summary
from src.shortage_engine import AnalysisBlockedError
from src.ui_state import llm_cache_key, upload_signature
from src.validators import validate_workbook
from src.workbook_reader import WorkbookReadError, read_workbook
from src.workflow_state import WORKFLOW_STATUSES, apply_workflow_state, update_workflow_state
from src.cockpit_service import (
    BUSINESS_EXCEPTION_LABELS, ai_candidate_exceptions, build_materials_view, build_orders_view,
    business_exception_label, order_investigation, pending_scheduling, po_schedule_lines,
)

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data" / "expanded_scenarios" / "generated"
DEFAULT_DATE = date.today()
E2E_MODE = os.getenv("AI6201_E2E_MODE", "").strip() == "1"
E2E_ANALYSIS_DATE = date(2026, 9, 25)
E2E_RESULTS_ROOT = ROOT / "results" / "web_e2e_llm"

st.set_page_config(page_title="AI Supply Chain Exception Cockpit", page_icon="◉", layout="wide")
st.markdown("""<style>
:root{--navy:#14233b;--blue:#2563eb;--line:#dce3ec;--muted:#5c6b80;--bg:#f4f6f9;--danger:#b42318;--warning:#b45309;--ai:#6d4aff}
html,body,[class*="css"]{font-family:Inter,"Segoe UI","Noto Sans",Arial,sans-serif;font-size:16px;line-height:1.55}
.stApp{background:var(--bg);color:var(--navy)} [data-testid="stHeader"]{background:transparent}
[data-testid="stSidebar"]{background:#f9fafb;border-right:1px solid var(--line)}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.8rem}
.block-container{max-width:1680px;padding-top:1.5rem;padding-bottom:3rem}
h1,h2,h3{color:var(--navy);letter-spacing:-.025em}h1{font-size:2.1rem!important;line-height:1.2!important;margin:0 0 .25rem!important}h2{font-size:1.5rem!important}h3{font-size:1.15rem!important}
p,li,label,[data-testid="stMarkdownContainer"]{line-height:1.55}
.subtitle{color:var(--muted);font-size:1.05rem;margin:.15rem 0 1rem}.status{display:inline-flex;background:white;border:1px solid var(--line);border-radius:12px;padding:.65rem 1rem;margin-bottom:1.2rem;box-shadow:0 3px 12px rgba(20,35,59,.04)}.ok{color:#147a55;font-weight:750}
.section-kicker{color:var(--blue);font-size:.75rem;font-weight:800;letter-spacing:.09em;text-transform:uppercase;margin-bottom:.1rem}
.result-lead{font-size:1.15rem;font-weight:700;color:var(--navy);margin:.2rem 0}.result-note{color:var(--muted);margin-bottom:.75rem}.risk-badge{display:inline-block;border-radius:999px;padding:.22rem .65rem;background:#fee4e2;color:var(--danger);font-size:.78rem;font-weight:800}.risk-badge.low{background:#e7f6ef;color:#147a55}.risk-badge.medium{background:#fff1d6;color:var(--warning)}
.ai-summary{background:linear-gradient(135deg,#f4f1ff 0%,#f8fafc 70%);border:1px solid #d9d1ff;border-radius:16px;padding:1.2rem 1.35rem;margin:.65rem 0 1.15rem}.ai-summary-label,.ai-label{color:#6556a8;font-size:.76rem;font-weight:800;letter-spacing:.07em;text-transform:uppercase}.ai-summary-text{color:var(--navy);font-size:1.18rem;font-weight:750;line-height:1.55;margin-top:.3rem}
.action-card{background:#fff;border:1px solid var(--line);border-left:5px solid var(--blue);border-radius:14px;padding:1.15rem 1.25rem;margin:.85rem 0;box-shadow:0 4px 16px rgba(20,35,59,.045)}.action-card strong{color:var(--navy);font-size:1.05rem}.action-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin-bottom:.85rem}.action-title{font-size:1.1rem;font-weight:800;color:var(--navy)}.priority-pill,.status-pill{display:inline-flex;align-items:center;border-radius:999px;padding:.22rem .62rem;font-size:.76rem;font-weight:800}.priority-pill{background:#fee4e2;color:var(--danger)}.priority-pill.high{background:#fff1d6;color:#9a4e08}.priority-pill.medium{background:#e8f0ff;color:#1f5dc8}.priority-pill.low{background:#edf2f7;color:#52627a}.status-pill{background:#edf2f7;color:#52627a}.ai-fact-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.55rem;margin:.45rem 0 1rem}.ai-fact{background:#f6f8fb;border-radius:9px;padding:.55rem .7rem}.ai-fact-label{display:block;color:var(--muted);font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}.ai-fact-value{display:block;color:var(--navy);font-weight:750;margin-top:.08rem}.ai-finding{font-size:1rem;line-height:1.65;color:var(--navy);margin:.55rem 0}.ai-recommendation{background:#f4f1ff;border-radius:10px;padding:.75rem .85rem;margin-top:.8rem;color:#302762;line-height:1.6}.ai-card-footer{display:flex;gap:.45rem;flex-wrap:wrap;margin-top:.8rem}.action-number{display:inline-flex;width:1.75rem;height:1.75rem;align-items:center;justify-content:center;border-radius:50%;background:#ece8ff;color:#5940d8;font-size:.8rem;font-weight:850;margin-right:.55rem}.action-meta{color:var(--muted);font-size:.84rem;margin-top:.35rem}
[data-testid="stMetric"]{height:100%;min-width:0;min-height:8.25rem;background:white;border:1px solid var(--line);border-radius:12px;padding:clamp(.85rem,1.35vw,1.1rem);box-shadow:0 2px 10px rgba(20,35,59,.04);display:flex;flex-direction:column;justify-content:center}
[data-testid="stMetricLabel"],[data-testid="stMetricLabel"] *{color:#536176!important;font-size:clamp(.82rem,1vw,.96rem)!important;font-weight:700!important;line-height:1.3!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important;overflow-wrap:normal!important;word-break:normal!important}
[data-testid="stMetricValue"],[data-testid="stMetricValue"] *{color:var(--navy)!important;font-size:clamp(1.8rem,2.15vw,2.35rem)!important;line-height:1.12!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important;overflow-wrap:normal!important;word-break:normal!important;hyphens:none!important}
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){align-items:stretch}
.stCaption,[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:#59677a!important;font-size:.9rem!important;line-height:1.5!important}
.filter-summary{color:#44546a;font-size:.85rem;font-weight:700;margin:.15rem 0 .35rem}.filter-chips{display:flex;gap:.35rem;flex-wrap:wrap;margin:0 0 .35rem}.filter-chip{background:#e8eef8;color:#294d78;border-radius:999px;padding:.16rem .5rem;font-size:.74rem;font-weight:750}
.secondary-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.65rem;background:#fff;border:1px solid var(--line);border-radius:12px;padding:.8rem 1rem;margin:.7rem 0 1.15rem;box-shadow:0 2px 10px rgba(20,35,59,.035)}.secondary-item{min-width:0}.secondary-label{display:block;color:#5b687c;font-size:.79rem;font-weight:700;line-height:1.3}.secondary-value{display:block;color:var(--navy);font-size:1rem;font-weight:800;line-height:1.35;margin-top:.12rem;overflow-wrap:anywhere}
.st-key-chart_type,.st-key-chart_priority,.st-key-chart_plant{background:#fff!important;border-color:var(--line)!important;box-shadow:0 3px 14px rgba(20,35,59,.035)}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:10px;overflow:hidden}
div[data-baseweb="tab-list"],[data-testid="stTabs"] [role="tablist"]{gap:.35rem;border:1px solid var(--line);background:#e9edf3;border-radius:16px;padding:.35rem;box-shadow:inset 0 1px 2px rgba(20,35,59,.04)}button[data-baseweb="tab"],[data-testid="stTab"]{border-radius:12px!important;font-size:1.08rem!important;font-weight:750!important;padding:.65rem 1rem!important;transition:background-color .2s ease,color .2s ease,box-shadow .2s ease,transform .2s ease!important}button[data-baseweb="tab"]:hover,[data-testid="stTab"]:hover{background:rgba(255,255,255,.62)!important}button[data-baseweb="tab"][aria-selected="true"],[data-testid="stTab"][aria-selected="true"]{background:#fff!important;color:var(--navy)!important;box-shadow:0 3px 10px rgba(20,35,59,.12)!important}div[data-baseweb="tab-highlight"],.react-aria-SelectionIndicator{display:none!important}
.stButton>button,.stDownloadButton>button{min-height:2.65rem;border-radius:8px;font-weight:700}.stButton>button:focus-visible,.stDownloadButton>button:focus-visible,input:focus-visible{outline:3px solid #93b4ff!important;outline-offset:2px}
[data-testid="stExpander"]{background:white;border:1px solid var(--line)!important;border-radius:10px!important}
[data-testid="stAlert"]{border-radius:10px}
@media(max-width:1000px){[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){flex-wrap:wrap!important}[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])>[data-testid="stColumn"]{min-width:calc(50% - .5rem)!important;flex:1 1 calc(50% - .5rem)!important}}
@media(max-width:650px){.block-container{padding:1rem}h1{font-size:1.75rem!important}[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])>[data-testid="stColumn"]{min-width:100%!important;flex-basis:100%!important}[data-testid="stMetricValue"],[data-testid="stMetricValue"] *{font-size:clamp(1.7rem,8vw,2.15rem)!important}.stButton>button,.stDownloadButton>button{width:100%}div[data-baseweb="tab-list"],[data-testid="stTabs"] [role="tablist"]{overflow-x:auto;flex-wrap:nowrap}.ai-fact-grid{grid-template-columns:1fr}.secondary-strip{grid-template-columns:1fr}}
</style>""", unsafe_allow_html=True)

def reset_state():
    for key in (
        "validated_sheets", "validation_report", "analysis_result", "exceptions",
        "source_content", "workflow_state",
        "llm_results", "selected_order", "ai_selected_order_option",
    ):
        st.session_state.pop(key, None)

@st.cache_data(show_spinner=False)
def cached_analysis(workbook_sha256, analysis_date_iso, engine_version, content):
    # The explicit scalar arguments document and enforce every cache invalidator.
    return analyze_workbook_content(content, date.fromisoformat(analysis_date_iso))

def load_source(source, identity):
    try:
        content = source if isinstance(source, bytes) else Path(source).read_bytes()
        sheets = read_workbook(content)
    except WorkbookReadError as exc:
        st.error(str(exc)); return
    st.session_state.validated_sheets = sheets
    st.session_state.source_identity = identity
    st.session_state.source_content = content

def record_e2e_llm_result(scenario_id, order_id, order_item, payload, output):
    """Persist an auditable record only when the explicit web E2E mode is enabled."""
    if not E2E_MODE or not scenario_id:
        return
    E2E_RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    record = {
        "scenario_id": scenario_id,
        "source_identity": st.session_state.get("source_identity"),
        "analysis_date": str(st.session_state.get("analysis_date", E2E_ANALYSIS_DATE)),
        "selected_order": {"Sales_Order_ID": order_id, "Sales_Order_Item": order_item},
        "llm_payload": payload,
        "parsed_output": output.parsed_output,
        "raw_output": output.raw_output,
        "model": output.model,
        "input_tokens": output.input_tokens,
        "output_tokens": output.output_tokens,
        "total_tokens": output.total_tokens,
        "generation_id": output.generation_id,
        "exact_cost_usd": output.exact_cost_usd,
        "estimated_cost_usd": output.estimated_cost_usd,
        "response_time_seconds": output.response_time_seconds,
    }
    (E2E_RESULTS_ROOT / f"{scenario_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

FILTER_WIDGET_KEYS = (
    "filter_plant", "filter_horizon", "filter_priority",
    "filter_role", "filter_exception_type",
)


def reset_filters():
    """Reset every exception-overview filter to its default value on the next rerun."""
    for key in FILTER_WIDGET_KEYS:
        st.session_state.pop(key, None)
    st.session_state.filters_reset_notice = True


def exception_overview_filters(current, analysis_date):
    """Render filters that apply only to the exception overview."""
    st.subheader("Filter Results")
    st.caption("Use these filters to narrow the exception overview below. Other result sections and AI use their own complete data scope.")
    filters_disabled = current.empty
    row1 = st.columns(3)
    plant = row1[0].selectbox(
        "Plant", ["All"] + (sorted(current.Plant.dropna().astype(str).unique()) if not current.empty else []),
        disabled=filters_disabled, key="filter_plant",
    )
    horizon = row1[1].selectbox(
        "Due-Date Range", ["Due within 4 weeks + overdue", "Due within 8 weeks + overdue", "All dates"],
        disabled=filters_disabled, key="filter_horizon",
        help="Unresolved overdue issues remain visible because they are current planning risks.",
    )
    priority_options = [
        value for value in ("Critical", "High", "Medium", "Low")
        if current.empty or value in set(current.Priority.dropna().astype(str))
    ]
    priority = row1[2].selectbox(
        "Issue Priority", ["All"] + priority_options, disabled=filters_disabled, key="filter_priority"
    )
    row2 = st.columns(2)
    role_options = sorted(current.Responsible_Role.dropna().astype(str).unique()) if not current.empty else []
    role = row2[0].selectbox(
        "Suggested Team", ["All"] + role_options, disabled=filters_disabled, key="filter_role",
        help="Suggested by the system from the issue type. This is not an assigned owner.",
    )
    kind_label = row2[1].selectbox(
        "Issue Type",
        ["All"] + ([business_exception_label(v) for v in sorted(current.Exception_Type.unique())] if not current.empty else []),
        disabled=filters_disabled, key="filter_exception_type",
    )
    reverse_labels = {label: code for code, label in BUSINESS_EXCEPTION_LABELS.items()}
    kind = reverse_labels.get(kind_label, kind_label)
    filtered = filter_by_horizon(filter_exceptions(current, plant, kind, priority, role), horizon, analysis_date)

    if not filters_disabled:
        st.markdown(
            f'<div class="filter-summary">Showing {len(filtered):,} of {len(current):,} exception records</div>',
            unsafe_allow_html=True,
        )
    filters_active = not filters_disabled and any((
        plant != "All", horizon != "Due within 4 weeks + overdue", priority != "All",
        role != "All", kind_label != "All",
    ))
    if st.session_state.pop("filters_reset_notice", False):
        st.toast("Filters reset")
    st.button("Reset Filters", disabled=not filters_active, on_click=reset_filters)
    return filtered


def filter_exceptions(frame, plant, kind, priority, role):
    output = frame.copy()
    for column, value in (("Plant", plant), ("Exception_Type", kind), ("Priority", priority), ("Responsible_Role", role)):
        if value != "All": output = output[output[column].astype(str) == str(value)]
    return output


def filter_by_horizon(frame, horizon, analysis_date):
    """Apply the selected planning horizon while retaining unresolved overdue rows."""
    if horizon == "All dates" or frame.empty:
        return frame
    dates = pd.to_datetime(frame.Material_Need_Date, errors="coerce")
    limit = analysis_date + timedelta(days=28 if horizon.startswith("Due within 4") else 56)
    return frame[dates.isna() | (dates.dt.date <= limit)]

def show_validation():
    report = st.session_state.get("validation_report")
    if report is None:
        st.info("Choose a workbook in Step 1, then run the workbook check.")
        return
    summary = report.summary(); cols = st.columns(3)
    validation_metrics = (
        ("Blocking Problems", "data_error_count", "These must be fixed before analysis can run."),
        ("Check Notes", "warning_count", "Analysis can continue, but you may want to check these items."),
        ("Excluded Rows", "ignored_count", "These rows were not used because they are outside the current analysis scope."),
    )
    for col, (label, key, explanation) in zip(cols, validation_metrics):
        col.metric(label, summary[key])
        col.caption(explanation)
    if not report.issues: st.success("Workbook check passed. Analysis is ready to run.")
    else: st.dataframe(pd.DataFrame([i.to_dict() for i in report.issues]), hide_index=True, width="stretch")

def horizontal_bar_chart(data, category, *, color="#2672e3", order="-x", color_scale=None):
    """Render a readable, full-width horizontal bar chart with direct labels."""
    if data.empty:
        st.info("No exceptions in the current filter.")
        return
    maximum = max(float(data["Count"].max()), 1.0)
    encoding = {
        "x": alt.X("Count:Q", title="Count", scale=alt.Scale(domain=[0, maximum * 1.12]), axis=alt.Axis(tickMinStep=1)),
        "y": alt.Y(f"{category}:N", title=None, sort=order, axis=alt.Axis(labelLimit=480, labelPadding=10)),
        "tooltip": [alt.Tooltip(f"{category}:N", title=category), alt.Tooltip("Count:Q", format=",.0f")],
    }
    if color_scale:
        encoding["color"] = alt.Color(f"{category}:N", scale=color_scale, legend=None)
    bars = alt.Chart(data).mark_bar(cornerRadiusEnd=5, color=color, size=28).encode(**encoding)
    labels = alt.Chart(data).mark_text(align="left", baseline="middle", dx=7, color="#34445c", fontSize=13, fontWeight=700).encode(
        x=alt.X("Count:Q", scale=alt.Scale(domain=[0, maximum * 1.12])),
        y=alt.Y(f"{category}:N", sort=order),
        text=alt.Text("Count:Q", format=",.0f"),
    )
    height = max(210, 48 * len(data) + 55)
    st.altair_chart((bars + labels).properties(height=height), width="stretch")

def dataframe_config(labels):
    """Build stable, readable labels without changing the underlying data."""
    return {column: st.column_config.Column(label) for column, label in labels.items()}

def concise_frame(frame, columns):
    available = [column for column in columns if column in frame.columns]
    return frame.loc[:, available].copy()


def secondary_signals(items):
    """Render supporting KPIs with readable hierarchy instead of faint caption text."""
    cards = "".join(
        '<div class="secondary-item">'
        f'<span class="secondary-label">{escape(str(label))}</span>'
        f'<span class="secondary-value">{escape(str(value))}</span></div>'
        for label, value in items
    )
    st.markdown(f'<div class="secondary-strip">{cards}</div>', unsafe_allow_html=True)


def overview(exceptions, orders):
    order_summary = build_order_summary(exceptions, orders)
    open_orders = int(orders.Order_Status.astype(str).str.upper().isin({"OPEN", "CREATED", "RELEASED", "PARTIALLY_CONFIRMED"}).sum())
    actionable = exceptions[
        exceptions.get("Impact_Class", pd.Series(index=exceptions.index, dtype=str)).isin(["BLOCKING", "AT_RISK"])
    ] if not exceptions.empty else exceptions
    high = int(actionable.dropna(subset=["Sales_Order_ID"])[["Sales_Order_ID", "Sales_Order_Item"]].drop_duplicates().shape[0])
    primary = [
        ("Order Lines Needing Action", high, "Order lines with at least one issue that may affect delivery or production."),
        ("Material Shortage Cases", int((exceptions.Exception_Type == "MATERIAL_SHORTAGE").sum()), "Cases where available inventory and incoming supply do not fully cover demand."),
        ("Sales Orders with Exceptions", int(order_summary.Sales_Order_ID.nunique()) if not order_summary.empty else 0, "Sales orders with at least one detected planning issue."),
    ]
    for col, (label, value, explanation) in zip(st.columns(3), primary):
        col.metric(label, value)
        col.caption(explanation)
    secondary_signals([
        ("Order Lines Without a Production Schedule", int((exceptions.Exception_Type == "UNSCHEDULED_ORDER").sum())),
        ("Overdue Production Orders", int((exceptions.Exception_Type == "PRODUCTION_BACKLOG").sum())),
        ("Open Sales-Order Lines", open_orders),
    ])
    st.caption("The supporting figures show unscheduled order lines, incomplete overdue production orders, and active sales-order lines.")
    with st.container(border=True, key="chart_type"):
        st.subheader("Exceptions by Type")
        business = exceptions.copy(); business["Exception"] = business.Exception_Type.map(business_exception_label)
        type_data = business["Exception"].fillna("Not assigned").value_counts().rename_axis("Exception").reset_index(name="Count")
        horizontal_bar_chart(type_data, "Exception")
    with st.container(border=True, key="chart_priority"):
        st.subheader("Exceptions by Priority")
        priority_order = ["Critical", "High", "Medium", "Low"]
        priority_data = exceptions.Priority.value_counts().reindex(priority_order, fill_value=0).rename_axis("Priority").reset_index(name="Count")
        priority_data = priority_data[priority_data.Count > 0]
        horizontal_bar_chart(
            priority_data,
            "Priority",
            order=priority_order,
            color_scale=alt.Scale(domain=priority_order, range=["#b42318", "#d97706", "#3b82f6", "#94a3b8"]),
        )
    with st.container(border=True, key="chart_plant"):
        st.subheader("Exceptions by Plant")
        if exceptions.empty: st.info("No plant-level exceptions in the current filter.")
        else:
            plant_data = exceptions.Plant.fillna("Not assigned").value_counts().rename_axis("Plant").reset_index(name="Count")
            horizontal_bar_chart(plant_data, "Plant", color="#496b91")
    st.subheader("Highest-Priority Affected Order Lines")
    st.caption("Order lines are ranked by their highest detected issue priority and requested delivery date.")
    if order_summary.empty: st.info("No affected sales orders.")
    else:
        ranked = order_summary.assign(_rank=order_summary.Highest_Priority.map(PRIORITY_RANK)).sort_values(["_rank", "Requested_Delivery_Date"]).drop(columns="_rank")
        table = concise_frame(ranked.head(8), ["Sales_Order_ID", "Sales_Order_Item", "Product_ID", "Requested_Delivery_Date", "Highest_Priority", "Responsible_Roles"])
        st.dataframe(table, hide_index=True, width="stretch", column_config=dataframe_config({"Sales_Order_ID":"Sales Order", "Sales_Order_Item":"Item", "Product_ID":"Product", "Requested_Delivery_Date":"Requested Delivery", "Highest_Priority":"Highest Priority", "Responsible_Roles":"Suggested Team"}))

def orders_view(exceptions, sheets, result, analysis_date):
    c1, c2 = st.columns(2); query = c1.text_input("Search sales order", placeholder="Enter any order ID", key="orders_search_order"); product_query = c2.text_input("Search product", placeholder="Product ID or description", key="orders_search_product")
    quick_filter = st.selectbox(
        "Show Order Lines",
        ["All Order Lines", "Order Lines with Switch Shortages", "Order Lines with Controller Shortages", "Order Lines Without a Production Schedule"],
        key="orders_view_filter",
    )
    summary = build_orders_view(sheets, result.shortage_results, exceptions, analysis_date)
    if quick_filter == "Order Lines Without a Production Schedule": summary = summary[summary.Scheduling_Status == "Pending Scheduling"]
    elif quick_filter in {"Order Lines with Switch Shortages", "Order Lines with Controller Shortages"}:
        category = "Switch" if "Switch" in quick_filter else "Controller"
        bom = sheets["BOM"]; ids = set(bom[bom.Material_Category.astype(str) == category].Component_Material_ID.astype(str))
        req = result.shortage_results[(result.shortage_results.Shortage_Quantity > 0) & result.shortage_results.Material_ID.astype(str).isin(ids)]
        keys = set(zip(req.Source_Sales_Order_ID.astype(str), req.Source_Sales_Order_Item.astype(str)))
        summary = summary[summary.apply(lambda r: (str(r.Sales_Order_ID), str(r.Sales_Order_Item)) in keys, axis=1)]
    if query: summary = summary[summary.Sales_Order_ID.str.contains(query, case=False, na=False, regex=False)]
    if product_query: summary = summary[summary.astype(str).apply(lambda row: row.str.contains(product_query, case=False, regex=False).any(), axis=1)]
    if summary.empty: st.info("No order lines match the current filters."); return
    display = concise_frame(summary, ["Sales_Order_ID", "Sales_Order_Item", "Product_ID", "Requested_Quantity", "Requested_Delivery_Date", "Plant", "Scheduling_Status", "Related_Production_Orders", "Highest_Priority", "Affected_Materials", "Total_Shortage", "Exception_Summary"])
    event = st.dataframe(display, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="orders_table", column_config=dataframe_config({"Sales_Order_ID":"Sales Order", "Sales_Order_Item":"Item", "Product_ID":"Product", "Requested_Quantity":"Requested Quantity", "Requested_Delivery_Date":"Requested Delivery Date", "Scheduling_Status":"Scheduling Status", "Related_Production_Orders":"Related Production Orders", "Highest_Priority":"Highest Priority", "Affected_Materials":"Affected Materials", "Total_Shortage":"Total Shortage", "Exception_Summary":"Exception Summary"}))
    index = event.selection.rows[0] if event.selection.rows else 0; selected = summary.iloc[index]
    st.session_state.selected_order = (str(selected.Sales_Order_ID), str(selected.Sales_Order_Item))
    investigation = order_investigation(str(selected.Sales_Order_ID), str(selected.Sales_Order_Item), sheets, result.shortage_results, exceptions, analysis_date)
    st.markdown("### Selected Order-Line Details")
    m1, m2, m3, m4 = st.columns(4); m1.metric("Scheduling Status", selected.Scheduling_Status); m2.metric("Overdue Production", "Yes" if investigation["production_backlog"] else "No"); m3.metric("Materials with Supply Risk", selected.Affected_Materials); m4.metric("Total Shortage", f"{selected.Total_Shortage:g}")
    st.markdown("#### Production Status")
    if investigation["production_orders"].empty:
        st.info("No linked production order is present.")
    else:
        st.dataframe(investigation["production_orders"], hide_index=True, width="stretch")
    st.markdown("#### Material Readiness and Shortages")
    material_cols = ["Material_ID", "Material_Need_Date", "Required_Quantity", "Usable_Inventory", "Eligible_Incoming_Quantity", "Inventory_Allocated", "Incoming_PO_Allocated", "Shortage_Quantity", "Priority"]
    st.dataframe(concise_frame(investigation["material_readiness"], material_cols), hide_index=True, width="stretch")
    st.markdown("#### Related or Potentially Supporting Supplier POs")
    st.caption("Related POs are potential supply, not confirmed allocation.")
    if investigation["supplier_pos"].empty:
        st.info("No related PO schedule line was found.")
    else:
        st.dataframe(investigation["supplier_pos"], hide_index=True, width="stretch")

def materials_view(exceptions, sheets, result, analysis_date):
    st.caption("Each row represents one material, plant and quantity-unit combination.")
    c1, c2 = st.columns(2); query = c1.text_input("Search material", placeholder="Material ID or description"); supplier_query = c2.text_input("Filter selected material's PO lines by supplier")
    categories = sorted(sheets["BOM"].Material_Category.dropna().unique()) if "Material_Category" in sheets["BOM"] else []
    category = st.selectbox("Material Category", ["All"] + categories, key="material_category")
    material_view = st.selectbox(
        "Show Material / Plant Records", ["All Analyzed Material / Plant Records", "Switch Material / Plant Shortages", "Controller Material / Plant Shortages"],
        key="materials_view_filter",
    )
    summary = build_materials_view(sheets, result.shortage_results)
    if category != "All": summary = summary[summary.Category == category]
    if material_view in {"Switch Material / Plant Shortages", "Controller Material / Plant Shortages"}:
        target = "Switch" if material_view.startswith("Switch") else "Controller"; summary = summary[(summary.Category == target) & (summary.Total_Shortage > 0)]
    if query: summary = summary[summary.Material_ID.str.contains(query, case=False, na=False) | summary.Description.astype(str).str.contains(query, case=False, na=False)]
    if summary.empty: st.info("No materials match the current filters."); return
    display = concise_frame(summary, [
        "Material_ID", "Description", "Category", "Plant", "Quantity_Unit", "Total_Required",
        "Usable_Inventory", "Incoming_PO_Allocated", "Total_Shortage", "Earliest_Need_Date",
        "Highest_Priority", "Affected_Sales_Orders", "Affected_Production_Orders",
    ])
    event = st.dataframe(display, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="materials_table", column_config=dataframe_config({"Material_ID":"Material", "Total_Required":"Total Required", "Incoming_PO_Allocated":"Incoming PO Allocated", "Total_Shortage":"Total Shortage", "Earliest_Need_Date":"Earliest Need Date", "Highest_Priority":"Highest Priority", "Affected_Sales_Orders":"Affected Sales Orders", "Affected_Production_Orders":"Affected Production Orders"}))
    selected = summary.iloc[event.selection.rows[0] if event.selection.rows else 0]
    st.markdown("### Supplier PO Schedule Lines for the Selected Material and Plant")
    st.caption("These PO lines share the selected material and plant. Check supply eligibility and actual allocation before treating them as available supply.")
    po = po_schedule_lines(str(selected.Material_ID), str(selected.Plant), sheets, result.shortage_results, analysis_date)
    if supplier_query: po = po[po.Supplier.astype(str).str.contains(supplier_query, case=False, na=False, regex=False)]
    if po.empty:
        st.info("No PO schedule lines match this material and plant.")
    else:
        st.dataframe(po, hide_index=True, width="stretch")

def pending_view(sheets, exceptions, analysis_date):
    st.markdown("### Order Lines Without a Production Schedule")
    st.caption("Open order lines with a positive requested quantity and no valid linked production order.")
    frame = pending_scheduling(sheets, analysis_date, exceptions)
    if frame.empty: st.success("No orders are pending scheduling in the current planning scope.")
    else: st.dataframe(frame, hide_index=True, width="stretch", column_config=dataframe_config({"Sales_Order_ID":"Sales Order", "Sales_Order_Item":"Item", "Product_ID":"Product", "Requested_Quantity":"Requested Quantity", "Requested_Delivery_Date":"Requested Delivery Date", "Days_Until_Delivery":"Days Until Delivery", "Scheduling_Status":"Scheduling Status"}))
    st.info("These order lines are excluded from material and AI reviews because no production order exists to establish component demand.")

def workflow_view(exceptions):
    st.subheader("Exception Review Status")
    st.caption("Optional status tracking for this session. It does not change analysis results or AI output.")
    if exceptions.empty:
        st.info("No exceptions are available for workflow tracking.")
        return
    labels = {
        str(row.Exception_ID): f"{row.Exception_ID} · {business_exception_label(row.Exception_Type)} · {row.Priority}"
        for row in exceptions.itertuples()
    }
    exception_id = st.selectbox("Exception", list(labels), format_func=labels.get, key="workflow_exception")
    selected = exceptions[exceptions.Exception_ID.astype(str) == exception_id].iloc[0]
    current = str(selected.Workflow_Status)
    status = st.selectbox(
        "Review Status", WORKFLOW_STATUSES,
        index=WORKFLOW_STATUSES.index(current) if current in WORKFLOW_STATUSES else 0,
        key=f"workflow_status_{exception_id}",
    )
    if st.button("Update Review Status", key="workflow_update"):
        update_workflow_state(st.session_state.setdefault("workflow_state", {}), exception_id, status)
        st.rerun()
    table = concise_frame(exceptions, ["Exception_ID", "Exception_Type", "Priority", "Responsible_Role", "Workflow_Status"])
    st.dataframe(table, hide_index=True, width="stretch", column_config=dataframe_config({"Responsible_Role": "Suggested Team", "Workflow_Status": "Review Status"}))

def ai_view(exceptions, candidate_exceptions, result):
    full_summary = build_order_summary(exceptions, st.session_state.validated_sheets["Orders"])
    fallback = full_summary.empty
    if fallback and result.shortage_results.empty: st.info("No analyzed result is available for an AI action plan."); return
    st.subheader("Choose an Order Line for AI Review")
    st.caption("AI uses the complete analysis for the selected order line. The Exception Overview filters do not affect this section.")
    if fallback:
        fact = result.shortage_results.iloc[0]; order_id = str(fact.get("Source_Sales_Order_ID") or fact["Production_Order_ID"]); order_item = str(fact.get("Source_Sales_Order_Item") or fact["Production_Order_Item"]); scoped = exceptions.iloc[0:0]
        from src.llm_prompt import build_structured_input
        preview = {"representative_shortage_fact": build_structured_input(fact)}
    else:
        summary = build_order_summary(candidate_exceptions, st.session_state.validated_sheets["Orders"])
        if summary.empty:
            st.info("No analyzed order line is available for AI review.")
            return
        options = [f"{r.Sales_Order_ID} / {r.Sales_Order_Item}" for r in summary.itertuples()]
        chosen = st.session_state.get("selected_order")
        preferred = f"{chosen[0]} / {chosen[1]}" if chosen else options[0]
        if preferred not in options:
            preferred = options[0]
        # Keep a stable widget key and repair a now-invalid value when a new
        # workbook changes the available order lines.
        if st.session_state.get("ai_selected_order_option") not in options:
            st.session_state.ai_selected_order_option = preferred
        selected_option = st.selectbox(
            "Selected order line", options, key="ai_selected_order_option"
        )
        order_id, order_item = [x.strip() for x in selected_option.split("/", 1)]
        st.session_state.selected_order = (order_id, order_item)
        scoped = exceptions[(exceptions.Sales_Order_ID.astype(str) == order_id) & (exceptions.Sales_Order_Item.astype(str) == order_item)]
        preview = build_order_ai_input(order_id, order_item, exceptions, result.shortage_results, st.session_state.validated_sheets)
    representative = preview["representative_shortage_fact"]
    llm_payload = preview.get("llm_payload", representative or {})
    st.subheader("Verified Risk Summary")
    st.metric("Verified Exception Records", len(scoped))
    if representative is None:
        st.info("No shortage row is available for the current evidence schema.")
        return
    key = llm_cache_key(st.session_state.source_identity, f"{order_id}|{order_item}", configured_model(), PROMPT_VERSION, SCHEMA_VERSION)
    output = st.session_state.setdefault("llm_results", {}).get(key)
    api_key = st.text_input(
        "OpenRouter API Key",
        type="password",
        key="openrouter_api_key",
        help="Used only for this browser session and only when you click Generate. It is not written to disk, logs, exports, or the AI payload.",
    ).strip()
    if not api_key:
        st.info("Enter an OpenRouter API Key to enable AI generation. Deterministic analysis remains available without a key. Only the displayed order-level payload is sent; the raw workbook and unrelated rows are never sent.")
    elif output is None and st.button("Generate Advisory Action Plan", type="primary", width="stretch"):
        try:
            with st.spinner("Generating evidence-bound advisory plan..."):
                output = generate_explanation(llm_payload, api_key=api_key)
            st.session_state.llm_results[key] = output
            record_e2e_llm_result(
                str(st.query_params.get("scenario", "")), order_id, order_item, llm_payload, output
            )
            # The button and spinner were already emitted earlier in this render pass.
            # Start a clean pass so the completed state cannot look like an in-flight
            # request and the Generate button is replaced by the cached result.
            st.rerun()
        except (LLMConfigurationError, LLMRequestError) as exc: st.error(str(exc))
    if output is None:
        st.markdown("### Priority Explanation")
        st.caption("Generate an AI plan for evidence-based explanations and review actions.")
        st.caption("AI output is advisory. It does not update ERP data, contact suppliers, reschedule production, or execute any action.")
        st.warning(FIXED_HUMAN_REVIEW_NOTICE)
    else:
        st.success("Cached output is shown; no duplicate API call was made.")
        parsed = output.parsed_output
        st.markdown(
            '<div class="ai-summary"><div class="ai-summary-label">Priority summary</div>'
            f'<div class="ai-summary-text">{escape(str(parsed["priority_summary"]))}</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown("### Priority Explanation")
        st.markdown(
            '<div class="action-card"><div class="ai-label">Why this needs attention</div>'
            f'<div class="ai-finding">{escape(str(parsed["explanation"]))}</div></div>',
            unsafe_allow_html=True,
        )
        if llm_payload.get("payload_truncated"):
            omitted = []
            for count_field, label in (
                ("additional_exception_count", "verified exceptions"),
                ("additional_affected_material_count", "affected materials"),
                ("additional_po_line_count", "related PO lines"),
            ):
                count = int(llm_payload.get(count_field, 0) or 0)
                if count:
                    omitted.append(f"{count} additional {label}")
            st.warning(
                "The bounded AI payload omitted " + ", ".join(omitted) + ". "
                "The deterministic analysis remains complete; AI advice is limited to the displayed payload."
            )
        reviews = parsed.get("exception_reviews", [])
        if reviews:
            st.markdown("### Exception-by-Exception Review")
            verified_by_id = {
                item.get("Exception_ID"): item
                for item in llm_payload.get("Verified_Exceptions", [])
                if isinstance(item, dict)
            }
            for review in reviews:
                material = review.get("material_id") or "No material ID"
                unit = review.get("quantity_unit") or ""
                verified = verified_by_id.get(review.get("exception_id"), {})
                coverage_message = inventory_coverage_message(verified)
                facts = [
                    ("Impact class", review.get("impact_class")),
                    ("Need date", review.get("material_need_date")),
                    ("Requested delivery", review.get("requested_delivery_date")),
                    ("Planned start", review.get("planned_start_date")),
                    ("Planned end", review.get("planned_end_date")),
                    ("Days after requested delivery", review.get("days_after_requested_delivery")),
                    ("Required / remaining", f'{verified.get("Remaining_Quantity")} {unit}'.strip() if verified.get("Remaining_Quantity") is not None else None),
                    ("Production status", verified.get("Production_Order_Status")),
                    ("Shortage", f'{review.get("shortage_quantity")} {unit}'.strip() if review.get("shortage_quantity") is not None else None),
                    ("Inventory allocated", f'{verified.get("Inventory_Allocated")} {unit}'.strip() if verified.get("Inventory_Allocated") is not None else None),
                    ("Late incoming", f'{review.get("late_incoming_quantity")} {unit}'.strip() if review.get("late_incoming_quantity") is not None else None),
                    ("Overdue incoming", f'{review.get("overdue_incoming_quantity")} {unit}'.strip() if review.get("overdue_incoming_quantity") is not None else None),
                    ("Next receipt", review.get("next_receipt_date")),
                    ("Supply relationship", review.get("supply_relationship")),
                    ("Directly pegged", review.get("directly_pegged_to_order")),
                ]
                facts_html = "".join(
                    '<div class="ai-fact">'
                    f'<span class="ai-fact-label">{escape(label)}</span>'
                    f'<span class="ai-fact-value">{escape(str(value))}</span></div>'
                    for label, value in facts if value is not None
                )
                priority_text = str(review["priority"])
                priority_class = priority_text.lower() if priority_text.lower() in {"high", "medium", "low"} else ""
                exception_label = business_exception_label(str(review["exception_type"]))
                st.markdown(
                    "".join((
                        '<div class="action-card">',
                        '<div class="action-head">',
                        f'<div class="action-title">{escape(str(material))} · {escape(exception_label)}</div>',
                        f'<span class="priority-pill {priority_class}">{escape(priority_text)}</span></div>',
                        f'<div class="ai-fact-grid">{facts_html}</div>',
                        f'<div class="ai-label">Deterministic conclusion</div><div class="ai-finding"><strong>{escape(coverage_message)}</strong></div>' if coverage_message else "",
                        f'<div class="ai-label">AI finding</div><div class="ai-finding">{escape(str(review["finding"]))}</div>',
                        '<div class="ai-recommendation"><span class="ai-label">Recommended review</span><br>',
                        f'{escape(str(review["recommended_review"]))}</div>',
                        '<div class="ai-card-footer"><span class="status-pill">Human review required</span>',
                        '<span class="status-pill">Not executed</span></div></div>',
                    )),
                    unsafe_allow_html=True,
                )
        st.markdown("### Recommended Review Actions")
        for index, action in enumerate(parsed["recommended_actions"], start=1):
            action_type = str(action["action_type"]).replace("_", " ").title()
            st.markdown(
                '<div class="action-card">'
                f'<div class="action-title"><span class="action-number">{index}</span>{escape(str(action["action"]))}</div>'
                f'<div class="action-meta">{escape(action_type)}</div>'
                '<div class="ai-card-footer"><span class="status-pill">Human review required</span>'
                '<span class="status-pill">Not executed</span></div></div>',
                unsafe_allow_html=True,
            )
        missing = [MISSING_INFORMATION[c] for c in parsed["missing_information_codes"]]
        st.markdown("### Missing Information and Verification Questions")
        if missing:
            st.markdown("\n".join(f"- {item}" for item in missing))
        else:
            st.success("No missing information was identified.")
        st.markdown("### Risks, Limitations, and Execution Status")
        st.markdown(
            '<div class="action-card"><div class="ai-finding">Advice is scoped to the selected order and verified facts.</div>'
            '<div class="ai-card-footer"><span class="status-pill">Human review required</span>'
            '<span class="status-pill">Not executed</span></div></div>',
            unsafe_allow_html=True,
        )
        st.warning(FIXED_HUMAN_REVIEW_NOTICE)
    preview_title = "Data Sent to AI for This Result" if output is not None else "Preview of Data Eligible to Be Sent to AI"
    with st.expander(f"{preview_title} · Supporting Evidence and AI Input"):
        st.markdown("**Verified order facts**")
        evidence = concise_frame(scoped, [
            "Exception_Type", "Material_ID", "Shortage_Quantity", "Priority",
            "Impact_Class", "Direct_Order_Impact", "Responsible_Role",
        ])
        st.dataframe(evidence, hide_index=True, width="stretch", column_config=dataframe_config({"Responsible_Role": "Suggested Team"}))
        st.markdown("**Structured AI input preview**")
        st.json(preview["representative_shortage_fact"] if fallback else preview)

st.title("Material Readiness Cockpit")
st.markdown('<div class="subtitle">Deterministic material readiness, shortage and planning exception analysis.</div>', unsafe_allow_html=True)
st.markdown('<div class="section-kicker">Workflow</div>', unsafe_allow_html=True)

with st.container(border=True):
    st.subheader("1 · Select Analysis Data")
    st.caption("Upload the ERP workbook and choose the planning date used for this analysis.")
    if E2E_MODE:
        scenario_id = str(st.query_params.get("scenario", "")).strip().upper()
        scenario_paths = {path.stem.upper(): path for path in DATA_ROOT.rglob("*.xlsx")}
        if scenario_id in scenario_paths:
            source_identity = f"e2e:{scenario_id}"
            if st.session_state.get("source_identity") != source_identity:
                reset_state()
                st.session_state.analysis_date = E2E_ANALYSIS_DATE
                load_source(scenario_paths[scenario_id], source_identity)
            st.caption(f"E2E scenario loaded: {scenario_id}")
    uploaded = st.file_uploader("Upload ERP Workbook", type=["xlsx"])
    chosen_date = st.date_input(
        "Analysis Date",
        value=st.session_state.get("analysis_date", DEFAULT_DATE),
        format="MM/DD/YYYY",
    )
    date_changed = chosen_date != st.session_state.get("analysis_date")
    if date_changed:
        st.session_state.analysis_date = chosen_date
        if "validated_sheets" in st.session_state: reset_state()
    if uploaded is not None:
        content = uploaded.getvalue(); signature = upload_signature(content, chosen_date)
        if signature != st.session_state.get("uploaded_signature"):
            reset_state(); st.session_state.uploaded_signature = signature; st.session_state.source_name = uploaded.name; load_source(content, f"upload:{signature[:12]}")
    if "validated_sheets" in st.session_state:
        st.success(f"Workbook loaded: {st.session_state.get('source_name', 'selected workbook')}")
    else:
        st.info("No workbook selected yet.")

with st.container(border=True):
    st.subheader("2 · Workbook Check")
    st.caption("Checks the uploaded Excel file before analysis. These are not planning tasks.")
    if st.button("Validate Workbook", width="stretch", disabled="validated_sheets" not in st.session_state):
        st.session_state.validation_report = validate_workbook(st.session_state.validated_sheets, chosen_date)
    show_validation()

with st.container(border=True):
    st.subheader("3 · Run Planning Analysis")
    st.caption("Calculates material requirements, supply coverage, shortages and planning issues using the validated workbook.")
    run_clicked = False
    if "validation_report" in st.session_state and st.session_state.validation_report.is_valid:
        run_clicked = st.button("Run Analysis", type="primary", width="stretch")
    else:
        st.button("Run Analysis", disabled=True, width="stretch")
    if "analysis_result" in st.session_state:
        st.success("Analysis complete. Results are available below.")
if run_clicked:
    try:
        content = st.session_state.source_content
        analyzed = cached_analysis(sha256(content).hexdigest(), chosen_date.isoformat(), ENGINE_VERSION, content)
        st.session_state.validated_sheets = analyzed.sheets; st.session_state.validation_report = analyzed.result.validation_report
        st.session_state.analysis_result = analyzed.result; st.session_state.exceptions = analyzed.exceptions
        st.session_state.workflow_state = {}; st.session_state.llm_results = {}
        st.rerun()
    except AnalysisBlockedError as exc: st.session_state.validation_report = exc.report
if "analysis_result" not in st.session_state:
    st.stop()

# Compact deterministic evidence retained for auditability and backwards-compatible classroom checks.
facts = st.session_state.analysis_result.shortage_results
if not facts.empty:
    selected_order_key = st.session_state.get("selected_order")
    selected_scope = facts
    selected_order_exceptions = st.session_state.exceptions.iloc[0:0]
    if selected_order_key:
        candidate = facts[(facts.Source_Sales_Order_ID.astype(str) == selected_order_key[0]) & (facts.Source_Sales_Order_Item.astype(str) == selected_order_key[1])]
        if not candidate.empty: selected_scope = candidate
        selected_order_exceptions = st.session_state.exceptions[
            (st.session_state.exceptions.Sales_Order_ID.astype(str) == selected_order_key[0])
            & (st.session_state.exceptions.Sales_Order_Item.astype(str) == selected_order_key[1])
        ].copy()
    selected_fact = selected_scope.assign(_rank=selected_scope.Priority.map(PRIORITY_RANK).fillna(99)).sort_values(["_rank", "Shortage_Quantity"], ascending=[True, False]).iloc[0]
    material_id = selected_fact.get("Material_ID")
    order_id = selected_fact.get("Source_Sales_Order_ID")
    unit = str(selected_fact["Quantity_Unit"])
    priority_text = str(selected_fact["Priority"])
    badge_class = "low" if priority_text.lower() == "low" else ("medium" if priority_text.lower() == "medium" else "")
    with st.container(border=True):
        heading, badge = st.columns([5, 1])
        with heading:
            coverage_title = "Selected Material Requirement Coverage" if selected_order_key else "Highest-Priority Material Requirement"
            st.markdown(f'<div class="section-kicker">{coverage_title}</div>', unsafe_allow_html=True)
            st.caption("Shows supply allocated to this requirement, not the total material supply pool.")
            identifier = f"Material {material_id}" if pd.notna(material_id) else "The selected requirement"
            shortage_quantity = float(selected_fact["Shortage_Quantity"])
            if shortage_quantity > 0:
                st.markdown(f'<div class="result-lead">{escape(identifier)} has a projected shortage of {shortage_quantity:g} {escape(unit)}.</div>', unsafe_allow_html=True)
                if pd.notna(order_id): st.markdown(f'<div class="result-note">This shortage may affect the delivery of sales order {escape(str(order_id))}.</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="result-lead">{escape(identifier)} has no projected shortage for the calculated requirement.</div>', unsafe_allow_html=True)
                if pd.notna(order_id): st.markdown(f'<div class="result-note">The requirement for sales order {escape(str(order_id))} is covered by allocated supply in this calculation.</div>', unsafe_allow_html=True)
        with badge: st.markdown(f'<span class="risk-badge {badge_class}">{escape(priority_text)} Shortage Risk</span>', unsafe_allow_html=True)
        evidence_cols = st.columns(4)
        evidence_cols[0].metric("Requirement Quantity", f"{selected_fact['Required_Quantity']:g} {unit}")
        evidence_cols[1].metric("Inventory Allocated", f"{selected_fact['Inventory_Allocated']:g}")
        evidence_cols[2].metric("Incoming PO Allocated", f"{selected_fact['Incoming_PO_Allocated']:g}")
        evidence_cols[3].metric("Uncovered Quantity", f"{selected_fact['Shortage_Quantity']:g}")
        st.caption("Calculation basis")
        st.code(f"{selected_fact['Required_Quantity']:g} - ({selected_fact['Inventory_Allocated']:g} + {selected_fact['Incoming_PO_Allocated']:g}) = {selected_fact['Shortage_Quantity']:g} {unit}")
        st.markdown(f"Material shortage priority: **{escape(priority_text)}** ({escape(str(selected_fact['Priority_Rule_ID']))})")
        if not selected_order_exceptions.empty:
            selected_order_exceptions["_priority_rank"] = selected_order_exceptions.Priority.map(PRIORITY_RANK).fillna(99)
            sort_columns = ["Action_Sequence", "_priority_rank"] if "Action_Sequence" in selected_order_exceptions else ["_priority_rank"]
            primary_order_exception = selected_order_exceptions.sort_values(sort_columns, kind="stable").iloc[0]
            st.warning(
                f"Order exception priority: {primary_order_exception['Priority']} — "
                f"{len(selected_order_exceptions)} verified exception(s). "
                "Material coverage does not rule out schedule, production, or supply-timing risks."
            )
else:
    st.info("Analysis completed with no active shortage result for the selected scope.")

exceptions = apply_workflow_state(st.session_state.exceptions, st.session_state.setdefault("workflow_state", {}))
ai_candidates = ai_candidate_exceptions(
    exceptions[exceptions.Exception_Type != "UNSCHEDULED_ORDER"], "All", st.session_state.validated_sheets,
    st.session_state.analysis_result.shortage_results, chosen_date,
)
st.markdown("## Analysis Results")
st.caption("The following sections show deterministic results calculated from the validated workbook.")
tabs = st.tabs(["Exception Overview", "Sales Orders", "Materials & Supplier POs", "Missing Production Schedules"])
with tabs[0]:
    with st.container(border=True):
        filtered = exception_overview_filters(exceptions, chosen_date)
    overview(filtered, st.session_state.validated_sheets["Orders"])
with tabs[1]: orders_view(exceptions, st.session_state.validated_sheets, st.session_state.analysis_result, chosen_date)
with tabs[2]: materials_view(exceptions, st.session_state.validated_sheets, st.session_state.analysis_result, chosen_date)
with tabs[3]: pending_view(st.session_state.validated_sheets, exceptions, chosen_date)

with st.expander("Exception Review Status · Session Only"):
    workflow_view(exceptions)

st.divider()
st.markdown("## AI Planning Copilot")
st.caption("Reviews one selected order line using complete verified analysis results. Filters in Exception Overview do not affect this section.")
with st.container(border=True):
    ai_view(exceptions, ai_candidates, st.session_state.analysis_result)

st.divider()
with st.expander("Export Results"):
    st.caption("Exports always include the full analyzed dataset.")
    result = st.session_state.analysis_result; d1,d2 = st.columns(2); d1.download_button("Download Shortage Results · Excel", results_to_excel(result), "shortage_results.xlsx"); d2.download_button("Download Shortage Results · CSV", results_to_csv(result), "shortage_results.csv")
    export = exceptions.copy().rename(columns={"Responsible_Role": "Suggested_Responsible_Function"}); metadata = {"Analysis_Date": chosen_date, "Source_Upload_Identity": st.session_state.source_identity, "AI_Execution_Status": "NOT_EXECUTED", "Human_Review_Required": True, "Workflow_Persistence": "SESSION_ONLY"}
    for key,value in metadata.items(): export[key] = value
    order_export = build_order_summary(exceptions, st.session_state.validated_sheets["Orders"]).rename(columns={"Responsible_Roles": "Suggested_Responsible_Functions"})
    e1,e2 = st.columns(2); e1.download_button("Download Exception Register · CSV", export.to_csv(index=False).encode("utf-8-sig"), "exception_register.csv"); e2.download_button("Download Order Summary · CSV", order_export.to_csv(index=False).encode("utf-8-sig"), "order_summary.csv")
