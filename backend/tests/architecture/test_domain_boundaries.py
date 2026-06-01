"""
Architectural guardrail: domain isolation via static AST analysis.

Enforcement matrix
──────────────────
  identity     must NOT import from  finance | intelligence
  finance      must NOT import from  intelligence
  crm          must NOT import from  finance | intelligence

Rationale: domains are bounded contexts — cross-domain coupling must flow
through published interfaces (events, API calls), not direct Python imports.
The only permitted cross-domain dependency at the Python level is
finance → identity (router layer pulls auth helpers from identity).
"""

import ast
from pathlib import Path

import pytest

# Resolve paths relative to this file so tests work regardless of cwd.
_BACKEND_ROOT = Path(__file__).parent.parent.parent          # backend/
_DOMAINS_ROOT = _BACKEND_ROOT / "src" / "domains"

# (source_domain, forbidden_target_domains)
_ISOLATION_RULES: list[tuple[str, list[str]]] = [
    ("identity",    ["finance", "intelligence"]),
    ("finance",     ["intelligence"]),
    ("crm",         ["finance", "intelligence"]),
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _python_files(domain: str) -> list[Path]:
    return sorted((_DOMAINS_ROOT / domain).rglob("*.py"))


def _imported_modules(path: Path) -> list[str]:
    """Return every module string referenced by import statements in *path*."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


# ── smoke test ────────────────────────────────────────────────────────────────

def test_domains_root_exists() -> None:
    """Guard against mis-configured paths silently passing all boundary checks."""
    assert _DOMAINS_ROOT.is_dir(), (
        f"Domains directory not found at {_DOMAINS_ROOT}. "
        "Check that _BACKEND_ROOT resolution in this file is correct."
    )
    domains = [d.name for d in _DOMAINS_ROOT.iterdir() if d.is_dir()]
    for required in ("identity", "finance", "intelligence", "crm"):
        assert required in domains, f"Expected domain '{required}' not found under {_DOMAINS_ROOT}"


# ── boundary tests ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source_domain,forbidden_domains", _ISOLATION_RULES)
def test_domain_does_not_import_forbidden_domains(
    source_domain: str,
    forbidden_domains: list[str],
) -> None:
    """Assert that *source_domain* contains no Python import referencing any
    domain in *forbidden_domains*."""

    violations: list[str] = []

    for py_file in _python_files(source_domain):
        for module in _imported_modules(py_file):
            for forbidden in forbidden_domains:
                if f"src.domains.{forbidden}" in module:
                    rel = py_file.relative_to(_BACKEND_ROOT)
                    violations.append(f"  {rel}  →  '{module}'")

    assert not violations, (
        f"\nDomain '{source_domain}' illegally imports from "
        f"{forbidden_domains}:\n" + "\n".join(violations)
    )


# ── per-file parametrization for fine-grained failure messages ────────────────

def _boundary_cases() -> list[tuple[Path, str, list[str]]]:
    """Expand isolation rules to (file, source_domain, forbidden_domains) tuples."""
    cases = []
    for domain, forbidden in _ISOLATION_RULES:
        for py_file in _python_files(domain):
            cases.append((py_file, domain, forbidden))
    return cases


@pytest.mark.parametrize(
    "py_file,source_domain,forbidden_domains",
    [
        pytest.param(f, d, fb, id=str(f.relative_to(_DOMAINS_ROOT)))
        for f, d, fb in _boundary_cases()
    ],
)
def test_file_does_not_import_forbidden_domains(
    py_file: Path,
    source_domain: str,
    forbidden_domains: list[str],
) -> None:
    """Per-file boundary check so CI pinpoints the exact offending file."""
    violations = [
        f"'{module}'"
        for module in _imported_modules(py_file)
        if any(f"src.domains.{fb}" in module for fb in forbidden_domains)
    ]
    assert not violations, (
        f"\n{py_file.relative_to(_BACKEND_ROOT)} (domain: '{source_domain}') "
        f"imports from forbidden domain(s) {forbidden_domains}:\n  "
        + "\n  ".join(violations)
    )
