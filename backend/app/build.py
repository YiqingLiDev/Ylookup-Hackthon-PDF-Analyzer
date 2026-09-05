"""Stage 4 -- Join & Build: writes the final Staging Sheet workbook.

Adapted directly from the validated reference script
`sample_data/join_with_masterlists.py` (kept as reference only, not
imported at runtime per the brief) -- the formula strings, ArrayFormula
usage, dynamic max-row computation, and helper columns (Z/AA/AB) are
carried over unchanged. The differences from that script:

- Loads `Staging_Sheet_Join_Kit.xlsx` fresh from app/reference/ for every
  request instead of reading a pre-existing Combined_Raw_Data.xlsx from an
  Input/ folder.
- Raw rows come from the in-memory pipeline output (post Stage 1-3)
  instead of a file on disk.
- Columns H (Pulled Out Project Code) and J (Pulled Out Sender/
  Beneficiary) are now populated (via Stage 3's AI values, mirrored from
  Raw Data like the other passthrough columns) instead of always blank.
- Extra metadata columns AC-AG are appended after the reference script's
  25+3 columns (extraction_confidence, enrichment_confidence,
  enrichment_notes, embedded screenshot, verification_notes) -- none of
  the existing formula column letters shift.
- Rows are sorted by enrichment_confidence ascending (ties broken by
  extraction_confidence ascending) before being written, so row numbers
  in the formulas correspond to the sorted order.
- The 'Join Guide' sheet (kit documentation, not useful to an analyst) is
  removed before saving.
- Returns a saved workbook path instead of writing to an Output/ folder.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from app.reference.join_kit import KIT_PATH

RAW_SHEET_NAME = "Raw Data (from Extracted file)"
JOINED_SHEET_NAME = "Joined Output"
GUIDE_SHEET_NAME = "Join Guide"

EXPECTED_HEADERS = [
    "Account Name", "Account Number", "Matched Legal Entity", "Currency",
    "Bank reference", "Narrative", "Equity/Loan", "Pulled Out Project Code",
    "Matched Project Code", "Pulled Out Sender/Beneficiary", "Matched Sender/Beneficiary",
    "Related Party Match", "Classification", "Cash Leg Transtype", "Counterparty Transtype",
    "Resolved Position", "Resolved Deal", "Customer reference", "TRN type",
    "Value date", "Credit amount", "Debit amount", "Balance", "Post date", "location",
]

IMAGE_WIDTH_PX = 200
ROW_HEIGHT_PT = 150


def _row_to_raw_values(row: dict) -> list:
    """Maps one pipeline row dict to the 25-column Raw Data shape. Columns
    that are formula-only in Joined Output (Matched Legal Entity,
    Equity/Loan, Matched Project Code, Matched Sender/Beneficiary, Related
    Party Match, Classification, Cash Leg Transtype, Counterparty
    Transtype, Resolved Position, Resolved Deal) are left blank here --
    Joined Output computes them live. location is a display string only
    (the real pointer back to source is the hyperlink + embedded
    screenshot written directly onto Joined Output)."""
    # Text fields fall back to "" rather than None: Joined Output mirrors
    # these via formula reference, and a formula pointing at a genuinely
    # blank cell renders as 0 in Excel, not blank -- "" avoids that.
    return [
        row.get("account_name") or "",      # A Account Name
        row.get("account_number") or "",    # B Account Number
        None,                                 # C Matched Legal Entity (formula)
        row.get("currency") or "",          # D Currency
        row.get("bank_reference") or "",    # E Bank reference
        row.get("narrative") or "",         # F Narrative
        None,                                 # G Equity/Loan (formula)
        row.get("pulled_project_code") or "",        # H Pulled Out Project Code (AI)
        None,                                 # I Matched Project Code (formula)
        row.get("pulled_sender_beneficiary") or "",  # J Pulled Out Sender/Beneficiary (AI)
        None,                                 # K Matched Sender/Beneficiary (formula)
        None,                                 # L Related Party Match (formula)
        None,                                 # M Classification (formula)
        None,                                 # N Cash Leg Transtype (formula)
        None,                                 # O Counterparty Transtype (formula)
        None,                                 # P Resolved Position (formula)
        None,                                 # Q Resolved Deal (formula)
        row.get("customer_reference") or "",  # R
        row.get("trn_type") or "",            # S
        row.get("value_date") or "",          # T
        row.get("credit_amount"),             # U (numeric -- None/blank is normal)
        row.get("debit_amount"),              # V (numeric -- None/blank is normal)
        row.get("balance"),                   # W (numeric -- None/blank is normal)
        row.get("post_date") or "",           # X
        f"{row.get('source_pdf')} p.{row.get('page')}",  # Y location display text
    ]


def _get_max_row(wb, sheet_name: str) -> int:
    if sheet_name in wb.sheetnames:
        return max(2, wb[sheet_name].max_row)
    return 2


def build_workbook(rows: list[dict], output_path: Path) -> Path:
    ordered_rows = sorted(
        rows, key=lambda r: (r.get("enrichment_confidence", 0), r.get("extraction_confidence", 0))
    )

    wb_master = load_workbook(KIT_PATH)

    crosswalk_last_row = _get_max_row(wb_master, "Account-Entity Crosswalk")
    pcr_last_row = _get_max_row(wb_master, "Project Code Report")
    dpml_last_row = _get_max_row(wb_master, "Deal & Position Master List")
    vml_last_row = _get_max_row(wb_master, "Vendor Master List")
    rpm_last_row = _get_max_row(wb_master, "Related Party Master")
    iml_last_row = _get_max_row(wb_master, "Investor Master List")

    # --- 'Raw Data (from Extracted file)' ---
    ws_raw = wb_master[RAW_SHEET_NAME]
    ws_raw.delete_rows(1, ws_raw.max_row)
    for c_idx, header_val in enumerate(EXPECTED_HEADERS, start=1):
        ws_raw.cell(row=1, column=c_idx, value=header_val)
    for r_idx, row in enumerate(ordered_rows, start=2):
        for c_idx, val in enumerate(_row_to_raw_values(row), start=1):
            ws_raw.cell(row=r_idx, column=c_idx, value=val)

    # --- 'Joined Output' ---
    ws_joined = wb_master[JOINED_SHEET_NAME]
    ws_joined.delete_rows(1, ws_joined.max_row)
    for c_idx, header_val in enumerate(EXPECTED_HEADERS, start=1):
        ws_joined.cell(row=1, column=c_idx, value=header_val)
    ws_joined["Z1"] = "Vendor Helper"
    ws_joined["AA1"] = "Related Party Helper"
    ws_joined["AB1"] = "Investor Helper"
    ws_joined["AC1"] = "extraction_confidence"
    ws_joined["AD1"] = "enrichment_confidence"
    ws_joined["AE1"] = "enrichment_notes"
    ws_joined["AF1"] = "screenshot"
    ws_joined["AG1"] = "verification_notes"

    raw_sheet = f"'{RAW_SHEET_NAME}'"

    screenshot_col_idx = 32  # AF
    ws_joined.column_dimensions[get_column_letter(screenshot_col_idx)].width = IMAGE_WIDTH_PX / 7.0

    for idx, row in enumerate(ordered_rows):
        r = idx + 2

        ws_joined[f"A{r}"] = f"={raw_sheet}!A{r}"
        ws_joined[f"B{r}"] = f"={raw_sheet}!B{r}"
        ws_joined[f"C{r}"] = (
            f'=IFERROR(VLOOKUP(B{r},\'Account-Entity Crosswalk\'!$A$2:$B${crosswalk_last_row},2,FALSE),'
            f'"Review - add to crosswalk")'
        )
        ws_joined[f"D{r}"] = f"={raw_sheet}!D{r}"
        ws_joined[f"E{r}"] = f"={raw_sheet}!E{r}"
        ws_joined[f"F{r}"] = f"={raw_sheet}!F{r}"
        ws_joined[f"G{r}"] = (
            f'=IFERROR(IF(ISNUMBER(SEARCH("(EQUITY)",F{r})),"Equity",'
            f'IF(ISNUMBER(SEARCH("(LOAN)",F{r})),"Loan",'
            f'IF(ISNUMBER(SEARCH("EQUITY",F{r})),"Equity",'
            f'IF(ISNUMBER(SEARCH("LOAN",F{r})),"Loan","")))),"")'
        )

        # H, J: now populated (Stage 3 AI values live in Raw Data), mirrored like the other
        # passthroughs -- guarded so a blank source cell reads as "" rather than the 0 Excel
        # normally shows for a formula pointing at an empty cell.
        ws_joined[f"H{r}"] = f'=IF({raw_sheet}!H{r}="","",{raw_sheet}!H{r})'
        ws_joined[f"J{r}"] = f'=IF({raw_sheet}!J{r}="","",{raw_sheet}!J{r})'

        f_I = (
            f'=IFERROR(INDEX(\'Project Code Report\'!$B$2:$B${pcr_last_row},'
            f"MATCH(TRUE,IF(LEN('Project Code Report'!$B$2:$B${pcr_last_row})=0,FALSE,"
            f"ISNUMBER(SEARCH('Project Code Report'!$B$2:$B${pcr_last_row},$F{r}))),0)),"
            f'"Review - no match")'
        )
        ws_joined[f"I{r}"] = ArrayFormula(f"I{r}", f_I)

        ws_joined[f"K{r}"] = f'=IF(AA{r}<>"",AA{r},IF(Z{r}<>"",Z{r},IF(AB{r}<>"",AB{r},"")))'
        ws_joined[f"L{r}"] = f'=IF(AA{r}<>"",AA{r},"")'
        ws_joined[f"M{r}"] = (
            f'=IF(AA{r}<>"","Related Party",IF(Z{r}<>"","Vendor",IF(AB{r}<>"","Investor",'
            f'IF(ISNUMBER(SEARCH("INTERNAL",F{r})),"Internal",'
            f'IF(OR(ISNUMBER(SEARCH("COMMISSION",F{r})),ISNUMBER(SEARCH("CHARGE",F{r})),'
            f'ISNUMBER(SEARCH("INTEREST",F{r}))),"Other","Review")))))'
        )
        # Conditional on which of credit/debit is populated (U/V) rather than
        # unconditionally "Disbursed" -- previously every row, including
        # incoming credits, was hardcoded to "Disbursed", which was silently
        # wrong for every credit row.
        ws_joined[f"N{r}"] = (
            f'=IF(ISNUMBER(U{r}),"Cash - Received - " & D{r},"Cash - Disbursed - " & D{r})'
        )
        ws_joined[f"O{r}"] = (
            f'=IF(M{r}="Internal","Currency Correcting Credit",'
            f'IF(M{r}="Vendor","Accounts Payable",'
            f'IF(M{r}="Related Party","Payable - Related Party",'
            f'IF(M{r}="Other",IF(ISNUMBER(SEARCH("INTEREST",F{r})),"Income - Bank Interest",'
            f'"Expense - Bank Charges"),"Review - manual"))))'
        )

        f_P = (
            f"=IFERROR(INDEX('Deal & Position Master List'!$D$2:$D${dpml_last_row},"
            f"MATCH(1,('Deal & Position Master List'!$A$2:$A${dpml_last_row}=$C{r})*"
            f"(IF(LEN($I{r})=0,FALSE,ISNUMBER(SEARCH($I{r},"
            f"'Deal & Position Master List'!$D$2:$D${dpml_last_row})))),0)),\"Review - manual\")"
        )
        ws_joined[f"P{r}"] = ArrayFormula(f"P{r}", f_P)

        f_Q = (
            f"=IFERROR(INDEX('Deal & Position Master List'!$B$2:$B${dpml_last_row},"
            f"MATCH(1,('Deal & Position Master List'!$A$2:$A${dpml_last_row}=$C{r})*"
            f"(IF(LEN($I{r})=0,FALSE,ISNUMBER(SEARCH($I{r},"
            f"'Deal & Position Master List'!$B$2:$B${dpml_last_row})))),0)),\"Review - manual\")"
        )
        ws_joined[f"Q{r}"] = ArrayFormula(f"Q{r}", f_Q)

        for col in ["R", "S", "T", "U", "V", "W", "X"]:
            ws_joined[f"{col}{r}"] = f"={raw_sheet}!{col}{r}"

        ws_joined[f"Y{r}"] = f"={raw_sheet}!Y{r}"
        screenshot_path = row.get("screenshot_path")
        if screenshot_path and Path(screenshot_path).exists():
            try:
                ws_joined[f"Y{r}"].hyperlink = Path(screenshot_path).resolve().as_uri()
                ws_joined[f"Y{r}"].style = "Hyperlink"
            except ValueError:
                pass  # non-file-backed path; leave Y as plain display text

        f_Z = (
            f"=IFERROR(INDEX('Vendor Master List'!$B$2:$B${vml_last_row},"
            f"MATCH(TRUE,IF(LEN('Vendor Master List'!$C$2:$C${vml_last_row})<4,FALSE,"
            f"ISNUMBER(SEARCH('Vendor Master List'!$C$2:$C${vml_last_row},$F{r}))),0)),\"\")"
        )
        ws_joined[f"Z{r}"] = ArrayFormula(f"Z{r}", f_Z)

        f_AA = (
            f"=IFERROR(INDEX('Related Party Master'!$B$2:$B${rpm_last_row},"
            f"MATCH(TRUE,IF(LEN('Related Party Master'!$C$2:$C${rpm_last_row})<4,FALSE,"
            f"ISNUMBER(SEARCH('Related Party Master'!$C$2:$C${rpm_last_row},$F{r}))),0)),\"\")"
        )
        ws_joined[f"AA{r}"] = ArrayFormula(f"AA{r}", f_AA)

        f_AB = (
            f"=IFERROR(INDEX('Investor Master List'!$B$2:$B${iml_last_row},"
            f"MATCH(TRUE,IF(LEN('Investor Master List'!$D$2:$D${iml_last_row})<4,FALSE,"
            f"ISNUMBER(SEARCH('Investor Master List'!$D$2:$D${iml_last_row},$F{r}))),0)),\"\")"
        )
        ws_joined[f"AB{r}"] = ArrayFormula(f"AB{r}", f_AB)

        # --- pipeline metadata (static values, not formulas) ---
        ws_joined[f"AC{r}"] = row.get("extraction_confidence")
        ws_joined[f"AD{r}"] = row.get("enrichment_confidence")
        ws_joined[f"AE{r}"] = row.get("enrichment_notes")
        # verification_notes: what Stage 2 (verify.py) corrected, if anything,
        # comparing the extracted values against the source page image.
        # Previously computed by Gemini but never written to the workbook --
        # an analyst had no way to see what was silently overwritten during
        # verification.
        ws_joined[f"AG{r}"] = row.get("verification_notes")

        ws_joined.row_dimensions[r].height = ROW_HEIGHT_PT
        if screenshot_path and Path(screenshot_path).exists():
            img = XLImage(screenshot_path)
            aspect_ratio = img.height / img.width
            img.width = IMAGE_WIDTH_PX
            img.height = int(IMAGE_WIDTH_PX * aspect_ratio)
            ws_joined.add_image(img, f"AF{r}")

    wb_master.calculation.fullCalcOnLoad = True

    if GUIDE_SHEET_NAME in wb_master.sheetnames:
        del wb_master[GUIDE_SHEET_NAME]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb_master.save(output_path)
    return output_path
