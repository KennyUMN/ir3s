"""Tests for the parts that decide whether a number is right.

The PDF fixtures are the real Bank BCA audited financial statements, so a
change that breaks the reader fails here rather than in someone's model.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ir3s.extractor import extract_statements, parse_number
from ir3s.mapping import CanonicalLabel, build_prompt, map_statement
from ir3s.schemas import Model, load_spec, validate_model

FIXTURES = Path(__file__).parent / "fixtures"
PDF = FIXTURES / "bca_fs_2025.pdf"
SPEC = Path(__file__).parents[1] / "specs" / "bbca.yaml"
# Real statements from the other sectors, so the reader is tested on more than
# the one layout it was built on.
AUDIT = Path("/Users/kennyvws/.hermes/cache/scratch/audit")


@pytest.mark.skipif(not PDF.exists(), reason="PDF fixture not present")
def test_balance_sheet_reads_exact_figures():
    """The figures come from the PDF, not from a model, so they are exact."""
    statements = extract_statements(str(PDF))
    balance = statements["balance_sheet"]
    assets = balance.row_for("TOTAL ASSETS")
    liabilities = balance.row_for("TOTAL LIABILITIES")
    equity = balance.row_for("TOTAL EQUITY")
    assert assets is not None and liabilities is not None and equity is not None
    assert assets.value_for(2025) == Decimal(1586828536)
    assert liabilities.value_for(2025) == Decimal(1294508286)
    assert equity.value_for(2025) == Decimal(281687555)


@pytest.mark.skipif(not PDF.exists(), reason="PDF fixture not present")
def test_pdf_balance_sheet_identity_holds():
    """Total assets equals liabilities plus syirkah plus equity, per year."""
    balance = extract_statements(str(PDF))["balance_sheet"]
    assets = balance.row_for("TOTAL ASSETS")
    liabilities = balance.row_for("TOTAL LIABILITIES")
    equity = balance.row_for("TOTAL EQUITY")
    syirkah = balance.row_for("TEMPORARY SYIRKAH DEPOSITS")
    for year in balance.years:
        total = assets.value_for(year)
        assert total == (
            liabilities.value_for(year)
            + equity.value_for(year)
            + (syirkah.value_for(year) if syirkah else Decimal(0))
        )


@pytest.mark.skipif(not PDF.exists(), reason="PDF fixture not present")
def test_income_statement_identity_holds():
    """Net income equals profit before tax plus the (negative) tax."""
    income = extract_statements(str(PDF))["income_statement"]
    net = income.row_for("NET INCOME")
    pretax = income.row_for("INCOME BEFORE TAX")
    tax = income.row_for("INCOME TAX EXPENSE")
    for year in income.years:
        assert net.value_for(year) == pretax.value_for(year) + tax.value_for(year)


@pytest.mark.parametrize(
    "token,expected",
    [
        ("25,305,031", Decimal("25305031")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("(12,841,842)", Decimal("-12841842")),
        ("-", Decimal(0)),
        ("1,000", Decimal("1000")),
        ("4,268,903", Decimal("4268903")),
    ],
)
def test_number_formats(token, expected):
    """Both conventions, negatives in parentheses, and a bare dash for nil."""
    assert parse_number(token) == expected


def _synthetic_bilingual_page(path: Path) -> None:
    """A page shaped like a bilingual Indonesian statement.

    Indonesian label on the left, the two year figures in the middle with a
    notes column between them, English label on the right. The figures sit
    left of the BCA-tuned VALUE_MIN_X, and the notes column makes the number
    of numeric columns differ from the number of years.
    """
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)

    def put(x: float, y: float, text: str, size: int = 9, bold: bool = False) -> None:
        page.insert_text((x, y), text, fontsize=size,
                          fontname="hebo" if bold else "helv")

    put(60, 60, "LAPORAN POSISI KEUANGAN", 12, True)
    put(60, 90, "31 Desember 2023 dan 2022")
    put(220, 110, "2023", 9, True)
    put(290, 110, "Notes", 9, True)
    put(360, 110, "2022", 9, True)
    for y in (140, 160):
        put(60, y, "Kas dan setara kas" if y == 140 else "Jumlah aset", 9, y == 160)
        put(240, y, "453.153")
        put(300, y, "4")
        put(370, y, "351.786")
        put(440, y, "Cash and cash equivalents")
    put(60, 210, "Catatan atas laporan keuangan")
    document.save(path)
    document.close()


def test_reads_a_statement_from_each_sector_and_they_balance():
    """One real statement per sector, each balancing on its own arithmetic.

    The reader was tuned on one bank, and the only fixture was that bank. A
    services company, a property developer and another bank all put their
    figures somewhere else on the page, and all of them balance.
    """
    from ir3s.extractor import extract_statements

    cases = [
        # company, pdf, assets label, liabilities label, equity label, extra label
        ("BCA", Path("/Users/kennyvws/projects/ir3s/tests/fixtures/bca_fs_2025.pdf"),
         "TOTAL ASSETS", "TOTAL LIABILITIES", "TOTAL EQUITY",
         "TEMPORARY SYIRKAH DEPOSITS"),
        ("CASS", AUDIT / "cass" / "cass_fs_2023.pdf",
         "TOTAL ASET TOTAL ASSETS", "TOTAL LIABILITAS TOTAL LIABILITIES",
         "TOTAL EKUITAS TOTAL EQUITY", None),
        ("DMAS", AUDIT / "deltamas" / "dmas_fs_fy2024.pdf",
         "JUMLAH ASET TOTAL ASSETS", "JUMLAH LIABILITAS TOTAL LIABILITIES",
         "JUMLAH EKUITAS TOTAL EQUITY", None),
        ("SBNR", AUDIT / "superbank" / "sbnr_audited_3.pdf",
         "JUMLAH ASET TOTAL ASSETS", "JUMLAH LIABILITAS TOTAL LIABILITIES",
         "JUMLAH EKUITAS TOTAL EQUITY", None),
    ]
    for name, pdf, assets, liabilities, equity, extra in cases:
        if not pdf.exists():
            pytest.skip(f"{name} fixture not present")
        balance = extract_statements(str(pdf))["balance_sheet"]
        assert balance.rows, f"{name}: no rows read"

        def find(label: str | None, year: int):
            if label is None:
                return None
            for row in balance.rows:
                if row.label.strip().upper() == label.upper():
                    return row.value_for(year)
            return None

        for year in balance.years:
            total_assets = find(assets, year)
            total_liabilities = find(liabilities, year)
            total_equity = find(equity, year)
            assert None not in (total_assets, total_liabilities, total_equity), \
                f"{name} {year}: a total was not read"
            # A bank may report temporary shariah funds between liabilities and
            # equity, which are neither of the two.
            between = find(extra, year) or Decimal(0)
            assert total_assets == total_liabilities + total_equity + between, \
                f"{name} {year}: assets != liabilities + equity"


def test_finds_a_statement_whose_header_has_no_notes_token():
    """A statement whose column header carries only the years.

    CASS's 2019 statements put the comparative year on a line of its own and
    spread the header over six lines. The reader used to find the report's
    date line, which names the same year twice, and to read nothing at all.
    """
    from ir3s.extractor import extract_statements

    pdf = AUDIT / "cass" / "cass_fs_2019.pdf"
    if not pdf.exists():
        pytest.skip("CASS fixture not present")
    statements = extract_statements(str(pdf))
    for kind in ("balance_sheet", "income_statement", "cash_flow"):
        assert kind in statements, f"{kind} was not found"
        assert statements[kind].rows, f"{kind} read no rows"
    balance = statements["balance_sheet"]
    for year in balance.years:
        total = balance.row_for("TOTAL ASET TOTAL ASSETS")
        if total is not None:
            assert total.value_for(year) is not None


def test_a_group_member_carries_the_group_name():
    """A statement may print a group name and its members on separate lines.

    CASS prints "Piutang usaha" with no figures and then "Pihak berelasi" and
    "Pihak ketiga" below it, each with its own. The members must carry the
    group's name, or a model sees an unrelated line called "Pihak berelasi".
    """
    from ir3s.extractor import extract_statements

    pdf = AUDIT / "cass" / "cass_fs_2023.pdf"
    if not pdf.exists():
        pytest.skip("CASS fixture not present")
    balance = extract_statements(str(pdf))["balance_sheet"]
    labels = [row.label for row in balance.rows]
    members = [label for label in labels if "Pihak berelasi" in label]
    assert members, "the related-party line was not read"
    for label in members:
        # A member names the group it belongs to, which is a receivable or a
        # payable.
        assert "Piutang" in label or "Utang" in label, \
            f"the member lost its group: {label!r}"


def test_a_note_reference_is_not_read_as_a_figure():
    """The notes column holds numbers that sit inside a figure band.

    Reading one as a figure both invents a value and hides the account it
    belongs to, which then never becomes a group heading.
    """
    from ir3s.extractor import extract_statements

    pdf = AUDIT / "cass" / "cass_fs_2023.pdf"
    if not pdf.exists():
        pytest.skip("CASS fixture not present")
    balance = extract_statements(str(pdf))["balance_sheet"]
    for row in balance.rows:
        # A notes reference looks like "3,5,29" or "10b".
        assert not row.label.strip() in {"3,5,29", "3,6,29", "3,5,29,42,46,49"}, \
            f"a notes reference became an account: {row.label!r}"


def test_a_label_that_wrapped_around_its_figure_is_one_account():
    """A statement may print an account name split by its own figure.

    CASS prints "Pendapatan dari kontrak" on one line and "dengan pelangan"
    with the figure on the next. The two halves are one account, and the
    reader used to report only the second half.
    """
    from ir3s.extractor import extract_statements

    pdf = AUDIT / "cass" / "cass_fs_2023.pdf"
    if not pdf.exists():
        pytest.skip("CASS fixture not present")
    income = extract_statements(str(pdf))["income_statement"]
    revenue = next((row for row in income.rows if row.value_for(2023) == 2199217), None)
    assert revenue is not None, "the revenue line was not read"
    assert "Pendapatan dari kontrak" in revenue.label, revenue.label
    assert "dengan pelangan" in revenue.label, revenue.label


def test_the_cass_spec_covers_the_accounts_the_reader_produces():
    """A spec must name accounts the reader can actually produce.

    A spec that names an account the statement does not print would leave a
    row empty without saying so.
    """
    from ir3s.extractor import extract_statements
    from ir3s.schemas import load_spec

    spec_path = Path(__file__).parents[1] / "specs" / "cass.yaml"
    pdf = AUDIT / "cass" / "cass_fs_2023.pdf"
    if not spec_path.exists() or not pdf.exists():
        pytest.skip("CASS spec or fixture not present")

    spec = load_spec(spec_path)
    statements = extract_statements(str(pdf))
    for kind in ("balance_sheet", "income_statement"):
        printed = " ".join(row.label for row in statements[kind].rows).lower()
        for line in spec.lines(kind):
            if line.is_total and not line.share:
                continue
            # The first word of the Indonesian name must appear in the
            # statement, or the row will never be filled.
            words = line.description.split("/")[0].strip().split()
            if not words:
                continue
            assert words[0].lower() in printed, \
                f"{kind}: {line.label} names {words[0]!r}, which the statement does not print"


def test_a_label_that_wraps_over_several_lines_is_one_account():
    """A label can run over several lines before its figure arrives.

    Deltamas prints "Properti investasi - setelah dikurangi akumulasi
    penyusutan ... Rp 29.437.573.213 pada tanggal ... " over five lines, with
    the figure on the sixth.
    """
    from ir3s.extractor import extract_statements

    pdf = AUDIT / "deltamas" / "dmas_fs_fy2024.pdf"
    if not pdf.exists():
        pytest.skip("Deltamas fixture not present")
    balance = extract_statements(str(pdf))["balance_sheet"]
    investment = next((row for row in balance.rows if row.value_for(2024) == 190016333904), None)
    assert investment is not None, "the investment property line was not read"
    assert investment.label.startswith("Properti investasi"), investment.label


def test_a_full_rupiah_statement_is_divided_down_to_a_millions_template():
    """A statement may be reported in a different unit from the template.

    Deltamas reports in full rupiah and the template's columns are in
    millions, so its figures have to be divided by a million before they are
    written, or every number in the model is a million times too large.
    """
    spec_path = Path(__file__).parents[1] / "specs" / "dmas.yaml"
    template = Path("/Users/kennyvws/.hermes/cache/scratch/fsm/template.xlsx")
    if not spec_path.exists() or not template.exists():
        pytest.skip("Deltamas spec or template not present")

    spec = load_spec(spec_path)
    assert spec.scale_to_target("Rupiah") == Decimal("0.000001")
    # A report already in the template's unit is left alone.
    assert spec.scale_to_target("millions of Rupiah") == Decimal(1)


def test_a_statement_with_four_year_columns_is_read():
    """A report may carry more than two comparative years.

    Superbank's 2025 report has four: 2025, 2024, 2023 and 2022. A column's
    figures do not all right-align to the same place, so a column can split
    into two bands, and the reader used to keep only the larger one and lose
    the rest.
    """
    from ir3s.extractor import extract_statements

    pdf = AUDIT / "superbank" / "sbnr_audited_2.pdf"
    if not pdf.exists():
        pytest.skip("Superbank fixture not present")
    balance = extract_statements(str(pdf))["balance_sheet"]
    assert balance.years == [2022, 2023, 2024, 2025], balance.years
    for year in balance.years:
        total = next(
            (row.value_for(year) for row in balance.rows
             if "TOTAL ASSETS" in row.label.upper()),
            None,
        )
        assert total is not None, f"{year}: total assets was not read"


def test_reader_handles_a_figure_layout_with_a_notes_column():
    """A statement whose figure columns outnumber its year columns.

    The header row of a bilingual Indonesian statement carries two years and
    a notes column, so the number of numeric columns below it is not the
    number of years. The reader used to raise TypeError here, on every
    Indonesian statement except the one it was tuned on.

    It now finds the figure columns from the data, so it reads the statement.
    """
    from ir3s.extractor import extract_statements

    pdf = Path(__file__).parent / "_synthetic.pdf"
    _synthetic_bilingual_page(pdf)
    try:
        statements = extract_statements(str(pdf))
        balance = statements["balance_sheet"]
        assert balance.years == [2022, 2023]
        labels = " ".join(row.label for row in balance.rows)
        # The figures sit in the middle of the page, in the middle of the row,
        # and the notes column holds a number too. None of that may leak into
        # the account name.
        assert "Kas" in labels
        assert "4,29" not in labels, "the notes reference became part of a label"
        cash = next(row for row in balance.rows if "Kas" in row.label)
        assert cash.value_for(2023) == Decimal("453153")
        assert cash.value_for(2022) == Decimal("351786")
    finally:
        pdf.unlink(missing_ok=True)


def test_unit_is_read_off_the_statement_header():
    """The reporting unit decides the scale of every figure.

    Indonesian statements say "jutaan Rupiah" (millions) or "Rupiah" alone
    (full rupiah). The old matcher looked for "juta rupiah" and missed
    "jutaan Rupiah" by one letter, and had no case for full rupiah at all.
    """
    from ir3s.extractor import _detect_unit, unit_scale

    assert _detect_unit("(Expressed in millions of Rupiah, unless otherwise stated)") \
        == "millions of Rupiah"
    assert _detect_unit("(Disajikan dalam jutaan Rupiah, kecuali dinyatakan lain)") \
        == "millions of Rupiah"
    assert _detect_unit("(Disajikan dalam Rupiah, kecuali dinyatakan lain)") == "Rupiah"
    assert _detect_unit("(Angka-angka Disajikan dalam Rupiah, kecuali Dinyatakan Lain)") \
        == "Rupiah"
    assert _detect_unit("no unit here") == "unspecified"

    assert unit_scale("millions of Rupiah") == Decimal(1_000_000)
    assert unit_scale("Rupiah") == Decimal(1)


def test_tax_identity_holds_under_either_sign_convention():
    """A company may print its tax as a negative or as a positive expense.

    BCA, CASS and Superbank print the tax charge negative, so net income is
    pretax plus tax. Deltamas prints it positive, so net income is pretax
    less tax. The sign belongs to the source, so the identity holds either
    way, and a wrong figure is still caught.
    """
    from ir3s.schemas import Model, validate_model

    def model_with(tax: Decimal) -> Model:
        return Model(
            company="X",
            unit="millions",
            years=[2024],
            income_statement={
                "income.pretax": {2024: Decimal(100)},
                "income.tax": {2024: tax},
                "income.net_income": {2024: Decimal(70)},
            },
        )

    # Tax printed negative: net = pretax + tax.
    assert validate_model(model_with(Decimal(-30))).ok
    # Tax printed positive: net = pretax - tax.
    assert validate_model(model_with(Decimal(30))).ok
    # A tax figure that is simply wrong is still caught.
    assert not validate_model(model_with(Decimal(-25))).ok
    assert not validate_model(model_with(Decimal(25))).ok


def test_a_row_the_statement_does_not_print_is_emptied():
    """A row the statement has no account for must not keep an old number.

    The template's total rows sum every row in the block, so a row that kept
    the previous company's number would make the block not add up.
    """
    import shutil

    import openpyxl

    from ir3s.sheet_writer import open_template, write_values

    source = Path("/Users/kennyvws/.hermes/cache/scratch/fsm/template.xlsx")
    if not source.exists():
        pytest.skip("template not present")
    copy = Path(__file__).parent / "_clear_test.xlsx"
    shutil.copyfile(source, copy)
    try:
        template = open_template(copy)
        sheet = openpyxl.load_workbook(copy)["3 Statements"]
        stale = sheet.cell(row=10, column=7).value
        assert stale is not None, "the fixture row should hold a value"
        write_values(
            template, "3 Statements", 5,
            {36: {2023: Decimal(100)}},
            force=True, label_for_row={36: "row 36"},
            clear_rows=((6, 67),),
        )
        template.workbook.save(copy)
        sheet = openpyxl.load_workbook(copy)["3 Statements"]
        assert sheet.cell(row=10, column=7).value is None, "the stale number stayed"
        assert sheet.cell(row=36, column=7).value == 100
        # The template's own totals are formulas and are left alone.
        assert str(sheet.cell(row=27, column=7).value).startswith("=")
    finally:
        copy.unlink(missing_ok=True)


def test_a_row_that_took_several_accounts_says_so():
    """A merged row records which accounts went into it.

    The whole point of the tool is putting many accounts into one template
    row, so the merge has to be visible in the file, not only in the spec.
    """
    import shutil

    import openpyxl

    from ir3s.sheet_writer import open_template, write_values

    source = Path("/Users/kennyvws/.hermes/cache/scratch/fsm/template.xlsx")
    if not source.exists():
        pytest.skip("template not present")
    copy = Path(__file__).parent / "_comment_test.xlsx"
    shutil.copyfile(source, copy)
    try:
        template = open_template(copy)
        report = write_values(
            template, "3 Statements", 5,
            {36: {2023: Decimal(100)}, 9: {2023: Decimal(200)}},
            force=True,
            label_for_row={36: "row 36", 9: "row 9"},
            merged_for_row={
                36: ["assets.deposits_from_customers", "syirkah.total"],
                9: ["assets.receivables"],
            },
        )
        template.workbook.save(copy)
        assert report.merged == {36: ["assets.deposits_from_customers", "syirkah.total"]}
        sheet = openpyxl.load_workbook(copy)["3 Statements"]
        merged_cell = sheet.cell(row=36, column=7)
        assert merged_cell.comment is not None
        assert "syirkah.total" in merged_cell.comment.text
        # A row that took one account gets no comment.
        assert sheet.cell(row=9, column=7).comment is None
    finally:
        copy.unlink(missing_ok=True)


def test_force_does_not_replace_a_computed_formula():
    """--force may replace a forward link, never a computed total.

    Replacing =sum(H8:H15) with a constant would break the template's own
    check rows, which read that total.
    """
    import shutil

    from ir3s.sheet_writer import open_template, write_values

    source = Path("/Users/kennyvws/.hermes/cache/scratch/fsm/template.xlsx")
    if not source.exists():
        pytest.skip("template not present")
    copy = Path(__file__).parent / "_force_test.xlsx"
    shutil.copyfile(source, copy)
    try:
        template = open_template(copy)
        # Row 16 is "Total Current Assets" = =sum(H8:H15): a computed total.
        report = write_values(template, "3 Statements", 5, {16: {2024: Decimal(999)}},
                              force=True, label_for_row={16: "Total Current Assets"})
        assert not report.written, "a computed total was overwritten"
        assert any("holds a formula" in note for note in report.skipped)
        assert template.sheet("3 Statements").cell(row=16, column=8).value == "=sum(H8:H15)"
    finally:
        copy.unlink(missing_ok=True)


def test_a_stray_dash_is_not_a_minus_sign():
    """A statement may print stray marks on a figure.

    Across the four corpora every genuine negative is written "(123)". A
    leading dash with no opening parenthesis is a hyphen that leaked out of
    the account name, and a trailing one is an artifact of the layout.
    """
    assert parse_number("(9.199.578)") == Decimal("-9199578")
    assert parse_number("-9.199.578)") == Decimal("9199578")
    assert parse_number("9.199.578)") == Decimal("9199578")
    assert parse_number("1.808.594-") == Decimal("1808594")
    assert parse_number("-1.234") == Decimal("-1234")


def test_number_formats_do_not_confuse_a_thousands_group_with_a_decimal():
    """'1,234' is a thousands group; '1,23' is a decimal."""
    assert parse_number("1,234") == Decimal("1234")
    assert parse_number("1,23") == Decimal("1.23")


def test_validator_reports_the_gap():
    """A broken balance sheet is reported, not swallowed."""
    model = Model(
        company="X",
        unit="millions",
        years=[2024],
        balance_sheet={
            "assets.total": {2024: Decimal(100)},
            "assets.total_current": {2024: Decimal(60)},
            "assets.total_non_current": {2024: Decimal(40)},
            "liabilities.total": {2024: Decimal(70)},
            "equity.total": {2024: Decimal(20)},
        },
    )
    result = validate_model(model)
    assert not result.ok
    assert any(v.gap == Decimal(10) for v in result.violations)


def test_validator_passes_a_balanced_model():
    """The same model with matching figures passes."""
    model = Model(
        company="X",
        unit="millions",
        years=[2024],
        balance_sheet={
            "assets.total": {2024: Decimal(100)},
            "assets.total_current": {2024: Decimal(60)},
            "assets.total_non_current": {2024: Decimal(40)},
            "liabilities.total": {2024: Decimal(70)},
            "equity.total": {2024: Decimal(30)},
        },
    )
    assert validate_model(model).ok


def test_catch_all_buckets_are_detected_and_offered_to_the_model():
    """A label named other_* is a catch-all, and the model must be offered it.

    The mapper sends unmatched lines to a catch-all, so a bucket that is not
    detected is a bucket the model can never fill.
    """
    spec = load_spec(SPEC)
    labels = [CanonicalLabel.from_spec(item) for item in spec.lines("balance_sheet")]
    others = [c.label for c in labels if c.is_other]
    assert others, "the spec has no catch-all bucket"

    prompt = build_prompt([], labels, [2024])
    for label in others:
        assert label in prompt, f"{label} is not offered to the model"


def test_mapper_uses_the_extracted_numbers_not_the_models():
    """The LLM's reply carries indices only; the values come from the rows."""

    class Row:
        def __init__(self, label, value):
            self.label = label
            self.section = "ASSETS"
            self.is_subtotal = False
            self._value = value

        def value_for(self, year):
            return self._value

    rows = [Row("Cash and cash equivalents", Decimal(100)), Row("Total assets", Decimal(250))]
    labels = [
        type("L", (), {"label": "assets.cash_and_equivalents", "section": "assets.current",
                       "is_total": False, "description": "", "is_other": False, "derived": False})(),
        type("L", (), {"label": "assets.total", "section": "assets", "is_total": True,
                       "description": "", "is_other": False, "derived": False})(),
    ]
    # The reply claims cash is 999. The mapper must ignore that.
    reply = {"mapping": {"assets.cash_and_equivalents": [0], "assets.total": [1]}}
    mapped = map_statement(rows, labels, [2024], ask=lambda prompt: reply)
    assert mapped["assets.cash_and_equivalents"][2024] == Decimal(100)
    assert mapped["assets.total"][2024] == Decimal(250)
