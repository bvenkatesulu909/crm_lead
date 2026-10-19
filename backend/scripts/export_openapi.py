"""Write the API contract (OpenAPI 3) to docs/api/openapi.json.

Run from the backend folder after changing any endpoint or schema, and commit the result:

    python -m scripts.export_openapi

tests/test_openapi_contract.py fails if the committed file no longer matches the code, so the
documented contract can never silently drift from what the API really does.
"""

import json
from pathlib import Path
from typing import Any

from app.core.auth.tokens import StaticKeyProvider, TokenVerifier
from app.core.config import Settings
from app.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    # Placeholder settings: nothing here appears in the contract, and no .env file is needed.
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused@127.0.0.1:1/unused",
        oidc_issuer="http://localhost:8080/realms/crm",
    )
    verifier = TokenVerifier(
        issuer=settings.oidc_issuer,
        audience="crm-api",
        key_provider=StaticKeyProvider({"keys": []}),
    )
    schema: dict[str, Any] = create_app(settings, token_verifier=verifier).openapi()
    return schema


def render() -> str:
    return json.dumps(build_openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
