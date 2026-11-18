from pypdf import PdfReader
from docx import Document
from pathlib import Path, PurePosixPath
from ctxvault.core.exceptions import UnsupportedFileTypeError, ExtractionError
import csv
import hashlib
from html.parser import HTMLParser

SUPPORTED_EXT = {'.txt', '.md', '.pdf', '.docx', '.html', '.csv'}

# Tags whose contents are not readable document text.
_HTML_SKIP_TAGS = frozenset({'script', 'style'})


class _ReadableHTMLExtractor(HTMLParser):
    """Collect visible text; drop scripts, styles and all markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in _HTML_SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _HTML_SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        # Join discrete text nodes with a space so adjacent tags (</h1><p>)
        # do not glue words together, then collapse leftover whitespace.
        return " ".join(part.strip() for part in self._parts if part.strip())

def _extract_from_txt(path: str)->str:
    try:
        with open(file=path, mode='r', encoding='utf-8') as f:
            txt_content = f.read()
        return txt_content
    except Exception as e:
        raise ExtractionError(f"Failed to extract .txt {path}: {e}")

def _extract_from_md(path: str)->str:
    # Markdown goes to the chunker as written: the headings are what it
    # splits on and what it prefixes each section with, and the agent reads
    # markdown as well as anyone. Rendering it to HTML and stripping the tags
    # threw the headings away before the chunker ever saw them.
    try:
        with open(file=path, mode='r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise ExtractionError(f"Failed to extract .md {path}: {e}")

def _extract_from_pdf(path: str)->str:
    try:
        reader = PdfReader(stream=path)
        pdf_content = ''.join([(p.extract_text() or '').strip() for p in reader.pages])
        return pdf_content
    except Exception as e:
        raise ExtractionError(f"Failed to extract .pdf {path}: {e}")

def _extract_from_docx(path: str)->str:
    try:
        f = open(file=path, mode='rb')
        document = Document(f)
        docx_content = ''.join([p.text.strip() for p in document.paragraphs if p.text.strip])
        f.close()
        return docx_content
    except Exception as e:
        raise ExtractionError(f"Failed to extract .docx {path}: {e}")

def _extract_from_html(path: str)->str:
    try:
        with open(file=path, mode='r', encoding='utf-8') as f:
            raw = f.read()
        parser = _ReadableHTMLExtractor()
        parser.feed(raw)
        parser.close()
        return parser.text()
    except Exception as e:
        raise ExtractionError(f"Failed to extract .html {path}: {e}")

def _extract_from_csv(path: str)->str:
    # One retrievable line per data row, with header names kept beside values:
    # "name: Sourdough, price: 6.50".
    try:
        with open(file=path, mode='r', encoding='utf-8', newline='') as f:
            rows = list(csv.reader(f))
        if not rows:
            return ""
        headers = rows[0]
        lines: list[str] = []
        for row in rows[1:]:
            pairs = [
                f"{header}: {row[i] if i < len(row) else ''}"
                for i, header in enumerate(headers)
            ]
            lines.append(", ".join(pairs))
        return "\n".join(lines)
    except Exception as e:
        raise ExtractionError(f"Failed to extract .csv {path}: {e}")

def extract_text(path: str)-> tuple[str, str]:
    suffix = PurePosixPath(path).suffix

    if suffix not in SUPPORTED_EXT:
        raise UnsupportedFileTypeError(f"Unsupported file type: {suffix}")

    if suffix == '.txt':
        return _extract_from_txt(path=path), suffix
    elif suffix == '.md':
        return _extract_from_md(path=path), suffix
    elif suffix == '.pdf':
        return _extract_from_pdf(path=path), suffix
    elif suffix == '.docx':
        return _extract_from_docx(path=path), suffix
    elif suffix == '.html':
        return _extract_from_html(path=path), suffix
    elif suffix == '.csv':
        return _extract_from_csv(path=path), suffix
