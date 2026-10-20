"""GET /sports/now and GET /sports/catalog: what is on right now in every sport, and what the program covers.

    GET /sports/now       {generated_utc, families: [{code, label, live: [...], upcoming_24h: [...],
                          next_start_utc}]} -- from STORED rows; no call to The Odds API per request
    GET /sports/catalog   {families: [{code, label, markets, dog_menu, ...}]} -- the sport families, their
                          labels, the markets captured for each and whether a dog may bet it (PUBLIC)

All the logic is in src/sports/allsports_view.py and src/sports/catalog.py, which import without FastAPI
(Linux CI has none); this file only mounts them. /sports/now is mounted behind the same paid-demo gate as the
rest of the read-only game surface (api/app.py); the catalog is public, like /hounds/builder/menu.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.sports import allsports_view, catalog

router = APIRouter()
public_router = APIRouter()


@router.get("/sports/now")
def get_sports_now() -> dict:
    return allsports_view.cached_sports_now()


@public_router.get("/sports/catalog")
def get_sports_catalog() -> dict:
    return {"families": catalog.public_catalog(), "paper_only": True}
