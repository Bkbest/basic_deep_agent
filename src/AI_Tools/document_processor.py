"""
Document to Image Converter

This module handles conversion of PDF and text-based documents (TXT, MD, DOC, DOCX, etc.)
into images for processing by the AI agent. Each page is rendered as a separate image with a page number overlay, mirroring the behavior of the original PDF converter.

Two strategies are supported:

1. **Native rendering (no extra deps)** — ``text_to_images`` wraps plain/markdown text onto a PIL canvas and splits it into pages. Works for ``.txt``, ``.md``, ``.log`` and any other plain-text format. Also handles ``.doc``/``.docx`` by extracting the text first (via ``python-docx`` for ``.docx``, simple heuristics for legacy ``.doc`` if ``antiword``/``textract`` is available; otherwise it falls back to the raw bytes decoded as text so it never fails hard).

2. **PDF rendering** — ``pdf_to_images`` uses PyMuPDF to rasterize PDF pages, unchanged from the original implementation.

``document_to_images`` is a small dispatcher that picks the right strategy based on MIME type or file extension so the caller (e.g. ``websocket_server.py``) can hand over any document without caring about format.
"""

import io
import base64
import os
import re
from typing import List, Dict, Any, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


def pdf_to_images(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert a PDF document to a list of page images.
    
    Args:
        document: Dict with filename, mime_type, and data (base64) keys
        
    Returns:
        List of dicts with 'page' (1-indexed) and 'image' (base64) keys
        
    Raises:
        ImportError: If PyMuPDF is not installed
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("PyMuPDF (fitz) is required for PDF processing. Install with: pip install PyMuPDF")
    
    filename = document.get('filename', 'document.pdf')
    data = document.get('data', '')
    
    # Decode base64 data
    try:
        pdf_bytes = base64.b64decode(data)
    except Exception as e:
        raise ValueError(f"Failed to decode PDF data: {e}")
    
    # Open PDF from bytes
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    pages = []
    for page_num, page in enumerate(pdf_doc, start=1):
        # Render page at higher resolution for quality
        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to PIL Image
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        # Add page number overlay
        draw = ImageDraw.Draw(img)
        page_text = f"Page {page_num} of {len(pdf_doc)}"
        
        # Get image dimensions
        img_width, img_height = img.size
        
        # Try to use a font, fallback if not available
        try:
            font_size = max(16, min(img_width, img_height) // 40)
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
        
        # Draw semi-transparent overlay at bottom
        overlay_height = 40
        overlay = Image.new('RGBA', (img_width, overlay_height), (255, 255, 255, 200))
        img.paste(overlay, (0, img_height - overlay_height))
        
        # Draw page number
        bbox = draw.textbbox((0, 0), page_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_x = (img_width - text_width) // 2
        draw.text((text_x, img_height - overlay_height + 10), page_text, font=font, fill='#666666')
        
        # Also add filename at top
        draw.text((10, 10), f"📄 {filename}", font=font, fill='#333333')
        
        # Convert to base64
        output_buffer = io.BytesIO()
        img.convert('RGB').save(output_buffer, format='PNG', quality=95)
        output_buffer.seek(0)
        
        pages.append({
            'page': page_num,
            'image': base64.b64encode(output_buffer.getvalue()).decode('utf-8')
        })
    
    pdf_doc.close()
    return pages


# ---------------------------------------------------------------------------
# Text -> Image rendering
# ---------------------------------------------------------------------------
#
# This block mirrors ``pdf_to_images`` for text-based documents. The goal is
# simple: turn a chunk of text into one or more PNG images that look like a
# rendered page, complete with a page-number footer and the filename header.
# No external binaries (LibreOffice, Pandoc, antiword, ...) are required.
#
# Supported inputs:
#   - ``.txt``, ``.md``, ``.markdown``, ``.rst``, ``.log`` and any other
#     plain-text format.
#   - ``.docx`` (requires the optional ``python-docx`` package; we attempt
#     to import it lazily so the module still loads without it).
#   - ``.doc`` (legacy Word format) — extracted as raw text by attempting
#     a UTF-8/Latin-1 decode, with control bytes filtered out. If users
#     want better fidelity they can pre-convert ``.doc`` -> ``.docx`` on
#     the client side. We deliberately don't shell out to ``antiword`` so
#     this stays a pure-Python solution on Windows.
#
# Anything else falls back to "best-effort text decode", which means the
# function always returns *something* rather than raising — the AI agent
# would rather receive a slightly ugly image than nothing.


def _decode_text_document(document: Dict[str, Any]) -> str:
    """Extract plain text from a text-based document.

    Args:
        document: Dict with ``filename``, ``mime_type`` and base64 ``data`` keys.

    Returns:
        Extracted text content as a single string.
    """
    filename: str = document.get("filename", "document.txt")
    data: str = document.get("data", "")

    # Lazy import so the module loads even when python-docx is missing.
    try:
        from docx import Document as DocxDocument  # type: ignore
        _HAS_DOCX = True
    except Exception:  # pragma: no cover - optional dependency
        DocxDocument = None  # type: ignore
        _HAS_DOCX = False

    ext = os.path.splitext(filename)[1].lower()

    # ---- .docx (modern Word) ----
    if ext == ".docx" and _HAS_DOCX:
        try:
            raw = base64.b64decode(data)
            docx_io = io.BytesIO(raw)
            doc = DocxDocument(docx_io)
            paragraphs = [p.text for p in doc.paragraphs]
            return "\n\n".join([p for p in paragraphs if p is not None])
        except Exception as e:
            # Fall through to raw-decode fallback.
            print(f"⚠️  python-docx failed ({e}); falling back to raw text decode.")

    # ---- everything else ----
    # Try a UTF-8 decode first (covers .txt, .md, .markdown, .rst, .log,
    # .json, .csv, .html, ...). If that fails, try latin-1 which can
    # decode any byte sequence without errors (good enough for .doc which
    # is mostly ASCII with stray control bytes).
    raw = base64.b64decode(data)
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            if encoding == "latin-1":
                # Strip non-printable control characters that .doc files
                # tend to sprinkle in. We keep \n, \r and \t.
                text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
            return text
        except UnicodeDecodeError:
            continue

    # Should be unreachable because latin-1 never raises, but keep a
    # defensive return so type-checkers are happy.
    return raw.decode("utf-8", errors="replace")


def _wrap_text_for_page(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    max_width: int,
) -> List[str]:
    """Wrap ``text`` into lines that fit within ``max_width`` pixels.

    Long lines are broken at whitespace when possible and at any character
    as a last resort. Blank input lines are preserved so paragraphs survive.
    """
    lines: List[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                # If a single word is wider than the page, hard-break it.
                while True:
                    bbox = draw.textbbox((0, 0), word, font=font)
                    if bbox[2] - bbox[0] <= max_width:
                        current = word
                        break
                    # binary-search a break point
                    lo, hi = 1, len(word)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        chunk = word[:mid]
                        bbox = draw.textbbox((0, 0), chunk, font=font)
                        if bbox[2] - bbox[0] <= max_width:
                            lo = mid
                        else:
                            hi = mid - 1
                    lines.append(word[:lo])
                    word = word[lo:]
                    current = ""
        if current:
            lines.append(current)
    return lines


def _paginate_lines(
    lines: List[str],
    lines_per_page: int,
) -> List[List[str]]:
    """Split ``lines`` into pages of at most ``lines_per_page`` each."""
    pages: List[List[str]] = []
    for i in range(0, len(lines), lines_per_page):
        pages.append(lines[i : i + lines_per_page])
    return pages or [[""]]


def _render_text_page(
    filename: str,
    page_num: int,
    total_pages: int,
    page_lines: List[str],
    page_size: Tuple[int, int],
    margin: int,
    line_spacing: int,
    font: ImageFont.ImageFont,
) -> Image.Image:
    """Render a single page of wrapped text onto a fresh PIL Image.

    Includes the same filename header (top-left) and page-number footer
    (bottom-center) that ``pdf_to_images`` adds, so the visual style is
    consistent between the two converters.
    """
    img_width, img_height = page_size
    img = Image.new("RGB", page_size, color="white")
    draw = ImageDraw.Draw(img)

    # Header: filename
    header_text = f"📄 {filename}"
    draw.text((margin, margin // 2), header_text, font=font, fill="#333333")

    # Body text
    y = margin
    for line in page_lines:
        draw.text((margin, y), line, font=font, fill="#000000")
        bbox = draw.textbbox((0, 0), line, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing
        if y > img_height - margin * 2:
            break  # safety net; pagination should have prevented this

    # Footer: page number on a soft overlay, matching the PDF converter.
    overlay_height = 40
    overlay = Image.new("RGBA", (img_width, overlay_height), (255, 255, 255, 200))
    img.paste(overlay, (0, img_height - overlay_height))
    page_text = f"Page {page_num} of {total_pages}"
    bbox = draw.textbbox((0, 0), page_text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text(
        ((img_width - text_width) // 2, img_height - overlay_height + 10),
        page_text,
        font=font,
        fill="#666666",
    )

    return img


def text_to_images(
    document: Dict[str, Any],
    page_size: Tuple[int, int] = (1240, 1754),  # ~A4 @ 150 DPI
    margin: int = 60,
    font_size: int = 18,
    line_spacing: int = 6,
) -> List[Dict[str, Any]]:
    """Convert a text-based document to a list of page images.

    Args:
        document: Dict with ``filename``, ``mime_type`` and base64 ``data`` keys.
        page_size: ``(width, height)`` in pixels for each rendered page.
        margin: Outer margin (px) applied to all four sides.
        font_size: Font size used for body text. The header/footer use
            the same font for visual consistency.
        line_spacing: Extra vertical pixels between text lines.

    Returns:
        List of dicts with ``'page'`` (1-indexed) and ``'image'`` (base64 PNG)
        keys — the same shape as :func:`pdf_to_images`.
    """
    filename = document.get("filename", "document.txt")
    text = _decode_text_document(document)

    # Resolve a usable font. ``arial.ttf`` is available on Windows; on
    # other platforms PIL's default bitmap font is a safe fallback.
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))  # cheap canvas for bbox math

    img_width, img_height = page_size
    usable_width = img_width - margin * 2
    line_height = font_size + line_spacing
    lines_per_page = max(1, (img_height - margin * 2) // line_height)

    wrapped = _wrap_text_for_page(text, draw, font, usable_width)
    pages_lines = _paginate_lines(wrapped, lines_per_page)
    total_pages = len(pages_lines)

    pages: List[Dict[str, Any]] = []
    for idx, page_lines in enumerate(pages_lines, start=1):
        img = _render_text_page(
            filename=filename,
            page_num=idx,
            total_pages=total_pages,
            page_lines=page_lines,
            page_size=page_size,
            margin=margin,
            line_spacing=line_spacing,
            font=font,
        )
        output_buffer = io.BytesIO()
        img.save(output_buffer, format="PNG", quality=95)
        output_buffer.seek(0)
        pages.append(
            {
                "page": idx,
                "image": base64.b64encode(output_buffer.getvalue()).decode("utf-8"),
            }
        )
    return pages


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".yml",
    ".yaml",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".go",
    ".rs",
    ".sh",
    ".bat",
    ".ps1",
    ".sql",
    ".doc",
    ".docx",
}


def _is_text_document(document: Dict[str, Any]) -> bool:
    """Return True when ``document`` should be handled by ``text_to_images``."""
    mime: Optional[str] = document.get("mime_type")
    filename: str = document.get("filename", "")
    ext = os.path.splitext(filename)[1].lower()

    if mime:
        if mime.startswith(_TEXT_MIME_PREFIXES):
            return True
        if mime in (
            "application/json",
            "application/xml",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ):
            return True
    return ext in _TEXT_EXTENSIONS


def document_to_images(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert any supported document to page images.

    Dispatches to :func:`pdf_to_images` for PDFs and to
    :func:`text_to_images` for everything else (TXT, MD, DOC, DOCX, code
    files, JSON, ...). The caller therefore doesn't need to know the file
    type — it just gets back a list of ``{'page', 'image'}`` dicts.
    """
    mime = (document.get("mime_type") or "").lower()
    filename = document.get("filename", "")
    ext = os.path.splitext(filename)[1].lower()

    if mime == "application/pdf" or ext == ".pdf":
        return pdf_to_images(document)
    return text_to_images(document)


if __name__ == "__main__":
    """
    Test document -> image conversion.

    Runs the ``document_to_images`` dispatcher on a small in-memory set of
    text documents plus, if ``drylab.pdf`` exists alongside the project, the
    PDF used by the original test harness. Output images are written to
    ``pdf_output/`` for visual inspection.
    """
    import os

    here = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(here, "..", ".."))
    output_dir = os.path.join(project_root, "pdf_output")
    os.makedirs(output_dir, exist_ok=True)

    # 1) Plain text + markdown + a code snippet — all routed through
    #    text_to_images by the dispatcher.
    text_samples = {
        "notes.txt": (
            "text/plain",
            "Hello from a plain text file!\n\n"
            "This renderer mirrors pdf_to_images: same header, same footer, "
            "same {page, image} return shape — but no extra dependencies."
        ),
        "README.md": (
            "text/markdown",
            "# Markdown sample\n\n"
            "- bullet one\n- bullet two with **bold** and *italic*\n\n"
            "## Section\n\n"
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."
        ),
        "snippet.py": (
            "text/x-python",
            "def greet(name: str) -> str:\n"
            "    \"\"\"Return a friendly greeting.\"\"\"\n"
            "    return f\"Hello, {name}!\"\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(greet(\"world\"))\n"
        ),
    }

    for filename, (mime, body) in text_samples.items():
        encoded = base64.b64encode(body.encode("utf-8")).decode("utf-8")
        doc = {"filename": filename, "mime_type": mime, "data": encoded}
        print(f"📝 Rendering {filename} ({mime})...")
        pages = document_to_images(doc)
        print(f"   ✅ {len(pages)} page(s)")
        for page_data in pages:
            out_path = os.path.join(
                output_dir, f"{os.path.splitext(filename)[0]}_p{page_data['page']}.png"
            )
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(page_data["image"]))
            print(f"   💾 {out_path}")

    # 1b) Real files dropped at the project root — exercise the dispatcher
    #     against the same shapes the WebSocket server receives.
    import mimetypes

    real_samples = ("industry.csv", "week2_full.md")
    for filename in real_samples:
        sample_path = os.path.join(project_root, filename)
        if not os.path.exists(sample_path):
            print(f"⚠️  Skipping {filename}: not found at {sample_path}")
            continue

        mime, _ = mimetypes.guess_type(sample_path)
        mime = mime or "application/octet-stream"
        with open(sample_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        doc = {"filename": filename, "mime_type": mime, "data": encoded}

        print(f"📂 Rendering {filename} ({mime}, {os.path.getsize(sample_path)} bytes)...")
        pages = document_to_images(doc)
        print(f"   ✅ {len(pages)} page(s)")
        for page_data in pages:
            out_path = os.path.join(
                output_dir, f"{os.path.splitext(filename)[0]}_p{page_data['page']}.png"
            )
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(page_data["image"]))
            print(f"   💾 {out_path}")

    # 2) PDF (if present) — keeps the original test path working.
    pdf_path = os.path.join(project_root, "drylab.pdf")
    if os.path.exists(pdf_path):
        print(f"\n📄 Rendering PDF: {pdf_path}")
        with open(pdf_path, "rb") as f:
            pdf_data = base64.b64encode(f.read()).decode("utf-8")
        doc = {
            "filename": os.path.basename(pdf_path),
            "mime_type": "application/pdf",
            "data": pdf_data,
        }
        pages = document_to_images(doc)
        print(f"   ✅ {len(pages)} page(s)")
        for page_data in pages:
            out_path = os.path.join(output_dir, f"page_{page_data['page']}.png")
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(page_data["image"]))
            print(f"   💾 {out_path}")
    else:
        print(f"\nℹ️  drylab.pdf not found at {pdf_path}; skipping PDF test.")

    print(f"\n✅ All images saved to: {output_dir}")
