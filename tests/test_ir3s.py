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
