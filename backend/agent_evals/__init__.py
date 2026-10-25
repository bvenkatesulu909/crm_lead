"""Agent evaluation harness (BP-10, docs/agent-evals.md).

Tooling that measures what the CRM's AI agents do. It lives outside ``app`` on purpose: it is
not part of the shipped application (the Docker image copies only ``app`` and ``scripts``).
"""
