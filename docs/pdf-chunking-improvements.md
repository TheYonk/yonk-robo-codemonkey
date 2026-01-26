# PDF Chunking Improvements - Design Document

## Status: Planning

## Problem Statement

Current PDF chunking produces many tiny, meaningless chunks that:
1. Have no semantic context (e.g., "USER;", "NLSSORT() CollateClause.")
2. Waste embedding compute and storage
3. Pollute search results with false positives
4. Provide no value for RAG retrieval

### Examples of Bad Chunks

| Chunk # | Content | Size | Problem |
|---------|---------|------|---------|
| #95 | "NLSSORT() CollateClause." | 28 chars | Table cell fragment |
| #117 | "USER;" | 5 chars | Single word from table |

### Root Causes

1. **Aggressive Heading Detection** (`pdf.py` lines 190-195)
   - Any short uppercase line (< 80 chars, ≤ 8 words) is treated as a heading
   - Creates new sections for table cells, code fragments, short lines

2. **No Minimum Section Enforcement**
   - PDF extractor creates sections of any size
   - Chunker receives tiny sections and can't merge them

3. **Poor Table Handling**
   - Tables extracted as separate sections per row
   - Loses table context and structure

4. **PDF Structure Loss**
   - pdfplumber extracts raw text, loses visual layout
   - Multi-column PDFs get interleaved incorrectly
   - Headers/footers mixed with content

---

## Proposed Solutions

### Solution 1: Chunk Merging (Quick Fix)

**Effort:** Low (1-2 hours)
**Impact:** Medium - eliminates tiny chunks but doesn't improve structure

Add post-processing to merge chunks below minimum size with neighbors.

```python
# In chunker.py - add after chunk_document()

def _merge_tiny_chunks(self, chunks: list[DocChunk], min_size: int = 100) -> list[DocChunk]:
    """Merge chunks smaller than min_size with adjacent chunks."""
    if not chunks:
        return chunks

    merged = []
    i = 0

    while i < len(chunks):
        chunk = chunks[i]

        # If chunk is too small, merge with next or previous
        if len(chunk.content) < min_size:
            if merged:
                # Merge with previous chunk
                prev = merged[-1]
                prev.content = prev.content + "\n\n" + chunk.content
                prev.end_char = chunk.end_char
                prev.char_count = len(prev.content)
                prev.token_count_approx = prev.char_count // 4
                # Recalculate hash
                prev.content_hash = hashlib.sha256(prev.content.encode()).hexdigest()[:16]
            elif i + 1 < len(chunks):
                # Merge with next chunk (prepend)
                next_chunk = chunks[i + 1]
                next_chunk.content = chunk.content + "\n\n" + next_chunk.content
                next_chunk.start_char = chunk.start_char
                next_chunk.char_count = len(next_chunk.content)
                next_chunk.token_count_approx = next_chunk.char_count // 4
                next_chunk.content_hash = hashlib.sha256(next_chunk.content.encode()).hexdigest()[:16]
            else:
                # Only chunk and it's tiny - keep it anyway
                merged.append(chunk)
        else:
            merged.append(chunk)

        i += 1

    # Renumber chunk indices
    for idx, chunk in enumerate(merged):
        chunk.chunk_index = idx

    return merged
```

**Files to Modify:**
- `knowledge_base/chunker.py` - Add `_merge_tiny_chunks()` method
- Call it at end of `chunk_document()`

---

### Solution 2: Improve PDF Heading Detection

**Effort:** Low (1 hour)
**Impact:** Medium - reduces false positive headings

Make heading detection require stronger signals.

```python
# In pdf.py - replace _detect_heading()

def _detect_heading(self, line: str, page) -> tuple[bool, int]:
    """Detect if a line is a heading - conservative approach."""

    # Explicit heading patterns only
    heading_patterns = [
        (r"^Chapter\s+\d+", 1),
        (r"^CHAPTER\s+\d+", 1),
        (r"^Part\s+[IVXLCDM\d]+", 1),
        (r"^Section\s+\d+", 2),
        (r"^\d+\.\s+[A-Z][a-z]", 2),      # "1. Introduction"
        (r"^\d+\.\d+\s+[A-Z]", 3),         # "1.1 Subsection"
        (r"^\d+\.\d+\.\d+\s+", 4),         # "1.1.1 Sub-subsection"
        (r"^Appendix\s+[A-Z]", 1),
        (r"^APPENDIX\s+[A-Z]", 1),
        (r"^Table of Contents", 1),
        (r"^Index$", 1),
        (r"^Glossary$", 1),
        (r"^References$", 1),
        (r"^Bibliography$", 1),
    ]

    for pattern, level in heading_patterns:
        if re.match(pattern, line, re.IGNORECASE):
            return True, level

    # ALL CAPS lines that are clearly titles (stricter rules)
    if re.match(r"^[A-Z][A-Z\s]{10,50}$", line):
        # Must be 10-50 chars, no punctuation except spaces
        if not any(c in line for c in ".,;:()[]{}"):
            return True, 2

    # Remove the aggressive short-line heuristic entirely
    return False, 0
```

**Files to Modify:**
- `knowledge_base/extractors/pdf.py` - Replace `_detect_heading()`

---

### Solution 3: PDF → Markdown Conversion (Best Quality)

**Effort:** Medium (4-6 hours)
**Impact:** High - dramatically better structure preservation

Add option to convert PDF to Markdown before chunking using Marker or Docling.

#### Option 3A: Marker Integration

```python
# New file: knowledge_base/extractors/pdf_markdown.py

"""
PDF to Markdown conversion using Marker.

Marker is an ML-based PDF converter that:
- Preserves document structure
- Handles tables, code blocks, equations
- Works well with technical documentation
"""

import subprocess
import tempfile
from pathlib import Path

from .markdown import MarkdownExtractor
from ..models import ExtractedDocument


class PDFMarkdownExtractor:
    """Extract PDF by converting to Markdown first."""

    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self.markdown_extractor = MarkdownExtractor()

    def extract(self, file_path: str) -> ExtractedDocument:
        """Convert PDF to Markdown, then extract."""
        path = Path(file_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Run marker conversion
            output_dir = Path(tmpdir)
            self._run_marker(path, output_dir)

            # Find the generated markdown file
            md_files = list(output_dir.glob("*.md"))
            if not md_files:
                raise RuntimeError(f"Marker produced no output for {file_path}")

            md_path = md_files[0]

            # Use markdown extractor on the result
            doc = self.markdown_extractor.extract(str(md_path))

            # Update source path to original PDF
            doc.source_path = str(path)
            doc.metadata["converted_from"] = "pdf"
            doc.metadata["converter"] = "marker"

            return doc

    def _run_marker(self, pdf_path: Path, output_dir: Path) -> None:
        """Run marker_single CLI."""
        cmd = [
            "marker_single",
            str(pdf_path),
            str(output_dir),
        ]

        if not self.use_gpu:
            cmd.extend(["--batch_multiplier", "1"])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Marker failed: {result.stderr}")
```

#### Option 3B: Docling Integration (IBM)

```python
# Alternative: use docling for PDF conversion

from docling.document_converter import DocumentConverter

class PDFDoclingExtractor:
    """Extract PDF using IBM Docling."""

    def __init__(self):
        self.converter = DocumentConverter()
        self.markdown_extractor = MarkdownExtractor()

    def extract(self, file_path: str) -> ExtractedDocument:
        result = self.converter.convert(file_path)
        markdown_content = result.document.export_to_markdown()

        # Write to temp file and use markdown extractor
        # ... similar to Marker approach
```

#### Configuration

Add to `config/robomonkey-daemon.yaml`:

```yaml
knowledge_base:
  pdf_extraction:
    method: "marker"  # "pdfplumber" (default), "marker", "docling"
    marker:
      use_gpu: true
      batch_multiplier: 2
    docling:
      # docling-specific options
```

**Dependencies to Add:**

```toml
# pyproject.toml - optional dependencies
[project.optional-dependencies]
pdf-ml = [
    "marker-pdf>=0.2.0",
    # OR
    "docling>=1.0.0",
]
```

**Files to Create:**
- `knowledge_base/extractors/pdf_markdown.py`
- `knowledge_base/extractors/pdf_docling.py`

**Files to Modify:**
- `knowledge_base/extractors/__init__.py` - Add extractor selection logic
- `web/routes/docs.py` - Add extraction method parameter
- `pyproject.toml` - Add optional dependencies

---

### Solution 4: Better Table Handling

**Effort:** Medium (2-3 hours)
**Impact:** Medium - tables become coherent chunks

Keep tables as single chunks with proper formatting.

```python
# In pdf.py - improve table extraction

def _extract_tables_as_chunks(self, page, page_num: int) -> list[ExtractedSection]:
    """Extract tables as complete, formatted sections."""
    sections = []

    tables = page.extract_tables()
    for table in tables:
        if not table or len(table) < 2:
            continue

        # Format as Markdown table
        md_table = self._format_as_markdown_table(table)

        if len(md_table) > 50:  # Only if substantial
            sections.append(ExtractedSection(
                content=md_table,
                heading=None,  # Don't create separate heading
                heading_level=0,
                page_number=page_num,
                chunk_type=ChunkType.TABLE,
            ))

    return sections

def _format_as_markdown_table(self, table: list[list]) -> str:
    """Convert table to Markdown format."""
    if not table:
        return ""

    lines = []

    # Header row
    header = [str(cell).strip() if cell else "" for cell in table[0]]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    # Data rows
    for row in table[1:]:
        cells = [str(cell).strip() if cell else "" for cell in row]
        # Pad if needed
        while len(cells) < len(header):
            cells.append("")
        lines.append("| " + " | ".join(cells[:len(header)]) + " |")

    return "\n".join(lines)
```

---

## Implementation Order

### Phase 1: Quick Fixes (Do First)
1. **Chunk Merging** - Eliminates tiny chunks immediately
2. **Heading Detection Fix** - Reduces false positives

### Phase 2: Quality Improvements
3. **Better Table Handling** - Tables become useful chunks
4. **PDF → Markdown Option** - Best quality for new documents

### Phase 3: Reprocessing
5. **Reindex existing documents** with improved chunking
6. **Regenerate embeddings** for merged/improved chunks

---

## Verification Plan

### Test Cases

1. **Minimum Chunk Size**
   ```sql
   -- Should return 0 after fix
   SELECT COUNT(*) FROM robomonkey_docs.doc_chunk
   WHERE char_count < 50;
   ```

2. **Average Chunk Quality**
   ```sql
   SELECT
     AVG(char_count) as avg_chars,
     MIN(char_count) as min_chars,
     MAX(char_count) as max_chars,
     COUNT(*) FILTER (WHERE char_count < 100) as tiny_chunks
   FROM robomonkey_docs.doc_chunk;
   ```

3. **Table Chunk Detection**
   ```sql
   SELECT COUNT(*) FROM robomonkey_docs.doc_chunk
   WHERE chunk_type = 'table';
   ```

### Manual Verification

1. Reindex a problematic PDF
2. Browse chunks in UI
3. Verify no tiny meaningless chunks
4. Verify tables are coherent
5. Test search quality

---

## Dependencies

| Solution | New Dependencies | Notes |
|----------|-----------------|-------|
| Chunk Merging | None | Pure Python |
| Heading Fix | None | Pure Python |
| Table Handling | None | Pure Python |
| Marker | `marker-pdf` | ~2GB models, GPU recommended |
| Docling | `docling` | IBM, lighter weight |

---

## Rollback Plan

All changes are backward compatible:
- New chunking logic only affects new/reindexed documents
- Can revert by reindexing with old code
- Database schema unchanged

---

## Open Questions

1. Should we keep the original pdfplumber extraction as fallback?
2. Do we want to store both PDF and Markdown versions?
3. Should chunk merging be configurable (min size threshold)?
4. How to handle very large tables that exceed max chunk size?

---

## References

- [Marker](https://github.com/VikParuchuri/marker) - ML-based PDF to Markdown
- [Docling](https://github.com/DS4SD/docling) - IBM document converter
- [pdfplumber](https://github.com/jsvine/pdfplumber) - Current PDF extractor
- [Unstructured.io](https://unstructured.io/) - Another option for document processing
