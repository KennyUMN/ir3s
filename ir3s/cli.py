"""Command line entry point.

    ir3s slice  <pdf>...                 show which statement pages are worth reading
    ir3s extract <pdf>                   read the three statements off a PDF
    ir3s fill   <pdf> <spec> <template>  write validated figures into a template
    ir3s verify <template>               recompute the template's own check rows
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from . import pdf_slicer, sheet_writer
from .extractor import extract_statements

STATEMENT_NAMES = ("balance_sheet", "income_statement", "cash_flow")


def _print_json(payload: object) -> None:
    def default(value):
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError(type(value))

    print(json.dumps(payload, indent=2, default=default))


def cmd_slice(args: argparse.Namespace) -> int:
    plan = pdf_slicer.plan_documents(args.pdfs, args.years or None)
    for path, slices in plan.items():
        print(f"{Path(path).name}")
        for item in slices:
            print(
                f"  {item.kind:16} pages {item.pages[0] + 1}-{item.pages[-1] + 1}"
                f"  years {item.years}"
            )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    statements = extract_statements(args.pdf, STATEMENT_NAMES)
    if args.json:
        payload = {
            kind: {
                "company": statement.company,
                "unit": statement.unit,
                "years": statement.years,
                "rows": [
                    {
                        "label": row.label,
                        "values": {str(c.year): str(c.value) for c in row.cells},
                    }
                    for row in statement.rows
                ],
            }
            for kind, statement in statements.items()
        }
        _print_json(payload)
        return 0
    for kind, statement in statements.items():
        print(f"=== {kind} ({statement.company}, {statement.unit}) years {statement.years}")
        for row in statement.rows:
            values = "  ".join(f"{c.year}={c.value:,}" for c in row.cells)
            print(f"  {values:46} | {row.label}")
    return 0


def cmd_fill(args: argparse.Namespace) -> int:
    from .pipeline import fill_template

    result = fill_template(
        pdf_path=args.pdf,
        spec_path=args.spec,
        template_path=args.template,
        output_path=args.output,
        force=args.force,
        dry_run=args.dry_run,
    )
    print(result)
    return 0 if result.ok else 1


def cmd_verify(args: argparse.Namespace) -> int:
    template = sheet_writer.open_template(args.template)
    sheet = template.sheet(args.sheet)
    columns = sorted(template.historical_columns(sheet, args.header_row).values())
    checks = sheet_writer.read_checks(
        sheet, {name: int(row) for name, row in args.check}, columns
    )
    for name, value in checks.items():
        print(f"{name}: {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ir3s", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    slice_parser = sub.add_parser("slice", help="find the statement pages in a PDF")
    slice_parser.add_argument("pdfs", nargs="+")
    slice_parser.add_argument("--years", type=int, nargs="*", default=[])
    slice_parser.set_defaults(func=cmd_slice)

    extract_parser = sub.add_parser("extract", help="read the statements off a PDF")
    extract_parser.add_argument("pdf")
    extract_parser.add_argument("--json", action="store_true")
    extract_parser.set_defaults(func=cmd_extract)

    fill_parser = sub.add_parser("fill", help="write validated figures into a template")
    fill_parser.add_argument("pdf")
    fill_parser.add_argument("spec")
    fill_parser.add_argument("template")
    fill_parser.add_argument("--output", default=None, help="write to a copy instead of in place")
    fill_parser.add_argument("--force", action="store_true", help="overwrite cells holding formulas")
    fill_parser.add_argument("--dry-run", action="store_true")
    fill_parser.set_defaults(func=cmd_fill)

    verify_parser = sub.add_parser("verify", help="recompute a template's check rows")
    verify_parser.add_argument("template")
    verify_parser.add_argument("--sheet", default="3 Statements")
    verify_parser.add_argument("--header-row", type=int, default=5)
    verify_parser.add_argument(
        "--check", nargs=2, action="append", default=[["balance", "64"], ["cash", "145"]]
    )
    verify_parser.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
