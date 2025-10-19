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

    # Open PDF and extract all text
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    doc.close()

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)

    # Helper function to extract with regex
    def find(pattern, fallback="N/A"):
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else fallback

    # Extract IPO details
    data["Company Name"] = find(r'\b([A-Z][A-Z\s]+LIMITED)\b')
    data["Face Value"] = find(r'face value of ₹?([\d\.]+)')
    data["Issue Price"] = find(r'PRICE OF ₹\[?([^\s\]]+)')
    # data["Total Issue Size"] = find(r'aggregating up to ₹([\d,\.]+) million')
    data["THE OFFER"] = find(r'THE OFFER Offer for sale of up to\s*([\d,]+)\s+Equity Shares bearing face value of ₹')

    # data["Offer For Sale"] = find(r'Offer for Sale.*?₹([\d,\.]+) million')
    # data["Listing at"] = find(r'listed on the (.*?)\(')

    # Clean up text before searching
    clean_text = re.sub(r'\s+', ' ', text)  # remove extra newlines and spaces

    # Find all Lead Managers dynamically
    lead_managers = re.findall(
        r'(?:Book Running Lead Managers[:\s]*)?([A-Z][A-Za-z0-9&\s\.]*?(?:Limited|Ltd|LLP|Inc|Company|Corporation))(?![A-Za-z])',
        clean_text,
        flags=re.IGNORECASE
    )

    data["Lead Managers"] = ", ".join(sorted(set(lead_managers))) if lead_managers else "N/A"


  
    # lead_managers = re.findall(
    #     r'([A-Z][A-Za-z\s&]+ Advisors Limited|Motilal Oswal Investment Advisors Limited|Intensive Fiscal Services Private Limited)',
    #     text
    # )
    # data["Lead Manager"] = ", ".join(set(lead_managers)) if lead_managers else "N/A"
    # data["Registrar"] = find(r'Registrar to the Offer .*? ([A-Z][A-Za-z\s&]+ Limited)')

    # Financial metrics
    # data["EPS Pre IPO"] = find(r'EPS.*Pre[-\s]?IPO[:\-]?\s*([\d\.]+)')
    # data["EPS Post IPO"] = find(r'EPS.*Post[-\s]?IPO[:\-]?\s*([\d\.]+)')
    # data["P/E Pre IPO"] = find(r'P/?E.*Pre[-\s]?IPO[:\-]?\s*([\d\.]+)')
    # data["P/E Post IPO"] = find(r'P/?E.*Post[-\s]?IPO[:\-]?\s*([\d\.]+)')
    # data["ROE"] = find(r'Return on Equity.*?([\d\.]+)%')
    # data["ROCE"] = find(r'Return on Capital Employed.*?([\d\.]+)%')
    # data["Debt/Equity"] = find(r'Debt[ \-\/]?Equity.*?([\d\.]+)')
    # data["RoNW"] = find(r'Return on Net Worth.*?([\d\.]+)%')
    # data["PAT Margin"] = find(r'PAT Margin.*?([\d\.]+)%')
    # data["Price to Book Value"] = find(r'Price to Book Value.*?([\d\.]+)')
    # data["Market Cap."] = find(r'Market Capitalization.*?₹([\d,\.]+)')

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

    # Optionally, delete temp PDF
    os.remove(tmp_path)

    return {
        "message": "Data extracted successfully",
        "output_file": output_filename,
        "data": ipo_data
    }
