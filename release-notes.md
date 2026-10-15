# Release Notes -- v0.28.0

> Released: 2026-10-14

DocKG now converts PDFs with the fleet's shared converter. `dockg build` and
`kgrag ingest` produce the same Markdown from the same PDF, and a scanned PDF
is left out of the graph instead of becoming an empty document.

## What changed

**One PDF converter for the fleet.** PDF text extraction now goes through
`kg_utils.ingest.PdfConverter`, released in kgmodule-utils 0.27.0. It makes
the same `pymupdf4llm` call DocKG made before, so the Markdown, and therefore
every chunk and section, is unchanged; the output was compared byte for byte
on six PDFs before release. DocKG no longer pins `pymupdf4llm` itself: it
comes with `kgmodule-utils[pdf]`, an extra that brings no other converter.

**Scanned PDFs are skipped.** A PDF with no text layer used to produce a
document node with no chunks. It is now skipped during parsing, with an
error that names OCR as the missing step, the same way an unreadable PDF was
already skipped.

## Upgrading

```bash
pip install -U doc-kg
```

Rebuild a corpus that contains scanned PDFs if you want their empty document
nodes gone; nothing else needs a rebuild.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
