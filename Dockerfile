FROM python:3.11-slim

# System dependencies:
#   tesseract-ocr + tesseract-ocr-fas -> OCR for scanned Persian PDFs
#   poppler-utils                     -> pdf2image rasterisation
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-fas \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
