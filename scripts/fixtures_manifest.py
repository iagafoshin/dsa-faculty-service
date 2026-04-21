"""Curated HSE profile URLs used as HTML fixtures for scraper tests.

Each entry has a `url` (real HSE profile) and a short `tag` used as a filename
stem under `tmp/raw_fixtures/<tag>.html` and `tests/fixtures/html/<tag>.html`.

The set is intentionally diverse so parser changes can be validated against
real DOM variation rather than a single synthetic sample.
"""
from __future__ import annotations

SAMPLES: list[dict[str, str]] = [
    # Rich profiles — many awards, conferences, grants
    {"url": "https://www.hse.ru/org/persons/25477", "tag": "rich_humanities_abankina_i"},
    {"url": "https://www.hse.ru/org/persons/203662", "tag": "rich_humanities_abankina_t"},
    {"url": "https://www.hse.ru/org/persons/63703", "tag": "rich_sociology_abramov"},

    # Technical — likely patents/grants
    {"url": "https://www.hse.ru/org/persons/25911955", "tag": "technical_ilvovsky"},
    {"url": "https://www.hse.ru/org/persons/4113483", "tag": "technical_neznanov"},
    {"url": "https://www.hse.ru/org/persons/139837", "tag": "math_kuznetsov"},
    {"url": "https://www.hse.ru/org/persons/3954058", "tag": "math_mirkin"},
    {"url": "https://www.hse.ru/org/persons/224066548", "tag": "technical_gromov"},

    # Supervisor heavy (many theses)
    {"url": "https://www.hse.ru/org/persons/204488", "tag": "supervisor_siwaev"},
    {"url": "https://www.hse.ru/org/persons/16338072", "tag": "supervisor_parinov"},

    # /staff/ slug URLs
    {"url": "https://www.hse.ru/staff/kamron", "tag": "staff_slug_aspirant_with_pubs"},
    {"url": "https://www.hse.ru/staff/AlexanderABD", "tag": "staff_slug_with_interests"},
    {"url": "https://www.hse.ru/staff/abolina", "tag": "staff_slug_minimal"},
    # aavakyan 404's as of 2026-04 → substituted with another sparse /staff/ slug
    {"url": "https://www.hse.ru/staff/aaa", "tag": "staff_slug_empty"},
    {"url": "https://www.hse.ru/staff/abdulkhakimov", "tag": "staff_slug_no_id"},

    # Economics / management
    {"url": "https://www.hse.ru/org/persons/60953", "tag": "econ_gusev"},
    # 791144985 404's → replaced with another economics-faculty profile
    {"url": "https://www.hse.ru/org/persons/101503035", "tag": "econ_semenikhin"},
    {"url": "https://www.hse.ru/org/persons/10586209", "tag": "math_lepskiy"},

    # Foreign staff — 190877371 404's → sampled a fresh active profile instead
    {"url": "https://www.hse.ru/org/persons/10440730", "tag": "possibly_foreign"},

    # Administrative / dean level
    {"url": "https://www.hse.ru/org/persons/140159", "tag": "admin_aleskerov"},
    {"url": "https://www.hse.ru/org/persons/3626661", "tag": "education_maksimenkova"},
    {"url": "https://www.hse.ru/org/persons/7161403", "tag": "education_papushina"},
]
