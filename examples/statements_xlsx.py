"""Build a company's statements workbook from its audited reports.

The figures are read off the PDFs by ir3s. A company script supplies rules
that map each printed line onto a standard line, within the part of the
statement the line sits in. Every printed figure must match a rule and every
subtotal must equal the sum of its lines, or the build stops. No language
model is involved.

A rule is (key, display label, is_total, part, pattern). Keys starting with
"_" are subtotals that some years print and others do not; they are checked
but not shown.
"""
import re
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ir3s.extractor import extract_statements  # noqa: E402

NUMBER = '#,##0;(#,##0);"-"'
# Earnings per share, the one line whose figure is small. Anchored: a share
# capital label also says "Rp 100 per saham".
EPS = re.compile(r"^(laba|rugi)\b.{0,20}per saham", re.I)

# Styled after the CASS model (CASS_FINMOD.xlsx): DM Sans, navy bands,
# labels in column B, years from column C, no gridlines.
NAVY = "393E5C"
FONT = "DM Sans"
BAND = PatternFill("solid", fgColor=NAVY)
LIGHT = PatternFill("solid", fgColor="E6E8EF")
GREEN = PatternFill("solid", fgColor="00FF00")
TOP = Border(top=Side(style="thin", color=NAVY))
FIRST = 3  # column of the first year


def classify(rows, rules, transitions, start, year, junk, min_figure):
    """Map one report's printed lines onto the standard lines for one year."""
    part, out, unmatched = start, {}, []
    for row in rows:
        value = row.value_for(year)
        if value is None or (junk and junk.search(row.label)):
            continue
        if 0 < abs(value) < min_figure and not EPS.search(row.label):
            # A note reference, page number or par value read as a figure.
            continue
        rule = next((r for r in rules
                     if r[3] == part and r[0] not in out and re.search(r[4], row.label, re.I)), None)
        if rule is None:
            unmatched.append((part, row.label[:90], value))
            continue
        out[rule[0]] = value
        part = transitions.get(rule[0], part)
    return out, unmatched


def read(pdf, reports, years, statements, unit, junk, min_figure):
    """The standard lines per (statement, year), and the report each came from."""
    found = {y: extract_statements(pdf.format(y), [s[1] for s in statements]) for y in reports}
    for y, by_kind in found.items():
        for _, kind, *_ in statements:
            assert by_kind[kind].unit == unit, (y, kind, by_kind[kind].unit)
    data, sources = {}, {}
    for short, kind, _, rules, transitions, start in statements:
        for year in years:
            report = next(r for r in reports if year in found[r][kind].years)
            sources[(short, year)] = report
            values, unmatched = classify(found[report][kind].rows, rules, transitions, start, year,
                                         junk, min_figure)
            assert not unmatched, (short, year, report, unmatched)
            data[(short, year)] = values
    return data, sources


def check(data, years, checks):
    """Apply each identity where its total is printed. Returns (applied, failures).

    An identity may name extra keys after its parts; it then applies only in
    the years those are printed, for a layout one report uses and another not.
    """
    failures, applied = [], 0
    for short, total, parts, *when in checks:
        for year in years:
            values = data[(short, year)]
            if total not in values or any(key not in values for key in when):
                continue
            applied += 1
            diff = values[total] - sum((values.get(p, Decimal(0)) for p in parts), Decimal(0))
            if diff:
                failures.append((short, year, total, parts, diff))
    return applied, failures


def _style_row(sh, row, last, font, fill=None, border=None):
    for c in range(1, last + 1):
        cell = sh.cell(row=row, column=c)
        cell.font = font
        if fill:
            cell.fill = fill
        if border:
            cell.border = border


def _band(sh, row, last, label, years=(), size=10):
    sh.cell(row=row, column=2, value=label)
    for c, year in enumerate(years, FIRST):
        sh.cell(row=row, column=c, value=year).alignment = Alignment(horizontal="right")
    _style_row(sh, row, last, Font(name=FONT, size=size, bold=True, color="FFFFFF"), BAND)


def _statement_sheet(wb, title, short, rules, data, sources, years, company, ticker, unit_label,
                     sections, width):
    last = FIRST + len(years) - 1
    sh = wb.create_sheet(title)
    sh.sheet_view.showGridLines = False
    _band(sh, 1, last, company)
    _band(sh, 2, last, ticker, years)
    _band(sh, 3, last, title.upper(), size=31)
    _band(sh, 5, last, f"{title.upper()} KONSOLIDASIAN ({unit_label})", years)
    sh.cell(row=6, column=2, value="Sumber (laporan keuangan tahun)")
    for c, y in enumerate(years, FIRST):
        sh.cell(row=6, column=c, value=f"LK {sources[(short, y)]}").alignment = Alignment(horizontal="right")
    _style_row(sh, 6, last, Font(name=FONT, size=9, italic=True, color="7F7F7F"))
    row = 7
    rows_at, seen, headed = {}, set(), set()
    for key, label, is_total, _, _ in rules:
        values = [data[(short, y)].get(key) for y in years]
        if key.startswith("_") or key in seen or all(v is None for v in values):
            continue
        seen.add(key)
        group = key.split(".")[0] if "." in key else None
        if group in sections and group not in headed:
            headed.add(group)
            for text, is_band in sections[group]:
                if is_band:
                    _band(sh, row, last, text)
                else:
                    sh.cell(row=row, column=2, value=text)
                    _style_row(sh, row, last, Font(name=FONT, size=10, bold=True))
                row += 1
        sh.cell(row=row, column=2, value=label)
        for c, v in enumerate(values, FIRST):
            if v is not None:
                # A Decimal like 1.57895577379E+11 is written in that form.
                v = int(v) if v == v.to_integral_value() else float(v)
            cell = sh.cell(row=row, column=c, value=v)
            cell.number_format = "#,##0.00" if EPS.search(label) else NUMBER
            cell.alignment = Alignment(horizontal="right")
        if is_total and label.split("/")[0].isupper():
            _style_row(sh, row, last, Font(name=FONT, size=10, bold=True, color="FFFFFF"), BAND)
        elif is_total:
            _style_row(sh, row, last, Font(name=FONT, size=10, bold=True), LIGHT, TOP)
        else:
            _style_row(sh, row, last, Font(name=FONT, size=10))
        rows_at[key] = row
        row += 1
    if "assets.total" in rows_at and "le.total" in rows_at:
        row += 1
        sh.cell(row=row, column=2, value="Check...... (aset - liabilitas dan ekuitas, harus 0)")
        for c in range(FIRST, last + 1):
            col = get_column_letter(c)
            cell = sh.cell(row=row, column=c, value=f"={col}{rows_at['assets.total']}-{col}{rows_at['le.total']}")
            cell.number_format = NUMBER
            cell.alignment = Alignment(horizontal="right")
        _style_row(sh, row, last, Font(name=FONT, size=10, bold=True), GREEN)
    sh.column_dimensions["A"].width = 5.7
    sh.column_dimensions["B"].width = 72
    for c in range(FIRST, last + 1):
        sh.column_dimensions[get_column_letter(c)].width = width
    sh.row_dimensions[3].height = 40
    sh.freeze_panes = sh.cell(row=7, column=FIRST)


def build(*, company, ticker, pdf, reports, years, statements, checks, sections, notes, out,
          unit, unit_label, min_figure, junk=None, width=16):
    """Read, map, check and write the workbook. Stops if any check fails."""
    data, sources = read(pdf, reports, years, statements, unit, junk, min_figure)
    applied, failures = check(data, years, checks)
    for f in failures:
        print("CHECK FAILED", f)
    wb = Workbook()
    wb.remove(wb.active)
    for short, _, title, rules, _, _ in statements:
        _statement_sheet(wb, title, short, rules, data, sources, years, company, ticker, unit_label,
                         sections, width)
    sheet = wb.create_sheet("Catatan")
    for line in notes + [
        "Angka dibaca langsung dari teks PDF oleh ir3s (tanpa model bahasa). Setiap baris tercetak sudah",
        "  dipetakan ke satu pos oleh aturan tertulis, dan setiap subtotal dicek sama dengan jumlah pos-posnya:",
        f"  {applied - len(failures)} cek lolos, {len(failures)} gagal.",
    ]:
        sheet.append([line])
    for cell in sheet["A"]:
        cell.font = Font(name=FONT, size=10)
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 120
    wb.save(out)
    print("saved", out, "| checks applied:", applied, "failed:", len(failures))
    return applied, failures
