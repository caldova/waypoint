"""Local report rendering for Contracts artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import quilldown


@dataclass(frozen=True)
class RenderedReport:
    markdown_path: Path
    docx_path: Path


def render_report(
    *,
    report_id: str,
    markdown: str,
    output_dir: Path,
) -> RenderedReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{report_id}.md"
    docx_path = output_dir / f"{report_id}.docx"

    markdown_path.write_text(markdown, encoding="utf-8")
    doc = quilldown.render_docx(
        quilldown.markdown_to_ir(markdown),
        {"theme": "github", "page_size": "letter", "page_numbers": True},
    )
    doc.save(docx_path)

    return RenderedReport(
        markdown_path=markdown_path,
        docx_path=docx_path,
    )
