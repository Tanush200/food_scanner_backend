import easyocr
import re
from rapidfuzz import process, fuzz

reader = easyocr.Reader(['en'], gpu=False)

def extract_text_and_parse(image_bytes):
    ocr_result_raw = reader.readtext(image_bytes, detail=1)
    
    # Extract bounding box items and sort top-to-bottom by Y coordinate
    items = []
    for r in ocr_result_raw:
        bbox, text, prob = r
        min_x = min(pt[0] for pt in bbox)
        min_y = min(pt[1] for pt in bbox)
        items.append({'x': min_x, 'y': min_y, 'text': text})
        
    items.sort(key=lambda i: i['y'])

    # Group bounding boxes into lines using 50px running mean threshold
    lines = []
    for it in items:
        placed = False
        for l in lines:
            if abs(l['y_mean'] - it['y']) <= 50:
                l['items'].append(it)
                l['y_mean'] = sum(i['y'] for i in l['items']) / len(l['items'])
                placed = True
                break
        if not placed:
            lines.append({'y_mean': it['y'], 'items': [it]})

    lines.sort(key=lambda l: l['y_mean'])
    
    raw_ocr_lines = []
    for l in lines:
        l['items'].sort(key=lambda i: i['x'])
        raw_ocr_lines.append(' '.join([i['text'] for i in l['items']]))

    # Join lines with newline and pre-clean typos like "4:8%" -> "4.8%" and apostrophes in "O'il"
    full_text = "\n".join(raw_ocr_lines)
    cleaned_text = re.sub(r"(\d+)[:;,](\d+)\s*%", r"\1.\2%", full_text)
    cleaned_text = re.sub(r"([a-zA-Z0-9])['`’]([a-zA-Z0-9])", r"\1\2", cleaned_text)

    # Split into comma/semicolon/newline delimited segments
    segments = re.split(r"[,;\n]", cleaned_text)

    extracted_items = []
    prev_unmatched_name = ""

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
            
        m = re.search(r"(.+?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%", seg)
        if m:
            name_part = m.group(1).strip()
            val = float(m.group(2))
            
            clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', name_part).lower().strip()
            clean_name = re.sub(r'^[a-z]\s+', '', clean_name)
            clean_name = re.sub(r'^(ingredients|contains|added|and)\s+', '', clean_name)
            
            # If segment had no name before % (e.g. "50%"), fallback to previous unmatched name
            if not clean_name and prev_unmatched_name:
                clean_name = prev_unmatched_name

            prev_unmatched_name = ""

            if clean_name and not clean_name.isdigit() and len(clean_name) >= 2:
                extracted_items.append({
                    "detected_name": clean_name,
                    "detected_percentage": val
                })
        else:
            # Segment has no percentage yet (e.g. "Wheat Flour" on line above "50%")
            clean_seg = re.sub(r'[^a-zA-Z0-9\s]', '', seg).lower().strip()
            clean_seg = re.sub(r'^(ingredients|contains|added|and)\s+', '', clean_seg)
            if clean_seg and not clean_seg.isdigit():
                prev_unmatched_name = clean_seg

    return extracted_items, raw_ocr_lines


def match_with_database_ingredients(detected_name, db_ingredients, threshold=60):
    """
    Fuzzy matching: Matches OCR output like 'paim oil' or 'sa1t' to DB ingredient 'palm oil' or 'salt'
    """
    choices = [ing['name'] for ing in db_ingredients]
    if not choices:
        return None

    for ing in db_ingredients:
        if ing['name'] == detected_name:
            return ing

    result = process.extractOne(detected_name, choices, scorer=fuzz.token_sort_ratio)
    if result and result[1] >= threshold:
        matched_name = result[0]
        for ing in db_ingredients:
            if ing['name'] == matched_name:
                return ing

    result_partial = process.extractOne(detected_name, choices, scorer=fuzz.partial_ratio)
    if result_partial and result_partial[1] >= 80:
        matched_name = result_partial[0]
        for ing in db_ingredients:
            if ing['name'] == matched_name:
                return ing

    return None


