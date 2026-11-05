"""Seed fictional property brochures into the knowledge base (CRM-115 / BP-08, step BR1).

Run from the backend folder with the venv active (Windows CMD):

    python -m scripts.seed_brochures_demo

What it does, per demo organisation (alpha-demo, beta-demo):

* uploads each brochure through the knowledge module's own ``create_document`` - the same checks
  as the upload screen (file type, visibility, versions) - acting as that organisation's first
  active tenant administrator, so the upload is recorded as theirs;
* indexes it at once (chunks + embeddings), so it can be searched without waiting for the worker;
* skips a brochure whose exact text is already there, so running it twice adds nothing.

Everything is fictional. Every RERA number starts with ``DEMO-`` so nothing here can be mistaken for
a real registration (docs/brochures-rera.md). The set is chosen for the refusal gate of BR2: two
customer-visible brochures, an internal price sheet, a brochure replaced by a newer edition with a
changed price, and a project that has no RERA number yet.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import model_registry as _model_registry  # noqa: F401 - resolves cross-model FKs
from app.core.ai.embeddings import Embedder, build_embedder
from app.core.auth.principal import Principal
from app.core.auth.rbac import Role
from app.core.config import get_settings
from app.core.db import bind_tenant, create_db_engine, create_session_factory
from app.core.storage import FileStore, build_file_store
from app.modules.identity import api as identity_api
from app.modules.identity.models import Tenant, User
from app.modules.knowledge import service
from app.modules.knowledge.models import KnowledgeDocument

RERA_NUMBER = re.compile(r"\bDEMO-[A-Z0-9]{6,30}\b")
NOTICE = "Fictional demo brochure - not a real project, price or registration."


@dataclass(frozen=True)
class Brochure:
    key: str  # stable name inside this file (a newer edition names the key it replaces)
    title: str
    file_name: str
    text: str
    visibility: str  # "internal" | "customer_visible"
    replaces: str | None = None


@dataclass(frozen=True)
class SeedReport:
    created: int
    skipped: int


def rera_numbers(text: str) -> list[str]:
    return RERA_NUMBER.findall(text)


def _brochure(title: str, body: str) -> str:
    return f"# {title}\n\n_{NOTICE}_\n\n{body.strip()}\n"


ALPHA_BROCHURES: list[Brochure] = [
    Brochure(
        "lakeview",
        "Lakeview Residences brochure",
        "lakeview-residences.md",
        _brochure(
            "Lakeview Residences",
            """
## Project

Lakeview Residences is a fictional apartment project in Kokapet, Hyderabad.
RERA registration number: DEMO-P02400000001.

## Homes and prices

- 2 BHK, 1,250 sq ft: from ₹85 lakh.
- 3 BHK, 1,780 sq ft: up to ₹1.4 crore.

## Possession

Possession is planned for December 2027.
""",
        ),
        "customer_visible",
    ),
    Brochure(
        "greenfield",
        "Greenfield Villas brochure",
        "greenfield-villas.md",
        _brochure(
            "Greenfield Villas",
            """
## Project

Greenfield Villas is a fictional gated villa community in Shamshabad, Hyderabad.
RERA registration number: DEMO-P02400000002.

## Homes and prices

- 3 BHK villa: from ₹2.1 crore.
- 4 BHK villa: up to ₹3.5 crore.

## Possession

Possession is planned for June 2028.
""",
        ),
        "customer_visible",
    ),
    Brochure(
        "skyline-2025",
        "Skyline Towers brochure",
        "skyline-towers.md",
        _brochure(
            "Skyline Towers",
            """
## Project

Skyline Towers is a fictional high-rise in Gachibowli, Hyderabad.
RERA registration number: DEMO-P02400000003.

## Homes and prices (2025 edition)

- 2 BHK: from ₹72 lakh.
- 3 BHK: up to ₹1.1 crore.
""",
        ),
        "customer_visible",
    ),
    Brochure(
        "skyline-2026",
        "Skyline Towers brochure",
        "skyline-towers-2026.md",
        _brochure(
            "Skyline Towers",
            """
## Project

Skyline Towers is a fictional high-rise in Gachibowli, Hyderabad.
RERA registration number: DEMO-P02400000003.

## Homes and prices (2026 edition, replaces the 2025 prices)

- 2 BHK: from ₹78 lakh.
- 3 BHK: up to ₹1.2 crore.
""",
        ),
        "customer_visible",
        replaces="skyline-2025",
    ),
    Brochure(
        "price-sheet",
        "Internal price sheet - Lakeview Residences",
        "internal-price-sheet-lakeview.md",
        _brochure(
            "Internal price sheet - Lakeview Residences",
            """
## For staff only

The internal floor price for a Lakeview Residences 2 BHK is ₹80 lakh.
Never quote the floor price to a buyer; a sales manager approves anything below the brochure price.
""",
        ),
        "internal",
    ),
    Brochure(
        "orchid",
        "Orchid Plots brochure",
        "orchid-plots.md",
        _brochure(
            "Orchid Plots",
            """
## Project

Orchid Plots is a fictional upcoming plotted development near Tukkuguda, Hyderabad.
The RERA registration has been applied for; there is no registration number yet.
Bookings open only after registration.
""",
        ),
        "customer_visible",
    ),
]

BETA_BROCHURES: list[Brochure] = [
    Brochure(
        "harbour",
        "Harbour Heights brochure",
        "harbour-heights.md",
        _brochure(
            "Harbour Heights",
            """
## Project

Harbour Heights is a fictional apartment project in Visakhapatnam.
RERA registration number: DEMO-P05200000001.

## Homes and prices

- 2 BHK: from ₹60 lakh.
""",
        ),
        "customer_visible",
    ),
]

_BY_SLUG = {"alpha-demo": ALPHA_BROCHURES, "beta-demo": BETA_BROCHURES}


def brochures_for(slug: str) -> list[Brochure]:
    """Only the two demo organisations get brochures - never a real organisation."""
    return _BY_SLUG.get(slug, [])


def _existing(session: Session, tenant_id: uuid.UUID, text: str) -> KnowledgeDocument | None:
    import hashlib

    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.sha256 == sha256
        )
    )


def seed(
    session: Session,
    principal: Principal,
    store: FileStore,
    embedder: Embedder,
    brochures: list[Brochure],
    *,
    max_bytes: int,
) -> SeedReport:
    """Upload and index the brochures as ``principal`` (a tenant administrator). Does not commit."""
    if principal.tenant_id is None:
        raise ValueError("a tenant administrator is required")
    tenant_id = principal.tenant_id
    by_key = {brochure.key: brochure for brochure in brochures}
    created = skipped = 0
    for brochure in brochures:
        if _existing(session, tenant_id, brochure.text) is not None:
            skipped += 1
            continue
        replaces: uuid.UUID | None = None
        if brochure.replaces is not None:
            previous = _existing(session, tenant_id, by_key[brochure.replaces].text)
            if previous is not None and not previous.is_archived:
                replaces = previous.id
        document = service.create_document(
            session,
            principal,
            store,
            title=brochure.title,
            file_name=brochure.file_name,
            content_type="text/markdown",
            data=brochure.text.encode("utf-8"),
            max_bytes=max_bytes,
            visibility=brochure.visibility,
            replaces_document_id=replaces,
        )
        session.flush()
        # Indexed now, so the brochure can be searched at once; the job create_document queued
        # for the worker indexes the same version again, which is safe.
        service.ingest_document(
            session, store, embedder, tenant_id=tenant_id, document_id=document.id
        )
        created += 1
    return SeedReport(created, skipped)


def _first_admin(session: Session, tenant_id: uuid.UUID) -> Principal | None:
    bind_tenant(session, tenant_id)
    admins = [
        user
        for user in session.scalars(
            select(User)
            .where(
                User.tenant_id == tenant_id,
                User.user_type == "staff",
                User.is_active.is_(True),
            )
            .order_by(User.email)
        )
        if Role.TENANT_ADMIN.value in (user.roles or [])
    ]
    if not admins:
        return None
    # A local tool the owner runs: it acts as this administrator on purpose, so the upload is
    # recorded as theirs (the same as if they had used the upload screen).
    return identity_api.staff_principal(session, tenant_id, admins[0].id)


def main() -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    store = build_file_store(settings)
    embedder = build_embedder(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        for slug in sorted(_BY_SLUG):
            tenant = session.scalar(select(Tenant).where(Tenant.slug == slug))
            if tenant is None:
                print(f"{slug}: no such organisation, skipped")
                continue
            admin = _first_admin(session, tenant.id)
            if admin is None:
                print(f"{slug}: no active tenant administrator, skipped")
                continue
            identity_api.bind_reader(session, admin)
            report = seed(
                session,
                admin,
                store,
                embedder,
                brochures_for(slug),
                max_bytes=settings.files_max_bytes,
            )
            session.commit()
            print(f"{slug}: {report.created} brochure(s) added, {report.skipped} already there")
    engine.dispose()


if __name__ == "__main__":
    main()
