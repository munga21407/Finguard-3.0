"""Unit tests for the RBAC permission matrix (no DB / HTTP)."""
from __future__ import annotations

import pytest

from src.domains.identity.models import UserRole
from src.domains.identity.permissions import Permission, has_permission, role_permissions


@pytest.mark.parametrize("role", list(UserRole))
def test_every_role_can_read(role: UserRole) -> None:
    assert has_permission(role, Permission.FINANCE_READ)
    assert has_permission(role, Permission.CRM_READ)
    assert has_permission(role, Permission.INTELLIGENCE_READ)


def test_viewer_cannot_write_or_act() -> None:
    for perm in (
        Permission.FINANCE_WRITE,
        Permission.CRM_WRITE,
        Permission.INTELLIGENCE_ACT,
        Permission.USER_MANAGE,
    ):
        assert not has_permission(UserRole.VIEWER, perm)


@pytest.mark.parametrize("role", [UserRole.ACCOUNTANT, UserRole.MANAGER])
def test_operators_can_write_and_act_but_not_manage_users(role: UserRole) -> None:
    assert has_permission(role, Permission.FINANCE_WRITE)
    assert has_permission(role, Permission.CRM_WRITE)
    assert has_permission(role, Permission.INTELLIGENCE_ACT)
    assert not has_permission(role, Permission.USER_MANAGE)


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.OWNER])
def test_admins_hold_every_permission(role: UserRole) -> None:
    assert role_permissions(role) == frozenset(Permission)
