from fastapi import FastAPI, File, UploadFile, Query
import fitz  # PyMuPDF
import json
import re
import os

app = FastAPI()

@app.post("/extract-page/")
async def extract_page_text(
    file: UploadFile = File(...),
    page_number: int = Query(..., description="Page number to extract (1-based index)")
):
    # Save uploaded file temporarily
    temp_file_path = file.filename
    with open(temp_file_path, "wb") as f:
        f.write(await file.read())

    # Open PDF
    doc = fitz.open(temp_file_path)
    page_index = page_number - 1

    # Validate page number
    if page_index < 0 or page_index >= len(doc):
        os.remove(temp_file_path)
        return {"error": f"Invalid page number. PDF has {len(doc)} pages."}

    # Extract text
    page = doc.load_page(page_index)
    text = page.get_text("text")
    ftext = re.sub(r'\s+', ' ', text)

    # Prepare JSON data
    data = {
        "page_number": page_number,
        "extracted_text": ftext
    }

    # Save JSON file
    json_file_name = f"page_{page_number}_text.json"
    with open(json_file_name, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    # Clean up temporary PDF
    os.remove(temp_file_path)

    return {
        "message": f"Extracted text from page {page_number}",
        "json_file": json_file_name,
        "data": data
    }
