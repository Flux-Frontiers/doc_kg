#!/usr/bin/env python3
"""
pipeline.py

AnalysisPipeline — 5-phase multipass analysis orchestrator for DocKG.

Implements the diary_kg-style transformation pipeline:

Phase 1 — Diversity Sampling
    Extract NLP features, cluster for diversity, select representative batch.

Phase 2 — Chunking
    Sentence-group or semantic chunking within each selected document.

Phase 3 — Topic Classification (Hybrid)
    Supervised keyword mapping with unsupervised K-means fallback.

Phase 4 — Memory Creation
    Build ``EntryChunk`` objects with full provenance and metadata.

Phase 5 — Structured Output
    Write pipe-delimited output with run parameters and source tracking.

Usage::

    from doc_kg.pipeline import AnalysisPipeline, PipelineConfig

    config = PipelineConfig(corpus_root=Path("./docs"))
    pipeline = AnalysisPipeline(config)
    result = pipeline.run()

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from doc_kg.chunker import SentenceGroupChunker, TextChunker, chunker_for
from doc_kg.dockg import iter_text_files
from doc_kg.embedder_worker import PIPELINE_MODEL
from doc_kg.entry_chunk import EntryChunk, SourceProvenance, make_chunk_id
from doc_kg.relations import extract_entities
from doc_kg.sampler import CorpusSampler, SampleResult
from doc_kg.topics import TopicExtractor

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class PipelineConfig:
    """Configuration for the multipass analysis pipeline.

    :param corpus_root: Root directory of the text corpus.
    :param chunk_strategy: ``"sentence_group"`` or ``"semantic"``.
    :param sentences_per_chunk: Sentences per chunk (sentence_group strategy).
    :param chunk_size: Max chars per chunk (semantic strategy).
    :param chunk_overlap: Overlap chars (semantic strategy).
    :param similarity_threshold: Cosine threshold for semantic boundaries.
    :param n_diversity_clusters: Number of K-means clusters for sampling.
    :param batch_size: Documents to sample per run.
    :param supervised_threshold: Min confidence for supervised topic classification.
    :param n_topic_clusters: Clusters for unsupervised topic fallback.
    :param topics_file: Custom topic catalog (YAML/JSON).
    :param output_dir: Where to write pipeline output files.
    :param embedding_model: Sentence-transformer model name.
    :param seed: Random seed for reproducibility.
    :param run_id: Pipeline run identifier (auto-generated if blank).
    :param max_chunks_per_doc: Max chunks emitted per document.
    :param enable_entities: Extract entities per chunk.
    :param enable_keywords: Extract keywords per chunk.
    """

    corpus_root: Path = Path(".")
    chunk_strategy: Literal["sentence_group", "semantic"] = "sentence_group"
    sentences_per_chunk: int = 4
    chunk_size: int = 512
    chunk_overlap: int = 64
    similarity_threshold: float = 0.75
    n_diversity_clusters: int = 8
    batch_size: int = 20
    supervised_threshold: float = 0.3
    n_topic_clusters: int = 8
    topics_file: str | None = None
    output_dir: Path | None = None
    embedding_model: str = PIPELINE_MODEL
    seed: int = 42
    run_id: str = ""
    max_chunks_per_doc: int = 0  # 0 = unlimited
    enable_entities: bool = True
    enable_keywords: bool = True


# ============================================================================
# Result
# ============================================================================


@dataclass
class PipelineResult:
    """Result of a full pipeline run.

    :param run_id: Unique identifier for this run.
    :param chunks: All produced ``EntryChunk`` objects.
    :param sample: Sampling metadata from Phase 1.
    :param output_path: Path to the pipe-delimited output file.
    :param stats: Summary statistics dict.
    :param elapsed_seconds: Wall-clock time for the full run.
    """

    run_id: str
    chunks: list[EntryChunk]
    sample: SampleResult | None = None
    output_path: Path | None = None
    stats: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0


# ============================================================================
# Pipeline
# ============================================================================


class AnalysisPipeline:
    """5-phase multipass analysis pipeline for document corpora.

    :param config: Pipeline configuration.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._run_id = config.run_id or uuid.uuid4().hex[:12]
        self._topic_extractor: TopicExtractor | None = None
        self._embedder = None

    def run(self, paths: list[Path] | None = None) -> PipelineResult:
        """Execute the full 5-phase pipeline.

        :param paths: Explicit file paths (skips file discovery if provided).
        :return: Pipeline result with chunks and metadata.
        """
        t0 = time.monotonic()
        cfg = self.config
        corpus_root = Path(cfg.corpus_root).resolve()

        # Discover files
        if paths is None:
            all_paths = iter_text_files(corpus_root)
        else:
            all_paths = [Path(p).resolve() for p in paths]

        if not all_paths:
            return PipelineResult(
                run_id=self._run_id,
                chunks=[],
                stats={"error": "no files found"},
            )

        logger.info("Pipeline %s: %d files discovered", self._run_id, len(all_paths))

        # Phase 1: Diversity Sampling
        sample_result = self._phase1_sample(all_paths, corpus_root)
        selected_paths = [
            corpus_root / p for p in sample_result.selected_paths
        ]
        logger.info("Phase 1: sampled %d / %d files", len(selected_paths), len(all_paths))

        # Phase 2: Chunking
        raw_chunks = self._phase2_chunk(selected_paths, corpus_root)
        logger.info("Phase 2: produced %d raw chunks", len(raw_chunks))

        # Phase 3: Topic Classification (Hybrid)
        classified_chunks = self._phase3_classify(raw_chunks)
        logger.info("Phase 3: classified %d chunks", len(classified_chunks))

        # Phase 4: Memory Creation (EntryChunk assembly)
        entry_chunks = self._phase4_create_entries(classified_chunks)
        logger.info("Phase 4: created %d EntryChunks", len(entry_chunks))

        # Phase 5: Structured Output
        output_path = self._phase5_output(entry_chunks, sample_result)
        logger.info("Phase 5: wrote output to %s", output_path)

        elapsed = time.monotonic() - t0

        # Compute stats
        method_counts = {"supervised": 0, "unsupervised": 0, "fallback": 0}
        for ec in entry_chunks:
            method_counts[ec.topic_method] = method_counts.get(ec.topic_method, 0) + 1

        stats = {
            "run_id": self._run_id,
            "total_files": len(all_paths),
            "sampled_files": len(selected_paths),
            "total_chunks": len(entry_chunks),
            "sampling_strategy": sample_result.strategy,
            "chunk_strategy": cfg.chunk_strategy,
            "classification_methods": method_counts,
            "elapsed_seconds": round(elapsed, 2),
        }

        return PipelineResult(
            run_id=self._run_id,
            chunks=entry_chunks,
            sample=sample_result,
            output_path=output_path,
            stats=stats,
            elapsed_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # Phase 1: Diversity Sampling
    # ------------------------------------------------------------------

    def _phase1_sample(
        self, all_paths: list[Path], corpus_root: Path
    ) -> SampleResult:
        """Phase 1: extract features, cluster, sample."""
        sampler = CorpusSampler(
            corpus_root,
            n_clusters=self.config.n_diversity_clusters,
            seed=self.config.seed,
        )
        return sampler.sample(
            all_paths,
            batch_size=self.config.batch_size,
            strategy="diversity",
        )

    # ------------------------------------------------------------------
    # Phase 2: Chunking
    # ------------------------------------------------------------------

    def _phase2_chunk(
        self, selected_paths: list[Path], corpus_root: Path
    ) -> list[dict]:
        """Phase 2: chunk selected documents.

        Returns a list of dicts with chunk text plus provenance metadata.
        """
        cfg = self.config
        chunker: TextChunker | SentenceGroupChunker = chunker_for(
            cfg.chunk_strategy,
            sentences_per_chunk=cfg.sentences_per_chunk,
            chunk_size=cfg.chunk_size,
            chunk_overlap=cfg.chunk_overlap,
            similarity_threshold=cfg.similarity_threshold,
        )

        all_chunks: list[dict] = []

        for abs_path in selected_paths:
            try:
                text = abs_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                try:
                    text = abs_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

            try:
                rel_path = str(abs_path.relative_to(corpus_root)).replace("\\", "/")
            except ValueError:
                rel_path = str(abs_path).replace("\\", "/")

            chunks = chunker.chunk(text, file_path=rel_path)

            if cfg.max_chunks_per_doc > 0:
                chunks = chunks[: cfg.max_chunks_per_doc]

            for idx, chunk in enumerate(chunks):
                chunk["_file_path"] = rel_path
                chunk["_chunk_index"] = idx
                all_chunks.append(chunk)

        return all_chunks

    # ------------------------------------------------------------------
    # Phase 3: Hybrid Topic Classification
    # ------------------------------------------------------------------

    def _phase3_classify(self, raw_chunks: list[dict]) -> list[dict]:
        """Phase 3: classify each chunk using hybrid supervised + unsupervised.

        Enriches each chunk dict with ``_topics``, ``_topic_method``, and
        ``_topic_confidence`` keys.
        """
        cfg = self.config

        # Initialize topic extractor
        self._topic_extractor = TopicExtractor(topics_file=cfg.topics_file)

        # Try to fit unsupervised clusters if we have enough chunks
        if len(raw_chunks) >= cfg.n_topic_clusters:
            self._fit_unsupervised_clusters(raw_chunks)

        for chunk in raw_chunks:
            text = chunk["text"]
            embedding = chunk.get("_embedding")

            matches, method = self._topic_extractor.classify_hybrid(
                text,
                embedding=embedding,
                supervised_threshold=cfg.supervised_threshold,
            )

            chunk["_topics"] = [(m.topic, m.score) for m in matches]
            chunk["_topic_method"] = method
            chunk["_topic_confidence"] = matches[0].score if matches else 0.0

            # Extract keywords and entities
            if cfg.enable_keywords:
                chunk["_keywords"] = self._topic_extractor.extract_keywords(
                    text, max_keywords=4
                )
            if cfg.enable_entities:
                chunk["_entities"] = extract_entities(text, max_entities=8)

        return raw_chunks

    def _fit_unsupervised_clusters(self, chunks: list[dict]) -> None:
        """Embed chunks and fit K-means for unsupervised topic fallback."""
        try:
            from doc_kg.index import (  # pylint: disable=import-outside-toplevel
                SentenceTransformerEmbedder,
                suppress_ingestion_logging,
            )

            suppress_ingestion_logging()
            if self._embedder is None:
                self._embedder = SentenceTransformerEmbedder(self.config.embedding_model)

            texts = [c["text"] for c in chunks]
            embeddings = self._embedder.embed_texts(texts)

            # Store embeddings on chunks for later use
            for chunk, emb in zip(chunks, embeddings):
                chunk["_embedding"] = emb

            # Fit clusters
            if self._topic_extractor is not None:
                self._topic_extractor.fit_clusters(
                    embeddings, n_clusters=self.config.n_topic_clusters
                )

        except (ImportError, Exception) as exc:
            logger.warning("Could not fit unsupervised clusters: %s", exc)

    # ------------------------------------------------------------------
    # Phase 4: Memory Creation
    # ------------------------------------------------------------------

    def _phase4_create_entries(self, classified_chunks: list[dict]) -> list[EntryChunk]:
        """Phase 4: assemble ``EntryChunk`` objects with full provenance."""
        entries: list[EntryChunk] = []

        for chunk in classified_chunks:
            file_path = chunk["_file_path"]
            char_start = chunk.get("char_start", 0)
            char_end = chunk.get("char_end", len(chunk["text"]))

            provenance = SourceProvenance(
                file_path=file_path,
                char_start=char_start,
                char_end=char_end,
                section_title=chunk.get("section_title"),
                section_level=chunk.get("section_level"),
                chunk_index=chunk.get("_chunk_index", 0),
            )

            chunk_id = make_chunk_id(file_path, char_start, chunk["text"])

            entry = EntryChunk(
                chunk_id=chunk_id,
                text=chunk["text"],
                provenance=provenance,
                topics=chunk.get("_topics", []),
                topic_method=chunk.get("_topic_method", "fallback"),
                topic_confidence=chunk.get("_topic_confidence", 0.0),
                keywords=chunk.get("_keywords", []),
                entities=chunk.get("_entities", []),
                embedding=chunk.get("_embedding"),
                run_id=self._run_id,
            )
            entries.append(entry)

        return entries

    # ------------------------------------------------------------------
    # Phase 5: Structured Output
    # ------------------------------------------------------------------

    def _phase5_output(
        self, entries: list[EntryChunk], sample: SampleResult
    ) -> Path | None:
        """Phase 5: write pipe-delimited output with run parameters."""
        cfg = self.config
        output_dir = cfg.output_dir or (Path(cfg.corpus_root) / ".dockg" / "pipeline")
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        output_path = output_dir / f"PipelineRun_{self._run_id}_{timestamp}.psv"

        with open(output_path, "w", encoding="utf-8") as f:
            # Header: run parameters
            f.write("# DocKG Multipass Analysis Pipeline - Run Parameters\n")
            f.write(f"# Run ID: {self._run_id}\n")
            f.write(f"# Generated: {datetime.now(tz=UTC).isoformat()}\n")
            f.write(f"# Corpus root: {cfg.corpus_root}\n")
            f.write(f"# Chunk strategy: {cfg.chunk_strategy}\n")
            if cfg.chunk_strategy == "sentence_group":
                f.write(f"# Sentences per chunk: {cfg.sentences_per_chunk}\n")
            else:
                f.write(f"# Chunk size: {cfg.chunk_size}\n")
            f.write(f"# Batch size: {cfg.batch_size}\n")
            f.write(f"# Sampling strategy: {sample.strategy}\n")
            f.write(f"# Diversity clusters: {cfg.n_diversity_clusters}\n")
            f.write(f"# Topic clusters: {cfg.n_topic_clusters}\n")
            f.write(f"# Supervised threshold: {cfg.supervised_threshold}\n")
            f.write(f"# Random seed: {cfg.seed}\n")
            f.write(f"# Total files: {len(sample.all_features)}\n")
            f.write(f"# Sampled files: {len(sample.selected_paths)}\n")
            f.write(f"# Total chunks: {len(entries)}\n")
            f.write("#\n")
            f.write("# ======== ENTRIES ========\n\n")

            # Group entries by source file
            current_file = ""
            for entry in entries:
                prov = entry.provenance

                # Source entry header when file changes
                if prov.file_path != current_file:
                    current_file = prov.file_path
                    f.write(f"\n# === Source: {current_file} ===\n")
                    if prov.section_title:
                        f.write(f"# Section: {prov.section_title}\n")

                # Pipe-delimited entry
                topic = entry.primary_topic
                confidence = f"{entry.topic_confidence:.2f}"
                method = entry.topic_method
                keywords_str = ",".join(entry.keywords) if entry.keywords else ""
                text_preview = entry.text.replace("\n", " ").strip()

                f.write(
                    f"{entry.chunk_id} | {topic} | {confidence} | "
                    f"{method} | {keywords_str} | {text_preview}\n"
                )

            # Footer: transformation statistics
            f.write("\n# ======== STATISTICS ========\n")
            method_counts = {"supervised": 0, "unsupervised": 0, "fallback": 0}
            for e in entries:
                method_counts[e.topic_method] = method_counts.get(e.topic_method, 0) + 1
            f.write(f"# Supervised classifications: {method_counts['supervised']}\n")
            f.write(f"# Unsupervised classifications: {method_counts['unsupervised']}\n")
            f.write(f"# Fallback classifications: {method_counts['fallback']}\n")
            supervised_pct = (
                method_counts["supervised"] / max(1, len(entries)) * 100
            )
            f.write(f"# Supervised rate: {supervised_pct:.1f}%\n")

        return output_path
