"""Download raw HSE profile HTML into tmp/raw_fixtures/<tag>.html.

Uses the same User-Agent headers as app.scraper.client to stay consistent
with what the production scraper sees. Sleeps 0.3s between requests to stay
friendly. HTTP errors are reported but do not abort the run.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# allow running as `python scripts/fetch_fixtures.py` without installing the pkg
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from app.scraper.client import USER_AGENT
from scripts.fixtures_manifest import SAMPLES

OUT_DIR = ROOT / "tmp" / "raw_fixtures"


def _ensure_gitignore() -> None:
    gi = ROOT / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if "tmp/" in text or "\ntmp\n" in text:
        return
    suffix = ("\n" if text and not text.endswith("\n") else "") + "\n# Local scraper fixtures\ntmp/\n"
    gi.write_text(text + suffix, encoding="utf-8")
    print("added tmp/ to .gitignore")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore()

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
    })

    total = len(SAMPLES)
    errors = 0
    for idx, item in enumerate(SAMPLES, start=1):
        url = item["url"]
        tag = item["tag"]
        out_path = OUT_DIR / f"{tag}.html"
        try:
            resp = sess.get(url, timeout=30, allow_redirects=True)
        except requests.RequestException as e:
            print(f"[{idx:>2}/{total}] {tag}.html — ERROR: {e!r}")
            errors += 1
            time.sleep(0.3)
            continue

        size_kb = len(resp.content) // 1024
        status = resp.status_code
        if status != 200:
            print(f"[{idx:>2}/{total}] {tag}.html — {size_kb} KB — {status} !!!")
            errors += 1
        else:
            out_path.write_bytes(resp.content)
            print(f"[{idx:>2}/{total}] {tag}.html — {size_kb} KB — {status} OK")

        time.sleep(0.3)

    print(f"\nDone. {total - errors}/{total} fetched into {OUT_DIR.relative_to(ROOT)}")
    if errors:
        print(f"!! {errors} failures, see log above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
