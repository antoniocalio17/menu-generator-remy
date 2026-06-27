"""
Pydantic models for LLM request/response validation.
Used by groq_llama.py and suggester.py.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from engine.constants import SUGGEST_MAX_CANDIDATES


class PlannerError(Exception):
    pass


class NamedDish(BaseModel):
    dish_name: Annotated[str, Field(min_length=1)]
    description: str
    ingredients: list[int]
    valid: bool
    reason: str = ""


class NamingResponse(BaseModel):
    meat: Annotated[list[NamedDish], Field(min_length=5, max_length=5)]
    vegetarian: Annotated[list[NamedDish], Field(min_length=5, max_length=5)]


class RenameResponse(BaseModel):
    dish_name: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]


class SuggestionCandidate(BaseModel):
    product_id: int
    reason: Annotated[str, Field(min_length=1)]


class SuggestionResponse(BaseModel):
    candidates: Annotated[
        list[SuggestionCandidate],
        Field(min_length=1, max_length=SUGGEST_MAX_CANDIDATES),
    ]
