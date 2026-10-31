"""The CRM's AI agents (ADR 0016, decision 1).

An AI feature that calls a language model must be listed here: the list is what the registry
page shows, what a budget applies to and what the tool filter narrows. The organisation's own
settings (on/off, budget, fewer tools) live in the database; this file is only the fixed part.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDef:
    key: str
    title: str
    description: str
    # The role accountable for the agent in an organisation (who is asked when it misbehaves).
    owner_role: str
    # Every tool the code gives this agent. An organisation can only remove tools, never add.
    tools: tuple[str, ...]
    # False for a feature that is governed like an agent (switch, usage) but calls no language
    # model: it has no token budget and the AI platform switch does not apply to it.
    uses_model: bool = True


AGENTS: dict[str, AgentDef] = {
    agent.key: agent
    for agent in (
        AgentDef(
            key="staff_assistant",
            title="Staff assistant",
            description="Answers staff questions about leads and proposes changes for approval.",
            owner_role="tenant_admin",
            tools=(
                "get_account",
                "get_ticket",
                "list_account_contacts",
                "propose_follow_up_task",
                "propose_lead_assignment",
                "propose_lead_status",
                "check_rera",
                "search_accounts",
                "search_leads",
            ),
        ),
        AgentDef(
            key="portal_assistant",
            title="Customer portal assistant",
            description="Helps signed-in customers with their orders, invoices and tickets.",
            owner_role="tenant_admin",
            tools=(
                "get_invoice",
                "get_my_quote",
                "get_order",
                "get_ticket",
                "list_invoices",
                "list_my_accounts",
                "list_my_contacts",
                "list_my_quotes",
                "list_orders",
                "list_products",
                "list_tickets",
                "propose_support_ticket",
                "search_help_articles",
            ),
        ),
        AgentDef(
            key="public_chat",
            title="Website chat",
            description="Talks to anonymous website visitors and saves a lead on request.",
            owner_role="tenant_admin",
            tools=("save_lead",),
        ),
        AgentDef(
            key="knowledge_answers",
            title="Knowledge answers",
            description="Answers questions from the knowledge base, always with sources.",
            owner_role="tenant_admin",
            tools=(),
        ),
        AgentDef(
            key="web_check",
            title="Web check",
            description=(
                "Looks up a RERA number or a company on a public registry and keeps the result "
                "as evidence. It uses no language model: usage counts checks, not tokens."
            ),
            owner_role="tenant_admin",
            tools=(),
            uses_model=False,
        ),
    )
}

KEY_PATTERN = r"^[a-z][a-z_]{2,39}$"
