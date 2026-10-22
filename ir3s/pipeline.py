"""The pipeline: PDF in, populated template out.

    extract  -> read the statements off a PDF (deterministic)
    map      -> assign each printed line to a canonical label (the LLM)
    validate -> check the accounting identities (Python)
    write    -> put the validated numbers in the template's historical columns

The LLM is one step of four and the only one that can be wrong about a
label. Every number it does not touch, and every identity it could break, is
checked before anything is written.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from decimal import Decimal

from .extractor import extract_statements
from .mapping import map_statement
from .schemas import Model, ModelSpec, ValidationResult, load_spec, validate_model
from .sheet_writer import open_template, read_checks, write_values

STATEMENTS = ("balance_sheet", "income_statement", "cash_flow")


@dataclass
class FillResult:
    """What the pipeline did, and whether the result balances."""

    ok: bool = False
    model: Model | None = None
    validation: ValidationResult | None = None
    write_report: object | None = None
    output_path: str | None = None
    messages: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = []
        if self.output_path:
            lines.append(f"template: {self.output_path}")
        if self.validation is not None:
            lines.append(
                f"identities: {'all pass' if self.validation.ok else 'FAILED'}"
            )
            for violation in self.validation.violations:
                lines.append(f"  {violation.render()}")
        if self.write_report is not None:
            lines.append(self.write_report.summary())
        lines.extend(f"  {message}" for message in self.messages)
        return "\n".join(lines)


def build_model(
    pdf_path: str,
    spec: ModelSpec,
    ask=None,
    max_attempts: int = 3,
) -> tuple[Model, ValidationResult]:
    """Extract, map, and validate. Re-prompt the LLM on a failed identity.

    The retry carries the exact discrepancy, so a second attempt knows which
    line is wrong rather than guessing again.
    """
    statements = extract_statements(pdf_path, STATEMENTS)
    years: list[int] = []
    for statement in statements.values():
        for year in statement.years:
            if year not in years:
                years.append(year)
    years.sort()

    source_unit = next(
        (statement.unit for statement in statements.values()
         if statement.unit != "unspecified"),
        spec.unit,
    )
    feedback: list[str] | None = None
    result = ValidationResult(ok=True)
    model = Model(company=spec.company, unit=source_unit, years=years)

    for attempt in range(max(1, max_attempts)):
        values: dict[str, dict[str, dict[int, Decimal]]] = {}
        for kind in STATEMENTS:
            statement = statements.get(kind)
            if statement is None:
                continue
            labels = spec.lines(kind)
            if not labels:
                continue
            mapped = map_statement(statement.rows, labels, statement.years, feedback=feedback, ask=ask)
            values[kind] = mapped

        model = Model(
            company=spec.company,
            unit=source_unit,
            years=years,
            balance_sheet=values.get("balance_sheet", {}),
            income_statement=values.get("income_statement", {}),
            cash_flow=values.get("cash_flow", {}),
        )
        result = validate_model(model, spec)
        if result.ok:
            return model, result
        feedback = [violation.render() for violation in result.violations]
    return model, result


def fill_template(
    pdf_path: str,
    spec_path: str,
    template_path: str,
    output_path: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    ask=None,
    max_attempts: int = 3,
) -> FillResult:
    """Populate a template's historical columns from a PDF."""
    spec = load_spec(spec_path)
    model, validation = build_model(pdf_path, spec, ask=ask, max_attempts=max_attempts)
    result = FillResult(model=model, validation=validation)

    if not validation.ok:
        result.messages.append(
            "identities failed; nothing was written (run with a corrected spec or more attempts)"
        )
        return result

    template = open_template(template_path)
    target = output_path or template_path
    if output_path and not dry_run:
        shutil.copyfile(template_path, output_path)
        template = open_template(output_path)

    rows: dict[int, dict[int, Decimal]] = {}
    labels_by_row: dict[int, str] = {}
    # Which canonical lines went into each template row, so a row that took
    # more than one account can say so in a comment.
    merged_for_row: dict[int, list[str]] = {}
    # Each statement block has its own year-header row, so the columns are
    # resolved per statement rather than once for the sheet.
    header_row = spec.header_rows.get("balance_sheet", 2)
    # A statement reported in a different unit from the template's columns is
    # divided down here, so a full-rupiah report fills a millions column. The
    # model's unit is the one the statement was printed in.
    scale = spec.scale_to_target(model.unit)
    for kind in STATEMENTS:
        # The spec's lines, not the model's: a line the statement does not
        # print has to be written as zero, or the row keeps the number of
        # whichever company filled the template last.
        for spec_line in spec.lines(kind):
            if spec_line.check_only:
                # A check-only line is not in the template at all.
                continue
            if spec_line.is_total and not spec_line.share:
                # Totals the template computes itself are its own formulas, so
                # writing them would replace a formula with a constant. A total
                # marked `share` has no template row of its own and is written
                # into the row it shares.
                continue
            values = getattr(model, kind).get(spec_line.label, {})
            bucket = rows.setdefault(spec_line.template_row, {})
            for year in model.years:
                value = values.get(year, Decimal(0))
                bucket[year] = bucket.get(year, Decimal(0)) + value * scale
            labels_by_row.setdefault(spec_line.template_row, spec_line.label)
            merged_for_row.setdefault(spec_line.template_row, []).append(spec_line.label)

    sheet_name = spec.sheet
    header_row = spec.header_rows.get("balance_sheet", 2)
    report = write_values(
        template, sheet_name, header_row, rows, force=force,
        label_for_row=labels_by_row, merged_for_row=merged_for_row,
        clear_rows=tuple(r for kind in STATEMENTS
                         if (r := spec.row_ranges.get(kind)) is not None),
    )
    result.write_report = report
    result.output_path = None if dry_run else target

    if not dry_run:
        sheet = template.sheet(sheet_name)
        # The check rows sit in the balance sheet block, so its header row
        # gives the columns the checks are read from.
        columns = sorted(template.historical_columns(sheet, header_row).values())
        report.checks = read_checks(sheet, spec.check_rows, columns)
        template.workbook.save(target)

    result.ok = True
    return result
