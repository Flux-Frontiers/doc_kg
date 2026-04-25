"""Tests for pipeline.py — PipelineConfig, AnalysisPipeline, PipelineResult."""

from pathlib import Path

from doc_kg.entry_chunk import EntryChunk, SourceProvenance
from doc_kg.pipeline import AnalysisPipeline, PipelineConfig, PipelineResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_corpus(tmp_path: Path, n: int = 3) -> Path:
    """Create n markdown files in tmp_path and return the directory."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        p = tmp_path / f"doc{i:02d}.md"
        p.write_text(
            f"# Document {i}\n\n"
            f"This document is about architecture and system design. "
            f"It discusses implementation patterns and code quality. "
            f"Testing with pytest ensures correctness. "
            f"Deployment to production requires careful planning.\n\n"
            f"## Section {i}\n\n"
            f"More details about topic {i}. "
            f"DocKG and SQLite are mentioned here for entity extraction. "
            f"Performance tuning and caching strategies matter.\n",
            encoding="utf-8",
        )
    return tmp_path


# ---------------------------------------------------------------------------
# PipelineConfig defaults
# ---------------------------------------------------------------------------


def test_pipeline_config_default_chunk_strategy():
    cfg = PipelineConfig()
    assert cfg.chunk_strategy == "sentence_group"


def test_pipeline_config_default_batch_size():
    cfg = PipelineConfig()
    assert cfg.batch_size == 20


def test_pipeline_config_default_sentences_per_chunk():
    cfg = PipelineConfig()
    assert cfg.sentences_per_chunk == 4


def test_pipeline_config_default_seed():
    cfg = PipelineConfig()
    assert cfg.seed == 42


def test_pipeline_config_default_max_chunks_per_doc():
    cfg = PipelineConfig()
    assert cfg.max_chunks_per_doc == 0


def test_pipeline_config_default_supervised_threshold():
    cfg = PipelineConfig()
    assert cfg.supervised_threshold == 0.3


def test_pipeline_config_default_n_diversity_clusters():
    cfg = PipelineConfig()
    assert cfg.n_diversity_clusters == 8


def test_pipeline_config_default_enable_entities():
    cfg = PipelineConfig()
    assert cfg.enable_entities is True


def test_pipeline_config_default_enable_keywords():
    cfg = PipelineConfig()
    assert cfg.enable_keywords is True


def test_pipeline_config_custom_values():
    cfg = PipelineConfig(
        chunk_strategy="semantic",
        batch_size=10,
        seed=123,
        max_chunks_per_doc=5,
    )
    assert cfg.chunk_strategy == "semantic"
    assert cfg.batch_size == 10
    assert cfg.seed == 123
    assert cfg.max_chunks_per_doc == 5


# ---------------------------------------------------------------------------
# Empty corpus
# ---------------------------------------------------------------------------


def test_pipeline_run_empty_corpus_returns_empty_result(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    cfg = PipelineConfig(corpus_root=empty_dir, output_dir=tmp_path / "out")
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    assert isinstance(result, PipelineResult)
    assert result.chunks == []
    assert "error" in result.stats


def test_pipeline_run_empty_corpus_has_run_id(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    cfg = PipelineConfig(corpus_root=empty_dir, output_dir=tmp_path / "out")
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    assert result.run_id != ""


# ---------------------------------------------------------------------------
# Small corpus run
# ---------------------------------------------------------------------------


def test_pipeline_run_produces_entry_chunks(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    assert isinstance(result.chunks, list)
    assert len(result.chunks) > 0


def test_pipeline_run_chunks_are_entry_chunk_instances(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    for chunk in result.chunks:
        assert isinstance(chunk, EntryChunk)


def test_pipeline_run_chunks_have_source_provenance(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    for chunk in result.chunks:
        assert isinstance(chunk.provenance, SourceProvenance)
        assert chunk.provenance.file_path != ""
        assert chunk.provenance.char_end >= chunk.provenance.char_start


def test_pipeline_run_chunks_have_non_empty_text(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    for chunk in result.chunks:
        assert chunk.text.strip() != ""


def test_pipeline_run_chunks_have_chunk_ids(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    for chunk in result.chunks:
        assert chunk.chunk_id.startswith("pchunk:")


def test_pipeline_run_chunks_linked_to_run_id(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    for chunk in result.chunks:
        assert chunk.run_id == result.run_id


# ---------------------------------------------------------------------------
# PSV output file
# ---------------------------------------------------------------------------


def test_pipeline_run_writes_psv_output(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    out_dir = tmp_path / "out"
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=out_dir,
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.suffix == ".psv"


def test_pipeline_run_psv_has_expected_header(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    out_dir = tmp_path / "out"
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=out_dir,
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    content = result.output_path.read_text(encoding="utf-8")
    assert "# DocKG Multipass Analysis Pipeline" in content
    assert "# Run ID:" in content
    assert "# Chunk strategy:" in content
    assert "# Total chunks:" in content


def test_pipeline_run_psv_contains_pipe_delimited_entries(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    out_dir = tmp_path / "out"
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=out_dir,
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    content = result.output_path.read_text(encoding="utf-8")
    # Non-comment lines that contain pipe characters are data entries
    data_lines = [line for line in content.splitlines() if "|" in line and not line.startswith("#")]
    assert len(data_lines) > 0


# ---------------------------------------------------------------------------
# max_chunks_per_doc
# ---------------------------------------------------------------------------


def test_pipeline_max_chunks_per_doc_limits_output(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    out_dir = tmp_path / "out"

    cfg_unlimited = PipelineConfig(
        corpus_root=corpus,
        output_dir=out_dir / "unlimited",
        batch_size=10,
        max_chunks_per_doc=0,
        seed=42,
    )
    cfg_limited = PipelineConfig(
        corpus_root=corpus,
        output_dir=out_dir / "limited",
        batch_size=10,
        max_chunks_per_doc=1,
        seed=42,
    )

    result_unlimited = AnalysisPipeline(cfg_unlimited).run()
    result_limited = AnalysisPipeline(cfg_limited).run()

    # With max_chunks_per_doc=1, we should get at most 1 chunk per file
    n_files = result_limited.stats.get("sampled_files", 3)
    assert len(result_limited.chunks) <= max(n_files, 1)
    assert len(result_limited.chunks) <= len(result_unlimited.chunks)


def test_pipeline_max_chunks_per_doc_one_chunk_per_file(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    out_dir = tmp_path / "out"
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=out_dir,
        batch_size=10,
        max_chunks_per_doc=1,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    # Count chunks per file
    file_chunk_counts: dict = {}
    for chunk in result.chunks:
        fp = chunk.provenance.file_path
        file_chunk_counts[fp] = file_chunk_counts.get(fp, 0) + 1

    for fp, count in file_chunk_counts.items():
        assert count <= 1, f"File {fp} has {count} chunks; expected at most 1"


# ---------------------------------------------------------------------------
# Stats dict
# ---------------------------------------------------------------------------


def test_pipeline_stats_keys(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    expected_keys = {
        "run_id",
        "total_files",
        "sampled_files",
        "total_chunks",
        "sampling_strategy",
        "chunk_strategy",
        "classification_methods",
        "elapsed_seconds",
    }
    for key in expected_keys:
        assert key in result.stats, f"Missing stats key: {key}"


def test_pipeline_stats_total_chunks_matches_chunks_list(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    assert result.stats["total_chunks"] == len(result.chunks)


def test_pipeline_stats_run_id_matches(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    assert result.stats["run_id"] == result.run_id


def test_pipeline_stats_classification_methods_structure(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    methods = result.stats["classification_methods"]
    assert isinstance(methods, dict)
    for key in ("supervised", "unsupervised", "fallback"):
        assert key in methods
        assert isinstance(methods[key], int)
        assert methods[key] >= 0


def test_pipeline_stats_total_files_is_positive(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=3)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    assert result.stats["total_files"] == 3


# ---------------------------------------------------------------------------
# Phase 4: EntryChunk with SourceProvenance
# ---------------------------------------------------------------------------


def test_pipeline_phase4_chunk_index_set(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=2)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    # Within each file the chunk_index should start at 0
    file_indices: dict = {}
    for chunk in result.chunks:
        fp = chunk.provenance.file_path
        if fp not in file_indices:
            file_indices[fp] = []
        file_indices[fp].append(chunk.provenance.chunk_index)

    for fp, indices in file_indices.items():
        assert 0 in indices, f"File {fp} has no chunk with index 0"


def test_pipeline_phase4_topic_method_is_valid(tmp_path):
    corpus = _make_corpus(tmp_path / "corpus", n=2)
    cfg = PipelineConfig(
        corpus_root=corpus,
        output_dir=tmp_path / "out",
        batch_size=10,
        seed=42,
    )
    pipeline = AnalysisPipeline(cfg)
    result = pipeline.run()

    valid_methods = {"supervised", "unsupervised", "fallback"}
    for chunk in result.chunks:
        assert chunk.topic_method in valid_methods
