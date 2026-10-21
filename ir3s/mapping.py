"""Map printed PDF labels onto canonical labels.

The LLM decides only *which printed line is which canonical line*, by index.
Every number comes from the extractor's Row cells. Anything the LLM says about
values is never read.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from . import llm

__all__ = ["CanonicalLabel", "build_prompt", "map_statement"]

Values = dict[int, Decimal]
Mapped = dict[str, Values]


class CanonicalLabel:
    """One target line from the model spec. Build with `from_spec`."""

    def __init__(self, label: str, section: str = "", is_total: bool = False,
                 description: str = "", is_other: bool | None = None,
                 derived: bool = False):
        self.label, self.section, self.is_total, self.description = label, section, is_total, description
        self.derived = derived
        # A catch-all bucket. The spec says which one it is; the name is only a
        # fallback for a spec that does not say.
        self.is_other = (not is_total and label.rsplit(".", 1)[-1].startswith("other")
                         if is_other is None else is_other)

    @classmethod
    def from_spec(cls, entry: Any) -> "CanonicalLabel":
        """Accept a CanonicalLabel, a spec dict, or any object with the same attributes."""
        if isinstance(entry, cls):
            return entry
        get = entry.get if isinstance(entry, dict) else lambda k, d=None: getattr(entry, k, d)
        return cls(get("label"), get("section", "") or "", bool(get("is_total", False)),
                   get("description", "") or "", get("is_other", None), bool(get("derived", False)))


def _in_section(label: CanonicalLabel, section: str) -> bool:
    return label.section == section or label.section.startswith(section + ".")


def build_prompt(rows: list, labels: list[CanonicalLabel], years: list[int],
                 feedback: list[str] | None = None) -> str:
    """Compact prompt: targets and indexed printed lines with values as context."""
    targets = [f"- {c.label} [{c.section}]{' TOTAL' if c.is_total else ''}"
               + (f": {c.description}" if c.description else "")
               for c in labels]
    shown = years[-2:]
    printed = []
    for i, row in enumerate(rows):
        vals = " | ".join(str(row.value_for(y)) if row.value_for(y) is not None else "-" for y in shown)
        section = f"[{row.section}] " if row.section else ""
        # A detected subtotal is marked, so the model does not have to spot
        # "Total" in a label that may be printed in either language.
        subtotal = " (subtotal)" if row.is_subtotal else ""
        printed.append(f"{i}. {section}{row.label}{subtotal}  ({vals})")
    parts = [
        "Match each printed financial-statement line to one canonical label.",
        "Canonical labels (label [section]):", *targets,
        f"Printed lines (index. label (values for {', '.join(map(str, shown))})):", *printed,
        "Rules:",
        "- a line whose label says Total or NET is a subtotal: assign it to the matching TOTAL label;",
        "- a line with no close match goes to the 'other' label of its own section if there is one;",
        "- otherwise leave the line unassigned;",
        "- a canonical label may take several indices (they are summed);",
        "- do not output any numbers, only indices.",
        'Reply JSON: {"mapping": {"<canonical label>": [<index>, ...]}, "reason": "<one short sentence>"}',
    ]
    if feedback:
        parts += ["Your previous mapping failed these accounting checks; fix the mapping:", *feedback]
    return "\n".join(parts)


def _parse_assignment(reply: dict, rows: list, labels: list[CanonicalLabel]) -> dict[str, list[int]]:
    """Keep only valid (known label, in-range int index, unused) pairs. Everything else is dropped."""
    allowed = {c.label for c in labels}
    used: set[int] = set()
    out: dict[str, list[int]] = {}
    raw = reply.get("mapping")
    for label, idxs in (raw.items() if isinstance(raw, dict) else []):
        if label not in allowed or not isinstance(idxs, list):
            continue
        for i in idxs:
            if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(rows) and i not in used:
                used.add(i)
                out.setdefault(label, []).append(i)
    return out


def _sum_rows(rows: list, idxs: list[int], years: list[int]) -> Values:
    return {y: sum((rows[i].value_for(y) or Decimal(0) for i in idxs), Decimal(0)) for y in years}


def map_statement(
    rows: list,
    labels: list,
    years: list[int] | None = None,
    *,
    feedback: list[str] | None = None,
    ask: Callable[..., dict] | None = None,
) -> Mapped:
    """Map one statement. Returns canonical label -> {year: Decimal}.

    Values are summed from the extractor rows the model pointed at, so no
    number ever comes from the model itself. A label nothing maps to comes
    back as 0, and a total label carries the value the PDF reported, which
    the writer treats as derived rather than written.

    A section that does not add up is caught by the accounting identities,
    not by filling a residual: the "other" bucket is a label the model
    assigns, like any other.
    """
    canon = [CanonicalLabel.from_spec(c) for c in labels]
    years = years or sorted({c.year for r in rows for c in r.cells})
    reply = (ask or llm.chat_json)(build_prompt(rows, canon, years, feedback))
    assign = _parse_assignment(reply, rows, canon)

    zero = {y: Decimal(0) for y in years}
    result: Mapped = {c.label: (_sum_rows(rows, assign[c.label], years) if c.label in assign else dict(zero))
                      for c in canon}

    # A derived total is always the sum of its section's leaves, even when
    # the PDF prints a total of its own: the leaves land in the template's
    # rows, and the template recomputes its totals from them, so a total read
    # from the PDF would not match what the template shows.
    for c in canon:
        if not c.derived:
            continue
        if c.label in assign:
            # The PDF prints this total, and the model found it. Keep the
            # PDF's value: a derived total is the sum of its leaves only
            # when the PDF does not print it.
            continue
        under = [x for x in canon if not x.is_total and _in_section(x, c.section)]
        result[c.label] = {
            y: sum((result[x.label][y] for x in under), Decimal(0)) for y in years
        }
    return result
