"""Contract test: every backend-emitted GenUI component_id is registered on the
frontend.

The backend emits ``component_id`` strings that the Next.js chat resolves against
``GenUiRegistry.tsx`` (via ``next/dynamic``). If the backend emits an id the
frontend hasn't registered, the widget silently degrades to fallback text — a
contract drift that no type system catches across the Python/TypeScript boundary.

This test parses the registry keys straight from the .tsx source and asserts the
backend's expected component set is fully present, failing loudly (with the exact
missing ids) when the two sides drift.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.domains.intelligence.prompts.h_advisor import H_ADVISOR_ALLOWED_COMPONENTS

# backend/tests/integration/this_file → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = (
    _REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "dashboard"
    / "intelligence"
    / "GenUiRegistry.tsx"
)

# component_ids the Python agents construct as hard literals (CompositeGenUIPayload).
_AGENT_EMITTED_COMPONENTS = frozenset(
    {
        "CashFlowChart",        # Agent D — Cash-Flow Forecaster
        "BudgetWatchdogMeter",  # Agent E — Budget Watchdog
        "TaxLiabilityDonut",    # Agent F — Tax Auditor
        "BankabilityScoreRadar",  # Agent G — Credit Strategist
    }
)

# Everything the backend can put on the wire = fixed agent widgets + the library
# components Agent H may emit per its GenUI catalog.
EXPECTED_BACKEND_COMPONENTS = _AGENT_EMITTED_COMPONENTS | H_ADVISOR_ALLOWED_COMPONENTS

# Registry keys look like:   ComponentName: dynamic(
_REGISTRY_KEY_RE = re.compile(r"(\w+):\s*dynamic\(")


def _parse_registry_keys(source: str) -> set[str]:
    return set(_REGISTRY_KEY_RE.findall(source))


def test_registry_file_exists_and_is_parseable() -> None:
    assert _REGISTRY_PATH.is_file(), f"GenUiRegistry.tsx not found at {_REGISTRY_PATH}"
    keys = _parse_registry_keys(_REGISTRY_PATH.read_text(encoding="utf-8"))
    # Sanity: the registry should not be empty, or our regex/path is wrong.
    assert keys, "No `name: dynamic(` registry entries parsed — check the regex/path."


def test_all_backend_components_are_registered_on_frontend() -> None:
    registry_keys = _parse_registry_keys(_REGISTRY_PATH.read_text(encoding="utf-8"))

    missing = sorted(EXPECTED_BACKEND_COMPONENTS - registry_keys)
    assert not missing, (
        "GenUI contract drift — these backend-emitted component_id(s) are NOT "
        f"registered in GenUiRegistry.tsx: {missing}. "
        "Add a `next/dynamic` entry for each (key must match the backend id "
        "exactly) or the widget will silently fall back to text in the chat. "
        f"Registered keys found: {sorted(registry_keys)}"
    )
