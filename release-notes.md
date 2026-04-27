# Release Notes — v0.12.1

> Released: 2026-04-26

## Summary

This patch release fixes a silent correctness bug in the multiprocessing embedding pipeline and consolidates model-path resolution across the KGModule stack.

## What's Fixed

**Cached models were being ignored by embedding workers.** When `dockg build` used multiple workers, each spawned process loaded the model directly from HuggingFace — bypassing any model previously cached with `dockg download-model`. Workers now check the local `.dockg/models/` cache (or `KGRAG_MODEL_DIR`) first, falling back to the HuggingFace hub cache and then network only when needed.

**Duplicate CI flag** — a redundant `--extras dev` in the lint job's `poetry install` step has been removed.

## What's Changed

**Model-path resolution is now shared via `kg_utils.embed`.** `DEFAULT_MODEL` and `_local_model_path` were extracted from `dockg.py` and `index.py` into the `kgmodule-utils` package (`kg_utils.embed.resolve_model_path`). All KGModule packages now honour the same `KGRAG_MODEL_DIR` environment variable for a system-wide model cache override.

**`kgmodule-utils` added as an explicit dependency** in `pyproject.toml`.

**README updated** — the Contributing section has been replaced with a Citation section (Zenodo DOI `10.5281/zenodo.19770973` in APA and BibTeX formats); the header DOI badge now links directly to the DOI resolver.

## Tests

Nine new tests cover `_local_model_path` (path type, `.dockg/models/` fallback, `KGRAG_MODEL_DIR` override) and `_embed_shard` model resolution (local cache hit, cache miss, `OSError` network fallback, output shape). All 33 `test_embedder_worker` tests pass.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
