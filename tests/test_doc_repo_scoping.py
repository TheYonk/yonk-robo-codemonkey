"""Tests for doc repo-scoping feature."""

import pytest
from pathlib import Path


class TestBuildRepoFilter:
    """Tests for _build_repo_filter helper function."""

    def test_repo_filter_none_returns_true(self):
        """No repo_name means no filtering."""
        from yonk_code_robomonkey.knowledge_base.search import _build_repo_filter

        bind_params = []
        condition, idx = _build_repo_filter(None, True, 1, bind_params)
        assert condition == "TRUE"
        assert len(bind_params) == 0
        assert idx == 1

    def test_repo_filter_with_include_global(self):
        """repo_name + include_global returns OR condition."""
        from yonk_code_robomonkey.knowledge_base.search import _build_repo_filter

        bind_params = []
        condition, idx = _build_repo_filter("my-repo", True, 1, bind_params)
        assert "OR ds.repo_name IS NULL" in condition
        assert "ds.repo_name = $1" in condition
        assert bind_params == ["my-repo"]
        assert idx == 2

    def test_repo_filter_without_include_global(self):
        """repo_name without include_global returns exact match only."""
        from yonk_code_robomonkey.knowledge_base.search import _build_repo_filter

        bind_params = []
        condition, idx = _build_repo_filter("my-repo", False, 1, bind_params)
        assert "IS NULL" not in condition
        assert "ds.repo_name = $1" in condition
        assert bind_params == ["my-repo"]

    def test_repo_filter_increments_param_index(self):
        """Should increment param_idx correctly."""
        from yonk_code_robomonkey.knowledge_base.search import _build_repo_filter

        bind_params = []
        condition, idx = _build_repo_filter("test-repo", True, 5, bind_params)
        assert "$5" in condition
        assert idx == 6


class TestDiscoverRepoDocs:
    """Tests for discover_repo_docs function."""

    def test_discovers_markdown_files(self, tmp_path):
        """Should find markdown files in repo."""
        from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs

        (tmp_path / "README.md").write_text("# Test")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs/guide.md").write_text("# Guide")

        docs = list(discover_repo_docs(tmp_path))
        assert len(docs) == 2
        names = {d.name for d in docs}
        assert "README.md" in names
        assert "guide.md" in names

    def test_excludes_node_modules(self, tmp_path):
        """Should exclude node_modules directory."""
        from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs

        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules/package.md").write_text("# Pkg")
        (tmp_path / "README.md").write_text("# Test")

        docs = list(discover_repo_docs(tmp_path))
        assert len(docs) == 1
        assert docs[0].name == "README.md"

    def test_excludes_git_directory(self, tmp_path):
        """Should exclude .git directory."""
        from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs

        (tmp_path / ".git").mkdir()
        (tmp_path / ".git/config.md").write_text("# Config")
        (tmp_path / "README.md").write_text("# Test")

        docs = list(discover_repo_docs(tmp_path))
        assert len(docs) == 1
        assert docs[0].name == "README.md"

    def test_excludes_venv_directory(self, tmp_path):
        """Should exclude .venv directory."""
        from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs

        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv/readme.md").write_text("# Venv")
        (tmp_path / "README.md").write_text("# Test")

        docs = list(discover_repo_docs(tmp_path))
        assert len(docs) == 1
        assert docs[0].name == "README.md"

    def test_finds_pdf_in_docs(self, tmp_path):
        """Should find PDF files in docs directory."""
        from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs

        (tmp_path / "docs").mkdir()
        (tmp_path / "docs/manual.pdf").write_bytes(b"PDF content")

        docs = list(discover_repo_docs(tmp_path))
        assert len(docs) == 1
        assert docs[0].name == "manual.pdf"

    def test_custom_patterns(self, tmp_path):
        """Should respect custom include/exclude patterns."""
        from yonk_code_robomonkey.indexer.doc_discovery import discover_repo_docs

        (tmp_path / "custom.txt").write_text("Custom")
        (tmp_path / "README.md").write_text("# Test")

        # Only include .txt files
        docs = list(discover_repo_docs(
            tmp_path,
            include_patterns=["*.txt"],
            exclude_patterns=[]
        ))
        assert len(docs) == 1
        assert docs[0].name == "custom.txt"


class TestDocSearchParams:
    """Tests for DocSearchParams model."""

    def test_default_include_global_is_true(self):
        """include_global should default to True."""
        from yonk_code_robomonkey.knowledge_base.models import DocSearchParams

        params = DocSearchParams(query="test")
        assert params.include_global is True
        assert params.repo_name is None

    def test_repo_name_can_be_set(self):
        """Should allow setting repo_name."""
        from yonk_code_robomonkey.knowledge_base.models import DocSearchParams

        params = DocSearchParams(query="test", repo_name="my-repo")
        assert params.repo_name == "my-repo"


class TestDocChunkResult:
    """Tests for DocChunkResult model."""

    def test_default_repo_name_is_global(self):
        """repo_name should default to 'global'."""
        from yonk_code_robomonkey.knowledge_base.models import DocChunkResult, DocType
        from uuid import uuid4

        result = DocChunkResult(
            chunk_id=uuid4(),
            content="test content",
            source_document="test.md",
            doc_type=DocType.GENERAL,
            section_path=[],
            chunk_index=0,
            score=0.9,
        )
        assert result.repo_name == "global"
