"""
Schema compliance: enforce placement and sourcing of shared type definitions.

Rules
─────
  1. VaultType must NOT be declared as a class inside finance/models.py.
     (It belongs exclusively in finance/types.py.)

  2. finance/models.py MUST import VaultType from src.domains.finance.types.
     (Ensures the canonical definition is always used, never shadowed.)

  3. finance/types.py MUST define VaultType as a class.
     (Validates the canonical home actually exists.)
"""

import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).parent.parent.parent       # backend/
_FINANCE_DIR = _BACKEND_ROOT / "src" / "domains" / "finance"
_MODELS_PY = _FINANCE_DIR / "models.py"
_TYPES_PY = _FINANCE_DIR / "types.py"
_CANONICAL_MODULE = "src.domains.finance.types"


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class_names(tree: ast.Module) -> list[str]:
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def _importfrom_entries(tree: ast.Module) -> list[tuple[str, list[str]]]:
    """Return [(module, [name, ...]), ...] for every `from X import Y` statement."""
    entries = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [alias.name for alias in node.names]
            entries.append((node.module, names))
    return entries


# ── tests ─────────────────────────────────────────────────────────────────────

def test_vault_type_not_redefined_in_models() -> None:
    """VaultType must not appear as a class definition inside models.py.

    Defining it there would create a shadow that diverges from the canonical
    enum in types.py, breaking dual-vault consistency at the ORM layer.
    """
    tree = _parse(_MODELS_PY)
    defined_classes = _class_names(tree)
    assert "VaultType" not in defined_classes, (
        f"VaultType is defined as a class inside "
        f"{_MODELS_PY.relative_to(_BACKEND_ROOT)}. "
        "Move the definition to src/domains/finance/types.py and import it."
    )


def test_vault_type_imported_from_canonical_module() -> None:
    """models.py must import VaultType from src.domains.finance.types.

    Any other source (local definition, re-export via __init__, etc.) violates
    the single-source-of-truth rule for the dual-vault type.
    """
    tree = _parse(_MODELS_PY)
    for module, names in _importfrom_entries(tree):
        if module == _CANONICAL_MODULE and "VaultType" in names:
            return  # compliant

    raise AssertionError(
        f"{_MODELS_PY.relative_to(_BACKEND_ROOT)} does not import VaultType "
        f"from '{_CANONICAL_MODULE}'.\n"
        "Add:  from src.domains.finance.types import VaultType"
    )


def test_vault_type_defined_in_types_module() -> None:
    """The canonical home — finance/types.py — must actually define VaultType."""
    tree = _parse(_TYPES_PY)
    assert "VaultType" in _class_names(tree), (
        f"VaultType is not defined in "
        f"{_TYPES_PY.relative_to(_BACKEND_ROOT)}. "
        "Ensure the enum class exists there as the single source of truth."
    )


def test_vault_type_is_enum_subclass() -> None:
    """VaultType in types.py must subclass enum.Enum (or str + enum.Enum).

    A plain class would break SQLAlchemy's Enum column type mapping.
    """
    tree = _parse(_TYPES_PY)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "VaultType":
            base_ids = []
            for base in node.bases:
                # handles  Name(id='Enum')  and  Attribute(attr='Enum')
                if isinstance(base, ast.Name):
                    base_ids.append(base.id)
                elif isinstance(base, ast.Attribute):
                    base_ids.append(base.attr)
            assert "Enum" in base_ids, (
                f"VaultType in {_TYPES_PY.relative_to(_BACKEND_ROOT)} does not "
                "subclass Enum. It must inherit from enum.Enum (or str + enum.Enum) "
                "for SQLAlchemy column compatibility."
            )
            return

    raise AssertionError("VaultType class not found in types.py — test_vault_type_defined_in_types_module should have caught this first.")
