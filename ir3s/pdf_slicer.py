"""Cut a large IR PDF down to the pages worth paying an LLM for.

An audited annual report is 150-600 pages. Only a handful carry the three
statements. This module finds those pages and reports the comparative years
each one holds, so the caller can decide which documents to read at all.

Comparative-year note: each audited report carries two years side by side (the
current year and the prior year), and the prior year is often restated. Reading
every other year's report therefore covers the full range with each year coming
from the most recent document that reports it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from .extractor import (
    _cluster_lines,
    find_statement_pages,
    parse_year,
)

# The statement titles, in English and Indonesian, live in the extractor, which
# owns the page classification. This module works on the pages it finds.


@dataclass
class Slice:
    """The pages of one statement inside one document."""

    kind: str
    document: str
    pages: list[int] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    title: str = ""

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _header_years(page: pymupdf.Page) -> list[int]:
    """Read the year header a statement page carries (`Notes | 2025 | 2024`).

    The header is laid out as separate positioned words, not as one line of
    text, so it has to be read from the word positions.
    """
    for line in _cluster_lines(page.get_text("words")):
        tokens = [word[4].strip() for word in line]
        if not any(token.startswith("Notes") for token in tokens):
            continue
        years = []
        for token in tokens:
            year = parse_year(token)
            if year is not None:
                years.append(year)
        if len(years) >= 2:
            return years
    return []


def slice_document(pdf_path: str, kinds: tuple[str, ...] | None = None) -> list[Slice]:
    """Find the statement pages in a PDF.

    A consolidated statement is identified by the column header row it
    repeats (`Notes | 2025 | 2024`), which is also what keeps the parent-only
    statements at the back of a report out of the result.
    """
    document = pymupdf.open(pdf_path)
    slices: list[Slice] = []
    by_kind: dict[str, Slice] = {}

    for kind, pages in find_statement_pages(document).items():
        if kinds is not None and kind not in kinds:
            continue
        item = Slice(kind=kind, document=pdf_path)
        for index in pages:
            item.pages.append(index)
            for year in _header_years(document[index]):
                if year not in item.years:
                    item.years.append(year)
        by_kind[kind] = item
        slices.append(item)

    document.close()
    for item in slices:
        item.years.sort()
    return slices


def plan_documents(
    pdf_paths: list[str], target_years: list[int] | None = None
) -> dict[str, list[Slice]]:
    """Choose which documents to read for which years.

    Each audited report holds two years. When a year is reported by more than
    one document, the most recently filed document wins, because a restated
    figure supersedes the original. Every statement of a chosen document is
    kept, not just the one that supplied the year.
    """
    candidates: dict[int, tuple[int, str]] = {}
    for path in pdf_paths:
        order = _document_order(path)
        for item in slice_document(path):
            for year in item.years:
                if target_years and year not in target_years:
                    continue
                if year not in candidates or order > candidates[year][0]:
                    candidates[year] = (order, path)

    chosen = {path for _, path in candidates.values()}
    plan: dict[str, list[Slice]] = {}
    for path in pdf_paths:
        if path not in chosen:
            continue
        plan[path] = slice_document(path)
    return plan


def _document_order(path: str) -> int:
    """A filing-date proxy, so a newer document wins for a restated year.

    BCA files live at .../Laporan-Diaudit/<year>/<dated-name>.pdf, so the
    directory year is the filing year.
    """
    match = re.search(r"Laporan-Diaudit/(\d{4})/", path)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{4})", path.rsplit("/", 1)[-1])
    return int(match.group(1)) if match else 0
