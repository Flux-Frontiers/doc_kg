# Release Notes — v0.21.0

> Released: 2026-08-03

**`pandas` is no longer a dependency of DocKG — and neither are `markdown-it-py`
or `einops`.** None of the three was ever imported: not in `src/`, not in
`tests/`, not in `benchmarks/`. Because they were declared *core*, every install
of `doc-kg` — and of every package that depends on it — paid for them anyway.
This release makes the declared dependency set match the code in both
directions: nothing is declared that is never imported, and nothing is imported
that is not declared. It is a packaging release; there are no behavioural
changes to indexing, querying, or the CLI.

## What changed

**Three core dependencies removed.** `pandas` is the one that matters — it is
heavy, it was core, and it propagated to every downstream KG in the fleet.
`markdown-it-py` was never imported either; it is a hard requirement of `rich`
(`>=2.2.0`) so it remains installed regardless, and what actually disappears is
an undocumented floor-raise to `>=3.0.0` on a package we do not use. `einops`
was added back in 0.9.0 for `nomic-embed-text-v1` and is reachable only when
`dockg model` is pointed at a `nomic-ai/*` model with `trust_remote_code`; the
default model is bge-small, so it was dead weight for essentially every install.

**Three imports that were never declared now are.** DocKG imported `tqdm`,
`joblib` and `torch` directly while relying on other packages to supply them.
`tqdm` (progress-bar suppression in `index.py`) is now core; `joblib` (K-means
model persistence in `discover_topics.py` and `dockg.py`) joins `scikit-learn`
in the `[analysis]` extra. This is the reasoning already written down in
`pyproject.toml` for `scikit-learn` itself, finally applied consistently.

**The semantic stack moved to `kgmodule-utils[semantic]>=0.10.0`.** `numpy`,
`sentence-transformers`, `sqlite-vec` and `transformers` were pinned both here
and in KG_utils — two files that could silently drift apart on every bump. They
now come from the extra, matching what pycode-kg already does. The trade-off is
recorded in `pyproject.toml`: those packages become a contract of `[semantic]`,
so a change to its contents changes DocKG's direct imports with it.

**`torch>=2.5.1` is finally constrained**, as a consequence of that move. DocKG
imports `torch` directly for MPS/CUDA cache eviction but never declared it, so
resolution was governed by `sentence-transformers`' far looser `torch>=1.11.0`.
Every sibling that imports torch already declared `>=2.5.1`; doc-kg was the
outlier. In the same spirit, the `rich` floor rises to `>=14.3.3,<15` from
`>=13.0.0,<15.0.0` — deliberately above what `[semantic]` carries, because
doc-kg was the one package in the fleet whose clean install could still resolve
rich 13.x.

## Upgrading

For most users this is `pip install --upgrade doc-kg` and nothing else. No
rebuild, no migration, no configuration change — the graph, the index, and every
CLI surface are untouched.

The one thing to check: **if your code imported `pandas` and got it for free
because DocKG declared it, declare it yourself.** That is the only way this
release can break you, and it is why this is a minor bump rather than a patch.
The same applies, far less likely, to `markdown-it-py` at `>=3.0.0` and to
`einops` — if you load a `nomic-ai/*` embedding model, `pip install einops`
first.

Downstream KGs in the fleet were checked before the removal and none of them
break: the only sibling that imports `pandas` without declaring it does so
inside a Streamlit app, and `streamlit` requires `pandas>=1.4.0,<4` itself.

Two constraints tightened, so a resolver that previously found a solution could
now refuse one: `torch>=2.5.1` and `rich>=14.3.3`. Both match what the rest of
the fleet has required for some time.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
