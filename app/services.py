"""Supporting services: PDF extraction + OCR, translation, embeddings,
chunking, and Label Studio integration."""
import logging
from functools import lru_cache

import fitz  # PyMuPDF
import requests

from .config import settings

logger = logging.getLogger("psyche.services")


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------
def extract_text(pdf_bytes: bytes) -> dict:
    """Extract text from a PDF.

    Tries the embedded text layer first (fast). If the PDF is a scanned
    image (common for Persian documents), falls back to OCR.
    """
    text = ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PyMuPDF extraction failed: %s", exc)

    method = "text-layer"
    if len(text.strip()) < 100:
        logger.info("Sparse text layer detected -> running OCR")
        text = ocr_pdf(pdf_bytes)
        method = "ocr"

    return {"text": text.strip(), "method": method}


def extract_epub(epub_bytes: bytes) -> dict:
    """Extract plain text from an EPUB file.

    EPUBs are ZIP archives containing XHTML chapters.  We open the archive
    directly, find every .html/.xhtml entry (skipping nav/toc files), strip
    HTML tags with BeautifulSoup, and join the text in filename order.
    This approach is robust to spec variations and needs no temp file.
    """
    import io, zipfile, re
    from bs4 import BeautifulSoup

    try:
        zf = zipfile.ZipFile(io.BytesIO(epub_bytes))
        # Collect content entries: xhtml/html that are not nav/toc files
        doc_names = sorted([
            n for n in zf.namelist()
            if re.search(r'\.(x?html?)$', n, re.I)
            and not re.search(r'(nav|toc|cover|ncx)', n, re.I)
        ])
        if not doc_names:
            # Fallback: include everything that looks like markup
            doc_names = sorted([
                n for n in zf.namelist()
                if re.search(r'\.(x?html?)$', n, re.I)
            ])

        parts = []
        for name in doc_names:
            html = zf.read(name)
            soup = BeautifulSoup(html, "lxml")
            # Remove script/style noise
            for tag in soup(["script", "style", "head"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            if len(text.strip()) > 50:   # skip near-empty pages
                parts.append(text)

        return {"text": "\n\n".join(parts).strip(), "method": "epub"}
    except Exception as exc:  # noqa: BLE001
        logger.error("EPUB extraction failed: %s", exc)
        return {"text": "", "method": "epub"}


def ocr_pdf(pdf_bytes: bytes, lang: str = "fas+eng") -> str:
    """OCR a scanned PDF with Tesseract (Persian + English language packs)."""
    from pdf2image import convert_from_bytes
    import pytesseract

    pages = convert_from_bytes(pdf_bytes, dpi=300)
    return "\n".join(pytesseract.image_to_string(page, lang=lang) for page in pages)


def detect_language(text: str) -> str:
    """Lightweight Persian detection based on the Arabic Unicode block."""
    if not text:
        return "unknown"
    persian = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return "fa" if persian / max(len(text), 1) > 0.25 else "en"


# --------------------------------------------------------------------------
# Translation (LibreTranslate)
# --------------------------------------------------------------------------
class Translator:
    """Thin wrapper around a self-hosted LibreTranslate instance."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.libretranslate_url

    def _translate(self, text: str, source: str, target: str) -> str:
        if not text.strip():
            return text
        try:
            resp = requests.post(
                f"{self.base_url}/translate",
                json={"q": text, "source": source, "target": target, "format": "text"},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["translatedText"]
        except Exception as exc:  # noqa: BLE001
            logger.error("Translation failed (%s->%s): %s", source, target, exc)
            return text  # graceful fallback: keep original text

    def to_english(self, text: str) -> str:
        return self._translate(text, "fa", "en")

    def to_persian(self, text: str) -> str:
        return self._translate(text, "en", "fa")


# --------------------------------------------------------------------------
# Embeddings (multilingual sentence-transformers)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model: %s", settings.embedding_model)
    return SentenceTransformer(settings.embedding_model)


def embed(text: str) -> list[float]:
    """Return a normalised embedding vector for the given text.

    The model is multilingual, so Persian queries match English documents.
    """
    return _embedder().encode(text, normalize_embeddings=True).tolist()


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------
def chunk_text(text: str, size: int = 800, overlap: int = 120) -> list[str]:
    """Split text into overlapping word-windows for embedding."""
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return [c for c in chunks if c.strip()]


# --------------------------------------------------------------------------
# Label Studio integration
# --------------------------------------------------------------------------
class LabelStudio:
    """Push extracted documents into the Label Studio review queue and
    pull back the reviewer's decisions."""

    def __init__(self):
        self.url = settings.label_studio_url
        self.project_id = settings.label_studio_project_id
        self.headers = {"Authorization": f"Token {settings.label_studio_api_key}"}

    def push_task(self, staging_id: str, filename: str, text: str, language: str):
        """Send one extracted document to the review project."""
        task = {
            "data": {
                "staging_id": staging_id,
                "filename": filename,
                "language": language,
                # Label Studio renders large text fine; cap for safety.
                "text": text[:50_000],
            }
        }
        resp = requests.post(
            f"{self.url}/api/projects/{self.project_id}/import",
            json=[task],
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_tasks(self) -> list[dict]:
        """Return every task in the review project, annotations included."""
        resp = requests.get(
            f"{self.url}/api/projects/{self.project_id}/tasks",
            params={"fields": "all", "page_size": 1000},
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        # The API returns either a bare list or a paginated object.
        return body.get("tasks", body) if isinstance(body, dict) else body
