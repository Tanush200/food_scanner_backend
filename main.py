from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
# Imports FastAPI tools for creating APIs, handling files, forms, dependencies, and errors.

from fastapi.middleware.cors import CORSMiddleware
# Imports CORS middleware to allow frontend applications to communicate with the backend.

from sqlalchemy.orm import Session
# Imports SQLAlchemy's Session type for database operations.

from sqlalchemy import text
# Allows us to write and execute raw SQL queries.

from database import get_db
# Imports our function that creates and manages database sessions.

from ocr_service import extract_text_and_parse, match_with_database_ingredients
# Imports OCR and ingredient-matching functions from our OCR service.


app = FastAPI(title="Food Label Ingredient Scanner API")
# Creates the FastAPI application with the given API title.


app.add_middleware(
    CORSMiddleware,
    # Adds CORS middleware to the FastAPI application.

    allow_origins=["*"],
    # Allows requests from any frontend/domain.

    allow_credentials=True,
    # Allows credentials such as cookies or authentication information.

    allow_methods=["*"],
    # Allows all HTTP methods such as GET, POST, PUT, and DELETE.

    allow_headers=["*"],
    # Allows all HTTP request headers.
)


@app.get("/api/categories")
# Creates a GET endpoint at /api/categories.

def get_categories(db: Session = Depends(get_db)):
    # Gets a database session through FastAPI's dependency injection.

    query = text("SELECT id, name FROM categories")
    # Creates a SQL query to retrieve category IDs and names.

    result = db.execute(query).fetchall()
    # Executes the query and retrieves all matching rows.

    return [{"id": row[0], "name": row[1]} for row in result]
    # Converts database rows into a list of dictionaries and returns them as JSON.


@app.post("/api/analyze")
# Creates a POST endpoint at /api/analyze for analyzing a food-label image.

async def analyze_label(
    category_id: int = Form(...),
    # Receives the required category ID from form data.

    file: UploadFile = File(...),
    # Receives the required uploaded food-label image.

    db: Session = Depends(get_db)
    # Gets a database session using the get_db dependency.
):

    cat_query = text("SELECT name FROM categories WHERE id = :cat_id")
    # Creates a SQL query to find the category name using its ID.

    category = db.execute(cat_query, {"cat_id": category_id}).fetchone()
    # Executes the query with the category ID and gets the first matching row.

    if not category:
        # Checks whether the requested category exists.

        raise HTTPException(status_code=404, detail="Category not found")
        # Stops execution and returns a 404 error if the category doesn't exist.

    category_name = category[0]
    # Extracts the category name from the returned database row.

    image_bytes = await file.read()
    # Reads the uploaded image and stores it as binary data.

    extracted_items, raw_ocr_lines = extract_text_and_parse(image_bytes)
    # Sends the image to OCR and receives structured ingredients plus raw OCR text.

    limits_query = text("""
        SELECT i.canonical_name, l.max_limit_percent 
        FROM category_ingredient_limits l
        JOIN ingredients i ON l.ingredient_id = i.id
        WHERE l.category_id = :cat_id
    """)
    # Creates a SQL query to retrieve allowed ingredient limits for the selected category.

    db_rules = db.execute(limits_query, {"cat_id": category_id}).fetchall()
    # Executes the limits query and retrieves all matching ingredient rules.

    db_ingredients = [{"name": row[0], "max_limit": float(row[1])} for row in db_rules]
    # Converts database rules into Python dictionaries containing ingredient names and limits.

    analysis_results = []
    # Creates an empty list to store the final ingredient analysis results.

    for item in extracted_items:
        # Loops through every ingredient detected by OCR.

        matched_db_ing = match_with_database_ingredients(item["detected_name"], db_ingredients)
        # Finds the corresponding database ingredient for the OCR-detected ingredient.

        if matched_db_ing:
            # Continues only when a matching database ingredient is found.

            detected_val = item["detected_percentage"]
            # Gets the ingredient percentage detected from the food label.

            max_limit = matched_db_ing["max_limit"]
            # Gets the maximum allowed percentage from the database.

            is_excess = detected_val > max_limit
            # Checks whether the detected percentage is greater than the allowed limit.

            excess_amount = round(detected_val - max_limit, 2) if is_excess else 0.0
            # Calculates how much the ingredient exceeds the allowed limit.

            analysis_results.append({
                # Adds the ingredient's analysis information to the results list.

                "ingredient": matched_db_ing["name"].title(),
                # Stores the ingredient name with proper capitalization.

                "detected_percentage": detected_val,
                # Stores the percentage detected from the label.

                "max_allowed_percentage": max_limit,
                # Stores the maximum percentage allowed by the database.

                "is_excess": is_excess,
                # Stores True if the ingredient exceeds the limit, otherwise False.

                "excess_percentage": excess_amount,
                # Stores the amount by which the ingredient exceeds the limit.

                "status": f"Excess by {excess_amount}%" if is_excess else "Safe Level",
                # Creates a simple status message based on whether the limit was exceeded.

                "message": f"{matched_db_ing['name'].title()} is {excess_amount}% excess above maximum permitted limit ({max_limit}%)." if is_excess else f"{matched_db_ing['name'].title()} ({detected_val}%) is within safe limits (Max {max_limit}%)."
                # Creates a detailed human-readable explanation of the ingredient's status.
            })

    return {
        # Returns the final analysis response to the frontend.

        "category_id": category_id,
        # Returns the selected category ID.

        "category_name": category_name,
        # Returns the selected category name.

        "results": analysis_results,
        # Returns the ingredient safety analysis.

        "raw_ocr_lines": raw_ocr_lines
        # Returns the raw text detected by OCR.
    }