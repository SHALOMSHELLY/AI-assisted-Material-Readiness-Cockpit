"""Static configuration shared across modules.

This file contains no secrets or business-calculation implementation.
"""

from datetime import date

ANALYSIS_DATE_FOR_TESTS = date(2026, 9, 25)
REQUIRED_SHEETS = (
    "Orders",
    "BOM",
    "Inventory",
    "Incoming_PO",
    "Production_Orders",
)

ORDER_STATUSES = {"OPEN", "COMPLETED", "CANCELLED"}
STOCK_TYPES = {
    "UNRESTRICTED",
    "QUALITY_INSPECTION",
    "BLOCKED",
    "IN_TRANSFER",
    "RESTRICTED",
}
PO_STATUSES = {"OPEN", "PARTIALLY_RECEIVED", "COMPLETED", "CANCELLED"}
PRODUCTION_ORDER_STATUSES = {
    "CREATED",
    "RELEASED",
    "PARTIALLY_CONFIRMED",
    "CONFIRMED",
    "COMPLETED",
    "CLOSED",
    "CANCELLED",
    "DELETED",
}
ACTIVE_PRODUCTION_ORDER_STATUSES = {"CREATED", "RELEASED", "PARTIALLY_CONFIRMED"}

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4.1-mini"
LLM_REQUEST_TIMEOUT_SECONDS = 45
LLM_MAX_OUTPUT_TOKENS = 6000

# Official list-price snapshot; estimation only, not a final OpenRouter bill.
# ;,OpenRouter.
MODEL_PRICING_USD_PER_MILLION_TOKENS = {
    "openai/gpt-4.1-mini": {
        "input": 0.40,
        "output": 1.60,
        "cache_read": 0.10,
        "source": "https://openrouter.ai/openai/gpt-4.1-mini",
        "as_of": "2026-09-24",
        "unit": "USD per 1,000,000 tokens",
    }
}
