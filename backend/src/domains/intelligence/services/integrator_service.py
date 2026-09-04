"""
External data integration for Agent I (External Integrator).

Framework-agnostic core: fetches and normalises FX rates, M-Pesa, Metropol
credit score, and KRA VAT/compliance status — none of it depends on
LangGraph or ``OrchestratorState``, so it's testable and callable without a
graph. ``agents.i_integrator.make_i_integrator_node`` is a thin adapter that
reads state, calls :func:`fetch_external_data`, and shapes the summary
message.

Honesty model — every source carries an explicit ``status`` so no consumer
ever mistakes simulated data for real:

  - ``live``        — real data from the provider.
  - ``manual``      — operator-supplied value (KRA / Metropol manual entry).
  - ``mock``        — simulated dev-only data (never emitted in production).
  - ``unavailable`` — not configured / unreachable. **No fabricated values.**

Sources:
  1. FX rates — free, keyless public provider (``FX_API_URL``); USD-based
     cross-rates → ``*_KES``. Mock only in dev; ``unavailable`` in prod.
  2. M-Pesa   — real transaction feed from the ``mpesa_transactions`` ledger
     (ingested via the C2B/STK callback); ``live`` when the ledger has rows.
     Falls back to the Daraja **sandbox** AccountBalance probe (mock in dev /
     ``unavailable`` in prod) only when the ledger is empty.
  3. Metropol — credit score. Commercial API: deferred. Manual entry via
     ``context["manual_credit_score"]``; otherwise ``unavailable`` (never faked).
  4. KRA      — VAT/compliance. iTax onboarding: deferred. Manual entry via
     ``context["manual_kra_status"]``; otherwise ``unavailable`` (never faked).

Each source is fetched once per session; failures are isolated so one bad source
never aborts the enrichment pass.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from src.core.config import settings
from src.domains.intelligence.tools.http_caller import make_http_caller
from src.infrastructure.database.postgres import AsyncSessionLocal

logger = structlog.get_logger(__name__)

# Explicit per-source provenance.
LIVE, MANUAL, MOCK, UNAVAILABLE = "live", "manual", "mock", "unavailable"

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
_MPESA_AUTH_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate"
# NOTE: this is the AccountBalance endpoint, not a transaction-history feed.
# Real per-transaction data arrives via the C2B/STK callback at
# POST /api/v1/finance/mpesa/callback — this call is only a balance probe.
_MPESA_BALANCE_URL = "https://sandbox.safaricom.co.ke/mpesa/accountbalance/v1/query"
_METROPOL_SCORE_URL = "https://api.metropol.co.ke/v2/report/credit_score"
_KRA_STATUS_URL = "https://itax.kra.go.ke/KRA-Portal/api/vat/status"


def _is_prod() -> bool:
    return settings.ENVIRONMENT == "production"


# ---------------------------------------------------------------------------
# M-Pesa (Daraja sandbox)
# ---------------------------------------------------------------------------

async def _get_mpesa_token(caller: Any) -> str | None:
    """Exchange consumer key + secret for a Bearer token via Basic auth."""
    if not settings.MPESA_CONSUMER_KEY or not settings.MPESA_CONSUMER_SECRET:
        return None

    import base64

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


# Max recent callback transactions surfaced to downstream agents per session.
_MPESA_FEED_LIMIT = 20


async def _fetch_mpesa_ledger() -> dict[str, Any] | None:
    """Pull the real M-Pesa transaction feed ingested via the C2B/STK callback.

    These rows are written by ``POST /api/v1/finance/mpesa/callback`` from live
    Daraja callbacks, so they are the authoritative transaction history —
    preferred over the sandbox AccountBalance probe (S6-3). Returns a ``live``
    payload when the ledger has rows, else ``None`` so the caller falls back to
    the balance probe. A DB error also returns ``None`` (never fabricates data).
    """
    sql = text(
        """
        SELECT trans_id, amount, phone, bill_ref, created_at
        FROM mpesa_transactions
        ORDER BY created_at DESC
        LIMIT :lim
        """
    )
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql, {"lim": _MPESA_FEED_LIMIT})
            rows = result.fetchall()
    except Exception as exc:
        logger.warning("integrator_service: M-Pesa ledger query failed", error=str(exc))
        return None

    if not rows:
        return None

    txns = [
        {
            "trans_id": r[0],
            "amount_kes": float(r[1]),
            "phone": r[2],
            "bill_ref": r[3],
            "timestamp": r[4].isoformat() if r[4] is not None else None,
        }
        for r in rows
    ]
    total = round(sum(t["amount_kes"] for t in txns), 2)
    return {
        "status": LIVE,
        "source": "mpesa",
        "feed": "callback",
        "recent_transactions": txns,
        "recent_credit_kes": total,
        "transaction_count": len(txns),
    }


async def _fetch_mpesa_data(caller: Any) -> dict[str, Any]:
    """Return the real callback transaction feed, else probe the sandbox balance.

    Precedence: the ingested C2B/STK callback ledger (real data) wins; only when
    it is empty/unavailable do we fall back to the sandbox AccountBalance probe
    (dev mock / prod ``unavailable``).
    """
    ledger = await _fetch_mpesa_ledger()
    if ledger is not None:
        return ledger

    token = await _get_mpesa_token(caller)
    if not token:
        logger.warning("integrator_service: M-Pesa credentials not configured")
        return _mpesa_degraded()

    result = await caller.ainvoke({
        "method": "POST",
        "url": _MPESA_BALANCE_URL,
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
        return {"status": LIVE, "source": "mpesa", "raw": result["data"]}

    logger.warning("integrator_service: M-Pesa API non-200", status_code=result["status_code"])
    return _mpesa_degraded()


def _mpesa_degraded() -> dict[str, Any]:
    """Prod: unavailable (honest). Dev: flagged mock so local flows still run."""
    if _is_prod():
        return {"status": UNAVAILABLE, "source": "mpesa", "reason": "M-Pesa not configured"}
    return {
        "status": MOCK,
        "source": "mpesa",
        "balance_kes": 125_000.00,
        "recent_transactions": [
            {"type": "credit", "amount": 45_000.00, "ref": "NLJ7RT61SV"},
            {"type": "debit", "amount": 12_500.00, "ref": "PLK8RT71AS"},
        ],
    }


# ---------------------------------------------------------------------------
# FX rates (free keyless provider; USD-based → *_KES cross-rates)
# ---------------------------------------------------------------------------

async def _fetch_fx(caller: Any) -> dict[str, Any]:
    """Fetch live USD-based rates and derive KES cross-rates.

    Expects a provider returning ``{"rates": {"KES": .., "EUR": .., "GBP": ..}}``
    with USD as the base (e.g. open.er-api.com). KES per 1 USD comes straight from
    ``rates["KES"]``; EUR/GBP→KES are computed as ``rates["KES"] / rates[sym]``.
    """
    if not settings.FX_API_URL:
        return _fx_degraded()

    result = await caller.ainvoke({"method": "GET", "url": settings.FX_API_URL})
    data = result.get("data")
    if result["status_code"] == 200 and isinstance(data, dict):
        rates = data.get("rates") or {}
        kes = rates.get("KES")
        if kes:
            out: dict[str, Any] = {"status": LIVE, "source": "fx", "USD_KES": round(float(kes), 4)}
            for sym, key in (("EUR", "EUR_KES"), ("GBP", "GBP_KES")):
                rate = rates.get(sym)
                if rate:
                    out[key] = round(float(kes) / float(rate), 4)
            return out

    logger.warning(
        "integrator_service: FX provider unavailable", status_code=result.get("status_code")
    )
    return _fx_degraded()


def _fx_degraded() -> dict[str, Any]:
    if _is_prod():
        return {"status": UNAVAILABLE, "source": "fx", "reason": "FX provider unreachable"}
    return {
        "status": MOCK,
        "source": "fx",
        "USD_KES": 129.50,
        "EUR_KES": 140.20,
        "GBP_KES": 164.80,
    }


# ---------------------------------------------------------------------------
# Metropol credit score — deferred; manual entry or unavailable (never faked)
# ---------------------------------------------------------------------------

async def _fetch_metropol_score(
    caller: Any, customer_id: str, manual: dict[str, Any] | None = None
) -> dict[str, Any]:
    if manual:
        return {"status": MANUAL, "source": "metropol", **manual}

    if not settings.METROPOL_API_KEY or not customer_id:
        return {
            "status": UNAVAILABLE,
            "source": "metropol",
            "reason": "Metropol not connected — supply context['manual_credit_score'] to override",
        }

    result = await caller.ainvoke({
        "method": "POST",
        "url": _METROPOL_SCORE_URL,
        "headers": {"Authorization": f"Bearer {settings.METROPOL_API_KEY}"},
        "body": {"customer_id": customer_id},
    })

    if result["status_code"] == 200 and isinstance(result["data"], dict):
        return {
            "status": LIVE,
            "source": "metropol",
            "score": int(result["data"].get("score", 0)),
            "grade": result["data"].get("grade", "N/A"),
            "delinquencies": result["data"].get("delinquencies", 0),
        }

    logger.warning("integrator_service: Metropol API non-200", status_code=result["status_code"])
    return {"status": UNAVAILABLE, "source": "metropol", "reason": "Metropol API unreachable"}


# ---------------------------------------------------------------------------
# KRA VAT/compliance — deferred; manual entry or unavailable (never faked)
# ---------------------------------------------------------------------------

async def _fetch_kra_status(
    caller: Any, pin_number: str, manual: dict[str, Any] | None = None
) -> dict[str, Any]:
    if manual:
        return {"status": MANUAL, "source": "kra", "pin": pin_number or manual.get("pin"), **manual}

    if not settings.KRA_ECITIZEN_API_KEY or not pin_number:
        return {
            "status": UNAVAILABLE,
            "source": "kra",
            "reason": "KRA not connected — supply context['manual_kra_status'] to override",
        }

    result = await caller.ainvoke({
        "method": "GET",
        "url": _KRA_STATUS_URL,
        "headers": {"X-API-Key": settings.KRA_ECITIZEN_API_KEY},
        "params": {"pin": pin_number},
    })

    if result["status_code"] == 200 and isinstance(result["data"], dict):
        data = result["data"]
        return {
            "status": LIVE,
            "source": "kra",
            "pin": pin_number,
            "vat_registered": data.get("vat_registered", False),
            "last_return_filed": data.get("last_return_filed"),
            "compliance_status": data.get("compliance_status", "UNKNOWN"),
        }

    logger.warning("integrator_service: KRA API non-200", status_code=result["status_code"])
    return {"status": UNAVAILABLE, "source": "kra", "reason": "KRA API unreachable"}


# ---------------------------------------------------------------------------
# Amount normaliser
# ---------------------------------------------------------------------------

def _normalise_to_kes(amount: float, currency: str, fx: dict[str, Any]) -> float:
    """Convert an amount to KES using the supplied FX rate map.

    Returns the amount unchanged when it is already KES or when no rate is
    available (e.g. FX is ``unavailable``) — never guesses.
    """
    key = f"{currency.upper()}_KES"
    rate = fx.get(key)
    if currency.upper() == "KES" or not isinstance(rate, (int, float)):
        return amount
    return round(amount * float(rate), 2)


# ---------------------------------------------------------------------------
# Orchestration — the node's single entry point
# ---------------------------------------------------------------------------

async def fetch_external_data(
    *,
    customer_id: str,
    kra_pin: str,
    manual_credit: dict[str, Any] | None,
    manual_kra: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fetch and assemble all four sources into the ``external_data`` payload.

    Each source is isolated — one failing never aborts the others — matching
    the module's honesty model (an exception degrades that source to
    ``unavailable``/``mock``, it never propagates and never fabricates data).
    """
    caller = make_http_caller(agent_id="I", timeout=20.0)

    # ── 1. FX rates (first — needed for normalisation) ────────────────────
    try:
        fx_rates = await _fetch_fx(caller)
    except Exception as exc:
        logger.error("integrator_service: FX fetch failed", error=str(exc))
        fx_rates = _fx_degraded()

    # ── 2. M-Pesa balance ─────────────────────────────────────────────────
    try:
        mpesa_data = await _fetch_mpesa_data(caller)
        if "balance_kes" in mpesa_data:
            mpesa_data["balance_kes"] = _normalise_to_kes(
                float(mpesa_data["balance_kes"]), "KES", fx_rates
            )
    except Exception as exc:
        logger.error("integrator_service: M-Pesa fetch failed", error=str(exc))
        mpesa_data = _mpesa_degraded()

    # ── 3. Metropol credit score (manual / live / unavailable) ────────────
    try:
        credit_data = await _fetch_metropol_score(caller, customer_id, manual_credit)
    except Exception as exc:
        logger.error("integrator_service: Metropol fetch failed", error=str(exc))
        credit_data = {"status": UNAVAILABLE, "source": "metropol", "reason": "fetch error"}

    # ── 4. KRA VAT status (manual / live / unavailable) ───────────────────
    try:
        kra_data = await _fetch_kra_status(caller, kra_pin, manual_kra)
    except Exception as exc:
        logger.error("integrator_service: KRA fetch failed", error=str(exc))
        kra_data = {"status": UNAVAILABLE, "source": "kra", "reason": "fetch error"}

    sources_status = {
        "fx_rates": fx_rates["status"],
        "mpesa": mpesa_data["status"],
        "credit_bureau": credit_data["status"],
        "kra_status": kra_data["status"],
    }
    simulated = any(s == MOCK for s in sources_status.values())
    degraded = any(s in (MOCK, UNAVAILABLE) for s in sources_status.values())

    return {
        "fx_rates": fx_rates,
        "mpesa": mpesa_data,
        "credit_bureau": credit_data,
        "kra_status": kra_data,
        "sources_status": sources_status,
        "simulated": simulated,
        # Back-compat top-level flag: "live" only when every source is real.
        "data_source": (
            "live" if not degraded else ("mock_sandbox" if simulated else "degraded")
        ),
    }
