# tests/test_validate_hallucination.py
import pytest
from pathlib import Path
from yonk_code_robomonkey.validate.capture.hallucination import (
    detect_file_hallucinations,
    detect_import_hallucinations,
    detect_symbol_hallucinations,
    check_hallucinations,
    HallucinationReport,
)

def test_detect_real_file(tmp_path):
    """No hallucination for files that exist."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    result = detect_file_hallucinations("check src/main.py", tmp_path)
    assert result == []

def test_detect_fake_file(tmp_path):
    """Detect file path that doesn't exist."""
    result = detect_file_hallucinations("look at src/nonexistent.py for details", tmp_path)
    assert "src/nonexistent.py" in result

def test_detect_valid_import(tmp_path):
    """No hallucination for valid stdlib import."""
    diff = "+import json\n+import os"
    result = detect_import_hallucinations(diff, tmp_path)
    assert result == []

def test_detect_fake_import(tmp_path):
    """Detect import that can't resolve."""
    diff = "+from totally_fake_module import something"
    result = detect_import_hallucinations(diff, tmp_path)
    assert "totally_fake_module" in result

def test_detect_valid_symbol(tmp_path):
    """No hallucination for class that exists in repo."""
    (tmp_path / "models.py").write_text("class MyModel:\n    pass\n")
    diff = "+obj = MyModel()"
    result = detect_symbol_hallucinations(diff, tmp_path)
    assert "MyModel" not in result

def test_detect_fake_symbol(tmp_path):
    """Detect class reference that doesn't exist."""
    (tmp_path / "models.py").write_text("class RealModel:\n    pass\n")
    diff = "+obj = FakeModel()"
    result = detect_symbol_hallucinations(diff, tmp_path)
    assert "FakeModel" in result

def test_clean_code_zero_hallucinations(tmp_path):
    """Zero hallucinations for correct code referencing real files."""
    (tmp_path / "app.py").write_text("class App:\n    pass\n")
    text = "The App class in app.py handles this."
    result = detect_file_hallucinations(text, tmp_path)
    assert result == []

@pytest.mark.asyncio
async def test_check_hallucinations_combined(tmp_path):
    """Full check returns combined report."""
    (tmp_path / "real.py").write_text("class Real:\n    pass\n")
    diff = "+from fake_lib import stuff\n+obj = Fake()"
    text = "See src/missing.py"
    report = await check_hallucinations(diff, text, tmp_path)
    assert report.total > 0
    assert isinstance(report, HallucinationReport)
