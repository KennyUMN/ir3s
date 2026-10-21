# ir3s — build spec

Pipeline that extracts 3-statement financial data from investor-relations PDFs
and populates a 3-statement model template. Numbers are read **deterministically**
from the PDF text layer; an LLM is used only for the fuzzy part (mapping printed
line labels onto a target schema) and never produces a number.

## Why not "send the PDF to the LLM and read the numbers"

The stated problem with LLM extraction is hallucinated digits and mixed-up
columns. We measured the actual source: in the audited BCA financial statements
the figures are right-aligned at fixed coordinates, the first year column's
right edge sits near x=475pt and the second near x=544pt, and the column header
row (`Notes | 2025 | 2024`) is present on every statement page. That makes the
read a geometry problem, not a language problem.

Consequences:
- Numbers come out exact. Verified on the real 2025 report: total assets
  1,586,828,536 = liabilities 1,294,508,286 + syirkah 10,632,695 + equity
  281,687,555. All seven years (2019-2025) balance.
- Token use collapses. The LLM sees ~40 short labels per page, not a 600-page
  report.
- The LLM can still be wrong, but only about *which* line is which. Every
  mapping is checked by an accounting identity, and a failure is fed back for
  a retry.

## Modules

| File | Contents |
|---|---|
| `ir3s/extractor.py` | Page location, the deterministic geometry reader, subtotal detection |
| `ir3s/pdf_slicer.py` | Which pages of a report are worth reading; comparative-year plan |
| `ir3s/schemas.py` | Pydantic models, the model-spec loader, the identity validators |
| `ir3s/llm.py` | Chat-completions client, JSON mode, retries |
| `ir3s/mapping.py` | Printed labels to canonical labels; the retry loop |
| `ir3s/sheet_writer.py` | Non-destructive write into historical columns only |
| `ir3s/pipeline.py` | extract -> map -> validate -> write |
| `ir3s/cli.py` | `ir3s slice / extract / fill / verify` |
| `tests/test_ir3s.py` | pytest over the real BCA PDF |

## Canonical data shape

```python
StatementKind = Literal["balance_sheet", "income_statement", "cash_flow"]

class LineItem(BaseModel):
    label: str
    source_label: str
    values: dict[int, Decimal]
    is_total: bool
    level: int

class Statement(BaseModel):
    kind: StatementKind
    company: str
    unit: str
    years: list[int]
    items: list[LineItem]

class Model(BaseModel):
    company: str
    unit: str
    years: list[int]
    balance_sheet: dict[str, dict[int, Decimal]]
    income_statement: dict[str, dict[int, Decimal]]
    cash_flow: dict[str, dict[int, Decimal]]
```

Decimals, not floats. Money does not round-trip through binary floating point.

## Model spec (YAML) — the target schema

A spec names, for each canonical line: the label, the statement it belongs to,
the section it rolls into, the template row it is written to, and its flags.

```yaml
company: BBCA
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
```

Flags:
- `is_total` — the template computes this line itself, so it is never written.
- `derived` — the PDF does not print this total, so it is the sum of its
  section's leaves (a bank prints no "Total current assets").
- `check_only` — the line is used by the identity checks but is not in the
  template at all (the template's cash flow block is entirely formulas).
- `share` — the line shares a template row with another line and both are
  summed into it (BCA's syirkah deposits have no row of their own).

## Accounting identities (the correctness gate)

Checked on the canonical model, per year, in `schemas.py`:

1. Balance sheet: `total_assets == total_liabilities + total_equity (+ syirkah)`
2. Balance sheet: `total_assets == total_current_assets + total_non_current_assets`
3. Balance sheet: `total_assets == grand_total` (the PDF's own grand total)
4. Equity: `parent_total + non_controlling == total_equity`
5. Income statement: `net_income == pretax + tax` (tax prints as a negative)
6. Income statement: `attributable_to_parent + non_controlling == net_income`
7. Cash flow: `ending_cash == beginning_cash + net_change (+ fx_effect)`
8. Cash flow: `net_change == operating + investing + financing`

On failure the validator returns the offending lines and the numeric gap, which
is what the retry loop sends back to the LLM.

## Template layout, as measured in the user's Google Sheet

`3 Statements` tab, column B holds labels, C onward holds years:
- row 2: `CASS.IJ | 2019 | ... | 2024 | 2025F | ... | 2030F` (the years are
  stored as numbers, so the text form is `2019.0`)
- row 5 repeats the year header for the balance sheet block; row 68 for the
  income statement block; row 91 for the cash flow block
- row 64 `Check......` = `C63-C27` (assets vs liabilities + equity)
- row 145 `Check..........` = `C144-C8` (cash flow ending cash vs balance
  sheet cash)
- forecast cells are formulas; historical cells are mostly literals but a few
  are hand-entered formulas (e.g. `C9 = 3427 + 267015`)

Writer rules:
- Write **historical columns only** (a year header that is a plain year).
- Never write a forecast column, the `Financial Modelling` / `Valuation` /
  `Key Valuation Risk` / `Additional Data` tabs, or a cell holding a computed
  formula. A cell that merely carries the previous column forward (`=G36`) is
  a value the owner may replace, so it is reported and needs `--force`.
- Totals are recomputed by the template's own formulas, so leaves are written.
- After writing, the template's own check rows are recomputed from the written
  numbers by a small formula evaluator, so the result is proved rather than
  assumed.

## Non-goals for v1

- No OCR for scanned PDFs. The pipeline reads the text layer; a scanned report
  needs a prior OCR pass and is rejected with a clear message.
- No segment-revenue or operating-driver extraction. The template's segment
  rows are formula-driven off `Financial Modelling`.
- No Google Sheets API writes. The target is `.xlsx`, which Sheets imports.
- One company per run. Multi-company consolidation is out of scope.
