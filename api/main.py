"""
FastAPI app — exposes the menu generation pipeline and serves the chef UI.
Run with: uvicorn api.main:app --reload  (from the menu-generator/ directory)
"""

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from api.dependencies import LOG_DIR, MENUS_DIR, STATIC_DIR, catalogue, menu_path, week_start
from api.logging_config import setup_logging
from api.request_format import DishUpdate, RenameRequest, SuggestRequest
from engine.exporter import build_summary, summary_to_dict
from engine.fallback import FallbackError, build_fallback_plan
from engine.llm.groq_llama import generate
from engine.llm.response_format import PlannerError
from engine.llm.suggester import rename_dish, suggest_substitutes
from engine.output_format import WeeklyPlan
from engine.validator import PlanValidationError, validate

setup_logging(LOG_DIR)
logger = logging.getLogger(__name__)
logger.info("Heyra Menu Generator started")

app = FastAPI(title="Heyra Menu Generator")

_VALID_TRACKS = {"meat", "vegetarian"}
_VALID_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday"}


def _check_track(track: str) -> None:
    if track not in _VALID_TRACKS:
        raise HTTPException(400, f"Unknown track: '{track}'")


def _check_day(day: str) -> None:
    if day not in _VALID_DAYS:
        raise HTTPException(400, f"Unknown day: '{day}'")


def _ingredients_to_dicts(ingredients: list) -> list[dict]:
    return [{"product_id": i.product_id, "quantity_g": i.quantity_g} for i in ingredients]


@app.post("/api/generate/{year}/{week}")
def generate_week(year: int, week: int) -> dict:
    """Run the full pipeline for the given ISO year + week and store the result."""
    MENUS_DIR.mkdir(parents=True, exist_ok=True)
    ws = week_start(year, week)

    logger.info("Generate request — year=%d week=%d", year, week)
    fallback_used = False
    try:
        plan = generate(ws.isoformat(), catalogue=catalogue)
        logger.info("LLM plan ready — year=%d week=%d", year, week)
    except PlannerError as planner_err:
        logger.warning("LLM failed (%s) — attempting fallback", planner_err)
        try:
            plan = build_fallback_plan(
                ws.isoformat(),
                menus_dir=MENUS_DIR,
                exclude_path=menu_path(year, week),
            )
            fallback_used = True
            logger.warning("Fallback plan built for year=%d week=%d", year, week)
        except FallbackError as fb_err:
            logger.error("Fallback failed: %s", fb_err)
            raise HTTPException(503, str(fb_err)) from fb_err

    try:
        validate(plan, catalogue)
    except PlanValidationError as e:
        logger.warning("Validation failed for year=%d week=%d: %s", year, week, e.errors)
        raise HTTPException(422, {"errors": e.errors}) from e

    menu_path(year, week).write_text(plan.model_dump_json())
    logger.info("Menu saved — year=%d week=%d fallback=%s", year, week, fallback_used)
    result = summary_to_dict(build_summary(plan, catalogue), week)
    if fallback_used:
        result["fallback"] = True
    return result


@app.get("/api/menu/{year}/{week}")
def get_week(year: int, week: int) -> dict:
    """Return the stored menu for a year+week (404 if not yet generated)."""
    path = menu_path(year, week)
    if not path.exists():
        raise HTTPException(404, "Menu not generated yet for this week")
    plan = WeeklyPlan.model_validate_json(path.read_text())
    return summary_to_dict(build_summary(plan, catalogue), week)


@app.put("/api/menu/{year}/{week}/{track}/{day}")
def update_dish(year: int, week: int, track: str, day: str, body: DishUpdate) -> dict:
    """Chef edits a single dish. Validates constraints before saving."""
    path = menu_path(year, week)
    if not path.exists():
        raise HTTPException(404, "Menu not generated yet for this week")
    _check_track(track)
    _check_day(day)

    data = json.loads(path.read_text())
    data[track][day] = {
        "dish_name": body.dish_name,
        "description": body.description,
        "ingredients": _ingredients_to_dicts(body.ingredients),
    }

    try:
        plan = WeeklyPlan.model_validate(data)
    except Exception as e:
        raise HTTPException(422, {"errors": [str(e)]}) from e

    try:
        validate(plan, catalogue)
    except PlanValidationError as e:
        raise HTTPException(422, {"errors": e.errors}) from e

    path.write_text(plan.model_dump_json())
    logger.info("Dish updated — year=%d week=%d %s/%s", year, week, track, day)
    return summary_to_dict(build_summary(plan, catalogue), week)


@app.post("/api/suggest")
def suggest(body: SuggestRequest) -> dict:
    """Return AI-ranked substitute candidates for one ingredient slot."""
    _check_track(body.track)
    ingredients = _ingredients_to_dicts(body.ingredients)

    try:
        candidates = suggest_substitutes(
            ingredients, body.target_product_id, body.track, catalogue
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error("Suggester error: %s", e)
        raise HTTPException(503, "AI suggestion unavailable — try again in a moment") from e

    logger.info(
        "Suggest — track=%s target=%d candidates=%d",
        body.track, body.target_product_id, len(candidates),
    )
    return {"candidates": candidates}


@app.post("/api/rename-dish")
def rename(body: RenameRequest) -> dict:
    """Re-generate dish name and description after an ingredient swap."""
    _check_track(body.track)
    ingredients = _ingredients_to_dicts(body.ingredients)

    try:
        result = rename_dish(ingredients, body.track, catalogue)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error("Rename error: %s", e)
        raise HTTPException(503, "AI rename unavailable — try again in a moment") from e

    logger.info("Rename — track=%s → %s", body.track, result["dish_name"])
    return result


@app.get("/api/catalogue")
def get_catalogue() -> dict:
    return {"products": catalogue.get_all_products()}


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
