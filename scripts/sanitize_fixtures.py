"""Sanitize raw HSE fixtures for check-in under tests/fixtures/html/.

Input : tmp/raw_fixtures/*.html        (gitignored, may contain real PII)
Output: tests/fixtures/html/*.html     (safe to commit)

Replaces personal contact data (phones, emails) with well-known placeholders.
All other page content — names, positions, publications, awards — is public
information on hse.ru and is preserved verbatim.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "tmp" / "raw_fixtures"
OUT_DIR = ROOT / "tests" / "fixtures" / "html"

# Phones are messy: +7 (495) 123-45-67, 8 495 123 45 67, +7 495 123 45 67 *22120,
# (812) 123-45-67, etc. We require a leading "+7"/"8"/"(" and at least 9 digits
# in total across digits/separators to avoid mangling random numeric tokens.
PHONE_RE = re.compile(
    r"""
    (?<!\w)                                   # not inside a word
    (?:\+?7|8)                                # country code 7 or 8
    [\s\-‐-― ]*                # optional separator
    \(?\d{3}\)?                               # area code with optional parens
    (?:[\s\-‐-― ]*\d){6,8}      # 6–8 more digits, any separators
    (?:[\s\-‐-― ]*\*\s*\d{3,6})?  # optional extension *NNNNN
    """,
    re.VERBOSE,
)

# Bare extension like "*22120" that may appear standalone in a dd.
EXT_RE = re.compile(r"\*\s*\d{3,6}")

# Loose email regex. Keep schema.org @example.com after replacement.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

PHONE_PLACEHOLDER = "+7 (XXX) XXX-XX-XX"
EMAIL_PLACEHOLDER = "user@example.com"


def sanitize(text: str) -> tuple[str, dict[str, int]]:
    counts = {"phones": 0, "emails": 0, "extensions": 0}

    def _ph(_m: re.Match[str]) -> str:
        counts["phones"] += 1
        return PHONE_PLACEHOLDER

    text = PHONE_RE.sub(_ph, text)

    def _ext(_m: re.Match[str]) -> str:
        counts["extensions"] += 1
        return "*XXXXX"

    text = EXT_RE.sub(_ext, text)

    def _em(_m: re.Match[str]) -> str:
        counts["emails"] += 1
        return EMAIL_PLACEHOLDER

    text = EMAIL_RE.sub(_em, text)
    return text, counts


def main() -> int:
    if not RAW_DIR.exists():
        print(f"no raw fixtures at {RAW_DIR}, run fetch_fixtures.py first", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(RAW_DIR.glob("*.html"))
    if not files:
        print(f"{RAW_DIR} is empty", file=sys.stderr)
        return 1

    total = {"phones": 0, "emails": 0, "extensions": 0}
    for idx, src in enumerate(files, start=1):
        raw = src.read_text(encoding="utf-8", errors="replace")
        clean, counts = sanitize(raw)
        dst = OUT_DIR / src.name
        dst.write_text(clean, encoding="utf-8")
        for k, v in counts.items():
            total[k] += v
        print(
            f"[{idx:>2}/{len(files)}] {src.name} — "
            f"phones={counts['phones']}, emails={counts['emails']}, ext={counts['extensions']}"
        )

    print(
        f"\nDone. {len(files)} files → {OUT_DIR.relative_to(ROOT)} "
        f"(phones={total['phones']}, emails={total['emails']}, ext={total['extensions']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
