"""
PDF to Image Converter

This module handles conversion of PDF documents into images for processing 
by the AI agent. Each page is rendered as a separate image with page number overlay.
"""

import io
import base64
from typing import List, Dict, Any

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


if __name__ == "__main__":
    """
    Test the PDF to image conversion by reading drylab.pdf and saving the output images.
    """
    import os
    
    # Path to the test PDF
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "..", "drylab.pdf")
    pdf_path = os.path.abspath(pdf_path)
    
    if not os.path.exists(pdf_path):
        print(f"❌ PDF file not found: {pdf_path}")
        exit(1)
    
    print(f"📄 Reading PDF: {pdf_path}")
    
    # Read and encode the PDF
    with open(pdf_path, "rb") as f:
        pdf_data = base64.b64encode(f.read()).decode("utf-8")
    
    # Create document dict
    document = {
        "filename": os.path.basename(pdf_path),
        "mime_type": "application/pdf",
        "data": pdf_data
    }
    
    # Convert to images
    print("🔄 Converting PDF to images...")
    pages = pdf_to_images(document)
    print(f"✅ Converted {len(pages)} page(s)")
    
    # Save each page as an image
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "pdf_output")
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    for page_data in pages:
        page_num = page_data["page"]
        image_data = page_data["image"]
        
        # Decode base64 and save as PNG
        img_bytes = base64.b64decode(image_data)
        output_path = os.path.join(output_dir, f"page_{page_num}.png")
        
        with open(output_path, "wb") as f:
            f.write(img_bytes)
        
        print(f"💾 Saved: {output_path}")
    
    print(f"\n✅ All images saved to: {output_dir}")
