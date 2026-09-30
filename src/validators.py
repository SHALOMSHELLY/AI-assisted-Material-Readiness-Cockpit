"""Validate workbook structure, fields, and cross-sheet relationships."""
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
import pandas as pd
from config.settings import ACTIVE_PRODUCTION_ORDER_STATUSES, ORDER_STATUSES, PO_STATUSES, PRODUCTION_ORDER_STATUSES, REQUIRED_SHEETS, STOCK_TYPES
from src.data_models import Severity, ValidationIssue, ValidationReport
SHEET_RULES = {'Orders': {'columns': ['Sales_Order_ID', 'Sales_Order_Item', 'Customer_ID', 'Product_ID', 'Requested_Quantity', 'Quantity_Unit', 'Requested_Delivery_Date', 'Plant', 'Order_Status'], 'required': ['Sales_Order_ID', 'Sales_Order_Item', 'Product_ID', 'Requested_Quantity', 'Quantity_Unit', 'Requested_Delivery_Date', 'Plant', 'Order_Status'], 'key': ['Sales_Order_ID', 'Sales_Order_Item']}, 'BOM': {'columns': ['BOM_ID', 'BOM_Item_ID', 'Parent_Product_ID', 'Plant', 'BOM_Usage', 'Alternative_BOM', 'Base_Quantity', 'Base_Quantity_Unit', 'Component_Material_ID', 'Component_Quantity', 'Component_Unit', 'Valid_From', 'Valid_To'], 'required': ['BOM_ID', 'BOM_Item_ID', 'Parent_Product_ID', 'Plant', 'BOM_Usage', 'Alternative_BOM', 'Base_Quantity', 'Base_Quantity_Unit', 'Component_Material_ID', 'Component_Quantity', 'Component_Unit', 'Valid_From'], 'key': ['BOM_ID', 'BOM_Item_ID']}, 'Inventory': {'columns': ['Material_ID', 'Plant', 'Storage_Location', 'Stock_Type', 'Quantity', 'Base_Unit', 'Safety_Stock', 'Snapshot_Date'], 'required': ['Material_ID', 'Plant', 'Storage_Location', 'Stock_Type', 'Quantity', 'Base_Unit', 'Safety_Stock', 'Snapshot_Date'], 'key': ['Material_ID', 'Plant', 'Storage_Location', 'Stock_Type']}, 'Incoming_PO': {'columns': ['PO_ID', 'PO_Item', 'Schedule_Line', 'Material_ID', 'Plant', 'Storage_Location', 'Ordered_Quantity', 'Received_Quantity', 'Open_Quantity', 'Quantity_Unit', 'Expected_Receipt_Date', 'PO_Status', 'Deletion_Flag', 'Completely_Delivered_Flag', 'Supplier_ID'], 'required': ['PO_ID', 'PO_Item', 'Schedule_Line', 'Material_ID', 'Plant', 'Storage_Location', 'Ordered_Quantity', 'Received_Quantity', 'Open_Quantity', 'Quantity_Unit', 'Expected_Receipt_Date', 'PO_Status', 'Deletion_Flag', 'Completely_Delivered_Flag'], 'key': ['PO_ID', 'PO_Item', 'Schedule_Line']}, 'Production_Orders': {'columns': ['Production_Order_ID', 'Production_Order_Item', 'Source_Sales_Order_ID', 'Source_Sales_Order_Item', 'Product_ID', 'Plant', 'Total_Quantity', 'Confirmed_Yield_Quantity', 'Remaining_Quantity', 'Quantity_Unit', 'Planned_Start_Date', 'Planned_End_Date', 'Order_Status'], 'required': ['Production_Order_ID', 'Production_Order_Item', 'Product_ID', 'Plant', 'Total_Quantity', 'Confirmed_Yield_Quantity', 'Remaining_Quantity', 'Quantity_Unit', 'Planned_Start_Date', 'Planned_End_Date', 'Order_Status'], 'key': ['Production_Order_ID', 'Production_Order_Item']}}
NUMERIC_RULES = {'Orders': {'Requested_Quantity': 'positive'}, 'BOM': {'Base_Quantity': 'positive', 'Component_Quantity': 'positive'}, 'Inventory': {'Quantity': 'nonnegative', 'Safety_Stock': 'nonnegative'}, 'Incoming_PO': {'Ordered_Quantity': 'nonnegative', 'Received_Quantity': 'nonnegative', 'Open_Quantity': 'nonnegative'}, 'Production_Orders': {'Total_Quantity': 'nonnegative', 'Confirmed_Yield_Quantity': 'nonnegative', 'Remaining_Quantity': 'nonnegative'}}
DATE_RULES = {'Orders': ['Requested_Delivery_Date'], 'BOM': ['Valid_From', 'Valid_To'], 'Inventory': ['Snapshot_Date'], 'Incoming_PO': ['Expected_Receipt_Date'], 'Production_Orders': ['Planned_Start_Date', 'Planned_End_Date']}

def validate_workbook(sheets: dict[str, pd.DataFrame], analysis_date: date) -> ValidationReport:
    """Validate workbook structure and data without allocating supply."""
    report = ValidationReport()
    _validate_sheet_names(sheets, report)
    valid_columns = _validate_columns(sheets, report)
    for sheet_name in REQUIRED_SHEETS:
        if sheet_name not in sheets or not valid_columns.get(sheet_name, False):
            continue
        frame = sheets[sheet_name]
        _validate_required_values(sheet_name, frame, report)
        _validate_unique_key(sheet_name, frame, SHEET_RULES[sheet_name]['key'], report)
        _validate_numeric_fields(sheet_name, frame, report)
        _validate_date_fields(sheet_name, frame, report)
    _validate_allowed_values(sheets, valid_columns, report)
    _validate_bom_dates(sheets, valid_columns, report)
    _validate_bom_header_consistency(sheets, valid_columns, report)
    _validate_bom_material_metadata(sheets, valid_columns, report)
    _validate_inventory(sheets, valid_columns, analysis_date, report)
    _validate_purchase_orders(sheets, valid_columns, report)
    _validate_production_orders(sheets, valid_columns, report)
    _validate_source_orders(sheets, valid_columns, report)
    _validate_demand_relationships(sheets, valid_columns, analysis_date, report)
    return report

def _issue(report: ValidationReport, severity: Severity, code: str, sheet: str, row: int | None, field: str, value: Any, message: str, fix: str) -> None:
    report.add(ValidationIssue(severity, code, sheet, row, field, _display_value(value), message, fix))

def _display_value(value: Any) -> Any:
    if _is_blank(value):
        return '<blank>'
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.strftime('%Y-%m-%d')
    if hasattr(value, 'item'):
        return value.item()
    return value

def _is_blank(value: Any) -> bool:
    if value is None or (isinstance(value, str) and (not value.strip())):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False

def _text(value: Any) -> str:
    return '' if _is_blank(value) else str(value).strip()

def _number(value: Any) -> float | None:
    if _is_blank(value) or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _date_value(value: Any) -> date | None:
    if _is_blank(value):
        return None
    parsed = pd.to_datetime(value, errors='coerce')
    return None if pd.isna(parsed) else parsed.date()

def _flag(value: Any) -> bool | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None

def _rows(frame: pd.DataFrame) -> Iterable[tuple[int, pd.Series]]:
    for fallback_position, (index, row) in enumerate(frame.iterrows(), start=2):
        row_number = int(index) + 2 if isinstance(index, int) else fallback_position
        yield (row_number, row)

def _validate_sheet_names(sheets: dict[str, pd.DataFrame], report: ValidationReport) -> None:
    for name in REQUIRED_SHEETS:
        if name not in sheets:
            _issue(report, 'DATA_ERROR', 'MISSING_SHEET', name, None, '<sheet>', name, f'Required worksheet {name} is missing.', f'Add a worksheet named exactly {name}.')
    for name in sheets:
        if name not in REQUIRED_SHEETS:
            _issue(report, 'WARNING', 'EXTRA_SHEET', name, None, '<sheet>', name, f'Worksheet {name} is not required and will be ignored.', 'No fix is required; remove it manually if unnecessary.')

def _validate_columns(sheets: dict[str, pd.DataFrame], report: ValidationReport) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for sheet_name, rules in SHEET_RULES.items():
        if sheet_name not in sheets:
            result[sheet_name] = False
            continue
        missing = [column for column in rules['columns'] if column not in sheets[sheet_name].columns]
        result[sheet_name] = not missing
        for column in missing:
            _issue(report, 'DATA_ERROR', 'MISSING_COLUMN', sheet_name, 1, column, '<missing>', f'The {sheet_name} sheet is missing required column {column}.', f'Add column {column} in row 1.')
    return result

def _validate_required_values(sheet_name: str, frame: pd.DataFrame, report: ValidationReport) -> None:
    for row_number, row in _rows(frame):
        for field in SHEET_RULES[sheet_name]['required']:
            if _is_blank(row[field]):
                _issue(report, 'DATA_ERROR', 'MISSING_REQUIRED_VALUE', sheet_name, row_number, field, row[field], f'{field} is required but blank.', 'Enter a value that follows the data dictionary.')

def _validate_unique_key(sheet_name: str, frame: pd.DataFrame, fields: list[str], report: ValidationReport) -> None:
    usable = frame[fields].apply(lambda column: column.map(_text))
    duplicated = usable.duplicated(keep=False) & usable.ne('').all(axis=1)
    for position in frame.index[duplicated]:
        row_number = int(position) + 2
        value = ' + '.join(usable.loc[position, fields])
        _issue(report, 'DATA_ERROR', 'DUPLICATE_KEY', sheet_name, row_number, ' + '.join(fields), value, f'Composite unique key {value} is duplicated.', 'Remove the duplicate row or correct the key fields.')

def _validate_numeric_fields(sheet_name: str, frame: pd.DataFrame, report: ValidationReport) -> None:
    for row_number, row in _rows(frame):
        for field, rule in NUMERIC_RULES[sheet_name].items():
            if _is_blank(row[field]):
                continue
            number = _number(row[field])
            if number is None:
                _issue(report, 'DATA_ERROR', 'INVALID_NUMBER', sheet_name, row_number, field, row[field], f'{field} must be numeric.', 'Enter a number.')
            elif rule == 'positive' and number <= 0 or (rule == 'nonnegative' and number < 0):
                boundary = '0' if rule == 'positive' else '0'
                boundary_en = 'greater than 0' if rule == 'positive' else 'greater than or equal to 0'
                _issue(report, 'DATA_ERROR', 'INVALID_QUANTITY_RANGE', sheet_name, row_number, field, row[field], f'{field} must be {boundary_en}.', f'Change the value so it is {boundary_en}.')

def _validate_date_fields(sheet_name: str, frame: pd.DataFrame, report: ValidationReport) -> None:
    for row_number, row in _rows(frame):
        for field in DATE_RULES[sheet_name]:
            if field == 'Valid_To' and _is_blank(row[field]):
                continue
            if not _is_blank(row[field]) and _date_value(row[field]) is None:
                _issue(report, 'DATA_ERROR', 'INVALID_DATE', sheet_name, row_number, field, row[field], f'{field} is not a valid date.', 'Enter a date recognized by Excel.')

def _validate_allowed_values(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], report: ValidationReport) -> None:
    rules = [('Orders', 'Order_Status', ORDER_STATUSES), ('Inventory', 'Stock_Type', STOCK_TYPES), ('Incoming_PO', 'PO_Status', PO_STATUSES), ('Production_Orders', 'Order_Status', PRODUCTION_ORDER_STATUSES)]
    for sheet_name, field, allowed in rules:
        if not valid.get(sheet_name):
            continue
        for row_number, row in _rows(sheets[sheet_name]):
            value = _text(row[field]).upper()
            if value and value not in allowed:
                _issue(report, 'DATA_ERROR', 'INVALID_STATUS', sheet_name, row_number, field, row[field], f'Value {value} in {field} is not allowed.', f"Use one of: {', '.join(sorted(allowed))}.")

def _validate_bom_dates(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], report: ValidationReport) -> None:
    if not valid.get('BOM'):
        return
    for row_number, row in _rows(sheets['BOM']):
        start, end = (_date_value(row['Valid_From']), _date_value(row['Valid_To']))
        if start and end and (start > end):
            _issue(report, 'DATA_ERROR', 'BOM_DATE_RANGE', 'BOM', row_number, 'Valid_From + Valid_To', f'{start} > {end}', 'BOM Valid_From is later than Valid_To.', 'Correct the dates so Valid_From is not later than Valid_To.')

def _validate_bom_header_consistency(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], report: ValidationReport) -> None:
    """Validate header fields shared by every item in one BOM."""
    if not valid.get('BOM'):
        return
    frame = sheets['BOM']
    key_fields = ['BOM_ID', 'BOM_Usage', 'Alternative_BOM']
    header_fields = ['Parent_Product_ID', 'Plant', 'Base_Quantity', 'Base_Quantity_Unit']
    grouped = frame.groupby(key_fields, dropna=False, sort=False)
    for key, group in grouped:
        bom_label = ' + '.join((_text(value) for value in key))
        excel_rows = [int(index) + 2 for index in group.index]
        for field in header_fields:
            if field == 'Base_Quantity':
                values = {_number(value) for value in group[field] if _number(value) is not None}
            else:
                values = {_text(value) for value in group[field] if _text(value)}
            if len(values) <= 1:
                continue
            rows_text = ', '.join(map(str, excel_rows))
            _issue(report, 'DATA_ERROR', 'INCONSISTENT_BOM_HEADER', 'BOM', excel_rows[0], field, f'BOM {bom_label}; rows {rows_text}; values {sorted(map(str, values))}', f'BOM {bom_label} has inconsistent {field} values in Excel rows {rows_text}.', f'Use one correct {field} value across Excel rows {rows_text}.')


def _validate_bom_material_metadata(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], report: ValidationReport) -> None:
    """Prevent first-row-wins material labels within the same plant."""
    if not valid.get('BOM'):
        return
    frame = sheets['BOM']
    fields = [field for field in ('Component_Material_Description', 'Material_Category') if field in frame]
    if not fields:
        return
    for (material, plant), group in frame.groupby(['Component_Material_ID', 'Plant'], dropna=False, sort=False):
        rows = [int(index) + 2 for index in group.index]
        for field in fields:
            values = {_text(value) for value in group[field] if _text(value)}
            if len(values) <= 1:
                continue
            _issue(
                report, 'DATA_ERROR', 'INCONSISTENT_MATERIAL_METADATA', 'BOM', rows[0], field,
                f'Material {material}; plant {plant}; rows {rows}; values {sorted(values)}',
                f'Material {material} has inconsistent {field} values in plant {plant}.',
                f'Use one {field} value for material {material} in plant {plant}.',
            )

def _validate_inventory(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], analysis_date: date, report: ValidationReport) -> None:
    if not valid.get('Inventory'):
        return
    frame = sheets['Inventory']
    dated = [(row_number, _date_value(row['Snapshot_Date']), row['Snapshot_Date']) for row_number, row in _rows(frame)]
    distinct = {value for _, value, _ in dated if value is not None}
    if len(distinct) > 1:
        _issue(report, 'DATA_ERROR', 'MULTIPLE_SNAPSHOT_DATES', 'Inventory', None, 'Snapshot_Date', sorted(map(str, distinct)), 'Inventory contains multiple Snapshot_Date values.', 'Use one valid snapshot date for all inventory rows.')
    for row_number, value, original in dated:
        if value and value > analysis_date:
            _issue(report, 'DATA_ERROR', 'FUTURE_SNAPSHOT_DATE', 'Inventory', row_number, 'Snapshot_Date', original, 'Snapshot_Date is later than Analysis_Date.', 'Use an inventory snapshot no later than the analysis date.')
    grouped = frame.groupby(['Material_ID', 'Plant'], dropna=False)
    for (material, plant), group in grouped:
        values = {_number(value) for value in group['Safety_Stock'] if _number(value) is not None}
        if len(values) > 1:
            for index in group.index:
                _issue(report, 'DATA_ERROR', 'INCONSISTENT_SAFETY_STOCK', 'Inventory', int(index) + 2, 'Safety_Stock', frame.loc[index, 'Safety_Stock'], f'Material {material} has inconsistent Safety Stock values in plant {plant}.', 'Use one consistent Safety Stock value for the material and plant.')

def _validate_purchase_orders(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], report: ValidationReport) -> None:
    if not valid.get('Incoming_PO'):
        return
    for row_number, row in _rows(sheets['Incoming_PO']):
        ordered, received, opened = (_number(row[field]) for field in ('Ordered_Quantity', 'Received_Quantity', 'Open_Quantity'))
        if None not in (ordered, received, opened):
            expected = max(0.0, ordered - received)
            if abs(opened - expected) > 1e-09:
                _issue(report, 'DATA_ERROR', 'OPEN_QUANTITY_MISMATCH', 'Incoming_PO', row_number, 'Open_Quantity', row['Open_Quantity'], f'Open_Quantity should be {expected:g}.', 'Use the non-negative result of Ordered_Quantity minus Received_Quantity.')
        deletion, delivered = (_flag(row['Deletion_Flag']), _flag(row['Completely_Delivered_Flag']))
        for field, parsed in (('Deletion_Flag', deletion), ('Completely_Delivered_Flag', delivered)):
            if parsed is None:
                _issue(report, 'DATA_ERROR', 'INVALID_BOOLEAN', 'Incoming_PO', row_number, field, row[field], f'{field} must be TRUE or FALSE.', 'Enter the Excel Boolean value TRUE or FALSE.')
        status = _text(row['PO_Status']).upper()
        if status == 'OPEN' and delivered is True or (status == 'COMPLETED' and opened is not None and (opened > 0)):
            _issue(report, 'DATA_ERROR', 'PO_STATUS_FLAG_CONFLICT', 'Incoming_PO', row_number, 'PO_Status + Flags', status, 'PO status, open quantity, and completion flag conflict.', 'Correct the status, quantity, or flags to match the business state.')

def _validate_production_orders(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], report: ValidationReport) -> None:
    if not valid.get('Production_Orders'):
        return
    for row_number, row in _rows(sheets['Production_Orders']):
        total, confirmed, remaining = (_number(row[field]) for field in ('Total_Quantity', 'Confirmed_Yield_Quantity', 'Remaining_Quantity'))
        if None not in (total, confirmed, remaining):
            expected = max(0.0, total - confirmed)
            if abs(remaining - expected) > 1e-09:
                _issue(report, 'DATA_ERROR', 'REMAINING_QUANTITY_MISMATCH', 'Production_Orders', row_number, 'Remaining_Quantity', row['Remaining_Quantity'], f'Remaining_Quantity should be {expected:g}.', 'Use the non-negative result of Total_Quantity minus Confirmed_Yield_Quantity.')
        start, end = (_date_value(row['Planned_Start_Date']), _date_value(row['Planned_End_Date']))
        if start and end and (start > end):
            _issue(report, 'DATA_ERROR', 'PRODUCTION_DATE_RANGE', 'Production_Orders', row_number, 'Planned_Start_Date + Planned_End_Date', f'{start} > {end}', 'Planned start date is later than planned end date.', 'Correct the dates so start is not later than end.')

def _validate_source_orders(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], report: ValidationReport) -> None:
    if not valid.get('Production_Orders'):
        return
    order_keys: set[tuple[str, str]] = set()
    if valid.get('Orders'):
        order_keys = {(_text(row['Sales_Order_ID']), _text(row['Sales_Order_Item'])) for _, row in _rows(sheets['Orders'])}
    for row_number, row in _rows(sheets['Production_Orders']):
        source_id, source_item = (_text(row['Source_Sales_Order_ID']), _text(row['Source_Sales_Order_Item']))
        if bool(source_id) != bool(source_item):
            _issue(report, 'DATA_ERROR', 'SOURCE_ORDER_PAIR', 'Production_Orders', row_number, 'Source_Sales_Order_ID + Source_Sales_Order_Item', f'{source_id} + {source_item}', 'Source sales-order ID and item must both be blank or both populated.', 'Clear both fields or populate both with a valid composite key.')
        elif valid.get('Orders') and source_id and source_item and ((source_id, source_item) not in order_keys):
            _issue(report, 'DATA_ERROR', 'SOURCE_ORDER_NOT_FOUND', 'Production_Orders', row_number, 'Source_Sales_Order_ID + Source_Sales_Order_Item', f'{source_id} + {source_item}', 'The source sales-order composite key does not exist in Orders.', 'Correct the source key or add the matching order item to Orders.')

def _validate_demand_relationships(sheets: dict[str, pd.DataFrame], valid: dict[str, bool], analysis_date: date, report: ValidationReport) -> None:
    required = {'Production_Orders', 'BOM', 'Inventory', 'Incoming_PO'}
    if not all((valid.get(name) for name in required)):
        return
    production = sheets['Production_Orders']
    bom = sheets['BOM']
    inventory = sheets['Inventory']
    incoming = sheets['Incoming_PO']
    prepared_bom = bom.copy()
    prepared_bom['_parent'] = prepared_bom['Parent_Product_ID'].map(_text)
    prepared_bom['_plant'] = prepared_bom['Plant'].map(_text)
    prepared_bom['_base_unit'] = prepared_bom['Base_Quantity_Unit'].map(_text)
    prepared_bom['_valid_from'] = pd.to_datetime(prepared_bom['Valid_From'], errors='coerce')
    prepared_bom['_valid_to'] = pd.to_datetime(prepared_bom['Valid_To'], errors='coerce')
    bom_by_product_plant = {
        (_text(product), _text(plant)): group
        for (product, plant), group in prepared_bom.groupby(['_parent', '_plant'], sort=False)
    }
    inventory_by_material_plant = {
        (_text(material), _text(plant)): group
        for (material, plant), group in inventory.groupby(['Material_ID', 'Plant'], sort=False, dropna=False)
    }
    inventory_units_by_material_plant = {
        key: {_text(value) for value in group['Base_Unit']}
        for key, group in inventory_by_material_plant.items()
    }
    po_by_material_plant = {
        (_text(material), _text(plant)): group
        for (material, plant), group in incoming.groupby(['Material_ID', 'Plant'], sort=False, dropna=False)
    }
    po_units_by_material_plant = {
        key: {_text(value) for value in group['Quantity_Unit']}
        for key, group in po_by_material_plant.items()
    }
    demanded_components: set[tuple[str, str, str]] = set()
    for prod_row_number, prod in _rows(production):
        if _text(prod['Order_Status']).upper() not in ACTIVE_PRODUCTION_ORDER_STATUSES:
            continue
        remaining = _number(prod['Remaining_Quantity'])
        if remaining is None or remaining <= 0:
            continue
        need_date = _date_value(prod['Planned_Start_Date'])
        if need_date is None:
            continue
        need_timestamp = pd.Timestamp(need_date)
        product, plant, unit = (_text(prod['Product_ID']), _text(prod['Plant']), _text(prod['Quantity_Unit']))
        product_plant = bom_by_product_plant.get((product, plant), prepared_bom.iloc[0:0])
        same_unit = product_plant[product_plant['_base_unit'] == unit]
        effective = same_unit[(same_unit['_valid_from'].notna()) & (same_unit['_valid_from'] <= need_timestamp) & (same_unit['_valid_to'].isna() | (same_unit['_valid_to'] >= need_timestamp))]
        if effective.empty:
            code = 'PRODUCTION_BOM_UNIT_MISMATCH' if not product_plant.empty and same_unit.empty else 'EFFECTIVE_BOM_NOT_FOUND'
            zh = 'BOM.' if code.endswith('UNIT_MISMATCH') else 'BOM.'
            en = 'Production-order unit does not match the BOM base unit.' if code.endswith('UNIT_MISMATCH') else 'No effective BOM was found on the material need date.'
            _issue(report, 'DATA_ERROR', code, 'Production_Orders', prod_row_number, 'Product_ID + Plant + Quantity_Unit', f'{product} + {plant} + {unit}', en, 'Correct the product, plant, unit, or BOM validity period.')
            continue
        bom_choices = effective[['BOM_ID', 'BOM_Usage', 'Alternative_BOM']].astype(str).drop_duplicates()
        if len(bom_choices) != 1:
            _issue(report, 'DATA_ERROR', 'MULTIPLE_EFFECTIVE_BOMS', 'Production_Orders', prod_row_number, 'Product_ID + Plant', f'{product} + {plant}', 'Multiple BOMs are effective on the material need date and version 1 cannot select one uniquely.', 'Adjust BOM validity or alternatives so exactly one BOM is effective on the need date.')
            continue
        choice = tuple(bom_choices.iloc[0])
        selected = effective[(effective['BOM_ID'].astype(str) == choice[0]) & (effective['BOM_Usage'].astype(str) == choice[1]) & (effective['Alternative_BOM'].astype(str) == choice[2])]
        for _, component in selected.iterrows():
            material, component_unit = (_text(component['Component_Material_ID']), _text(component['Component_Unit']))
            demanded_components.add((material, plant, component_unit))
            child_pool = bom_by_product_plant.get((material, plant), prepared_bom.iloc[0:0])
            child_boms = child_pool[(child_pool['_valid_from'].notna()) & (child_pool['_valid_from'] <= need_timestamp) & (child_pool['_valid_to'].isna() | (child_pool['_valid_to'] >= need_timestamp))]
            if not child_boms.empty:
                child_row = int(child_boms.index[0]) + 2
                _issue(report, 'DATA_ERROR', 'UNSUPPORTED_MULTILEVEL_BOM', 'BOM', child_row, 'Parent_Product_ID', material, f'Component {material} in the current effective demand also has an effective BOM in the same plant on the need date; an unsupported multilevel BOM was detected.', 'Provide a single-level BOM for the current demand in version 1.')
            inventory_match = inventory_by_material_plant.get((material, plant), inventory.iloc[0:0])
            if inventory_match.empty:
                _issue(report, 'WARNING', 'MISSING_INVENTORY_AS_ZERO', 'Inventory', None, 'Material_ID + Plant', f'{material} + {plant}', f'Effective BOM component {material} has no inventory row in plant {plant}; usable inventory will be treated as zero.', 'Add a same-plant, same-unit inventory row if stock exists.')
            else:
                if inventory_units_by_material_plant[(material, plant)] != {component_unit}:
                    for inv_index, inv in inventory_match.iterrows():
                        if _text(inv['Base_Unit']) != component_unit:
                            _issue(report, 'DATA_ERROR', 'INVENTORY_UNIT_MISMATCH', 'Inventory', int(inv_index) + 2, 'Base_Unit', inv['Base_Unit'], f'Inventory unit for component {material} does not match the BOM component unit.', 'Align BOM component and inventory base units; version 1 does not convert units.')
    demanded_material_plants = {key[:2] for key in demanded_components}
    for row_number, po in _rows(incoming):
        status = _text(po['PO_Status']).upper()
        deletion = _flag(po['Deletion_Flag'])
        delivered = _flag(po['Completely_Delivered_Flag'])
        open_quantity = _number(po['Open_Quantity'])
        if status not in PO_STATUSES or deletion is None or delivered is None or (open_quantity is None) or (open_quantity < 0):
            continue
        if status in {'COMPLETED', 'CANCELLED'} or deletion or delivered or (open_quantity == 0):
            _issue(report, 'IGNORED', 'INACTIVE_INCOMING_PO', 'Incoming_PO', row_number, 'PO_Status + Flags + Open_Quantity', status, 'This PO schedule line does not participate in future supply and was excluded before demand matching and unit validation.', 'No fix is required; if it should participate in future supply, review status, deletion flag, completely delivered flag, and open quantity.')
            continue
        key = (_text(po['Material_ID']), _text(po['Plant']), _text(po['Quantity_Unit']))
        material_plant_relevant = key[:2] in demanded_material_plants
        if key not in demanded_components:
            if material_plant_relevant:
                _issue(report, 'DATA_ERROR', 'PO_UNIT_MISMATCH', 'Incoming_PO', row_number, 'Quantity_Unit', po['Quantity_Unit'], 'PO unit does not match the current effective BOM component unit.', 'Align PO and BOM component units; version 1 does not convert units.')
            else:
                _issue(report, 'IGNORED', 'UNRELATED_INCOMING_PO', 'Incoming_PO', row_number, 'Material_ID + Plant', f'{key[0]} + {key[1]}', 'This PO schedule line is unrelated to current effective BOM demand and was ignored.', 'No fix is required; if it should participate, check product, BOM, plant, and material.')
            continue
        receipt_date = _date_value(po['Expected_Receipt_Date'])
        if receipt_date is not None and receipt_date < analysis_date:
            _issue(report, 'WARNING', 'OVERDUE_INCOMING_PO', 'Incoming_PO', row_number, 'Expected_Receipt_Date', po['Expected_Receipt_Date'], 'This open PO schedule line is overdue and is excluded from eligible supply and allocation.', 'Confirm the supply status and update Expected_Receipt_Date.')
