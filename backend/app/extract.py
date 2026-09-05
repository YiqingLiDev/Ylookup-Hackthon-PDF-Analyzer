"""Stage 1 -- Extract: PDF -> raw 12 fields per transaction row, via Gemini.

PyMuPDF (fitz) is used only to render each page to a PNG screenshot and to
get the page count. All field extraction is done by Gemini with forced
JSON-schema output -- no deterministic table parsing.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf
from pydantic import BaseModel

from app.ai import generate_structured, pdf_part

logger = logging.getLogger(__name__)

RENDER_DPI = 175

EXTRACT_PROMPT = """You are extracting structured data from a bank account statement PDF.

Return the statement header fields and every transaction line in the statement's table.

Header fields (these apply to the whole statement, repeated for every row):
- account_name: the name on the account.
- account_number: the account number as printed.
- currency: the ISO currency code of the account (e.g. EUR, USD, DKK, GBP).

For every transaction line in the table, extract:
- bank_reference: the bank's own reference/transaction ID for this line.
- customer_reference: the customer/payment reference, if present, else null.
- trn_type: the transaction type code/label, if present, else null.
- value_date: the value date as printed (do not reformat), else null.
- credit_amount: the credit amount as a plain number with no currency symbol
  and no thousands separators (e.g. 1234.56, not "1,234.56 EUR"). Null if
  this line has no credit amount.
- debit_amount: the debit amount as a plain number, same formatting rules.
  Null if this line has no debit amount.
- Exactly one of credit_amount / debit_amount should be populated per row;
  the other must be null. Never populate both, never leave both null.
- balance: the running balance after this transaction, as a plain number,
  else null if not printed on this line.
- post_date: the posting date as printed (do not reformat), else null.
- narrative: the full free-text description of the transaction. Statements
  often wrap a single transaction's narrative across multiple lines
  underneath the row -- join all of those lines into ONE string for
  narrative. Do not split one transaction's wrapped narrative into multiple
  rows, and do not merge two distinct transactions into one row.
- page: the 1-indexed page number of the PDF this transaction row appears on.

Extract every transaction row on every page of the document. Do not skip
rows, do not summarize, do not invent rows that aren't present. Read
amounts exactly as printed (after stripping symbols/separators) -- never
estimate or round."""


class ExtractedTransaction(BaseModel):
    bank_reference: str
    customer_reference: str | None = None
    trn_type: str | None = None
    value_date: str | None = None
    credit_amount: float | None = None
    debit_amount: float | None = None
    balance: float | None = None
    post_date: str | None = None
    narrative: str
    page: int


class ExtractedDocument(BaseModel):
    account_name: str
    account_number: str
    currency: str
    transactions: list[ExtractedTransaction]


def _render_pages(pdf_path: Path, image_dir: Path) -> dict[int, str]:
    image_dir.mkdir(parents=True, exist_ok=True)
    page_images: dict[int, str] = {}

    doc = pymupdf.open(pdf_path)
    try:
        zoom = RENDER_DPI / 72
        matrix = pymupdf.Matrix(zoom, zoom)
        for page_index in range(doc.page_count):
            pix = doc[page_index].get_pixmap(matrix=matrix)
            image_path = image_dir / f"{pdf_path.stem}_p{page_index + 1}.png"
            pix.save(image_path)
            page_images[page_index + 1] = str(image_path)
    finally:
        doc.close()

    return page_images


class ExtractionError(Exception):
    """Raised when Gemini extraction fails after retries for a given PDF.

    Callers (jobs.py) catch this per-file so one failed document doesn't
    silently vanish from the batch -- it is surfaced as a failed file on
    the job and as a placeholder row in the output workbook, rather than
    the caller quietly moving on with an empty row list.
    """

    def __init__(self, source_pdf: str):
        self.source_pdf = source_pdf
        super().__init__(f"extraction failed for {source_pdf} after retries")


def extract_pdf(pdf_path: Path, image_dir: Path) -> list[dict]:
    """Extract raw transaction rows + rendered page screenshots for one PDF.

    Returns a list of row dicts (12 raw fields + source_pdf + page +
    screenshot_path + row_id). If extraction still fails after retries,
    raises ExtractionError rather than returning an empty list -- the
    caller is responsible for surfacing the failure instead of it being
    indistinguishable from "this statement genuinely has zero rows".
    """
    source_pdf = pdf_path.name
    page_images = _render_pages(pdf_path, image_dir)
    page_count = len(page_images)

    result = generate_structured(
        parts=[pdf_part(pdf_path.read_bytes()), EXTRACT_PROMPT],
        response_schema=ExtractedDocument,
        label=f"extract {source_pdf}",
    )

    if result is None:
        logger.error("extraction failed for %s after retries", source_pdf)
        raise ExtractionError(source_pdf)

    rows: list[dict] = []
    for index, txn in enumerate(result.transactions):
        page_in_range = 1 <= txn.page <= page_count
        page = txn.page if page_in_range else 1
        row = {
            "account_name": result.account_name,
            "account_number": result.account_number,
            "currency": result.currency,
            "bank_reference": txn.bank_reference,
            "customer_reference": txn.customer_reference,
            "trn_type": txn.trn_type,
            "value_date": txn.value_date,
            "credit_amount": txn.credit_amount,
            "debit_amount": txn.debit_amount,
            "balance": txn.balance,
            "post_date": txn.post_date,
            "narrative": txn.narrative,
            "source_pdf": source_pdf,
            "page": page,
            "screenshot_path": page_images.get(page, ""),
            "row_id": f"{source_pdf}:p{page}:{index}",
        }
        if not page_in_range:
            # Gemini reported a page number outside the document -- rather
            # than silently pairing this row with page 1's screenshot with
            # no visible signal, carry a warning through so verify.py can
            # force a low extraction_confidence and record it in
            # verification_notes. Stage 2 verification would otherwise judge
            # this row's fields against the wrong page image with nothing
            # flagging that the page number itself was suspect.
            row["extraction_warning"] = (
                f"Gemini reported page {txn.page}, which is out of range for "
                f"this {page_count}-page document. This row was paired with "
                "page 1's screenshot as a fallback and should be treated as "
                "low-confidence / manually reviewed."
            )
        rows.append(row)

    return rows
