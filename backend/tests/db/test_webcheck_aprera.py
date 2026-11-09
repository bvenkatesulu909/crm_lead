# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""An AP RERA check end to end in the database (ADR 0019, Amendment A, step WC6b).

The request, the queued job and the REAL worker job (``run_check`` -> ``form_search`` -> the AP RERA
parser -> insert-only evidence). Only the network is replaced: a fake answers like the real site
(tests/aprera_pages.py - real structure, invented content)."""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.webfetch import PinnedRequest, TransportResponse
from app.modules.webcheck import service
from tests import aprera_pages as pages
from tests.db.test_approvals import add_lead
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name
from tests.db.test_webcheck import Acting, acting, settings  # noqa: F401

SOURCE = "rera_andhra_pradesh"
PATH = "/RERA/Views/Reports/ApprovedProjectSearch.aspx"
ON = settings(webcheck_demo=False, webcheck_sources=SOURCE)


class Site:
    """Plays rera.ap.gov.in: no robots.txt, the search page, then ``answer`` for the POST."""

    def __init__(self, answer: str = pages.results(pages.row(1)), page: str = pages.SEARCH):
        self.answer, self.page = answer, page
        self.requests: list[PinnedRequest] = []

    def resolver(self, host: str) -> list[str]:
        assert host == "rera.ap.gov.in"
        return ["93.184.216.34"]

    def transport(self, request: PinnedRequest) -> TransportResponse:
        self.requests.append(request)
        if request.target == "/robots.txt":
            return TransportResponse(404, {"content-type": "text/html"}, b"", False)
        assert request.target == PATH
        body = self.page if request.method == "GET" else self.answer
        return TransportResponse(
            200, {"content-type": "text/html; charset=utf-8"}, body.encode(), False
        )


def check(acting: Acting, db_session: Session, world: World, site: Site, query: str) -> Any:
    acting.demo.resolver = site.resolver  # type: ignore[method-assign]
    acting.demo.transport = site.transport  # type: ignore[method-assign]
    lead = add_lead(db_session, world)
    acting.request("alpha.agent1", lead.id, query, source_key=SOURCE, config=ON)
    [job] = acting.jobs()
    acting.run(job, config=ON)
    [row] = acting.evidence()
    return row


def test_a_registered_project_becomes_evidence(acting, db_session, world) -> None:
    site = Site()
    row = check(acting, db_session, world, site, "p00000000042")
    assert (row.verdict, row.status, row.registered_name) == (
        "found",
        "registered",
        "Eval Towers Phase 1",
    )
    assert (row.source_key, row.query) == (SOURCE, "P00000000042")  # stored in capitals
    assert row.final_url == f"https://rera.ap.gov.in{PATH}"
    assert "Promoter: Eval Builders Pvt Ltd" in row.excerpt and row.error_code is None
    assert [(r.method, r.target) for r in site.requests] == [
        ("GET", "/robots.txt"),
        ("GET", PATH),
        ("POST", PATH),
    ]


def test_a_number_that_is_not_registered_is_not_found(acting, db_session, world) -> None:
    row = check(acting, db_session, world, Site(answer=pages.NONE), "P00000000099")
    assert (row.verdict, row.status) == ("not_found", None)


def test_a_changed_search_form_is_stored_as_an_error_not_a_guess(acting, db_session, world) -> None:
    changed = pages.SEARCH.replace("./ApprovedProjectSearch.aspx", "./NewSearch.aspx")
    site = Site(page=changed)
    row = check(acting, db_session, world, site, "P00000000042")
    assert (row.verdict, row.error_code) == ("error", "form_changed")
    assert all(r.method == "GET" for r in site.requests)  # nothing was posted


def test_a_changed_results_table_is_unclear(acting, db_session, world) -> None:
    answer = pages.results(pages.row(1), header=pages.HEADER.replace("Status", "State"))
    row = check(acting, db_session, world, Site(answer=answer), "P00000000042")
    assert (row.verdict, row.status) == ("unclear", None)


def test_the_source_is_off_unless_the_deployment_names_it(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(service.SourceUnavailableError):
        acting.request(
            "alpha.agent1", lead.id, "P00000000042", source_key=SOURCE, config=settings()
        )
    assert acting.jobs() == []


@pytest.mark.parametrize("query", ["Eval Towers", "P0000000004", "https://rera.ap.gov.in/x"])
def test_only_one_registration_number_can_be_asked_for(acting, db_session, world, query) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(service.QueryNotValidError):
        acting.request("alpha.agent1", lead.id, query, source_key=SOURCE, config=ON)
    assert acting.jobs() == []
