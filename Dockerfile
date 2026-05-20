FROM python:3.11-slim

# Install system dependencies: tesseract OCR + poppler (for pdf2image)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-ell \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 10000

# Start gunicorn
CMD ["gunicorn", "--timeout", "300", "--workers", "2", "--bind", "0.0.0.0:10000", "app:app"]
