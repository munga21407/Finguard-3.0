"""
Role-based access control (RBAC) policy.

A single source of truth mapping each ``UserRole`` to the set of permissions it
grants.  Routers depend on ``require_permission(...)`` (see
``identity.dependencies``) so authorization is enforced consistently and
default-deny — a role only gets a permission if it is listed here.

Design notes
------------
* Permissions are coarse-grained per domain + verb (read vs write/act).  This is
  enough to stop a ``viewer`` from mutating financial data while keeping the
  matrix readable; finer object-level checks belong in the service layer.
* Roles are cumulative in practice but the matrix is written out explicitly per
  role rather than via inheritance, so the exact grant of every role is
  auditable at a glance.
"""
from __future__ import annotations

import enum

from src.domains.identity.models import UserRole


class Permission(enum.StrEnum):
    FINANCE_READ = "finance:read"
    FINANCE_WRITE = "finance:write"
    CRM_READ = "crm:read"
    CRM_WRITE = "crm:write"
    INTELLIGENCE_READ = "intelligence:read"      # read-only insights / cached reads
    INTELLIGENCE_ACT = "intelligence:act"        # state-changing agent actions
    USER_MANAGE = "user:manage"                  # verify users, change roles


_READ_ONLY: frozenset[Permission] = frozenset(
    {Permission.FINANCE_READ, Permission.CRM_READ, Permission.INTELLIGENCE_READ}
)

_OPERATOR: frozenset[Permission] = _READ_ONLY | frozenset(
    {Permission.FINANCE_WRITE, Permission.CRM_WRITE, Permission.INTELLIGENCE_ACT}
)

_ADMIN: frozenset[Permission] = _OPERATOR | frozenset({Permission.USER_MANAGE})


# Default-deny: any role absent here (should never happen — enum is exhaustive)
# resolves to no permissions.
_ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.VIEWER: _READ_ONLY,
    UserRole.ACCOUNTANT: _OPERATOR,
    UserRole.MANAGER: _OPERATOR,
    UserRole.ADMIN: _ADMIN,
    UserRole.OWNER: _ADMIN,
}


def role_permissions(role: UserRole) -> frozenset[Permission]:
    """Return the full permission set granted to *role* (empty if unknown)."""
    return _ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in role_permissions(role)
