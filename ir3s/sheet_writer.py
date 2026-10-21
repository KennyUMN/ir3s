"""Write validated historical figures into a 3-statement model template.

The rules that make this non-destructive, all measured against the user's
Google Sheet ("3 Statements" tab):

* Historical columns carry a plain integer year header (2019..2024 in columns
  C..H). Forecast columns carry a suffixed header (2025F..2030F in I..N).
  Only historical columns are ever written.
* Totals are the template's own formulas (`=sum(C8:C15)`), so leaves are
  written and the totals recompute themselves.
* A historical cell may still hold a hand-entered formula (e.g.
  `C9 = 3427 + 267015`). Overwriting it would destroy the user's work, so the
  writer refuses unless explicitly told to force.
* The other tabs (Financial Modelling, Valuation, Key Valuation Risk,
  Additional Data) are never touched.

The template already carries its own check rows (row 64 `Check......` for
assets against liabilities and equity, row 145 `Check..........` for cash flow
ending cash against balance sheet cash). A small formula evaluator recomputes
them from the written numbers, so the writer can prove the sheet balances
without waiting for Excel to recalculate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter

_CELL_REF = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)")
# A reference to another sheet: 'Financial Modelling'!E228
_SHEET_REF = re.compile(r"'([^']+)'!\$?([A-Z]{1,3})\$?(\d+)")
# Excel's function names are case-insensitive, and the template writes "sum".
_SUM_RANGE = re.compile(r"SUM\(\s*\$?([A-Z]{1,3})\$?(\d+)\s*:\s*\$?([A-Z]{1,3})\$?(\d+)\s*\)", re.I)
_SUM_CELLS = re.compile(r"SUM\(([^()]*)\)", re.I)


def _header_year(value: object) -> int | None:
    """The year a column header names, or None.

    The template stores its year headers as numbers (2019.0), so the text form
    is "2019.0" and a plain-text match misses every one of them.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        year = int(value)
        return year if 1900 <= year <= 2099 else None
    if value is None:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(19|20)\d{2}(?:\.0)?([A-Za-z])?", text)
    if not match:
        return None
    year = int(text[:4])
    return year if match.group(2) is None else None


def _forecast_year(value: object) -> int | None:
    """The year a forecast column header names (2025F), or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None
    match = re.fullmatch(r"(19|20)\d{2}(?:\.0)?\s*[A-Za-z]", str(value).strip())
    return int(str(value).strip()[:4]) if match else None


@dataclass
class WriteReport:
    """What the writer did, and what it refused to do."""

    written: dict[str, dict[int, str]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)

    @property
    def written_count(self) -> int:
        return sum(len(years) for years in self.written.values())

    def summary(self) -> str:
        lines = [f"wrote {self.written_count} cell(s)"]
        for label, years in sorted(self.written.items()):
            lines.append(f"  {label}: {', '.join(str(y) for y in sorted(years))}")
        if self.skipped:
            lines.append(f"skipped {len(self.skipped)}:")
            lines.extend(f"  {note}" for note in self.skipped)
        for name, value in sorted(self.checks.items()):
            lines.append(f"check {name}: {value}")
        return "\n".join(lines)


@dataclass
class Template:
    """A loaded template: its tabs, its historical columns, its year headers."""

    path: Path
    workbook: openpyxl.Workbook

    def sheet(self, name: str) -> openpyxl.worksheet.worksheet.Worksheet:
        if name not in self.workbook.sheetnames:
            raise KeyError(
                f"template has no sheet {name!r}; it has {list(self.workbook.sheetnames)}"
            )
        return self.workbook[name]

    def historical_columns(self, sheet, header_row: int) -> dict[int, int]:
        """Map year -> column index for the historical columns of a header row.

        A column counts as historical when its header is a plain year.
        """
        columns: dict[int, int] = {}
        for index in range(1, sheet.max_column + 1):
            year = _header_year(sheet.cell(row=header_row, column=index).value)
            if year is not None:
                columns[year] = index
        return columns

    def forecast_columns(self, sheet, header_row: int) -> dict[int, int]:
        """Map forecast year -> column index, for reporting a skipped year."""
        columns: dict[int, int] = {}
        for index in range(1, sheet.max_column + 1):
            year = _forecast_year(sheet.cell(row=header_row, column=index).value)
            if year is not None:
                columns[year] = index
        return columns


def open_template(path: str | Path) -> Template:
    """Load a template, keeping formulas rather than their last computed values."""
    resolved = Path(path)
    workbook = openpyxl.load_workbook(resolved, data_only=False)
    return Template(path=resolved, workbook=workbook)


def write_values(
    template: Template,
    sheet_name: str,
    header_row: int,
    rows: dict[int, dict[int, Decimal]],
    force: bool = False,
    label_for_row: dict[int, str] | None = None,
) -> WriteReport:
    """Write figures into the historical columns of a template sheet.

    `rows` maps a template row number to {year: value}. Totals are not written:
    the template computes them, so passing one is refused and reported.
    """
    sheet = template.sheet(sheet_name)
    historical = template.historical_columns(sheet, header_row)
    forecast = template.forecast_columns(sheet, header_row)
    report = WriteReport()

    for row_number, values in sorted(rows.items()):
        label = (label_for_row or {}).get(row_number, f"row {row_number}")
        for year, value in sorted(values.items()):
            column = historical.get(year)
            if column is None:
                if year in forecast:
                    report.skipped.append(
                        f"{label} {year} is a forecast column; skipped"
                    )
                else:
                    report.skipped.append(f"{label} {year} is not in the template; skipped")
                continue
            cell = sheet.cell(row=row_number, column=column)
            if isinstance(cell.value, str) and cell.value.startswith("=") and not force:
                # A formula that only carries the previous column forward
                # (=G36) is a value the owner can replace. A formula that
                # computes something (=sum(H8:H15)) is not.
                if _is_forward_link(cell.value):
                    if not force:
                        report.skipped.append(
                            f"{label} {year} ({cell.coordinate}) carries the previous column "
                            "forward; re-run with --force to replace it"
                        )
                        continue
                else:
                    report.skipped.append(
                        f"{label} {year} ({cell.coordinate}) holds a formula; skipped"
                    )
                    continue
            cell.value = float(value)
            report.written.setdefault(label, {})[year] = str(value)

    return report


def _is_forward_link(formula: str) -> bool:
    """True for a formula that only carries the previous column forward.

    The template's forecast columns chain from the last historical column
    (=G36, =H36, ...), and a historical cell that does the same holds a
    value the owner may replace. A formula that computes something, like
    =sum(H8:H15), is a total and is left alone.
    """
    return bool(re.fullmatch(r"=\$?[A-Z]{1,3}\$?\d+", formula.strip()))


def _number(value: Decimal) -> str:
    """A Decimal as the plain text the formula evaluator expects."""
    return str(value.normalize())


def _cell_number(sheet, row: int, column: int, seen: set[tuple[int, int]] | None = None) -> Decimal:
    """The numeric value of a cell, following formulas one level deep.

    A cell that holds a formula is evaluated with the small evaluator below.
    """
    value = sheet.cell(row=row, column=column).value
    if value is None:
        return Decimal(0)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str) and value.startswith("="):
        guard = seen if seen is not None else set()
        if (row, column) in guard:
            return Decimal(0)
        guard.add((row, column))
        return evaluate_formula(sheet, value, guard)
    return Decimal(0)


def _resolve_sheet(sheet, name: str):
    """The named sheet of the same workbook, or None."""
    workbook = getattr(sheet, "parent", None)
    if workbook is None or name not in workbook.sheetnames:
        return None
    return workbook[name]


def evaluate_formula(sheet, formula: str, seen: set[tuple[int, int]] | None = None) -> Decimal:
    """Evaluate the small formula subset the template's check rows use.

    Supports cell references, cross-sheet references, `+ - * /`, `SUM(range)`
    and `SUM(a, b, c)`. Anything outside that subset returns zero rather than
    guessing, and the caller reports the check as not evaluable.
    """
    guard = seen if seen is not None else set()
    expression = formula[1:] if formula.startswith("=") else formula

    def replace_sheet_ref(match: re.Match[str]) -> str:
        name, column, row = match.groups()
        other = _resolve_sheet(sheet, name)
        if other is None:
            raise ValueError(f"unknown sheet {name!r} in {formula!r}")
        return _number(_cell_number(other, int(row), column_index_from_string(column), guard))

    expression = _SHEET_REF.sub(replace_sheet_ref, expression)

    def replace_range(match: re.Match[str]) -> str:
        first_col, first_row, last_col, last_row = match.groups()
        start = column_index_from_string(first_col)
        end = column_index_from_string(last_col)
        total = Decimal(0)
        for row in range(int(first_row), int(last_row) + 1):
            for column in range(start, end + 1):
                total += _cell_number(sheet, row, column, guard)
        return _number(total)

    expression = _SUM_RANGE.sub(replace_range, expression)

    def replace_sum(match: re.Match[str]) -> str:
        inner = match.group(1)
        total = Decimal(0)
        for part in inner.split(","):
            part = part.strip()
            if not part:
                continue
            reference = _CELL_REF.fullmatch(part)
            if reference:
                column = column_index_from_string(reference.group(1))
                total += _cell_number(sheet, int(reference.group(2)), column, guard)
        return _number(total)

    expression = _SUM_CELLS.sub(replace_sum, expression)

    def replace_cell(match: re.Match[str]) -> str:
        column = column_index_from_string(match.group(1))
        return _number(_cell_number(sheet, int(match.group(2)), column, guard))

    expression = _CELL_REF.sub(replace_cell, expression)

    if not re.fullmatch(r"[0-9eE\.\+\-\*/\(\) ]+", expression):
        raise ValueError(f"formula outside the supported subset: {formula!r}")
    try:
        return Decimal(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307
    except (InvalidOperation, ZeroDivisionError, SyntaxError) as error:
        raise ValueError(f"could not evaluate {formula!r}: {error}") from error


def read_checks(
    sheet,
    check_rows: dict[str, int],
    columns: list[int],
) -> dict[str, str]:
    """Recompute the template's own check rows from the written numbers.

    A check that reads zero means the sheet balances in that column.
    """
    results: dict[str, str] = {}
    for name, row_number in check_rows.items():
        values: list[str] = []
        for column in columns:
            cell = sheet.cell(row=row_number, column=column)
            if cell.value is None:
                continue
            try:
                value = evaluate_formula(sheet, str(cell.value))
            except ValueError:
                values.append(f"{get_column_letter(column)}=not evaluable")
                continue
            values.append(f"{get_column_letter(column)}={value.normalize()}")
        results[name] = ", ".join(values) if values else "no columns to check"
    return results
