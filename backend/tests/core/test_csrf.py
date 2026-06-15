"""Double-submit CSRF logic: token validation + the middleware's enforce/skip
decision (safe methods, exempt allowlist, and the CSRF_ENABLED kill-switch).

Tests target the pure helpers so they need no DB / event loop; the middleware
just composes ``_csrf_required`` + ``_validate_tokens``. An end-to-end HTTP
assertion belongs in an integration test (requires the app + DB).
"""
from __future__ import annotations

import pytest

from src.core import csrf
from src.core.csrf import _csrf_required, _validate_tokens

_TOKEN = "a" * 64


# ── token validation ────────────────────────────────────────────────────────

def test_matching_tokens_ok() -> None:
    assert _validate_tokens(_TOKEN, _TOKEN) is None


def test_missing_token_rejected() -> None:
    assert _validate_tokens(None, _TOKEN) == "CSRF validation failed: missing token"
    assert _validate_tokens(_TOKEN, None) == "CSRF validation failed: missing token"
    assert _validate_tokens("", "") == "CSRF validation failed: missing token"


def test_mismatched_token_rejected() -> None:
    assert _validate_tokens(_TOKEN, "b" * 64) == "CSRF validation failed: token mismatch"


# ── enforce/skip decision ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _enable_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    # The suite disables CSRF globally; turn it back on for these tests.
    monkeypatch.setattr(csrf.settings, "CSRF_ENABLED", True)


def test_safe_methods_skip_enforcement() -> None:
    for method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        assert _csrf_required(method, "/api/v1/finance/budgets") is False


def test_mutating_method_requires_csrf() -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert _csrf_required(method, "/api/v1/finance/budgets") is True


def test_exempt_paths_skip_enforcement() -> None:
    # Each is a justified hole: inbound webhook + the unauthenticated auth bootstrap.
    assert _csrf_required("POST", "/api/v1/finance/mpesa/callback") is False
    assert _csrf_required("POST", "/api/v1/identity/token") is False
    assert _csrf_required("POST", "/api/v1/identity/register") is False


def test_disabled_flag_skips_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(csrf.settings, "CSRF_ENABLED", False)
    assert _csrf_required("POST", "/api/v1/finance/budgets") is False
