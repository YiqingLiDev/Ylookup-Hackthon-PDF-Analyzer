"""Stage 3 -- Enrich: match every row in the combined multi-file table
against the internal reference workbook.

Runs once over the full concatenated table (all uploaded PDFs already
extracted + verified independently and combined in code before this
module is called), batched internally for prompt size. Calls the Gemini
API using forced structured output so the response is always parseable
JSON. The AI proposes a match; it does not decide one -- every row still
carries a confidence score for a human analyst to verify against the
row's screenshot.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from app.ai import generate_structured
from app.reference.load_enrichment_data import load_enrichment_data

logger = logging.getLogger(__name__)

BATCH_SIZE = 8

Metric = Literal["vendor payment", "investment transfer", "investor movement", "internal", "review"]

_REFERENCE_TEXT = load_enrichment_data()


class EnrichedMatch(BaseModel):
    row_id: str
    company: str | None = None
    metric: Metric
    enrichment_confidence: float


class EnrichBatchResult(BaseModel):
    results: list[EnrichedMatch]


def _batched(items: list[dict], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _build_prompt(batch: list[dict]) -> str:
    lines = [
        "Match each transaction row below to a company from the reference "
        "data provided, and classify it.",
        "",
        "Only return a company name if it appears in the provided reference "
        "data. If no candidate plausibly matches, return null for company "
        'and use metric "review".',
        "",
        "Transaction rows:",
    ]
    for row in batch:
        lines.append(
            f"- row_id: {row['row_id']}\n"
            f"  narrative: {row.get('narrative')}\n"
            f"  credit_amount: {row.get('credit_amount')}\n"
            f"  debit_amount: {row.get('debit_amount')}\n"
            f"  currency: {row.get('currency')}"
        )
    lines.append("")
    lines.append("Reference data:")
    lines.append(_REFERENCE_TEXT)
    return "\n".join(lines)


def _default_match(row_id: str) -> EnrichedMatch:
    return EnrichedMatch(row_id=row_id, company=None, metric="review", enrichment_confidence=0.0)


def _enrich_batch(batch: list[dict], batch_index: int) -> dict[str, EnrichedMatch]:
    label = f"enrich batch {batch_index} ({len(batch)} rows)"
    result = generate_structured(
        parts=[_build_prompt(batch)], response_schema=EnrichBatchResult, label=label
    )
    if result is None:
        return {}
    return {item.row_id: item for item in result.results}


def enrich_rows(rows: list[dict]) -> list[dict]:
    """Enrich the full combined (multi-file) table in one logical pass,
    batched internally for prompt size. Returns the same rows with
    company/metric/enrichment_confidence attached."""
    if not rows:
        return []

    matches: dict[str, EnrichedMatch] = {}
    for batch_index, batch in enumerate(_batched(rows, BATCH_SIZE)):
        batch_matches = _enrich_batch(batch, batch_index)
        for row in batch:
            matches[row["row_id"]] = batch_matches.get(row["row_id"], _default_match(row["row_id"]))

    output = []
    for row in rows:
        match = matches.get(row["row_id"], _default_match(row["row_id"]))
        enriched = dict(row)
        enriched["company"] = match.company
        enriched["metric"] = match.metric
        enriched["enrichment_confidence"] = match.enrichment_confidence
        output.append(enriched)
    return output
