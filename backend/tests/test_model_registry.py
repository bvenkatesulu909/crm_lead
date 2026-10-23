"""Every module's models must be listed in app/model_registry.py.

Alembic compares the database with the models it finds through that file only. A module whose
models.py is missing there makes `alembic revision --autogenerate` propose DROPPING that
module's tables (this nearly happened with the knowledge-base tables). The check is static, so
it needs no database and runs the same on a developer's computer and in CI.
"""

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_every_module_with_models_is_registered() -> None:
    registry = (APP / "model_registry.py").read_text(encoding="utf-8")
    missing = [
        models.parent.name
        for models in sorted((APP / "modules").glob("*/models.py"))
        if f"from app.modules.{models.parent.name} import models" not in registry
    ]
    assert missing == [], (
        f"modules with a models.py that model_registry.py does not import: {missing}. "
        "Add them, or Alembic autogenerate will propose dropping their tables."
    )


def test_core_model_files_are_registered() -> None:
    registry = (APP / "model_registry.py").read_text(encoding="utf-8")
    for name in ("audit", "heartbeat", "outbox"):
        assert f"from app.core import {name} as {name}_models" in registry
