"""Small pure helpers for Streamlit state."""

import hashlib
from datetime import date


def upload_signature(content: bytes, analysis_date: date) -> str:
    """Identify an input using its SHA-256 digest and analysis date."""

    return f"{hashlib.sha256(content).hexdigest()}:{analysis_date.isoformat()}"


def llm_cache_key(upload_id: str, row_identity: str, model: str, prompt_version: str, schema_version: str) -> str:
    """Bind the session cache to source, row, model, prompt, and schema."""

    return "|".join((upload_id, row_identity, model, prompt_version, schema_version))
