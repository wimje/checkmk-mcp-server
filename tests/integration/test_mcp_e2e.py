"""End-to-end test: spawn the MCP server as a subprocess and drive it
through the real MCP client -- the full chain used by checkmk_cli_mcp.py
and Claude Desktop. This is the layer unit tests cannot cover (stdio
transport, session lifecycle, tool argument/response wrapping)."""

import os

import pytest
import yaml

from checkmk_mcp_server.config import load_config
from checkmk_mcp_server.mcp_client import CheckmkMCPClient

pytestmark = pytest.mark.integration


@pytest.fixture
def test_config_file(tmp_path, live_client):
    """Write a config file pointing at the live test site."""
    cfg = {
        "checkmk": {
            "server_url": os.environ["CHECKMK_TEST_URL"],
            "site": os.environ.get("CHECKMK_TEST_SITE", "cmk"),
            "username": os.environ.get("CHECKMK_TEST_USER", "cmk-test-admin"),
            "password": os.environ.get(
                "CHECKMK_TEST_PASSWORD", "cmk-test-admin-secret"
            ),
        }
    }
    path = tmp_path / "test-config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return str(path)


class TestMCPEndToEnd:
    async def test_connect_call_tools_disconnect(self, test_config_file):
        client = CheckmkMCPClient(load_config(test_config_file))
        await client.connect(config_file=test_config_file)
        try:
            # get_system_info: version + support status
            info = await client.call_tool("get_system_info", {})
            assert info.get("success") is True, info
            assert info.get("version_supported") is True, info

            # list_hosts: None arguments must be stripped, response unwrapped
            result = await client.call_tool(
                "list_hosts", {"search": None, "folder": None}
            )
            assert result.get("success") is True, result
            hosts = result.get("data", {}).get("hosts", [])
            names = {h.get("name") for h in hosts}
            assert "cmk-test-local" in names

            # list_host_services for the seeded host
            result = await client.call_tool(
                "list_host_services", {"host_name": "cmk-test-local"}
            )
            assert result.get("success") is True, result
        finally:
            await client.disconnect()

    async def test_reconnect_in_fresh_event_loop(self, test_config_file):
        """Each CLI command opens a fresh connection in its own loop --
        a second connect/disconnect cycle must work cleanly."""
        client = CheckmkMCPClient(load_config(test_config_file))
        await client.connect(config_file=test_config_file)
        try:
            info = await client.call_tool("get_system_info", {})
            assert info.get("success") is True
        finally:
            await client.disconnect()
