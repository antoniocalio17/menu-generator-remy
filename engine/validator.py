"""
Validates a WeeklyPlan against the catalogue.
Checks that all product_ids exist, meat track has meat, vegetarian track has no meat,
and each track stays within the weekly budget.
"""

from engine.catalogue import Catalogue, IngredientInput, Product
from engine.constants import DAYS, MEAT_GROUPS, WEEKLY_BUDGET_EUR
from engine.output_format import Dish, TrackPlan, WeeklyPlan


class PlanValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def fix_budget(plan: WeeklyPlan, catalogue: Catalogue) -> WeeklyPlan:
    """Replace expensive ingredients with cheaper ones from the same group until within budget.

    Works one ingredient at a time: always targets the single highest-cost ingredient
    across all dishes in the track, swaps it for the cheapest available alternative
    in the same ingredient_group, skipping swaps that would produce a duplicate dish.
    Returns the plan unchanged if it is already within budget or no swap is possible.
    """
    data = plan.model_dump()
    data["meat"] = _fix_track_budget(data["meat"], "meat", catalogue)
    data["vegetarian"] = _fix_track_budget(data["vegetarian"], "vegetarian", catalogue)
    return WeeklyPlan.model_validate(data)


def _track_cost(track: dict, catalogue: Catalogue) -> float:
    total = 0.0
    for day in DAYS:
        known = [
            ing
            for ing in track[day]["ingredients"]
            if catalogue.get_product_by_id(ing["product_id"]) is not None
        ]
        if known:
            total += catalogue.compute_meal_stats(known).cost_eur
    return total


def _find_priciest_ingredient(track: dict, catalogue: Catalogue) -> tuple[str, int, Product] | None:
    """Return (day, ingredient_index, product) for the ingredient with the highest cost."""
    target_day = ""
    target_idx = 0
    highest_cost = 0.0

    for day in DAYS:
        for idx, ing in enumerate(track[day]["ingredients"]):
            product = catalogue.get_product_by_id(ing["product_id"])
            if product is None:
                continue
            cost = product["cost_per_100g_eur"] * ing["quantity_g"] / 100
            if cost > highest_cost:
                highest_cost = cost
                target_day = day
                target_idx = idx

    if not target_day:
        return None

    pid = track[target_day]["ingredients"][target_idx]["product_id"]
    product = catalogue.get_product_by_id(pid)
    return (target_day, target_idx, product) if product is not None else None


def _fix_track_budget(track: dict, track_name: str, catalogue: Catalogue) -> dict:
    while _track_cost(track, catalogue) > WEEKLY_BUDGET_EUR:
        priciest = _find_priciest_ingredient(track, catalogue)
        if priciest is None:
            break

        target_day, target_idx, target_product = priciest

        existing_sets = [
            frozenset(ing["product_id"] for ing in track[day]["ingredients"]) for day in DAYS
        ]
        other_sets = [s for day, s in zip(DAYS, existing_sets, strict=True) if day != target_day]

        alternatives = catalogue.get_cheaper_in_group(
            target_product["ingredient_group"],
            target_product["cost_per_100g_eur"],
            track_name,
        )

        swapped = False
        for alt in alternatives:
            new_ids = frozenset(
                alt["product_id"] if i == target_idx else ing["product_id"]
                for i, ing in enumerate(track[target_day]["ingredients"])
            )
            if new_ids not in other_sets:
                track[target_day]["ingredients"][target_idx]["product_id"] = alt["product_id"]
                swapped = True
                break

        if not swapped:
            break

    return track


def validate(plan: WeeklyPlan, catalogue: Catalogue) -> None:
    """Raise PlanValidationError listing all constraint violations found in the plan."""
    errors: list[str] = []
    _check_track(plan.meat, "meat", catalogue, errors)
    _check_track(plan.vegetarian, "vegetarian", catalogue, errors)
    if errors:
        raise PlanValidationError(errors)


def _check_track(
    track: TrackPlan, track_name: str, catalogue: Catalogue, errors: list[str]
) -> None:
    weekly_cost = 0.0

    for day in DAYS:
        dish = getattr(track, day)
        _check_dish(dish, day, track_name, catalogue, errors)

        known_ingredients: list[IngredientInput] = [
            {"product_id": ing.product_id, "quantity_g": ing.quantity_g}
            for ing in dish.ingredients
            if catalogue.get_product_by_id(ing.product_id) is not None
        ]
        if known_ingredients:
            weekly_cost += catalogue.compute_meal_stats(known_ingredients).cost_eur

    if weekly_cost > WEEKLY_BUDGET_EUR:
        errors.append(
            f"{track_name}: weekly cost {weekly_cost:.2f} EUR "
            f"exceeds budget of {WEEKLY_BUDGET_EUR:.2f} EUR"
        )


def _check_dish(
    dish: Dish, day: str, track_name: str, catalogue: Catalogue, errors: list[str]
) -> None:
    has_meat_protein = False

    for ing in dish.ingredients:
        product = catalogue.get_product_by_id(ing.product_id)
        if product is None:
            errors.append(
                f"{track_name}/{day}/{dish.dish_name}: "
                f"product_id {ing.product_id} not found in catalogue"
            )
            continue

        if product["ingredient_group"] in MEAT_GROUPS:
            has_meat_protein = True

        if track_name == "vegetarian" and product["dietary_class"] == "meat":
            errors.append(
                f"{track_name}/{day}/{dish.dish_name}: "
                f"'{product['product_name']}' (id={ing.product_id}) is a meat product "
                f"— not allowed in the vegetarian track"
            )

    if track_name == "meat" and not has_meat_protein:
        errors.append(
            f"{track_name}/{day}/{dish.dish_name}: "
            f"no meat/poultry/fish/seafood/charcuterie ingredient found"
        )
