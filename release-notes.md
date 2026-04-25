# Release Notes — v0.12.0

> Released: 2026-04-25

### Added
- `kg.py`: `DocKG.__init__` now accepts an optional `embedder: Embedder | None` parameter — allows callers to inject a pre-built embedding backend, bypassing lazy `SentenceTransformerEmbedder` initialization. Defaults to `None` (existing behaviour preserved).

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
