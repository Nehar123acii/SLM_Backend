"""
backend/etl/ocr_engine.py
=========================
Local OCR and Scanned Document Processing Engine.

Capabilities:
- Validates file format by magic bytes (PDF, PNG, JPEG, TIFF) and enforces size/page limits.
- Uses PyMuPDF (pymupdf) for PDF text extraction, metadata, and page rendering.
- Uses local Tesseract OCR (pytesseract) for scanned/image-based pages and image files.
- Two-stage PDF extraction: attempts native text first; falls back to OCR if text is insufficient.
- Tracks page numbers, extraction method (native_text vs ocr), confidences, bounding boxes, warnings.
- Supports English ('eng') by default, plus Hindi ('hin') and Kannada ('kan') when language packs are installed.
- Zero raw PII/text logging; safe cleanup of temporary pixmaps and buffers.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from PIL import Image, ImageOps, ImageStat
import pandas as pd
import pymupdf
import pytesseract

from backend.config import settings
from backend.security import mask

logger = logging.getLogger("ocr_engine")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class OCRError(Exception):
    """Base exception for OCR and document ingestion errors."""
    pass


class UnsupportedDocumentError(OCRError):
    """Raised when the document format or file signature is unsupported."""
    pass


class MalformedDocumentError(OCRError):
    """Raised when a document is corrupted or cannot be parsed."""
    pass


class EncryptedDocumentError(OCRError):
    """Raised when a PDF is password-protected or encrypted."""
    pass


class OversizedDocumentError(OCRError):
    """Raised when file size or page count exceeds configured limits."""
    pass


class TesseractNotFoundError(OCRError):
    """Raised when Tesseract OCR binary is required but not installed or in PATH."""
    pass


class LanguageNotInstalledError(OCRError):
    """Raised when requested Tesseract language data (.traineddata) is missing."""
    pass


class UnsupportedLanguageError(OCRError):
    """Raised when an unrecognized language code is requested."""
    pass


# ---------------------------------------------------------------------------
# Magic Byte Signatures
# ---------------------------------------------------------------------------
FILE_SIGNATURES: Dict[str, List[bytes]] = {
    "PDF": [b"%PDF-"],
    "PNG": [b"\x89PNG\r\n\x1a\n"],
    "JPEG": [b"\xff\xd8\xff"],
    "TIFF": [b"II*\x00", b"MM\x00*"],
}

SUPPORTED_OCR_LANGUAGES: Dict[str, str] = {
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    "hi": "hin",
    "hin": "hin",
    "hindi": "hin",
    "kn": "kan",
    "kan": "kan",
    "kannada": "kan",
}

# Standard Windows paths where Tesseract is frequently installed
DEFAULT_WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
WINDOWS_TESSERACT_PATHS = [
    DEFAULT_WINDOWS_TESSERACT,
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


# ---------------------------------------------------------------------------
# Tesseract Path & Language Discovery
# ---------------------------------------------------------------------------
def resolve_tesseract_cmd() -> Optional[str]:
    """
    Finds the Tesseract executable on the host system:
    1. Configured settings.tesseract_cmd or TESSERACT_CMD env var
    2. PATH lookup via shutil.which('tesseract')
    3. C:\\Program Files\\Tesseract-OCR\\tesseract.exe
    4. Common Windows installation locations
    Configures pytesseract.pytesseract.tesseract_cmd if found.
    """
    # 1. Env TESSERACT_CMD or settings.tesseract_cmd
    env_cmd = os.environ.get("TESSERACT_CMD") or getattr(settings, "tesseract_cmd", None)
    if env_cmd and os.path.exists(env_cmd):
        pytesseract.pytesseract.tesseract_cmd = env_cmd
        return env_cmd

    # 2. PATH lookup
    in_path = shutil.which("tesseract")
    if in_path:
        pytesseract.pytesseract.tesseract_cmd = in_path
        return in_path

    # 3. C:\Program Files\Tesseract-OCR\tesseract.exe
    if os.path.exists(DEFAULT_WINDOWS_TESSERACT):
        pytesseract.pytesseract.tesseract_cmd = DEFAULT_WINDOWS_TESSERACT
        return DEFAULT_WINDOWS_TESSERACT

    # 4. Common Windows installation locations
    if os.name == "nt":
        for win_path in WINDOWS_TESSERACT_PATHS:
            if os.path.exists(win_path):
                pytesseract.pytesseract.tesseract_cmd = win_path
                return win_path

    return None


def get_available_tesseract_languages() -> List[str]:
    """Returns list of installed Tesseract language codes, or empty list if unavailable."""
    cmd = resolve_tesseract_cmd()
    if not cmd:
        return []
    try:
        tessdata = settings.tessdata_dir or os.environ.get("TESSDATA_PREFIX")
        config_arg = f'--tessdata-dir "{tessdata}"' if tessdata else ""
        return pytesseract.get_languages(config=config_arg)
    except Exception as exc:
        logger.debug("Failed to query Tesseract languages: %s", exc)
        return []


def normalize_and_validate_language(lang_hint: Optional[str]) -> str:
    """
    Normalizes language hint to 3-letter Tesseract code ('eng', 'hin', 'kan'),
    or combined codes ('eng+hin+kan').
    Validates availability in Tesseract tessdata.
    """
    raw = (lang_hint or getattr(settings, "ocr_default_language", "eng") or "eng").strip().lower()
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    normalized_parts = []
    for p in parts:
        if p not in SUPPORTED_OCR_LANGUAGES:
            raise UnsupportedLanguageError(
                f"Unsupported OCR language '{p}'. Permitted languages: English ('eng'), "
                f"Hindi ('hin'), Kannada ('kan')."
            )
        normalized_parts.append(SUPPORTED_OCR_LANGUAGES[p])

    target_code = "+".join(normalized_parts)

    # Verify each language is installed in Tesseract
    available = get_available_tesseract_languages()
    if available:
        for code in normalized_parts:
            if code not in available:
                raise LanguageNotInstalledError(
                    f"Tesseract language data for '{code}' is not installed in tessdata. "
                    f"Available languages: {available}. To process {code.upper()} documents, "
                    f"download '{code}.traineddata' from github.com/tesseract-ocr/tessdata "
                    f"and place it in your Tesseract tessdata directory."
                )
    return target_code


# ---------------------------------------------------------------------------
# Image Preprocessing & Token Sanitization
# ---------------------------------------------------------------------------
RE_PHONE_TOKEN = re.compile(r"(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9](?:[\-\s]?\d){9}")
RE_EMAIL_TOKEN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
RE_AADHAAR_TOKEN = re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}\b|\b\d{12}\b")
RE_PAN_TOKEN = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")


def _mask_token_sensitive(token: str) -> str:
    """Masks identifier values in bounding box tokens so raw data is never persisted in SQLite."""
    clean = token.strip()
    if RE_PHONE_TOKEN.search(clean):
        return mask("phone", clean)
    if RE_EMAIL_TOKEN.search(clean):
        return mask("email", clean)
    if RE_AADHAAR_TOKEN.search(clean):
        return mask("aadhaar", clean)
    if RE_PAN_TOKEN.search(clean):
        return mask("pan", clean)
    return clean


def preprocess_image_for_ocr(image: Image.Image) -> Tuple[Image.Image, float]:
    """
    Preprocesses an image before OCR recognition:
    1. Converts to grayscale.
    2. Inverts if dark-mode (mean brightness below 100).
    3. Auto-contrast enhancement.
    4. Upscales small images (minimum width 1200 px).
    Returns (processed_image, scale_factor).
    """
    gray = image.convert("L")

    # Invert if dark-mode (mean brightness below 100)
    stat = ImageStat.Stat(gray)
    mean_brightness = stat.mean[0] if stat.mean else 128.0
    if mean_brightness < 100.0:
        gray = ImageOps.invert(gray)

    # Auto-contrast enhancement
    gray = ImageOps.autocontrast(gray)

    # Upscale small images (minimum width 1200 px)
    orig_w, orig_h = gray.size
    scale = 1.0
    if orig_w < 1200:
        scale = 1200.0 / orig_w
        new_w = 1200
        new_h = int(round(orig_h * scale))
        gray = gray.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return gray, scale


# ---------------------------------------------------------------------------
# File Format & Safety Validation
# ---------------------------------------------------------------------------
def detect_document_format_from_bytes(header_bytes: bytes) -> Optional[str]:
    """Matches leading bytes against magic byte signatures for PDF, PNG, JPEG, TIFF."""
    for fmt, sigs in FILE_SIGNATURES.items():
        for sig in sigs:
            if header_bytes.startswith(sig):
                return fmt
    return None


def validate_document_file(
    file_path: str,
    max_size_bytes: Optional[int] = None,
) -> str:
    """
    Validates file existence, size, and magic bytes.
    Returns detected format ('PDF', 'PNG', 'JPEG', 'TIFF').
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    max_bytes = max_size_bytes or settings.ocr_max_file_size_bytes
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise MalformedDocumentError(f"Document file is empty (0 bytes): {os.path.basename(file_path)}")
    if file_size > max_bytes:
        raise OversizedDocumentError(
            f"Document file size ({file_size / (1024 * 1024):.1f} MB) exceeds maximum "
            f"permitted limit of {max_bytes / (1024 * 1024):.1f} MB."
        )

    with open(file_path, "rb") as f:
        header = f.read(16)

    detected_format = detect_document_format_from_bytes(header)
    if not detected_format:
        ext = os.path.splitext(file_path)[1].lower()
        raise UnsupportedDocumentError(
            f"Unsupported or corrupted file '{os.path.basename(file_path)}' (extension: {ext}). "
            f"File signature did not match PDF, PNG, JPEG, or TIFF."
        )

    return detected_format


# ---------------------------------------------------------------------------
# Rule: Native Text Sufficiency
# ---------------------------------------------------------------------------
def is_native_text_sufficient(
    page_text: str,
    min_chars: Optional[int] = None,
    min_words: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Determines whether native PDF text extraction is sufficient or if OCR is required.

    Documented Rule:
    1. If extracted text is completely empty or whitespace only -> Insufficient (scanned/blank).
    2. Count alphanumeric word tokens and total alphanumeric characters (excluding formatting).
    3. If alphanumeric characters >= min_chars (default 50) AND words >= min_words (default 5):
       -> Sufficient: preserve native text without unnecessary OCR overhead.
    4. Otherwise:
       -> Insufficient: attempt local OCR on the rendered page image.
    """
    threshold_chars = min_chars or settings.ocr_min_native_text_chars
    threshold_words = min_words or settings.ocr_min_native_words

    cleaned = page_text.strip()
    if not cleaned:
        return False, "Page contains 0 characters of native text."

    alpha_chars = sum(1 for c in cleaned if c.isalnum())
    words = [w for w in re.split(r"\s+", cleaned) if len(w) >= 2 and any(ch.isalnum() for ch in w)]

    if alpha_chars >= threshold_chars and len(words) >= threshold_words:
        return True, f"Native text sufficient ({alpha_chars} chars, {len(words)} words >= threshold {threshold_chars})."

    return (
        False,
        f"Native text insufficient ({alpha_chars} chars < {threshold_chars} or {len(words)} words < {threshold_words}). Attempting OCR.",
    )


# ---------------------------------------------------------------------------
# Pluggable OCR Runner (supports mock injection for unit tests)
# ---------------------------------------------------------------------------
_CUSTOM_OCR_RUNNER: Optional[Callable[[Image.Image, str], Dict[str, Any]]] = None


def set_custom_ocr_runner(
    runner: Optional[Callable[[Image.Image, str], Dict[str, Any]]]
) -> None:
    """Injects a custom OCR runner for deterministic testing without Tesseract."""
    global _CUSTOM_OCR_RUNNER
    _CUSTOM_OCR_RUNNER = runner


def default_tesseract_ocr_runner(image: Image.Image, lang: str = "eng") -> Dict[str, Any]:
    """
    Executes Tesseract OCR on a PIL Image and returns structured word data.
    Uses pytesseract.image_to_data for word text, confidences, and bounding boxes.
    """
    cmd = resolve_tesseract_cmd()
    if not cmd:
        raise TesseractNotFoundError(
            "Tesseract OCR executable is not installed or configured on the system. "
            "Please install Tesseract OCR and set TESSERACT_CMD or add it to your PATH."
        )

    tessdata = settings.tessdata_dir or os.environ.get("TESSDATA_PREFIX")
    config_arg = f'--tessdata-dir "{tessdata}"' if tessdata else ""

    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=config_arg,
        output_type=pytesseract.Output.DICT,
        timeout=settings.ocr_timeout_seconds,
    )
    return data


def run_ocr_on_image(image: Image.Image, lang: str = "eng") -> Dict[str, Any]:
    """Dispatches OCR to the configured or mocked OCR runner."""
    if _CUSTOM_OCR_RUNNER is not None:
        return _CUSTOM_OCR_RUNNER(image, lang)
    return default_tesseract_ocr_runner(image, lang)


# ---------------------------------------------------------------------------
# Structured Document Extractor
# ---------------------------------------------------------------------------
class DocumentExtractor:
    """
    Extracts text, bounding boxes, and provenance records from PDF and image files.
    """

    def __init__(
        self,
        language: Optional[str] = None,
        max_pages: Optional[int] = None,
        min_native_chars: Optional[int] = None,
        confidence_threshold: Optional[float] = None,
    ) -> None:
        self.language = normalize_and_validate_language(language)
        self.max_pages = max_pages or settings.ocr_max_pages
        self.min_native_chars = min_native_chars or settings.ocr_min_native_text_chars
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else getattr(settings, "ocr_confidence_threshold", 0.8)
        )

    def extract(self, file_path: str) -> Tuple[pd.DataFrame, List[str], Dict[str, str], Dict[str, Any]]:
        """
        Extracts structured records and metadata from a document file.
        Returns:
            df: DataFrame of extracted lines with provenance
            warnings: List of extraction warnings
            mapping: Column normalization mapping
            metadata: Comprehensive document and extraction metadata
        """
        start_time = time.perf_counter()
        doc_format = validate_document_file(file_path)
        filename = os.path.basename(file_path)

        if doc_format == "PDF":
            records, warnings, page_summaries, bboxes = self._extract_pdf(file_path)
        else:
            records, warnings, page_summaries, bboxes = self._extract_image(file_path, doc_format)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Build DataFrame
        if not records:
            # Fallback single record indicating empty document
            records = [{
                "record_ref": "DOC-P01-L001",
                "page_number": 1,
                "line_number": 1,
                "text_content": "[NO USABLE TEXT FOUND]",
                "extraction_method": "ocr" if doc_format != "PDF" else "native_text",
                "confidence": 0.0,
                "char_length": 0,
                "status": "EMPTY",
                "source_reference": f"{filename}:page_1:line_1",
            }]
            warnings.append("Document yielded 0 text lines across all pages.")

        df = pd.DataFrame(records)

        # Compute aggregate metrics
        total_pages = len(page_summaries)
        native_pages = sum(1 for p in page_summaries if p.get("method") == "native_text")
        ocr_pages = sum(1 for p in page_summaries if p.get("method") == "ocr")
        empty_pages = sum(1 for p in page_summaries if p.get("status") == "EMPTY")
        failed_pages = sum(1 for p in page_summaries if p.get("status") == "FAILED")
        total_chars = int(df["char_length"].sum()) if "char_length" in df.columns else 0

        # Safe logging: duration and counts only — NEVER log extracted text
        logger.info(
            "Extracted document '%s': format=%s, pages=%d, native=%d, ocr=%d, empty=%d, "
            "failed=%d, duration=%dms",
            filename,
            doc_format,
            total_pages,
            native_pages,
            ocr_pages,
            empty_pages,
            failed_pages,
            duration_ms,
        )

        metadata: Dict[str, Any] = {
            "source_type": "document_ocr",
            "document_format": doc_format,
            "original_filename": filename,
            "file_size_bytes": os.path.getsize(file_path),
            "total_pages": total_pages,
            "pages_native_text": native_pages,
            "pages_ocr": ocr_pages,
            "pages_empty": empty_pages,
            "pages_failed": failed_pages,
            "total_characters": total_chars,
            "ocr_language": self.language,
            "processing_duration_ms": duration_ms,
            "extraction_warnings": warnings,
            "page_details": page_summaries,
            "bounding_boxes_available": bool(bboxes),
            "bounding_boxes": bboxes,
        }

        mapping = {c: c for c in df.columns}
        return df, warnings, mapping, metadata

    def _extract_pdf(
        self, file_path: str
    ) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]], Dict[str, Any]]:
        warnings: List[str] = []
        records: List[Dict[str, Any]] = []
        page_summaries: List[Dict[str, Any]] = []
        all_bboxes: Dict[str, Any] = {}
        filename = os.path.basename(file_path)

        try:
            doc = pymupdf.open(file_path)
        except Exception as exc:
            raise MalformedDocumentError(f"Malformed or corrupted PDF file '{filename}': {str(exc)}")

        try:
            if doc.is_encrypted:
                raise EncryptedDocumentError(
                    f"Encrypted or password-protected PDF '{filename}' cannot be processed. "
                    "Please provide an unencrypted document."
                )

            total_pages = doc.page_count
            if total_pages == 0:
                raise MalformedDocumentError(f"PDF file '{filename}' contains 0 pages.")
            if total_pages > self.max_pages:
                raise OversizedDocumentError(
                    f"PDF page count ({total_pages}) exceeds configured limit of {self.max_pages} pages."
                )

            for p_idx in range(total_pages):
                page_num = p_idx + 1
                page = doc[p_idx]
                page_ref = f"page_{page_num}"

                # 1. Native text extraction
                native_text = page.get_text("text").strip()
                is_sufficient, reason = is_native_text_sufficient(
                    native_text, min_chars=self.min_native_chars
                )

                if is_sufficient:
                    # Native text is sufficient
                    page_records, page_bboxes = self._parse_native_page(page, page_num, filename)
                    records.extend(page_records)
                    all_bboxes[page_ref] = page_bboxes
                    page_summaries.append({
                        "page_number": page_num,
                        "method": "native_text",
                        "status": "SUCCESS",
                        "character_count": sum(r["char_length"] for r in page_records),
                        "line_count": len(page_records),
                        "confidence": 1.0,
                        "reason": reason,
                    })
                else:
                    # Native text insufficient -> Attempt OCR
                    warnings.append(f"Page {page_num}: {reason}")
                    pix = None
                    try:
                        # Render page at 200 DPI for reliable OCR
                        pix = page.get_pixmap(dpi=200)
                        img_bytes = pix.tobytes("png")
                        pil_img = Image.open(io.BytesIO(img_bytes))

                        page_records, page_bboxes, page_status, page_warn = self._parse_ocr_image(
                            pil_img, page_num=page_num, source_name=filename
                        )
                        records.extend(page_records)
                        all_bboxes[page_ref] = page_bboxes
                        if page_warn:
                            warnings.append(f"Page {page_num}: {page_warn}")

                        page_summaries.append({
                            "page_number": page_num,
                            "method": "ocr",
                            "status": page_status,
                            "character_count": sum(r["char_length"] for r in page_records),
                            "line_count": len(page_records),
                            "confidence": round(
                                float(sum(r["confidence"] for r in page_records) / max(1, len(page_records))),
                                2,
                            ),
                            "reason": "Scanned page recognized via local Tesseract OCR.",
                        })

                    except TesseractNotFoundError as tne:
                        warnings.append(f"Page {page_num}: OCR failed — {str(tne)}")
                        page_summaries.append({
                            "page_number": page_num,
                            "method": "ocr",
                            "status": "FAILED",
                            "character_count": 0,
                            "line_count": 0,
                            "confidence": 0.0,
                            "reason": str(tne),
                        })
                        records.append({
                            "record_ref": f"DOC-P{page_num:02d}-L001",
                            "page_number": page_num,
                            "line_number": 1,
                            "text_content": "[OCR FAILED: TESSERACT NOT INSTALLED]",
                            "extraction_method": "ocr",
                            "confidence": 0.0,
                            "char_length": 0,
                            "status": "FAILED",
                            "source_reference": f"{filename}:page_{page_num}:line_1",
                        })
                    except Exception as exc:
                        warnings.append(f"Page {page_num}: OCR processing error: {type(exc).__name__}")
                        page_summaries.append({
                            "page_number": page_num,
                            "method": "ocr",
                            "status": "FAILED",
                            "character_count": 0,
                            "line_count": 0,
                            "confidence": 0.0,
                            "reason": f"OCR failed with {type(exc).__name__}",
                        })
                        records.append({
                            "record_ref": f"DOC-P{page_num:02d}-L001",
                            "page_number": page_num,
                            "line_number": 1,
                            "text_content": f"[OCR ERROR: {type(exc).__name__}]",
                            "extraction_method": "ocr",
                            "confidence": 0.0,
                            "char_length": 0,
                            "status": "FAILED",
                            "source_reference": f"{filename}:page_{page_num}:line_1",
                        })
                    finally:
                        # Clean up pixmap and image buffers safely
                        if pix is not None:
                            del pix

        finally:
            doc.close()

        return records, warnings, page_summaries, all_bboxes

    def _extract_image(
        self, file_path: str, doc_format: str
    ) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]], Dict[str, Any]]:
        warnings: List[str] = []
        records: List[Dict[str, Any]] = []
        filename = os.path.basename(file_path)

        try:
            with Image.open(file_path) as img:
                # Validate image dimensions (10,000 px max dimension)
                width, height = img.size
                if width > 10000 or height > 10000:
                    raise OversizedDocumentError(
                        f"Image dimensions ({width}x{height}) exceed maximum limit of 10,000x10,000 pixels."
                    )

                page_records, page_bboxes, page_status, page_warn = self._parse_ocr_image(
                    img, page_num=1, source_name=filename
                )
                records.extend(page_records)
                if page_warn:
                    warnings.append(f"Image {filename}: {page_warn}")

                page_summaries = [{
                    "page_number": 1,
                    "method": "ocr",
                    "status": page_status,
                    "character_count": sum(r["char_length"] for r in page_records),
                    "line_count": len(page_records),
                    "confidence": round(
                        float(sum(r["confidence"] for r in page_records) / max(1, len(page_records))),
                        2,
                    ),
                    "reason": f"Image format {doc_format} processed via local OCR.",
                }]
                all_bboxes = {"page_1": page_bboxes}

        except OCRError:
            raise
        except Exception as exc:
            raise MalformedDocumentError(f"Malformed or corrupted image file '{filename}': {str(exc)}")

        return records, warnings, page_summaries, all_bboxes

    def _parse_native_page(
        self, page: pymupdf.Page, page_num: int, filename: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Parses native PDF page text into line records with word-level coordinates."""
        records: List[Dict[str, Any]] = []
        bboxes: List[Dict[str, Any]] = []

        # Get words: (x0, y0, x1, y1, word, block_no, line_no, word_no)
        raw_words = page.get_text("words")

        # Group words by (block_no, line_no)
        lines_dict: Dict[Tuple[int, int], List[Tuple[Any, ...]]] = {}
        for w in raw_words:
            key = (w[5], w[6])
            lines_dict.setdefault(key, []).append(w)

        line_idx = 1
        for key in sorted(lines_dict.keys()):
            word_list = lines_dict[key]
            line_text = " ".join(str(w[4]) for w in word_list).strip()
            if not line_text:
                continue

            # Compute bounding box enclosing the line
            x0 = min(w[0] for w in word_list)
            y0 = min(w[1] for w in word_list)
            x1 = max(w[2] for w in word_list)
            y1 = max(w[3] for w in word_list)

            record_ref = f"DOC-P{page_num:02d}-L{line_idx:03d}"
            records.append({
                "record_ref": record_ref,
                "page_number": page_num,
                "line_number": line_idx,
                "text_content": line_text,
                "extraction_method": "native_text",
                "confidence": 1.0,
                "char_length": len(line_text),
                "status": "SUCCESS",
                "source_reference": f"{filename}:page_{page_num}:line_{line_idx}",
            })
            bboxes.append({
                "record_ref": record_ref,
                "page_number": page_num,
                "line_number": line_idx,
                "bbox": [round(float(x0), 1), round(float(y0), 1), round(float(x1), 1), round(float(y1), 1)],
                "words": [
                    {
                        "text": _mask_token_sensitive(str(w[4])),
                        "bbox": [round(float(w[0]), 1), round(float(w[1]), 1), round(float(w[2]), 1), round(float(w[3]), 1)],
                        "confidence": 1.0,
                    }
                    for w in word_list
                ],
            })
            line_idx += 1

        if not records:
            # Fallback if get_text("words") was empty but get_text("text") had text
            full_text = page.get_text("text").strip()
            if full_text:
                for idx, line in enumerate(full_text.splitlines(), start=1):
                    line_clean = line.strip()
                    if line_clean:
                        records.append({
                            "record_ref": f"DOC-P{page_num:02d}-L{idx:03d}",
                            "page_number": page_num,
                            "line_number": idx,
                            "text_content": line_clean,
                            "extraction_method": "native_text",
                            "confidence": 1.0,
                            "char_length": len(line_clean),
                            "status": "SUCCESS",
                            "source_reference": f"{filename}:page_{page_num}:line_{idx}",
                        })

        return records, bboxes

    def _parse_ocr_image(
        self, image: Image.Image, page_num: int, source_name: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, Optional[str]]:
        """
        Executes OCR on an image with preprocessing and builds line records
        with coordinates and per-token confidences.
        """
        preprocessed_img, scale = preprocess_image_for_ocr(image)
        ocr_data = run_ocr_on_image(preprocessed_img, lang=self.language)

        records: List[Dict[str, Any]] = []
        bboxes: List[Dict[str, Any]] = []
        conf_threshold = getattr(self, "confidence_threshold", 0.8)

        texts = ocr_data.get("text", [])
        confs = ocr_data.get("conf", [])
        lefts = ocr_data.get("left", [])
        tops = ocr_data.get("top", [])
        widths = ocr_data.get("width", [])
        heights = ocr_data.get("height", [])
        block_nums = ocr_data.get("block_num", [])
        line_nums = ocr_data.get("line_num", [])

        # Group words by (block_num, line_num)
        lines: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
        for idx in range(len(texts)):
            w_text = str(texts[idx]).strip()
            if not w_text:
                continue

            raw_conf = confs[idx] if idx < len(confs) else -1
            try:
                conf_val = float(raw_conf)
                # Tesseract reports -1 for spaces/block headers
                if conf_val < 0:
                    conf_val = 80.0
                conf_normalized = max(0.0, min(1.0, conf_val / 100.0))
            except (ValueError, TypeError):
                conf_normalized = 0.80

            b_num = block_nums[idx] if idx < len(block_nums) else 0
            l_num = line_nums[idx] if idx < len(line_nums) else 0
            x = lefts[idx] if idx < len(lefts) else 0
            y = tops[idx] if idx < len(tops) else 0
            w = widths[idx] if idx < len(widths) else 0
            h = heights[idx] if idx < len(heights) else 0

            # Scale coordinates back to original image space
            orig_bbox = [c / scale for c in [float(x), float(y), float(x + w), float(y + h)]]
            is_low_conf = (conf_normalized < conf_threshold)

            lines.setdefault((b_num, l_num), []).append({
                "text": w_text,
                "conf": conf_normalized,
                "bbox": orig_bbox,
                "low_confidence": is_low_conf,
            })

        line_idx = 1
        for key in sorted(lines.keys()):
            word_list = lines[key]
            line_str = " ".join(w["text"] for w in word_list).strip()
            if not line_str:
                continue

            avg_conf = round(float(sum(w["conf"] for w in word_list) / max(1, len(word_list))), 2)
            x0 = min(w["bbox"][0] for w in word_list)
            y0 = min(w["bbox"][1] for w in word_list)
            x1 = max(w["bbox"][2] for w in word_list)
            y1 = max(w["bbox"][3] for w in word_list)

            bx_int = int(round(x0))
            by_int = int(round(y0))
            bw_int = int(round(x1 - x0))
            bh_int = int(round(y1 - y0))
            bbox_locator = f"page_{page_num}_bbox_{bx_int}_{by_int}_{bw_int}_{bh_int}"

            record_ref = f"DOC-P{page_num:02d}-L{line_idx:03d}"
            status = "LOW_CONFIDENCE" if avg_conf < conf_threshold else "SUCCESS"
            is_line_low_conf = (status == "LOW_CONFIDENCE")

            records.append({
                "record_ref": record_ref,
                "page_number": page_num,
                "line_number": line_idx,
                "text_content": line_str,
                "extraction_method": "ocr",
                "confidence": avg_conf,
                "char_length": len(line_str),
                "status": status,
                "low_confidence": is_line_low_conf,
                "bbox_locator": bbox_locator,
                "source_reference": f"{source_name}:page_{page_num}:line_{line_idx}",
            })
            bboxes.append({
                "record_ref": record_ref,
                "page_number": page_num,
                "line_number": line_idx,
                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                "bbox_locator": bbox_locator,
                "words": [
                    {
                        "text": _mask_token_sensitive(w["text"]),
                        "bbox": [round(c, 1) for c in w["bbox"]],
                        "confidence": w["conf"],
                        "low_confidence": w.get("low_confidence", False),
                    }
                    for w in word_list
                ],
            })
            line_idx += 1

        if not records:
            # Empty / blank page
            record_ref = f"DOC-P{page_num:02d}-L001"
            records.append({
                "record_ref": record_ref,
                "page_number": page_num,
                "line_number": 1,
                "text_content": "[NO USABLE TEXT FOUND]",
                "extraction_method": "ocr",
                "confidence": 0.0,
                "char_length": 0,
                "status": "EMPTY",
                "low_confidence": True,
                "source_reference": f"{source_name}:page_{page_num}:line_1",
            })
            return records, bboxes, "EMPTY", "Page contains no readable OCR text."

        avg_page_conf = sum(r["confidence"] for r in records) / len(records)
        page_status = "LOW_CONFIDENCE" if avg_page_conf < conf_threshold else "SUCCESS"
        page_warn = f"Low OCR recognition confidence ({avg_page_conf:.2f} < {conf_threshold:.2f}). Human review advised." if page_status == "LOW_CONFIDENCE" else None

        return records, bboxes, page_status, page_warn
