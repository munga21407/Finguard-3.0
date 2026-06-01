import enum


class VaultType(str, enum.Enum):
    """Dual-vault: every transaction must declare its payment rail."""
    MPESA = "MPESA"
    CASH = "CASH"
