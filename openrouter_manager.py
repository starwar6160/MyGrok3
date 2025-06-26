"""OpenRouter model and pricing management utilities.

This module centralises all logic related to fetching, caching and refreshing
OpenRouter model information and pricing data.  It was extracted from
``grok3.py`` to improve separation of concerns and keep the main application
module focused on Flask-specific code.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

from MyGrok3 import logging_config

logger = logging_config.configure_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration & globals
# ---------------------------------------------------------------------------

OPENROUTER_MODELS_API = "https://openrouter.ai/api/v1/models"
OPENROUTER_PRICE_CACHE_PATH = Path(__file__).with_name("openrouter_model_prices.json")

# { 'models': List[dict], 'price_dict': Dict[str, Dict[str, float]], 'last_fetch': datetime }
openrouter_models_cache: Dict[str, object] = {
    "models": [],
    "price_dict": {},
    "last_fetch": None,
}

# Environment-driven API key (same one used by OpenAI client in grok3)
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set – OpenRouter price fetching will fail.")

# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _save_price_cache() -> None:
    """Persist today’s pricing information to JSON on disk."""
    try:
        data = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "models": openrouter_models_cache["models"],
            "price_dict": openrouter_models_cache["price_dict"],
        }
        with OPENROUTER_PRICE_CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("Saved OpenRouter price cache to %s", OPENROUTER_PRICE_CACHE_PATH)
    except Exception as exc:  # pragma: no cover – defensive logging
        logger.error("Failed to save OpenRouter price cache: %s", exc)


def _load_price_cache() -> bool:
    """Load today’s pricing information from disk (if present & fresh)."""
    if not OPENROUTER_PRICE_CACHE_PATH.exists():
        return False

    try:
        with OPENROUTER_PRICE_CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return False  # Stale cache

        openrouter_models_cache["models"] = data.get("models", [])
        openrouter_models_cache["price_dict"] = data.get("price_dict", {})
        openrouter_models_cache["last_fetch"] = datetime.now()
        logger.debug("Loaded OpenRouter price cache from disk.")
        return True
    except Exception as exc:  # pragma: no cover – defensive logging
        logger.error("Failed to load OpenRouter price cache: %s", exc)
        return False

# ---------------------------------------------------------------------------
# Remote fetch helpers
# ---------------------------------------------------------------------------

def _fetch_openrouter_models() -> None:
    """Retrieve full model list and pricing from the OpenRouter API."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not configured – cannot fetch OpenRouter models.")
        return

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    try:
        resp = requests.get(OPENROUTER_MODELS_API, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning("Failed to fetch OpenRouter models – HTTP %s", resp.status_code)
            return

        data = resp.json()
        models: List[dict] = data.get("data", [])
        price_dict: Dict[str, Dict[str, float]] = {}

        for model in models:
            model_id: str = model.get("id")
            pricing: Dict = model.get("pricing", {})
            try:
                input_price = float(pricing.get("prompt", 0))
                output_price = float(pricing.get("completion", 0))
            except Exception:
                input_price = output_price = 0.0
            price_dict[model_id] = {"input": input_price, "output": output_price}

        openrouter_models_cache.update({
            "models": models,
            "price_dict": price_dict,
            "last_fetch": datetime.now(),
        })

        logger.info("OpenRouter model/pricing cache updated – %d models", len(models))
        _save_price_cache()
    except Exception as exc:  # pragma: no cover – defensive logging
        logger.error("Exception fetching OpenRouter models: %s", exc)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_openrouter_models(force_refresh: bool = False) -> None:
    """Ensure the cache is populated and fresh (≈24 h freshness)."""
    if force_refresh:
        logger.info("Forcing refresh of OpenRouter model prices.")
        _fetch_openrouter_models()
        return

    now = datetime.now()
    last: Optional[datetime] = openrouter_models_cache.get("last_fetch")  # type: ignore[arg-type]

    # Attempt to load today’s cached file if memory cache empty
    if (not openrouter_models_cache["models"] or not openrouter_models_cache["price_dict"]):
        _load_price_cache()
        last = openrouter_models_cache.get("last_fetch")  # type: ignore[arg-type]

    if not last or (now - last > timedelta(hours=24)):
        _fetch_openrouter_models()

    # Start background refresh thread once
    if not getattr(ensure_openrouter_models, "_started", False):
        threading.Thread(target=_refresh_loop, daemon=True).start()
        ensure_openrouter_models._started = True


def _refresh_loop() -> None:
    while True:
        _fetch_openrouter_models()
        time.sleep(24 * 60 * 60)  # Refresh daily


def get_1m_output_cost(model_name: str) -> float:
    """Return the cost (USD) of 1 M output tokens for *model_name*."""
    ensure_openrouter_models()
    price = openrouter_models_cache["price_dict"].get(model_name)
    return price["output"] * 1_000_000 if price else 0.0


def suggest_cheaper_models(current_model: str, max_output_cost: float = 1.0) -> List[str]:
    """Suggest up to 2 cheaper models under *max_output_cost* per 1 M tokens."""
    ensure_openrouter_models()
    cheaper = [
        m for m, v in openrouter_models_cache["price_dict"].items()
        if v["output"] * 1_000_000 < max_output_cost and m != current_model
    ]
    return cheaper[:2]
