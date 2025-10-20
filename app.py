from fastapi import FastAPI, UploadFile, File
import fitz  # PyMuPDF
import re
import json
import tempfile
import os
from datetime import datetime

app = FastAPI(title="IPO PDF Extractor API")


def extract_ipo_data(pdf_path):
    """
    Extract IPO-related data from a PDF using PyMuPDF.
    """
    data = {}

    # --- Step 1: Extract text from PDF ---
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += f"\n\n--- Page {page.number + 1} ---\n\n"
        text += page.get_text("text")
    doc.close()

    # --- Step 2: Normalize text ---
    text = re.sub(r'\s+', ' ', text)
    text = text.replace("₹ ", "₹")  # unify currency format

    # --- Step 3: Helper function ---
    def find(pattern, fallback="N/A", flags=re.IGNORECASE):
        match = re.search(pattern, text, flags)
        return match.group(1).strip() if match else fallback

    # --- Step 4: Extract IPO details ---
    data["Company Name"] = find(
        r'(?:Company Name|Name of the Company)\s*[:\-]?\s*([A-Z][A-Za-z0-9\s&]+(?:Limited|Ltd\.))'
    )

    data["Face Value"] = find(
        r'face value\s*(?:of)?\s*₹?\s*([\d\.]+)', flags=re.IGNORECASE
    )

    data["Issue Price"] = find(
        r'(?:offer price|issue price|price range)\s*(?:of)?\s*₹?\s*([\d\.]+(?:\s*-\s*₹?\d+)?)(?=\s*per share)',
        flags=re.IGNORECASE
    )

    data["Total Issue Size"] = find(
        r'(?:total issue size|aggregating up to)\s*₹?\s*([\d,\.]+ ?(?:crore|million|lakh)?)',
        flags=re.IGNORECASE
    )

    data["Fresh Issue"] = find(
        r'fresh issue of up to\s*([\d,\.]+)\s*(?:equity shares|shares)',
        flags=re.IGNORECASE
    )

    data["Offer For Sale"] = find(
        r'offer for sale of up to\s*([\d,\.]+)\s*(?:equity shares|shares)',
        flags=re.IGNORECASE
    )

    data["Listing At"] = find(
        r'(?:proposed to be listed on|listing at)\s*[:\-]?\s*([A-Z\s&]+)',
        flags=re.IGNORECASE
    )

    # --- Step 5: Lead Managers & Registrar ---
    lead_managers = re.findall(
        r'(?:book running lead manager|brlm|lead manager)[\s:–-]*([A-Z][A-Za-z\s&]+(?:Limited|Ltd\.))',
        text, re.IGNORECASE
    )
    data["Lead Manager"] = ", ".join(sorted(set(lead_managers))) if lead_managers else "N/A"

    data["Registrar"] = find(
        r'(?:registrar to the offer|registrar)\s*[:\-]?\s*([A-Z][A-Za-z\s&]+(?:Limited|Ltd\.))',
        flags=re.IGNORECASE
    )

    return data


@app.post("/extract")
async def extract_from_pdf(file: UploadFile = File(...)):
    """
    Upload a PDF and extract IPO data as JSON.
    """
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # Extract IPO data
    ipo_data = extract_ipo_data(tmp_path)

    # Save JSON output with timestamp
    timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
    output_filename = f"ipo_data_{timestamp}.json"
    output_path = os.path.join(os.getcwd(), output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ipo_data, f, indent=4, ensure_ascii=False)

    # Delete temporary PDF
    os.remove(tmp_path)

    return {
        "message": "Data extracted successfully",
        "output_file": output_filename,
        "data": ipo_data
    }
