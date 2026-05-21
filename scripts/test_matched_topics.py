"""Smoke-тест substring-based matched_topics в /experts/search.

На коротких запросах (2-4 слова) KeyBERT возвращает [], поэтому
старая логика пересечения query_tags ∩ interests_extracted давала
matched_topics=[]. Новый substring-фильтр должен показывать совпадения
почти всегда.

Запуск (uvicorn / docker-app на :8000):
    python scripts/test_matched_topics.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402


async def main() -> None:
    queries = ["машинное обучение", "блокчейн", "теория игр", "social"]
    # trust_env=False — иначе httpx подхватит системный macOS-прокси
    # и упрётся в 503 при попытке достучаться до localhost через него.
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        for q in queries:
            r = await client.get(
                "http://localhost:8000/api/v1/experts/search",
                params={"q": q, "limit": 3},
            )
            data = r.json()
            print(f"\n=== {q} ===")
            for hit in data.get("results", []):
                print(f"  {hit['full_name']} (score={hit['score']:.3f})")
                print(f"    matched_topics: {hit.get('matched_topics', [])}")


if __name__ == "__main__":
    asyncio.run(main())
