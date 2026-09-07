from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from ocr_service import extract_text_and_parse, match_with_database_ingredients

app = FastAPI(title="Food Label Ingredient Scanner API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    query = text("SELECT id, name FROM categories")
    result = db.execute(query).fetchall()
    return [{"id": row[0], "name": row[1]} for row in result]


@app.post("/api/analyze")
async def analyze_label(
    category_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):

    cat_query = text("SELECT name FROM categories WHERE id = :cat_id")
    category = db.execute(cat_query, {"cat_id": category_id}).fetchone()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    category_name = category[0]

    image_bytes = await file.read()
    extracted_items, raw_ocr_lines = extract_text_and_parse(image_bytes)

    limits_query = text("""
        SELECT i.canonical_name, l.max_limit_percent 
        FROM category_ingredient_limits l
        JOIN ingredients i ON l.ingredient_id = i.id
        WHERE l.category_id = :cat_id
    """)
    db_rules = db.execute(limits_query, {"cat_id": category_id}).fetchall()
    db_ingredients = [{"name": row[0], "max_limit": float(row[1])} for row in db_rules]
    analysis_results = []
    for item in extracted_items:
        matched_db_ing = match_with_database_ingredients(item["detected_name"], db_ingredients)
        
        if matched_db_ing:
            detected_val = item["detected_percentage"]
            max_limit = matched_db_ing["max_limit"]
            is_excess = detected_val > max_limit
            excess_amount = round(detected_val - max_limit, 2) if is_excess else 0.0

            analysis_results.append({
                "ingredient": matched_db_ing["name"].title(),
                "detected_percentage": detected_val,
                "max_allowed_percentage": max_limit,
                "is_excess": is_excess,
                "excess_percentage": excess_amount,
                "status": f"Excess by {excess_amount}%" if is_excess else "Safe Level",
                "message": f"{matched_db_ing['name'].title()} is {excess_amount}% excess above maximum permitted limit ({max_limit}%)." if is_excess else f"{matched_db_ing['name'].title()} ({detected_val}%) is within safe limits (Max {max_limit}%)."
            })

    return {
        "category_id": category_id,
        "category_name": category_name,
        "results": analysis_results,
        "raw_ocr_lines": raw_ocr_lines
    }
