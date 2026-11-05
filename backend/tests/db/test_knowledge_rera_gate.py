# ruff: noqa: F811, F401 - fixtures are imported and used as parameters
"""The RERA / price refusal gate through the real answer pipeline (CRM-115 / BP-08, step BR2).

The fictional brochures of BR1 are seeded into the test database; only the model is scripted (it
returns a fixed text, so each test decides what the "model" claims). The search is the real one:
permission filters, full-text, pgvector, and the new exact-number lookup.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_evals.rag import HashingEmbedder
from app.core.storage import MemoryFileStore
from app.modules.assistant.llm import ModelReply
from app.modules.knowledge import answers, retrieval
from app.modules.knowledge.models import KnowledgeDocument
from scripts import seed_brochures_demo as seed
from tests.db.test_approvals import Acting, acting
from tests.db.test_qualifier_governed import make_settings
from tests.db.test_quotes_api import World, world

EMBEDDER = HashingEmbedder()
SETTINGS = make_settings(knowledge_min_similarity=0.0)
LAKEVIEW = "DEMO-P02400000001"
SKYLINE = "DEMO-P02400000003"
HARBOUR = "DEMO-P05200000001"  # beta-demo's


class Scripted:
    """A model that answers with one fixed text and remembers what it was shown."""

    available = True

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[list[dict[str, Any]]] = []

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.calls.append(messages)
        return ModelReply(self.text, [], "end_turn")


@pytest.fixture
def brochures(acting: Acting, world: World) -> Acting:
    for who, brochures in (
        ("alpha.admin", seed.ALPHA_BROCHURES),
        ("beta.admin", seed.BETA_BROCHURES),
    ):
        seed.seed(
            acting.session,
            acting.who(who),
            MemoryFileStore(),
            EMBEDDER,
            brochures,
            max_bytes=1024 * 1024,
        )
    acting.session.flush()
    return acting


def ask(
    acting: Acting, who: str, question: str, model: Scripted, **settings: Any
) -> answers.AnswerOutcome:
    return answers.answer_question(
        acting.session,
        acting.who(who),
        EMBEDDER,
        model,
        question=question,
        settings=make_settings(knowledge_min_similarity=0.0, **settings),
        account_ids=[] if who.endswith("customer") else None,
    )


def shown(model: Scripted) -> str:
    return str(model.calls[0][0]["content"])


def sources_shown(model: Scripted) -> str:
    """Only the sources part of what the model was shown (not the person's own question)."""
    return shown(model).split("Sources:", 1)[1]


def cite(acting: Acting, who: str, question: str, *needles: str) -> str:
    """The citation marks of the sources that hold each needle (asks once with a probe model)."""
    probe = Scripted("x [1].")
    ask(acting, who, question, probe)
    blocks = sources_shown(probe).split("\n\n[")
    marks: list[str] = []
    for needle in needles:
        number = next(i for i, block in enumerate(blocks, start=1) if needle in block)
        if f"[{number}]" not in marks:
            marks.append(f"[{number}]")
    return "".join(marks)


# --- a number nobody has on file ------------------------------------------------------------------


def test_an_unknown_rera_number_is_refused_before_the_model(brochures) -> None:
    model = Scripted("It is registered [1].")
    outcome = ask(brochures, "alpha.agent1", "Is DEMO-P02499999999 registered?", model)
    assert model.calls == []
    assert outcome.reason == "rera_not_found" and not outcome.enough and not outcome.sources
    assert "DEMO-P02499999999" in outcome.answer and "couldn't find" in outcome.answer


def test_another_organisations_number_is_unknown_to_us(brochures) -> None:
    model = Scripted("It is registered [1].")
    outcome = ask(brochures, "alpha.agent1", f"Is {HARBOUR} registered?", model)
    assert model.calls == [] and outcome.reason == "rera_not_found"


def test_one_unknown_number_among_known_ones_is_enough_to_refuse(brochures) -> None:
    model = Scripted("Both are registered [1].")
    outcome = ask(brochures, "alpha.agent1", f"Compare {LAKEVIEW} and DEMO-P02499999999", model)
    assert model.calls == [] and outcome.reason == "rera_not_found"
    assert "DEMO-P02499999999" in outcome.answer


# --- the exact-number lookup ----------------------------------------------------------------------


def test_the_brochure_with_the_asked_number_is_always_a_source(brochures) -> None:
    model = Scripted(f"Skyline Towers is registered as {SKYLINE} [1].")
    outcome = ask(brochures, "alpha.agent1", f"{SKYLINE} price", model)
    assert outcome.sources[0].document_title == "Skyline Towers brochure"
    assert SKYLINE in shown(model)


def test_the_exact_lookup_ignores_case_and_dashes(brochures) -> None:
    model = Scripted(f"Skyline Towers is registered as {SKYLINE} [1].")
    outcome = ask(brochures, "alpha.agent1", "what about demo-p0240-0000003?", model)
    assert outcome.sources and outcome.sources[0].document_title == "Skyline Towers brochure"


def test_the_exact_lookup_never_finds_the_archived_edition(brochures) -> None:
    model = Scripted(f"Skyline Towers ({SKYLINE}) starts at ₹78 lakh [1].")
    outcome = ask(brochures, "alpha.agent1", f"{SKYLINE} price", model)
    assert "₹72 lakh" not in sources_shown(model) and "₹78 lakh" in sources_shown(model)
    assert outcome.model_used


def test_the_rest_of_the_brochure_comes_with_its_number(brochures) -> None:
    """The number is in the "Project" section, the prices in another one: both are shown."""
    model = Scripted("x [1].")
    ask(brochures, "alpha.agent1", f"{SKYLINE} price", model)
    assert SKYLINE in sources_shown(model) and "from ₹78 lakh" in sources_shown(model)


def test_a_customer_never_gets_the_internal_price_sheet_through_the_number(brochures) -> None:
    model = Scripted(f"Lakeview Residences is registered as {LAKEVIEW} [1].")
    ask(brochures, "alpha.customer", f"{LAKEVIEW} floor price", model)
    assert "Internal price sheet" not in sources_shown(model)
    assert "₹80 lakh" not in sources_shown(model)
    assert "₹85 lakh" in sources_shown(model)  # the public brochure is there


# --- the answer must quote its cited sources ------------------------------------------------------


def test_a_correct_answer_passes_and_gets_the_fixed_line(brochures) -> None:
    question = f"What does {LAKEVIEW} cost?"
    marks = cite(brochures, "alpha.agent1", question, LAKEVIEW, "₹85 lakh")
    text = f"Lakeview Residences ({LAKEVIEW}) starts at ₹85 lakh {marks}."
    outcome = ask(brochures, "alpha.agent1", question, Scripted(text))
    assert outcome.grounded and outcome.reason is None
    assert outcome.answer.startswith(text)
    assert outcome.answer.endswith(answers.LIVE_CHECK_LINE)


def test_an_invented_rera_number_is_refused(brochures) -> None:
    model = Scripted("Lakeview Residences is registered as DEMO-P02412345678 [1].")
    outcome = ask(brochures, "alpha.agent1", f"What is {LAKEVIEW}?", model)
    assert outcome.reason == "rera_not_cited" and not outcome.grounded
    assert outcome.answer == answers.NUMBERS_REFUSAL and "DEMO-P02412345678" not in outcome.answer
    assert outcome.sources == [] and outcome.model_used


def test_a_wrong_price_is_refused(brochures) -> None:
    question = f"{SKYLINE} price"
    marks = cite(brochures, "alpha.agent1", question, SKYLINE, "₹78 lakh")
    model = Scripted(f"Skyline Towers ({SKYLINE}) starts at ₹72 lakh {marks}.")  # the OLD price
    outcome = ask(brochures, "alpha.agent1", question, model)
    assert outcome.reason == "price_not_cited" and outcome.answer == answers.NUMBERS_REFUSAL


def test_a_number_in_a_source_that_is_not_cited_is_refused(brochures) -> None:
    """The number is in source [1], but the answer only cites a source number that has no such
    number in it: citing the wrong document is not quoting."""
    probe = Scripted("x [1].")
    first = ask(brochures, "alpha.agent1", f"{SKYLINE} and the Lakeview floor price", probe)
    assert len(first.sources) >= 2 or first.reason is not None
    other = next((n for n, s in enumerate(first.sources, start=1) if SKYLINE not in s.text), None)
    assert other is not None
    model = Scripted(f"Skyline Towers is {SKYLINE} [{other}].")
    outcome = ask(brochures, "alpha.agent1", f"{SKYLINE} and the Lakeview floor price", model)
    assert outcome.reason == "rera_not_cited"


def test_the_persons_own_budget_may_be_repeated(brochures) -> None:
    question = f"My budget is 90 lakh, does {SKYLINE} fit?"
    marks = cite(brochures, "alpha.agent1", question, SKYLINE, "₹78 lakh")
    model = Scripted(f"With ₹90 lakh, a Skyline 2 BHK ({SKYLINE}) from ₹78 lakh fits {marks}.")
    outcome = ask(brochures, "alpha.agent1", question, model)
    assert outcome.grounded and outcome.reason is None


def test_answers_without_numbers_work_as_before(brochures) -> None:
    model = Scripted("Orchid Plots has no registration number yet [1].")
    outcome = ask(brochures, "alpha.agent1", "Does Orchid Plots have a RERA number?", model)
    assert outcome.grounded and outcome.reason is None
    assert not outcome.answer.endswith(answers.LIVE_CHECK_LINE)


def test_an_answer_without_a_citation_is_still_refused_first(brochures) -> None:
    model = Scripted(f"It is {LAKEVIEW}.")
    outcome = ask(brochures, "alpha.agent1", f"What is {LAKEVIEW}?", model)
    assert outcome.answer == answers.UNGROUNDED_REFUSAL and outcome.reason == "ungrounded"


# --- the two literal lookups keep every permission rule -------------------------------------------


def internal_note(acting: Acting) -> uuid.UUID:
    """An internal staff note that names a customer-visible project's RERA number."""
    brochure = seed.Brochure(
        "note",
        "Internal note - Lakeview negotiation",
        "internal-note-lakeview.md",
        f"# Internal note\n\nFictional. For {LAKEVIEW}: the floor price is ₹79 lakh. Staff only.\n",
        "internal",
    )
    seed.seed(
        acting.session,
        acting.who("alpha.admin"),
        MemoryFileStore(),
        EMBEDDER,
        [brochure],
        max_bytes=1024 * 1024,
    )
    acting.session.flush()
    found = acting.session.scalar(
        select(KnowledgeDocument.id).where(KnowledgeDocument.title == brochure.title)
    )
    assert found is not None
    return found


def test_the_number_lookup_never_gives_a_customer_an_internal_document(brochures) -> None:
    note = internal_note(brochures)
    staff = retrieval.chunks_with_number(
        brochures.session, brochures.who("alpha.agent1"), LAKEVIEW, limit=10
    )
    assert note in {hit.document_id for hit in staff}
    customer = retrieval.chunks_with_number(
        brochures.session, brochures.who("alpha.customer"), LAKEVIEW, limit=10, account_ids=[]
    )
    assert customer and note not in {hit.document_id for hit in customer}


def test_the_sections_lookup_never_gives_a_customer_an_internal_document(brochures) -> None:
    note = internal_note(brochures)
    principal = brochures.who("alpha.customer")
    assert (
        retrieval.document_chunks(brochures.session, principal, note, limit=10, account_ids=[])
        == []
    )
    staff = brochures.who("alpha.agent1")
    assert retrieval.document_chunks(brochures.session, staff, note, limit=10)


def archived_skyline(acting: Acting) -> uuid.UUID:
    acting.who("alpha.admin")  # read as alpha (row-level security)
    found = acting.session.scalar(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.title == "Skyline Towers brochure", KnowledgeDocument.is_archived
        )
    )
    assert found is not None
    return found


def test_neither_lookup_returns_an_archived_edition(brochures) -> None:
    old = archived_skyline(brochures)
    staff = brochures.who("alpha.agent1")
    hits = retrieval.chunks_with_number(brochures.session, staff, SKYLINE, limit=10)
    assert hits and old not in {hit.document_id for hit in hits}
    assert retrieval.document_chunks(brochures.session, staff, old, limit=10) == []


def test_neither_lookup_crosses_into_another_organisation(brochures) -> None:
    beta = brochures.who("beta.agent")
    assert retrieval.chunks_with_number(brochures.session, beta, LAKEVIEW, limit=10) == []
    old = archived_skyline(brochures)
    lakeview = retrieval.chunks_with_number(
        brochures.session, brochures.who("alpha.agent1"), LAKEVIEW, limit=1
    )[0].document_id
    beta = brochures.who("beta.agent")
    assert retrieval.document_chunks(brochures.session, beta, lakeview, limit=10) == []
    assert old  # (the archived edition exists, so the test above is meaningful)
