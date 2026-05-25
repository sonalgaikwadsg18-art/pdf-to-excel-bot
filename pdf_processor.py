"""
PDF Processor v2 — Extracts text, tables (via pdfplumber), text positions,
and layout analysis for intelligent Excel generation.
"""
import io
import os
import re
import logging
import sys as _sys

# Silent fitz import (suppresses pymupdf_layout suggestion on fresh installs)
_n = open(os.devnull, "w")
_old_stderr = _sys.stderr
_sys.stderr = _n
import fitz
_sys.stderr = _old_stderr
_n.close()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class PDFProcessingError(Exception): pass
class EncryptedPDFError(PDFProcessingError): pass
class EmptyPDFError(PDFProcessingError): pass
class CorruptedPDFError(PDFProcessingError): pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_MB = 200
MIN_TEXT_FOR_TEXT_PDF = 50

# ---------------------------------------------------------------------------
# Core extraction — PyMuPDF
# ---------------------------------------------------------------------------
def extract_text_pymupdf(pdf_bytes: bytes) -> list[dict]:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except NameError:
        raise PDFProcessingError("PyMuPDF (fitz) not available.")
    except Exception as e:
        raise CorruptedPDFError(f"Cannot open PDF: {e}")

    if doc.is_encrypted:
        doc.close()
        raise EncryptedPDFError("This PDF is encrypted or password-protected.")

    if doc.page_count == 0:
        doc.close()
        raise EmptyPDFError("PDF contains zero pages.")

    pages = []
    for i in range(doc.page_count):
        page = doc[i]

        # Block-level text extraction with positions
        blocks = page.get_text("dict")["blocks"]
        all_text_blocks = []
        for b in blocks:
            if b["type"] == 0:  # text block
                for line in b["lines"]:
                    text = "".join([s["text"] for s in line["spans"]])
                    all_text_blocks.append({
                        "text": text,
                        "x": line["bbox"][0],
                        "y": line["bbox"][1],
                        "size": line["spans"][0]["size"] if line["spans"] else 11,
                        "font": line["spans"][0]["font"] if line["spans"] else "",
                    })

        # Plain text
        text = page.get_text("text")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        # Table extraction via PyMuPDF built-in
        tables_raw = []
        try:
            tables = page.find_tables()
            if tables:
                for t in tables:
                    table_data = []
                    for row in t.extract():
                        table_data.append([str(c or "").strip() for c in row])
                    if table_data:
                        tables_raw.append(table_data)
        except Exception:
            pass

        lines = text.split("\n") if text else []
        pages.append({
            "page_num": i + 1,
            "text": text,
            "raw_lines": lines,
            "blocks": all_text_blocks,
            "tables": tables_raw,
            "char_count": len(text),
            "line_count": len(lines),
        })

    doc.close()
    return pages


# ---------------------------------------------------------------------------
# Core extraction — pdfplumber (better tables)
# ---------------------------------------------------------------------------
def extract_tables_pdfplumber(pdf_bytes: bytes) -> dict[int, list]:
    try:
        import pdfplumber
    except ImportError:
        return {}

    result = {}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                if tables:
                    cleaned = []
                    for t in tables:
                        rows = []
                        for row in t:
                            rows.append([str(c or "").strip() for c in row])
                        if rows:
                            cleaned.append(rows)
                    if cleaned:
                        result[i + 1] = cleaned
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Merge tables
# ---------------------------------------------------------------------------
def merge_tables(pages: list[dict], plumber_tables: dict[int, list]) -> list[dict]:
    for p in pages:
        pn = p["page_num"]
        if pn in plumber_tables and plumber_tables[pn]:
            existing_ids = set()
            for t in p.get("tables", []):
                existing_ids.add(tuple(t[0]) if t else None)
            for t in plumber_tables[pn]:
                sig = tuple(t[0]) if t else None
                if sig not in existing_ids:
                    p["tables"].append(t)
                    existing_ids.add(sig)
    return pages


# ---------------------------------------------------------------------------
# Content type detection
# ---------------------------------------------------------------------------
def detect_content_type(pages: list[dict]) -> str:
    total_chars = sum(p["char_count"] for p in pages)
    if not pages or total_chars == 0:
        return "unknown"
    avg = total_chars / len(pages)
    if avg < 5:
        return "image"
    elif avg < MIN_TEXT_FOR_TEXT_PDF:
        return "mixed"
    return "text"


# ---------------------------------------------------------------------------
# Structure analysis
# ---------------------------------------------------------------------------
def detect_headers(lines: list[str]) -> list[int]:
    indices = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if s.isupper() and 3 < len(s) < 60:
            indices.append(i)
        elif s.endswith(":") and len(s) < 40:
            indices.append(i)
        elif s.istitle() and len(s) < 50 and i + 1 < len(lines) and not lines[i + 1].strip():
            indices.append(i)
    return indices


def build_sections(pages: list[dict]) -> list[dict]:
    sections = []
    for page in pages:
        lines = page["raw_lines"]
        headers = detect_headers(lines)
        hs = set(headers)
        cur_h = f"Page {page['page_num']}"
        cur_l = []

        for i, line in enumerate(lines):
            if i in hs:
                if cur_l:
                    sections.append({"page": page["page_num"], "header": cur_h, "content": "\n".join(cur_l).strip()})
                cur_h = line.strip()
                cur_l = []
            else:
                s = line.strip()
                if s:
                    cur_l.append(s)
        if cur_l:
            sections.append({"page": page["page_num"], "header": cur_h, "content": "\n".join(cur_l).strip()})

        for ti, table in enumerate(page.get("tables", [])):
            table_str = "\n".join([" | ".join(r) for r in table])
            sections.append({
                "page": page["page_num"], "header": f"Table {ti+1}",
                "content": table_str, "is_table": True, "table_data": table,
            })
    return sections


# ---------------------------------------------------------------------------
# Entity extraction helpers
# ---------------------------------------------------------------------------
def extract_prices(text: str) -> list[dict]:
    prices = []
    for m in re.finditer(r"\$[\d,]+(?:,\d{3})*(?:\.\d{2})?", text):
        prices.append({"value": m.group(), "position": m.start()})
    return prices


def extract_percentages(text: str) -> list[dict]:
    pcts = []
    for m in re.finditer(r"\d+\.?\d*%", text):
        pcts.append({"value": m.group(), "position": m.start()})
    return pcts


def extract_quotes(text: str) -> list[str]:
    quotes = re.findall(r'"([^"]{20,})"', text)
    return quotes


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def process_pdf(pdf_bytes: bytes, filename: str = "document.pdf") -> dict:
    warnings = []
    file_size_mb = len(pdf_bytes) / (1024 * 1024)

    if file_size_mb > MAX_FILE_SIZE_MB:
        raise PDFProcessingError(f"File too large ({file_size_mb:.1f} MB). Max: {MAX_FILE_SIZE_MB} MB.")

    pages = extract_text_pymupdf(pdf_bytes)
    total_chars = sum(p["char_count"] for p in pages)
    content_type = detect_content_type(pages)

    if content_type in ("image", "mixed"):
        warnings.append("This PDF appears scanned/image-based. Extractable text may be limited.")

    # Try pdfplumber for better table extraction
    plumber_tables = extract_tables_pdfplumber(pdf_bytes)
    pages = merge_tables(pages, plumber_tables)
    sections = build_sections(pages)

    all_text_parts = []
    for p in pages:
        if p["text"]:
            all_text_parts.append(f"--- Page {p['page_num']} ---\n{p['text']}")
    all_text = "\n\n".join(all_text_parts)

    has_tables = any(p.get("tables") for p in pages)
    total_tables = sum(len(p.get("tables", [])) for p in pages)

    # Entity extraction
    prices = extract_prices(all_text)
    percentages = extract_percentages(all_text)
    quotes = extract_quotes(all_text)

    metadata = {
        "filename": filename,
        "pages": len(pages),
        "file_size_mb": round(file_size_mb, 2),
        "total_chars": total_chars,
        "content_type": content_type,
        "has_tables": has_tables,
        "total_tables": total_tables,
        "sections_found": len(sections),
        "prices_found": len(prices),
        "quotes_found": len(quotes),
    }

    return {
        "metadata": metadata,
        "pages": pages,
        "sections": sections,
        "all_text": all_text,
        "warnings": warnings,
        "entities": {"prices": prices, "percentages": percentages, "quotes": quotes},
    }
