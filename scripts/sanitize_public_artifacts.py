"""Create publication-safe evaluation artifacts without changing metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
)


def _public_generation_id(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"sha256:{digest}"


def sanitize_ledger(source: Path, destination: Path) -> int:
    rows = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        row["generation_id"] = _public_generation_id(row.get("generation_id"))
    rendered = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    for pattern in SECRET_PATTERNS:
        if pattern.search(rendered):
            raise ValueError("Refusing to write an artifact containing a secret-like value")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8", newline="\n")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    count = sanitize_ledger(args.source, args.destination)
    print(f"Wrote {count} publication-safe ledger rows to {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
