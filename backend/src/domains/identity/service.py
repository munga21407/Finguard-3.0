import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)
from src.core.security import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_refresh_token,
    decode_email_verification_token,
    decode_password_reset_token,
    decode_token,
    hash_password,
    token_issued_after_password_change,
    verify_password,
)
from src.domains.identity.models import User, UserRole
from src.domains.identity.repository import UserRepository
from src.domains.identity.schemas import TokenResponse, UserCreate, UserUpdate
from src.domains.notifications.models import EmailCategory
from src.domains.notifications.service import NotificationService
from src.infrastructure.cache.redis import get_auth_redis

# A fixed, valid bcrypt hash verified against on the "email not found" path so a
# login attempt for a non-existent account costs the same wall-clock time as one
# for a real account.  Without it, the missing-user branch short-circuits before
# bcrypt runs, turning response latency into an account-enumeration oracle.
_DUMMY_PASSWORD_HASH = hash_password("finguard-timing-equalizer-not-a-real-password")


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)
        self._session = session

    async def register(self, data: UserCreate) -> User:
        if await self._repo.get_by_email(data.email):
            raise ConflictError("Email already registered")

        # Bootstrap: the first account can claim a verified OWNER role, but only
        # by presenting the configured INITIAL_BOOTSTRAP_KEY — without it the
        # unrestricted "first to register owns the system" hijack is gone. Every
        # other self-registration is an UNVERIFIED VIEWER that cannot log in until
        # an administrator verifies it.
        is_first_user = (await self._repo.count()) == 0
        claim_owner = self._claims_owner(data.bootstrap_key, is_first_user)
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.OWNER if claim_owner else UserRole.VIEWER,
            is_verified=claim_owner,
            # The bootstrap owner is trusted (held the bootstrap key), so their
            # email is auto-verified; everyone else must confirm via the link.
            email_verified_at=datetime.now(UTC) if claim_owner else None,
        )
        user = await self._repo.create(user)
        # Enqueue in the same transaction as the account row (atomic; the flush
        # worker delivers). The bootstrap owner gets a welcome; every other
        # registrant gets a verification email with the confirm link.
        notifier = NotificationService(self._session)
        if claim_owner:
            await notifier.enqueue_email(
                to_email=user.email,
                to_name=user.full_name,
                subject="Welcome to Finguard",
                template="welcome",
                context={"full_name": user.full_name, "is_verified": True},
                idempotency_key=f"welcome:{user.id}",
            )
        else:
            await self._enqueue_verification_email(notifier, user)
        await self._session.commit()
        return user

    async def _enqueue_verification_email(
        self, notifier: NotificationService, user: User
    ) -> None:
        token = create_email_verification_token(str(user.id))
        verify_url = f"{settings.APP_BASE_URL}/verify-email?token={token}"
        await notifier.enqueue_email(
            to_email=user.email,
            to_name=user.full_name,
            subject="Verify your Finguard email",
            template="verify_email",
            context={
                "full_name": user.full_name,
                "verify_url": verify_url,
                "expires_hours": settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
            },
            # Fresh key per send so a resend re-delivers; the endpoint rate-limits.
            idempotency_key=f"verify:{uuid.uuid4()}",
        )

    @staticmethod
    def _claims_owner(bootstrap_key: str | None, is_first_user: bool) -> bool:
        """Decide whether a registration may bootstrap the OWNER role.

        With ``INITIAL_BOOTSTRAP_KEY`` configured (always in production), the
        first account must present the matching key — a wrong key, or any attempt
        once the owner exists, is rejected outright. With no key configured
        (local dev / CI), the first account bootstraps unconditionally so the
        suite and developer setup stay frictionless.
        """
        configured = settings.INITIAL_BOOTSTRAP_KEY
        if not configured:
            return is_first_user
        if not bootstrap_key:
            return False
        # Constant-time compare so a wrong key can't be discovered by timing.
        if not hmac.compare_digest(bootstrap_key, configured):
            raise ForbiddenError("Invalid bootstrap key")
        if not is_first_user:
            raise ForbiddenError("The owner account has already been claimed")
        return True

    async def login(
        self, email: str, password: str, ip: str | None = None
    ) -> TokenResponse:
        redis = get_auth_redis()
        # Lockout is keyed per (email, source IP) rather than per email alone.
        # An email-only key let any anonymous attacker lock a victim out of their
        # account by submitting bad passwords (a targeted denial of service). The
        # IP component confines a lockout to the offending client, while the
        # per-endpoint rate limit (5/min/IP) remains the brute-force backstop.
        attempts_key = f"login_attempts:{email.lower()}:{ip or 'unknown'}"

        # Account lockout: reject before verifying the password once the failure
        # threshold is hit, so brute-force / credential-stuffing stops cold.
        attempts = int(await redis.get(attempts_key) or 0)
        if attempts >= settings.MAX_LOGIN_ATTEMPTS:
            raise TooManyRequestsError(
                "Account temporarily locked after too many failed login attempts. "
                f"Try again in {settings.LOCKOUT_DURATION_MINUTES} minutes."
            )

        user = await self._repo.get_by_email(email)
        # Always run bcrypt — against the user's hash, or a dummy hash when the
        # email is unknown — so timing does not reveal whether the account exists.
        password_ok = verify_password(
            password, user.hashed_password if user else _DUMMY_PASSWORD_HASH
        )
        if not user or not password_ok:
            await redis.incr(attempts_key)
            # Sliding window: each failed attempt extends the lock so a
            # persistent attacker stays locked out.
            await redis.expire(attempts_key, settings.LOCKOUT_DURATION_MINUTES * 60)
            raise UnauthorizedError("Invalid credentials")
        if not user.is_active:
            raise UnauthorizedError("Account disabled")
        # Two independent gates. Check email ownership first — it's self-actionable
        # (the user can fix it from their inbox); admin approval is not.
        if user.email_verified_at is None:
            raise ForbiddenError(
                "Please verify your email — check your inbox for the confirmation link."
            )
        if not user.is_verified:
            raise ForbiddenError("Account is pending verification by an administrator")

        await redis.delete(attempts_key)  # successful login clears the counter
        return TokenResponse(
            access_token=create_access_token(str(user.id), {"role": user.role}),
            refresh_token=create_refresh_token(str(user.id)),
        )

    # ── User administration (USER_MANAGE) ──────────────────────────────────────

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[User]:
        return await self._repo.list_all(limit=limit, offset=offset)

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self._repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")
        return user

    async def update_user(self, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self.get_user(user_id)
        was_verified = user.is_verified
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(user, field, value)
        user = await self._repo.save(user)
        # Email the user only on the actual verification transition (false → true),
        # not on every profile edit. Idempotency-keyed so re-verifying is a no-op.
        if not was_verified and user.is_verified:
            await NotificationService(self._session).enqueue_email(
                to_email=user.email,
                to_name=user.full_name,
                subject="Your Finguard account is ready",
                template="account_approved",
                context={"full_name": user.full_name},
                idempotency_key=f"approved:{user.id}",
            )
        await self._session.commit()
        return user

    async def verify_email(self, token: str) -> None:
        """Confirm email ownership from a valid verification token.

        Idempotent: verifying an already-verified account is a no-op (a
        double-click doesn't error). Admin approval remains a separate gate.
        """
        user_id = decode_email_verification_token(token)
        user = await self._repo.get_by_id(uuid.UUID(user_id))
        if not user or not user.is_active:
            raise UnauthorizedError("Invalid or expired verification link")
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
            await self._repo.save(user)
            await self._session.commit()

    async def resend_verification(self, email: str) -> None:
        """Re-send the verification email if the account exists and is unverified.

        Always returns None (no account enumeration); an unknown, inactive, or
        already-verified email simply sends nothing.
        """
        user = await self._repo.get_by_email(email)
        if not user or not user.is_active or user.email_verified_at is not None:
            return
        await self._enqueue_verification_email(NotificationService(self._session), user)
        await self._session.commit()

    async def request_password_reset(self, email: str) -> None:
        """Email a reset link if the account exists — always returns None.

        Deliberately reveals nothing about whether the address is registered (no
        account enumeration): the caller gets the same response either way, and an
        unknown or inactive email simply enqueues no mail.
        """
        user = await self._repo.get_by_email(email)
        if not user or not user.is_active:
            return
        token = create_password_reset_token(str(user.id))
        reset_url = f"{settings.APP_BASE_URL}/reset-password?token={token}"
        await NotificationService(self._session).enqueue_email(
            to_email=user.email,
            to_name=user.full_name,
            subject="Reset your Finguard password",
            template="password_reset",
            context={
                "full_name": user.full_name,
                "reset_url": reset_url,
                "expires_minutes": settings.PASSWORD_RESET_EXPIRE_MINUTES,
            },
            # Fresh key per request so a legitimate re-request re-sends; the
            # endpoint's rate limit is what bounds abuse.
            idempotency_key=f"pwreset:{uuid.uuid4()}",
            category=EmailCategory.ACCOUNT,
        )
        await self._session.commit()

    async def reset_password(self, token: str, new_password: str) -> None:
        """Set a new password from a valid reset token and end existing sessions.

        The reset link is one-time-use (its jti is blacklisted after success), and
        stamping ``password_changed_at`` invalidates every access/refresh token
        issued before now (see ``token_issued_after_password_change``), so a reset
        prompted by compromise also evicts the attacker.
        """
        payload = decode_password_reset_token(token)
        jti: str | None = payload.get("jti")
        redis = get_auth_redis()
        if jti is not None and await redis.exists(f"blacklist:{jti}"):
            raise UnauthorizedError("This reset link has already been used")

        user = await self._repo.get_by_id(uuid.UUID(str(payload["sub"])))
        if not user or not user.is_active:
            raise UnauthorizedError("Invalid or expired reset link")
        user.hashed_password = hash_password(new_password)
        user.password_changed_at = datetime.now(UTC)
        await self._repo.save(user)
        await self._session.commit()
        # Consume the link: a second use is rejected above.
        if jti is not None:
            await self._blacklist_jti(redis, jti, payload.get("exp"))

    async def refresh(self, refresh_token: str) -> TokenResponse:
        redis = get_auth_redis()
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid token type")

        jti: str | None = payload.get("jti")
        family_id: str | None = payload.get("family_id")

        # Family-level revocation check: a previous reuse in this chain has
        # already invalidated every token that shares the same family_id.
        if family_id and await redis.exists(f"revoked_family:{family_id}"):
            raise UnauthorizedError("Session has been invalidated due to suspicious activity")

        # Reuse detection: once a refresh token is rotated its jti is
        # blacklisted.  A second presentation of the same jti means a consumed
        # token is being replayed — a strong indicator of theft.  Revoke the
        # entire family so even the legitimately issued successor is dead.
        if jti is not None and await redis.exists(f"blacklist:{jti}"):
            if family_id:
                await self._revoke_family(redis, family_id)
            raise UnauthorizedError("Refresh token has been revoked — session invalidated")

        user = await self._repo.get_by_id(uuid.UUID(str(payload["sub"])))
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or disabled")

        # A refresh token minted before the user's last password reset is dead —
        # so a reset kills even a stolen 7-day refresh token.
        if not token_issued_after_password_change(
            payload.get("iat"), user.password_changed_at
        ):
            raise UnauthorizedError("Session ended — please sign in again")

        # Rotate: blacklist the just-consumed jti; issue a new token that
        # carries the same family_id so future replay detection works.
        if jti is not None:
            await self._blacklist_jti(redis, jti, payload.get("exp"))

        return TokenResponse(
            access_token=create_access_token(str(user.id), {"role": user.role}),
            refresh_token=create_refresh_token(str(user.id), family_id=family_id),
        )

    @staticmethod
    async def _blacklist_jti(redis: Any, jti: str, exp: int | None) -> None:
        """Blacklist a token's jti in Redis until its natural expiry."""
        now_ts = int(datetime.now(UTC).timestamp())
        ttl = max(1, exp - now_ts) if exp else settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400
        await redis.setex(f"blacklist:{jti}", ttl, "1")

    @staticmethod
    async def _revoke_family(redis: Any, family_id: str) -> None:
        """Revoke all tokens in a refresh-token family.

        Called on reuse detection.  Any token sharing this ``family_id`` will be
        rejected on the next refresh attempt regardless of its individual jti
        blacklist status.  TTL matches the maximum refresh token lifetime so the
        key expires automatically once no valid token in the family could exist.
        """
        ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400
        await redis.setex(f"revoked_family:{family_id}", ttl, "1")
