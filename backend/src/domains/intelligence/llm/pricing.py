"""Model-keyed LLM pricing (USD per 1M tokens), externally configurable.

Previously the cost-attribution rate lived as a single hardcoded pair of
per-token settings.  That drifts the moment a provider changes
list prices or a second model is used, silently skewing the ``/metrics`` cost
counter.  Pricing is now keyed by model id with a built-in default table that
can be overridden **wholesale** via the ``LLM_PRICING_JSON`` env var — a JSON
object of ``{"<model-id>": {"input": <usd>, "output": <usd>}}`` — so operators
update rates without a code change.

An unknown model resolves to a zero-cost entry (cost attribution degrades to 0
rather than guessing a wrong rate); callers/dashboards can alert on a zero-rate
model if needed.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_mtok: float
    output_usd_per_mtok: float


# The Fireworks Gemma 4 deployment is GPU-hour billed (not per-token) and the
# Featherless backup is subscription-priced, so per-token cost attribution
# defaults to zero. Set an effective per-token rate via LLM_PRICING_JSON keyed by
# the exact model id (the Fireworks deployment path or the Featherless model id)
# if you want the /metrics cost counter populated.
_DEFAULTS: dict[str, ModelPrice] = {
    "google/gemma-4-31B-it": ModelPrice(0.0, 0.0),
}

_ZERO = ModelPrice(0.0, 0.0)


@lru_cache(maxsize=1)
def _table() -> dict[str, ModelPrice]:
    """Built-in defaults merged with any LLM_PRICING_JSON override (cached)."""
    table = dict(_DEFAULTS)
    raw = os.environ.get("LLM_PRICING_JSON", "").strip()
    if not raw:
        return table
    try:
        data = json.loads(raw)
        for model, entry in data.items():
            table[model] = ModelPrice(
                float(entry["input"]), float(entry["output"])
            )
    except (ValueError, KeyError, TypeError):
        logger.exception(
            "Invalid LLM_PRICING_JSON — falling back to built-in pricing defaults"
        )
        return dict(_DEFAULTS)
    return table


def price_for(model: str) -> ModelPrice:
    """Return the price entry for ``model`` (zero-cost entry if unknown)."""
    return _table().get(model, _ZERO)


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute the USD cost of one call from prompt/completion token counts."""
    price = price_for(model)
    return (
        prompt_tokens / 1_000_000 * price.input_usd_per_mtok
        + completion_tokens / 1_000_000 * price.output_usd_per_mtok
    )
