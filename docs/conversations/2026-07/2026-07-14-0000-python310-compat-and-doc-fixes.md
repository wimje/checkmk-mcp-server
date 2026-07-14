TITLE: Python 3.10 compatibility fixes and MCP CLI end-to-end repair
DATE: 2026-07-14
PARTICIPANTS: Wim Vandermeeren, Claude
SUMMARY: Started with a code-structure walkthrough, then iteratively debugged the MCP CLI from crash-on-import to fully working against a live Checkmk site. Fixed Python 3.10 startup errors (ExceptionGroup, forward references), then discovered the MCP client session was never entered — the true cause of the "macOS stdio timeout" issues previously worked around with fallback machinery. Repaired the full chain: connection lifecycle, tool argument/response handling, missing formatter methods, interactive session bugs, a stale service-container lookup, and a permissions-aware host listing fallback. Verified interactively: connect, ping, help, exit, and list all hosts all work via MCP.

INITIAL PROMPT: explain code structure

KEY DECISIONS:
- Use the `exceptiongroup` backport with stub-class fallback for Python < 3.11 rather than bumping the minimum Python version
- Enter/exit `ClientSession` and the stdio context properly, in the same task, rather than keeping timeout-based workarounds; removed the 2s "macOS startup" sleep
- Open a fresh MCP connection per CLI subcommand (each runs in its own asyncio.run loop) via the async_command decorator, keeping the group-callback connection as a probe/fallback trigger
- Exit the process after a successful direct-CLI fallback so click doesn't invoke MCP subcommands with an uninitialized context
- Unwrap the server's double-serialized CallToolResult dict client-side rather than changing the server's SDK-bug workaround (Claude Desktop depends on current behavior)
- Strip None values from tool arguments client-side to satisfy server input schemas
- Fall back to the monitoring endpoint for host listing when host_config is empty/403, mapping results to the config response shape (folder unknown, "/")

FILES CHANGED:
- mcp_checkmk_server.py: ExceptionGroup/BaseExceptionGroup shim for Python < 3.11; terminal-run guard returns instead of sys.exit(0)
- checkmk_mcp_server/cli_mcp.py: future annotations fix; per-command MCP connections in async_command; direct __aenter__ (no wait_for); sys.exit(0) after fallback paths; MCPCLIContext carries config_file
- checkmk_mcp_server/mcp_client.py: enter/exit ClientSession properly; in-task cleanup of partial connections; removed startup sleep and bogus server_info log; ping only fails on explicit error; call_tool strips None args and unwraps double-serialized responses; disconnect simplified
- checkmk_mcp_server/formatters/cli_formatter.py: added format_header/info/success/warning/prompt/help, format_host_details, format_acknowledge_result, format_downtime_result, format_discovery_result, format_problem_summary, format_host_analysis, and a generic dict renderer
- checkmk_mcp_server/interactive/mcp_session.py: local structured/natural-language classification (replaces incompatible CommandParser.parse call); add_history and show_help method fixes; removed nonexistent load_history call
- checkmk_mcp_server/mcp_server/tools/advanced/tools.py: get_system_info uses the service container's async_client instead of removed server.checkmk_client
- checkmk_mcp_server/api_client.py: list_hosts falls back to the monitoring endpoint on empty/403 host_config responses (new _list_hosts_via_monitoring)
- docs/getting-started.md: corrected connection-test snippet; replaced stale checkmk_llm_agent paths
- docs/troubleshooting.md: entries for the NameErrors and CheckmkAPIClient import mistake; stale path fix
- CLAUDE.md: "Recently Completed" entries for both fix batches
