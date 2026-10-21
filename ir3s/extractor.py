"""Locate the financial-statement pages inside a large IR PDF, and read the
figures off those pages deterministically.

Why deterministic: the figures in a PDF financial statement are right-aligned at
fixed coordinates, and every statement page repeats a column header row. That
makes "which year is this number" a geometry question, not a language question.
Measured on the Bank BCA audited reports (2019-2025): the first year column's
right edge sits near x=475pt and the second near x=544pt, and the header row is
`Notes | 2025 | 2024`.

The consequence is that no number ever passes through a language model, so the
hallucinated-digit failure mode is structurally impossible rather than merely
unlikely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import pymupdf

# A statement page carries one of these titles, in Indonesian or English.
STATEMENT_TITLES: tuple[tuple[str, str], ...] = (
    ("balance_sheet", "statement of financial position"),
    ("balance_sheet", "laporan posisi keuangan"),
    ("income_statement", "statement of profit or loss"),
    ("income_statement", "laba rugi"),
    ("cash_flow", "statement of cash flows"),
    ("cash_flow", "arus kas"),
    ("equity", "statement of changes in equity"),
    ("equity", "laporan perubahan ekuitas"),
    ("highlights", "financial highlights"),
    ("highlights", "ikhtisar data keuangan"),
)

# Title words that identify the statement a page belongs to, in priority order.
_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("balance_sheet", re.compile(r"statements?\s+of\s+financial\s+position", re.I)),
    ("balance_sheet", re.compile(r"laporan\s+posisi\s+keuangan", re.I)),
    ("income_statement", re.compile(r"statements?\s+of\s+profit\s+or\s+loss", re.I)),
    ("income_statement", re.compile(r"laba\s+rugi", re.I)),
    ("cash_flow", re.compile(r"statements?\s+of\s+cash\s+flows", re.I)),
    ("cash_flow", re.compile(r"arus\s+kas", re.I)),
    ("equity", re.compile(r"statements?\s+of\s+changes\s+in\s+equity", re.I)),
    ("equity", re.compile(r"laporan\s+perubahan\s+ekuitas", re.I)),
)

# Zones on a statement page, measured on the BCA reports.
LABEL_MAX_X = 340.0
VALUE_MIN_X = 420.0
NOTES_TOKEN = "Notes"
# A statement names itself in the top band of the page, above the figures.
HEADER_BAND_Y = 120.0

_NUMERIC = re.compile(r"^\(?-?[\d][\d.,]*\)?\*?$")
_DASHES = {"-", "--", "–", "—"}


class ExtractionError(Exception):
    """A statement was located but could not be read."""


@dataclass(frozen=True)
class Cell:
    """One figure, already bound to a year."""

    year: int
    value: Decimal
    raw: str


@dataclass
class Row:
    """One printed line: its label plus the figures on that line."""

    label: str
    cells: list[Cell] = field(default_factory=list)
    notes: str = ""
    page: int = 0
    bold: bool = False
    # The section heading the line sits under ("ASSETS", "LIABILITIES").
    section: str = ""
    # True when the line's figure equals the sum of the lines above it, so it
    # is a subtotal rather than a new primitive.
    is_subtotal: bool = False

    def value_for(self, year: int) -> Decimal | None:
        for cell in self.cells:
            if cell.year == year:
                return cell.value
        return None


@dataclass
class Statement:
    """One statement read off one or more pages."""

    kind: str
    company: str
    unit: str
    years: list[int]
    rows: list[Row] = field(default_factory=list)

    def row_for(self, label: str) -> Row | None:
        """Find a row by exact label, then by a normalised comparison."""
        for row in self.rows:
            if row.label == label:
                return row
        target = _normalise(label)
        for row in self.rows:
            if _normalise(row.label) == target:
                return row
        return None

    def value(self, label: str, year: int) -> Decimal | None:
        row = self.row_for(label)
        return row.value_for(year) if row else None


def _normalise(text: str) -> str:
    """Fold a printed label to a comparison key: case, spacing, punctuation."""
    folded = re.sub(r"\s+", " ", text.strip().lower())
    return re.sub(r"[^a-z0-9 ]", "", folded)


def parse_number(token: str) -> Decimal | None:
    """Parse one printed figure.

    Handles the two conventions in this corpus: English "1,234.56" and Indonesian
    "1.234,56"; parentheses for negatives; a trailing "*" footnote marker; and a
    bare "-" for nil.
    """
    text = token.strip().rstrip("*").strip()
    if text in _DASHES:
        return Decimal(0)
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(" ", "").replace(" ", "")
    if not text or text == "-":
        return Decimal(0)
    if "," in text and "." in text:
        # The right-most separator is the decimal point.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        # Three trailing digits is a thousands group; one or two is a decimal.
        text = text.replace(",", "") if len(tail) == 3 else head + "." + tail
    elif "." in text:
        head, _, tail = text.rpartition(".")
        text = text.replace(".", "") if len(tail) == 3 else head + "." + tail
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative else value


def _is_numeric(token: str) -> bool:
    text = token.strip()
    if text in _DASHES:
        return True
    if not _NUMERIC.match(text):
        return False
    return any(ch.isdigit() for ch in text)


def parse_year(token: str) -> int | None:
    """The year a header token names, or None.

    A year header can carry footnote markers: "2025", "2024*", "2024*)". The
    markers have to come off in the right order, because "2024*)" ends in a
    parenthesis that hides the asterisk from a plain rstrip.
    """
    text = token.strip()
    if not re.fullmatch(r"(19|20)\d{2}\s*\*?\)?|\*?\)?", text):
        return None
    return int(text[:4])


def _cluster_lines(words: list[tuple], tolerance: float = 2.5) -> list[list[tuple]]:
    """Group words into visual lines by vertical position."""
    lines: list[dict] = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        for line in lines:
            if abs(line["y"] - word[1]) <= tolerance:
                line["words"].append(word)
                break
        else:
            lines.append({"y": word[1], "words": [word]})
    for line in lines:
        line["words"].sort(key=lambda w: w[0])
    lines.sort(key=lambda line: line["y"])
    return [line["words"] for line in lines]


def mark_subtotals(rows: list[Row]) -> list[Row]:
    """Flag the rows that are subtotals rather than new line items.

    A statement prints a subtotal as the sum of the lines above it. Walking
    the rows of a section and comparing each figure with the running sum of
    the primitives above it tells the two apart, which the bold face alone
    does not: BCA prints "Total interest and sharia income" in the regular
    weight while "NET INTEREST AND SHARIA INCOME" is bold, and both are
    subtotals.

    A row that matches the running sum is a subtotal and does not extend the
    run. A row that does not match is a primitive and does.
    """
    section = None
    runs: dict[int, list[Decimal]] = {}
    for row in rows:
        if row.section != section:
            section = row.section
            runs = {}
        for cell in row.cells:
            year = cell.year
            run = runs.setdefault(year, [])
            if run and cell.value == sum(run, Decimal(0)):
                row.is_subtotal = True
                # A subtotal is a component of the next subtotal, not a new
                # primitive, so the run keeps only the subtotal's own value.
                runs[year] = [cell.value]
            else:
                run.append(cell.value)
    return rows


def _bold_lines(page: pymupdf.Page) -> set[int]:
    """The y positions of the page's bold text lines.

    Bold separates a section heading ("ASSETS", "LIABILITIES", "EQUITY") from a
    line item. Measured on the BCA reports: headings and totals are
    Arial-BoldMT, components are ArialMT.
    """
    positions: set[int] = set()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if "Bold" in span.get("font", ""):
                    positions.add(round(span["bbox"][1]))
    return positions


def _column_clusters(lines: list[list[tuple]], header_index: int) -> list[tuple[float, list[tuple]]]:
    """Cluster the value figures by right edge, below the header row.

    Figures are right-aligned, so the right edge is the stable coordinate.
    """
    buckets: dict[int, list[tuple]] = {}
    for line in lines[header_index + 1 :]:
        for word in line:
            if word[0] >= VALUE_MIN_X and _is_numeric(word[4]):
                buckets.setdefault(round(word[2] / 4.0), []).append(word)
    clusters: list[list[tuple]] = []
    for _, words in sorted(buckets.items()):
        if clusters:
            previous = clusters[-1]
            mean = sum(w[2] for w in words) / len(words)
            last = sum(w[2] for w in previous) / len(previous)
            if abs(mean - last) < 10.0:
                previous.extend(words)
                continue
        clusters.append(list(words))
    return [(sum(w[2] for w in words) / len(words), words) for words in clusters]


def read_page(
    page: pymupdf.Page, page_number: int = 0
) -> tuple[list[int], list[Row]]:
    """Read one statement page into labelled rows with year-tagged figures.

    Returns the years found on the page and the rows read from it.
    """
    lines = _cluster_lines(page.get_text("words"))

    header_index = None
    years: list[int] = []
    for index, line in enumerate(lines):
        tokens = [w[4].strip() for w in line]
        if not any(t.startswith(NOTES_TOKEN) for t in tokens):
            continue
        found = []
        for word in line:
            year = parse_year(word[4].strip())
            if year is not None:
                found.append((word[0], year))
        if len(found) >= 2:
            header_index = index
            years = [year for _, year in sorted(found)]
            break
    if header_index is None:
        return [], []

    clusters = _column_clusters(lines, header_index)
    if len(clusters) != len(years):
        # Pair each header year with the cluster whose figures sit nearest to it.
        pairs: list[tuple[float, list[tuple]]] = []
        remaining = list(clusters)
        for word in sorted(
            (w for w in lines[header_index] if parse_year(w[4].strip())),
            key=lambda w: w[0],
        ):
            if not remaining:
                break
            best = min(remaining, key=lambda c: abs(c[0] - word[0]))
            remaining.remove(best)
            pairs.append(best)
        clusters = pairs

    bold_y = _bold_lines(page)
    rows: list[Row] = []
    pending: list[str] = []
    section = ""
    for line in lines[header_index + 1 :]:
        label_parts: list[str] = []
        note_parts: list[str] = []
        figures: list[tuple] = []
        for word in line:
            text = word[4].strip()
            if word[0] >= VALUE_MIN_X and _is_numeric(text):
                figures.append(word)
                continue
            if word[2] < LABEL_MAX_X:
                label_parts.append(text)
            else:
                note_parts.append(text)

        label = " ".join(label_parts).strip()
        is_bold = any(round(line[0][1]) == y for y in bold_y)
        if not figures:
            if label:
                if is_bold:
                    # A bold line with no figures is a section heading
                    # ("ASSETS", "LIABILITIES"). It names the section, it is not
                    # part of the next line's label.
                    section = label
                    pending = []
                else:
                    pending.append(label)
            continue

        cells: list[Cell] = []
        for figure in figures:
            edge = figure[2]
            best_index, best_distance = None, None
            for index, (centre, _) in enumerate(clusters):
                distance = abs(edge - centre)
                if best_distance is None or distance < best_distance:
                    best_index, best_distance = index, distance
            if best_index is None:
                continue
            value = parse_number(figure[4])
            if value is None:
                continue
            cells.append(Cell(years[best_index], value, figure[4]))

        rows.append(
            Row(
                label=" ".join(pending + [label]).strip() if pending else label,
                cells=cells,
                notes=" ".join(note_parts).strip(),
                page=page_number,
                bold=is_bold,
                section=section,
            )
        )
        pending = []
    return years, rows


def _header_kind(page: pymupdf.Page) -> str | None:
    """Classify a page by a statement title in its header band.

    A statement page names itself at the top, above the figures. Titles quoted
    in the notes sit lower down, so only the top band is considered.
    """
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            if line["bbox"][1] >= HEADER_BAND_Y:
                continue
            text = " ".join(span["text"] for span in line.get("spans", []))
            for kind, pattern in _TITLE_PATTERNS:
                if pattern.search(text):
                    return kind
    return None


def has_column_header(page: pymupdf.Page) -> bool:
    """True when the page carries a `Notes | 2025 | 2024` column header.

    This is the signature of a consolidated statement page. It excludes the
    notes (which quote statement titles in body text) and the parent-entity
    statements (which sit at the back of the report and have no Notes column).
    """
    for line in _cluster_lines(page.get_text("words")):
        tokens = [word[4].strip() for word in line]
        if not any(token.startswith(NOTES_TOKEN) for token in tokens):
            continue
        years = re.findall(r"(?:19|20)\d{2}", " ".join(tokens))
        if len(years) >= 2:
            return True
    return False


def find_statement_pages(document: pymupdf.Document) -> dict[str, list[int]]:
    """Map statement kind to the page numbers that carry it.

    A consolidated statement page is one that carries the `Notes | 2025 | 2024`
    column header. That gate excludes the notes (which quote statement titles
    in body text) and the parent-entity statements at the back of the report
    (which have no Notes column). The header band names the statement.
    """
    found: dict[str, list[int]] = {}
    current: str | None = None
    for index, page in enumerate(document):
        if not has_column_header(page):
            current = None
            continue
        kind = _header_kind(page)
        if kind is not None:
            current = kind
        if current is None:
            continue
        found.setdefault(current, []).append(index)
    return found


def _detect_unit(text: str) -> str:
    """Read the reporting unit off the statement header."""
    lowered = text.lower()
    if "millions of rupiah" in lowered or "juta rupiah" in lowered:
        return "millions of Rupiah"
    if "billions" in lowered:
        return "billions"
    if "thousands" in lowered:
        return "thousands"
    if "millions" in lowered:
        return "millions"
    return "unspecified"


def _detect_company(text: str) -> str:
    """Read the reporting entity off the statement header."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("PT ") and " AND SUBSIDIARIES" in stripped.upper():
            return stripped.split(" AND SUBSIDIARIES")[0].strip()
        if stripped.upper().startswith("PT ") and len(stripped) < 60:
            return stripped
    return "unknown"


def extract_statements(
    pdf_path: str, kinds: tuple[str, ...] = ("balance_sheet", "income_statement", "cash_flow")
) -> dict[str, Statement]:
    """Read the requested statements out of a PDF.

    The result holds every printed row, so a later stage can map labels onto a
    target schema without going back to the PDF.
    """
    document = pymupdf.open(pdf_path)
    pages = find_statement_pages(document)

    statements: dict[str, Statement] = {}
    for kind in kinds:
        page_numbers = pages.get(kind, [])
        if not page_numbers:
            continue
        years: list[int] = []
        rows: list[Row] = []
        company = "unknown"
        unit = "unspecified"
        for number in page_numbers:
            page = document[number]
            text = page.get_text()
            if company == "unknown":
                company = _detect_company(text)
            if unit == "unspecified":
                unit = _detect_unit(text)
            page_years, page_rows = read_page(page, number + 1)
            for year in page_years:
                if year not in years:
                    years.append(year)
            rows.extend(page_rows)
        if not rows and years:
            # The page was recognised as a statement but nothing was read off
            # it. That means the figure columns were not where this reader
            # expects them, which is a failure worth reporting: a silent
            # empty result reads like a document with no statements.
            raise ExtractionError(
                f"{kind}: found statement pages {page_numbers} but read no rows. "
                "The figure columns are not where the reader expects them; "
                "this layout is not supported yet."
            )
        if rows:
            statements[kind] = Statement(
                kind=kind,
                company=company,
                unit=unit,
                years=sorted(years),
                rows=mark_subtotals(rows),
            )
    document.close()
    return statements
