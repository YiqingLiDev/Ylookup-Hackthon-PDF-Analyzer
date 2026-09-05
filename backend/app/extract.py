"""PDF bank statement extraction: raw transaction rows + rendered page screenshots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

RENDER_DPI = 175

# Table header labels (as they appear in the PDF) mapped to our raw field names.
_COLUMN_MAP = {
    "bank reference": "bank_reference",
    "customer reference": "customer_reference",
    "trn type": "trn_type",
    "value date": "value_date",
    "credit amount": "credit_amount",
    "debit amount": "debit_amount",
    "balance": "balance",
    "post date": "post_date",
}

_HEADER_PATTERNS = {
    "account_name": re.compile(r"Account name\s+(.+?)\s+Closing ledger balance"),
    "account_number": re.compile(r"Account number\s+(\S+)\s+From"),
    "currency": re.compile(r"Currency\s+([A-Z]{3})\s+From"),
}


@dataclass
class TransactionRow:
    account_name: str
    account_number: str
    currency: str
    bank_reference: str
    customer_reference: str
    trn_type: str
    value_date: str
    credit_amount: float | None
    debit_amount: float | None
    balance: float | None
    post_date: str
    narrative: str
    source_pdf: str
    page: int
    screenshot_path: str
    row_id: str


def _clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.replace("\n", " ")).strip()


def _parse_amount(value: str | None) -> float | None:
    cleaned = _clean_cell(value)
    if not cleaned:
        return None
    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


def _extract_header(first_page_text: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for field_name, pattern in _HEADER_PATTERNS.items():
        match = pattern.search(first_page_text)
        header[field_name] = match.group(1).strip() if match else ""
    return header


def _rows_from_table(table: list[list[str | None]]) -> list[dict[str, str]]:
    if not table:
        return []

    header_row = [(_clean_cell(cell)).lower() for cell in table[0]]
    index_to_field = {
        idx: _COLUMN_MAP[name] for idx, name in enumerate(header_row) if name in _COLUMN_MAP
    }
    if not index_to_field:
        return []

    rows: list[dict[str, str]] = []
    i = 1
    while i < len(table):
        row = table[i]
        first_cell = _clean_cell(row[0]) if row else ""
        first_cell_lower = first_cell.lower()
        if first_cell_lower == "narrative":
            i += 1
            continue
        if first_cell_lower.startswith("balance as at close") or first_cell_lower.startswith(
            "balance brought forward"
        ):
            i += 1
            continue

        data = {field_name: "" for field_name in _COLUMN_MAP.values()}
        for idx, field_name in index_to_field.items():
            if idx < len(row):
                data[field_name] = _clean_cell(row[idx])

        narrative = ""
        if i + 1 < len(table):
            next_row = table[i + 1]
            if next_row and _clean_cell(next_row[0]).lower() == "narrative":
                narrative = _clean_cell(next_row[1]) if len(next_row) > 1 else ""
                i += 1
        data["narrative"] = narrative
        rows.append(data)
        i += 1

    return rows


def extract_pdf(pdf_path: Path, image_dir: Path) -> list[TransactionRow]:
    """Extract transaction rows and render page screenshots for one PDF."""
    image_dir.mkdir(parents=True, exist_ok=True)
    source_pdf = pdf_path.name
    results: list[TransactionRow] = []

    doc = fitz.open(pdf_path)
    try:
        zoom = RENDER_DPI / 72
        matrix = fitz.Matrix(zoom, zoom)
        page_images: dict[int, str] = {}
        for page_index in range(doc.page_count):
            pix = doc[page_index].get_pixmap(matrix=matrix)
            image_path = image_dir / f"{pdf_path.stem}_p{page_index + 1}.png"
            pix.save(image_path)
            page_images[page_index + 1] = str(image_path)
    finally:
        doc.close()

    with pdfplumber.open(pdf_path) as pdf:
        header = {}
        if pdf.pages:
            header = _extract_header(pdf.pages[0].extract_text() or "")

        row_index = 0
        for page_index, page in enumerate(pdf.pages):
            page_number = page_index + 1
            table = page.extract_table()
            raw_rows = _rows_from_table(table) if table else []

            for raw in raw_rows:
                results.append(
                    TransactionRow(
                        account_name=header.get("account_name", ""),
                        account_number=header.get("account_number", ""),
                        currency=header.get("currency", ""),
                        bank_reference=raw.get("bank_reference", ""),
                        customer_reference=raw.get("customer_reference", ""),
                        trn_type=raw.get("trn_type", ""),
                        value_date=raw.get("value_date", ""),
                        credit_amount=_parse_amount(raw.get("credit_amount")),
                        debit_amount=_parse_amount(raw.get("debit_amount")),
                        balance=_parse_amount(raw.get("balance")),
                        post_date=raw.get("post_date", ""),
                        narrative=raw.get("narrative", ""),
                        source_pdf=source_pdf,
                        page=page_number,
                        screenshot_path=page_images.get(page_number, ""),
                        row_id=f"{source_pdf}:p{page_number}:{row_index}",
                    )
                )
                row_index += 1

    return results


def extract_pdfs(pdf_paths: list[Path], image_dir: Path) -> list[TransactionRow]:
    rows: list[TransactionRow] = []
    for pdf_path in pdf_paths:
        rows.extend(extract_pdf(pdf_path, image_dir))
    return rows
