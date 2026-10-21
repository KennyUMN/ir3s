# ir3s

Extract multi-year 3-statement financial data from investor-relations PDFs and
fill a 3-statement model template with it.

## The idea

The usual approach asks a language model to read the numbers out of a PDF. That
is where hallucinations and column mix-ups come from, and it costs a fortune on
a 600-page report.

This tool reads the numbers deterministically and asks a language model for
exactly one thing: which printed line is which line in the model.

The measurement that makes this possible: in an audited financial statement the
figures are right-aligned at fixed coordinates, and every statement page
repeats a column header row. Deciding which year a number belongs to is a
geometry problem, not a language problem. On the Bank BCA audited reports the
first year column's right edge sits near x=475pt and the second near x=544pt,
and the header reads `Notes | 2025 | 2024`.

So the numbers never pass through a model. A model can still be wrong about
*which* line is which, and every mapping is checked against the accounting
identities before anything is written.

## What it reads

Indonesian annual reports and audited financial statements, in English or
Indonesian, with the usual conventions: dots or commas for thousands, commas
or dots for decimals, parentheses for negatives, and two comparative years
side by side in each file.

## How it works

    extract  read the statements off a PDF (deterministic)
    map      assign each printed line to a canonical label (the model)
    validate check the accounting identities (Python)
    write    put the validated numbers in the template's historical columns

The four stages are `extractor.py`, `mapping.py`, `schemas.py` and
`sheet_writer.py`, joined by `pipeline.py`.

## Usage

    pip install -e .

    # which pages of a report are worth reading
    ir3s slice report.pdf

    # what the reader makes of a report
    ir3s extract audited-2025.pdf

    # fill a template
    export OPENROUTER_API_KEY=sk-or-...
    ir3s fill audited-2025.pdf specs/bbca.yaml model.xlsx --output filled.xlsx

The model is configured by environment variables: `IR3S_LLM_BASE_URL`,
`IR3S_LLM_API_KEY`, `IR3S_LLM_MODEL`. Any OpenAI-compatible endpoint works.

## The model spec

A spec says which canonical line goes in which template row, and is the only
place company-specific knowledge lives. A new company means a new spec, not a
code change.

    company: PT Bank Central Asia Tbk
    unit: millions of Rupiah
    sheet: 3 Statements
    header_rows:
      balance_sheet: 5
      income_statement: 68
      cash_flow: 91
    check_rows:
      balance: 64
      cash: 145
    sections:
      assets:
        total: assets.total
    statements:
      balance_sheet:
        - label: assets.cash_and_equivalents
          section: assets.current
          template_row: 8
          description: Cash and cash equivalents

Flags: `is_total` for a line the template computes itself, `derived` for a
total the PDF does not print, `check_only` for a line used only by the identity
checks, `share` for a line that shares a template row with another.

## The writer is non-destructive

It writes historical columns only. Forecast columns, the other tabs, and every
cell holding a formula are left alone and reported. The template's own check
rows are recomputed afterwards, so the result is proved rather than assumed.

## Identities checked

- total assets == total liabilities + total equity (+ temporary syirkah funds)
- total assets == the current / non-current split, and the PDF's own grand total
- equity attributable + non-controlling == total equity
- net income == profit before tax + tax
- net change in cash == operating + investing + financing
- ending cash == beginning cash + net change (+ FX effect)

A failure is fed back to the model with the exact discrepancy, so a retry knows
which line is wrong instead of guessing again.

## Status

Working end to end on the Bank BCA audited statements (2019-2025). All
identities pass for every year, and the template's own check row reads zero
after a fill.

Not done: segment revenue and operational drivers, writing to a live Google
Sheet (the target is `.xlsx`, which Sheets can import), and scanned PDFs, which
need an OCR pass first.
