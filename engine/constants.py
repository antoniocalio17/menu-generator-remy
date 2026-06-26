"""
Shared constants used across engine modules.
Import from here — do not redefine in individual modules.
"""

DAYS: list[str] = ["monday", "tuesday", "wednesday", "thursday", "friday"]

VEGETARIAN_CLASSES: frozenset[str] = frozenset({"vegan", "vegetarian"})

PROTEIN_ROLE: dict[str, str] = {
    "meat": "protein_meat",
    "vegetarian": "protein_veg",
}

DISH_ROLES: list[str] = ["carb", "vegetable", "sauce"]

# All 29 ingredient groups mapped to the 5 recipe roles.
ROLE_GROUPS: dict[str, list[str]] = {
    "protein_meat": ["meat", "poultry", "fish", "seafood", "charcuterie"],
    "protein_veg":  ["legumes", "eggs", "plant proteins", "cheeses", "nuts"],
    "carb":         ["grains", "rices", "pastas", "breads"],
    "vegetable":    ["vegetables", "mushrooms"],
    "sauce": [
        "sauces",
        "condiments",
        "oils",
        "herbs",
        "spices",
        "creams and butters",
        "yogurts",
    ],
}

# Ingredient groups that count as meat protein (used by validator)
MEAT_GROUPS: frozenset[str] = frozenset(ROLE_GROUPS["protein_meat"])

WEEKLY_BUDGET_EUR: float = 20.10

# Cuisine target per day slot (Mon→Fri). Mediterranean appears twice — richest pool.
CUISINE_ROTATION: list[str] = [
    "mediterranean",
    "asian",
    "nordic",
    "middle_eastern",
    "mediterranean",
]
