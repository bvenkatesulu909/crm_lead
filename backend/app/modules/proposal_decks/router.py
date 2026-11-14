"""Proposal deck endpoints (ADR 0032, PD3): staff ask for a deck of a quote and download it, and a
portal customer downloads the deck of a quote they can see. Thin: gate, call the service, commit."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.core.storage import FileStore, get_file_store
from app.modules.identity.api import require_any_permission
from app.modules.proposal_decks import service
from app.modules.proposal_decks.schemas import DeckLinkRead, DeckStatusRead

Db = Annotated[Session, Depends(get_db_session)]
Files = Annotated[FileStore, Depends(get_file_store)]

router = APIRouter(prefix="/quotes", tags=["proposal-decks"], responses=problem_responses(401, 403))
portal_router = APIRouter(
    prefix="/portal/quotes", tags=["portal"], responses=problem_responses(401, 403)
)
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.QUOTE_READ_ALL, Permission.QUOTE_READ_OWN)),
]
Writer = Annotated[
    Principal,
    Depends(require_any_permission(Permission.QUOTE_WRITE_ALL, Permission.QUOTE_WRITE_OWN)),
]
Customer = Annotated[Principal, Depends(require_any_permission(Permission.PORTAL_QUOTE_READ))]


def _read(state: service.DeckState) -> DeckStatusRead:
    return DeckStatusRead(
        status=state.state,
        reason=state.reason,
        file_name=state.file_name,
        size_bytes=state.size_bytes,
        created_at=state.created_at,
        refresh_failed=state.refresh_failed,
    )


@router.post(
    "/{quote_id}/deck",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a branded proposal deck of an approved quote (made in the background)",
    description="No body. The deck is drawn from the quote and the organisation's branding as they "
    "are when the worker runs; the same content gives the same file.",
    responses=problem_responses(404, 409, 429),
)
def create_deck(
    quote_id: uuid.UUID, request: Request, principal: Writer, session: Db
) -> DeckStatusRead:
    settings: Settings = request.app.state.settings
    state = service.request_deck(session, principal, quote_id, settings)
    session.commit()
    return _read(state)


@router.get(
    "/{quote_id}/deck",
    summary="Where the quote's proposal deck stands",
    responses=problem_responses(404),
)
def deck_status(quote_id: uuid.UUID, principal: Reader, session: Db) -> DeckStatusRead:
    return _read(service.deck_state(session, principal, quote_id, customer=False))


@router.get(
    "/{quote_id}/deck/link",
    summary="A 60-second link to the newest proposal deck (ADR 0025)",
    responses=problem_responses(404),
)
def deck_link(quote_id: uuid.UUID, principal: Reader, session: Db, files: Files) -> DeckLinkRead:
    link = service.deck_link(session, principal, files, quote_id, customer=False)
    return DeckLinkRead(url=link.url, file_name=link.file_name, expires_at=link.expires_at)


@portal_router.get(
    "/{quote_id}/deck",
    summary="Whether the deck of one of my quotes is ready",
    responses=problem_responses(404),
)
def my_deck_status(quote_id: uuid.UUID, principal: Customer, session: Db) -> DeckStatusRead:
    return _read(service.deck_state(session, principal, quote_id, customer=True))


@portal_router.get(
    "/{quote_id}/deck/link",
    summary="A 60-second link to the deck of one of my quotes (ADR 0025)",
    responses=problem_responses(404),
)
def my_deck_link(
    quote_id: uuid.UUID, principal: Customer, session: Db, files: Files
) -> DeckLinkRead:
    link = service.deck_link(session, principal, files, quote_id, customer=True)
    return DeckLinkRead(url=link.url, file_name=link.file_name, expires_at=link.expires_at)
