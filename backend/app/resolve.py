"""AI resolve step: match each transaction narrative against the master lists.

Calls the Claude API using forced tool use so the response is always
parseable structured JSON, never free text. The AI proposes a match; it does
not decide one — every row still carries a confidence score for a human
analyst to verify against the row's screenshot.
"""

from __future__ import annotations

import logging
from pathlib import Path

import anthropic

from app.core.config import settings
from app.extract import TransactionRow

logger = logging.getLogger(__name__)

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
BATCH_SIZE = 8
MAX_RETRIES = 2
VALID_METRICS = {
    "vendor payment",
    "investment transfer",
    "investor movement",
    "internal",
    "review",
}

TOOL_SCHEMA = {
    "name": "record_matches",
    "description": (
        "Record the resolved company, metric and confidence for each "
        "transaction row in this batch."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "row_id": {"type": "string"},
                        "company": {"type": ["string", "null"]},
                        "metric": {
                            "type": "string",
                            "enum": sorted(VALID_METRICS),
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["row_id", "company", "metric", "confidence"],
                },
            }
        },
        "required": ["results"],
    },
}


def _load_master_lists() -> str:
    files = [
        ("Legal Entity Master List", "legal_entity_master_list.txt"),
        ("Vendor Master List", "vendor_master_list.txt"),
        ("Investor Master List", "investor_master_list.txt"),
        ("Project Code Report", "project_code_report.txt"),
    ]
    blocks = []
    for title, filename in files:
        path = REFERENCE_DIR / filename
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        blocks.append(f"### {title}\n{content}")
    return "\n\n".join(blocks)


_MASTER_LISTS_TEXT = _load_master_lists()


def _batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _build_prompt(batch: list[TransactionRow]) -> str:
    lines = [
        "Match each transaction row below to a company from the master "
        "lists provided, and classify it.",
        "",
        "Only return a company name if it appears in the provided lists. "
        'If none of the candidates plausibly match, return null for company '
        'and use metric "review".',
        "",
        "Transaction rows:",
    ]
    for row in batch:
        lines.append(
            f"- row_id: {row.row_id}\n"
            f"  narrative: {row.narrative}\n"
            f"  credit_amount: {row.credit_amount}\n"
            f"  debit_amount: {row.debit_amount}\n"
            f"  currency: {row.currency}"
        )
    lines.append("")
    lines.append("Master lists:")
    lines.append(_MASTER_LISTS_TEXT)
    return "\n".join(lines)


def _default_result(row_id: str) -> dict:
    return {"row_id": row_id, "company": None, "metric": "review", "confidence": 0.0}


def _call_batch(client: anthropic.Anthropic, batch: list[TransactionRow]) -> dict[str, dict]:
    prompt = _build_prompt(batch)
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                tools=[TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": "record_matches"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "record_matches":
                    results = block.input.get("results", [])
                    parsed: dict[str, dict] = {}
                    for item in results:
                        row_id = item.get("row_id")
                        if not row_id:
                            continue
                        metric = item.get("metric")
                        if metric not in VALID_METRICS:
                            metric = "review"
                        confidence = item.get("confidence")
                        try:
                            confidence = max(0.0, min(1.0, float(confidence)))
                        except (TypeError, ValueError):
                            confidence = 0.0
                        parsed[row_id] = {
                            "row_id": row_id,
                            "company": item.get("company"),
                            "metric": metric,
                            "confidence": confidence,
                        }
                    return parsed
            last_error = ValueError("no tool_use block in response")
        except Exception as exc:
            last_error = exc
            logger.warning("resolve batch attempt %s failed: %s", attempt, exc)

    logger.error("resolve batch failed after retries: %s", last_error)
    return {}


def resolve_rows(rows: list[TransactionRow]) -> list[dict]:
    """Resolve company/metric/confidence for every row, batched per API call."""
    if not rows:
        return []

    resolved: dict[str, dict] = {}

    try:
        client: anthropic.Anthropic | None = anthropic.Anthropic(
            api_key=settings.anthropic_api_key
        )
    except Exception as exc:
        logger.error("could not construct Anthropic client, marking all rows for review: %s", exc)
        client = None

    for batch in _batched(rows, BATCH_SIZE):
        batch_results = _call_batch(client, batch) if client is not None else {}
        for row in batch:
            resolved[row.row_id] = batch_results.get(row.row_id, _default_result(row.row_id))

    output = []
    for row in rows:
        match = resolved.get(row.row_id, _default_result(row.row_id))
        output.append(
            {
                "account_name": row.account_name,
                "account_number": row.account_number,
                "currency": row.currency,
                "bank_reference": row.bank_reference,
                "customer_reference": row.customer_reference,
                "trn_type": row.trn_type,
                "value_date": row.value_date,
                "credit_amount": row.credit_amount,
                "debit_amount": row.debit_amount,
                "balance": row.balance,
                "post_date": row.post_date,
                "narrative": row.narrative,
                "company": match["company"],
                "metric": match["metric"],
                "confidence": match["confidence"],
                "source_pdf": row.source_pdf,
                "page": row.page,
                "screenshot_path": row.screenshot_path,
            }
        )
    return output
