"""
Shared dependencies: paths, catalogue instance, and path helpers.
Imported by routers — do not import from main.py.
"""

import logging
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from engine.catalogue import Catalogue

MENUS_DIR = Path(__file__).parent.parent / "data" / "menus"
STATIC_DIR = Path(__file__).parent.parent / "web_app"
LOG_DIR = Path(__file__).parent.parent / "data" / "logs"

catalogue = Catalogue()
logging.getLogger(__name__).info(
    "Catalogue loaded — %d products", len(catalogue.get_all_products())
)


def week_start(year: int, week: int) -> date:
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError as e:
        raise HTTPException(400, f"Invalid week {week} for year {year}") from e


def menu_path(year: int, week: int) -> Path:
    return MENUS_DIR / f"{year}_w{week:02d}.json"
