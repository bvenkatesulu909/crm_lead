"""The real program over real stdio, as an IDE starts it (ADR 0015, D3).

Starts ``python -m crm_mcp.server`` as a child process, speaks MCP to it like a client does
(initialize, list tools) and checks the answer against the written contract. Nothing is signed in
and no CRM or Keycloak is needed: listing tools never calls either. A change that would stop
every IDE from connecting (a stray ``print`` on stdout, a crash at start-up, a tool list that no
longer matches the contract) fails here.
"""

import asyncio
import os
import sys
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from crm_mcp import catalogue

TIMEOUT = 30


def params(env: dict[str, str] | None = None) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "crm_mcp.server"],
        env={**os.environ, **(env or {})},
    )


async def _talk() -> tuple[Any, list[Any]]:
    async with stdio_client(params()) as (read, write), ClientSession(read, write) as session:
        init = await asyncio.wait_for(session.initialize(), TIMEOUT)
        tools = await asyncio.wait_for(session.list_tools(), TIMEOUT)
        return init, tools.tools


@pytest.fixture(scope="module")
def conversation() -> tuple[Any, list[Any]]:
    return asyncio.run(_talk())


def test_the_server_starts_and_introduces_itself(conversation: tuple[Any, list[Any]]) -> None:
    init, _ = conversation
    assert init.server_info.name == "crm-lead"
    assert "read-only" in (init.instructions or "").lower()


def test_the_tools_over_stdio_are_the_documented_ones(conversation: tuple[Any, list[Any]]) -> None:
    _, tools = conversation
    documented = {t["name"]: t for t in catalogue.current_catalogue()["tools"]}
    assert {t.name for t in tools} == set(documented)
    for found in tools:
        notes = found.annotations
        assert (
            notes is not None and notes.read_only_hint is True and notes.destructive_hint is False
        )


def test_the_server_offers_tools_only() -> None:
    """No resources or prompts: nothing but the documented read-only tools can be reached."""

    async def listings() -> tuple[list[Any], list[Any]]:
        async with stdio_client(params()) as (read, write), ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), TIMEOUT)
            resources = await asyncio.wait_for(session.list_resources(), TIMEOUT)
            prompts = await asyncio.wait_for(session.list_prompts(), TIMEOUT)
            return resources.resources, prompts.prompts

    assert asyncio.run(listings()) == ([], [])


def test_a_bad_setting_stops_the_server_with_a_clear_message() -> None:
    """A wrong address must fail loudly at start-up, on stderr, not hang the IDE."""

    async def start() -> int:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "crm_mcp.server",
            env={**os.environ, "CRM_MCP_API_URL": "http://crm.example.com/api/v1"},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(process.communicate(), TIMEOUT)
        assert out == b""  # stdout is the protocol channel: nothing else may appear on it
        assert b"must use https" in err
        return process.returncode or 0

    assert asyncio.run(start()) != 0
