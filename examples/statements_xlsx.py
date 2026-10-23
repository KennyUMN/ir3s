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
import pymupdf  # noqa: E402

from ir3s.extractor import extract_statements, parse_number  # noqa: E402

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
AMBER = PatternFill("solid", fgColor="FFC000")
TOP = Border(top=Side(style="thin", color=NAVY))
FIRST = 3  # column of the first year


def classify(rows, rules, transitions, start, year, junk, min_figure):
    """Map one report's printed lines onto the standard lines for one year.

    Returns the values by key, the lines no rule matched, and the printed
    line each value came from.
    """
    part, out, unmatched, lines = start, {}, [], {}
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
        lines[rule[0]] = row
        part = transitions.get(rule[0], part)
    return out, unmatched, lines


def read(pdf, reports, years, statements, unit, junk, min_figure):
    """Map every report onto the standard lines.

    Each year's figures come from the newest report that prints it. Every
    other report that prints the same year is mapped too, so the two can be
    compared. Returns (data, sources, lines, others); `others` holds
    (statement, year, report, values, unmatched) for those older reports.
    """
    found = {y: extract_statements(pdf.format(y), [s[1] for s in statements]) for y in reports}
    for y, by_kind in found.items():
        for _, kind, *_ in statements:
            assert by_kind[kind].unit == unit, (y, kind, by_kind[kind].unit)
    data, sources, lines, others = {}, {}, {}, []
    for short, kind, _, rules, transitions, start in statements:
        for year in years:
            having = [r for r in reports if year in found[r][kind].years]
            for report in having:
                values, unmatched, printed = classify(found[report][kind].rows, rules, transitions,
                                                      start, year, junk, min_figure)
                if report == having[0]:
                    assert not unmatched, (short, year, report, unmatched)
                    data[(short, year)], sources[(short, year)] = values, report
                    lines[(short, year)] = printed
                else:
                    others.append((short, year, report, values, unmatched))
    return data, sources, lines, others


def restatements(data, sources, others):
    """Figures an older report prints differently from the one used.

    Only lines both reports print are compared. A line one report leaves out
    may be a split, a merge, or a line no rule matched in the older report;
    a real reclassification still shows in the totals it moves.
    """
    found = []
    for short, year, report, values, _ in others:
        used = data[(short, year)]
        for key, a in used.items():
            b = values.get(key)
            if not key.startswith("_") and b is not None and a != b:
                found.append((short, key, year, a, sources[(short, year)], b, report))
    return found


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


def _plain(v):
    """A cell value: a Decimal like 1.57895577379E+11 is written in that form."""
    if v is None:
        return None
    return int(v) if v == v.to_integral_value() else float(v)


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
                     sections, width, cash_tie=None):
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
            cell = sh.cell(row=row, column=c, value=_plain(v))
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
    if cash_tie and cash_tie[1] in rows_at:
        # A soft check: cash-flow cash can include overdrafts or restricted
        # deposits that the balance sheet shows on other lines.
        bs_key, cf_key = cash_tie
        row += 1
        sh.cell(row=row, column=2, value="Kas dan setara kas di neraca / Cash and cash equivalents in the balance sheet")
        for c, y in enumerate(years, FIRST):
            cell = sh.cell(row=row, column=c, value=_plain(data[("bs", y)].get(bs_key)))
            cell.number_format = NUMBER
            cell.alignment = Alignment(horizontal="right")
        _style_row(sh, row, last, Font(name=FONT, size=10))
        row += 1
        sh.cell(row=row, column=2, value="Cek: kas akhir arus kas - kas neraca (0, atau dijelaskan di Catatan)")
        _style_row(sh, row, last, Font(name=FONT, size=10, bold=True), GREEN)
        for c, y in enumerate(years, FIRST):
            col = get_column_letter(c)
            cell = sh.cell(row=row, column=c, value=f"={col}{rows_at[cf_key]}-{col}{row - 1}")
            cell.number_format = NUMBER
            cell.alignment = Alignment(horizontal="right")
            if data[("cf", y)].get(cf_key) != data[("bs", y)].get(bs_key):
                cell.fill = AMBER
    sh.column_dimensions["A"].width = 5.7
    sh.column_dimensions["B"].width = 72
    for c in range(FIRST, last + 1):
        sh.column_dimensions[get_column_letter(c)].width = width
    sh.row_dimensions[3].height = 40
    sh.freeze_panes = sh.cell(row=7, column=FIRST)


def _ungrounded(pdf, cited):
    """Cited figures whose printed text is not on their page, or reads back differently.

    Each row is (statement, line, year, value, "LK <year>", page, label, raw).
    """
    texts, missing = {}, []
    for item in cited:
        _, _, _, value, report, page, _, raw = item
        path = pdf.format(report.split()[1])
        if (path, page) not in texts:
            with pymupdf.open(path) as doc:
                texts[(path, page)] = doc[page - 1].get_text()
        digits = raw.replace("(", "").replace(")", "").strip()
        if digits not in texts[(path, page)] or parse_number(raw) != Decimal(str(value)):
            missing.append(item)
    return missing


def _table(wb, title, intro, header, rows, widths, number_columns=()):
    """A plain sheet: intro lines, a navy header, then the rows."""
    sh = wb.create_sheet(title)
    sh.sheet_view.showGridLines = False
    for line in intro:
        sh.append([line])
        sh.cell(row=sh.max_row, column=1).font = Font(name=FONT, size=10)
    sh.append([])
    sh.append(header)
    first = sh.max_row
    for cell in sh[first]:
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = BAND
    for values in rows:
        sh.append(values)
        for cell in sh[sh.max_row]:
            cell.font = Font(name=FONT, size=10)
            if cell.column in number_columns:
                cell.number_format = NUMBER
    for col, width in enumerate(widths, 1):
        sh.column_dimensions[get_column_letter(col)].width = width
    sh.freeze_panes = sh.cell(row=first + 1, column=1)
    sh.auto_filter.ref = f"A{first}:{get_column_letter(len(header))}{sh.max_row}"


def build(*, company, ticker, pdf, reports, years, statements, checks, sections, notes, out,
          unit, unit_label, min_figure, junk=None, width=16, cash_tie=None):
    """Read, map, check and write the workbook.

    `cash_tie` is (balance-sheet cash key, cash-flow closing cash key).
    """
    data, sources, lines, others = read(pdf, reports, years, statements, unit, junk, min_figure)
    applied, failures = check(data, years, checks)
    for f in failures:
        print("CHECK FAILED", f)
    titles = {short: title for short, _, title, *_ in statements}
    labels = {(short, key): label for short, _, _, rules, _, _ in statements for key, label, *_ in rules}
    wb = Workbook()
    wb.remove(wb.active)
    for short, _, title, rules, _, _ in statements:
        _statement_sheet(wb, title, short, rules, data, sources, years, company, ticker, unit_label,
                         sections, width, cash_tie if short == "cf" else None)

    restated = restatements(data, sources, others)
    unread = [(titles[short], year, f"LK {report}", label, _plain(value))
              for short, year, report, _, unmatched in others for _, label, value in unmatched]
    _table(
        wb, "Penyajian kembali",
        [f"Angka yang dicetak berbeda oleh dua laporan untuk tahun yang sama ({len(restated)} angka).",
         "Workbook memakai laporan terbaru; kolom 'Laporan lain' adalah laporan yang lebih lama.",
         "Hanya pos yang dicetak di kedua laporan yang dibandingkan; pos yang dipindah atau dipecah terlihat di jumlahnya."]
        + ([f"{len(unread)} baris di laporan lama tidak cocok dengan aturan mana pun dan tidak ikut dibandingkan;",
            "  daftarnya ada di bawah tabel."] if unread else []),
        ["Laporan", "Pos", "Tahun", "Angka dipakai", "Sumber", "Angka di laporan lain", "Laporan lain", "Selisih"],
        [(titles[short], labels[(short, key)], year, _plain(a), f"LK {source}", _plain(b), f"LK {report}",
          _plain((a or 0) - (b or 0)))
         for short, key, year, a, source, b, report in restated],
        (12, 70, 7, 20, 10, 20, 12, 20), number_columns=(4, 6, 8),
    )
    if unread:
        sh = wb["Penyajian kembali"]
        sh.append([])
        sh.append(["Baris laporan lama yang tidak dibandingkan:"])
        for item in unread:
            sh.append(list(item))
        for row in sh.iter_rows(min_row=sh.max_row - len(unread)):
            for cell in row:
                cell.font = Font(name=FONT, size=10)

    cited = [(titles[short], labels[(short, key)], year, _plain(data[(short, year)][key]),
              f"LK {sources[(short, year)]}", row.page, row.label,
              next(c.raw for c in row.cells if c.year == year and not c.interim))
             for short, *_ in statements for year in years
             for key, row in lines[(short, year)].items() if not key.startswith("_")]
    ungrounded = _ungrounded(pdf, cited)
    assert not ungrounded, ungrounded[:5]
    _table(
        wb, "Sumber",
        ["Setiap angka di workbook ini, dengan laporan, halaman PDF dan baris tercetaknya, untuk dicek langsung ke PDF.",
         "'Angka tercetak' adalah teks persis seperti di halaman itu; build mengecek setiap angka ada di halaman tersebut."],
        ["Laporan", "Pos", "Tahun", "Angka", "Sumber", "Halaman PDF", "Baris tercetak", "Angka tercetak"],
        cited, (12, 60, 7, 20, 10, 12, 80, 20), number_columns=(4,),
    )

    sheet = wb.create_sheet("Catatan")
    for line in notes + [
        "Angka dibaca langsung dari teks PDF oleh ir3s (tanpa model bahasa). Setiap baris tercetak sudah",
        "  dipetakan ke satu pos oleh aturan tertulis, dan setiap subtotal dicek sama dengan jumlah pos-posnya:",
        f"  {applied - len(failures)} cek lolos, {len(failures)} gagal.",
        f"Setiap angka ({len(cited)}) dicek tercetak persis di halaman PDF yang disebut di sheet Sumber.",
        f"Sheet Penyajian kembali mencatat {len(restated)} angka yang berbeda antara dua laporan untuk tahun yang sama.",
    ]:
        sheet.append([line])
    for cell in sheet["A"]:
        cell.font = Font(name=FONT, size=10)
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 120
    wb.save(out)
    print("saved", out, "| checks applied:", applied, "failed:", len(failures))
    return applied, failures
