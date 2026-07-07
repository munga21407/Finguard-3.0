import enum


class UnitOfMeasure(enum.StrEnum):
    EACH = "each"
    KG = "kg"
    LITRE = "litre"
    METRE = "metre"
    BOX = "box"
    PACK = "pack"


class MovementType(enum.StrEnum):
    """The signed direction is derived from the type, not stored free-form."""

    RECEIPT = "receipt"
    ISSUE = "issue"
    SALE = "sale"
    RETURN_IN = "return_in"
    ADJUSTMENT = "adjustment"
    TRANSFER = "transfer"


INBOUND = frozenset({MovementType.RECEIPT, MovementType.RETURN_IN})


class MovementReason(enum.StrEnum):
    PURCHASE = "purchase"
    SALE = "sale"
    DAMAGE = "damage"
    THEFT = "theft"
    STOCK_TAKE = "stock_take"
    EXPIRY = "expiry"
    CORRECTION = "correction"
    OTHER = "other"
