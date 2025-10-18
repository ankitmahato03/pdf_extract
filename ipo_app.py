from fastapi import FastAPI, UploadFile, File
import fitz  # PyMuPDF
import re
import tempfile
import os
import json
from datetime import datetime

app = FastAPI(title="IPO PDF Extractor API")


# Define the specific fields we want
IPO_FIELDS = {
    "Company Name": r'\b([A-Z][A-Z\s]+LIMITED)\b',
    "Face Value": r'face value of ₹?([\d\.]+)',
    "Issue Type": r'issue type[:\-]?\s*([A-Za-z\s]+)',
    "Lot Size": r'lot size of ([\d,]+) shares',
    "Offer Price": r'(?:PRICE OF|Offer Price) ₹?([\d\.]+)',
    "Total Issue Size": r'aggregating up to ₹([\d,\.]+) million',
    "Fresh Share": r'Fresh Issue.*?₹([\d,\.]+) million',
    "Offer For Sale": r'Offer for Sale.*?₹([\d,\.]+) million',
    "Listing at": r'listed on the (.*?)\('
}


def extract_ipo_fields(text: str) -> dict:
    """
    Extract predefined IPO fields from PDF text.
    """
    data = {}
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

    for field, pattern in IPO_FIELDS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        data[field] = match.group(1).strip() if match else "N/A"

    return data


def process_pdf(file_path: str) -> dict:
    """
    Extract all text from PDF and parse IPO fields.
    """
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    doc.close()

    return extract_ipo_fields(text)


@app.post("/extract")
async def extract_from_pdf(file: UploadFile = File(...)):
    """
    Upload a single PDF, extract predefined IPO fields, save JSON, and return data.
    """
    # Save uploaded PDF temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # Extract IPO fields
    extracted_data = process_pdf(tmp_path)

    # Delete temporary PDF
    os.remove(tmp_path)

    # Save JSON with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"ipo_data_{timestamp}.json"
    output_path = os.path.join(os.getcwd(), output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=4, ensure_ascii=False)

    return {
        "message": "PDF processed successfully",
        "file_name": file.filename,
        "json_file": output_filename,
        "data": extracted_data
    }
