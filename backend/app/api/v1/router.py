"""Collects every v1 route. Each new module adds its router here."""

from fastapi import APIRouter

from app.api.v1 import health, internal
from app.modules.accounts.router import router as accounts_router
from app.modules.activities.router import router as activities_router
from app.modules.agents.router import router as agents_router
from app.modules.approvals.router import router as approvals_router
from app.modules.assistant.router import router as assistant_router
from app.modules.assistant.staff_router import router as staff_assistant_router
from app.modules.catalog.router import router as catalog_router
from app.modules.communications.router import router as communications_router
from app.modules.contacts.router import router as contacts_router
from app.modules.contracts.router import router as contracts_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.documents.router import portal_router as portal_documents_router
from app.modules.documents.router import router as documents_router
from app.modules.identity.onboarding_router import (
    onboarding_router,
    platform_router,
    portal_access_router,
    tenant_router,
)
from app.modules.identity.router import router as identity_router
from app.modules.invoices.router import portal_router as portal_invoices_router
from app.modules.invoices.router import router as invoices_router
from app.modules.knowledge.router import portal_router as portal_knowledge_router
from app.modules.knowledge.router import router as knowledge_router
from app.modules.leads.router import router as leads_router
from app.modules.notifications.router import router as notifications_router
from app.modules.orders.router import portal_router as portal_orders_router
from app.modules.orders.router import router as orders_router
from app.modules.portal.router import router as portal_router
from app.modules.public_chat.router import router as public_chat_router
from app.modules.public_chat.router import staff_router as public_chat_staff_router
from app.modules.quotes.router import portal_router as portal_quotes_router
from app.modules.quotes.router import router as quotes_router
from app.modules.relationships.router import router as relationships_router
from app.modules.reports.router import router as reports_router
from app.modules.sales.router import router as opportunities_router
from app.modules.support.router import portal_router as portal_tickets_router
from app.modules.support.router import router as tickets_router
from app.modules.voice.router import router as voice_router
from app.modules.webcheck.router import router as webcheck_router
from app.modules.workflows.router import router as workflows_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(internal.router)
api_router.include_router(identity_router)
api_router.include_router(relationships_router)
api_router.include_router(accounts_router)
api_router.include_router(contacts_router)
api_router.include_router(opportunities_router)
api_router.include_router(activities_router)
api_router.include_router(catalog_router)
api_router.include_router(quotes_router)
api_router.include_router(portal_quotes_router)
api_router.include_router(contracts_router)
api_router.include_router(documents_router)
api_router.include_router(portal_documents_router)
api_router.include_router(notifications_router)
api_router.include_router(communications_router)
api_router.include_router(public_chat_router)
api_router.include_router(public_chat_staff_router)
api_router.include_router(approvals_router)
api_router.include_router(agents_router)
api_router.include_router(webcheck_router)
api_router.include_router(workflows_router)
api_router.include_router(reports_router)
api_router.include_router(leads_router)
api_router.include_router(portal_router)
api_router.include_router(tickets_router)
api_router.include_router(portal_tickets_router)
api_router.include_router(orders_router)
api_router.include_router(portal_orders_router)
api_router.include_router(invoices_router)
api_router.include_router(knowledge_router)
api_router.include_router(portal_knowledge_router)
api_router.include_router(portal_invoices_router)
api_router.include_router(tenant_router)
api_router.include_router(portal_access_router)
api_router.include_router(onboarding_router)
api_router.include_router(platform_router)
api_router.include_router(assistant_router)
api_router.include_router(staff_assistant_router)
api_router.include_router(dashboard_router)
api_router.include_router(voice_router)
