# Finguard 3.0 — Security & Code Weakness Report

**Date:** 2026-06-12
**Scope:** Backend (FastAPI / Python), Frontend (Next.js 15), infrastructure config
**Reviewer:** Automated code audit
**Method:** Static review of authentication, authorization, the AI/agent layer, data access, and configuration. No dynamic testing was performed; severity reflects code-path analysis.

---

## Executive Summary

Finguard 3.0 is a well-engineered multi-agent finance platform with several genuinely strong security controls: deterministic SQL AST validation for Text-to-SQL, JTI-based access-token revocation, HMAC-verified M-Pesa callbacks, idempotency keys on state-changing AI endpoints, bcrypt password hashing, and structured exception handling that does not leak stack traces.

However, the **authorization layer is effectively absent**. The data model defines five roles, but no endpoint enforces them, and self-registration is open. The practical result: anyone on the internet can create an account and immediately read and modify all financial data — invoices, ledger entries, payments, budgets, and customers. This single class of issue (broken access control) dominates the risk profile and should be treated as a release blocker.

The findings below are ordered by severity.

| # | Severity | Finding |
|---|----------|---------|
| 1 | **Critical** | No role-based access control — every authenticated user has full write access |
| 2 | **Critical** | Open self-registration grants immediate access to financial data |
| 3 | **High** | No object/tenant isolation — IDOR across all financial resources |
| 4 | **High** | Account lockout configured but never implemented (brute-force exposure) |
| 5 | **High** | Refresh tokens cannot be revoked; survive logout for 7 days |
| 6 | **Medium** | Access & refresh tokens stored in `localStorage` (XSS-exfiltratable) |
| 7 | **Medium** | Text-to-SQL can read all financial tables; read-only DB role is optional |
| 8 | **Medium** | SSRF-capable HTTP tool with no URL allowlist |
| 9 | **Medium** | IDOR on conversation status endpoint |
| 10 | **Low** | No security scanning in CI; thin test coverage of auth |
| 11 | **Low** | No `SECRET_KEY` strength/placeholder validation at startup |
| 12 | **Low** | Schema managed by both `create_all` and Alembic |
| 13 | **Low** | Account enumeration via registration & login responses |
| 14 | **Info** | Transitive `ecdsa` timing CVE (not exploitable with HS256) |

---

## 1. No Role-Based Access Control (Critical)

**Where:** `backend/src/domains/finance/router.py`, `crm/router.py`, `intelligence/router.py`

The `User` model defines a full role hierarchy:

```python
# src/domains/identity/models.py
class UserRole(enum.StrEnum):
    OWNER = "owner"; ADMIN = "admin"; MANAGER = "manager"
    ACCOUNTANT = "accountant"; VIEWER = "viewer"
```

But **no route ever checks the role.** Every protected endpoint depends only on `CurrentUser` / `get_current_user`, which proves *authentication* but never *authorization*:

```python
# finance/router.py — the parameter is named `_` because the identity is discarded
@router.post("/ledger", status_code=201)
async def post_ledger_entry(data: LedgerEntryCreate, db: DBSession, _: CurrentUser): ...

@router.post("/payments/cash", status_code=201)
async def record_cash_payment(data: PaymentCreate, db: DBSession, current_user: CurrentUser): ...
```

A repository-wide search for `require_role`, `require_permission`, `is_admin`, `.role ==`, etc. returns **zero enforcement points** in the HTTP layer. The only place roles are consulted at all is `agents/h_advisor.py`, where the role merely tunes how verbose an AI answer is — not whether an action is allowed.

**Impact:** A user with the lowest role (`viewer`, which is also the registration default — see #2) can:
- Post arbitrary ledger entries (`POST /finance/ledger`)
- Create, edit, and mark invoices paid (`POST/PATCH /finance/invoices`, `/pay`)
- Record cash payments (`POST /finance/payments/cash`)
- Create budgets, create/modify customers
- Invoke the AI **actions** orchestrator (`POST /intelligence/ai-actions`), which is documented as able to trigger M-Pesa payments and invoice generation

This is OWASP A01:2021 (Broken Access Control), the highest-impact class of web vulnerability.

**Fix:** Introduce an authorization dependency (e.g. `require_role(*allowed)` / a permission matrix) and apply it to every state-changing route. Default to deny. Treat `viewer` as read-only and gate writes behind `accountant`+.

---

## 2. Open Self-Registration into Financial Data (Critical)

**Where:** `identity/router.py` (`POST /register`), `identity/service.py`, `identity/models.py`

```python
@router.post("/register", status_code=201)
async def register(data: UserCreate, db: DBSession):
    user = await IdentityService(db).register(data)
```

Registration is unauthenticated and creates an immediately-active account:

- `is_active` defaults to `True` (`models.py`) — the account works right away.
- `is_verified` defaults to `False` but is **never enforced** anywhere; login only checks `is_active`.
- No email-confirmation, invite, or admin-approval step exists.
- There is no organization/tenant binding — every new user lands in the same global data set.

Combined with finding #1 (no RBAC), **any anonymous visitor can register and instantly read and write the company's books.** For a financial system this is a complete authorization bypass.

**Fix:** Gate registration behind an invite/admin flow, or require email verification before `is_active` is granted. Bind users to a tenant. Enforce `is_verified` in `login`.

---

## 3. No Object / Tenant Isolation — IDOR (High)

**Where:** `crm/router.py`, `finance/router.py`, `finance/service.py`

Resources are global and unscoped to any owner or tenant:

```python
@router.get("/customers/{customer_id}")     # any user → any customer
@router.patch("/customers/{customer_id}")    # any user → edit any customer
@router.get("/invoices/{invoice_id}")        # any user → any invoice
@router.get("/expenses")                     # lists ALL expenses
```

`list_invoices` with no `customer_id` selects every invoice in the database; `list_expenses` and `list_budgets` likewise return everything. There is no `WHERE owner_id = current_user` or tenant filter anywhere in the service layer.

**Impact:** Insecure Direct Object Reference. Even if multi-user roles existed, one tenant could enumerate and modify another tenant's customers and financial records.

**Fix:** Add tenant/ownership columns and scope every query to the authenticated principal's tenant. Enforce object-level checks in the service layer (not just the router).

---

## 4. Account Lockout Configured but Not Implemented (High)

**Where:** `core/config.py`, `identity/service.py`

Settings advertise a lockout policy:

```python
MAX_LOGIN_ATTEMPTS: int = 5
LOCKOUT_DURATION_MINUTES: int = 30
```

…but `IdentityService.login` contains **no failed-attempt tracking, counter, or lockout** — it simply verifies the password and returns tokens. A grep for `attempt|lockout|locked|failed_login` in the identity domain returns nothing.

The only throttle is an IP-based SlowAPI limit on the login route:

```python
limiter = Limiter(key_func=get_remote_address, ...)
@limiter.limit("5/minute")
```

This is per-IP and uses `get_remote_address` (the socket peer). Behind the Nginx reverse proxy, unless `ProxyHeaders`/`ForwardedAllowIps` is correctly configured this throttles by the *proxy* IP (one shared bucket), and from the attacker side it is trivially bypassed by rotating source IPs. It provides no per-account protection.

**Impact:** Online password brute-force / credential stuffing against any known email.

**Fix:** Implement the advertised lockout (Redis counter keyed by account, with the configured threshold and cooldown), independent of the IP rate limit.

---

## 5. Refresh Tokens Are Unrevocable and Survive Logout (High)

**Where:** `core/security.py`, `identity/router.py` (`/logout`), `identity/service.py` (`/refresh`)

Access tokens carry a `jti` and are revoked on logout by blacklisting the JTI in Redis. **Refresh tokens do not:**

```python
def create_refresh_token(subject):
    payload = {"sub": str(subject), "exp": ..., "type": "refresh"}  # no jti
```

The `/logout` handler only blacklists the access token's JTI. The refresh token has no JTI, is never blacklisted, and has no reuse-detection or rotation-invalidation. It remains valid for the full `REFRESH_TOKEN_EXPIRE_DAYS = 7` and can mint fresh access tokens via `/token/refresh` even after the user "logs out."

**Impact:** A stolen refresh token (see #6) gives an attacker up to 7 days of access that the user cannot terminate. Logout provides a false sense of security.

**Fix:** Add a `jti` to refresh tokens and blacklist it on logout; implement refresh-token rotation with reuse detection (invalidate the family on replay).

---

## 6. Tokens Stored in `localStorage` (Medium)

**Where:** `frontend/src/lib/auth/token-manager.ts`

```typescript
localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
document.cookie = "fg_session=1; path=/; SameSite=Lax; max-age=86400"; // non-HttpOnly
```

Both the access token **and the long-lived refresh token** live in `localStorage`, which is readable by any JavaScript in the page. A single XSS flaw (or a compromised npm dependency) exfiltrates the 7-day refresh token — which, per #5, cannot be revoked. The `fg_session` cookie is also non-HttpOnly.

**Impact:** XSS escalates from session theft to a durable, unrevocable account takeover.

**Fix:** Store the refresh token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie; keep the access token in memory only. Pair with a strong Content-Security-Policy.

---

## 7. Text-to-SQL Reach & Optional Read-Only Role (Medium)

**Where:** `intelligence/tools/sql_executor.py`, `infrastructure/database/postgres.py`, `agents/d_forecaster.py`, `agents/e_watchdog.py`

The Text-to-SQL guardrails are, to their credit, strong: a regex pre-filter, full `sqlglot` AST validation rejecting non-`SELECT` roots and any DML/DDL node, multi-statement rejection, schema masking (the `users`, `knowledge_base`, `outbox_events` tables are hidden from Agent D), and a `LIMIT` clamp to 100 rows. Three weaknesses remain:

1. **Read-only DB role is optional and silently downgraded.** If `DATABASE_READONLY_URL` is unset, `execute_readonly_sql` and the engine factory **fall back to the fully-privileged main engine** and only emit a `warning` log:
   ```python
   _readonly_url = settings.DATABASE_READONLY_URL or settings.DATABASE_URL
   ```
   The defence-in-depth boundary depends on an operator remembering an env var; a misconfigured deploy runs LLM-generated SQL with full write privileges, with only string-level validation between the model and the database.

2. **`make_sql_executor` (used by `e_watchdog`) binds the read-write request session**, not the read-only engine — so that path never benefits from the role boundary at all.

3. **No row-level scoping.** Generated queries can read *all* rows of `ledger_entries`, `invoices`, `budgets`, `expenses`. Combined with #1/#2, a `viewer` can use the AI to exfiltrate the entire financial dataset in natural language.

**Fix:** Make `DATABASE_READONLY_URL` mandatory (fail closed at startup, don't warn-and-continue). Route `e_watchdog` through the read-only engine. Inject a tenant/row filter into generated SQL or run it under a role with row-level security.

---

## 8. SSRF-Capable HTTP Tool With No Allowlist (Medium)

**Where:** `intelligence/tools/http_caller.py`

`make_http_caller` builds a LangChain `@tool` that issues outbound requests to an **arbitrary `url`** with `follow_redirects=True` and no host/scheme allowlist or private-IP guard:

```python
async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
    response = await _send_with_retry(client, method, url, ...)
```

Today it is only invoked from `i_integrator.py` with fixed external endpoints, so it is not *currently* attacker-reachable. But it is a generic, exposed tool with no SSRF protection: if it is ever bound to an LLM with tool-calling (the obvious next step for an "agent"), a prompt-injection payload could drive it to `http://169.254.169.254/…` (cloud metadata), internal services, or redirect-based bypasses.

**Fix:** Add an allowlist of permitted hosts/schemes, block link-local and private ranges, and disable or carefully constrain redirect following before this tool is ever LLM-driven.

---

## 9. IDOR on Conversation Status (Medium)

**Where:** `intelligence/router.py` — `GET /conversation/{session_id}/status`

The endpoint requires authentication but **does not verify the session belongs to the caller**:

```python
async def conversation_status(session_id: str, current_user: CurrentUser):
    raw = await redis_client.get(f"task_status:{session_id}")
    ... returns artifact_id, gen_ui_payloads, detail ...
```

Any authenticated user who learns or guesses another user's `session_id` receives that session's result, artifact IDs, and rendered payloads. The `session_id` is a random UUIDv4 (so not trivially enumerable), but the access check is missing — the control relies entirely on the secrecy of the identifier.

**Fix:** Store the owning `user_id` with the task status and verify it matches `current_user.id`.

---

## 10. No Security Scanning in CI; Thin Auth Test Coverage (Low)

**Where:** `.github/workflows/`, `backend/tests/`

- CI (`ci.yml`, `backend-architecture-ci.yml`, `deploy.yml`) runs no SAST, dependency audit, or secret scanning — no `bandit`, `pip-audit`/`safety`, `semgrep`, `npm audit`, or `gitleaks`/`trufflehog`.
- There are only 6 backend test files. Identity tests cover the happy path, duplicate registration, and invalid credentials — but **none of the security-critical behaviours**: no test for authorization/role enforcement, lockout, token revocation, or refresh-token reuse (largely because those behaviours don't exist — #1, #4, #5).

**Fix:** Add `pip-audit` + `bandit` + `npm audit` + secret scanning to CI as required gates. Add authz/lockout/revocation regression tests once those controls are implemented.

---

## 11. No `SECRET_KEY` Validation at Startup (Low)

**Where:** `core/config.py`, `backend/.env.example`

`SECRET_KEY` is a required setting but has no validator. Nothing rejects the shipped placeholder (`change-me-to-a-strong-random-secret-key`) or enforces a minimum length/entropy. Because the same `SECRET_KEY` signs user JWTs **and** the agent Verifiable Credentials (`vc_issuer.py`, HS256), a weak or leaked key forges both user sessions and the audit/trust-log credentials.

**Fix:** Add a Pydantic validator that rejects the placeholder and enforces ≥32 bytes of entropy in non-development environments. Consider separate keys for user auth vs. VC signing.

---

## 12. Schema Managed by Both `create_all` and Alembic (Low)

**Where:** `infrastructure/database/postgres.py`

```python
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

The app calls `create_all` on every startup while also shipping Alembic migrations (`alembic/versions/…`). `create_all` only creates missing tables — it never alters existing columns/constraints — so the two mechanisms can silently diverge, and a fresh `create_all` boot can produce a schema that doesn't match the migration history.

**Fix:** Pick one source of truth. Use Alembic for all environments and drop `create_all` (or restrict it to ephemeral test setup).

---

## 13. Account Enumeration (Low)

**Where:** `identity/service.py`

- `register` raises `409 "Email already registered"`, confirming which emails have accounts.
- `login` returns distinct messages: `"Invalid credentials"` vs `"Account disabled"` (the latter only after a correct password, which limits leakage but still distinguishes states).

**Fix:** Return a generic message on registration conflicts (or move to an email-verification flow), and keep login responses uniform.

---

## 14. Transitive `ecdsa` Timing CVE (Informational)

`python-jose` is correctly pinned to **3.5.0** in `uv.lock` (the JWT-bomb / algorithm-confusion CVEs from older releases are patched). However it pulls in `ecdsa==0.19.2`, which carries the unpatched Minerva timing side-channel (CVE-2024-23342). **Not exploitable here** because the application signs exclusively with HS256 (HMAC), but it will be flagged by `pip-audit`/`safety` and is worth suppressing explicitly or removing the ECDSA extra if unused.

---

## Strengths Worth Preserving

To keep this balanced, the following were done well and should not be regressed:

- **Deterministic SQL validation** via `sqlglot` AST (not just regex), with schema masking and `LIMIT` clamping.
- **Access-token revocation** via per-token `jti` + Redis blacklist.
- **M-Pesa callback authenticity** verified with HMAC-SHA256 and constant-time comparison (`hmac.compare_digest`).
- **Idempotency keys** (atomic Redis `SETNX`) on `ai-insights`/`ai-actions` to prevent duplicate payments.
- **bcrypt** password hashing via `passlib`.
- **Exception handler** returns clean `{"detail": ...}` payloads without leaking stack traces.
- **`/metrics`** behind a constant-time Bearer check, and **`/docs`** disabled unless `DEBUG`.
- Secrets correctly git-ignored; only `.env.example` files are tracked.

---

## Recommended Remediation Order

1. **Implement RBAC** on every state-changing route; default-deny (#1).
2. **Close self-registration** or require verification + tenant binding (#2).
3. **Add tenant/object scoping** to all financial queries (#3).
4. **Move refresh tokens to HttpOnly cookies** and make them revocable (#5, #6).
5. **Implement the configured account lockout** (#4).
6. **Make the read-only DB role mandatory**; scope Text-to-SQL by tenant (#7).
7. Add CI security gates and authz regression tests (#10).
8. Address the remaining medium/low items (#8, #9, #11–#14).

The first three items eliminate the dominant risk and should block any production or pilot deployment handling real financial data.
