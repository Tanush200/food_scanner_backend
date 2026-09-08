# Import EasyOCR library to extract/read text from images
import easyocr

# Import Python's regular expression module for finding and cleaning text patterns
import re

# Import RapidFuzz tools for fuzzy/similarity string matching
from rapidfuzz import process, fuzz


# Create an EasyOCR reader for English language
# gpu=False means OCR will run using the CPU instead of GPU
reader = easyocr.Reader(['en'], gpu=False)


# Function that takes image bytes and extracts ingredient names and percentages
def extract_text_and_parse(image_bytes):

    # Run OCR on the image
    # detail=1 tells EasyOCR to return:
    # 1. Bounding box → where the text is located
    # 2. Text → what was detected
    # 3. Probability → OCR confidence score
    ocr_result_raw = reader.readtext(image_bytes, detail=1)


    # Create an empty list to store the OCR results
    # We will store x position, y position, and detected text
    items = []


    # Loop through every piece of text detected by EasyOCR
    for r in ocr_result_raw:

        # Each OCR result contains:
        # bbox  → bounding box coordinates
        # text  → detected text
        # prob  → OCR confidence/probability
        bbox, text, prob = r


        # Find the smallest X coordinate from the bounding box
        # X represents the horizontal position (left/right)
        min_x = min(pt[0] for pt in bbox)


        # Find the smallest Y coordinate from the bounding box
        # Y represents the vertical position (top/bottom)
        min_y = min(pt[1] for pt in bbox)


        # Store the important information in our own dictionary
        # We don't need the probability for the remaining processing
        items.append({
            'x': min_x,       # Horizontal position
            'y': min_y,       # Vertical position
            'text': text      # OCR detected text
        })


    # Sort all detected text from top to bottom using the Y coordinate
    # Smaller Y value = text is higher on the image
    items.sort(key=lambda i: i['y'])


    # Create an empty list to store groups of text that belong
    # to the same visual line
    lines = []


    # Loop through every OCR text item
    for it in items:

        # Initially assume this item has not been assigned to a line
        placed = False


        # Check the current item against every existing line
        for l in lines:

            # Check whether the item's Y position is within 50 pixels
            # of the average Y position of an existing line
            #
            # If yes, we assume both pieces of text belong to the same line
            if abs(l['y_mean'] - it['y']) <= 50:

                # Add this OCR item to the existing line
                l['items'].append(it)


                # Recalculate the average Y coordinate of the line
                # This helps keep track of where the line is located
                l['y_mean'] = sum(
                    i['y'] for i in l['items']
                ) / len(l['items'])


                # Mark this item as successfully placed in a line
                placed = True


                # Stop checking other lines because we already found
                # the correct line for this item
                break


        # If the item did not belong to any existing line
        if not placed:

            # Create a new line containing this item
            #
            # y_mean = Y position of the item
            # items = list containing the current OCR item
            lines.append({
                'y_mean': it['y'],
                'items': [it]
            })


    # Sort the reconstructed lines from top to bottom
    # using their average Y coordinate
    lines.sort(key=lambda l: l['y_mean'])


    # Create a list that will contain the final reconstructed OCR lines
    raw_ocr_lines = []


    # Process each reconstructed line
    for l in lines:

        # Sort the text inside each line from left to right
        # using the X coordinate
        l['items'].sort(key=lambda i: i['x'])


        # Extract the text from every item in the line
        # and join them together using spaces
        #
        # Example:
        # ["Wheat Flour", "50%"]
        # becomes:
        # "Wheat Flour 50%"
        raw_ocr_lines.append(
            ' '.join([i['text'] for i in l['items']])
        )


    # Join all reconstructed OCR lines together using newline characters
    #
    # Example:
    # [
    #   "Ingredients",
    #   "Wheat Flour 50%",
    #   "Palm Oil 20%"
    # ]
    #
    # becomes:
    #
    # Ingredients
    # Wheat Flour 50%
    # Palm Oil 20%
    full_text = "\n".join(raw_ocr_lines)


    # Fix OCR mistakes in percentages
    #
    # Example:
    # "4:8%" → "4.8%"
    # "4;8%" → "4.8%"
    # "4,8%" → "4.8%"
    #
    # (\d+) = one or more digits
    # [:;,] = colon, semicolon, or comma
    # (\d+) = another group of digits
    cleaned_text = re.sub(
        r"(\d+)[:;,](\d+)\s*%",
        r"\1.\2%",
        full_text
    )


    # Remove unwanted apostrophes that OCR may insert between characters
    #
    # Example:
    # "O'il" → "Oil"
    # "pa'lm" → "palm"
    cleaned_text = re.sub(
        r"([a-zA-Z0-9])['`’]([a-zA-Z0-9])",
        r"\1\2",
        cleaned_text
    )


    # Split the cleaned text whenever we find:
    # comma (,)
    # semicolon (;)
    # newline (\n)
    #
    # Example:
    # "Wheat Flour 50%, Palm Oil 20%"
    #
    # becomes:
    # ["Wheat Flour 50%", "Palm Oil 20%"]
    segments = re.split(
        r"[,;\n]",
        cleaned_text
    )


    # Create an empty list to store the final extracted ingredients
    extracted_items = []


    # Temporary variable used when an ingredient name is detected
    # before its percentage
    #
    # Example:
    # "Wheat Flour"
    # "50%"
    #
    # We temporarily remember "Wheat Flour"
    prev_unmatched_name = ""


    # Process every text segment one by one
    for seg in segments:

        # Remove spaces from the beginning and end of the segment
        seg = seg.strip()


        # If the segment is empty, skip it
        if not seg:
            continue


        # Search for a pattern containing:
        # ingredient name + optional ":" or "-" + percentage
        #
        # Examples it can detect:
        #
        # "Wheat Flour 50%"
        # "Wheat Flour: 50%"
        # "Wheat Flour - 50%"
        #
        # (.+?) → ingredient name
        # [: -]? → optional colon or hyphen
        # (\d+(?:\.\d+)?) → integer or decimal number
        # % → percentage symbol
        m = re.search(
            r"(.+?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%",
            seg
        )


        # If a name + percentage was successfully found
        if m:

            # Extract the ingredient name from the first regex group
            name_part = m.group(1).strip()


            # Extract the percentage from the second regex group
            # and convert it from text into a floating-point number
            #
            # Example:
            # "50" → 50.0
            # "4.8" → 4.8
            val = float(m.group(2))


            # Clean the ingredient name:
            #
            # 1. Remove special characters
            # 2. Convert to lowercase
            # 3. Remove spaces from beginning/end
            #
            # Example:
            # "Palm-Oil!" → "palm oil"
            clean_name = re.sub(
                r'[^a-zA-Z0-9\s]',
                '',
                name_part
            ).lower().strip()


            # Remove a single unwanted letter at the beginning
            # if OCR accidentally detected something like:
            # "a wheat flour" → "wheat flour"
            clean_name = re.sub(
                r'^[a-z]\s+',
                '',
                clean_name
            )


            # Remove common words that aren't actual ingredient names
            #
            # Example:
            # "ingredients wheat flour" → "wheat flour"
            # "contains palm oil" → "palm oil"
            clean_name = re.sub(
                r'^(ingredients|contains|added|and)\s+',
                '',
                clean_name
            )


            # If there is no ingredient name in the current segment
            # but we previously detected an unmatched ingredient name,
            # use that previous name
            #
            # Example:
            # "Wheat Flour"
            # "50%"
            #
            # When processing "50%", use the previously stored
            # "wheat flour" as the ingredient name
            if not clean_name and prev_unmatched_name:
                clean_name = prev_unmatched_name


            # Clear the previous unmatched name because
            # we have now used it
            prev_unmatched_name = ""


            # Validate the ingredient name before storing it
            #
            # clean_name → must not be empty
            # not clean_name.isdigit() → cannot be only numbers
            # len(clean_name) >= 2 → must have at least 2 characters
            if (
                clean_name
                and not clean_name.isdigit()
                and len(clean_name) >= 2
            ):

                # Add the cleaned ingredient and percentage
                # to our final extracted items list
                extracted_items.append({
                    "detected_name": clean_name,
                    "detected_percentage": val
                })


        # If the current segment does NOT contain a percentage
        else:

            # Clean the segment:
            # 1. Remove special characters
            # 2. Convert to lowercase
            # 3. Remove extra spaces
            clean_seg = re.sub(
                r'[^a-zA-Z0-9\s]',
                '',
                seg
            ).lower().strip()


            # Remove common unnecessary prefixes
            #
            # Example:
            # "Ingredients Wheat Flour"
            # → "wheat flour"
            clean_seg = re.sub(
                r'^(ingredients|contains|added|and)\s+',
                '',
                clean_seg
            )


            # Make sure the segment isn't empty
            # and isn't just a number
            if clean_seg and not clean_seg.isdigit():

                # Remember this ingredient name temporarily
                #
                # This is useful when the percentage appears
                # in the next segment
                prev_unmatched_name = clean_seg


    # Return two things:
    #
    # extracted_items:
    # Structured ingredient + percentage data
    #
    # raw_ocr_lines:
    # The reconstructed OCR text lines
    return extracted_items, raw_ocr_lines


# Function used to match an OCR-detected ingredient
# with an ingredient stored in our database
def match_with_database_ingredients(
    detected_name,       # Ingredient detected by OCR
    db_ingredients,      # List of ingredients from database
    threshold=60         # Minimum fuzzy-match score
):

    # Documentation explaining what this function does
    """
    Fuzzy matching: Matches OCR output like 'paim oil' or 'sa1t'
    to DB ingredient 'palm oil' or 'salt'
    """


    # Extract only the ingredient names from the database objects
    #
    # Example:
    #
    # db_ingredients = [
    #     {"id": 1, "name": "palm oil"},
    #     {"id": 2, "name": "salt"}
    # ]
    #
    # choices becomes:
    #
    # ["palm oil", "salt"]
    choices = [
        ing['name']
        for ing in db_ingredients
    ]


    # If the database contains no ingredients,
    # there is nothing to match against
    if not choices:
        return None


    # First try an exact match
    #
    # Example:
    # OCR = "salt"
    # DB  = "salt"
    #
    # This is faster and more reliable than fuzzy matching
    for ing in db_ingredients:

        # Compare the OCR name with the database name
        if ing['name'] == detected_name:

            # Return the complete database ingredient object
            return ing


    # Try fuzzy matching using RapidFuzz
    #
    # extractOne() finds the single most similar string
    #
    # token_sort_ratio compares the words/tokens while
    # being less sensitive to their order
    result = process.extractOne(
        detected_name,
        choices,
        scorer=fuzz.token_sort_ratio
    )


    # Check whether:
    # 1. RapidFuzz found a result
    # 2. Its similarity score is greater than or equal to
    #    our threshold
    if result and result[1] >= threshold:

        # result[0] contains the matched database ingredient name
        matched_name = result[0]


        # Find the complete database object using the matched name
        for ing in db_ingredients:

            # If the database ingredient name matches
            # the fuzzy-matched name
            if ing['name'] == matched_name:

                # Return the complete ingredient object
                return ing


    # If token_sort_ratio wasn't good enough,
    # try another fuzzy matching algorithm
    #
    # partial_ratio is useful when one string is a strong
    # partial match of another string
    result_partial = process.extractOne(
        detected_name,
        choices,
        scorer=fuzz.partial_ratio
    )


    # Require a higher score of 80 for partial matching
    # because partial matching can potentially create
    # more false positives
    if result_partial and result_partial[1] >= 80:

        # Get the name of the matched database ingredient
        matched_name = result_partial[0]


        # Find and return the complete database ingredient object
        for ing in db_ingredients:

            # Check whether this is the ingredient RapidFuzz selected
            if ing['name'] == matched_name:

                # Return the complete database object
                return ing


    # If no exact or fuzzy match was found,
    # return None
    return None


