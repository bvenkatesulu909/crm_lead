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
    # Whether the AI platform switch (CRM_AI_DISABLED) stops it. True for anything an AI acts
    # through - also an outside model (the MCP client) that we cannot meter.
    platform_switch: bool = True
    # What an organisation without a settings row gets. An outside AI client starts switched OFF.
    default_enabled: bool = True


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
            key="qualifier",
            title="Qualifier",
            description=(
                "Reads one lead and the organisation's written qualification steps and "
                "SUGGESTS what to do. It never changes a lead: every suggestion waits in the "
                "approval queue for a different person."
            ),
            owner_role="tenant_admin",
            tools=("submit_assessment",),
        ),
        AgentDef(
            key="lead_agent",
            title="Lead agent",
            description=(
                "Looks at one lead and SUGGESTS whether its status should change. It never "
                "changes a lead: every suggestion waits in the approval queue for a different "
                "person. Off until an administrator switches it on."
            ),
            owner_role="tenant_admin",
            tools=("submit_suggestion",),
            default_enabled=False,
        ),
        AgentDef(
            key="deal_desk",
            title="Deal desk",
            description=(
                "Three AI reviewers look at one deal at the same time (pricing, account, "
                "momentum) and a desk lead writes a short brief. It may SUGGEST at most two "
                "follow-up tasks; they wait in the approval queue. On for every organisation "
                "unless an administrator switches it off (owner's decision, 2026-11-08)."
            ),
            owner_role="tenant_admin",
            tools=("submit_findings", "submit_brief"),
        ),
        AgentDef(
            key="account_research",
            title="Account research",
            description=(
                "Writes a one-page brief about one account from the CRM's own records (deals, "
                "support, interactions, registry checks on file), every sentence with its source. "
                "It reads only; it proposes nothing and does not browse the web. Off until "
                "switched on."
            ),
            owner_role="tenant_admin",
            tools=("submit_account_brief",),
            default_enabled=False,
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
            platform_switch=False,
        ),
        AgentDef(
            key="company_details",
            title="Company details",
            description=(
                "Reads a lead's company website (home page and About page) and suggests its "
                "website, industry and size; the person decides what to save. No language model, "
                "nothing about the person is sent. Off until switched on."
            ),
            owner_role="tenant_admin",
            tools=(),
            uses_model=False,
            platform_switch=False,
            default_enabled=False,
        ),
        AgentDef(
            key="voice",
            title="Voice conversation",
            description=(
                "Lets staff talk to the assistant and hear its answers. The answers come from the "
                "staff assistant (its switch and budget apply too). Counts minutes of server "
                "speech; the browser's own speech is free and not counted. Off until switched on."
            ),
            owner_role="tenant_admin",
            tools=(),
            uses_model=False,
            platform_switch=False,
            default_enabled=False,
        ),
        AgentDef(
            key="mcp_client",
            title="AI clients (MCP)",
            description=(
                "Lets an outside AI client such as Claude Code or Cursor, signed in as a person, "
                "SUGGEST changes. They wait in the approval queue and a different person decides. "
                "The model is the client's, so there is no token budget. Off until switched on."
            ),
            owner_role="tenant_admin",
            tools=(),
            uses_model=False,
            default_enabled=False,
        ),
    )
}

KEY_PATTERN = r"^[a-z][a-z_]{2,39}$"
