"""The committed OpenAPI contract (docs/api/openapi.json) must match the code."""

from typing import Any

import pytest

from scripts.export_openapi import OUTPUT, build_openapi, render

LEAD_OPERATIONS = {
    ("/api/v1/leads", "get"),
    ("/api/v1/leads", "post"),
    ("/api/v1/leads/{lead_id}", "get"),
    ("/api/v1/leads/{lead_id}", "patch"),
    ("/api/v1/leads/{lead_id}/assign", "post"),
    ("/api/v1/leads/{lead_id}/status", "post"),
    ("/api/v1/leads/{lead_id}/qualify", "post"),
    ("/api/v1/leads/{lead_id}/disqualify", "post"),
    ("/api/v1/leads/{lead_id}/convert", "post"),
    ("/api/v1/leads/{lead_id}/activities", "get"),
    ("/api/v1/leads/{lead_id}/activities", "post"),
    ("/api/v1/leads/{lead_id}/assignments", "get"),
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return build_openapi()


def test_committed_contract_is_up_to_date() -> None:
    assert OUTPUT.exists(), "run: python -m scripts.export_openapi"
    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "docs/api/openapi.json is out of date - run: python -m scripts.export_openapi"
    )


def test_all_lead_operations_are_documented(spec: dict[str, Any]) -> None:
    documented = {(path, method) for path, ops in spec["paths"].items() for method in ops}

    assert documented >= LEAD_OPERATIONS


@pytest.mark.parametrize(("path", "method"), sorted(LEAD_OPERATIONS))
def test_lead_operations_document_auth_errors_and_bearer_security(
    spec: dict[str, Any], path: str, method: str
) -> None:
    operation = spec["paths"][path][method]

    assert operation.get("summary")
    assert {"401", "403"} <= set(operation["responses"])
    assert {"HTTPBearer": []} in operation.get("security", [])
    error_schema = operation["responses"]["403"]["content"]["application/json"]["schema"]
    assert error_schema["$ref"].endswith("/ProblemDetails")


def test_conversion_documents_both_success_codes(spec: dict[str, Any]) -> None:
    responses = spec["paths"]["/api/v1/leads/{lead_id}/convert"]["post"]["responses"]

    assert {"200", "201", "404", "409", "422"} <= set(responses)
