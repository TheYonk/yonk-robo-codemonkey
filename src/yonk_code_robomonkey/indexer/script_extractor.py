"""Extract JavaScript/TypeScript from template files.

Handles extraction of <script> tags from:
- EJS templates (.ejs)
- HTML files (.html, .htm)
- Vue components (.vue)
- Svelte components (.svelte)
- Handlebars templates (.hbs, .handlebars)
- Astro components (.astro)
- JSP files (.jsp)
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List


@dataclass
class ScriptBlock:
    """Extracted script block with line mapping."""
    content: str  # JavaScript content
    start_line: int  # Line number in original file (1-indexed)
    end_line: int  # Line number in original file (1-indexed)
    language: str  # 'javascript' or 'typescript'


def extract_script_blocks(content: str, file_extension: str) -> List[ScriptBlock]:
    """Extract JavaScript/TypeScript from template file.

    Args:
        content: File content as string
        file_extension: File extension (e.g., '.ejs', '.vue')

    Returns:
        List of extracted script blocks with line mappings
    """
    blocks = []

    # Vue.js: extract <script> or <script setup> or <script lang="ts">
    if file_extension == ".vue":
        blocks.extend(_extract_vue_scripts(content))
    # Svelte: extract <script> or <script lang="ts">
    elif file_extension == ".svelte":
        blocks.extend(_extract_svelte_scripts(content))
    # Astro: extract frontmatter and script blocks
    elif file_extension == ".astro":
        blocks.extend(_extract_astro_scripts(content))
    # All other HTML-based templates: extract all <script> tags
    else:
        blocks.extend(_extract_html_script_tags(content))

    return blocks


def _extract_html_script_tags(content: str) -> List[ScriptBlock]:
    """Extract all <script> tags from HTML-like content.

    Handles:
    - <script>...</script>
    - <script type="text/javascript">...</script>
    - <script type="module">...</script>
    - <script lang="ts">...</script> (TypeScript)
    """
    blocks = []
    lines = content.split('\n')

    # Pattern to find <script> tags
    # Handles: <script>, <script type="...">, <script lang="ts">, etc.
    script_start_pattern = re.compile(r'<script(?:\s+[^>]*)?>',  re.IGNORECASE)
    script_end_pattern = re.compile(r'</script>', re.IGNORECASE)

    i = 0
    while i < len(lines):
        line = lines[i]
        start_match = script_start_pattern.search(line)

        if start_match:
            # Determine language from attributes
            lang = 'javascript'
            tag_content = start_match.group(0)
            if 'lang="ts"' in tag_content or 'lang=\'ts\'' in tag_content:
                lang = 'typescript'
            elif 'type="text/typescript"' in tag_content:
                lang = 'typescript'

            # Find the start of script content (after opening tag)
            start_line = i + 1  # 1-indexed
            script_lines = []

            # Check if opening and closing tags are on same line
            end_match_same_line = script_end_pattern.search(line, start_match.end())
            if end_match_same_line:
                # Single-line script tag
                script_content = line[start_match.end():end_match_same_line.start()]
                if script_content.strip():
                    blocks.append(ScriptBlock(
                        content=script_content,
                        start_line=start_line,
                        end_line=start_line,
                        language=lang
                    ))
                i += 1
                continue

            # Multi-line: collect until </script>
            # Add remainder of first line if any
            first_line_content = line[start_match.end():]
            if first_line_content.strip():
                script_lines.append(first_line_content)

            i += 1
            while i < len(lines):
                line = lines[i]
                end_match = script_end_pattern.search(line)

                if end_match:
                    # Found closing tag
                    # Add content before closing tag
                    before_close = line[:end_match.start()]
                    if before_close.strip():
                        script_lines.append(before_close)

                    end_line = i + 1  # 1-indexed
                    script_content = '\n'.join(script_lines)

                    if script_content.strip():
                        blocks.append(ScriptBlock(
                            content=script_content,
                            start_line=start_line,
                            end_line=end_line,
                            language=lang
                        ))
                    break
                else:
                    # Still inside script tag
                    script_lines.append(line)

                i += 1

        i += 1

    return blocks


def _extract_vue_scripts(content: str) -> List[ScriptBlock]:
    """Extract <script> blocks from Vue single-file components."""
    # Vue has a single <script> or <script setup> block
    # Can have lang="ts" for TypeScript
    return _extract_html_script_tags(content)


def _extract_svelte_scripts(content: str) -> List[ScriptBlock]:
    """Extract <script> blocks from Svelte components."""
    # Svelte can have multiple <script> blocks (module and instance)
    # Can have lang="ts" for TypeScript
    return _extract_html_script_tags(content)


def _extract_astro_scripts(content: str) -> List[ScriptBlock]:
    """Extract scripts from Astro components.

    Astro components have:
    1. Frontmatter (between --- fences at top)
    2. Regular <script> tags in the template
    """
    blocks = []
    lines = content.split('\n')

    # Extract frontmatter (TypeScript by default in Astro)
    if len(lines) > 0 and lines[0].strip() == '---':
        frontmatter_lines = []
        i = 1
        while i < len(lines):
            if lines[i].strip() == '---':
                # End of frontmatter
                frontmatter_content = '\n'.join(frontmatter_lines)
                if frontmatter_content.strip():
                    blocks.append(ScriptBlock(
                        content=frontmatter_content,
                        start_line=2,  # After first ---
                        end_line=i,  # Before second ---
                        language='typescript'
                    ))
                break
            frontmatter_lines.append(lines[i])
            i += 1

    # Also extract regular <script> tags
    blocks.extend(_extract_html_script_tags(content))

    return blocks


def combine_script_blocks(blocks: List[ScriptBlock]) -> tuple[str, dict[int, int]]:
    """Combine multiple script blocks into single source with line mapping.

    Args:
        blocks: List of extracted script blocks

    Returns:
        Tuple of (combined_source, line_map)
        line_map maps combined source line number -> original file line number
    """
    if not blocks:
        return "", {}

    combined_lines = []
    line_map = {}  # combined line -> original line

    current_line = 1
    for block in blocks:
        block_lines = block.content.split('\n')
        original_line = block.start_line

        for block_line in block_lines:
            combined_lines.append(block_line)
            line_map[current_line] = original_line
            current_line += 1
            original_line += 1

        # Add blank line between blocks for separation
        combined_lines.append('')
        line_map[current_line] = block.end_line  # Map separator to end of previous block
        current_line += 1

    combined_source = '\n'.join(combined_lines)
    return combined_source, line_map
