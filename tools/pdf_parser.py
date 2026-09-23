"""
PDF parser: extract text from downloaded arXiv PDFs.

Strategy:
1. Try pymupdf (fitz) — fast, accurate.
2. Fall back to pypdf — slower but widely available.
3. If both fail, return empty string (abstract-only fallback handled upstream).

Extracts full text and attempts heuristic section segmentation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section detection patterns (heuristic, works for most arXiv CS papers)
# ---------------------------------------------------------------------------
_SECTION_PATTERNS = {
    "abstract":     re.compile(r"\babstract\b", re.IGNORECASE),
    "introduction": re.compile(r"\b(1\.?\s*)?introduction\b", re.IGNORECASE),
    "method":       re.compile(
        r"\b(method(ology)?|approach|model|architecture|proposed)\b",
        re.IGNORECASE,
    ),
    "experiment":   re.compile(
        r"\b(experiment(s|al)?|evaluation|results?)\b", re.IGNORECASE
    ),
    "dataset":      re.compile(r"\b(dataset(s)?|data\s+collection)\b", re.IGNORECASE),
    "limitation":   re.compile(
        r"\b(limitation(s)?|future\s+work|discussion)\b", re.IGNORECASE
    ),
    "conclusion":   re.compile(r"\b(conclusion|summary)\b", re.IGNORECASE),
    "references":   re.compile(r"\breferences\b", re.IGNORECASE),
}


@dataclass
class ParsedPaper:
    raw_text: str
    sections: dict[str, str]  # section_name -> extracted text
    page_count: int = 0

    @property
    def abstract(self) -> str:
        return self.sections.get("abstract", "")

    @property
    def method_text(self) -> str:
        return self.sections.get("method", "")

    @property
    def limitation_text(self) -> str:
        return self.sections.get("limitation", "")

    @property
    def dataset_text(self) -> str:
        return self.sections.get("dataset", "")


# ---------------------------------------------------------------------------
# Backend imports (lazy)
# ---------------------------------------------------------------------------
def _try_pymupdf(path: Path) -> tuple[str, int] | None:
    try:
        import fitz  # pymupdf
    except ImportError:
        return None
    try:
        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        return "\n".join(pages), len(pages)
    except Exception as exc:
        logger.warning("pymupdf failed on %s: %s", path, exc)
        return None


def _try_pypdf(path: Path) -> tuple[str, int] | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return None
    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages), len(reader.pages)
    except Exception as exc:
        logger.warning("pypdf failed on %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
class PDFParser:

    def parse(self, pdf_path: Path) -> ParsedPaper | None:
        """
        Parse a PDF and return a ParsedPaper.
        Returns None if the file cannot be read by any backend.
        """
        if not pdf_path or not pdf_path.exists():
            logger.debug("PDF path not found: %s", pdf_path)
            return None

        result = _try_pymupdf(pdf_path) or _try_pypdf(pdf_path)
        if result is None:
            logger.warning("All PDF parsers failed for %s", pdf_path)
            return None

        raw_text, page_count = result
        raw_text = self._clean_text(raw_text)
        sections = self._segment_sections(raw_text)

        return ParsedPaper(raw_text=raw_text, sections=sections, page_count=page_count)

    # ------------------------------------------------------------------
    @staticmethod
    def _clean_text(text: str) -> str:
        """Remove excessive whitespace and common PDF artefacts."""
        # Collapse multiple blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove hyphenation at line breaks
        text = re.sub(r"-\n(\w)", r"\1", text)
        return text.strip()

    @staticmethod
    def _segment_sections(text: str) -> dict[str, str]:
        """
        Split the text into sections by detecting section headings.
        Returns a dict {section_name: text_content}.
        """
        lines = text.split("\n")
        # Find candidate heading lines (short, possibly numbered)
        heading_re = re.compile(r"^(\d+\.?\s+)?[A-Z].{3,60}$")

        section_boundaries: list[tuple[int, str]] = []  # (line_index, section_key)

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or not heading_re.match(stripped):
                continue
            for key, pattern in _SECTION_PATTERNS.items():
                if pattern.search(stripped):
                    section_boundaries.append((i, key))
                    break

        # Build section texts
        sections: dict[str, str] = {}
        for idx, (start_line, key) in enumerate(section_boundaries):
            end_line = (
                section_boundaries[idx + 1][0]
                if idx + 1 < len(section_boundaries)
                else len(lines)
            )
            # Stop at "references" — don't include citation text
            if key == "references":
                break
            content = "\n".join(lines[start_line + 1 : end_line]).strip()
            sections[key] = content[:4000]  # cap per-section at 4 k chars

        return sections
