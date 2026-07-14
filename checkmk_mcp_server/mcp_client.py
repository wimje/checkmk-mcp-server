"""MCP Client wrapper for Checkmk CLI integration."""

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import AppConfig
from .services.models.hosts import HostInfo, HostListResult
from .services.models.services import ServiceInfo, ServiceListResult, ServiceState
from .services.models.status import HealthDashboard, ProblemSummary


logger = logging.getLogger(__name__)


class CheckmkMCPClient:
    """MCP Client wrapper for interacting with Checkmk MCP Server."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self._server_process: Optional[subprocess.Popen] = None
        self._stdio_context = None
        self._read_stream = None
        self._write_stream = None

    async def connect(
        self, server_path: Optional[str] = None, config_file: Optional[str] = None
    ) -> None:
        """Connect to the MCP server."""
        if self.session:
            logger.warning("Already connected to MCP server")
            return

        try:
            # Determine server path
            if not server_path:
                # Default to the MCP server in the project root
                project_root = Path(__file__).parent.parent
                server_path = str(project_root / "mcp_checkmk_server.py")

            # Ensure server path exists
            if not Path(server_path).exists():
                raise FileNotFoundError(f"MCP server not found at: {server_path}")

            logger.info(f"Connecting to MCP server at: {server_path}")

            # Create server parameters
            args = [server_path]
            if config_file:
                args.extend(["--config", config_file])

            server_params = StdioServerParameters(
                command=sys.executable,
                args=args,
                env={
                    "PYTHONPATH": str(Path(__file__).parent.parent),
                    "PYTHONUNBUFFERED": "1",  # Force unbuffered Python output
                    "PYTHONIOENCODING": "utf-8",  # Ensure consistent encoding
                    **dict(os.environ),
                },
            )

            # Connect to the server with improved error handling
            self._stdio_context = stdio_client(server_params)
            self._read_stream, self._write_stream = (
                await self._stdio_context.__aenter__()
            )

            # Create the session and enter its context. Entering the session
            # (__aenter__) starts the background receive loop -- without it
            # the session never reads responses from the server and
            # initialize() times out.
            self.session = ClientSession(self._read_stream, self._write_stream)
            await self.session.__aenter__()

            # Use a more aggressive approach for macOS - try immediate initialization
            # without timeout to see if the issue is timeout-related
            logger.info("Attempting MCP session initialization...")
            try:
                # First try without timeout to diagnose the issue
                init_task = asyncio.create_task(self.session.initialize())
                
                # Wait a bit and check if it completes quickly
                try:
                    await asyncio.wait_for(init_task, timeout=5.0)
                    logger.info("Session initialized successfully (fast path)")
                except asyncio.TimeoutError:
                    logger.info("Fast initialization failed, trying patient approach...")
                    # Cancel the fast attempt
                    init_task.cancel()
                    try:
                        await init_task
                    except asyncio.CancelledError:
                        pass
                    
                    # Try again with longer timeout and different approach
                    await asyncio.sleep(1.0)
                    await asyncio.wait_for(self.session.initialize(), timeout=60.0)
                
                logger.info("Successfully connected to MCP server")
                
                # Verify connection with a simple ping test
                try:
                    # Tool responses aren't guaranteed to carry a "success"
                    # key; only treat an explicit error as a failed ping.
                    ping_result = await self.call_tool("get_system_info", {})
                    if ping_result.get("error"):
                        logger.warning(
                            f"MCP connection established but ping test failed: "
                            f"{ping_result['error']}"
                        )
                    else:
                        logger.info("MCP connection verified with system info ping")
                except Exception as ping_error:
                    logger.warning(f"MCP connection ping test failed: {ping_error}")
                
            except Exception as e:
                # Handle any remaining initialization errors
                if "timeout" in str(e).lower():
                    raise RuntimeError(
                        f"MCP session initialization timed out. "
                        "This may be due to MCP SDK stdio communication issues on macOS."
                    )
                else:
                    raise RuntimeError(f"MCP session initialization failed: {e}")

        except BaseException as e:
            # Clean up the partially-opened stdio context *in this task* --
            # anyio cancel scopes must be exited in the task that entered them.
            # Leaving it open leaks an async generator that asyncio closes at
            # loop shutdown, producing "Attempted to exit cancel scope in a
            # different task" tracebacks.
            await self._cleanup_connection_state()
            if isinstance(e, asyncio.CancelledError):
                raise
            logger.exception("Failed to connect to MCP server")
            raise RuntimeError(f"MCP connection failed: {str(e)}")

    async def _cleanup_connection_state(self) -> None:
        """Close the session and stdio context (if open) and reset state."""
        if self.session is not None:
            try:
                await self.session.__aexit__(None, None, None)
            except BaseException as cleanup_error:
                logger.debug(f"Error closing MCP session: {cleanup_error}")
            finally:
                self.session = None
        if self._stdio_context is not None:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except BaseException as cleanup_error:
                logger.debug(f"Error closing stdio context: {cleanup_error}")
            finally:
                self._stdio_context = None
                self._read_stream = None
                self._write_stream = None

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        was_connected = self.session is not None
        await self._cleanup_connection_state()
        if was_connected:
            logger.info("Disconnected from MCP server")

        if self._server_process:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"Error terminating server process: {e}")
            finally:
                self._server_process = None

    def _ensure_connected(self) -> None:
        """Ensure we're connected to the MCP server."""
        if not self.session:
            raise RuntimeError("Not connected to MCP server. Call connect() first.")

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call an MCP tool and return the result."""
        self._ensure_connected()

        # Omit None values: unset optional parameters must be absent, not
        # null, or the server's input schema validation rejects the call
        # ("None is not of type 'string'").
        arguments = {k: v for k, v in arguments.items() if v is not None}

        try:
            result = await self.session.call_tool(tool_name, arguments)

            # Parse the result based on the expected format
            if hasattr(result, "content"):
                # Handle different content types
                if hasattr(result.content[0], "text"):
                    # TextContent
                    response_text = result.content[0].text
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError:
                        return {
                            "success": False,
                            "error": f"Invalid JSON response: {response_text}",
                        }
                    # The server returns a raw CallToolResult-shaped dict (an
                    # MCP SDK bug workaround), which the SDK serializes again
                    # as text content. Unwrap to get the actual tool payload.
                    if (
                        isinstance(data, dict)
                        and "isError" in data
                        and isinstance(data.get("content"), list)
                    ):
                        try:
                            data = json.loads(data["content"][0]["text"])
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            pass
                    return data
                else:
                    return {"success": False, "error": "Unexpected content type"}
            else:
                return {"success": False, "error": "No content in response"}

        except Exception as e:
            logger.exception(f"Error calling tool {tool_name}")
            return {"success": False, "error": str(e)}

    async def get_resource(self, uri: str) -> Dict[str, Any]:
        """Get an MCP resource."""
        self._ensure_connected()

        try:
            result = await self.session.read_resource(uri)

            # Parse the resource content
            if hasattr(result, "contents"):
                for content in result.contents:
                    if hasattr(content, "text"):
                        try:
                            return json.loads(content.text)
                        except json.JSONDecodeError:
                            return {
                                "error": f"Invalid JSON in resource: {content.text}"
                            }

            return {"error": "No content in resource"}

        except Exception as e:
            logger.exception(f"Error reading resource {uri}")
            return {"error": str(e)}

    async def get_prompt(self, prompt_name: str, arguments: Dict[str, str]) -> str:
        """Get an MCP prompt."""
        self._ensure_connected()

        try:
            result = await self.session.get_prompt(prompt_name, arguments)

            # Extract the prompt text
            if hasattr(result, "messages") and result.messages:
                message = result.messages[0]
                if hasattr(message, "content") and hasattr(message.content, "text"):
                    return message.content.text

            return f"Error: Could not extract prompt text for {prompt_name}"

        except Exception as e:
            logger.exception(f"Error getting prompt {prompt_name}")
            return f"Error getting prompt: {str(e)}"

    # High-level convenience methods that wrap MCP tool calls

    async def list_hosts(self, **kwargs) -> Dict[str, Any]:
        """List hosts using MCP."""
        return await self.call_tool("list_hosts", kwargs)

    async def create_host(self, **kwargs) -> Dict[str, Any]:
        """Create a host using MCP."""
        return await self.call_tool("create_host", kwargs)

    async def get_host(self, **kwargs) -> Dict[str, Any]:
        """Get host details using MCP."""
        return await self.call_tool("get_host", kwargs)

    async def update_host(self, **kwargs) -> Dict[str, Any]:
        """Update a host using MCP."""
        return await self.call_tool("update_host", kwargs)

    async def delete_host(self, **kwargs) -> Dict[str, Any]:
        """Delete a host using MCP."""
        return await self.call_tool("delete_host", kwargs)

    async def list_host_services(self, **kwargs) -> Dict[str, Any]:
        """List services for a host using MCP."""
        return await self.call_tool("list_host_services", kwargs)

    async def list_all_services(self, **kwargs) -> Dict[str, Any]:
        """List all services using MCP."""
        return await self.call_tool("list_all_services", kwargs)

    async def get_service_status(self, **kwargs) -> Dict[str, Any]:
        """Get service status using MCP."""
        return await self.call_tool("get_service_status", kwargs)

    async def acknowledge_service_problem(self, **kwargs) -> Dict[str, Any]:
        """Acknowledge a service problem using MCP."""
        return await self.call_tool("acknowledge_service_problem", kwargs)

    async def create_service_downtime(self, **kwargs) -> Dict[str, Any]:
        """Create service downtime using MCP."""
        return await self.call_tool("create_service_downtime", kwargs)

    async def discover_services(self, **kwargs) -> Dict[str, Any]:
        """Discover services using MCP."""
        return await self.call_tool("discover_services", kwargs)

    async def get_health_dashboard(self, **kwargs) -> Dict[str, Any]:
        """Get health dashboard using MCP."""
        return await self.call_tool("get_health_dashboard", kwargs)

    async def get_host_problems(self, **kwargs) -> Dict[str, Any]:
        """Get host problems using MCP."""
        return await self.call_tool("get_host_problems", kwargs)

    async def get_critical_problems(self, **kwargs) -> Dict[str, Any]:
        """Get critical problems using MCP."""
        return await self.call_tool("get_critical_problems", kwargs)

    async def analyze_host_health(self, **kwargs) -> Dict[str, Any]:
        """Analyze host health using MCP."""
        return await self.call_tool("analyze_host_health", kwargs)

    async def get_effective_parameters(self, **kwargs) -> Dict[str, Any]:
        """Get effective parameters using MCP."""
        return await self.call_tool("get_effective_parameters", kwargs)

    async def set_service_parameters(self, **kwargs) -> Dict[str, Any]:
        """Set service parameters using MCP."""
        return await self.call_tool("set_service_parameters", kwargs)

    # Resource access methods

    async def get_live_dashboard(self) -> Dict[str, Any]:
        """Get live health dashboard from MCP resource."""
        return await self.get_resource("checkmk://dashboard/health")

    async def get_live_problems(self) -> Dict[str, Any]:
        """Get live critical problems from MCP resource."""
        return await self.get_resource("checkmk://dashboard/problems")

    async def get_live_host_status(self) -> Dict[str, Any]:
        """Get live host status from MCP resource."""
        return await self.get_resource("checkmk://hosts/status")

    async def get_live_service_problems(self) -> Dict[str, Any]:
        """Get live service problems from MCP resource."""
        return await self.get_resource("checkmk://services/problems")

    async def get_live_metrics(self) -> Dict[str, Any]:
        """Get live performance metrics from MCP resource."""
        return await self.get_resource("checkmk://metrics/performance")

    # Prompt methods

    async def get_host_analysis_prompt(
        self, host_name: str, include_grade: bool = True
    ) -> str:
        """Get AI prompt for host health analysis."""
        return await self.get_prompt(
            "analyze_host_health",
            {"host_name": host_name, "include_grade": str(include_grade).lower()},
        )

    async def get_service_troubleshooting_prompt(
        self, host_name: str, service_name: str
    ) -> str:
        """Get AI prompt for service troubleshooting."""
        return await self.get_prompt(
            "troubleshoot_service",
            {"host_name": host_name, "service_name": service_name},
        )

    async def get_infrastructure_overview_prompt(
        self, time_range_hours: int = 24
    ) -> str:
        """Get AI prompt for infrastructure overview."""
        return await self.get_prompt(
            "infrastructure_overview", {"time_range_hours": str(time_range_hours)}
        )

    async def get_parameter_optimization_prompt(
        self, host_name: str, service_name: str
    ) -> str:
        """Get AI prompt for parameter optimization."""
        return await self.get_prompt(
            "optimize_parameters",
            {"host_name": host_name, "service_name": service_name},
        )


class AsyncContextManager:
    """Async context manager for MCP client connections."""

    def __init__(self, client: CheckmkMCPClient):
        self.client = client

    async def __aenter__(self):
        config_file = getattr(self.client, "_config_file", None)
        await self.client.connect(config_file=config_file)
        return self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.disconnect()


def create_mcp_client(
    config: AppConfig, config_file: Optional[str] = None
) -> AsyncContextManager:
    """Create an MCP client with context manager support."""
    client = CheckmkMCPClient(config)
    client._config_file = config_file  # Store for later use in connect
    return AsyncContextManager(client)
