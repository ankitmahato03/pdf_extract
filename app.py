"""
FastAPI IPO PDF extractor
Requirements:
    pip install fastapi uvicorn pymupdf python-multipart
Run:
    uvicorn fastapi_ipo_extractor:app --reload --port 8000

This script extracts fields (with page numbers) from an IPO PDF and saves a JSON output.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
import fitz  # PyMuPDF
import re
import json
import tempfile
import os
import logging
from datetime import datetime
from typing import List, Tuple, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ipo_extractor")

app = FastAPI(title="IPO PDF Extractor API")


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_amount(text: str) -> str:
    """Try to normalize numeric amounts like "₹ 120.00", "1,200 crore", "₹1,200", "120-125".
    Returns the cleaned string (no extra spaces) or original text if it cannot be parsed further.
    """
    if not text:
        return "N/A"
    t = text.replace('\u200b', '').strip()  # remove zero-width spaces
    t = t.replace('₹', '').replace('Rs.', '').replace('INR', '')
    t = t.replace(',', '')
    t = t.lower()

    # handle ranges
    t = t.replace('–', '-').replace('—', '-')
    t = t.strip()

    # preserve crore/lakh if present
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)(\s*(crore|cr|lakh|lac|million|billion))?", t)
    if m:
        num = m.group(1)
        unit = m.group(3) or ""
        return (num + (" " + unit if unit else "")).strip()

    return t


def find_all(pattern: re.Pattern, pages: List[str]) -> List[Tuple[str, int]]:
    """Search `pattern` across page texts. Return list of (match, page_index).
       pattern should have a capturing group for the desired value.
    """
    results: List[Tuple[str, int]] = []
    for i, text in enumerate(pages):
        for m in pattern.finditer(text):
            val = m.group(1).strip()
            val = normalize_spaces(val)
            results.append((val, i + 1))
    return results


def first_or_na(matches: List[Tuple[str, int]]) -> Dict[str, Any]:
    if not matches:
        return {"value": "N/A", "pages": []}
    values = [m[0] for m in matches]
    pages = sorted({m[1] for m in matches})
    # prefer the longest / most descriptive value among duplicates
    best = max(values, key=lambda x: len(x))
    return {"value": best, "pages": pages}


def extract_ipo_data(pdf_path: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}

    # --- Step 1: Extract text per page ---
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.exception("Failed to open PDF")
        raise

    pages_text: List[str] = []
    for page in doc:
        txt = page.get_text("text")
        pages_text.append(txt)
    doc.close()

    full_text = "\n".join(pages_text)

    # unify spacing and remove odd Unicode spaces
    full_text = re.sub(r"\u200b|\u00A0", " ", full_text)

    # --- Step 2: Define robust patterns ---
    # each pattern captures the value in group 1
    patterns = {
        "Company Name": re.compile(r"(?:Name of the Company|Company Name|the company named)\s*[:\-\n]*\s*([A-Z][A-Za-z0-9\-&\.,()\s]{2,}?(?:Limited|Ltd|PLC|Pvt|Private|Incorporated|LLP|Co\.|Company)?)(?=\s|,|\.|\\n)", re.IGNORECASE),

        # Face value examples: "Face Value: ₹10 per equity share" or "Face Value per Equity Share: Rs. 10"
        "Face Value": re.compile(r"face value[\s:–-]*[\w\s]*(?:[:\-—]*)[\s\n]*₹?\s*(Rs\.?\s*)?([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),

        # Issue / Offer Price (single price or range)
        "Issue Price": re.compile(
    r"(?:offer price|issue price|price range|offer price range)?\s*(?:of)?\s*[:\-]*\s*₹?\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—]\s*[0-9]+(?:\.[0-9]+)?)?)",
    re.IGNORECASE
),

        # Total issue size / aggregating up to
        "Total Issue Size": re.compile(r"(?:total issue size|aggregating up to|aggregate issue size|size of the issue)[:\-\n]*\s*₹?\s*([0-9,\.\s]+(?:crore|lakh|lac|million|billion)?)", re.IGNORECASE),

        # Fresh issue and Offer for Sale (sometimes explicitly stated)
        "Fresh Issue": re.compile(r"fresh issue(?: of)?[:\-\s]*([0-9,\.\s]+(?:equity shares|shares|nos\.|nos)?)", re.IGNORECASE),

        "Offer For Sale": re.compile(r"offer for sale(?: of)?[:\-\s]*([0-9,\.\s]+(?:equity shares|shares|nos\.|nos)?)", re.IGNORECASE),

        # Listing at (NSE, BSE etc.)
        "Listing At": re.compile(r"(?:proposed to be listed on|listing at|the shares will be listed on|listing on)[:\-\s]*([A-Za-z,\s&]+)", re.IGNORECASE),

        # Registrars
        "Registrar": re.compile(r"(?:registrar to the issue|registrar to the offer|registrar)[:\-\s]*([A-Z][A-Za-z0-9\s&\.,\-()]{3,}?(?:Limited|Ltd\.?|Private|Pvt|Registrar)?)", re.IGNORECASE),
    }

    # --- Step 3: Search for each field across pages ---
    found: Dict[str, Any] = {}
    for key, pat in patterns.items():
        # special handling for face value because we used a second capture group
        if key == "Face Value":
            matches: List[Tuple[str, int]] = []
            for i, ptxt in enumerate(pages_text):
                for m in pat.finditer(ptxt):
                    # m.group(2) holds the numeric face value
                    val = m.group(2).strip() if m.group(2) else m.group(1).strip()
                    matches.append((val, i + 1))
            found[key] = first_or_na(matches)
        else:
            matches = find_all(pat, pages_text)
            found[key] = first_or_na(matches)

    # --- Step 4: Lead managers (may be multiple) ---
    brlm_pattern = re.compile(r"(?:book running lead manager|lead manager|brlm)[:\-\s]*([A-Z][A-Za-z\s&,\.\-]{3,}?(?:Limited|Ltd\.?|Pvt\.?|Private|Bank|Securities|Capital)?)", re.IGNORECASE)
    brlm_matches = find_all(brlm_pattern, pages_text)
    if brlm_matches:
        managers = sorted({m[0] for m in brlm_matches})
        pages = sorted({m[1] for m in brlm_matches})
        found["Lead Managers"] = {"value": ", ".join(managers), "pages": pages}
    else:
        # fallback: look for lines under a heading "Lead Managers" or a list nearby
        fallback = []
        for i, ptxt in enumerate(pages_text):
            if re.search(r"lead managers|lead manager|book running", ptxt, re.IGNORECASE):
                # grab the next 400 characters to try to find names separated by commas or newlines
                snippet = ptxt[:800]
                names = re.findall(r"([A-Z][A-Za-z\s&,\.\-]{3,}?(?:Limited|Ltd\.?|Pvt\.?|Securities|Capital|Bank))", snippet)
                for n in names:
                    fallback.append((normalize_spaces(n), i + 1))
        found["Lead Managers"] = first_or_na(fallback)

    # --- Step 5: Clean numeric-looking fields ---
    for k in ("Face Value", "Issue Price", "Total Issue Size", "Fresh Issue", "Offer For Sale"):
        entry = found.get(k, {"value": "N/A", "pages": []})
        if entry["value"] != "N/A":
            entry["value"] = parse_amount(entry["value"])
        found[k] = entry

    # --- Step 6: Company name cleanup (pick best candidate) ---
    company = found.get("Company Name", {"value": "N/A", "pages": []})
    if company["value"] != "N/A":
        # remove trailing punctuation and common words
        company_name = re.sub(r"\s+[,\.-]+$", "", company["value"])
        found["Company Name"] = {"value": company_name, "pages": company["pages"]}

    # --- Step 7: Final result structure ---
    result = {
        "extracted_at": datetime.now().isoformat(),
        "source_file": os.path.basename(pdf_path),
        "fields": found,
        "raw_text_sample": full_text[:1500]
    }

    return result


@app.post("/extract")
async def extract_from_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        ipo_data = extract_ipo_data(tmp_path)

        # Save JSON output with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"ipo_data_{timestamp}.json"
        output_path = os.path.join(os.getcwd(), output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(ipo_data, f, indent=2, ensure_ascii=False)

        return {
            "message": "Data extracted successfully",
            "output_file": output_filename,
            "data": ipo_data["fields"]
        }
    except Exception as e:
        logger.exception("Extraction failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
