"""Stage 2 -- Verify: compare Stage 1's extracted values against the actual
page image, correct anything wrong, and assign an extraction_confidence.

Runs per file (each PDF's rows are verified against that PDF's own page
screenshots), batched by page -- every row on the same page shares one
screenshot, so they're verified together in one call.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from app.ai import generate_structured, image_part

logger = logging.getLogger(__name__)

VERIFY_PROMPT_HEADER = """You are verifying transaction data extracted from a bank
statement page against the actual page image attached.

For each extracted row below, compare every field against what is actually
printed on the page image. If a field was extracted incorrectly, return the
corrected value. If a field is correct as extracted, return it unchanged.

Keep amounts as plain numbers with no currency symbols or thousands
separators. Exactly one of credit_amount / debit_amount should be populated
per row. Keep narrative as the full joined text of the transaction,
matching what the page actually shows.

Assign extraction_confidence (0 to 1) per row: how confident you are that
the (possibly corrected) values now match the source page exactly. Use 1.0
only when every field is a confirmed exact match to the page image. If you
made any correction, briefly note what you changed in verification_notes."""

FIELD_NAMES = [
    "account_name",
    "account_number",
    "currency",
    "bank_reference",
    "customer_reference",
    "trn_type",
    "value_date",
    "credit_amount",
    "debit_amount",
    "balance",
    "post_date",
    "narrative",
]


class VerifiedTransaction(BaseModel):
    row_id: str
    account_name: str
    account_number: str
    currency: str
    bank_reference: str
    customer_reference: str | None = None
    trn_type: str | None = None
    value_date: str | None = None
    credit_amount: float | None = None
    debit_amount: float | None = None
    balance: float | None = None
    post_date: str | None = None
    narrative: str
    extraction_confidence: float
    verification_notes: str | None = None


class VerifyBatchResult(BaseModel):
    results: list[VerifiedTransaction]


def _build_prompt(rows: list[dict]) -> str:
    lines = [VERIFY_PROMPT_HEADER, "", "Extracted rows to verify against the attached page image:"]
    for row in rows:
        lines.append(f"- row_id: {row['row_id']}")
        for field in FIELD_NAMES:
            lines.append(f"  {field}: {row.get(field)}")
    return "\n".join(lines)


def _degraded_row(row: dict) -> dict:
    degraded = {field: row.get(field) for field in FIELD_NAMES}
    degraded.update(
        {
            "row_id": row["row_id"],
            "extraction_confidence": 0.0,
            "verification_notes": "verification failed after retries; passed through unverified",
            "source_pdf": row["source_pdf"],
            "page": row["page"],
            "screenshot_path": row["screenshot_path"],
        }
    )
    return degraded


def _verify_batch(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    screenshot_path = rows[0]["screenshot_path"]
    parts: list = []
    if screenshot_path and Path(screenshot_path).exists():
        parts.append(image_part(Path(screenshot_path).read_bytes()))
    else:
        logger.warning(
            "no screenshot available for %s page %s; verifying without page image",
            rows[0].get("source_pdf"),
            rows[0].get("page"),
        )
    parts.append(_build_prompt(rows))

    label = f"verify {rows[0].get('source_pdf')} p{rows[0].get('page')}"
    result = generate_structured(parts=parts, response_schema=VerifyBatchResult, label=label)

    by_id = {item.row_id: item for item in result.results} if result is not None else {}

    output = []
    for row in rows:
        verified = by_id.get(row["row_id"])
        if verified is None:
            merged = _degraded_row(row)
        else:
            merged = verified.model_dump()
            merged["source_pdf"] = row["source_pdf"]
            merged["page"] = row["page"]
            merged["screenshot_path"] = row["screenshot_path"]

        # extract.py flags rows whose page number was out of range and got
        # silently paired with page 1's screenshot as a fallback. Force a
        # low confidence and surface the warning instead of letting this
        # row pass through looking like a normal, fully-verified row --
        # Stage 2 verification just judged it against the wrong page image.
        warning = row.get("extraction_warning")
        if warning:
            merged["extraction_confidence"] = 0.0
            existing_notes = merged.get("verification_notes")
            merged["verification_notes"] = (
                f"{warning} | {existing_notes}" if existing_notes else warning
            )

        output.append(merged)
    return output


def verify_rows(rows: list[dict]) -> list[dict]:
    """Verify one file's extracted rows against their source page images,
    batched by page. Returns the same row shape with corrected field values
    (where Gemini found a discrepancy) plus extraction_confidence."""
    if not rows:
        return []

    batches: dict[tuple[str, int], list[dict]] = defaultdict(list)
    order: list[tuple[str, int]] = []
    for row in rows:
        key = (row["source_pdf"], row["page"])
        if key not in batches:
            order.append(key)
        batches[key].append(row)

    verified_rows: list[dict] = []
    for key in order:
        verified_rows.extend(_verify_batch(batches[key]))
    return verified_rows
