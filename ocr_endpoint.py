"""
Autoanosis OCR Endpoint - Professional PDF & Image Processing
Handles both text PDFs, scanned PDFs, and images with OCR
"""

from flask import Blueprint, request, jsonify
import os
import io
import base64
from openai import OpenAI

ocr_bp = Blueprint('ocr', __name__)

# Initialize OpenAI client (key from environment)
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

@ocr_bp.route('/ocr', methods=['POST'])
def process_ocr():
    """
    OCR endpoint that handles:
    1. Text PDFs (extract text directly)
    2. Scanned PDFs (OCR via OpenAI Vision)
    3. Images (OCR via OpenAI Vision)
    
    Returns: {"success": True, "extracted_text": "...", "type": "pdf|image"}
    """
    
    # Validate file upload
    if 'file' not in request.files:
        return jsonify({
            "success": False,
            "error": "NO_FILE",
            "message": "No file provided in request"
        }), 400
    
    file = request.files['file']
    
    if not file or file.filename == '':
        return jsonify({
            "success": False,
            "error": "EMPTY_FILE",
            "message": "Empty file provided"
        }), 400
    
    # Read file data
    file_data = file.read()
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    
    # Route to appropriate handler
    try:
        if content_type == "application/pdf" or filename.endswith(".pdf"):
            return handle_pdf(file_data, filename)
        elif content_type.startswith("image/"):
            return handle_image(file_data, content_type)
        else:
            return jsonify({
                "success": False,
                "error": "UNSUPPORTED_TYPE",
                "message": f"Unsupported file type: {content_type}"
            }), 400
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "PROCESSING_ERROR",
            "message": str(e)
        }), 500


def handle_pdf(file_data, filename):
    """
    Handle PDF files:
    1. Try text extraction first (for text-based PDFs)
    2. If no text found, use OCR (for scanned PDFs)
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return jsonify({
            "success": False,
            "error": "DEPENDENCY_MISSING",
            "message": "PyMuPDF not installed. Run: pip install pymupdf"
        }), 500
    
    try:
        # Open PDF from bytes
        doc = fitz.open(stream=file_data, filetype="pdf")
        
        # Extract text from all pages
        text_pages = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text").strip()
            if text:
                text_pages.append(text)
        
        # If we got text, return it
        if text_pages:
            extracted_text = "\n\n".join(text_pages)
            return jsonify({
                "success": True,
                "extracted_text": extracted_text,
                "type": "pdf_text",
                "pages": len(text_pages)
            })
        
        # No text found - it's a scanned PDF
        # Convert first 3 pages to images and OCR them
        extracted_text_parts = []
        max_pages = min(3, len(doc))
        
        for page_num in range(max_pages):
            page = doc[page_num]
            
            # Render page to image (PNG)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x scale for better OCR
            img_bytes = pix.tobytes("png")
            
            # OCR the image
            ocr_result = ocr_image_with_openai(img_bytes, "image/png")
            if ocr_result:
                extracted_text_parts.append(f"--- Σελίδα {page_num + 1} ---\n{ocr_result}")
        
        if extracted_text_parts:
            return jsonify({
                "success": True,
                "extracted_text": "\n\n".join(extracted_text_parts),
                "type": "pdf_scanned",
                "pages": len(extracted_text_parts)
            })
        else:
            return jsonify({
                "success": True,
                "extracted_text": "",
                "type": "pdf_empty",
                "message": "PDF contains no extractable text or images"
            })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "PDF_PROCESSING_ERROR",
            "message": str(e)
        }), 500


def handle_image(file_data, content_type):
    """
    Handle image files using OpenAI Vision OCR
    """
    try:
        extracted_text = ocr_image_with_openai(file_data, content_type)
        
        return jsonify({
            "success": True,
            "extracted_text": extracted_text or "",
            "type": "image"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "IMAGE_OCR_ERROR",
            "message": str(e)
        }), 500


def ocr_image_with_openai(image_bytes, content_type):
    """
    Perform OCR on image using OpenAI Vision API
    
    Args:
        image_bytes: Raw image bytes
        content_type: MIME type (e.g., "image/png")
    
    Returns:
        Extracted text string
    """
    try:
        # Encode image to base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # Call OpenAI Vision API
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """Εξάγε όλο το κείμενο από αυτή την εικόνα ιατρικής εξέτασης.
Περίλαβε:
- Όνομα εξέτασης
- Ημερομηνία
- Όλες τις τιμές και μετρήσεις
- Τυχόν σχόλια ή παρατηρήσεις

Επέστρεψε μόνο το εξαγμένο κείμενο, χωρίς επεξηγήσεις."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        print(f"OpenAI Vision OCR error: {e}")
        return ""
