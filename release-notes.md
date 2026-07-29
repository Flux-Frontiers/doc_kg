# Release Notes — v0.19.0

> Released: 2026-07-28

DocKG now runs on `transformers` 5. The previous `<4.57` ceiling pinned the stack
to 4.56.2, a release carrying two open high-severity advisories, and this version
lifts it to `>=5.5.0,<6`. The upgrade is invisible to your data: embeddings come
out bitwise identical, an index rebuilt on the new stack is byte-for-byte the same
file, and queries return the same rankings and scores. Nothing needs rebuilding.

## What changed

**The transformers ceiling is gone.** The cap dated from an unrelated commit and
carried no recorded reason; by the time it was examined it no longer matched
anything, since DocKG had already shipped on transformers 5.6.2 back at 0.12.3.
Lifting it clears a remote-code-execution advisory and an arbitrary-code-execution
advisory in the model-loading path. Because the old and new ranges do not overlap,
this is a breaking dependency change — an environment pinned to transformers 4.x
cannot install this release. `huggingface-hub` moves to 1.x along with it.

**Embeddings were verified unchanged, not assumed unchanged.** Three models were
checked across awkward inputs — empty strings, whitespace, three-thousand-character
blocks, unicode and emoji, CRLF line endings — and every vector matched bit for
bit. A full rebuild of a 2847-vector corpus reproduced an identical vector store,
and queries run against an index built under the old stack returned identical
results under the new one.

**A silent embedder bug went with it.** `transformers` 5 removed the
`transformers.logging` submodule alias. The shared embedder imported it by name,
and the resulting `ModuleNotFoundError` was swallowed by a broad `except`, so log
and progress-bar suppression quietly stopped working while appearing fine. The fix
ships in `kgmodule-utils` 0.9.0, which this release now requires — the floor
matters, because the old version's constraints would otherwise have let the
resolver keep it.

**The `kgdeps` extra has been removed.** DocKG and PyCodeKG each listed the other
as an optional dependency, which meant neither could resolve a relaxed pin until
the other had already been published — a deadlock with no first move. Since
neither package actually imports the other, the dependency was removed rather than
sequenced around.

## Upgrading

Existing corpora need no attention. There is no migration, no re-index, and no
change to the vector store format — the same corpus produces the same file before
and after.

The one thing to check is your environment. If you hold `transformers` at 4.x for
another package, that pin now conflicts and must be resolved before upgrading. And
if you installed via `pip install 'doc-kg[kgdeps]'`, that extra no longer exists;
install the sibling directly with `pip install pycode-kg` instead.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
