"""Stage 3 -- AI Enrich: fills the two manual-only columns (Pulled Out
Project Code / Pulled Out Sender-Beneficiary) and scores enrichment
confidence, informed by the specific failure modes the kit's Join Guide
documents for the deterministic join (Stage 4 / build.py).

Runs once over the combined multi-file table. A Python mirror of the
Joined Output formulas (join_kit.compute_join_preview) is computed first,
purely so this stage's confidence scoring can react to what the join will
actually resolve to (Classification, Matched Sender/Beneficiary, etc.)
without waiting on Excel to evaluate anything -- the real output workbook
still uses the live, unmodified Excel formulas built in Stage 4; this
mirror only feeds the AI's context and is discarded afterward.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from app.ai import generate_structured
from app.reference.join_kit import compute_join_preview, load_master_data

logger = logging.getLogger(__name__)

BATCH_SIZE = 8

ENRICH_PROMPT_HEADER = """You are enriching bank statement transaction rows that have
already been run through a deterministic formula join against master-list
reference data (legal entities, vendors, related parties, investors,
project codes). Your job has two parts.

PART 1 -- fill two columns the formula join cannot fill, because no lookup
table backs them (they are manual-transcription-only columns):
- pulled_project_code: read the Narrative and transcribe whatever
  project-related word/phrase appears in it (a project name, code, or
  deal reference mentioned in the text). Null if nothing project-related
  is mentioned.
- pulled_sender_beneficiary: read the Narrative and transcribe the name of
  the counterparty the money is being paid to or received from, in your
  own best-effort reading of the text. Null if you can't tell.

PART 2 -- score enrichment_confidence (0 to 1) for each row, using the
join preview already computed by the formula-mirror logic (given below per
row) PLUS these specific, documented caveats about that join logic. Do not
give a generic confidence guess -- actively check for each of these
patterns and adjust accordingly, and explain what you found in
enrichment_notes:

1. Name/classification matching (Matched Sender/Beneficiary, Related Party
   Match, Classification) uses suffix-stripped substring search and is
   known to get 9/10 right, with a documented miss where a narrative name
   variant doesn't textually match its master-list entry (e.g. an
   abbreviated or reordered form of a related party's name). If the
   Narrative seems to reference a party by a name/spelling that looks like
   it *should* match something but the join preview shows no match (or a
   weak one), lower confidence and say so in enrichment_notes.

2. Classification = "Related Party" is suspect whenever the narrative
   reads like a purchase/acquisition transfer (e.g. contains phrasing like
   "PMT FRM ... TO ... FOR PURCHASE" / "FOR ACQ" / "ACQUISITION"). These
   are often really Investment / Investment Transfer transactions
   mislabeled as Related Party by the formula, which has no way to detect
   this distinction. If you see this pattern, lower confidence and flag it
   explicitly in enrichment_notes.

3. Cash Leg Transtype is a hardcoded/unverified pattern (always
   "Disbursed"), never tested against a genuine "Received" case. If this
   row has a populated credit_amount (money coming IN) and the join
   preview's cash_leg_transtype still says "Disbursed", flag that
   specifically as an unverified caveat in enrichment_notes and lower
   confidence somewhat.

4. Classification errors cascade into Counterparty Transtype (it's
   derived directly from Classification). If you flagged a Classification
   concern under caveat 1 or 2 above, treat Counterparty Transtype as
   carrying the same caveat and reflect that in the confidence score too.

5. Matched Legal Entity is only reliable because this dataset involves a
   very small number of known accounts. If the join preview's
   matched_legal_entity is "Review - add to crosswalk" (meaning this
   row's account number isn't in the crosswalk at all), that is a hard
   signal -- confidence should be low and enrichment_notes should say the
   account needs to be added to the crosswalk.

Only return null for the two manual-pull columns when you genuinely can't
tell -- don't force a guess that isn't supported by the narrative text."""


class EnrichedRow(BaseModel):
    row_id: str
    pulled_project_code: str | None = None
    pulled_sender_beneficiary: str | None = None
    enrichment_confidence: float
    enrichment_notes: str | None = None


class EnrichBatchResult(BaseModel):
    results: list[EnrichedRow]


def _batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _build_prompt(batch: list[dict[str, Any]]) -> str:
    lines = [ENRICH_PROMPT_HEADER, "", "Rows to enrich:"]
    for row in batch:
        preview = row["_join_preview"]
        lines.append(
            f"- row_id: {row['row_id']}\n"
            f"  narrative: {row.get('narrative')}\n"
            f"  currency: {row.get('currency')}\n"
            f"  credit_amount: {row.get('credit_amount')}\n"
            f"  debit_amount: {row.get('debit_amount')}\n"
            f"  account_number: {row.get('account_number')}\n"
            f"  [join preview -- computed by the formula-mirror, not final; use it as context]\n"
            f"  matched_legal_entity: {preview['matched_legal_entity']}\n"
            f"  classification: {preview['classification']}\n"
            f"  matched_sender_beneficiary: {preview['matched_sender_beneficiary']}\n"
            f"  cash_leg_transtype: {preview['cash_leg_transtype']}\n"
            f"  counterparty_transtype: {preview['counterparty_transtype']}"
        )
    return "\n".join(lines)


def _default_result(row_id: str) -> EnrichedRow:
    return EnrichedRow(
        row_id=row_id,
        pulled_project_code=None,
        pulled_sender_beneficiary=None,
        enrichment_confidence=0.0,
        enrichment_notes="enrichment failed after retries",
    )


def _enrich_batch(batch: list[dict], batch_index: int) -> dict[str, EnrichedRow]:
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
    pulled_project_code/pulled_sender_beneficiary/enrichment_confidence/
    enrichment_notes attached."""
    if not rows:
        return []

    master = load_master_data()
    for row in rows:
        row["_join_preview"] = compute_join_preview(row, master)

    matches: dict[str, EnrichedRow] = {}
    for batch_index, batch in enumerate(_batched(rows, BATCH_SIZE)):
        batch_matches = _enrich_batch(batch, batch_index)
        for row in batch:
            matches[row["row_id"]] = batch_matches.get(row["row_id"], _default_result(row["row_id"]))

    output = []
    for row in rows:
        match = matches.get(row["row_id"], _default_result(row["row_id"]))
        enriched = {k: v for k, v in row.items() if k != "_join_preview"}
        enriched["pulled_project_code"] = match.pulled_project_code
        enriched["pulled_sender_beneficiary"] = match.pulled_sender_beneficiary
        enriched["enrichment_confidence"] = match.enrichment_confidence
        enriched["enrichment_notes"] = match.enrichment_notes
        output.append(enriched)
    return output
