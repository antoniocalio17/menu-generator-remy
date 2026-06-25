"""
Calls the Groq LLM with the candidate ingredient pools and returns a validated WeeklyPlan.
"""

import json
import os
from pathlib import Path
from typing import cast
from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import ValidationError
from engine.catalogue import Catalogue, Product, TrackPool, WeeklyPools
from engine.output_format import WeeklyPlan

load_dotenv(Path(__file__).parent / ".env")

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_MODEL = "llama-3.3-70b-versatile"
_TEMPERATURE = 0.2
_MAX_RETRIES = 3


class PlannerError(Exception):
    pass


def _format_products(products: list[Product]) -> str:
    """
    For each product we have :
     product_id, product_name, ingredient_group, cost_per_100g_eur,
     energy_kcal_per_100g, allergen_gluten, allergen_nuts, allergen_dairy.
    """
    lines = []
    for p in products:
        allergens = []
        if p["allergen_gluten"] == 1:
            allergens.append("gluten")
        if p["allergen_nuts"] == 1:
            allergens.append("nuts")
        if p["allergen_dairy"] == 1:
            allergens.append("dairy")
        allergen_str = ", ".join(allergens) if allergens else "none"
        lines.append(
            f"  id={p['product_id']} | {p['product_name']} | {p['ingredient_group']} | "
            f"{p['cost_per_100g_eur']:.2f} EUR/100g | {p['energy_kcal_per_100g']:.0f} kcal/100g | "
            f"allergens: {allergen_str}"
        )
    return "\n".join(lines)


def _format_track(pool: TrackPool) -> str:
    """
    For each role we list the products
    """
    return "\n\n".join(f"[{role}]\n{_format_products(products)}" for role, products in pool.items())


def _prompt_messages(
    pools: WeeklyPools,
    week_start: str,
    errors: list[str],
) -> list[ChatCompletionMessageParam]:
    system = (
        "You are a canteen menu planner for a company cafeteria.\n"
        "Generate a full week of lunch main dishes (Monday to Friday) for two tracks: "
        "meat and vegetarian.\n"
        "Use ONLY the products listed in the candidate pools — do not invent products.\n"
        "Return valid JSON matching the schema exactly. No explanation, no markdown."
    )

    constraints = f"""\
CONSTRAINTS
- week_start: {week_start}
- Meat track: every dish must include at least one meat/poultry/fish/seafood/charcuterie product
- Vegetarian track: use only vegan or vegetarian products — no meat
- Each dish must be a complete main: protein + carb + vegetables + sauce
- Realistic canteen quantities: protein 100-200g | carb 80-150g | vegetables 80-120g | sauce 20-50g
- 5 distinct dishes per track — no repeated dishes within the week
- Stay within 20.10 euros per week per track"""

    pools_section = (
        f"MEAT TRACK\n{_format_track(pools['meat'])}\n\n"
        f"VEGETARIAN TRACK\n{_format_track(pools['vegetarian'])}"
    )
    schema = json.dumps(WeeklyPlan.model_json_schema(), indent=2)
    error_section = ""
    if errors:
        error_lines = "\n".join(f"- {e}" for e in errors)
        error_section = f"\nPREVIOUS ERRORS — fix these before responding:\n{error_lines}"

    user = f"{constraints}\n\n{pools_section}\n\nJSON SCHEMA\n{schema}{error_section}"

    return [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system}),
        cast(ChatCompletionMessageParam, {"role": "user", "content": user}),
    ]


def generate(week_start: str, catalogue: Catalogue | None = None) -> WeeklyPlan:
    if catalogue is None:
        catalogue = Catalogue()

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=_GROQ_BASE_URL)
    pools = catalogue.build_weekly_pools()

    errors: list[str] = []
    last_raw = ""

    for _ in range(_MAX_RETRIES):
        messages = _prompt_messages(pools, week_start, errors)
        response = client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=_TEMPERATURE,
            response_format=ResponseFormatJSONObject(type="json_object"),
        )
        last_raw = response.choices[0].message.content or ""

        try:
            return WeeklyPlan.model_validate_json(last_raw)
        except ValidationError as e:
            errors.append(str(e))

    raise PlannerError(
        f"Failed to generate a valid plan after {_MAX_RETRIES} attempts.\n"
        f"Last error: {errors[-1]}\n"
        f"Last response: {last_raw}"
    )
