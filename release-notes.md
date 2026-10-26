# Release Notes -- v0.29.0

> Released: 2026-10-25

DocKG's MCP server now runs on the fleet's shared base, `kg_utils.mcp`, so it
answers the same five tools under the same names as every other KG server:
`stats`, `query`, `pack`, `get_node` and `neighbors`. LanceDB support is gone;
the vector index is a single sqlite-vec file. Both changes break existing MCP
configs and some Python callers, so read Upgrading before you install.

## What changed

**One MCP vocabulary across the fleet.** `graph_stats`, `query_docs` and
`pack_docs` are now `stats`, `query` and `pack`, with no aliases, and the new
`neighbors` tool walks one node's edges without loading the embedding model.
`query` and `pack` keep DocKG's own hybrid search; `pack` still sizes excerpts
by `max_chars`. The server's instructions are generated from the tools'
docstrings, and `dockg mcp --manifest` prints the tool list without opening a
graph.

**One command, standard flags.** `dockg mcp` and `dockg-mcp` are the same
command, with the fleet's `--repo`, `--db`, `--vectors`, `--model`,
`--transport stdio|streamable-http`, `--host`, `--port` and `--manifest`. The
graph opens per session and closes after, a corpus with no graph is refused
instead of served empty, and stray output can no longer corrupt the stdio
stream.

**Statistics in the fleet shape.** `DocKG.stats()` returns `kind`, `nodes`
(`total`, `by_kind`) and `edges` (`total`, `by_rel`), plus `vector_backend` and
`vector_count`, the shape KGRAG and every other module read.

**sqlite-vec only.** `dockg convert-index`, the `[lancedb]` extra and the
LanceDB options are removed. The vector store is
`<corpus>/.dockg/vectors.sqlite`.

## Upgrading

Rename the tools in any agent instructions or scripts (`graph_stats` ->
`stats`, `query_docs` -> `query`, `pack_docs` -> `pack`), pass `rels` as a list,
and rename `--vectors-path` to `--vectors` in MCP configs. Code that read
`DocKG.stats()["node_count"]` reads `["nodes"]["total"]` instead. A corpus that
still has only a `.dockg/lancedb` directory needs `dockg build` (or
`dockg build-index`). doc-kg now needs kgmodule-utils 0.29.0, whose `[mcp]`
extra brings the MCP SDK.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
