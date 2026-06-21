import enum


class VaultType(enum.StrEnum):
    """Settlement rail every transaction must declare.

    MPESA and CASH are the original dual-vault rails; BANK was added when bank
    statement reconciliation (Agent C, bank_statement_lines → invoices) began
    producing Payment rows tagged with their settlement rail.
    """
    MPESA = "MPESA"
    CASH = "CASH"
    BANK = "BANK"
