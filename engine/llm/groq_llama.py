"""
Calls the Groq LLM to name and describe pre-composed dishes.
The composer builds the ingredient sets; the LLM only handles naming,
description, and coherence validation.
"""

import logging
import os
import time
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import ValidationError

from engine.catalogue import Catalogue
from engine.composer import ComposedDish, ComposerError, compose_single_dish, compose_week
from engine.constants import (
    CUISINE_ROTATION,
    DAYS,
    GROQ_BASE_URL,
    GROQ_MODEL,
    NAMING_MAX_RETRIES,
    NAMING_OUTPUT_FORMAT,
    NAMING_RATE_LIMIT_BACKOFF,
    NAMING_SYSTEM_PROMPT,
    NAMING_TEMPERATURE,
)
from engine.llm.response_format import NamedDish, NamingResponse, PlannerError
from engine.output_format import WeeklyPlan

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


def _format_dish(dish: ComposedDish, idx: int) -> str:
    lines = [f"Dish {idx} [{dish.cuisine}]"]
    for product, qty in dish.products:
        lines.append(
            f"  {product['ingredient_group']} ({qty:.0f}g): "
            f"{product['product_name']} (id={product['product_id']})"
        )
    return "\n".join(lines)


def _prompt(
    meat_dishes: list[ComposedDish],
    veg_dishes: list[ComposedDish],
    errors: list[str],
) -> list[ChatCompletionMessageParam]:
    meat_section = "MEAT TRACK\n" + "\n\n".join(
        _format_dish(d, i + 1) for i, d in enumerate(meat_dishes)
    )
    veg_section = "VEGETARIAN TRACK\n" + "\n\n".join(
        _format_dish(d, i + 1) for i, d in enumerate(veg_dishes)
    )

    error_section = ""
    if errors:
        error_lines = "\n".join(f"- {e}" for e in errors)
        error_section = f"\nPREVIOUS ERRORS — fix these before responding:\n{error_lines}"

    user = f"{meat_section}\n\n{veg_section}\n\n{NAMING_OUTPUT_FORMAT}{error_section}"

    return [
        cast(ChatCompletionMessageParam, {"role": "system", "content": NAMING_SYSTEM_PROMPT}),
        cast(ChatCompletionMessageParam, {"role": "user", "content": user}),
    ]


def _validate_ids(
    naming: NamingResponse,
    meat_dishes: list[ComposedDish],
    veg_dishes: list[ComposedDish],
    catalogue: Catalogue,
) -> list[str]:
    errors: list[str] = []
    for track_name, named_list, composed_list in (
        ("meat", naming.meat, meat_dishes),
        ("vegetarian", naming.vegetarian, veg_dishes),
    ):
        for i, (named, composed) in enumerate(zip(named_list, composed_list, strict=True)):
            composed_ids = {p["product_id"] for p, _ in composed.products}
            for pid in named.ingredients:
                if catalogue.get_product_by_id(pid) is None:
                    errors.append(
                        f"{track_name} dish {i + 1}: product_id {pid} not in catalogue"
                    )
                elif pid not in composed_ids:
                    errors.append(
                        f"{track_name} dish {i + 1}: product_id {pid} was not in the "
                        "composed set — use only the IDs provided"
                    )
    return errors


def _assemble_plan(
    week_start: str,
    meat_dishes: list[ComposedDish],
    naming: NamingResponse,
    veg_dishes: list[ComposedDish],
) -> WeeklyPlan:
    def build_track(dishes: list[ComposedDish], named: list[NamedDish]) -> dict:
        return {
            day: dishes[i].to_dish(named[i].dish_name, named[i].description).model_dump()
            for i, day in enumerate(DAYS)
        }

    return WeeklyPlan.model_validate({
        "week_start": week_start,
        "meat": build_track(meat_dishes, naming.meat),
        "vegetarian": build_track(veg_dishes, naming.vegetarian),
    })


def generate(week_start: str, catalogue: Catalogue | None = None) -> WeeklyPlan:
    if catalogue is None:
        catalogue = Catalogue()

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL)

    logger.info("Composing dishes for week_start=%s", week_start)
    meat_dishes = compose_week("meat", catalogue)
    veg_dishes = compose_week("vegetarian", catalogue)

    # llama-3.3-70b-versatile only supports json_object, not json_schema.
    # Structural validation is handled by NamingResponse.model_validate_json().
    response_format = ResponseFormatJSONObject(type="json_object")

    errors: list[str] = []
    last_raw = ""
    rl_attempt = 0

    for attempt in range(1, NAMING_MAX_RETRIES + 1):
        logger.info("LLM naming call — attempt %d/%d", attempt, NAMING_MAX_RETRIES)
        messages = _prompt(meat_dishes, veg_dishes, errors)

        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=NAMING_TEMPERATURE,
                response_format=response_format,
            )
        except RateLimitError:
            wait = (
                NAMING_RATE_LIMIT_BACKOFF[rl_attempt]
                if rl_attempt < len(NAMING_RATE_LIMIT_BACKOFF)
                else None
            )
            if wait is not None:
                logger.warning("Rate limit hit — waiting %.0fs before retry", wait)
                time.sleep(wait)
                rl_attempt += 1
                continue
            logger.error("Rate limit exhausted after %d backoff attempts", rl_attempt)
            raise PlannerError("Groq rate limit exceeded — try again in a moment") from None
        except APIError as e:
            logger.error("Groq API error on attempt %d: %s", attempt, e)
            raise PlannerError(f"Groq API error: {e}") from e

        if response.usage:
            logger.info(
                "tokens attempt=%d prompt=%d completion=%d total=%d",
                attempt,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
            )
        last_raw = response.choices[0].message.content or ""

        try:
            naming = NamingResponse.model_validate_json(last_raw)
        except ValidationError as e:
            logger.warning("Attempt %d — schema validation failed: %s", attempt, e)
            errors.append(str(e))
            continue

        id_errors = _validate_ids(naming, meat_dishes, veg_dishes, catalogue)
        if id_errors:
            logger.warning("Attempt %d — invalid product IDs: %s", attempt, id_errors)
            errors.extend(id_errors)
            continue

        invalid: dict[str, list[int]] = {"meat": [], "vegetarian": []}
        for i, named in enumerate(naming.meat):
            if not named.valid:
                logger.warning("Meat dish %d flagged invalid — %s", i + 1, named.reason)
                invalid["meat"].append(i)
        for i, named in enumerate(naming.vegetarian):
            if not named.valid:
                logger.warning("Vegetarian dish %d flagged invalid — %s", i + 1, named.reason)
                invalid["vegetarian"].append(i)

        if invalid["meat"] or invalid["vegetarian"]:
            if attempt == NAMING_MAX_RETRIES:
                logger.warning(
                    "Accepting plan with %d flagged dish(es) after %d attempts — "
                    "re-composition exhausted",
                    len(invalid["meat"]) + len(invalid["vegetarian"]),
                    attempt,
                )
                return _assemble_plan(week_start, meat_dishes, naming, veg_dishes)

            for i in invalid["meat"]:
                seen = [meat_dishes[j].ingredient_set() for j in range(5) if j != i]
                try:
                    meat_dishes[i] = compose_single_dish(
                        "meat", CUISINE_ROTATION[i], catalogue, seen
                    )
                    logger.info("Re-composed meat dish %d", i + 1)
                except ComposerError as e:
                    logger.warning("Re-composition failed for meat dish %d: %s", i + 1, e)

            for i in invalid["vegetarian"]:
                seen = [veg_dishes[j].ingredient_set() for j in range(5) if j != i]
                try:
                    veg_dishes[i] = compose_single_dish(
                        "vegetarian", CUISINE_ROTATION[i], catalogue, seen
                    )
                    logger.info("Re-composed vegetarian dish %d", i + 1)
                except ComposerError as e:
                    logger.warning("Re-composition failed for vegetarian dish %d: %s", i + 1, e)

            errors.append(
                f"LLM flagged {len(invalid['meat'])} meat and "
                f"{len(invalid['vegetarian'])} vegetarian dishes as incoherent — re-composed"
            )
            continue

        logger.info("Valid naming received on attempt %d", attempt)
        return _assemble_plan(week_start, meat_dishes, naming, veg_dishes)

    logger.error("All %d attempts failed. Last response: %.200s", NAMING_MAX_RETRIES, last_raw)
    raise PlannerError(
        f"Failed to name dishes after {NAMING_MAX_RETRIES} attempts. "
        f"Last error: {errors[-1] if errors else 'unknown'}"
    )
