"""The Alembic migration history is a single linear chain (no DB needed).

Guards against the classic multi-head merge hazard: a stray branch would let two
migrations claim the same ``down_revision`` and silently diverge.
"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script_directory() -> ScriptDirectory:
    alembic_dir = Path(__file__).resolve().parent.parent / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    return ScriptDirectory.from_config(cfg)


def test_single_migration_head() -> None:
    assert len(_script_directory().get_heads()) == 1


def test_chain_is_linear() -> None:
    script = _script_directory()
    revisions = list(script.walk_revisions())
    # Exactly one base (down_revision is None) and no shared parents → linear.
    bases = [r for r in revisions if r.down_revision is None]
    assert len(bases) == 1, f"expected a single base revision, got {bases}"
    parents = [r.down_revision for r in revisions if r.down_revision is not None]
    assert len(parents) == len(set(parents)), "a revision is reused as a parent (branch)"
