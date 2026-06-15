"""Pure validation tests for CRM customer schemas (no DB).

Pin the request-contract guarantees the HTTP layer relies on: email format,
the customer-type enum + default, and status-enum coercion on update.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.domains.crm.models import CustomerStatus, CustomerType
from src.domains.crm.schemas import CustomerCreate, CustomerUpdate


def test_create_defaults_to_individual() -> None:
    c = CustomerCreate(name="Jane", email="jane@example.com")
    assert c.customer_type is CustomerType.INDIVIDUAL


def test_create_accepts_business_type() -> None:
    c = CustomerCreate(name="Acme", email="acme@example.com", customer_type="business")
    assert c.customer_type is CustomerType.BUSINESS


def test_create_rejects_malformed_email() -> None:
    with pytest.raises(ValidationError):
        CustomerCreate(name="Bad", email="not-an-email")


def test_create_rejects_unknown_customer_type() -> None:
    with pytest.raises(ValidationError):
        CustomerCreate(name="X", email="x@example.com", customer_type="alien")


def test_update_status_enum_coercion() -> None:
    u = CustomerUpdate(status="churned")
    assert u.status is CustomerStatus.CHURNED


def test_update_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        CustomerUpdate(status="frozen")


def test_update_all_fields_optional() -> None:
    # An empty PATCH body is valid (no-op update).
    assert CustomerUpdate().model_dump(exclude_unset=True) == {}
