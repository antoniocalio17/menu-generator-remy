"""
FastAPI app — exposes the menu generation pipeline and serves the chef UI.
Run with: uvicorn api.main:app --reload  (from the menu-generator/ directory)
"""

import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.catalogue import Catalogue
from engine.exporter import build_summary, summary_to_dict
from engine.output_format import WeeklyPlan
from engine.groq_llama import PlannerError, generate
from engine.validator import PlanValidationError, fix_budget, validate

MENUS_DIR = Path(__file__).parent.parent / "data" / "menus"
STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Heyra Menu Generator")
catalogue = Catalogue()


def _week_start(week: int) -> date:
    try:
        return date.fromisocalendar(date.today().year, week, 1)
    except ValueError:
        raise HTTPException(400, f"Invalid week number: {week}")


def _menu_path(week: int) -> Path:
    return MENUS_DIR / f"{date.today().year}_w{week:02d}.json"


# ---------------------------------------------------------------------------
# Generation & retrieval
# ---------------------------------------------------------------------------


@app.post("/api/generate/{week}")
def generate_week(week: int) -> dict:
    """Run the full pipeline for the given ISO week number and store the result."""
    MENUS_DIR.mkdir(parents=True, exist_ok=True)
    week_start = _week_start(week)

    try:
        plan = generate(week_start.isoformat(), catalogue=catalogue)
    except PlannerError as e:
        raise HTTPException(500, str(e))

    plan = fix_budget(plan, catalogue)

    try:
        validate(plan, catalogue)
    except PlanValidationError as e:
        raise HTTPException(422, {"errors": e.errors})

    _menu_path(week).write_text(plan.model_dump_json())
    return summary_to_dict(build_summary(plan, catalogue), week)


@app.get("/api/menu/{week}")
def get_week(week: int) -> dict:
    """Return the stored menu for a week (404 if not yet generated)."""
    path = _menu_path(week)
    if not path.exists():
        raise HTTPException(404, "Menu not generated yet for this week")
    plan = WeeklyPlan.model_validate_json(path.read_text())
    return summary_to_dict(build_summary(plan, catalogue), week)


# ---------------------------------------------------------------------------
# Chef customization
# ---------------------------------------------------------------------------


class IngredientPayload(BaseModel):
    product_id: int
    quantity_g: float


class DishUpdate(BaseModel):
    dish_name: str
    ingredients: list[IngredientPayload]


@app.put("/api/menu/{week}/{track}/{day}")
def update_dish(week: int, track: str, day: str, body: DishUpdate) -> dict:
    """Chef edits a single dish. Validates constraints before saving."""
    path = _menu_path(week)
    if not path.exists():
        raise HTTPException(404, "Menu not generated yet for this week")

    if track not in ("meat", "vegetarian"):
        raise HTTPException(400, f"Unknown track: '{track}'")
    if day not in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        raise HTTPException(400, f"Unknown day: '{day}'")

    data = json.loads(path.read_text())
    data[track][day] = {
        "dish_name": body.dish_name,
        "ingredients": [
            {"product_id": i.product_id, "quantity_g": i.quantity_g}
            for i in body.ingredients
        ],
    }

    try:
        plan = WeeklyPlan.model_validate(data)
    except Exception as e:
        raise HTTPException(422, {"errors": [str(e)]})

    try:
        validate(plan, catalogue)
    except PlanValidationError as e:
        raise HTTPException(422, {"errors": e.errors})

    path.write_text(plan.model_dump_json())
    return summary_to_dict(build_summary(plan, catalogue), week)


# ---------------------------------------------------------------------------
# Catalogue (used by the UI to populate ingredient search)
# ---------------------------------------------------------------------------


@app.get("/api/catalogue")
def get_catalogue() -> dict:
    return {"products": catalogue.get_all_products()}


# ---------------------------------------------------------------------------
# Static frontend — must be last so API routes take priority
# ---------------------------------------------------------------------------


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
