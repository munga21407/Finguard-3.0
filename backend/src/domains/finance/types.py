import enum


class VaultType(enum.StrEnum):
    """Dual-vault: every transaction must declare its payment rail."""
    MPESA = "MPESA"
    CASH = "CASH"
