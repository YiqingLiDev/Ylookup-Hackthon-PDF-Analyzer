# SourceLine - YLookUp Hackthon

<p align="center">
  <a href="https://ylookup-hackthon-pdf-analyzer.onrender.com/"><img alt="Live Demo" src="https://img.shields.io/badge/demo-live-brightgreen?style=for-the-badge"></a>
  <a href="Intro%20Slides.pdf"><img alt="Slides" src="https://img.shields.io/badge/slides-pdf-orange?style=for-the-badge"></a>
  <a href="https://youtu.be/SEwdJaZp7Rk"><img alt="Video" src="https://img.shields.io/badge/video-walkthrough-red?style=for-the-badge"></a>
</p>

<div align="center">

### 🚀 [Live App](https://ylookup-hackthon-pdf-analyzer.onrender.com/) &nbsp;·&nbsp; 📊 [Slides](Intro%20Slides.pdf) &nbsp;·&nbsp; 🎥 [Demo Video](https://youtu.be/SEwdJaZp7Rk)

</div>

<p align="center">
  <a href="https://youtu.be/SEwdJaZp7Rk">
    <img alt="App screenshot" src="Screenshot%202026-09-06%20at%2011.33.13.png" width="800">
  </a>
</p>

---

AI-assisted bank statement matching. 

Upload PDF bank statements; Gemini extracts, verifies, and enriches every transaction; a deterministic Excel formula join against your reference master lists (vendors, legal entities, investors) resolves classification and counterparty. 

Download a workbook where every cell is either a live formula or an AI field carrying its own confidence score and a screenshot of its source page — nothing is a black-box guess an analyst has to just trust.

**Design principle: AI proposes, never decides.** 

Matching/classification is computed by plain Excel formulas against your reference data, not by the LLM. 

The LLM's job is limited to: 
- reading values off the page image, 
- two manual-transcription-only columns no lookup table can fill, and 
- scoring how much a given row needs human review.

## How it works

One uploaded batch of PDFs runs through four stages:

1. **Extract** — Gemini reads each PDF and pulls the 12 raw fields per transaction row (dates, amounts, narrative, references, etc.), plus a full-page PNG screenshot is rendered per page for later reference.
2. **Verify** — Gemini re-checks every extracted row against its actual page screenshot, corrects anything wrong, and assigns an `extraction_confidence`.
3. **Enrich** — once every file's rows are combined into one table, Gemini fills the two columns no reference table can (`Pulled Out Project Code`, `Pulled Out Sender/Beneficiary`) and scores `enrichment_confidence`, informed by documented weak spots in the deterministic join (see "Known limitations" below).
4. **Join & Build** — a pre-built reference workbook
   (`Staging_Sheet_Join_Kit.xlsx`) is loaded, raw rows are written to its `Raw Data` sheet, and `Joined Output` is populated with live Excel formulas (VLOOKUP / INDEX-MATCH / SEARCH against the Account-Entity Crosswalk, Vendor Master List, Related Party Master, Investor Master List, Project Code Report,
   and Deal & Position Master List). Rows are sorted lowest-confidence-first so the rows most in need of review are at the top, each with its source-page screenshot embedded next to it.

Processing runs as a background job per upload batch — the API returns a `job_id` immediately and the frontend polls for per-stage status (`extract` / `verify` / `enrich`) until the workbook is ready to download.

## Want to run it yourself or dig into the code?

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, project layout, the
API reference, and known limitations.
