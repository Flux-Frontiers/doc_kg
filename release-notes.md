# Release Notes — v0.12.3

> Released: 2026-04-28

### Added
- `tests/test_cli.py`: Tests for the `download-model` command — verifies help text, already-cached path short-circuit, `--force` redownload, and save-to-path behaviour.

### Changed
- `src/doc_kg/index.py`: Removed duplicate `Embedder` and `SentenceTransformerEmbedder` definitions; both are now imported from `kg_utils.embedder` (shared KGModule embedding infrastructure). Removed `_local_model_path` helper — delegates to `kg_utils.embed.resolve_model_path`.
- `src/doc_kg/embedder_worker.py`: `PIPELINE_MODEL` switched from `nomic-ai/nomic-embed-text-v1` to `BAAI/bge-small-en-v1.5`, aligning with DocKG and PyCodeKG defaults. Replaced manual local/remote model loading logic with `load_sentence_transformer()` from `kg_utils.embedder`.
- `src/doc_kg/cli/cmd_model.py`: `download-model` command now resolves model cache path via `kg_utils.embed.resolve_model_path` instead of the removed local `_local_model_path`.
- `pyproject.toml`, `poetry.lock`: Version bumped to 0.12.3; major dependency updates — `transformers` 4.57.6→5.6.2, `huggingface-hub` 0.36.2→1.12.0, `safetensors` 0.5.3→0.7.0, `pycode-kg` 0.16.0→0.17.2, `kgmodule-utils` 0.2.0→0.2.2; removed `kg-snapshot` (absorbed into `kgmodule-utils`); added `typer`, `rich`, `shellingham` as transitive deps.
- `.dockg/snapshots/manifest.json`: New DocKG snapshot for `feat/viz3d` branch (v0.12.2, 2521 nodes / 18884 edges, coverage 0.908).
- `tests/test_embedder_worker.py`: Replaced `_local_model_path` tests with a `resolve_model_path` availability check against `kg_utils.embed`; updated `_embed_shard` tests to patch `kg_utils.embedder.resolve_model_path`.

### Removed
- `src/doc_kg/index.py`: Removed `_local_model_path()`, `Embedder`, and `SentenceTransformerEmbedder` — now provided by `kg_utils`.
- `src/doc_kg/embedder_worker.py`: Removed `_local_model_path()` — replaced by `kg_utils.embed.resolve_model_path` via `load_sentence_transformer`.

### Fixed
- `src/doc_kg/embedder_worker.py`: Removed spurious `os.environ["TQDM_DISABLE"] = "1"` from `_embed_shard` — `transformers` ≥5.x ignores that env var and requires `hf_logging.disable_progress_bar()`, which `load_sentence_transformer()` in `kg_utils.embedder` now calls internally. The "Loading weights" tqdm bar during `dockg build` is suppressed correctly.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
