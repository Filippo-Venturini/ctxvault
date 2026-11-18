from pypdf import PdfReader
from docx import Document
from pathlib import Path, PurePosixPath
from ctxvault.core.exceptions import UnsupportedFileTypeError, ExtractionError
import csv
import hashlib
from html.parser import HTMLParser

SUPPORTED_EXT = {'.txt', '.md', '.pdf', '.docx', '.html', '.htm', '.csv'}

# Tags whose contents are not readable document text.
_HTML_SKIP_TAGS = frozenset({'script', 'style', 'noscript', 'template'})

# Block / break elements: insert a word separator around these so adjacent
# blocks do not glue together. Inline tags are concatenated as they are.
_HTML_BLOCK_TAGS = frozenset({
    'address', 'article', 'aside', 'blockquote', 'body', 'br', 'caption',
    'dd', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer',
    'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'header', 'hr',
    'html', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table',
    'tbody', 'td', 'tfoot', 'th', 'thead', 'title', 'tr', 'ul',
})

# Marker inserted at block boundaries; never appears in HTML text nodes.
_HTML_BLOCK_SEP = '\0'


class _ReadableHTMLExtractor(HTMLParser):
    """Collect visible text; drop scripts/styles and separate only on blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and tag in _HTML_BLOCK_TAGS:
            self._parts.append(_HTML_BLOCK_SEP)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _HTML_SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth == 0 and tag in _HTML_BLOCK_TAGS:
            self._parts.append(_HTML_BLOCK_SEP)

    def handle_startendtag(self, tag: str, attrs) -> None:
        # Void / self-closing tags (e.g. <br/>): treat like a block break.
        tag = tag.lower()
        if tag in _HTML_SKIP_TAGS:
            return
        if self._skip_depth == 0 and tag in _HTML_BLOCK_TAGS:
            self._parts.append(_HTML_BLOCK_SEP)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        # Concatenate inline text as-is; only block boundaries become spaces.
        joined = "".join(self._parts)
        chunks = [chunk.strip() for chunk in joined.split(_HTML_BLOCK_SEP) if chunk.strip()]
        return " ".join(chunks)

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

def _detect_csv_delimiter(sample: str) -> str:
    """Sniff comma / semicolon / tab / pipe; fall back to comma."""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
        return dialect.delimiter
    except csv.Error:
        return ','

def _extract_from_csv(path: str)->str:
    # One retrievable line per data row, with header names kept beside values:
    # "name: Sourdough, price: 6.50".
    try:
        with open(file=path, mode='r', encoding='utf-8-sig', newline='') as f:
            sample = f.read(8192)
            f.seek(0)
            delimiter = _detect_csv_delimiter(sample) if sample.strip() else ','
            rows = list(csv.reader(f, delimiter=delimiter))
        if not rows:
            return ""
        headers = rows[0]
        lines: list[str] = []
        for row in rows[1:]:
            if not any(cell.strip() for cell in row):
                continue
            pairs = [
                f"{header}: {row[i] if i < len(row) else ''}"
                for i, header in enumerate(headers)
            ]
            # Cells past the header are kept, appended without a header name.
            for extra in row[len(headers):]:
                pairs.append(extra)
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
    elif suffix in ('.html', '.htm'):
        return _extract_from_html(path=path), suffix
    elif suffix == '.csv':
        return _extract_from_csv(path=path), suffix
