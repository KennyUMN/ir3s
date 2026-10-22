# ir3s — multi-company plan

What has to change in `ir3s` for the pipeline to process a services company
(CASS), a property developer (DMAS) and a bank (SBNR) into the `3 Statements`
template, as well as Bank BCA (BCA), which it handles today.

Every claim below was produced by running the tool against the real audited
financial statements of those four companies. The PDFs are listed at the end.

## 1. Where the tool stands

| Document | pages found by the slicer | rows read | outcome |
|---|---|---|---|
| BCA 2025 | BS 7-8, IS 9-10, CF 13-14 | 47 / 43 / 50 | correct, all identities pass |
| CASS 2023 | BS 14-16, IS 17-18, CF 20 | BS 4, then ExtractionError | broken |
| CASS 2019 | **BS 10-12 only** | 10 | income statement and cash flow silently missing |
| DMAS FY2024 | BS 10-11, IS 12 | 18 / 3 | partly read |
| SBNR 2024 | BS 4-5, IS 6-7, CF 8-9 | 2 | broken |

The page finder is in good shape: it located the right pages in every
document. The reader is where the work is.

## 2. Defects, in the order they should be fixed

### D1. DONE: the figure columns are discovered, not assumed

`extractor.py` used `LABEL_MAX_X = 340.0` and `VALUE_MIN_X = 420.0`, both
tuned on BCA's 595pt page. Three other companies put their figures
elsewhere, and the reader read almost nothing from them.

The columns are now found from the data: every numeric token below the
header is a candidate, the tokens are clustered by right edge, and each band
is paired with the year header it sits under. A band that is not near a
year token is the notes reference column, and is dropped. Committed as
`13272f5`.

Measured, rows read before and after:

| Document | before | after | balances |
|---|---|---|---|
| BCA | 47 / 43 / 50 | 47 / 43 / 50 | yes |
| CASS | 4 (then an error) | 54 / 26 / 21 | yes, both years |
| DMAS | 18 / 3 | 44 / 30 | yes, both years |
| SBNR | 2 (then an error) | 26 / 20 / 37 | yes, all five reports |

All four now satisfy assets = liabilities + equity, read from the PDF with
no model involved. A live fill of the template still leaves the balance
check at zero.

Three things had to move with it, and each was a real defect:

- The notes reference column is excluded by position, under the header's
  notes token, rather than by a constant. It used to leak into the account
  names: `Borrowings 2g,21,37,42,46,49`.
- A statement may print an account name and its figures two and a half
  points apart, on two visual lines. The line tolerance now merges them,
  which is what split Superbank's `JUMLAH ASET` from its figures.
- A model that thinks before answering puts prose in front of its JSON, so
  the object is extracted from wherever it appears.

### D2. DONE, and it was not what it looked like

The figures are not split. Superbank's cash row reads `Kas | 27 | 651) |
978) | Cash`, and the `27` is the note reference (Catatan 27) sitting in the
notes column, not a digit of the figure. The same was true of CASS's `4,29`
and Deltamas's `5,47`.

So the apparent "split numbers" were the notes column, and excluding that
column by position (see D1) resolves them. What remains is the sign hazard
in D5a.

### D3. DONE: a statement that is not found is reported  (commit `2aa1016`)

CASS 2019's income statement and cash flow carry a header row with no
`Notes` token, so `has_column_header` returns False and the slicer reports
only the balance sheet. `extract_statements` returns a balance sheet and
nothing else, with no warning. A caller cannot distinguish "this report has
no cash flow statement" from "this report's cash flow was not found".

**Fix.** `find_statement_pages` should report which statement kinds it
looked for and did not find, and `extract_statements` should raise when a
kind that the document's own table of contents implies is missing. The
document's index page lists the statements; that is the cheap check.

**Also.** CASS 2019's balance sheet has three columns (2019 | 2018 restated |
1 Jan 2018 opening balance) — a third header shape.

### D4. NOT A DEFECT: the gap shown to the LLM is not masked  (checked, no action)

This was reported and then disproved. `schemas.py` renders the discrepancy as
`f"{self.gap:+}"`, and the output looked like `+293****5878`. The asterisks
are a **redaction in the tool that displays command output**, which replaces
long digit runs. Encoding the value so no redaction can apply shows the real
text is `gap +29315878`, and the original format and an explicit sign produce
byte-identical results.

The self-correction retry prompt carries the exact discrepancy. No change
needed.

### D5. DONE: `--force` refuses a computed subtotal  (commit `c15e191`)

`write_values` used to treat every formula the same way. Without `--force`
both a forward link (`=G36`) and a computed subtotal (`=sum(H8:H15)`) were
skipped, but with `--force` both were replaced by a constant. Measured:
writing row 16 with `force=True` turned `=sum(H8:H15)` into `999.0`, which
breaks the template's own check row 64.

`--force` now permits replacing a forward link, which is a value the owner
may replace, and refuses a computed formula outright.

### D5a. DONE: the stray signs in the text layer  (commit `311a216`)

Superbank's 2025 statements print stray marks on their figures. Every
positive figure carries a trailing `)`, and one account name ends in a
hyphen, so its figure reads `-9.199.578)`. The parser read that as a
negative, and another figure read `1.808.594-` as unparseable, so it was
dropped silently.

The rule, measured across the four corpora: a parenthesis pair means
negative; a trailing `)` with no opening `(` is an artifact of the layout;
a trailing `-` is an artifact; a leading `-` is a real sign unless it
comes with that stray trailing `)`, which is a hyphen that leaked out of
the account name. `-9.199.578)` is the only leading-dash token in the
whole corpus that is not a parenthesis pair.

The loans chain now reads correctly: 9,618,259 gross less 418,681
allowance is 9,199,578 net, which is what the PDF prints.

### D6. DONE: the unit is read, and the scale is known  (commit `202de36`)

DMAS prints full rupiah; BCA, CASS and SBNR print millions. "millions of
Rupiah" was only a label string in the spec, and nothing applied a scale
factor, so a DMAS figure would land a factor of 1,000,000 off.

The matcher also looked for "juta rupiah" while Indonesian statements say
"**jutaan** Rupiah", so CASS came back "unspecified" too, and there was no
case for full rupiah at all. `_detect_unit` now handles the Indonesian
forms, and `unit_scale()` gives the factor that converts a printed figure
into the reporting unit.

The factor is not yet applied when writing, because a full-rupiah report
also has to be divided down to the template's millions, and that belongs
with the spec work rather than in the reader.

### D7. The document-selection policy does not do every-other-year  (design)

`plan_documents` chose 7 of 7 BCA reports. The "newest document wins"
restatement policy makes each document the newest source for its own years,
so none is redundant. The brief asked for every-other-year, which halves the
reads but risks missing a restatement.

**Fix.** A decision, not a bug. Either keep newest-wins and read everything,
or prefer the newest report per year pair and accept that a mid-year
restatement of an older year is missed. The two policies disagree and the
code implements the first.

### D8. The target rows are hardcoded in the spec  (maintainability)

The template's rows are literal `template_row: 8` numbers in the spec.
Nothing reads the template's column B to discover which row is which, so a
template change means editing the spec by hand. This is defensible — the
spec is where company-specific knowledge belongs — but it means the tool
cannot be pointed at a different template without a new spec.

**Fix, if wanted.** Read column B, match the printed labels to the template's
labels, and derive the row mapping. The mapping from printed label to
template label is the same problem the LLM already solves, so this is mostly
reusing existing machinery.

### D9. The identity set is hardcoded in code, not in the spec  (flexibility)

`schemas.py` holds a fixed list of `check()` calls against a fixed `LABELS`
dict. A spec can rename the labels but cannot declare a different identity.
Only the section roll-up is spec-driven.

**Fix, if wanted.** Let the spec declare its identities as
`lhs == rhs` expressions over canonical labels. This is what lets a property
spec assert `total_current_assets + total_non_current_assets == total_assets`
while a bank spec asserts a different set.

### D11. DONE: the tax sign convention is the source's, not ours

Measured across the four companies:

| Company | How the tax line prints | The identity |
|---|---|---|
| BCA | `INCOME TAX EXPENSE` = ‑13,697,783 | net = pretax + tax |
| CASS | `Beban pajak penghasilan` = ‑135,919 | net = pretax + tax |
| Superbank | `(Beban) manfaat pajak` = ‑43,589 (a benefit) | net = pretax + tax |
| Deltamas | `BEBAN PAJAK KINI` = **+**39,152,674,220 | net = pretax **−** tax |

The identity check hardcoded BCA's convention, so it would have reported a
78,305,348,440 gap on Deltamas's income statement that was not an error at
all. The check now holds under either sign: the sign belongs to the source,
and what the identity checks is that net income is pretax less the tax charge.
A wrong tax figure is still caught.

### D12. DONE: the group a member belongs to

CASS prints a group name with no figures and its members below it, each with
its own: `Piutang usaha` then `Pihak berelasi` and `Pihak ketiga`. The
members had no group name, so the model saw a line called `Pihak berelasi`
with no way to tell which account it belonged to.

The cause was the notes reference. It is a number, and it sits close enough
to the first figure column to fall inside its band, so it was read as a
figure. That both invented a value and hid the account the reference belongs
to, which is why the group was never recognised. The notes column is now
excluded before the band test, and a member is identified by being printed
indented under its group, which is how a statement shows that a line belongs
to the line above it.

### D13. DONE: a reasoning model needs room to think

A mapping of a whole statement asks the model to decide what every printed
line is. Measured on DeepSeek V4.1 Flash, the model reasons for about
**35,000 tokens** before it writes the JSON:

| Output budget | Result |
|---|---|
| 16,384 | empty reply, `reasoning_tokens: 16384`, `finish_reason: length` |
| 65,536 | the mapping, after `reasoning_tokens: 34,570` |

So a budget that looks generous for the answer is far too small for the
thinking, and the failure looks like a network error rather than a
configuration one. The client's budget is now 65,536, and a reply that runs
out of budget is reported with the budget that was used, so the fix is to
raise it rather than to retry.

This is a cost, not just a setting: a full mapping of three statements is
about 100,000 reasoning tokens. Split the statements across calls, or use a
route that charges for reasoning rather than hiding it in a free tier.

### D20. DONE: the spec says which labels are catch-alls

A label whose name starts with "other" was assumed to be a catch-all, so a
spec that named a real account with "other" in it got marked as one. Every
label in every spec now says whether it is a catch-all, and the prompt names
them, so the model knows where a line with no close match goes.

### D21. DONE: the dead code

Removed what nothing called: the pydantic `LineItem` and `Statement`, the
spec's `other_label` and `total_label`, `ValidationResult.render_skipped`,
`STATEMENT_TITLES`, `Slice.page_count`, `ModelSpec.header_row` and
`ModelSpec.check_row`, and `Statement.value`.

Two of the audit's dead-code findings turned out to be a false positive, and
the audit was wrong on both: `Row.notes` is carried into every row and the
`is_other` flag now decides the catch-alls. `mark_subtotals` and
`Row.is_subtotal` were dead too, and are now live: the prompt marks the
subtotals the reader has already detected, so the model does not have to
spot "Total" in a label that may be printed in either language.

### D22. DONE: a footnote marker made a figure invisible

A figure can carry a footnote marker, which prints as an extra closing
parenthesis: "(261.877))". The marker is not part of the number and
`parse_number` already ignored it, but the numeric test did not, so the
figure was read as text and its year was lost.

Superbank's 2024 net change in cash is exactly such a figure, so that year
was checked against a zero the reader had invented.

### D23. DONE: a label the model did not find is absent, not zero

"The statement does not print this line" and "the statement prints zero" are
different facts, and only the second is a number. An identity that needs the
first has to be skipped, not checked against a zero. Superbank's cash flow
prints no net-change line for 2024, and that year was being checked against
a zero.

The writer now walks the spec's lines rather than the model's, so a row the
statement does not print is written as zero instead of keeping whatever
number filled the template last.

### D24. DONE: a row the statement does not print kept the last company's number

The template's total rows sum every row in the block, so a row the spec
does not name kept whatever number filled the template last, and the block
no longer added up. Superbank's 2024 balance check was 803,498 because of
it.

The writer now empties the rows each statement owns before writing, which
the spec declares in `row_ranges`. A cell holding a formula over other
cells is the template computing something and is left alone. A formula over
bare numbers (=273579+1596) is a value the owner wrote down, not a total,
so it is cleared and overwritten like any other value.

### D25. DONE: a reply holding two JSON objects is read

An upstream that echoes its own envelope, or a model that answers twice,
both put more than one object in the reply. The reader took the first
object it found, which was the envelope, and the request failed. It now
takes the object that looks like the answer, and otherwise the last one.

### D26. DONE: Deltamas's lease liability

Deltamas's non-current liabilities include a lease liability of 531,939,220
for 2023, which the spec had no label for. The block was short by exactly
that much, so the roll-up failed for 2023 only.

### D27. DONE: the template's cash check row is not a company check

Its values are identical for Deltamas, Superbank and CASS, because row 144
is a formula over rows 112/121/141, which are formulas over the balance
sheet. It compares the model's own derived cash with the balance sheet's
cash row, so it does not move with the company. The balance check (row 64)
is the one that does, and it is 0 for every company and every column.

### D28. VERIFIED: every company, one run, against the PDF

- CASS 2022: the asset leaves sum to 1,686,235, the PDF's TOTAL ASSETS is
  1,686,235. 2023: 1,919,403 both ways.
- Deltamas 2024: 8,254,678.433726 million, the PDF's 8,254,678,433,726
  rupiah.
- Superbank 2024: 11,395,094 both ways. Cash 431,617, which is what the
  statement's own cash flow says the closing cash is. Receivables 6,054,713,
  the net figure.
- The merged rows carry their comments: Superbank's rows 8, 24 and 76;
  Deltamas's rows 13, 15, 25, 32 and 36.

### D10. DONE: a merged row says which accounts went into it

The whole point of the tool is putting many accounts into one template row,
so the merge has to be visible in the file and not only in the spec. A row
that took more than one account now carries a comment naming them, and the
write report lists the merged rows. A row that took one account gets no
comment.



`sheet_writer.py` never uses openpyxl's `Comment` API, so nothing records
which PDF accounts were merged into a row. For a mapping that merges many
accounts into one template row, that record is what makes the result
reviewable.

**Fix.** When a row receives more than one canonical label, write a comment
listing them. openpyxl supports this directly.

## 3. What the company differences mean for the spec

The sector assumptions belong in a per-sector spec. The layout assumptions
belong in the code.

**Balance sheet structure.** CASS and DMAS split assets and liabilities into
current and non-current, so the template's rows 8-15 / 19-25 and 30-41 /
46-49 fit them one for one. BCA and SBNR present a single undifferentiated
list: a bank has no "current assets" section in the sense the template means.
The current/non-current split for a bank is a modelling judgement the LLM
would have to make, and it is not in the PDF. This is a genuine sector
difference and belongs in a bank spec, not in the code.

**Accounts with no template row.**

- CASS: "Perolehan konsesi / Acquisition of a concession" (84,324 in 2022) has
  no row; loss from discontinued operations has no row; OCI items have no
  rows. Rows 30/40/46 (bank loans) are nil from 2022 because CASS repaid all
  its debt, and row 36 (advances from customers) became "Liabilitas kontrak"
  (row 35) on PSAK 72 adoption.
- DMAS: `Persediaan` appears in BOTH the current and the non-current section
  (real-estate inventory vs land for development); `Properti investasi`,
  `Investasi dalam ventura bersama`, `Uang muka` and `Liabilitas kontrak`
  need rows.
- SBNR: `Efek-efek` (securities), `Kredit yang diberikan` (loans receivable),
  `Liabilitas segera` (due immediately) and CKPN have no canonical label in
  the BCA spec. The BCA spec also has `assets.inventories`,
  `assets.held_for_sale`, `assets.goodwill` and `liabilities.contract_liabilities`,
  which no bank reports.

**One structural mismatch that is not a spec problem.** CASS prints a single
"Beban usaha / Operating expenses" of 1,650,665 with no COGS split, while the
template models Revenue - Cost of revenues = Gross profit - Operating
expenses = Operating profit. The split (1,610,193 of segment costs, 40,472 of
G&A) is recoverable only from note 24. A tool that maps printed statement
lines to template rows cannot produce rows 70 and 72 from the face of the
statement. Filling the income statement for a services company needs
note-level extraction, which the tool does not do at all: `StatementKind` is a
three-value literal and there is no note-reading path.

**Segment revenue.** CASS's segment revenue comes from note 23, the
*external* revenue table, not note 32, which reports total segment revenue
including inter-segment sales and an elimination column. The template's rows
6-10 match note 23's five segments exactly, and note 23's total equals the
template's row 11.

**Operating drivers are not in the audited statements at all.** The template's
`Financial Modelling` tab expects volumes (handling units, tons, meals,
flights). Those figures appear only in the annual report's operational
statistics, never in the audited financial statements. Populating that tab
needs the annual report, not these PDFs.

## 4. Recommended order of work

1. DONE **D1** discover the figure columns (commit `13272f5`).
2. DONE **D2** the notes column, not split figures.
3. DONE **D5a** the stray signs (commit `311a216`).
4. DONE **D5** `--force` refuses a computed formula (commit `c15e191`).
5. DONE **D6** the unit is read (commit `202de36`).
6. DONE **D3** report a missing statement instead of returning nothing.
7. DONE the spec work: `specs/cass.yaml`, `specs/dmas.yaml`, `specs/sbnr.yaml`,
   each with the canonical labels that company needs. CASS is verified end to
   end: 81 cells written, every identity passes, the balance check reads zero
   in all six historical columns, and the 2023 column matches the PDF's own
   totals exactly (assets 1,919,403, liabilities 886,975, equity 1,032,428).
   Deltamas is verified for the scale: its full-rupiah figures reach the
   template divided into millions and match the PDF to the last digit.
8. Then, if wanted: D7 (policy decision), D8 (dynamic rows), D9
   (spec-declared identities), D10 (audit comments), and the dead code the
   audit found.

Steps 1 to 6 are done, and they are the difference between "works on one
company" and "works on Indonesian statements": all nineteen statement-years
from four companies now balance on their own arithmetic. Steps 7 and 8 are
what make each company a one-file change.

### D14. DONE: the unit a statement is reported in

Deltamas reports in full rupiah and the template's columns are in millions,
so its figures would have landed a factor of a million too large. The spec
now names the unit it targets, and the writer divides down to it. The scale
table lives with the spec, which is what applies it.

### D15. DONE: a derived total is the sum of its leaves

A total the template computes from its own rows cannot be read from the PDF:
the leaves land in the template's rows, and the template recomputes its
totals from them, so a total read from the PDF would not match what the
template shows. A `derived` total is now always the sum of its section's
leaves.

### D16. DONE: what a line with no figures of its own is

A statement prints three kinds of line with no figures, and the reader could
not tell them apart:

    a section heading, "ASET ASSETS", whose next line is at the same indent;
    an account whose members follow below it, "Piutang usaha  3,5,29" then
      "Pihak berelasi  391", next line indented and carrying a note
      reference;
    a label that wrapped around its own figure, "Pendapatan dari kontrak"
      then "dengan pelangan  2.199.217", also indented but with no note.

What follows the line decides which it is, and the note reference tells an
account from a wrapped label. Bold cannot: CASS prints its whole income
statement in a bold face, which is why the reader was reporting only the
second half of the revenue label. A label may also wrap over several lines
before its figure arrives, which is what Deltamas does over five lines for
"Properti investasi".

### D17. DONE: a total the PDF prints is read, not summed

A `derived` total was overwritten with the sum of its section's leaves, even
when the model had already found the total the PDF prints. The balance sheet
got away with it because each of its totals sits in its own sub-section. The
income statement has one flat section, so every derived total summed the
whole statement: CASS's profit before tax came out as its gross profit.

A derived total now keeps the PDF's value when the model finds one, and is
summed only when the PDF does not print it.

### D18. DONE: a discontinued operation is below the tax line

A company that sold a business prints a profit for the year that differs
from profit before tax less tax, because the discontinued result sits below
the tax line. CASS's 2023 figures: 565,962 before tax, (135,919) tax,
430,043 continuing, and 426,991 for the year, the difference being the
(3,052) discontinued loss.

That is now an optional term in the identity, and CASS's spec names it. The
template has no row for it, so it is not written.

### D19. DONE: a column's figures that do not align are one column

A report may carry more than two comparative years: Superbank's 2025
statement has four. A column's figures do not all right-align to the same
place, because a wide number sits further left than a narrow one, so a column
could split into two bands, and the reader kept the band with more figures
and dropped the other.

The bands that belong to the same year are now merged, and the merged band
is centred on where its figures actually are, which is what they are read
against. All four years read, and their totals balance.

The tests now cover one statement per sector, and all of them are the real
statements:

- BCA, the fixture in the repository, a bank with figures at the right.
- CASS, a services company with figures in the middle and a notes column
  between the years, a group whose members carry the group's name, and a
  label that wrapped around its own figure.
- Deltamas, a property developer with figures in the middle, a label that
  wraps over five lines, and a full-rupiah unit.
- Superbank, a digital bank, and its 2025 statement with four year columns.

And the behaviour that decides whether a model is right:

- Every company's balance sheet balances on its own arithmetic.
- A total the PDF prints is read from the PDF, not summed from the leaves.
- A stray dash on a figure is not read as a minus sign.
- A statement whose header carries no notes token is still found.
- A group member carries the group name.
- A label that wrapped is one account.
- A full-rupiah statement is divided down to a millions template.
- A four-year statement is read.
- `--force` refuses a computed subtotal.
- The tax identity holds under either sign convention.
- A test that the reader reads the expected number of rows per company, so a
  silent partial read fails.
- A test that a missing statement is reported.
- A test that a lost minus sign fails an identity and that the gap text
  reaching the model contains the number.
- A test that `--force` refuses a computed formula.
- A test that a filled template's check row reads zero, per company.

## 6. The PDFs used

| Company | File | Source |
|---|---|---|
| BCA | `tests/fixtures/bca_fs_2025.pdf` | bca.co.id IR |
| CASS | `audit/cass/cass_fs_2023.pdf` | casgroup.co.id IR (wp-content uploads) |
| CASS | `audit/cass/cass_fs_2022.pdf`, `cass_fs_2019.pdf` | same |
| DMAS | `audit/deltamas/dmas_fs_fy2024.pdf` | deltamas.id IR |
| SBNR | `audit/superbank/sbnr_audited_1..5.pdf` | superbank.id IR via the S3 bucket |

The CASS IR page and the Superbank IR page are both reachable; Superbank's
returns 403 to plain HTTP but its PDFs are on a plain S3 bucket, so a browser
fetches the links and curl fetches the files.
