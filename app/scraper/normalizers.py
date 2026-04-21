"""Pure-Python string helpers that split/structure messy scraped text.

Every function here operates on already-extracted strings (or lists of them),
never on HTML. Functions are tolerant of missing/empty/malformed input and
always return a sensible default instead of raising.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "clean_whitespace",
    "normalize_position_title",
    "normalize_work_experience",
    "normalize_conference_string",
    "normalize_phone",
    "normalize_award",
]


def clean_whitespace(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Position titles — `"A, B, C:"` → `["A", "B", "C"]`
# ---------------------------------------------------------------------------

def normalize_position_title(raw: str | None) -> list[str]:
    """Split a comma-joined position title into individual titles.

    Examples:
        'Старший преподаватель, Младший научный сотрудник, Аспирант:'
        → ['Старший преподаватель', 'Младший научный сотрудник', 'Аспирант']

        'Профессор:' → ['Профессор']
        '' → []
    """
    text = clean_whitespace(raw).rstrip(":").rstrip(",").strip()
    if not text:
        return []
    parts = [clean_whitespace(p).rstrip(":") for p in text.split(",")]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Work experience — detect year patterns, split the blob into per-entry dicts
# ---------------------------------------------------------------------------

# Match either a standalone 4-digit year or a year range. Also accepts an
# optional `MM.` month prefix so patterns like `09.2013 – н.в.` are captured
# as a single span.
#   2021                  single year (rarely alone, see below)
#   2021 г.               single year with Russian marker
#   09.2013               month.year
#   2018 – 2020
#   2015 - 2017
#   2021 г. – по н.в.     open range
#   2021 – по настоящее время
#   2021 – н.в.
_YEAR_ATOM = r"(?:\d{1,2}\.)?(?:19|20)\d{2}(?:\s*г\.?)?"
_OPEN_END = r"(?:по\s+н\.?в\.?|по\s+настоящее\s+время|н\.?в\.?)"
_SEP = r"\s*[–\-−—]\s*"
_YEAR_PATTERN_RE = re.compile(
    rf"(?P<span>{_YEAR_ATOM}(?:{_SEP}(?:{_YEAR_ATOM}|{_OPEN_END}))?)",
    re.IGNORECASE,
)
# Stronger pattern — only matches year-ish spans that look like entry
# prefixes: the year appears at a non-digit boundary and the span ends at
# whitespace, punctuation, or end-of-string.
_ENTRY_PREFIX_RE = re.compile(
    rf"(?<![\d.])(?P<span>{_YEAR_ATOM}(?:{_SEP}(?:{_YEAR_ATOM}|{_OPEN_END}))?)(?=\s|$|[,;:.])",
    re.IGNORECASE,
)


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize_work_experience(raw: Any) -> list[dict[str, str]]:
    """Split a single messy work-experience blob (or a list of them) into
    structured per-entry dicts.

    Accepts:
        str — parse as a single blob containing many entries.
        list[str] — parse each item; each may itself be a single entry or
          another blob.

    Each returned dict has two keys: ``years`` and ``position``. Entries whose
    position text is empty after splitting are dropped.

    Examples:
        '2021 г. – по н.в. Высшая школа... 2018 – 2020 лаборант... '
        → [
            {'years': '2021 г. – по н.в.', 'position': 'Высшая школа...'},
            {'years': '2018 – 2020', 'position': 'лаборант...'},
          ]
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[dict[str, str]] = []
        for item in raw:
            out.extend(normalize_work_experience(item))
        return out

    text = _collapse_spaces(str(raw))
    if not text:
        return []

    spans = list(_ENTRY_PREFIX_RE.finditer(text))
    if not spans:
        # No year marker at all → the whole string is one opaque entry.
        return [{"years": "", "position": text}]

    entries: list[dict[str, str]] = []
    # Any text BEFORE the first year marker is a preface; attach it to the
    # first entry's position so we don't lose it.
    preface = text[: spans[0].start()].strip(" ,.;—–-\t\n")
    for i, m in enumerate(spans):
        years = _collapse_spaces(m.group("span"))
        start = m.end()
        end = spans[i + 1].start() if i + 1 < len(spans) else len(text)
        body = text[start:end].strip(" ,.;—–-\t\n")
        if i == 0 and preface:
            body = f"{preface} {body}".strip()
        if body:
            entries.append({"years": years, "position": body})
    return entries


# ---------------------------------------------------------------------------
# Conference strings
# ---------------------------------------------------------------------------

_CONF_FULL_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_NO_LOC_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_NO_TALK_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_TITLE_ONLY_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
# When year is given separately (e.g. from the DOM hangover), body is
# `Title (Location). Доклад: talk_title` without a leading year.
_CONF_BODY_FULL_RE = re.compile(
    r"^\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_BODY_NO_LOC_RE = re.compile(
    r"^\s*(?P<title>.+?)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_BODY_NO_TALK_RE = re.compile(
    r"^\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def normalize_conference_string(
    raw: str | None, year: int | None = None
) -> dict[str, Any]:
    """Parse a conference description into structured fields.

    Returns a dict with keys ``year``, ``title``, ``location``, ``talk_title``.
    Absent fields are ``None``.

    If ``year`` is supplied (from DOM hangover), the text is matched without
    a leading year prefix. Otherwise the regexes expect `YYYY: ...` or
    `YYYY. ...` at the start.
    """
    result: dict[str, Any] = {
        "year": year,
        "title": None,
        "location": None,
        "talk_title": None,
    }

    text = clean_whitespace(raw)
    if not text:
        return result

    if year is not None:
        patterns = [
            (_CONF_BODY_FULL_RE, ("title", "loc", "talk")),
            (_CONF_BODY_NO_LOC_RE, ("title", "talk")),
            (_CONF_BODY_NO_TALK_RE, ("title", "loc")),
        ]
        for pat, keys in patterns:
            m = pat.match(text)
            if m:
                result["title"] = clean_whitespace(m.group("title")) or None
                if "loc" in keys:
                    result["location"] = clean_whitespace(m.group("loc")) or None
                if "talk" in keys:
                    result["talk_title"] = clean_whitespace(m.group("talk")) or None
                return result
        result["title"] = text
        return result

    patterns_y = [
        (_CONF_FULL_RE, ("year", "title", "loc", "talk")),
        (_CONF_NO_LOC_RE, ("year", "title", "talk")),
        (_CONF_NO_TALK_RE, ("year", "title", "loc")),
        (_CONF_TITLE_ONLY_RE, ("year", "title")),
    ]
    for pat, keys in patterns_y:
        m = pat.match(text)
        if m:
            try:
                result["year"] = int(m.group("year"))
            except (ValueError, IndexError):
                pass
            if "title" in keys:
                result["title"] = clean_whitespace(m.group("title")) or None
            if "loc" in keys:
                result["location"] = clean_whitespace(m.group("loc")) or None
            if "talk" in keys:
                result["talk_title"] = clean_whitespace(m.group("talk")) or None
            return result

    result["title"] = text
    return result


# ---------------------------------------------------------------------------
# Phone splitter
# ---------------------------------------------------------------------------

def normalize_phone(raw: str | None) -> list[str]:
    """Split a comma-/pipe-separated phones blob into a list of phones.

    Preserves internal extensions (`*NNNNN`) on the number they belong to.
    Common labels like `main:` or `mobile:` are kept inline because callers
    may want them; only the separators are stripped.

    Examples:
        'main: +7 (495) 772-95-90 *22120, mobile: +7 (999) 123-45-67'
        → ['main: +7 (495) 772-95-90 *22120', 'mobile: +7 (999) 123-45-67']
    """
    text = clean_whitespace(raw)
    if not text:
        return []
    # Accept `,`, `|`, `;` and `/` as separators. Do NOT split on spaces
    # because numbers contain spaces.
    parts = re.split(r"\s*[,|;/]\s*", text)
    return [p for p in (clean_whitespace(x) for x in parts) if p]


# ---------------------------------------------------------------------------
# Awards — parse optional year range from a title
# ---------------------------------------------------------------------------

_AWARD_YEAR_RANGE_RE = re.compile(
    r"\s*\(\s*(?:[^()\d]*?)(?P<from>\d{4})(?:\s*[–\-−—]\s*(?P<to>\d{4}))?\s*(?:г\.|гг\.)?\s*\)\s*$"
)


def normalize_award(raw: str | None) -> dict[str, Any]:
    """Extract optional `(YYYY)` or `(YYYY–YYYY)` year range from an award title.

    Examples:
        'Надбавка за публикацию (2025–2026)'
        → {'title': 'Надбавка за публикацию', 'year_from': 2025, 'year_to': 2026}

        'Медаль (2024 г.)'
        → {'title': 'Медаль', 'year_from': 2024, 'year_to': None}

        'Какая-то награда'
        → {'title': 'Какая-то награда', 'year_from': None, 'year_to': None}
    """
    text = clean_whitespace(raw)
    if not text:
        return {"title": "", "year_from": None, "year_to": None}

    m = _AWARD_YEAR_RANGE_RE.search(text)
    if not m:
        return {"title": text, "year_from": None, "year_to": None}

    year_from = int(m.group("from"))
    year_to_raw = m.group("to")
    year_to = int(year_to_raw) if year_to_raw else None
    title = text[: m.start()].rstrip(" ,.;:-–—")
    return {
        "title": title or text,
        "year_from": year_from,
        "year_to": year_to,
    }
