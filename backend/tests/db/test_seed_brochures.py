# ruff: noqa: F811, F401 - fixtures are imported and used as parameters
"""The fictional brochure seed (CRM-115 / BP-08, step BR1, docs/brochures-rera.md).

The brochures go through the knowledge module's own upload and ingestion (file type, visibility,
versions, chunks), against the real test database. A deterministic stand-in embedder is used so no
model is downloaded; the full-text part of the search is the real PostgreSQL one.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_evals.rag import HashingEmbedder
from app.core.db import bind_tenant
from app.core.storage import MemoryFileStore
from app.modules.knowledge import retrieval
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from scripts import seed_brochures_demo as seed
from tests.db.test_approvals import Acting, acting, alpha
from tests.db.test_quotes_api import World, world

EMBEDDER = HashingEmbedder()
MAX_BYTES = 1024 * 1024


def run(acting: Acting, who: str, brochures: list[seed.Brochure]) -> seed.SeedReport:
    return seed.seed(
        acting.session,
        acting.who(who),
        MemoryFileStore(),
        EMBEDDER,
        brochures,
        max_bytes=MAX_BYTES,
    )


def documents(db: Session, tenant_id: uuid.UUID) -> list[KnowledgeDocument]:
    bind_tenant(db, tenant_id)
    return list(
        db.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.tenant_id == tenant_id)
            .order_by(KnowledgeDocument.title, KnowledgeDocument.version)
        )
    )


def beta(world: World) -> uuid.UUID:
    return world.users["beta.admin"].tenant_id


def find(
    acting: Acting, who: str, query: str, account_ids: list[uuid.UUID] | None = None
) -> set[str]:
    outcome = retrieval.search(
        acting.session,
        acting.who(who),
        EMBEDDER,
        query=query,
        candidates=40,
        rrf_k=60,
        top_k=5,
        min_similarity=None,
        account_ids=account_ids,
    )
    return {hit.document_title for hit in outcome.results}


@pytest.fixture
def seeded(acting: Acting, world: World) -> Acting:
    run(acting, "alpha.admin", seed.ALPHA_BROCHURES)
    run(acting, "beta.admin", seed.BETA_BROCHURES)
    acting.session.flush()
    return acting


# --- the content itself (no database) ---------------------------------------------------------


def all_brochures() -> list[seed.Brochure]:
    return [*seed.ALPHA_BROCHURES, *seed.BETA_BROCHURES]


def test_every_rera_number_is_fictional_and_fits_the_web_check_pattern() -> None:
    from app.modules.webcheck.sources import SOURCES

    pattern = SOURCES["demo_rera"].query_pattern
    numbers = [n for b in all_brochures() for n in seed.rera_numbers(b.text)]
    assert len(numbers) >= 4
    for number in numbers:
        assert number.startswith("DEMO-") and pattern.fullmatch(number), number
    # Nothing that LOOKS like a real registration (a P-number without the DEMO- prefix).
    for brochure in all_brochures():
        stripped = brochure.text.replace("DEMO-P", "")
        assert "P024" not in stripped and "P052" not in stripped, brochure.title


def test_the_set_covers_what_the_gate_will_need() -> None:
    visibilities = {b.visibility for b in seed.ALPHA_BROCHURES}
    assert visibilities == {"internal", "customer_visible"}
    assert any(b.replaces for b in seed.ALPHA_BROCHURES)  # a newer version with a changed price
    assert any(not seed.rera_numbers(b.text) for b in seed.ALPHA_BROCHURES)  # no RERA number yet
    keys = [b.key for b in all_brochures()]
    assert len(keys) == len(set(keys))
    for brochure in all_brochures():
        assert brochure.replaces is None or brochure.replaces in keys
        assert "fictional" in brochure.text.lower(), brochure.title


# --- seeding ----------------------------------------------------------------------------------


def test_seeding_stores_and_indexes_every_brochure_with_its_visibility(
    seeded, db_session, world
) -> None:
    stored = documents(db_session, alpha(world))
    assert len(stored) == len(seed.ALPHA_BROCHURES)
    wanted = {(b.title, b.visibility) for b in seed.ALPHA_BROCHURES}
    assert {(d.title, d.visibility) for d in stored} == wanted
    assert all(d.status == "indexed" for d in stored), [(d.title, d.status) for d in stored]
    chunks = db_session.scalar(
        select(KnowledgeChunk.id).where(KnowledgeChunk.tenant_id == alpha(world)).limit(1)
    )
    assert chunks is not None
    assert all(d.created_by_user_id == world.users["alpha.admin"].id for d in stored)


def test_the_replaced_brochure_is_archived_and_the_new_one_is_version_two(
    seeded, db_session, world
) -> None:
    newer = next(b for b in seed.ALPHA_BROCHURES if b.replaces)
    older = next(b for b in seed.ALPHA_BROCHURES if b.key == newer.replaces)
    assert older.title == newer.title  # the same brochure, a new edition
    versions = sorted(
        (d for d in documents(db_session, alpha(world)) if d.title == newer.title),
        key=lambda d: d.version,
    )
    assert [(d.version, d.is_archived) for d in versions] == [(1, True), (2, False)]
    assert versions[0].group_id == versions[1].group_id


def test_seeding_twice_adds_nothing(seeded, db_session, world) -> None:
    before = len(documents(db_session, alpha(world)))
    report = run(seeded, "alpha.admin", seed.ALPHA_BROCHURES)
    assert report.created == 0 and report.skipped == len(seed.ALPHA_BROCHURES)
    assert len(documents(db_session, alpha(world))) == before


def test_each_organisation_gets_only_its_own_brochures(seeded, db_session, world) -> None:
    alpha_titles = {d.title for d in documents(db_session, alpha(world))}
    beta_titles = {d.title for d in documents(db_session, beta(world))}
    assert beta_titles == {b.title for b in seed.BETA_BROCHURES}
    assert not alpha_titles & beta_titles


def test_brochures_for_knows_the_two_demo_organisations_only() -> None:
    assert seed.brochures_for("alpha-demo") == seed.ALPHA_BROCHURES
    assert seed.brochures_for("beta-demo") == seed.BETA_BROCHURES
    assert seed.brochures_for("someone-real") == []


# --- what people can find (section 3c of the design) --------------------------------------------


def lakeview() -> seed.Brochure:
    return next(b for b in seed.ALPHA_BROCHURES if b.key == "lakeview")


def test_staff_find_a_brochure_by_its_rera_number(seeded) -> None:
    (number,) = seed.rera_numbers(lakeview().text)
    assert lakeview().title in find(seeded, "alpha.agent1", f"What is the status of {number}?")


def test_a_customer_never_finds_the_internal_price_sheet(seeded) -> None:
    sheet = next(b for b in seed.ALPHA_BROCHURES if b.visibility == "internal")
    assert sheet.title in find(seeded, "alpha.agent1", "internal floor price Lakeview")
    assert sheet.title not in find(seeded, "alpha.customer", "internal floor price Lakeview", [])


def test_another_organisation_never_finds_our_brochures(seeded) -> None:
    (number,) = seed.rera_numbers(lakeview().text)
    titles = {b.title for b in seed.ALPHA_BROCHURES}
    assert not find(seeded, "beta.agent", number) & titles
