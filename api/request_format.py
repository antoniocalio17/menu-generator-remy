"""
Define the expected shape of request bodies for specific endpoints
pydantic models give us type safety and validation
"""

from pydantic import BaseModel


class IngredientPayload(BaseModel):
    product_id: int
    quantity_g: float


class DishUpdate(BaseModel):
    dish_name: str
    description: str = ""
    ingredients: list[IngredientPayload]


class SuggestRequest(BaseModel):
    track: str
    target_product_id: int
    ingredients: list[IngredientPayload]


class RenameRequest(BaseModel):
    track: str
    ingredients: list[IngredientPayload]
