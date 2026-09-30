"""Stable fictional master data for Apex Industrial Controls."""

PRODUCTS = [
    ("CC", "Control Cabinet", "Control Cabinets"), ("MSP", "Motor Starter Panel", "Motor Control"),
    ("SCU", "Sensor Control Unit", "Sensor Systems"), ("CCB", "Conveyor Control Box", "Conveyor Controls"),
    ("PCP", "Pump Control Panel", "Pump Controls"), ("DCP", "Distribution Control Panel", "Distribution"),
    ("MSF", "Machine Safety Panel", "Machine Safety"), ("IAU", "Industrial Automation Unit", "Automation"),
]
COMPONENTS = [
    ("CTRL-24V-01", "24V Controller", "Controller"), ("CTRL-PLC-A2", "PLC Controller A2", "Controller"),
    ("SW-PUSH-GRN", "Green Push Button", "Switch"), ("SW-EMG-RED", "Red Emergency Switch", "Switch"),
    ("SW-SELECT-02", "Two-position Selector Switch", "Switch"), ("SENSOR-PROX-M18", "M18 Proximity Sensor", "Sensor"),
    ("SENSOR-PHOTO-01", "Photoelectric Sensor", "Sensor"), ("RELAY-24V-02", "24V Control Relay", "Relay"),
    ("CONTACTOR-32A", "32A Contactor", "Contactor"), ("PSU-24V-10A", "24V 10A Power Supply", "Power Supply"),
    ("PCB-CTRL-A2", "Control PCB A2", "PCB"), ("TERM-12P", "12-position Terminal Block", "Terminal"),
    ("MOTOR-075KW", "0.75kW Motor", "Motor"), ("ENC-IP65-M", "Medium IP65 Enclosure", "Enclosure"),
    ("CABLE-CTRL-05M", "5m Control Cable Assembly", "Cable"), ("FUSE-10A", "10A Industrial Fuse", "Protection Device"),
    ("CB-3P-32A", "3-pole 32A Circuit Breaker", "Protection Device"),
]
PLANTS = ("1010", "2020", "3030", "4040")
SUPPLIERS = [(f"SUP{i:03d}", f"Apex Partner {i:02d}") for i in range(1, 25)]

def product_master(index: int) -> tuple[str, str, str]:
    code, description, family = PRODUCTS[index % len(PRODUCTS)]; variant = index // len(PRODUCTS) + 1
    return f"FG-{code}-{variant:02d}", f"{description} Variant {variant}", family

def component_master(index: int) -> tuple[str, str, str]:
    code, description, category = COMPONENTS[index % len(COMPONENTS)]; variant = index // len(COMPONENTS) + 1
    return (code if variant == 1 else f"{code}-V{variant}", description if variant == 1 else f"{description} Variant {variant}", category)
