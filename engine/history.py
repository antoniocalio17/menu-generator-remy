import json
from datetime import date
from pathlib import Path
from typing import cast

HISTORY_PATH = Path(__file__).parent.parent / "data" / "history.json"
MAX_WEEKS = 4
MAX_IOU = 0.65


def load(path: Path = HISTORY_PATH) -> list[dict[str, object]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    result: list[dict[str, object]] = json.loads(path.read_text())
    return result


def past_pool_ids(n_weeks: int = MAX_WEEKS, path: Path = HISTORY_PATH) -> list[set[int]]:
    """Return the pool product_id sets from the last n weeks.

    Used to check IoU against the new week's pool before calling the LLM.
    Each entry is the full set of product_ids shown to the LLM that week.
    """
    weeks = load(path)[-n_weeks:]
    return [set(cast(list[int], week["pool_ids"])) for week in weeks]


def pool_iou(a: set[int], b: set[int]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def is_pool_fresh(new_ids: set[int], past_weeks: list[set[int]], max_iou: float = MAX_IOU) -> bool:
    """Return True if the new pool is sufficiently different from all past weeks."""
    return all(pool_iou(new_ids, past) <= max_iou for past in past_weeks)


def save_week(week_start: str, pool_ids: list[int], path: Path = HISTORY_PATH) -> None:
    """Append this week's pool to history, keeping only the last MAX_WEEKS entries."""
    weeks = load(path)
    weeks.append(
        {
            "week_start": week_start,
            "pool_ids": pool_ids,
            "saved_at": date.today().isoformat(),
        }
    )
    path.write_text(json.dumps(weeks[-MAX_WEEKS:], indent=2, ensure_ascii=False))
