"""Staff ticket endpoints (/api/v1/tickets) and customer-portal ticket endpoints
(/api/v1/portal/tickets). Thin: permission gate, call the service, commit once."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.knowledge import api as knowledge_api
from app.modules.support import service
from app.modules.support.repository import TicketFilters
from app.modules.support.schemas import (
    CommentCreate,
    CommentRead,
    KnowledgeDraftSource,
    PortalCommentCreate,
    PortalCommentRead,
    PortalTicketCreate,
    PortalTicketRead,
    TicketAssign,
    TicketCategory,
    TicketCreate,
    TicketKnowledgeDraft,
    TicketPage,
    TicketPriority,
    TicketRating,
    TicketRead,
    TicketSort,
    TicketStatus,
    TicketStatusChange,
    TicketUpdate,
)

Db = Annotated[Session, Depends(get_db_session)]
TicketId = Annotated[uuid.UUID, "Ticket ID"]

# --- staff --------------------------------------------------------------------------------

router = APIRouter(prefix="/tickets", tags=["tickets"], responses=problem_responses(401, 403))
can_read = require_any_permission(Permission.TICKET_READ_ALL, Permission.TICKET_READ_OWN_ACCOUNTS)
can_manage = require_any_permission(Permission.TICKET_MANAGE)
Reader = Annotated[Principal, Depends(can_read)]
Manager = Annotated[Principal, Depends(can_manage)]


@router.get(
    "",
    summary="List and search support tickets",
    description="`q` matches the subject or the ticket number (e.g. `T-12`). `overdue=true` keeps "
    "open tickets past an SLA deadline. Only tickets you may see are returned and counted.",
    responses=problem_responses(422),
)
def list_tickets(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    ticket_status: Annotated[list[TicketStatus] | None, Query(alias="status")] = None,
    priority: TicketPriority | None = None,
    category: TicketCategory | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    account_id: uuid.UUID | None = None,
    overdue: bool = False,
    sort: TicketSort = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> TicketPage:
    filters = TicketFilters(
        q=q.strip() if q else None,
        statuses=tuple(ticket_status or ()),
        priority=priority,
        category=category,
        assignee_id=assignee_id,
        unassigned=unassigned,
        account_id=account_id,
        overdue=overdue,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items, total = service.list_tickets(session, principal, filters)
    return TicketPage(
        items=[service.to_staff_view(t) for t in items], total=total, limit=limit, offset=offset
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a ticket for a customer account (staff)",
    responses=problem_responses(404, 422),
)
def create_ticket(
    data: TicketCreate, principal: Manager, session: Db, response: Response
) -> TicketRead:
    ticket = service.create_staff_ticket(
        session,
        principal,
        account_id=data.account_id,
        subject=data.subject,
        description=data.description,
        priority=data.priority,
        category=data.category,
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/tickets/{ticket.id}"
    return service.to_staff_view(ticket)


@router.get("/{ticket_id}", summary="Get one ticket", responses=problem_responses(404))
def get_ticket(ticket_id: TicketId, principal: Reader, session: Db) -> TicketRead:
    return service.to_staff_view(service.get_ticket(session, principal, ticket_id))


@router.post(
    "/{ticket_id}/knowledge-draft",
    summary="Draft a customer reply from the knowledge base (customer-visible scope)",
    responses=problem_responses(404, 503),
)
def ticket_knowledge_draft(
    ticket_id: TicketId,
    principal: Reader,
    session: Db,
    request: Request,
) -> TicketKnowledgeDraft:
    ticket = service.get_ticket(session, principal, ticket_id)
    outcome = knowledge_api.answer_customer_scope(
        session,
        principal,
        question=f"{ticket.subject}\n\n{ticket.description}",
        account_ids=[ticket.account_id],
        settings=request.app.state.settings,
        embedder=request.app.state.embedder,
        chat_model=request.app.state.chat_model,
        reranker=request.app.state.reranker,
    )
    return TicketKnowledgeDraft(
        draft=outcome.answer,
        sources=[
            KnowledgeDraftSource(
                document_title=source.document_title,
                heading_path=source.heading_path,
                page_from=source.page_from,
                page_to=source.page_to,
                text=source.text,
            )
            for source in outcome.sources
        ],
        enough=outcome.enough,
        grounded=outcome.grounded,
    )


@router.patch(
    "/{ticket_id}",
    summary="Change the priority (recalculates SLA deadlines) and/or the category",
    responses=problem_responses(404, 409, 422),
)
def update_ticket(
    ticket_id: TicketId, data: TicketUpdate, principal: Manager, session: Db
) -> TicketRead:
    ticket = service.update_ticket(
        session,
        principal,
        ticket_id,
        data.version,
        priority=data.priority,
        category=data.category,
    )
    session.commit()
    return service.to_staff_view(ticket)


@router.post(
    "/{ticket_id}/status",
    summary="Change the status",
    description="new→open|pending_customer|resolved|closed, open→pending_customer|resolved|closed, "
    "pending_customer→open|resolved|closed, resolved→open|closed. Closed is final.",
    responses=problem_responses(404, 409, 422),
)
def change_status(
    ticket_id: TicketId, data: TicketStatusChange, principal: Manager, session: Db
) -> TicketRead:
    ticket = service.change_status(session, principal, ticket_id, data.status, data.reason)
    session.commit()
    return service.to_staff_view(ticket)


@router.post(
    "/{ticket_id}/assign",
    summary="Assign to a support employee",
    responses=problem_responses(404, 409, 422),
)
def assign_ticket(
    ticket_id: TicketId, data: TicketAssign, principal: Manager, session: Db
) -> TicketRead:
    ticket = service.assign(session, principal, ticket_id, data.assignee_id)
    session.commit()
    return service.to_staff_view(ticket)


@router.get(
    "/{ticket_id}/comments",
    summary="Conversation including internal notes (staff)",
    responses=problem_responses(404),
)
def staff_comments(ticket_id: TicketId, principal: Reader, session: Db) -> list[CommentRead]:
    return service.staff_comments(session, principal, ticket_id)


@router.post(
    "/{ticket_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Reply to the customer (public) or add an internal note",
    description="The first public reply records the first-response time for the SLA.",
    responses=problem_responses(404, 409, 422),
)
def add_staff_comment(
    ticket_id: TicketId, data: CommentCreate, principal: Manager, session: Db
) -> dict[str, str]:
    comment = service.add_staff_comment(session, principal, ticket_id, data.body, data.visibility)
    session.commit()
    return {"id": str(comment.id)}


# --- customer portal ----------------------------------------------------------------------

portal_router = APIRouter(
    prefix="/portal/tickets", tags=["portal"], responses=problem_responses(401, 403)
)
is_portal_reader = require_any_permission(Permission.PORTAL_TICKET_READ)
is_portal_writer = require_any_permission(Permission.PORTAL_TICKET_WRITE)
Customer = Annotated[Principal, Depends(is_portal_reader)]
CustomerWriter = Annotated[Principal, Depends(is_portal_writer)]


@portal_router.get("", summary="My company's tickets")
def my_tickets(
    principal: Customer,
    session: Db,
    account_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[PortalTicketRead]:
    filters = TicketFilters(account_id=account_id, limit=limit, offset=offset)
    items, _ = service.list_tickets(session, principal, filters)
    return [service.to_portal_view(t) for t in items]


@portal_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Open a ticket for one of my accounts",
    responses=problem_responses(404, 422),
)
def open_ticket(
    data: PortalTicketCreate, principal: CustomerWriter, session: Db
) -> PortalTicketRead:
    ticket = service.create_customer_ticket(
        session,
        principal,
        account_id=data.account_id,
        subject=data.subject,
        description=data.description,
        category=data.category,
    )
    session.commit()
    return service.to_portal_view(ticket)


@portal_router.post(
    "/{ticket_id}/rating",
    summary="Rate how a resolved ticket was handled (once, 1-5)",
    responses=problem_responses(404, 409, 422),
)
def rate_ticket(
    ticket_id: TicketId, data: TicketRating, principal: CustomerWriter, session: Db
) -> PortalTicketRead:
    ticket = service.rate_ticket(
        session, principal, ticket_id, rating=data.rating, comment=data.comment
    )
    session.commit()
    return service.to_portal_view(ticket)


@portal_router.get("/{ticket_id}", summary="One of my tickets", responses=problem_responses(404))
def my_ticket(ticket_id: TicketId, principal: Customer, session: Db) -> PortalTicketRead:
    return service.to_portal_view(service.get_ticket(session, principal, ticket_id))


@portal_router.get(
    "/{ticket_id}/comments",
    summary="Conversation (public replies only)",
    responses=problem_responses(404),
)
def my_ticket_comments(
    ticket_id: TicketId, principal: Customer, session: Db
) -> list[PortalCommentRead]:
    return service.portal_comments(session, principal, ticket_id)


@portal_router.post(
    "/{ticket_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Reply on my ticket (re-opens it if it was waiting for me or resolved)",
    responses=problem_responses(404, 409, 422),
)
def reply_to_ticket(
    ticket_id: TicketId, data: PortalCommentCreate, principal: CustomerWriter, session: Db
) -> dict[str, str]:
    comment = service.add_customer_comment(session, principal, ticket_id, data.body)
    session.commit()
    return {"id": str(comment.id)}
