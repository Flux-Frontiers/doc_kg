# ufo-knowledge-base vs. DocKG — Analysis & Implementation Plan

**Date:** 2026-07-02
**Author:** Eric G. Suchanek, PhD (with Claude)
**Subject:** What [zvizdo/ufo-knowledge-base](https://github.com/zvizdo/ufo-knowledge-base)
teaches us, and a concrete plan to adopt its two best ideas into DocKG.

---

## 1. What zvizdo built

It is **not** a RAG pipeline — it is a *curated ontology / second brain*, and it
inverts almost every default of a system like DocKG.

- **The graph IS the files.** 2,584 plain-Markdown pages with YAML frontmatter and
  `[[wikilinks]]` (27,220 of them). No vector DB as source of truth, no derived
  SQLite. The corpus *is* the graph — human-readable, git-versionable, auditable.
  NetworkX is used only for viz/traversal.

- **Transcripts are decomposed, not chunked.** A YouTube transcript is shredded
  into *typed entity pages* — people (1,050), organizations, incidents,
  claim-theses — each with required sections and mandatory links
  (`Every entity page MUST link to ≥1 concept page`). The transcript survives only
  as a "per-source claim summary" pointing into the entity graph. The meaning lives
  in the **edges**, not in a vector.

- **Vector search is deliberately demoted to "cold seed-finding."** The rule, verbatim:
  > "Vector search (qmd) is allowed *only* for cold seed-finding when no slug/alias
  > resolves. Once on the graph, traversal is the sole grounding mechanism."

  Resolution order: exact slug/alias → substring → fuzzy → *only then* embeddings.

- **Answers are traced paths with quoted lines.** The `kb-query` skill enforces:
  *"If you can't trace a claim to a path, you can't make the claim."* Output is
  `[[A]] → [[B]] → [[C]]` with the exact source line where each link appears
  (`linearize-path.py`). Contradictions are first-class (`⚠ Conflict:` callouts);
  "gap" queries are a supported mode.

- **The LLM does ingestion; Python just fetches.** `youtube_import.py` only pulls
  captions (`yt-dlp`), strips VTT timestamps, dedups rolling-window caption repeats,
  and stages Markdown. All extraction/linking/dedup is delegated to Claude via
  `/kb-import`, governed by a `CONSTITUTION.md` schema, with a **single persistent
  Claude session** across files for consistency. Link *prediction* (Jaccard,
  Adamic-Adar, common neighbors) proposes non-obvious edges.

---

## 2. How this contrasts with DocKG

| Dimension        | zvizdo ufo-kb                      | DocKG                                          |
|------------------|-----------------------------------|------------------------------------------------|
| Source of truth  | Markdown + wikilinks (the graph)  | Documents; SQLite+LanceDB are **derived**      |
| Unit of knowledge| Typed entity/claim page           | Chunk / section / topic / entity               |
| Vector role      | Last-resort seed-finder           | Primary ranker (ANN over chunks)               |
| Grounding        | Traversal path + quoted line      | Semantic similarity + hop expansion            |
| Ingestion        | LLM-curated per source            | Automated embed + inferred edges               |
| Edges            | Human/LLM-authored `[[links]]`    | Mostly inferred (semantic/structural)          |
| Scales to        | Thousands of curated pages        | Large corpora, cheaply, automatically          |

The two sit at opposite ends of a precision/recall/cost triangle. His wins on
**trust and precision** (every claim traceable, contradictions surfaced) but is
**expensive and slow to build** and recall-bounded by curation. DocKG wins on
**scale and automation** but retrieval is fuzzier and far less auditable —
`pack_docs` hands back chunks, not a defensible chain of reasoning. They are
complementary, not competing.

---

## 3. What to borrow — ranked by value/effort

1. ~~**Honor explicit `[[wikilinks]]` as first-class edges.**~~ *(dropped — see note below)*
2. **Traversal-grounded answers with quoted-path provenance.** (High value, medium effort.) **✅ SHIPPED — see §4.**
3. Seed-then-traverse retrieval mode (vector picks the entry node only).
4. Entity-decomposition ingestion profile for transcript corpora (DiaryKG convergence).
5. Per-corpus schema "constitution" + `dockg audit` validator.
6. Link prediction (Adamic-Adar / common-neighbors) to suggest missing edges.
7. Contradiction detection as first-class output (`⚠ Conflict`).

> **Note on #1 (dropped).** The corpus contains no `[[wikilinks]]`, so authoring a
> wikilink-parsing path was an abstract exercise. DocKG already has the general
> "links" concept: markdown `[text](href)` hyperlinks become `REFERENCES` edges.
> More importantly, **#2 turned out not to depend on #1 at all** — path provenance
> rides on the edges DocKG already builds (`CONTAINS`, `NEXT`, `REFERENCES`,
> `SIMILAR_TO`, `MENTIONS_ENTITY`, …) plus the exact source offsets every chunk
> already carries. Wikilinks would only add a second *syntax* feeding the same
> `REFERENCES`-style idea; revisit only if a curated corpus starts using them.

**One-line takeaway:** he proved that *for a corpus you care about, a
human/LLM-authored wikilink graph with traversal-grounded, path-cited answers
beats pure semantic retrieval on trust.* DocKG shouldn't drop its automated scale
— it should grow a traversal-grounded, quoted-provenance answer layer on top of it,
and treat explicit links as the on-ramp from "indexed" to "curated."

---

## 4. Implementation plan

### Current architecture (verified via pycodekg, 2026-07-02)

```
corpus → parse_corpus (dockg.py)        # nodes + edges
          ├─ TextChunker.chunk          # chunker.py — emits chunk dicts
          │    └─ _extract_links        # captures [text](href) + [label]: href → chunk["references"]
          ├─ _resolve_reference         # href → corpus doc path → REFERENCES edge
       → GraphStore (store.py, SQLite)  # edges(src, rel, dst, evidence JSON)
       → SemanticIndex (index.py, LanceDB)
query/pack → DocKG.query / DocKG.pack (kg.py)
          ├─ _fused_seeds               # RRF(dense LanceDB + lexical FTS5)
          ├─ GraphStore.expand          # BFS, returns {id: ProvMeta(best_hop, via_seed)}
          └─ TextPack.to_markdown       # nodes + flat edge list (no paths)
```

One fact makes provenance nearly free:
- `DocKG.pack` **already fetches the full expanded subgraph** (`all_edges =
  self.store.edges_within(all_ids)`), and every chunk node already carries `text` +
  `file_path` + `char_start`/`char_end`. `REFERENCES` edges carry
  `evidence={"href": …}` and `SIMILAR_TO` edges carry `evidence={"similarity": …}`.
  So path tracing rides entirely on data already in hand.

---

### #2 — Quoted-path provenance in `pack` — ✅ SHIPPED (branch `feat/traced-provenance`)

**Goal:** turn `pack_docs` from "here are similar chunks" into
`seed → … → node` with the exact source line at each hop — zvizdo's grounding
contract, opt-in so the default output is byte-identical.

**Key simplification vs. the original plan.** The first draft proposed adding
parent pointers to `GraphStore.expand` (a `ProvMeta.parent` slot + a modified
per-hop UNION query). That touches the performance-sensitive traversal loop and
would need a benchmark pass. **It proved unnecessary.** Because `pack` already has
the full expanded edge set, path reconstruction is a *pure post-processing step* —
a small multi-source BFS in Python over `all_edges`, run only when `traced=True`.
No `expand()` change, no `ProvMeta` change, no schema change, **and no rebuild** —
it works on the existing `.dockg` graph immediately.

**As built** (all in `kg.py` unless noted):

1. **`_trace_paths(seed_ids, node_map, edges, targets)`** — builds undirected
   adjacency from the already-fetched `all_edges`, runs a multi-source BFS from the
   seeds (matching `expand`'s bidirectional traversal), records a parent + the
   connecting edge per node, then walks parents back to the nearest seed for each
   returned node. Unreachable targets are omitted; a seed maps to a single-step
   path.
2. **`_hop_label(rel, evidence)`** — human-readable hop labels
   (`"similar to (0.91)"`, `"links to (other.md)"`, `"contains"`, `"mentions"`, …).
3. **`_node_quote(node)`** — first sentence of the node's source text, capped at
   160 chars, with a `file_path:char_start` citation. Structural/semantic nodes
   with no text fall back to their title.
4. **`_render_path(path)`** — renders the arrow chain
   (`` `A` → `B` → `C` ``) plus a quoted line per hop.
5. **`TextPack.paths`** — new optional field (`dict[str, list[dict]] | None`);
   serialized by `to_dict`/`to_json` and rendered by `to_markdown` **only when
   present**, so untraced output is unchanged.
6. **Opt-in flag** — `DocKG.pack(..., traced=False)`; threaded through the MCP
   `pack_docs` tool (`mcp_server.py`) and the `dockg pack --traced` CLI flag
   (`cli/cmd_query.py`).

**Tests** — `tests/test_traced_pack.py` (9 tests): the pure helpers
(`_hop_label`, `_node_quote`, `_trace_paths` reconstruct / seed-single-step /
unreachable-omitted, `_render_path`) plus integration (`pack(traced=True)` attaches
a path to every returned node; `to_dict`/`to_markdown` carry it; untraced pack is
unchanged). Full suite: **421 passed, 1 skipped**; ruff + format clean.

**Live output** (`dockg pack "knowledge graph architecture" --hop 2 --traced`):

```
### chunk — `Citation`   (README.md, offset 9058–9343)
- provenance: `Hybrid Knowledge Graph` → `Citation`
    - seed: `Hybrid Knowledge Graph`
    - mentions: "If you use DocKG in research or a project, please cite it…"  (README.md:9058)
```

DocKG grounds *harder* than zvizdo here: it cites exact character offsets into real
source files rather than a whole page.

**Known rough edge.** `MENTIONS_ENTITY` renders as "mentions" while the traversal
runs entity→chunk (the chunk mentions the entity, so the label direction is
slightly reversed). Informative as-is; a direction-aware label table is the fix if
it bothers.

---

### Out of scope (future)
- Seed-then-traverse ranking mode (#3) reuses the same `_trace_paths` machinery; the
  `traced` flag is the natural seam to add a `grounded=True` ranking variant later.
- Wikilink edges (former #1) remain deferred until a corpus actually uses `[[…]]`.
