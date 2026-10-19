"""Staff endpoints for contacts, mounted at /api/v1/contacts.

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.contacts import service
from app.modules.contacts.repository import ContactFilters
from app.modules.contacts.schemas import (
    ContactArchive,
    ContactCreate,
    ContactDuplicateCheck,
    ContactPage,
    ContactRead,
    ContactSort,
    ContactUpdate,
    EmailConsent,
    HistoryEntry,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/contacts", tags=["contacts"], responses=problem_responses(401, 403))

Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.CONTACT_READ_ALL, Permission.CONTACT_READ_OWN)),
]
Writer = Annotated[
    Principal,
    Depends(require_any_permission(Permission.CONTACT_WRITE_ALL, Permission.CONTACT_WRITE_OWN)),
]
Db = Annotated[Session, Depends(get_db_session)]


@router.get(
    "",
    summary="List and search the contacts you may see",
    description="`q` searches name, e-mail, phone, mobile and job title. Sales agents see "
    "contacts they own and the contacts of accounts they own.",
)
def list_contacts(
    principal: Reader,
    session: Db,
    q: str | None = Query(default=None, min_length=1, max_length=100),
    account_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    email_consent: EmailConsent | None = None,
    primary_only: bool = False,
    sort: ContactSort = "last_name",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> ContactPage:
    filters = ContactFilters(
        q=q.strip() if q else None,
        account_id=account_id,
        owner_id=owner_id,
        email_consent=email_consent,
        primary_only=primary_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    contacts, total = service.list_contacts(session, principal, filters)
    return ContactPage(
        items=[ContactRead.model_validate(c) for c in contacts],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/duplicates",
    summary="Possible duplicates before creating a contact",
    description="Matches on e-mail, phone/mobile (last 9 digits) and full name. Matches you "
    "may not see are only counted.",
)
def check_duplicates(
    principal: Reader,
    session: Db,
    email: str | None = Query(default=None, min_length=1, max_length=320),
    phone: str | None = Query(default=None, min_length=1, max_length=50),
    first_name: str | None = Query(default=None, max_length=100),
    last_name: str | None = Query(default=None, min_length=1, max_length=100),
    exclude_id: uuid.UUID | None = None,
) -> ContactDuplicateCheck:
    return service.check_duplicates(
        session,
        principal,
        email=email,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
        exclude_id=exclude_id,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a contact",
    description="Linking to an account you cannot see answers 404, like a missing account.",
    responses=problem_responses(404, 422),
)
def create_contact(
    data: ContactCreate, principal: Writer, session: Db, response: Response
) -> ContactRead:
    contact = service.create_contact(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/contacts/{contact.id}"
    return ContactRead.model_validate(contact)


@router.get("/{contact_id}", summary="Get one contact", responses=problem_responses(404))
def get_contact(contact_id: uuid.UUID, principal: Reader, session: Db) -> ContactRead:
    return ContactRead.model_validate(service.get_contact(session, principal, contact_id))


@router.patch(
    "/{contact_id}",
    summary="Change contact details, account link, preferences or consent",
    responses=problem_responses(404, 409, 422),
)
def update_contact(
    contact_id: uuid.UUID, data: ContactUpdate, principal: Writer, session: Db
) -> ContactRead:
    contact = service.update_contact(session, principal, contact_id, data)
    session.commit()
    return ContactRead.model_validate(contact)


@router.post(
    "/{contact_id}/archive",
    summary="Archive a contact (nothing is deleted)",
    responses=problem_responses(404, 409, 422),
)
def archive_contact(
    contact_id: uuid.UUID, data: ContactArchive, principal: Writer, session: Db
) -> Response:
    service.archive_contact(
        session, principal, contact_id, version=data.version, reason=data.reason
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{contact_id}/history",
    summary="Change history of the contact (newest first)",
    responses=problem_responses(404),
)
def get_history(contact_id: uuid.UUID, principal: Reader, session: Db) -> list[HistoryEntry]:
    return service.contact_history(session, principal, contact_id)
