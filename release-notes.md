# Release Notes -- v0.28.1

> Released: 2026-10-20

PDF ingest works on a fresh install again. Since 2026-10-16, installing
doc-kg 0.28.0 into a new environment could leave it with no PDF converter at
all, so `dockg build` failed on every PDF. This release fixes the dependency;
nothing in DocKG's code or output changes.

## What changed

**The PDF dependency is declared correctly.** pymupdf4llm 2.0 is an empty
placeholder package: its code now ships inside pymupdf 2.0, and the
placeholder installs nothing and does not pull pymupdf in. DocKG gets its PDF
support through `kgmodule-utils[pdf]`, and kgmodule-utils 0.27.0 declared
`pymupdf4llm>=1.28.2`, which a fresh resolve now satisfies with the empty
placeholder. DocKG now requires kgmodule-utils 0.27.1, which declares
`pymupdf>=2.0` instead. The conversion call is the same
`pymupdf4llm.to_markdown`, so the Markdown, chunks and sections are
unchanged.

**The tests use the `pymupdf` name.** pymupdf 2.0 deprecates the old `fitz`
import name, and the PDF tests now import `pymupdf` directly.

## Upgrading

Upgrade the package; no graph rebuild is needed. An environment that already
has pymupdf 1.28.x keeps working, and upgrading moves it to pymupdf 2.0. If
you ever move an environment back from pymupdf 2.0 to 1.28.x, reinstall with
`pip install --force-reinstall pymupdf==1.28.2 pymupdf4llm==1.28.2`: pymupdf
2.0 owns the `pymupdf4llm` files, and a plain downgrade leaves them missing.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
