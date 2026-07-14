#!/usr/bin/env python3
"""
ann_recall_bench.py
===================

Index-fidelity benchmark for the row-count-gated IVF index in
:class:`doc_kg.index.SemanticIndex` (branch ``feat/ann-index-gate``).

The embedding model and the cosine ranking are unchanged by the index work —
the *only* thing the IVF index changes is **which** vectors get scored.  So the
correct validation is not gold-label recall (the gold set was built against the
per-book indices and its chunk numbering does not map onto the re-chunked
bundle), but **fidelity to the exact flat scan**: for the same real queries on
the same corpus, how much of the exact top-k does the IVF index reproduce?

Ground truth is a brute-force cosine scan over the full vector matrix loaded
from the table.  The candidate is the *production* search path,
:meth:`SemanticIndex.search`, exercised at several ``nprobes`` settings.  Query
texts are the real human queries from the gutenberg_kg gold CSV (their labels
are ignored; only the query strings are used).

Nothing is modified: the LanceDB table is opened read-only and the matrix is
loaded once for the exact baseline.

Usage
-----

    PYTHONPATH=src python benchmarks/ann_recall_bench.py \\
        --lancedb ../gutenberg_kg/bundles/gutenberg-all/.dockg/lancedb \\
        --gold ../gutenberg_kg/analysis/similar_to_query_template.csv \\
        --nprobes 10,20,50,100 --k 10

Author: Eric G. Suchanek, PhD
License: Elastic-2.0
Last Revision: 2026-06-24
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from doc_kg.index import SemanticIndex, make_embedder

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LANCEDB = (
    REPO_ROOT.parent / "gutenberg_kg" / "bundles" / "gutenberg-all" / ".dockg" / "lancedb"
)
DEFAULT_GOLD = REPO_ROOT.parent / "gutenberg_kg" / "analysis" / "similar_to_query_template.csv"


@dataclass
class CondResult:
    """Aggregated fidelity/latency for one (nprobes, refine) condition."""

    nprobes: int
    refine: int
    n_queries: int
    fidelity_at_k: float  # mean |ANN∩exact| / k  — overlap with exact top-k
    top1_retention: float  # fraction of queries where exact's #1 is in ANN top-k
    full_recall_rate: float  # fraction of queries with fidelity == 1.0
    p50_ms: float
    p90_ms: float


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--lancedb", default=str(DEFAULT_LANCEDB), help="LanceDB dir of the indexed bundle."
    )
    p.add_argument(
        "--gold", default=str(DEFAULT_GOLD), help="CSV with a query_text column (real queries)."
    )
    p.add_argument("--table", default="dockg_nodes", help="LanceDB table name.")
    p.add_argument("--k", type=int, default=10, help="Top-k cutoff for fidelity.")
    p.add_argument(
        "--nprobes", default="10,20,50,100", help="Comma-separated nprobes settings to sweep."
    )
    p.add_argument(
        "--refine", type=int, default=0, help="refine_factor (0 = off; FLAT needs none)."
    )
    p.add_argument("--repeats", type=int, default=3, help="Timed repeats per query (min kept).")
    p.add_argument(
        "--out-prefix",
        default="benchmarks/data/ann_recall_bench",
        help="Output JSON prefix relative to the doc_kg repo root.",
    )
    return p.parse_args()


def load_query_texts(csv_path: Path) -> list[str]:
    """Return de-duplicated, non-empty ``query_text`` strings from the gold CSV."""
    seen: set[str] = set()
    out: list[str] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            q = (r.get("query_text") or "").strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                out.append(q)
    return out


def load_matrix(tbl) -> tuple[list[str], np.ndarray]:
    """Load all (id, vector) rows and L2-normalise the vectors for exact cosine."""
    arr = tbl.to_arrow()
    ids = arr.column("id").to_pylist()
    v = np.asarray(arr.column("vector").to_pylist(), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
    return ids, v


def exact_topk(qv: np.ndarray, ids: list[str], mat: np.ndarray, k: int) -> list[str]:
    """Brute-force exact cosine top-k (descending similarity)."""
    sims = mat @ qv
    top = np.argpartition(-sims, k)[:k]
    top = top[np.argsort(-sims[top])]
    return [ids[i] for i in top]


def main() -> None:
    """Run the ANN-vs-exact fidelity sweep and print a summary."""
    args = parse_args()
    lancedb_dir = Path(args.lancedb).resolve()
    queries = load_query_texts(Path(args.gold).resolve())
    nprobes_list = [int(x) for x in args.nprobes.split(",") if x.strip()]

    embedder = make_embedder()
    index = SemanticIndex(lancedb_dir, embedder=embedder, table=args.table)
    tbl = index._lance_table()
    indices = tbl.list_indices()
    print(f"corpus rows : {tbl.count_rows():,}")
    print(f"index       : {indices}")
    print(f"queries     : {len(queries)} real query texts")
    if not indices:
        print("WARNING: no vector index present — ANN == flat scan (fidelity will be 1.0).")

    print("loading full matrix for exact baseline (one-time) ...")
    t0 = time.perf_counter()
    ids, mat = load_matrix(tbl)
    qvecs = [np.asarray(embedder.embed_query(q), dtype=np.float32) for q in queries]
    qvecs = [v / (np.linalg.norm(v) + 1e-9) for v in qvecs]
    gold_topk = [set(exact_topk(v, ids, mat, args.k)) for v in qvecs]
    gold_top1 = [exact_topk(v, ids, mat, 1)[0] for v in qvecs]
    print(f"  baseline ready in {time.perf_counter() - t0:.1f}s")

    results: list[CondResult] = []
    per_query: list[dict] = []
    for nprobes in nprobes_list:
        index.ann_nprobes = nprobes
        index.ann_refine_factor = args.refine
        index._has_ann = bool(indices)  # force the probe path on the real search()

        fids: list[float] = []
        top1: list[int] = []
        lats: list[float] = []
        for q, gset, g1 in zip(queries, gold_topk, gold_top1):
            best = float("inf")
            got: list[str] = []
            for _ in range(max(1, args.repeats)):
                s = time.perf_counter()
                hits = index.search(q, k=args.k)
                dt = (time.perf_counter() - s) * 1000.0
                if dt < best:
                    best = dt
                got = [h.id for h in hits]
            ann = set(got)
            fid = len(gset & ann) / max(args.k, 1)
            fids.append(fid)
            top1.append(1 if g1 in ann else 0)
            lats.append(best)
            per_query.append(
                {
                    "nprobes": nprobes,
                    "query": q,
                    "fidelity": round(fid, 3),
                    "top1_kept": top1[-1],
                    "ms": round(best, 2),
                }
            )

        lat_sorted = sorted(lats)
        results.append(
            CondResult(
                nprobes=nprobes,
                refine=args.refine,
                n_queries=len(queries),
                fidelity_at_k=round(float(np.mean(fids)), 4),
                top1_retention=round(float(np.mean(top1)), 4),
                full_recall_rate=round(
                    float(np.mean([1.0 if f >= 0.999 else 0.0 for f in fids])), 4
                ),
                p50_ms=round(lat_sorted[len(lat_sorted) // 2], 2),
                p90_ms=round(lat_sorted[min(len(lat_sorted) - 1, int(len(lat_sorted) * 0.9))], 2),
            )
        )

    print(f"\n=== ANN fidelity vs exact flat scan (k={args.k}, refine={args.refine}) ===")
    print(
        f"{'nprobes':>7s} {'fidelity@k':>11s} {'top1_kept':>10s} {'full@k':>8s} {'p50_ms':>8s} {'p90_ms':>8s}"
    )
    for r in results:
        print(
            f"{r.nprobes:7d} {r.fidelity_at_k:11.3f} {r.top1_retention:10.3f} "
            f"{r.full_recall_rate:8.3f} {r.p50_ms:8.2f} {r.p90_ms:8.2f}"
        )

    out_prefix = REPO_ROOT / args.out_prefix
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_json = out_prefix.parent / f"{out_prefix.name}_{stamp}.json"
    out_json.write_text(
        json.dumps(
            {
                "meta": {
                    "lancedb": str(lancedb_dir),
                    "table": args.table,
                    "index": str(indices),
                    "k": args.k,
                    "refine": args.refine,
                    "n_queries": len(queries),
                    "rows": tbl.count_rows(),
                },
                "conditions": [asdict(r) for r in results],
                "per_query": per_query,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nrows -> {out_json}")


if __name__ == "__main__":
    main()
