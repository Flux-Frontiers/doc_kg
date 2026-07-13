# Release Notes — v0.17.0

> Released: 2026-07-13

DocKG 0.17.0 makes a text pack **explain itself**: `pack(..., traced=True)` attaches a
`seed → … → node` provenance path to every returned node, with a quoted source line and a
`file_path:char_start` citation at each hop — turning "here are similar chunks" into a
traceable chain of *why* each result surfaced. Tracing is reconstructed from edges the
pack already fetches, so it adds no extra queries, no schema change, and **no rebuild**;
untraced output is byte-identical. The release also consolidates the embedding pipeline
into `kgmodule-utils` and hardens long builds against the memory blowups seen on
multi-hundred-thousand-node corpora.

## What changed

**Traced provenance in `pack`.** Available everywhere packs are made: the Python API
(`DocKG.pack(traced=True)`), the MCP tool (`pack_docs(traced=...)`), and the CLI
(`dockg pack --traced`). Each hop is labeled with its relation ("similar to (0.91)",
"links to (other.md)", "contains", "mentions") and grounded in a quoted line from the
source document, in the spirit of traversal-grounded, path-cited answering.

**One canonical corpus embedder.** `CorpusEmbedder`/`EmbeddingCache` had been forked into
sibling KG projects, and the device-pinning and shard-recycling fixes from 0.15.9 never
propagated to the copies. The implementation now lives in `kgmodule-utils` (≥0.4.9) as
`kg_utils.corpus_embedder`; `doc_kg.embedder_worker` re-exports it, so existing imports
keep working unchanged.

**Memory-safe long builds.** The encode batch in `SemanticIndex.build()` is hard-capped at
128 (throughput is flat above that on CPU and MPS, while a 1024 batch on long chunks
allocates several GB per encode call), and mid-run embedder reloads are gone — they
discarded caller-shared embedders and risked a second-load SIGBUS on MPS. Embedding-cache
precompute now routes by device: GPU stays single-process, while CPU streams shard-by-shard
through the multi-process `CorpusEmbedder.embed_to_cache()`, so peak memory scales with
shard size rather than corpus size.

## Upgrading

No action required — no schema change and no index rebuild. Existing `.dockg` graphs gain
`traced=True` immediately. `kgmodule-utils>=0.4.9` is pulled in automatically on install.
If you had tuned `--encode-batch` above 128, note it is now clamped; the cap is deliberate
and costs no throughput.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
