"""Canonical data shapes, the model-spec loader, and the accounting-identity gate.

Numbers are Decimal end to end. The validator never raises on a missing label:
an identity that cannot be evaluated is reported in ``ValidationResult.skipped``.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "StatementKind",
    "LineItem",
    "Statement",
    "Model",
    "SpecLine",
    "ModelSpec",
    "load_spec",
    "Violation",
    "Skipped",
    "ValidationResult",
    "validate_model",
    "LABELS",
]

StatementKind = Literal["balance_sheet", "income_statement", "cash_flow"]

# Canonical labels the identities are written against. The spec only fixes the
# `<section>.<name>` convention (e.g. `assets.total`), so these are the defaults;
# pass `labels={...}` to validate_model to override any of them.
LABELS: dict[str, str] = {
    "total_assets": "assets.total",
    "total_current_assets": "assets.total_current",
    "total_non_current_assets": "assets.total_non_current",
    "total_liabilities": "liabilities.total",
    "total_equity": "equity.total",
    # BCA-style reports carry temporary syirkah funds between liabilities and
    # equity. Optional: included in the balance identity only when present.
    "total_syirkah": "syirkah.total",
    "pretax": "income.pretax",
    "tax": "income.tax",
    "net_income": "income.net_income",
    "beginning_cash": "cash.beginning",
    "net_change": "cash.net_change",
    "ending_cash": "cash.ending",
    "fx_effect": "cash.fx_effect",
    "operating": "cash.operating",
    "investing": "cash.investing",
    "financing": "cash.financing",
}

_Values = dict[int, Decimal]


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str  # canonical label, e.g. "assets.cash_and_equivalents"
    source_label: str  # exactly as printed in the PDF
    values: _Values  # year -> value, in the PDF's own unit
    is_total: bool = False
    level: int = 0  # indent depth, 0 = top level


class Statement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: StatementKind
    company: str
    unit: str  # e.g. "millions of Rupiah"
    years: list[int]
    items: list[LineItem]


class Model(BaseModel):
    """A 3-statement model, one entry per canonical line."""

    model_config = ConfigDict(extra="forbid")

    company: str
    unit: str
    years: list[int]
    balance_sheet: dict[str, _Values] = Field(default_factory=dict)
    income_statement: dict[str, _Values] = Field(default_factory=dict)
    cash_flow: dict[str, _Values] = Field(default_factory=dict)


# --- model spec ------------------------------------------------------------


class SpecLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    section: str
    template_row: int
    is_total: bool = False
    description: str = ""
    # A catch-all bucket. A line the mapper cannot place lands here, so a
    # granular item never has to fit the template one for one. When the spec
    # does not say, a label whose last name part starts with "other" is one.
    is_other: bool | None = None
    # A total the PDF does not print (a bank's liabilities net of nothing, for
    # example). Its value is the sum of the section's leaves.
    derived: bool = False
    # This line shares a template row with another line; both are summed into
    # that row. Used where the template has no row of its own.
    share: bool = False
    # This line is only used by the identity checks. The template computes it
    # itself (its cell is a formula), so it is never written.
    check_only: bool = False


class SpecSection(BaseModel):
    """A group of lines that rolls up into a total.

    `other` names the residual bucket: a PDF line the mapper did not place
    lands there, so the section still totals to what the PDF reported.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    total: str | None = None
    other: str | None = None


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    unit: str
    statements: dict[StatementKind, list[SpecLine]]
    # v1 does not populate drivers; the field is accepted so specs can carry it.
    sections: dict[str, SpecSection] = Field(default_factory=dict)
    # Where the numbers go. `sheet` names the tab, `header_rows` gives the
    # year-header row per statement, `check_rows` the template's own check rows.
    sheet: str = "3 Statements"
    header_rows: dict[str, int] = Field(default_factory=dict)
    check_rows: dict[str, int] = Field(default_factory=dict)

    def lines(self, kind: StatementKind) -> list[SpecLine]:
        return self.statements.get(kind, [])

    def line(self, label: str) -> SpecLine | None:
        for kind in self.statements:
            for item in self.statements[kind]:
                if item.label == label:
                    return item
        return None

    def other_label(self, section: str) -> str | None:
        entry = self.sections.get(section)
        return entry.other if entry else None

    def total_label(self, section: str) -> str | None:
        entry = self.sections.get(section)
        return entry.total if entry else None

    def header_row(self, kind: StatementKind) -> int:
        return self.header_rows.get(kind, 2)

    def check_row(self, name: str) -> int | None:
        return self.check_rows.get(name)


def load_spec(source: str | Path) -> ModelSpec:
    """Parse a spec from a YAML file path, or from a YAML string."""
    if isinstance(source, Path) or ("\n" not in source and Path(source).is_file()):
        source = Path(source).read_text(encoding="utf-8")
    spec = ModelSpec.model_validate(yaml.safe_load(source))
    _validate_spec(spec)
    return spec


def _validate_spec(spec: ModelSpec) -> None:
    """Reject a spec that cannot be self-checked.

    Two template rows writing the same place would fail late and quietly, so
    a row may be claimed twice only when the spec says so with `share:`.
    """
    rows: dict[int, list[str]] = {}
    sharers: dict[int, int] = {}
    for kind in spec.statements:
        for item in spec.statements[kind]:
            if item.check_only:
                # Never written, so it cannot collide with a written row.
                continue
            rows.setdefault(item.template_row, []).append(item.label)
            if item.share:
                sharers[item.template_row] = sharers.get(item.template_row, 0) + 1
    for row_number, labels in rows.items():
        if len(labels) > 1 and sharers.get(row_number, 0) != len(labels):
            raise ValueError(
                f"template row {row_number} is claimed by {labels}; "
                "mark the lines that share it with share: true"
            )
    for name, section in spec.sections.items():
        for role, label in (("other", section.other), ("total", section.total)):
            if label and spec.line(label) is None:
                raise ValueError(
                    f"section {name!r} names {role} bucket {label!r}, "
                    "which is not a line in the spec"
                )


# --- validation ------------------------------------------------------------


class Violation(BaseModel):
    identity: str  # e.g. "balance_sheet: total_assets == total_liabilities + total_equity"
    statement: StatementKind
    year: int
    expected: Decimal  # the right-hand side
    actual: Decimal  # the left-hand side
    gap: Decimal  # actual - expected
    labels: list[str]  # canonical labels involved, left side first

    def render(self) -> str:
        return (
            f"[{self.statement}] {self.identity} fails for {self.year}: "
            f"expected {self.expected}, got {self.actual}, gap {self.gap:+} "
            f"(labels: {', '.join(self.labels)})"
        )


class Skipped(BaseModel):
    identity: str
    statement: StatementKind
    year: int | None
    missing: list[str]

    def render(self) -> str:
        where = f" for {self.year}" if self.year is not None else ""
        return f"[{self.statement}] {self.identity} skipped{where}: missing {', '.join(self.missing)}"


class ValidationResult(BaseModel):
    ok: bool  # True when there are no violations. Skips do not fail the gate.
    violations: list[Violation] = Field(default_factory=list)
    skipped: list[Skipped] = Field(default_factory=list)

    def render(self) -> str:
        """One line per violation: the text to paste into an LLM retry prompt."""
        return "\n".join(v.render() for v in self.violations)

    def render_skipped(self) -> str:
        return "\n".join(s.render() for s in self.skipped)


def validate_model(
    model: Model,
    spec: ModelSpec | None = None,
    labels: dict[str, str] | None = None,
    tolerance: Decimal = Decimal(0),
) -> ValidationResult:
    """Run every accounting identity over ``model`` for each of its years.

    ``spec`` enables the section roll-up check; without it that check is skipped
    and reported. ``tolerance`` defaults to exact equality.
    """
    L = {**LABELS, **(labels or {})}
    violations: list[Violation] = []
    skipped: list[Skipped] = []

    def check(kind: StatementKind, name: str, lhs: str, rhs: list[tuple[int, str]],
              optional: tuple[str, ...] = ()) -> None:
        """lhs == sum(sign * rhs). `rhs` is [(+1|-1, label_key)]; optional keys are
        added (with +1) only when present."""
        data: dict[str, _Values] = getattr(model, kind)

        def resolve(key: str) -> str:
            # A key is either a label-key in LABELS or a canonical label.
            return L.get(key, key)

        lhs_label = resolve(lhs)
        rhs_labels = [(sign, resolve(key)) for sign, key in rhs]
        optional_labels = [(1, resolve(key)) for key in optional]
        for year in model.years:
            keys = [lhs_label] + [label for _, label in rhs_labels]
            missing = [label for label in keys if year not in data.get(label, {})]
            if missing:
                skipped.append(Skipped(identity=name, statement=kind, year=year, missing=missing))
                continue
            terms = rhs_labels + [(sign, label) for sign, label in optional_labels
                                  if year in data.get(label, {})]
            actual = data[lhs_label][year]
            expected = sum((sign * data[label][year] for sign, label in terms), Decimal(0))
            if abs(actual - expected) > tolerance:
                violations.append(Violation(
                    identity=name, statement=kind, year=year, expected=expected,
                    actual=actual, gap=actual - expected,
                    labels=[lhs_label] + [label for _, label in terms],
                ))

    check("balance_sheet", "total_assets == total_liabilities + total_equity (+ total_syirkah)",
          "total_assets", [(1, "total_liabilities"), (1, "total_equity")], optional=("total_syirkah",))
    # The PDF's own grand total, which must equal its total assets.
    check("balance_sheet", "total_assets == grand_total",
          "total_assets", [(1, "equity.grand_total")])
    # The current / non-current split must add up to the reported total.
    check("balance_sheet", "total_current_assets + total_non_current_assets == total_assets",
          "total_assets", [(1, "total_current_assets"), (1, "total_non_current_assets")])
    check("balance_sheet", "equity.parent_total + equity.non_controlling == equity.total",
          "equity.total", [(1, "equity.parent_total"), (1, "equity.non_controlling")])
    # Tax is printed as a negative, so it is added, not subtracted.
    check("income_statement", "net_income == pretax + tax",
          "net_income", [(1, "pretax"), (1, "tax")])
    check("income_statement", "attributable_to_parent + non_controlling == net_income",
          "net_income", [(1, "attributable_to_parent"), (1, "non_controlling")])
    check("cash_flow", "ending_cash == beginning_cash + net_change (+ fx_effect)",
          "ending_cash", [(1, "beginning_cash"), (1, "net_change")], optional=("fx_effect",))
    check("cash_flow", "net_change == operating + investing + financing",
          "net_change", [(1, "operating"), (1, "investing"), (1, "financing")])

    _check_rollups(model, spec, tolerance, violations, skipped)
    return ValidationResult(ok=not violations, violations=violations, skipped=skipped)


def _check_rollups(model: Model, spec: ModelSpec | None, tolerance: Decimal,
                   violations: list[Violation], skipped: list[Skipped]) -> None:
    """Check that a section's leaves sum to the section's derived total.

    Only totals the PDF does not print (a bank has no "Total current assets")
    are checked, and those are derived from their leaves, so this confirms the
    derivation rather than the mapping. The mapping itself is checked by the
    cross-section identities above, and the template's own check rows check
    the written result.

    The income statement is hierarchical (gross profit feeds operating profit
    feeds pretax), so a flat section roll-up does not describe it; the
    template's own formulas do that work.
    """
    if spec is None:
        for kind in ("balance_sheet", "income_statement", "cash_flow"):
            skipped.append(Skipped(identity="section roll-ups", statement=kind, year=None,
                                   missing=["spec"]))
        return
    for kind in ("balance_sheet",):
        data: dict[str, _Values] = getattr(model, kind)
        for total in (ln for ln in spec.lines(kind) if ln.is_total and ln.derived):
            leaves = [ln.label for ln in spec.lines(kind) if not ln.is_total
                      and (ln.section == total.section or ln.section.startswith(total.section + "."))]
            name = f"{total.label} == sum of leaves in section {total.section}"
            for year in model.years:
                if year not in data.get(total.label, {}):
                    skipped.append(Skipped(identity=name, statement=kind, year=year,
                                           missing=[total.label]))
                    continue
                absent = [lb for lb in leaves if year not in data.get(lb, {})]
                if absent:
                    skipped.append(Skipped(identity=name + " (absent leaves counted as 0)",
                                           statement=kind, year=year, missing=absent))
                expected = sum((data[lb][year] for lb in leaves if year in data.get(lb, {})), Decimal(0))
                actual = data[total.label][year]
                if abs(actual - expected) > tolerance:
                    violations.append(Violation(
                        identity=name, statement=kind, year=year, expected=expected, actual=actual,
                        gap=actual - expected, labels=[total.label] + leaves))
