"""CLI-входная точка: `python -m app.nlp <command> [options]`.

Команды:
    enrich-persons       — для всех персон в БД извлекает теги и эмбеддит профиль
    enrich-publications  — то же для публикаций
"""
from __future__ import annotations

import argparse
import asyncio

from app.nlp.cli import enrich_persons, enrich_publications


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.nlp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser(
        "enrich-persons",
        help="NER + embedding для персон (Person.interests_extracted, Person.embedding)",
    )
    p1.add_argument("--sample", type=int, default=None,
                    help="ограничить общее число обрабатываемых записей")
    p1.add_argument("--batch", type=int, default=100,
                    help="размер батча (default 100)")
    p1.add_argument("--only-empty", action="store_true",
                    help="пропускать записи где embedding IS NOT NULL")

    p2 = sub.add_parser(
        "enrich-publications",
        help="NER + embedding для публикаций (Publication.topics, Publication.embedding)",
    )
    p2.add_argument("--sample", type=int, default=None)
    p2.add_argument("--batch", type=int, default=200)
    p2.add_argument("--only-empty", action="store_true")

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.cmd == "enrich-persons":
        asyncio.run(enrich_persons(
            sample=args.sample, batch=args.batch, only_empty=args.only_empty,
        ))
    elif args.cmd == "enrich-publications":
        asyncio.run(enrich_publications(
            sample=args.sample, batch=args.batch, only_empty=args.only_empty,
        ))


if __name__ == "__main__":
    main()
