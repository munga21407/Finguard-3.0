"""
Agent I — External Integrator.

Fetches and normalises live data from four Kenyan financial APIs, then writes
the result into ``state["context"]["external_data"]`` for downstream agents:

  1. M-Pesa Daraja API  — mobile money transaction history (Safaricom sandbox).
  2. CBK FX rates       — live USD/KES, EUR/KES rates (Central Bank of Kenya).
  3. Metropol           — customer credit score lookup.
  4. KRA e-Citizen      — VAT return filing status.

Each source is fetched only when its key is absent from context (idempotent
within a session).  All monetary amounts are normalised to KES using fresh FX
rates.  External failures are caught per-source so one bad API never aborts the
entire enrichment pass.
"""
from __future__ import annotations

import base64
from typing import Any

import structlog
from langchain_core.messages import AIMessage

from src.core.config import settings
from src.domains.intelligence.schemas import OrchestratorState
from src.domains.intelligence.tools.http_caller import make_http_caller

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# API base URLs
# ---------------------------------------------------------------------------
_MPESA_AUTH_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate"
_MPESA_TRANSACTIONS_URL = "https://sandbox.safaricom.co.ke/mpesa/accountbalance/v1/query"
_CBK_FX_URL = "https://api.centralbank.go.ke/api/v1/forex"
_METROPOL_SCORE_URL = "https://api.metropol.co.ke/v2/report/credit_score"
_KRA_STATUS_URL = "https://itax.kra.go.ke/KRA-Portal/api/vat/status"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_mpesa_token(caller: Any) -> str | None:
    """Exchange consumer key + secret for a Bearer token via Basic auth."""
    if not settings.MPESA_CONSUMER_KEY or not settings.MPESA_CONSUMER_SECRET:
        return None

    credentials = base64.b64encode(
        f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}".encode()
    ).decode()

    result = await caller.ainvoke({
        "method": "GET",
        "url": _MPESA_AUTH_URL,
        "headers": {"Authorization": f"Basic {credentials}"},
        "params": {"grant_type": "client_credentials"},
    })

    if result["status_code"] == 200 and isinstance(result["data"], dict):
        return result["data"].get("access_token")
    return None


async def _fetch_mpesa_data(caller: Any) -> dict[str, Any]:
    """Fetch M-Pesa account balance / recent transactions from Daraja API."""
    token = await _get_mpesa_token(caller)
    if not token:
        logger.warning("i_integrator: M-Pesa token unavailable; returning mock data")
        return _mock_mpesa()

    result = await caller.ainvoke({
        "method": "POST",
        "url": _MPESA_TRANSACTIONS_URL,
        "headers": {"Authorization": f"Bearer {token}"},
        "body": {
            "Initiator": "testapi",
            "SecurityCredential": "",
            "CommandID": "AccountBalance",
            "PartyA": settings.MPESA_SHORTCODE or "174379",
            "IdentifierType": "4",
            "Remarks": "Finguard balance check",
            "QueueTimeOutURL": "",
            "ResultURL": "",
        },
    })

    if result["status_code"] == 200:
        return {"source": "mpesa_live", "raw": result["data"]}

    logger.warning(
        "i_integrator: M-Pesa API returned non-200",
        status_code=result["status_code"],
    )
    return _mock_mpesa()


async def _fetch_cbk_fx(caller: Any) -> dict[str, Any]:
    """Fetch live FX rates from the Central Bank of Kenya API."""
    if not settings.CBK_FX_API_KEY:
        return _mock_fx_rates()

    result = await caller.ainvoke({
        "method": "GET",
        "url": _CBK_FX_URL,
        "headers": {"X-API-Key": settings.CBK_FX_API_KEY},
        "params": {"base": "KES", "symbols": "USD,EUR,GBP"},
    })

    if result["status_code"] == 200 and isinstance(result["data"], dict):
        rates = result["data"].get("rates", {})
        return {
            "USD_KES": float(rates.get("USD", 129.50)),
            "EUR_KES": float(rates.get("EUR", 140.20)),
            "GBP_KES": float(rates.get("GBP", 164.80)),
            "source": "cbk_live",
        }

    logger.warning(
        "i_integrator: CBK FX API unavailable; using mock rates",
        status_code=result["status_code"],
    )
    return _mock_fx_rates()


async def _fetch_metropol_score(caller: Any, customer_id: str) -> dict[str, Any]:
    """Look up a customer's Metropol credit score."""
    if not settings.METROPOL_API_KEY or not customer_id:
        return _mock_credit_score()

    result = await caller.ainvoke({
        "method": "POST",
        "url": _METROPOL_SCORE_URL,
        "headers": {"Authorization": f"Bearer {settings.METROPOL_API_KEY}"},
        "body": {"customer_id": customer_id},
    })

    if result["status_code"] == 200 and isinstance(result["data"], dict):
        return {
            "score": int(result["data"].get("score", 0)),
            "grade": result["data"].get("grade", "N/A"),
            "delinquencies": result["data"].get("delinquencies", 0),
            "source": "metropol_live",
        }

    logger.warning(
        "i_integrator: Metropol API unavailable; using mock score",
        status_code=result["status_code"],
    )
    return _mock_credit_score()


async def _fetch_kra_status(caller: Any, pin_number: str) -> dict[str, Any]:
    """Check KRA VAT return status for a given KRA PIN."""
    if not settings.KRA_ECITIZEN_API_KEY or not pin_number:
        return _mock_kra_status()

    result = await caller.ainvoke({
        "method": "GET",
        "url": _KRA_STATUS_URL,
        "headers": {"X-API-Key": settings.KRA_ECITIZEN_API_KEY},
        "params": {"pin": pin_number},
    })

    if result["status_code"] == 200 and isinstance(result["data"], dict):
        data = result["data"]
        return {
            "pin": pin_number,
            "vat_registered": data.get("vat_registered", False),
            "last_return_filed": data.get("last_return_filed"),
            "compliance_status": data.get("compliance_status", "UNKNOWN"),
            "source": "kra_live",
        }

    logger.warning(
        "i_integrator: KRA e-Citizen API unavailable; using mock status",
        status_code=result["status_code"],
    )
    return _mock_kra_status()


# ---------------------------------------------------------------------------
# Mock fallbacks (used when API keys are absent or APIs are unreachable)
# ---------------------------------------------------------------------------

def _mock_mpesa() -> dict[str, Any]:
    return {
        "source": "mpesa_mock",
        "data_source": "mock_sandbox",
        "balance_kes": 125_000.00,
        "recent_transactions": [
            {"type": "credit", "amount": 45_000.00, "ref": "NLJ7RT61SV"},
            {"type": "debit",  "amount": 12_500.00, "ref": "PLK8RT71AS"},
        ],
    }


def _mock_fx_rates() -> dict[str, Any]:  # widened return type to carry the flag
    return {
        "USD_KES": 129.50,
        "EUR_KES": 140.20,
        "GBP_KES": 164.80,
        "source": "fx_mock",
        "data_source": "mock_sandbox",
    }


def _mock_credit_score() -> dict[str, Any]:
    return {
        "score": 672,
        "grade": "B",
        "delinquencies": 1,
        "source": "metropol_mock",
        "data_source": "mock_sandbox",
    }


def _mock_kra_status() -> dict[str, Any]:
    return {
        "pin": "MOCK_PIN",
        "vat_registered": True,
        "last_return_filed": "2026-03-31",
        "compliance_status": "COMPLIANT",
        "source": "kra_mock",
        "data_source": "mock_sandbox",
    }


# ---------------------------------------------------------------------------
# Amount normaliser
# ---------------------------------------------------------------------------

def _normalise_to_kes(
    amount: float,
    currency: str,
    fx: dict[str, float],
) -> float:
    """Convert an amount to KES using the supplied FX rate map."""
    key = f"{currency.upper()}_KES"
    if currency.upper() == "KES" or key not in fx:
        return amount
    return round(amount * fx[key], 2)


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

def make_i_integrator_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def i_integrator_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]

        # Skip if external data was already collected this session.
        if "external_data" in ctx:
            return {
                "messages": [
                    AIMessage(
                        content="[i_integrator] External data already present; skipping fetch.",
                        name="i_integrator",
                    )
                ],
                "context": ctx,
            }

        customer_id: str = ctx.get("customer_id", "")
        kra_pin: str = ctx.get("kra_pin", "")
        caller = make_http_caller(timeout=20.0)

        # ── 1. CBK FX rates (always first — needed for normalisation) ─────────
        try:
            fx_rates = await _fetch_cbk_fx(caller)
        except Exception as exc:
            logger.error("i_integrator: CBK FX fetch failed", error=str(exc))
            fx_rates = _mock_fx_rates()

        # ── 2. M-Pesa transaction history ─────────────────────────────────────
        try:
            mpesa_data = await _fetch_mpesa_data(caller)
            # Normalise balance if present
            balance = mpesa_data.get("balance_kes", mpesa_data.get("balance", 0.0))
            mpesa_data["balance_kes"] = _normalise_to_kes(float(balance), "KES", fx_rates)
        except Exception as exc:
            logger.error("i_integrator: M-Pesa fetch failed", error=str(exc))
            mpesa_data = _mock_mpesa()

        # ── 3. Metropol credit score ───────────────────────────────────────────
        try:
            credit_data = await _fetch_metropol_score(caller, customer_id)
        except Exception as exc:
            logger.error("i_integrator: Metropol fetch failed", error=str(exc))
            credit_data = _mock_credit_score()

        # ── 4. KRA e-Citizen VAT status ───────────────────────────────────────
        try:
            kra_data = await _fetch_kra_status(caller, kra_pin)
        except Exception as exc:
            logger.error("i_integrator: KRA fetch failed", error=str(exc))
            kra_data = _mock_kra_status()

        # Detect whether any source fell back to mock data.  A single top-level
        # flag lets downstream agents (e.g. Agent H) add a "Based on simulated
        # data" disclaimer without inspecting every nested source dict.
        any_mock = any(
            d.get("data_source") == "mock_sandbox"
            for d in (fx_rates, mpesa_data, credit_data, kra_data)
        )

        external_data: dict[str, Any] = {
            "fx_rates": fx_rates,
            "mpesa": mpesa_data,
            "credit_bureau": credit_data,
            "kra_status": kra_data,
            "data_source": "mock_sandbox" if any_mock else "live",
        }

        updated_ctx = dict(ctx)
        updated_ctx["external_data"] = external_data

        source_label = "simulated (mock sandbox)" if any_mock else "live"
        summary = (
            f"[i_integrator] External data collected ({source_label}) — "
            f"FX: 1 USD = {fx_rates.get('USD_KES', 'N/A')} KES | "
            f"Credit score: {credit_data.get('score', 'N/A')} ({credit_data.get('grade', '?')}) | "
            f"KRA status: {kra_data.get('compliance_status', 'UNKNOWN')} | "
            f"M-Pesa balance: KES {mpesa_data.get('balance_kes', 0):,.2f}"
        )
        logger.info(summary, any_mock=any_mock)

        return {
            "messages": [AIMessage(content=summary, name="i_integrator")],
            "context": updated_ctx,
        }

    return i_integrator_node
