"""
Refresh-token rotation, family revocation, and logout revocation.

Cookie-based flow (after HttpOnly migration):
  * /token sets fg_refresh_token (HttpOnly) + fg_csrf (non-HttpOnly) cookies.
  * /token/refresh reads the cookie; requires X-CSRF-Token header == fg_csrf.
  * Replaying a consumed token triggers family-wide revocation: every token in
    the chain (including already-rotated successors) is rejected.
  * /logout blacklists both the access and refresh tokens and clears cookies.

Service-layer tests for family revocation run through IdentityService directly
so they don't depend on httpx cookie-path behaviour.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.identity.schemas import UserCreate
from src.domains.identity.service import IdentityService

# ── Helpers ────────────────────────────────────────────────────────────────────

async def _register_and_login(client: AsyncClient, email: str) -> dict:
    """Register + login; return the JSON body (access_token only after migration)."""
    await client.post(
        "/api/v1/identity/register",
        json={"email": email, "password": "secure1234", "full_name": "Token User"},
    )
    res = await client.post(
        "/api/v1/identity/token",
        json={"email": email, "password": "secure1234"},
    )
    assert res.status_code == 200
    return res.json()


# ── Router-level cookie tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_sets_refresh_cookie_and_csrf(client: AsyncClient) -> None:
    email = f"cookie-{uuid.uuid4().hex[:8]}@finguard.io"
    await _register_and_login(client, email)

    assert client.cookies.get("fg_refresh_token"), "HttpOnly refresh cookie should be set"
    assert client.cookies.get("fg_csrf"), "CSRF cookie should be set"


@pytest.mark.asyncio
async def test_refresh_via_cookie_rotates_tokens(client: AsyncClient) -> None:
    email = f"rotate-{uuid.uuid4().hex[:8]}@finguard.io"
    await _register_and_login(client, email)
    original_refresh = client.cookies.get("fg_refresh_token")
    original_csrf = client.cookies.get("fg_csrf")
    assert original_refresh and original_csrf

    first = await client.post(
        "/api/v1/identity/token/refresh",
        headers={"X-CSRF-Token": original_csrf},
    )
    assert first.status_code == 200
    assert "access_token" in first.json()

    # Cookie should have rotated to a new value
    assert client.cookies.get("fg_refresh_token") != original_refresh
    # Body must NOT contain refresh_token (it's in the cookie)
    assert "refresh_token" not in first.json()


@pytest.mark.asyncio
async def test_refresh_rejected_without_csrf_header(client: AsyncClient) -> None:
    email = f"nocsrf-{uuid.uuid4().hex[:8]}@finguard.io"
    await _register_and_login(client, email)

    # Omit the X-CSRF-Token header
    res = await client.post("/api/v1/identity/token/refresh")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_refresh_rejected_with_wrong_csrf_header(client: AsyncClient) -> None:
    email = f"badcsrf-{uuid.uuid4().hex[:8]}@finguard.io"
    await _register_and_login(client, email)

    res = await client.post(
        "/api/v1/identity/token/refresh",
        headers={"X-CSRF-Token": "definitely-not-the-real-token"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_logout_clears_cookies_and_blacklists_tokens(client: AsyncClient) -> None:
    email = f"logout-{uuid.uuid4().hex[:8]}@finguard.io"
    body = await _register_and_login(client, email)
    access_token = body["access_token"]

    # Capture cookies before logout so we can test the refresh token is blacklisted
    saved_refresh = client.cookies.get("fg_refresh_token")
    saved_csrf = client.cookies.get("fg_csrf")
    assert saved_refresh and saved_csrf

    out = await client.post(
        "/api/v1/identity/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert out.status_code == 204

    # Cookies should be cleared (backend sent empty Set-Cookie with expired date)
    assert not client.cookies.get("fg_refresh_token")

    # Blacklisted refresh token is rejected even if we replay it manually
    client.cookies.set("fg_refresh_token", saved_refresh)
    client.cookies.set("fg_csrf", saved_csrf)
    res = await client.post(
        "/api/v1/identity/token/refresh",
        headers={"X-CSRF-Token": saved_csrf},
    )
    assert res.status_code == 401


# ── Service-level family revocation tests ─────────────────────────────────────
#
# These bypass the router so they are not affected by cookie/path handling in
# httpx and can assert directly on the service's revocation behaviour.

@pytest_asyncio.fixture
async def svc(db_session: AsyncSession) -> IdentityService:
    return IdentityService(db_session)


async def _create_user(svc: IdentityService, email: str) -> None:
    await svc.register(UserCreate(email=email, password="secure1234", full_name="Fam User"))


@pytest.mark.asyncio
async def test_family_revocation_on_replay(svc: IdentityService) -> None:
    """Replaying a consumed token revokes the entire family chain."""
    from src.core.exceptions import UnauthorizedError

    email = f"family-{uuid.uuid4().hex[:8]}@finguard.io"
    await _create_user(svc, email)
    t1_resp = await svc.login(email, "secure1234")
    t1 = t1_resp.refresh_token

    # Normal rotation: T1 → T2
    t2_resp = await svc.refresh(t1)
    t2 = t2_resp.refresh_token

    # Replay T1 → should trigger family revocation and be rejected
    with pytest.raises(UnauthorizedError):
        await svc.refresh(t1)

    # T2 (the legitimately issued successor) is now also dead — family was revoked
    with pytest.raises(UnauthorizedError):
        await svc.refresh(t2)


@pytest.mark.asyncio
async def test_single_blacklist_on_normal_rotation(svc: IdentityService) -> None:
    """Without replay, the rotated token remains valid for further rotations."""
    email = f"chain-{uuid.uuid4().hex[:8]}@finguard.io"
    await _create_user(svc, email)
    t1_resp = await svc.login(email, "secure1234")

    t2_resp = await svc.refresh(t1_resp.refresh_token)
    t3_resp = await svc.refresh(t2_resp.refresh_token)
    t4_resp = await svc.refresh(t3_resp.refresh_token)

    # All three rotations succeeded; the chain carries the same family_id
    from src.core.security import decode_token
    t1_fid = decode_token(t1_resp.refresh_token)["family_id"]
    t4_fid = decode_token(t4_resp.refresh_token)["family_id"]
    assert t1_fid == t4_fid, "family_id should be inherited across the whole chain"


@pytest.mark.asyncio
async def test_fresh_login_starts_new_family(svc: IdentityService) -> None:
    """Each login generates a distinct family_id."""
    from src.core.security import decode_token

    email = f"twofam-{uuid.uuid4().hex[:8]}@finguard.io"
    await _create_user(svc, email)

    session_a = await svc.login(email, "secure1234")
    session_b = await svc.login(email, "secure1234")

    fid_a = decode_token(session_a.refresh_token)["family_id"]
    fid_b = decode_token(session_b.refresh_token)["family_id"]
    assert fid_a != fid_b, "Two separate logins must not share a family_id"
