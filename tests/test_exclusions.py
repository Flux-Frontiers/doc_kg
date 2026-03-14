"""Tests for config.py and iter_text_files exclusion behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from doc_kg.config import load_exclude_dirs
from doc_kg.dockg import iter_text_files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def corpus_with_dirs(tmp_path: Path) -> Path:
    """Corpus with several subdirectories but no pyproject.toml."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n")
    (tmp_path / "docs" / "reference.md").write_text("# Reference\n")

    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "old.md").write_text("# Old\n")

    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "external.txt").write_text("external content\n")

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_notes.md").write_text("# Test Notes\n")

    return tmp_path


@pytest.fixture
def corpus_with_pyproject(tmp_path: Path) -> Path:
    """Same directory layout plus pyproject.toml with exclude config."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n")
    (tmp_path / "docs" / "reference.md").write_text("# Reference\n")

    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "old.md").write_text("# Old\n")

    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "external.txt").write_text("external content\n")

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_notes.md").write_text("# Test Notes\n")

    (tmp_path / "pyproject.toml").write_text('[tool.dockg]\nexclude = ["archive", "vendor"]\n')
    return tmp_path


# ---------------------------------------------------------------------------
# load_exclude_dirs
# ---------------------------------------------------------------------------


def test_load_exclude_dirs_no_pyproject(tmp_path: Path):
    result = load_exclude_dirs(tmp_path)
    assert result == set()


def test_load_exclude_dirs_no_dockg_section(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[tool.other]\nkey = 1\n")
    result = load_exclude_dirs(tmp_path)
    assert result == set()


def test_load_exclude_dirs_no_exclude_key(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[tool.dockg]\nmodel = 'all-mpnet-base-v2'\n")
    result = load_exclude_dirs(tmp_path)
    assert result == set()


def test_load_exclude_dirs_single_value(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[tool.dockg]\nexclude = ["archive"]\n')
    result = load_exclude_dirs(tmp_path)
    assert result == {"archive"}


def test_load_exclude_dirs_multiple_values(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.dockg]\nexclude = ["archive", "vendor", "scratch"]\n'
    )
    result = load_exclude_dirs(tmp_path)
    assert result == {"archive", "vendor", "scratch"}


def test_load_exclude_dirs_strips_trailing_slashes(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[tool.dockg]\nexclude = ["archive/", "vendor/"]\n')
    result = load_exclude_dirs(tmp_path)
    assert result == {"archive", "vendor"}


def test_load_exclude_dirs_invalid_toml_returns_empty(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("this is not: valid toml [\n")
    result = load_exclude_dirs(tmp_path)
    assert result == set()


def test_load_exclude_dirs_non_list_value_returns_empty(tmp_path: Path):
    # exclude is a string, not a list — should be ignored
    (tmp_path / "pyproject.toml").write_text('[tool.dockg]\nexclude = "archive"\n')
    result = load_exclude_dirs(tmp_path)
    assert result == set()


def test_load_exclude_dirs_accepts_path_object(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[tool.dockg]\nexclude = ["src"]\n')
    result = load_exclude_dirs(Path(tmp_path))
    assert "src" in result


def test_load_exclude_dirs_accepts_string_path(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[tool.dockg]\nexclude = ["src"]\n')
    result = load_exclude_dirs(str(tmp_path))
    assert "src" in result


# ---------------------------------------------------------------------------
# iter_text_files
# ---------------------------------------------------------------------------


def test_iter_text_files_no_exclude_finds_all(corpus_with_dirs: Path):
    found = {f.name for f in iter_text_files(corpus_with_dirs)}
    assert "guide.md" in found
    assert "reference.md" in found
    assert "old.md" in found
    assert "external.txt" in found
    assert "test_notes.md" in found


def test_iter_text_files_exclude_single_dir(corpus_with_dirs: Path):
    found = {f.name for f in iter_text_files(corpus_with_dirs, exclude={"archive"})}
    assert "old.md" not in found
    assert "guide.md" in found
    assert "external.txt" in found


def test_iter_text_files_exclude_multiple_dirs(corpus_with_dirs: Path):
    found = {f.name for f in iter_text_files(corpus_with_dirs, exclude={"archive", "vendor"})}
    assert "old.md" not in found
    assert "external.txt" not in found
    assert "guide.md" in found
    assert "test_notes.md" in found


def test_iter_text_files_default_extensions_only(tmp_path: Path):
    (tmp_path / "notes.md").write_text("# Notes\n")
    (tmp_path / "readme.txt").write_text("plain\n")
    (tmp_path / "docs.rst").write_text("RST\n")
    (tmp_path / "script.py").write_text("# python\n")
    (tmp_path / "data.json").write_text("{}\n")

    found = {f.name for f in iter_text_files(tmp_path)}
    assert "notes.md" in found
    assert "readme.txt" in found
    assert "docs.rst" in found
    assert "script.py" not in found
    assert "data.json" not in found


def test_iter_text_files_extension_override(tmp_path: Path):
    (tmp_path / "notes.md").write_text("# Notes\n")
    (tmp_path / "data.json").write_text("{}\n")
    (tmp_path / "script.py").write_text("# python\n")

    found = {f.name for f in iter_text_files(tmp_path, extensions={".json", ".py"})}
    assert "data.json" in found
    assert "script.py" in found
    assert "notes.md" not in found


def test_iter_text_files_empty_corpus(tmp_path: Path):
    assert iter_text_files(tmp_path) == []


def test_iter_text_files_skips_venv_even_without_explicit_exclude(tmp_path: Path):
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "readme.md").write_text("# venv readme\n")
    (tmp_path / "real.md").write_text("# Real\n")

    found = {f.name for f in iter_text_files(tmp_path)}
    assert "readme.md" not in found
    assert "real.md" in found


def test_iter_text_files_skips_all_builtin_skip_dirs(tmp_path: Path):
    skip_dirs = [
        ".git",
        "venv",
        "__pycache__",
        ".dockg",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
    ]
    for d in skip_dirs:
        (tmp_path / d).mkdir()
        (tmp_path / d / "file.md").write_text("hidden\n")

    (tmp_path / "visible.md").write_text("visible\n")
    found = {f.name for f in iter_text_files(tmp_path)}
    assert found == {"visible.md"}


def test_iter_text_files_returns_sorted_paths(tmp_path: Path):
    (tmp_path / "zebra.md").write_text("z\n")
    (tmp_path / "alpha.md").write_text("a\n")
    (tmp_path / "middle.md").write_text("m\n")

    found = [f.name for f in iter_text_files(tmp_path)]
    assert found == ["alpha.md", "middle.md", "zebra.md"]


# ---------------------------------------------------------------------------
# Integration: load_exclude_dirs + iter_text_files
# ---------------------------------------------------------------------------


def test_integration_config_exclude_dirs(corpus_with_pyproject: Path):
    exclude = load_exclude_dirs(corpus_with_pyproject)
    found = {f.name for f in iter_text_files(corpus_with_pyproject, exclude=exclude)}

    # archive and vendor should be excluded
    assert "old.md" not in found
    assert "external.txt" not in found

    # docs and tests should still be present
    assert "guide.md" in found
    assert "reference.md" in found
    assert "test_notes.md" in found


def test_integration_cli_merge_with_config(corpus_with_pyproject: Path):
    config_exclude = load_exclude_dirs(corpus_with_pyproject)
    # Simulate CLI adding an extra exclusion
    combined = config_exclude | {"tests"}

    found = {f.name for f in iter_text_files(corpus_with_pyproject, exclude=combined)}

    # archive, vendor, and tests all excluded
    assert "old.md" not in found
    assert "external.txt" not in found
    assert "test_notes.md" not in found

    # docs still present
    assert "guide.md" in found
    assert "reference.md" in found


def test_integration_no_pyproject_no_exclusions(corpus_with_dirs: Path):
    # corpus_with_dirs has no pyproject.toml → empty set → all dirs visible
    exclude = load_exclude_dirs(corpus_with_dirs)
    assert exclude == set()

    found = {f.name for f in iter_text_files(corpus_with_dirs, exclude=exclude)}
    assert "old.md" in found
    assert "external.txt" in found
