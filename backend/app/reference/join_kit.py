"""Loads the Staging Sheet Join Kit's master-list sheets once, and mirrors
the same substring/lookup logic used by the live Excel formulas in
'Joined Output' (see build.py's adaptation of join_with_masterlists.py) --
but in plain Python.

This mirror exists ONLY to give Stage 3's confidence-scoring prompt a
preview of what the join will resolve to for a row (e.g. its likely
Classification) before the workbook is even built. It is never written to
the output file -- the real workbook always uses the actual, unmodified
Excel formulas, per the Join Guide's validated logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import openpyxl

KIT_PATH = Path(__file__).resolve().parent / "Staging_Sheet_Join_Kit.xlsx"


@dataclass
class MasterData:
    crosswalk: dict[str, str]
    vendors: list[tuple[str, str]]
    related_parties: list[tuple[str, str]]
    investors: list[tuple[str, str]]
    project_codes: list[str]
    deal_position: list[tuple[str, str, str]]  # (legal_entity, deal_name, position)


def _rows(ws, min_row: int = 2):
    return ws.iter_rows(min_row=min_row, values_only=True)


@lru_cache
def load_master_data() -> MasterData:
    wb = openpyxl.load_workbook(KIT_PATH, read_only=True, data_only=True)
    try:
        crosswalk: dict[str, str] = {}
        for account_number, legal_entity, *_ in _rows(wb["Account-Entity Crosswalk"]):
            if account_number and legal_entity:
                crosswalk[str(account_number).strip()] = str(legal_entity).strip()

        vendors = [
            (str(search_key), str(name))
            for _domain, name, search_key in _rows(wb["Vendor Master List"])
            if name and search_key and len(str(search_key)) >= 4
        ]

        related_parties = [
            (str(search_key), str(name))
            for _domain, name, search_key in _rows(wb["Related Party Master"])
            if name and search_key and len(str(search_key)) >= 4
        ]

        investors = [
            (str(search_key), str(name))
            for _entity, name, _vehicle, search_key in _rows(wb["Investor Master List"])
            if name and search_key and len(str(search_key)) >= 4
        ]

        project_codes = [
            str(code) for _domain, code, _new_code in _rows(wb["Project Code Report"]) if code
        ]

        deal_position = [
            (str(row[0]), str(row[1]), str(row[3]))
            for row in _rows(wb["Deal & Position Master List"])
            if row[0] and row[1] and row[3]
        ]

        return MasterData(
            crosswalk=crosswalk,
            vendors=vendors,
            related_parties=related_parties,
            investors=investors,
            project_codes=project_codes,
            deal_position=deal_position,
        )
    finally:
        wb.close()


def _search_first(narrative: str, candidates: list[tuple[str, str]]) -> str:
    narrative_lower = narrative.lower()
    for search_key, name in candidates:
        if search_key.lower() in narrative_lower:
            return name
    return ""


def compute_join_preview(row: dict, master: MasterData | None = None) -> dict:
    """Python mirror of the Joined Output formulas, keyed the same as the
    Excel columns they mirror -- for AI context only, never the final
    output value (see module docstring)."""
    master = master or load_master_data()
    narrative = row.get("narrative") or ""
    narrative_upper = narrative.upper()

    matched_legal_entity = master.crosswalk.get(
        str(row.get("account_number") or "").strip(), "Review - add to crosswalk"
    )

    if "(EQUITY)" in narrative_upper:
        equity_loan = "Equity"
    elif "(LOAN)" in narrative_upper:
        equity_loan = "Loan"
    elif "EQUITY" in narrative_upper:
        equity_loan = "Equity"
    elif "LOAN" in narrative_upper:
        equity_loan = "Loan"
    else:
        equity_loan = ""

    vendor_match = _search_first(narrative, master.vendors)
    related_party_match = _search_first(narrative, master.related_parties)
    investor_match = _search_first(narrative, master.investors)

    if related_party_match:
        matched_sender_beneficiary = related_party_match
        classification = "Related Party"
    elif vendor_match:
        matched_sender_beneficiary = vendor_match
        classification = "Vendor"
    elif investor_match:
        matched_sender_beneficiary = investor_match
        classification = "Investor"
    elif "INTERNAL" in narrative_upper:
        matched_sender_beneficiary = ""
        classification = "Internal"
    elif any(kw in narrative_upper for kw in ("COMMISSION", "CHARGE", "INTEREST")):
        matched_sender_beneficiary = ""
        classification = "Other"
    else:
        matched_sender_beneficiary = ""
        classification = "Review"

    currency = row.get("currency") or ""
    cash_leg_transtype = f"Cash - Disbursed - {currency}"

    if classification == "Internal":
        counterparty_transtype = "Currency Correcting Credit"
    elif classification == "Vendor":
        counterparty_transtype = "Accounts Payable"
    elif classification == "Related Party":
        counterparty_transtype = "Payable - Related Party"
    elif classification == "Other":
        counterparty_transtype = (
            "Income - Bank Interest" if "INTEREST" in narrative_upper else "Expense - Bank Charges"
        )
    else:
        counterparty_transtype = "Review - manual"

    matched_project_code = next(
        (code for code in master.project_codes if code.lower() in narrative.lower()),
        "Review - no match",
    )

    resolved_position = "Review - manual"
    resolved_deal = "Review - manual"
    if matched_project_code != "Review - no match":
        for legal_entity, deal_name, position in master.deal_position:
            if legal_entity == matched_legal_entity and matched_project_code.lower() in position.lower():
                resolved_position = position
                resolved_deal = deal_name
                break

    return {
        "matched_legal_entity": matched_legal_entity,
        "equity_loan": equity_loan,
        "matched_project_code": matched_project_code,
        "matched_sender_beneficiary": matched_sender_beneficiary,
        "related_party_match": related_party_match,
        "classification": classification,
        "cash_leg_transtype": cash_leg_transtype,
        "counterparty_transtype": counterparty_transtype,
        "resolved_position": resolved_position,
        "resolved_deal": resolved_deal,
    }
