#!/usr/bin/env python3
"""
DocKG × LongMemEval Benchmark
==============================

Evaluates DocKG retrieval against the LongMemEval benchmark.
Goal: 100% retrieval recall, **no inference**.

Architecture (matches the gutenberg_kg pattern):

    prepare  →  one persistent corpus + one DocKG build
    run      →  500 queries against the pre-built KG

Every unique haystack session across all 500 questions is written once as
``<session_id>.md`` under ``benchmarks/data/longmemeval_corpus/``. ``dockg build``
runs a single time, producing a persistent SQLite graph + LanceDB vector index
plus full relational structure: document/section/chunk hierarchy, SIMILAR_TO
edges (cosine ≥ 0.85), HAS_TOPIC, MENTIONS_ENTITY, HAS_KEYWORD, CO_OCCURS_WITH.

Retrieval uses ``DocKG.query`` — the same semantic-seed + graph-expansion path
``pack_docs`` uses. No keyword-overlap rerank, no LLM rerank, no inference.
The graph is the retrieval engine: semantic hits seed the search, and edge
expansion walks to any node that shares a topic, entity, keyword, structural
parent, or similarity edge with a seed. For each question the ranked nodes are
collapsed to session IDs by ``file_path`` and post-filtered to the question's
``haystack_session_ids``.

Usage
-----

Step 0 — download the dataset (one time, ~50 MB):

    python benchmarks/longmemeval_dockg.py prepare /tmp/longmemeval-data/longmemeval_s_cleaned.json --download

Step 1 — prepare corpus + build the KG (one time):

    python benchmarks/longmemeval_dockg.py prepare /tmp/longmemeval-data/longmemeval_s_cleaned.json

    # Rebuild from scratch (after corpus / code changes):
    python benchmarks/longmemeval_dockg.py prepare <data.json> --wipe

Step 2 — run the benchmark (many times — KG is reused):

    python benchmarks/longmemeval_dockg.py run <data.json>
    python benchmarks/longmemeval_dockg.py run <data.json> --limit 20
    python benchmarks/longmemeval_dockg.py run <data.json> --k 50 --hop 2 --max-nodes 500
    python benchmarks/longmemeval_dockg.py run <data.json> --rels CONTAINS,NEXT,SIMILAR_TO,HAS_TOPIC,MENTIONS_ENTITY,HAS_KEYWORD,CO_OCCURS_WITH

All-in-one convenience:

    python benchmarks/longmemeval_dockg.py all <data.json> --limit 20
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Make `src/` importable when running from a source checkout
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))


# =============================================================================
# PATHS
# =============================================================================

CORPUS_DIR = REPO_ROOT / "benchmarks" / "data" / "longmemeval_corpus"
DOCKG_DB = REPO_ROOT / "benchmarks" / "data" / ".dockg" / "graph.sqlite"
DOCKG_LANCEDB = REPO_ROOT / "benchmarks" / "data" / ".dockg" / "lancedb"
DOCKG_EMB_CACHE = REPO_ROOT / "benchmarks" / "data" / ".dockg" / "embeddings.json"


# =============================================================================
# METRICS
# =============================================================================


def dcg(relevances: list[float], k: int) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def ndcg(
    rankings: list[int], correct_ids: set[str], corpus_ids: list[str], k: int
) -> float:
    relevances = [
        1.0 if corpus_ids[idx] in correct_ids else 0.0 for idx in rankings[:k]
    ]
    ideal = sorted(relevances, reverse=True)
    idcg = dcg(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg(relevances, k) / idcg


def evaluate_retrieval(
    rankings: list[int], correct_ids: set[str], corpus_ids: list[str], k: int
) -> tuple[float, float, float]:
    top_k_ids = {corpus_ids[idx] for idx in rankings[:k]}
    recall_any = float(any(cid in top_k_ids for cid in correct_ids))
    recall_all = float(all(cid in top_k_ids for cid in correct_ids))
    nd = ndcg(rankings, correct_ids, corpus_ids, k)
    return recall_any, recall_all, nd


# =============================================================================
# PREPARE — write corpus files + build DocKG
# =============================================================================


def _format_session_markdown(sess_id: str, date: str, turns: list[dict]) -> str:
    """Render a longmemeval session as a Markdown document."""
    lines: list[str] = [
        f"# Session {sess_id}",
        "",
        f"**Date:** {date}",
        "",
    ]
    for turn in turns:
        role = turn.get("role", "user")
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"## {role.capitalize()}")
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_corpus(
    data_file: Path, corpus_dir: Path, force: bool = False
) -> dict[str, str]:
    """Walk the longmemeval JSON and write every unique haystack session to disk.

    Returns a map of ``session_id → file_path`` (as a string, repo-relative).
    """
    with open(data_file) as fh:
        data = json.load(fh)

    corpus_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in corpus_dir.glob("*.md")}

    written = 0
    skipped = 0
    session_files: dict[str, str] = {}

    for entry in data:
        for session, sess_id, date in zip(
            entry["haystack_sessions"],
            entry["haystack_session_ids"],
            entry["haystack_dates"],
        ):
            out_path = corpus_dir / f"{sess_id}.md"
            session_files[sess_id] = str(out_path)
            if not force and sess_id in existing:
                skipped += 1
                continue
            out_path.write_text(_format_session_markdown(sess_id, date, session))
            written += 1
            existing.add(sess_id)

    total = written + skipped
    print(
        f"  Corpus: {total} unique sessions "
        f"({written} written, {skipped} reused) → {corpus_dir}"
    )
    return session_files


def build_kg(
    corpus_dir: Path,
    db_path: Path,
    lancedb_dir: Path,
    wipe: bool = True,
    model: str | None = None,
    workers: int | None = None,
    emb_cache: Path | None = None,
    similar: bool = True,
) -> None:
    """Build a persistent DocKG from the corpus dir.

    When *workers* > 1 (or *emb_cache* is given), uses the two-phase build:
    ``build_graph`` → ``build_embeddings`` (multi-worker) → ``build_index_from_cache``.
    Otherwise falls back to the standard single-process ``build``.
    """
    from doc_kg.kg import DEFAULT_MODEL, DocKG

    use_two_phase = (workers is not None and workers > 1) or emb_cache is not None
    print(f"  Building DocKG ({'wipe' if wipe else 'incremental'}, "
          f"{'two-phase' if use_two_phase else 'standard'})...")
    print(f"    corpus:  {corpus_dir}")
    print(f"    sqlite:  {db_path}")
    print(f"    lancedb: {lancedb_dir}")
    print(f"    model:   {model or DEFAULT_MODEL}")
    if use_two_phase:
        print(f"    workers: {workers or 'auto'}")
        print(f"    emb cache: {emb_cache or DOCKG_EMB_CACHE}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    lancedb_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    kg = DocKG(
        corpus_root=corpus_dir,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
        model=model or DEFAULT_MODEL,
    )
    try:
        if use_two_phase:
            cache_path = emb_cache or DOCKG_EMB_CACHE
            # Skip graph rebuild if SQLite already exists and wipe not requested
            if wipe or not db_path.exists():
                graph_stats = kg.build_graph(wipe=wipe)
                print(
                    f"  Graph:   {graph_stats.total_nodes} nodes, "
                    f"{graph_stats.total_edges} edges"
                )
            else:
                print(f"  Graph:   reusing existing SQLite at {db_path}")
            kg.build_embeddings(out=cache_path, n_workers=workers)
            # Always wipe LanceDB in two-phase mode — embeddings are recomputed
            # fresh so incremental deletes are wasteful and slow.
            stats = kg.build_index_from_cache(cache_path, wipe=True, discover_similar=similar)
        else:
            stats = kg.build(wipe=wipe, discover_similar=similar)
    finally:
        kg.close()
    dt = time.time() - t0

    print(
        f"  Built in {dt:.1f}s → "
        f"{stats.total_nodes} nodes, {stats.total_edges} edges, "
        f"{stats.indexed_rows} indexed rows"
    )


_LONGMEMEVAL_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"
    "/resolve/main/longmemeval_s_cleaned.json"
)


def download_dataset(dest: Path) -> None:
    """Download longmemeval_s_cleaned.json from HuggingFace if not present."""
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading LongMemEval dataset → {dest}")
    print(f"    Source: {_LONGMEMEVAL_URL}")
    urllib.request.urlretrieve(_LONGMEMEVAL_URL, dest)
    print(f"  Downloaded: {dest.stat().st_size / 1_048_576:.1f} MB")


def cmd_prepare(args: argparse.Namespace) -> None:
    data_file = Path(args.data_file).resolve()
    if not data_file.exists():
        if args.download:
            download_dataset(data_file)
        else:
            sys.exit(
                f"ERROR: data file not found: {data_file}\n"
                f"  Download it with:\n"
                f"    python {Path(__file__).name} prepare {args.data_file} --download\n"
                f"  Or manually:\n"
                f"    mkdir -p {data_file.parent}\n"
                f"    curl -fsSL -o {data_file} '{_LONGMEMEVAL_URL}'"
            )

    print("=" * 60)
    print("  DocKG × LongMemEval — PREPARE")
    print("=" * 60)
    print(f"  Source: {data_file}")

    write_corpus(data_file, CORPUS_DIR, force=args.wipe)
    build_kg(
        CORPUS_DIR,
        DOCKG_DB,
        DOCKG_LANCEDB,
        wipe=args.wipe,
        model=args.model,
        workers=getattr(args, "workers", None),
        emb_cache=Path(args.emb_cache) if getattr(args, "emb_cache", None) else None,
        similar=not getattr(args, "no_similar", False),
    )
    print("  Ready. Run with:")
    print(f"    python {Path(__file__).name} run {data_file}")


# =============================================================================
# QUERY — DocKG retrieval + session-level ranking
# =============================================================================


@dataclass
class SessionHit:
    """A single session-level retrieval hit for one query.

    ``rank`` is the position of the best-ranked DocKG node that resolved back
    to this session (lower = better). ``via_node_id`` is that node's stable ID,
    useful when auditing which chunk/topic/entity caused the session to surface.
    """

    session_id: str
    rank: int
    via_node_id: str | None


def _session_id_from_file_path(file_path: str | None) -> str | None:
    """Extract ``<session_id>`` from paths like ``.../<session_id>.md``."""
    if not file_path:
        return None
    stem = Path(file_path).stem
    return stem or None


def query_sessions(
    kg: Any,
    question: str,
    *,
    k: int,
    hop: int,
    rels: tuple[str, ...],
    max_nodes: int,
    haystack: set[str] | None = None,
) -> list[SessionHit]:
    """Run ``DocKG.query`` and collapse its ranked nodes to session-level hits.

    This is the pure DocKG retrieval path: semantic seeding over LanceDB plus
    graph expansion over ``rels`` (CONTAINS / NEXT / SIMILAR_TO / HAS_TOPIC /
    MENTIONS_ENTITY / HAS_KEYWORD / CO_OCCURS_WITH / REFERENCES). No rerank,
    no inference — the graph is the retrieval engine.

    Any ranked node whose ``file_path`` resolves to a session in the current
    question's haystack contributes. The earliest (lowest-ranked) such node
    per session wins.

    :param kg: An open :class:`doc_kg.kg.DocKG` instance.
    :param question: Natural-language query.
    :param k: Semantic seed count (LanceDB top-K before graph expansion).
    :param hop: Graph expansion hops.
    :param rels: Edge types to traverse during expansion.
    :param max_nodes: Cap on ranked nodes returned by ``DocKG.query``.
    :param haystack: If supplied, only sessions in this set are returned.
    :return: Session-level hits sorted by ascending rank (best first).
    """
    result = kg.query(question, k=k, hop=hop, rels=rels, max_nodes=max_nodes)

    best_per_session: dict[str, SessionHit] = {}
    for rank, node in enumerate(result.nodes):
        sess_id = _session_id_from_file_path(node.get("file_path"))
        if sess_id is None:
            continue
        if haystack is not None and sess_id not in haystack:
            continue
        prev = best_per_session.get(sess_id)
        if prev is None or rank < prev.rank:
            best_per_session[sess_id] = SessionHit(
                session_id=sess_id,
                rank=rank,
                via_node_id=node.get("id"),
            )

    return sorted(best_per_session.values(), key=lambda x: x.rank)


# =============================================================================
# BENCHMARK RUNNER
# =============================================================================


def _parse_rels(rels_arg: str | None) -> tuple[str, ...]:
    """Parse a ``--rels`` CLI value ("A,B,C") into a tuple, or default."""
    from doc_kg.store import DEFAULT_RELS

    if not rels_arg:
        return DEFAULT_RELS
    parts = [r.strip() for r in rels_arg.split(",") if r.strip()]
    return tuple(parts) if parts else DEFAULT_RELS


def cmd_run(args: argparse.Namespace) -> None:
    from doc_kg.kg import DocKG

    data_file = Path(args.data_file).resolve()
    if not data_file.exists():
        sys.exit(f"ERROR: data file not found: {data_file}")
    if not DOCKG_DB.exists() or not DOCKG_LANCEDB.exists():
        sys.exit(
            "ERROR: DocKG not found. Run `prepare` first:\n"
            f"  python {Path(__file__).name} prepare {data_file}"
        )

    with open(data_file) as fh:
        data = json.load(fh)

    if args.limit > 0:
        data = data[: args.limit]
    if args.skip > 0:
        data = data[args.skip :]

    rels = _parse_rels(args.rels)

    print("=" * 60)
    print("  DocKG × LongMemEval — RUN")
    print("=" * 60)
    print(f"  Data:        {data_file.name}")
    print(f"  Questions:   {len(data)}")
    print(f"  k (seeds):   {args.k}")
    print(f"  hop:         {args.hop}")
    print(f"  max_nodes:   {args.max_nodes}")
    print(f"  rels:        {','.join(rels)}")
    print("-" * 60)

    kg = DocKG(
        corpus_root=CORPUS_DIR,
        db_path=DOCKG_DB,
        lancedb_dir=DOCKG_LANCEDB,
    )

    ks = [1, 3, 5, 10, 30, 50]
    metrics = {f"recall_any@{k}": [] for k in ks}
    metrics.update({f"recall_all@{k}": [] for k in ks})
    metrics.update({f"ndcg_any@{k}": [] for k in ks})
    per_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    results_log: list[dict] = []
    start = datetime.now()
    misses: list[str] = []

    try:
        for i, entry in enumerate(data):
            qid = entry["question_id"]
            qtype = entry["question_type"]
            question = entry["question"]
            haystack = set(entry["haystack_session_ids"])
            answer_sids = set(entry["answer_session_ids"])

            hits = query_sessions(
                kg,
                question,
                k=args.k,
                hop=args.hop,
                rels=rels,
                max_nodes=args.max_nodes,
                haystack=haystack,
            )

            # Any haystack sessions not surfaced by the graph query go to the tail
            returned = {h.session_id for h in hits}
            tail_start = len(hits)
            tail = [
                SessionHit(
                    session_id=sid,
                    rank=tail_start + offset,
                    via_node_id=None,
                )
                for offset, sid in enumerate(
                    sid for sid in entry["haystack_session_ids"] if sid not in returned
                )
            ]
            ordered = hits + tail

            # Corpus-aligned structures expected by evaluate_retrieval
            corpus_ids = [h.session_id for h in ordered]
            rankings = list(range(len(ordered)))

            entry_metrics: dict[str, float] = {}
            for k in ks:
                ra, rl, nd = evaluate_retrieval(rankings, answer_sids, corpus_ids, k)
                metrics[f"recall_any@{k}"].append(ra)
                metrics[f"recall_all@{k}"].append(rl)
                metrics[f"ndcg_any@{k}"].append(nd)
                entry_metrics[f"recall_any@{k}"] = ra
                entry_metrics[f"ndcg_any@{k}"] = nd

            per_type[qtype]["recall_any@5"].append(metrics["recall_any@5"][-1])
            per_type[qtype]["recall_any@10"].append(metrics["recall_any@10"][-1])
            per_type[qtype]["ndcg_any@10"].append(metrics["ndcg_any@10"][-1])

            r5 = metrics["recall_any@5"][-1]
            r10 = metrics["recall_any@10"][-1]
            status = "HIT" if r5 > 0 else ("MISS" if r10 == 0 else "late")
            if status == "MISS":
                misses.append(qid)
            print(
                f"  [{i + 1:4}/{len(data)}] {qid[:30]:30} "
                f"R@5={r5:.0f} R@10={r10:.0f}  {status}"
            )

            results_log.append(
                {
                    "question_id": qid,
                    "question_type": qtype,
                    "question": question,
                    "answer": entry.get("answer"),
                    "retrieved": [
                        {
                            "session_id": h.session_id,
                            "rank": h.rank,
                            "via_node_id": h.via_node_id,
                        }
                        for h in ordered[: max(ks)]
                    ],
                    "metrics": entry_metrics,
                }
            )
    finally:
        kg.close()

    elapsed = (datetime.now() - start).total_seconds()

    print()
    print("=" * 60)
    print(
        f"  RESULTS — DocKG (k={args.k} hop={args.hop} " f"max_nodes={args.max_nodes})"
    )
    print("=" * 60)
    print(f"  Time: {elapsed:.1f}s ({elapsed / max(len(data), 1):.2f}s per question)")
    print()
    print("  SESSION-LEVEL METRICS:")
    for k in ks:
        ra = sum(metrics[f"recall_any@{k}"]) / len(metrics[f"recall_any@{k}"])
        nd = sum(metrics[f"ndcg_any@{k}"]) / len(metrics[f"ndcg_any@{k}"])
        print(f"    Recall@{k:2}: {ra:.3f}    NDCG@{k:2}: {nd:.3f}")
    print()
    print("  PER-TYPE BREAKDOWN (session recall_any@10):")
    for qtype, vals in sorted(per_type.items()):
        r10 = sum(vals["recall_any@10"]) / len(vals["recall_any@10"])
        n = len(vals["recall_any@10"])
        print(f"    {qtype:35} R@10={r10:.3f}  (n={n})")

    if misses:
        print()
        print(f"  MISSES @10: {len(misses)}/{len(data)}")
        for qid in misses[:20]:
            print(f"    - {qid}")
        if len(misses) > 20:
            print(f"    ... {len(misses) - 20} more")

    print()

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as fh:
            for row in results_log:
                fh.write(json.dumps(row) + "\n")
        print(f"  Results saved to: {out_path}")


def cmd_all(args: argparse.Namespace) -> None:
    cmd_prepare(args)
    print()
    cmd_run(args)


# =============================================================================
# CLI
# =============================================================================


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("data_file", help="Path to longmemeval_s_cleaned.json")
    p.add_argument(
        "--limit", type=int, default=0, help="Limit to N questions (0 = all)"
    )
    p.add_argument("--skip", type=int, default=0, help="Skip first N questions")
    p.add_argument(
        "--k",
        type=int,
        default=50,
        help="Semantic seed count (LanceDB top-K before graph expansion). Default: 50.",
    )
    p.add_argument(
        "--hop",
        type=int,
        default=2,
        help="Graph expansion hops from each seed. Default: 2.",
    )
    p.add_argument(
        "--max-nodes",
        type=int,
        default=1000,
        help=(
            "Cap on ranked nodes returned by DocKG.query. "
            "Must be large enough that the haystack's sessions are covered. Default: 1000."
        ),
    )
    p.add_argument(
        "--rels",
        default=None,
        help=(
            "Comma-separated edge types to traverse during graph expansion. "
            "Default: DocKG DEFAULT_RELS (CONTAINS,NEXT,REFERENCES,SIMILAR_TO,"
            "HAS_TOPIC,MENTIONS_ENTITY,HAS_KEYWORD,CO_OCCURS_WITH)."
        ),
    )
    p.add_argument("--out", default=None, help="Output JSONL file path")


def main() -> None:
    parser = argparse.ArgumentParser(description="DocKG × LongMemEval Benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="Write corpus + build persistent DocKG")
    p_prep.add_argument("data_file", help="Path to longmemeval_s_cleaned.json")
    p_prep.add_argument(
        "--wipe",
        action="store_true",
        help="Rewrite corpus files and rebuild from scratch",
    )
    p_prep.add_argument(
        "--model", default=None, help="Override sentence-transformer model"
    )
    p_prep.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker processes for embedding (enables two-phase build). Default: single-process.",
    )
    p_prep.add_argument(
        "--emb-cache",
        default=None,
        help=f"Path to embedding cache JSON (two-phase build). Default: {DOCKG_EMB_CACHE}",
    )
    p_prep.add_argument(
        "--no-similar",
        action="store_true",
        help="Skip SIMILAR_TO edge discovery (recommended for large corpora >100K chunks)",
    )
    p_prep.add_argument(
        "--download",
        action="store_true",
        help="Download the dataset from HuggingFace if the data file does not exist",
    )
    p_prep.set_defaults(func=cmd_prepare)

    p_run = sub.add_parser("run", help="Query the pre-built DocKG and score results")
    _add_run_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_all = sub.add_parser("all", help="prepare + run in one invocation")
    _add_run_args(p_all)
    p_all.add_argument("--wipe", action="store_true", help="Rebuild the KG")
    p_all.add_argument(
        "--model", default=None, help="Override sentence-transformer model"
    )
    p_all.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker processes for embedding (enables two-phase build). Default: single-process.",
    )
    p_all.add_argument(
        "--emb-cache",
        default=None,
        help=f"Path to embedding cache JSON (two-phase build). Default: {DOCKG_EMB_CACHE}",
    )
    p_all.add_argument(
        "--no-similar",
        action="store_true",
        help="Skip SIMILAR_TO edge discovery (recommended for large corpora >100K chunks)",
    )
    p_all.add_argument(
        "--download",
        action="store_true",
        help="Download the dataset from HuggingFace if the data file does not exist",
    )
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
