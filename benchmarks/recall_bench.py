#!/usr/bin/env python3
"""
recall_bench.py
===============

Standard retrieval-recall benchmark for DocKG seeding changes.

Adapted from ``gutenberg_kg/scripts/evaluate_similar_to_value.py`` to A/B the
query-time seeding pipeline itself (dense-only vs hybrid RRF fusion) rather
than SIMILAR_TO build conditions.  Two complementary query sets:

Gold mode (cost side)
    Human-labeled queries from the gutenberg_kg gold CSV
    (``analysis/similar_to_query_template.csv``).  The gold set was built
    from dense-only retrieval pools, so hybrid seeding can only lose on it —
    treat deltas as the *cost* of the lexical channel.

Phrase mode (benefit side)
    Auto-generated exact-phrase queries: for each book, sample word spans
    from chunk text that occur in exactly one chunk; the source chunk is the
    expected result.  This measures verbatim-phrase retrieval — the case the
    lexical (BM25) channel exists for — with no human labeling.

The corpus artifacts are never modified: each book's ``graph.sqlite`` is
copied to a temp directory and the FTS5 index is built on the copy; the
existing LanceDB index is opened read-only, so node IDs stay stable and
match the gold labels.

Conditions are seeding variants, applied at query time to the same indices:

- ``dense``  — lexical channel disabled (pre-v0.15.7 behaviour)
- ``hybrid`` — stock RRF fusion with the current ``_LEXICAL_SEED_BASE_DIST``
- ``<float>`` (e.g. ``0.30``) — fusion with that synthetic lexical base dist

Usage
-----

Run both modes with default conditions (dense vs current hybrid)::

    .venv/bin/python benchmarks/recall_bench.py

Sweep synthetic base distances on the gold set only::

    .venv/bin/python benchmarks/recall_bench.py \\
        --conditions dense,0.25,0.35,0.45 --phrase-per-book 0

Author: Eric G. Suchanek, PhD
License: Elastic-2.0
Last Revision: 2026-06-10
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import doc_kg.kg as kgmod
from doc_kg.index import make_embedder
from doc_kg.kg import DocKG
from doc_kg.store import DEFAULT_RELS

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOOKS_ROOT = REPO_ROOT.parent / "gutenberg_kg"
DEFAULT_GOLD = "analysis/similar_to_query_template.csv"

# Token pattern must mirror FTS5's unicode61 tokenizer (and doc_kg's
# store._fts_terms): bare alphanumeric runs, apostrophes/punctuation split.
# Anything else (e.g. skipping digits) breaks phrase adjacency in the FTS
# index and silently degrades generated phrase queries to OR-of-terms.
_WORD = re.compile(r"[A-Za-z0-9]+")
_EXCLUDED_CONTENT = ("front_matter", "reference")


@dataclass(frozen=True)
class BenchQuery:
    """One benchmark query bound to a book.

    :param qid: Stable query id.
    :param mode: ``"gold"`` or ``"phrase"``.
    :param query: Query text.
    :param expected_ids: Relevant node ids.
    """

    qid: str
    mode: str
    query: str
    expected_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResultRow:
    """Per-query, per-condition metric row."""

    condition: str
    mode: str
    book: str
    qid: str
    query: str
    expected_n: int
    hits: int
    recall: float
    mrr: float
    ndcg: float
    seconds: float


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--books-root",
        default=str(DEFAULT_BOOKS_ROOT),
        help="Repo containing the labeled corpus (default: ../gutenberg_kg).",
    )
    p.add_argument(
        "--gold",
        default=DEFAULT_GOLD,
        help="Gold query CSV path relative to --books-root.",
    )
    p.add_argument(
        "--conditions",
        default="dense,hybrid",
        help="Comma-separated: 'dense', 'hybrid', or float base-dist values.",
    )
    p.add_argument("--k", type=int, default=8, help="Semantic seed count.")
    p.add_argument("--hop", type=int, default=1, help="Expansion hop count.")
    p.add_argument(
        "--max-nodes", type=int, default=15, help="Max nodes returned and metric cutoff k."
    )
    p.add_argument(
        "--phrase-per-book",
        type=int,
        default=5,
        help="Exact-phrase queries to auto-generate per book (0 disables).",
    )
    p.add_argument("--phrase-words", type=int, default=6, help="Words per generated phrase query.")
    p.add_argument("--seed", type=int, default=42, help="RNG seed for phrase sampling.")
    p.add_argument("--limit-books", type=int, default=0, help="Limit books (0 = all).")
    p.add_argument(
        "--out-prefix",
        default="benchmarks/data/recall_bench",
        help="Output prefix relative to the doc_kg repo root.",
    )
    return p.parse_args()


def split_ids(raw: str) -> tuple[str, ...]:
    """Split expected node ids from a CSV cell (comma/semicolon/pipe/newline)."""
    for s in ("|", ";", "\n"):
        raw = raw.replace(s, ",")
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def eval_metrics(
    retrieved: list[str], expected: tuple[str, ...], k: int
) -> tuple[int, float, float, float]:
    """Compute hits, Recall@k, MRR@k, nDCG@k for binary relevance.

    :param retrieved: Ranked node ids returned by the query.
    :param expected: Relevant node ids.
    :param k: Metric cutoff.
    :return: ``(hits, recall, mrr, ndcg)``.
    """
    rel = set(expected)
    top = retrieved[:k]
    hits = sum(1 for n in top if n in rel)
    recall = hits / max(len(rel), 1)
    rr = next((1.0 / i for i, n in enumerate(top, 1) if n in rel), 0.0)
    dcg = sum(1.0 / math.log2(i + 1) for i, n in enumerate(top, 1) if n in rel)
    ideal = min(len(rel), len(top))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal + 1))
    return hits, recall, rr, (dcg / idcg if idcg else 0.0)


def load_gold(csv_path: Path) -> dict[str, list[BenchQuery]]:
    """Load labeled gold queries grouped by book relpath.

    :param csv_path: Gold CSV (gutenberg_kg query-template format).
    :return: ``{book_relpath: [BenchQuery, ...]}``.
    """
    grouped: dict[str, list[BenchQuery]] = defaultdict(list)
    with csv_path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            qtext = (r.get("query_text") or "").strip()
            expected = split_ids((r.get("expected_node_ids") or "").strip())
            book = (r.get("book_relpath") or "").strip()
            if qtext and expected and book:
                grouped[book].append(
                    BenchQuery(
                        qid=(r.get("query_id") or "").strip(),
                        mode="gold",
                        query=qtext,
                        expected_ids=expected,
                    )
                )
    return grouped


def _normalise(text: str) -> str:
    """Lowercase and collapse a text to space-joined word tokens."""
    return " ".join(_WORD.findall(text.lower()))


def generate_phrase_queries(
    kg: DocKG, *, n_queries: int, n_words: int, rng: random.Random
) -> list[BenchQuery]:
    """Sample exact-phrase queries whose source chunk is unique in the book.

    Picks word spans from prose chunks and keeps a span only if it occurs in
    exactly one chunk's normalised text, so the source chunk is an unambiguous
    gold label for verbatim-phrase retrieval.

    :param kg: Open DocKG for one book (FTS not required).
    :param n_queries: Number of phrase queries to generate.
    :param n_words: Words per phrase.
    :param rng: Seeded RNG for reproducible sampling.
    :return: Generated queries (may be fewer if the book is too repetitive).
    """
    chunks = [
        n
        for n in kg.store.query_nodes(kinds=["chunk"])
        if (n.get("text") or "").strip()
        and n.get("content_type") not in _EXCLUDED_CONTENT
        and not (n.get("file_path") or "").endswith("reference.md")
    ]
    if not chunks:
        return []
    norm_texts = {n["id"]: _normalise(n["text"]) for n in chunks}

    queries: list[BenchQuery] = []
    seen_phrases: set[str] = set()
    candidates = rng.sample(chunks, k=min(len(chunks), n_queries * 8))
    for chunk in candidates:
        if len(queries) >= n_queries:
            break
        words = _WORD.findall(chunk["text"])
        if len(words) < n_words + 4:
            continue
        start = rng.randrange(2, len(words) - n_words - 1)
        phrase = " ".join(words[start : start + n_words])
        key = phrase.lower()
        if key in seen_phrases:
            continue
        seen_phrases.add(key)
        holders = [nid for nid, txt in norm_texts.items() if key in txt]
        if holders != [chunk["id"]]:
            continue  # phrase not unique to its source chunk
        queries.append(
            BenchQuery(
                qid=f"P{len(queries):03d}",
                mode="phrase",
                query=phrase,
                expected_ids=(chunk["id"],),
            )
        )
    return queries


def main() -> None:
    """Run the seeding A/B benchmark and print per-condition summaries."""
    args = parse_args()
    books_root = Path(args.books_root).resolve()
    gold = load_gold(books_root / args.gold)
    books = sorted(gold)
    if args.limit_books > 0:
        books = books[: args.limit_books]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    rels = tuple(r for r in DEFAULT_RELS if r != "SIMILAR_TO")
    orig_base = kgmod._LEXICAL_SEED_BASE_DIST

    embedder = make_embedder()  # shared across books: one model load
    tmp_root = Path(tempfile.mkdtemp(prefix="recall_bench_"))
    rows: list[ResultRow] = []
    print(
        f"Books: {len(books)}  conditions: {conditions}  "
        f"k={args.k} hop={args.hop} max_nodes={args.max_nodes}"
    )

    try:
        for bi, book in enumerate(books, 1):
            book_dir = books_root / book
            src_db = book_dir / ".dockg" / "graph.sqlite"
            lance = book_dir / ".dockg" / "lancedb"
            if not src_db.exists() or not lance.exists():
                print(f"[{bi}/{len(books)}] SKIP {book} (missing .dockg artifacts)")
                continue

            work_db = tmp_root / f"book_{bi}.sqlite"
            shutil.copy2(src_db, work_db)
            kg = DocKG(book_dir, db_path=work_db, lancedb_dir=lance, embedder=embedder)
            kg.store.rebuild_fts(quiet=True)

            queries = list(gold[book])
            if args.phrase_per_book > 0:
                rng = random.Random(f"{args.seed}:{book}")
                queries += generate_phrase_queries(
                    kg, n_queries=args.phrase_per_book, n_words=args.phrase_words, rng=rng
                )
            n_phrase = sum(1 for q in queries if q.mode == "phrase")
            print(
                f"[{bi}/{len(books)}] {book.split('/')[-1]}: "
                f"{len(queries) - n_phrase} gold + {n_phrase} phrase queries"
            )

            real_lexical = kg.store.search_lexical
            for cond in conditions:
                if cond == "dense":
                    kg.store.search_lexical = lambda *_a, **_k: []
                    kgmod._LEXICAL_SEED_BASE_DIST = orig_base
                else:
                    kg.store.search_lexical = real_lexical
                    kgmod._LEXICAL_SEED_BASE_DIST = orig_base if cond == "hybrid" else float(cond)
                for q in queries:
                    t0 = time.perf_counter()
                    qr = kg.query(
                        q.query, k=args.k, hop=args.hop, rels=rels, max_nodes=args.max_nodes
                    )
                    dt = time.perf_counter() - t0
                    retrieved = [str(n.get("id", "")) for n in qr.nodes]
                    hits, recall, rr, ndcg = eval_metrics(retrieved, q.expected_ids, args.max_nodes)
                    rows.append(
                        ResultRow(
                            condition=cond,
                            mode=q.mode,
                            book=book,
                            qid=q.qid,
                            query=q.query,
                            expected_n=len(q.expected_ids),
                            hits=hits,
                            recall=round(recall, 4),
                            mrr=round(rr, 4),
                            ndcg=round(ndcg, 4),
                            seconds=round(dt, 4),
                        )
                    )
            kg.store.search_lexical = real_lexical
            kg.close()
    finally:
        kgmod._LEXICAL_SEED_BASE_DIST = orig_base
        shutil.rmtree(tmp_root, ignore_errors=True)

    for mode in ("gold", "phrase"):
        sel_mode = [r for r in rows if r.mode == mode]
        if not sel_mode:
            continue
        print(f"\n=== {mode} queries ===")
        recall_hdr = f"recall@{args.max_nodes}"
        print(f"{'condition':10s} {'n':>4s} {recall_hdr:>10s} {'mrr':>8s} {'ndcg':>8s}")
        for cond in conditions:
            sel = [r for r in sel_mode if r.condition == cond]
            if not sel:
                continue
            n = len(sel)
            print(
                f"{cond:10s} {n:4d} {sum(r.recall for r in sel) / n:10.4f} "
                f"{sum(r.mrr for r in sel) / n:8.4f} {sum(r.ndcg for r in sel) / n:8.4f}"
            )

    out_prefix = REPO_ROOT / args.out_prefix
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_json = out_prefix.parent / f"{out_prefix.name}_{stamp}.json"
    out_json.write_text(
        json.dumps(
            {
                "meta": {
                    "books_root": str(books_root),
                    "conditions": conditions,
                    "k": args.k,
                    "hop": args.hop,
                    "max_nodes": args.max_nodes,
                    "phrase_per_book": args.phrase_per_book,
                    "phrase_words": args.phrase_words,
                    "seed": args.seed,
                    "base_dist_default": orig_base,
                },
                "rows": [asdict(r) for r in rows],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nper-query rows -> {out_json}")


if __name__ == "__main__":
    main()
