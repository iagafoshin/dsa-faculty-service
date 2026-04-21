"""Inspect tests/fixtures/html/*.html and produce a DOM structure report.

Writes docs/html_structure_analysis.md containing:
  * which sections (by heading label) are present in each fixture,
  * frequency counts across the corpus,
  * structural variants per section (tab-node class, with-indent/js-timeline,
    ul.g-list_closer, etc.),
  * notable edge cases (fixtures with zero sections, odd heading text).

The script parses HTML with lxml — same library as app/scraper/parser.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "html"
OUT = ROOT / "docs" / "html_structure_analysis.md"

sys.path.insert(0, str(ROOT))

from lxml import html as lxml_html  # noqa: E402

# Section labels to detect. Keys normalized to lowercase for comparison.
SECTION_LABELS = [
    "Публикации",
    "Достижения и поощрения",
    "Награды",
    "Гранты",
    "Патенты",
    "Руководство студенческими работами",
    "Редакционный состав",
    "Опыт работы",
    "Конференции",
    "Доклады на конференциях",
    "Преподавание",
    "Образование",
    "Повышение квалификации",
    "Членство в диссертационных советах",
    "Области научных интересов",
    "Биография",
    "Публичные выступления",
    "Экспертиза",
]

# CSS/class markers of interest inside a section container.
CLASS_MARKERS = [
    "js-timeline-item",
    "l-section",
    "with-indent",
    "g-list_closer",
    "b-person-data",
    "employment-add",
    "edu-courses",
    "person-avatar",
]

# Raw tab-node tags — these appear as e.g. <div class="b-person-data" tab-node="awards">
TAB_NODES = [
    "awards", "sci-intrests", "sci-degrees1", "additional_education",
    "experience", "grants", "editorial-staff", "conferences",
    "press_links_news", "bio", "theses", "patents", "expertise",
    "activities", "public_speeches", "d_council",
]


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip().lower()


def _fixture_label(path: Path) -> str:
    return path.stem


def _section_presence(tree) -> dict[str, bool]:
    """Detect which section labels are present by h2/h3/h4 headings."""
    found = {label: False for label in SECTION_LABELS}
    headings = tree.xpath("//h2|//h3|//h4")
    heading_texts = [_norm("".join(h.itertext())) for h in headings]
    for label in SECTION_LABELS:
        wanted = _norm(label)
        for text in heading_texts:
            if wanted and wanted in text:
                found[label] = True
                break
    return found


def _tab_node_counts(tree) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in TAB_NODES:
        xp = f"//div[contains(@class,'b-person-data') and @tab-node='{name}']"
        counts[name] = len(tree.xpath(xp))
    return counts


def _class_marker_counts(tree) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cls in CLASS_MARKERS:
        counts[cls] = len(tree.xpath(f"//*[contains(@class, '{cls}')]"))
    return counts


def _person_id(tree) -> str | None:
    vals = tree.xpath("//*[@data-author]/@data-author")
    for v in vals:
        s = str(v).strip()
        if s.isdigit():
            return s
    vals = tree.xpath("//script[@data-person-id]/@data-person-id")
    for v in vals:
        s = str(v).strip()
        if s.isdigit():
            return s
    return None


def _full_name(tree) -> str | None:
    n = tree.xpath("//h1[contains(@class,'person-caption')]/text()")
    return _norm(n[0]) if n else None


def _headings(tree) -> list[str]:
    hs = tree.xpath("//h2|//h3|//h4")
    return [_norm("".join(h.itertext())) for h in hs if _norm("".join(h.itertext()))]


def _render_presence_table(rows: list[dict]) -> str:
    # rows: [{'tag': str, 'presence': {label: bool}}, ...]
    header = "| section \\ fixture | " + " | ".join(r["tag"] for r in rows) + " |"
    sep = "|---" * (len(rows) + 1) + "|"
    out = [header, sep]
    for label in SECTION_LABELS:
        cells = [("✅" if r["presence"][label] else "❌") for r in rows]
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def _render_frequency(rows: list[dict]) -> str:
    total = len(rows)
    freq = Counter()
    for r in rows:
        for label, v in r["presence"].items():
            if v:
                freq[label] += 1
    lines = []
    for label in SECTION_LABELS:
        n = freq[label]
        pct = round(n * 100 / total) if total else 0
        lines.append(f"- **{label}** — {n}/{total} fixtures ({pct}%)")
    return "\n".join(lines)


def _render_tab_nodes(rows: list[dict]) -> str:
    header = "| tab-node \\ fixture | " + " | ".join(r["tag"] for r in rows) + " |"
    sep = "|---" * (len(rows) + 1) + "|"
    lines = [header, sep]
    for tn in TAB_NODES:
        counts = [str(r["tab_nodes"].get(tn, 0)) for r in rows]
        lines.append(f"| `{tn}` | " + " | ".join(counts) + " |")
    return "\n".join(lines)


def _render_class_markers(rows: list[dict]) -> str:
    header = "| class \\ fixture | " + " | ".join(r["tag"] for r in rows) + " |"
    sep = "|---" * (len(rows) + 1) + "|"
    lines = [header, sep]
    for cls in CLASS_MARKERS:
        counts = [str(r["class_markers"].get(cls, 0)) for r in rows]
        lines.append(f"| `.{cls}` | " + " | ".join(counts) + " |")
    return "\n".join(lines)


def _render_variants(rows: list[dict]) -> str:
    """Summarize DOM-path variants observed across fixtures."""
    # We express variants as: "section X uses tab-node=Y in N fixtures, falls back to
    # heading-only in M fixtures".
    lines: list[str] = []

    label_to_tabnode = {
        "Награды": "awards",
        "Достижения и поощрения": "awards",
        "Области научных интересов": "sci-intrests",
        "Образование": "sci-degrees1",
        "Повышение квалификации": "additional_education",
        "Опыт работы": "experience",
        "Гранты": "grants",
        "Редакционный состав": "editorial-staff",
        "Конференции": "conferences",
        "Доклады на конференциях": "conferences",
        "Патенты": "patents",
        "Руководство студенческими работами": "theses",
        "Членство в диссертационных советах": "d_council",
        "Биография": "bio",
        "Публичные выступления": "public_speeches",
        "Экспертиза": "expertise",
    }

    for label, tn in label_to_tabnode.items():
        with_heading = sum(1 for r in rows if r["presence"][label])
        with_tabnode = sum(1 for r in rows if r["tab_nodes"].get(tn, 0) > 0)
        both = sum(
            1 for r in rows
            if r["presence"][label] and r["tab_nodes"].get(tn, 0) > 0
        )
        heading_only = with_heading - both
        tabnode_only = with_tabnode - both
        lines.append(
            f"- **{label}** / `tab-node={tn}`: heading hits {with_heading}, "
            f"tab-node hits {with_tabnode}, both {both}, heading-only {heading_only}, "
            f"tab-node-only {tabnode_only}"
        )
    return "\n".join(lines)


def _render_edge_cases(rows: list[dict]) -> str:
    lines: list[str] = []
    for r in rows:
        n_sections = sum(1 for v in r["presence"].values() if v)
        if n_sections == 0:
            lines.append(
                f"- `{r['tag']}` has **zero detected sections** (person_id={r['person_id']!r}, "
                f"name={r['full_name']!r})"
            )
        elif n_sections <= 2:
            present = [k for k, v in r["presence"].items() if v]
            lines.append(
                f"- `{r['tag']}` has only {n_sections} section(s): {present}"
            )
    # also: fixtures without person_id
    for r in rows:
        if not r["person_id"]:
            lines.append(f"- `{r['tag']}` has no data-author/person-id attribute")
    return "\n".join(lines) if lines else "- (none)"


def main() -> int:
    files = sorted(FIXTURES.glob("*.html"))
    if not files:
        print(f"no fixtures found at {FIXTURES}", file=sys.stderr)
        return 1

    rows = []
    for f in files:
        tree = lxml_html.fromstring(f.read_text(encoding="utf-8"))
        rows.append({
            "tag": _fixture_label(f),
            "person_id": _person_id(tree),
            "full_name": _full_name(tree),
            "presence": _section_presence(tree),
            "tab_nodes": _tab_node_counts(tree),
            "class_markers": _class_marker_counts(tree),
            "headings": _headings(tree),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)

    md: list[str] = []
    md.append("# HSE profile page — DOM structure analysis")
    md.append("")
    md.append(
        f"Generated by `scripts/analyze_fixtures.py` from "
        f"{len(rows)} fixtures in `tests/fixtures/html/`."
    )
    md.append("")
    md.append("## Section presence (heading scan)")
    md.append("")
    md.append("Heading match = an `<h2>/<h3>/<h4>` whose normalized text contains the label.")
    md.append("")
    md.append(_render_presence_table(rows))
    md.append("")
    md.append("## Frequency summary")
    md.append("")
    md.append(_render_frequency(rows))
    md.append("")
    md.append("## tab-node container counts")
    md.append("")
    md.append("Each section is rendered as `<div class=\"b-person-data\" tab-node=\"…\">`. "
              "Counts are how many such blocks exist per fixture.")
    md.append("")
    md.append(_render_tab_nodes(rows))
    md.append("")
    md.append("## Class marker counts")
    md.append("")
    md.append(_render_class_markers(rows))
    md.append("")
    md.append("## Section variants — heading vs tab-node")
    md.append("")
    md.append(
        "For each section, we cross-check two detectors. "
        "Discrepancies indicate DOM variants parser code must handle."
    )
    md.append("")
    md.append(_render_variants(rows))
    md.append("")
    md.append("## Edge cases")
    md.append("")
    md.append(_render_edge_cases(rows))
    md.append("")
    md.append("## Per-fixture overview")
    md.append("")
    for r in rows:
        md.append(f"### `{r['tag']}`")
        md.append("")
        md.append(f"- person_id: `{r['person_id']}`")
        md.append(f"- full_name: `{r['full_name']}`")
        md.append(f"- detected sections: {sum(1 for v in r['presence'].values() if v)}")
        md.append(f"- headings ({len(r['headings'])}): {r['headings'][:12]}"
                  f"{'…' if len(r['headings']) > 12 else ''}")
        md.append("")

    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(rows)} fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
