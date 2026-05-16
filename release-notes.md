# Release Notes — v0.15.0

> Released: 2026-05-16

### Added
- `src/doc_kg/cli/cmd_build.py`: Three new commands: `build-embeddings` (SQLite → embedding cache JSON/JSONL, gzip-capable), `build-index-from-cache` (cache → LanceDB without model inference), and `build-two-phase` (stable end-to-end pipeline using cache as intermediary). `build-index` gains `--device` (auto/cpu/mps/cuda) and `--index-kind` (repeatable, restricts embedded node kinds) options.
- `src/doc_kg/index.py`: `make_embedder()` factory function with `device` override; `build()` now streams nodes via `store.iter_nodes()` (avoids loading all node dicts into RAM) and pre-allocates a contiguous `(n_chunks × dim)` float32 ndarray for the SIMILAR_TO ANN pass; `_discover_similar_edges()` signature updated to accept separate `chunk_ids` + `chunk_vecs` arrays; `_is_jsonl_cache()` and `_open_text_auto()` helpers for cache I/O.
- `src/doc_kg/store.py`: `count_nodes()` — fast kind-filtered row count used for progress bars and pre-allocation; `iter_nodes()` — batch generator that streams node dicts without holding the full result set in RAM; `query_nodes()` gains `limit` and `offset` parameters for pagination.
- `src/doc_kg/chunker.py`: `VerseChunker` — new chunker for `chapter:verse`-structured sacred texts (KJV Bible, Quran, etc.). Auto-detects verse documents via `is_verse_document()` (>10% of non-blank lines match `^\d+:\d+\s`), skips TOC preambles, splits by book sections, enforces chapter boundaries, and emits chunk dicts with `content_type`, `book`, `chapter`, `verse_start`, `verse_end` metadata. Added `"verse"` strategy to `chunker_for()`.
- `src/doc_kg/discover_topics.py`: New `discover_topics()` function — corpus-driven topic discovery via K-means on chunk embeddings + within-cluster TF-IDF scoring. Writes a human-readable YAML catalog (`{cluster_NN: [kw, ...]}`) and a fitted `*.kmeans.joblib` model for embedding-based topic assignment during `build-graph`.
- `src/doc_kg/sacred_texts_topics.yaml`: Built-in 12-topic catalog for sacred-text corpora (Creation, Covenant, Law, Prophecy, Gospel, Epistle, Wisdom, Lament, Praise, Narrative, Apocalyptic, Ethics) with multi-word and single-word keywords.
- `src/doc_kg/dockg.py`: `parse_corpus()` gains `kmeans_model_path` and `topics_file_map` parameters. When `kmeans_model_path` is set, all chunks are batch-embedded per file and assigned to the nearest K-means centroid (near-100% topic coverage, overrides keyword matching). `topics_file_map` enables per-path topic catalog routing (first prefix match wins).
- `src/doc_kg/entry_chunk.py`: `SourceProvenance` gains five new optional fields: `content_type`, `book`, `chapter`, `verse_start`, `verse_end`; mirrored in `EntryChunk.to_node_dict()`.
- `src/doc_kg/store.py`: SQLite schema extended with five verse columns (`content_type TEXT`, `book TEXT`, `chapter INTEGER`, `verse_start INTEGER`, `verse_end INTEGER`). Includes `ALTER TABLE` migration for existing databases. All INSERT/SELECT/UPSERT statements updated to 14 columns.
- `src/doc_kg/cli/cmd_build.py`: `build` and `build-graph` gain `--chunk-strategy [semantic|sentence_group|fixed|verse]`, `--kmeans-model FILE`, and `--topics-prefix PREFIX=FILE` (repeatable) options. `_parse_topics_prefix()` helper parses the `PREFIX=FILE` pairs.
- `src/doc_kg/cli/cmd_pipeline.py`: New `dockg pipeline discover-topics` command — wraps `discover_topics()` with full Click decorator stack (`--n-clusters`, `--n-keywords`, `--chunk-strategy`, `--sentences`, `--model`, `--quiet`).
- `tests/test_verse_chunker.py`: 21 tests across 6 test classes covering `VerseChunker` detection, TOC skipping, chapter boundary enforcement, book section parsing, multi-book corpora, and `chunker_for("verse")` integration.
- `docs/verse_workflow.md`: New comprehensive verse ingestion workflow guide with five-phase pipeline walkthrough, actual KJV Bible benchmark numbers, k-selection guidance, verse chunk schema reference, per-path override patterns, and troubleshooting section. Includes infographic image-generation prompt.
- `docs/pipeline_visual.md`: New pipeline visual reference document.
- `assets/dockg_pipeline.png`: Pipeline architecture diagram asset.

### Changed
- `src/doc_kg/dockg.py`: `DocNode` dataclass gains five optional fields (`content_type`, `book`, `chapter`, `verse_start`, `verse_end`). `parse_corpus()` auto-detects verse documents and switches to `VerseChunker` when the file qualifies. Lazy chunker import expanded to include `TextChunker` and `SentenceGroupChunker` for correct mypy type annotations.
- `src/doc_kg/graph.py`: `DocGraph.__init__()` gains `kmeans_model_path` parameter; threaded through to `parse_corpus()` call in `extract()`.
- `src/doc_kg/kg.py`: `DocKG.__init__()` gains `kmeans_model_path` and `device` parameters; lazy `embedder` property now calls `make_embedder()` with device; `build_embeddings()` and `build_index_from_cache()` methods added.
- `src/doc_kg/cli/cmd_build.py`: `build-index` default LanceDB write batch size raised 256 → 8192 (fewer LanceDB fragments, faster scan on large tables).
- `src/doc_kg/embedder_worker.py`: Embedding cache supports gzip compression (`.json.gz`, `.jsonl.gz`); JSON serialized with compact separators (`ensure_ascii=False`) to reduce file size by ~20%.
- `src/doc_kg/pipeline.py`: `_phase2_chunk()` annotation updated to `TextChunker | SentenceGroupChunker | VerseChunker`; `VerseChunker` added to import.
- `src/doc_kg/topics.py`: `TopicExtractor.classify()` multi-word keyword fix — single-word keywords use set lookup on tokenized words; multi-word keywords use substring search on lowercased text (was broken: all multi-word phrases silently missed).
- `docs/CHEATSHEET.md`: New Section 9 — Verse Corpus Ingestion with condensed workflow, coverage comparison table, and link to `verse_workflow.md`. Section 10 (Multipass Pipeline) and Section 11 (Live Stats) renumbered. Node kinds table updated to include `.rst` and `.pdf` file types.
- `.dockg/snapshots/manifest.json`: Snapshot updated.
- `.claude/plans/verse-ingestion.md`: Implementation plan saved.

### Removed

### Fixed
- `src/doc_kg/discover_topics.py`: `import yaml` annotated with `# type: ignore[import-untyped]` (consistent with `topics.py`); `ck` variable given explicit union type annotation to satisfy mypy.
- `src/doc_kg/index.py`: Removed leftover `DEBUG` `print` statement from `index_nodes()` that was leaking to stderr during every build.

### Performance
- `src/doc_kg/index.py`: `_discover_similar_edges()` rewritten to use LanceDB HNSW ANN queries instead of batched numpy matmul. The old approach allocated an `(n_chunks × dim)` matrix for all nodes plus a `(row_batch × n_chunks)` temporary similarity matrix per batch — for 400 K chunks the temp alone reached ~1.6 GB, causing OOM on large sacred-text corpora. The new approach queries LanceDB for each chunk's top-k nearest neighbours via the existing HNSW index; peak RAM is O(n_chunks × dim) with no N×N allocation. `build()` and `index_nodes()` no longer pre-allocate `all_vecs_np`; instead they accumulate `chunk_pairs: list[tuple[str, vec]]` for chunk nodes only (smaller than the full node set). SQLite PRIMARY KEY on `(src, rel, dst)` continues to deduplicate edges emitted by both A→B and B→A ANN results.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
