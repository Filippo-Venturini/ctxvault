from pypdf import PdfReader
from docx import Document
from pathlib import Path, PurePosixPath
from ctxvault.core.exceptions import UnsupportedFileTypeError, ExtractionError
import hashlib

SUPPORTED_EXT = {'.txt', '.md', '.pdf', '.docx'}

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
