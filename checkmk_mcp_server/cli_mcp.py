"""CLI implementation using MCP client backend."""

from __future__ import annotations

import asyncio
import logging
import sys
from functools import wraps
from typing import Optional, Dict, Any, List, Callable, Awaitable, Union

import click

from .config import AppConfig, load_config
from .mcp_client import create_mcp_client, CheckmkMCPClient
from .formatters import CLIFormatter
from .logging_utils import setup_logging

# Import request tracking utilities
try:
    from .utils.request_context import generate_request_id, set_request_id
    from .middleware.request_tracking import track_request, with_request_tracking
except ImportError:
    # Fallback for cases where request tracking is not available
    def generate_request_id() -> str:
        return "req_unknown"

    def set_request_id(request_id: str) -> None:
        pass

    def track_request(**kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func
        return decorator

    def with_request_tracking(**kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func
        return decorator


logger = logging.getLogger(__name__)


def _validate_context_and_input(
    ctx_obj: Optional[MCPCLIContext], 
    **validations: Optional[str]
) -> None:
    """Helper function to validate CLI context and input parameters.
    
    Args:
        ctx_obj: The MCP CLI context object
        **validations: Named parameters to validate (name=value pairs)
        
    Raises:
        SystemExit: If validation fails
    """
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    for param_name, param_value in validations.items():
        if param_value is not None and (not param_value or not param_value.strip()):
            click.echo(ctx_obj.formatter.format_error(f"{param_name.replace('_', ' ').title()} cannot be empty"))
            sys.exit(1)


def _handle_api_result(
    result: Optional[Dict[str, Any]], 
    ctx_obj: MCPCLIContext, 
    operation_name: str,
    success_msg: Optional[str] = None,
    format_func: Optional[Callable[[Dict[str, Any]], str]] = None,
    no_data_msg: Optional[str] = None
) -> None:
    """Helper function to handle API results consistently.
    
    Args:
        result: API result dictionary
        ctx_obj: CLI context for formatting
        operation_name: Name of the operation for error messages
        success_msg: Optional success message
        format_func: Optional function to format successful data
        no_data_msg: Message when no data is returned
    """
    if result and result.get("success"):
        data = result.get("data", {})
        if data:
            if format_func:
                click.echo(format_func(data))
            if success_msg:
                click.echo(ctx_obj.formatter.format_success(success_msg))
        else:
            message = no_data_msg or f"No data available for {operation_name}"
            click.echo(ctx_obj.formatter.format_info(message))
    else:
        error_msg = result.get('error', 'Unknown error') if result else 'No response received'
        click.echo(ctx_obj.formatter.format_error(f"Failed to {operation_name}: {error_msg}"))
        sys.exit(1)


class MCPCLIContext:
    """Context object for MCP-based CLI commands."""

    def __init__(
        self,
        config: AppConfig,
        mcp_client: CheckmkMCPClient,
        formatter: CLIFormatter,
        config_file: Optional[str] = None,
    ) -> None:
        self.config = config
        self.mcp_client = mcp_client
        self.formatter = formatter
        self.config_file = config_file


def async_command(f: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
    """Decorator to run async commands in the event loop.

    Each command runs in its own asyncio.run() event loop, so an MCP
    connection opened in the group callback's loop is unusable here (its
    stdio reader/writer tasks died with that loop). If the command receives
    an MCPCLIContext, open a fresh connection for the lifetime of the
    command in this loop.
    """

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx_obj = next((a for a in args if isinstance(a, MCPCLIContext)), None)

        async def runner() -> Any:
            if ctx_obj is None:
                return await f(*args, **kwargs)
            async with create_mcp_client(ctx_obj.config, ctx_obj.config_file) as client:
                ctx_obj.mcp_client = client
                return await f(*args, **kwargs)

        return asyncio.run(runner())

    return wrapper


@click.group()
@click.option(
    "--config", "-c", type=click.Path(exists=True), help="Path to configuration file"
)
@click.option(
    "--log-level",
    "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Set the logging level",
)
@click.option("--request-id", help="Specific request ID to use for tracing (optional)")
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--force-direct", is_flag=True, help="Force direct CLI mode (bypass MCP)", hidden=True)
@click.pass_context
@async_command
@with_request_tracking("MCP CLI Command")
async def cli(
    ctx: click.Context, 
    config: Optional[str], 
    log_level: str, 
    request_id: Optional[str], 
    no_color: bool, 
    force_direct: bool
) -> None:
    """Checkmk LLM Agent CLI - MCP Edition"""
    # Setup logging with request ID support
    setup_logging(log_level, include_request_id=True)

    # Set request ID if provided, otherwise generate one
    if request_id:
        set_request_id(request_id)
    else:
        request_id = generate_request_id()
        set_request_id(request_id)

    # Load configuration
    config_file_path = config
    app_config = load_config(config_file_path)

    # Create formatter
    formatter = CLIFormatter(use_colors=not no_color)

    # Check if we should force direct mode or try MCP first
    if force_direct:
        # Skip MCP and go directly to fallback
        click.echo(formatter.format_info("Using direct CLI mode (MCP bypassed)"))
        from .cli import cli as direct_cli
        original_args = sys.argv[1:]
        if '--force-direct' in original_args:
            original_args.remove('--force-direct')
        sys.argv = ['checkmk_mcp_server.cli'] + original_args
        direct_cli.main(standalone_mode=False)
        # The direct CLI handled the full command line (including any
        # subcommand); exit so click doesn't also invoke the MCP subcommand.
        sys.exit(0)

    # Try MCP client connection, fallback to direct CLI if stdio fails.
    # NOTE: __aenter__ must NOT be wrapped in asyncio.wait_for() -- that runs
    # it in a child task, and the anyio cancel scopes inside stdio_client can
    # then never be exited cleanly from this task. connect() has its own
    # internal timeouts.
    try:
        mcp_client_context = create_mcp_client(app_config, config_file_path)
        mcp_client = await mcp_client_context.__aenter__()
        try:
            # Store in context for subcommands (each reconnects in its own
            # event loop via async_command; this connection is a probe)
            ctx.obj = MCPCLIContext(
                app_config, mcp_client, formatter, config_file=config_file_path
            )

            # If this is not a subcommand, just connect and exit
            if ctx.invoked_subcommand is None:
                click.echo("Checkmk MCP CLI connected. Use --help for available commands.")
        finally:
            # Ensure proper cleanup
            try:
                await mcp_client_context.__aexit__(None, None, None)
            except Exception as cleanup_error:
                logger.warning(f"Error during MCP client cleanup: {cleanup_error}")
    except (RuntimeError, asyncio.TimeoutError, OSError) as e:
        # Fallback to direct CLI for any MCP connection issues
        logger.info(f"MCP connection failed ({type(e).__name__}), falling back to direct CLI")
        click.echo(f"⚠️  MCP connection failed ({type(e).__name__}). Falling back to direct CLI...")
        
        # Import and delegate to the working direct CLI
        from .cli import cli as direct_cli
        
        # Get the original command arguments and delegate
        original_args = sys.argv[1:]  # Skip script name
        
        # Remove our script name and replace with direct CLI
        sys.argv = ['checkmk_mcp_server.cli'] + original_args
        
        # Call the direct CLI which works perfectly
        try:
            direct_cli.main(standalone_mode=False)
        except Exception as direct_cli_error:
            logger.error(f"Both MCP and direct CLI failed: {direct_cli_error}")
            click.echo(formatter.format_error(f"CLI initialization failed: {direct_cli_error}"))
            sys.exit(1)
        # The direct CLI handled the full command line (including any
        # subcommand); exit so click doesn't also invoke the MCP subcommand
        # with an uninitialized context ("Error: CLI context not initialized").
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error during CLI initialization: {e}")
        click.echo(formatter.format_error(f"Unexpected error: {e}"))
        sys.exit(1)


@cli.group()
@click.pass_obj
def hosts(ctx_obj: Optional[MCPCLIContext]) -> None:
    """Host management commands"""
    if ctx_obj is None:
        click.echo("Error: CLI context not properly initialized")
        sys.exit(1)


@hosts.command("list")
@click.option("--search", "-s", help="Search pattern for host names")
@click.option("--folder", "-f", help="Filter by folder")
@click.option("--limit", "-n", type=int, help="Maximum number of hosts to return")
@click.option("--status", is_flag=True, help="Include host status information")
@click.pass_obj
@async_command
async def list_hosts(
    ctx_obj: MCPCLIContext, 
    search: Optional[str], 
    folder: Optional[str], 
    limit: Optional[int], 
    status: bool
) -> None:
    """List all hosts"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.list_hosts(
            search=search, folder=folder, limit=limit, include_status=status
        )

        if result and result.get("success"):
            data = result.get("data", {})
            if data:
                click.echo(ctx_obj.formatter.format_host_list(data))
            else:
                click.echo(ctx_obj.formatter.format_info("No hosts found"))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to list hosts: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error listing hosts: {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@hosts.command("create")
@click.argument("name")
@click.option("--folder", "-f", default="/", help="Folder path")
@click.option("--ip", help="IP address")
@click.option("--alias", help="Host alias")
@click.option("--tags", "-t", multiple=True, help="Host tags")
@click.pass_obj
@async_command
async def create_host(
    ctx_obj: MCPCLIContext, 
    name: str, 
    folder: str, 
    ip: Optional[str], 
    alias: Optional[str], 
    tags: tuple
) -> None:
    """Create a new host"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    # Validate required parameters
    if not name or not name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    try:
        # Build attributes
        attributes: Dict[str, Any] = {}
        if alias:
            attributes["alias"] = alias.strip()
        if tags:
            attributes["tag_list"] = list(tags)

        result = await ctx_obj.mcp_client.create_host(
            name=name.strip(), folder=folder, ip_address=ip, attributes=attributes
        )

        if result and result.get("success"):
            click.echo(
                ctx_obj.formatter.format_success(f"Successfully created host '{name}'")
            )
            if result.get("data"):
                click.echo(ctx_obj.formatter.format_host_details(result["data"]))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to create host: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error creating host '{name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@hosts.command("show")
@click.argument("name")
@click.option("--status", is_flag=True, help="Include status information")
@click.pass_obj
@async_command
async def show_host(ctx_obj: MCPCLIContext, name: str, status: bool) -> None:
    """Show details for a specific host"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not name or not name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.get_host(name=name.strip(), include_status=status)

        if result and result.get("success"):
            data = result.get("data", {})
            if data:
                click.echo(ctx_obj.formatter.format_host_details(data))
            else:
                click.echo(ctx_obj.formatter.format_info(f"Host '{name}' not found or no data available"))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to get host details: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error getting host '{name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@hosts.command("update")
@click.argument("name")
@click.option("--folder", "-f", help="New folder path")
@click.option("--ip", help="New IP address")
@click.option("--alias", help="New host alias")
@click.option("--add-tag", "-t", multiple=True, help="Add tags")
@click.option("--remove-tag", "-r", multiple=True, help="Remove tags")
@click.pass_obj
@async_command
async def update_host(
    ctx_obj: MCPCLIContext, 
    name: str, 
    folder: Optional[str], 
    ip: Optional[str], 
    alias: Optional[str], 
    add_tag: tuple, 
    remove_tag: tuple
) -> None:
    """Update an existing host"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not name or not name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    try:
        # Build update parameters
        update_params: Dict[str, Any] = {"name": name.strip()}

        if folder:
            update_params["folder"] = folder.strip()
        if ip:
            update_params["ip_address"] = ip.strip()

        # Build attributes if needed
        attributes: Dict[str, Any] = {}
        if alias:
            attributes["alias"] = alias.strip()
        if add_tag or remove_tag:
            # Would need to get current tags first in a real implementation
            click.echo(
                ctx_obj.formatter.format_warning(
                    "Tag management not fully implemented in this example"
                )
            )

        if attributes:
            update_params["attributes"] = attributes

        result = await ctx_obj.mcp_client.update_host(**update_params)

        if result and result.get("success"):
            click.echo(
                ctx_obj.formatter.format_success(f"Successfully updated host '{name}'")
            )
            if result.get("data"):
                click.echo(ctx_obj.formatter.format_host_details(result["data"]))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to update host: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error updating host '{name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@hosts.command("delete")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_obj
@async_command
async def delete_host(ctx_obj: MCPCLIContext, name: str, force: bool) -> None:
    """Delete a host"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not name or not name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    try:
        name = name.strip()
        if not force:
            if not click.confirm(f"Are you sure you want to delete host '{name}'?"):
                click.echo("Aborted.")
                return

        result = await ctx_obj.mcp_client.delete_host(name=name)

        if result and result.get("success"):
            click.echo(
                ctx_obj.formatter.format_success(f"Successfully deleted host '{name}'")
            )
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to delete host: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error deleting host '{name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@cli.group()
@click.pass_obj
def services(ctx_obj: Optional[MCPCLIContext]) -> None:
    """Service management commands"""
    if ctx_obj is None:
        click.echo("Error: CLI context not properly initialized")
        sys.exit(1)


@services.command("list")
@click.argument("host_name", required=False)
@click.option(
    "--state",
    "-s",
    type=click.Choice(["OK", "WARNING", "CRITICAL", "UNKNOWN"]),
    multiple=True,
    help="Filter by service state",
)
@click.option("--limit", "-n", type=int, help="Maximum number of services")
@click.option("--details", is_flag=True, help="Include detailed information")
@click.pass_obj
@async_command
async def list_services(
    ctx_obj: MCPCLIContext, 
    host_name: Optional[str], 
    state: tuple, 
    limit: Optional[int], 
    details: bool
) -> None:
    """List services for a host or all hosts"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    try:
        state_filter = list(state) if state else None
        
        if host_name and host_name.strip():
            # List services for specific host
            result = await ctx_obj.mcp_client.list_host_services(
                host_name=host_name.strip(),
                state_filter=state_filter,
                include_details=details,
            )
        else:
            # List all services
            result = await ctx_obj.mcp_client.list_all_services(
                state_filter=state_filter, limit=limit
            )

        if result and result.get("success"):
            data = result.get("data", {})
            if data:
                click.echo(ctx_obj.formatter.format_service_list(data))
            else:
                click.echo(ctx_obj.formatter.format_info("No services found"))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to list services: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error listing services: {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@services.command("status")
@click.argument("host_name")
@click.argument("service_name")
@click.option("--related", is_flag=True, help="Include related services")
@click.pass_obj
@async_command
async def service_status(
    ctx_obj: MCPCLIContext, 
    host_name: str, 
    service_name: str, 
    related: bool
) -> None:
    """Get detailed status for a specific service"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not host_name or not host_name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    if not service_name or not service_name.strip():
        click.echo(ctx_obj.formatter.format_error("Service name cannot be empty"))
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.get_service_status(
            host_name=host_name.strip(), 
            service_name=service_name.strip(), 
            include_related=related
        )

        if result and result.get("success"):
            data = result.get("data", {})
            if data:
                click.echo(ctx_obj.formatter.format_service_status(data))
            else:
                click.echo(ctx_obj.formatter.format_info(
                    f"No status data for service '{service_name}' on host '{host_name}'"))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to get service status: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error getting service status for '{host_name}/{service_name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@services.command("acknowledge")
@click.argument("host_name")
@click.argument("service_name")
@click.option(
    "--comment", "-c", default="Acknowledged via CLI", help="Acknowledgement comment"
)
@click.option("--sticky/--no-sticky", default=True, help="Sticky acknowledgement")
@click.option("--notify/--no-notify", default=True, help="Send notifications")
@click.option(
    "--persistent/--no-persistent", default=False, help="Persist across restarts"
)
@click.pass_obj
@async_command
async def acknowledge_problem(
    ctx_obj: MCPCLIContext, 
    host_name: str, 
    service_name: str, 
    comment: str, 
    sticky: bool, 
    notify: bool, 
    persistent: bool
) -> None:
    """Acknowledge a service problem"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not host_name or not host_name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    if not service_name or not service_name.strip():
        click.echo(ctx_obj.formatter.format_error("Service name cannot be empty"))
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.acknowledge_service_problem(
            host_name=host_name.strip(),
            service_name=service_name.strip(),
            comment=comment.strip() if comment else "Acknowledged via CLI",
            sticky=sticky,
            notify=notify,
            persistent=persistent,
        )

        if result and result.get("success"):
            click.echo(
                ctx_obj.formatter.format_success(
                    f"Successfully acknowledged {host_name}/{service_name}"
                )
            )
            if result.get("data"):
                click.echo(ctx_obj.formatter.format_acknowledge_result(result["data"]))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to acknowledge problem: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error acknowledging service '{host_name}/{service_name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@services.command("downtime")
@click.argument("host_name")
@click.argument("service_name")
@click.argument("duration", type=float)
@click.option(
    "--comment", "-c", default="Scheduled downtime via CLI", help="Downtime comment"
)
@click.option("--start", help="Start time (ISO format, default: now)")
@click.option("--fixed/--flexible", default=True, help="Fixed or flexible downtime")
@click.pass_obj
@async_command
async def create_downtime(
    ctx_obj: MCPCLIContext, 
    host_name: str, 
    service_name: str, 
    duration: float, 
    comment: str, 
    start: Optional[str], 
    fixed: bool
) -> None:
    """Create scheduled downtime for a service"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not host_name or not host_name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    if not service_name or not service_name.strip():
        click.echo(ctx_obj.formatter.format_error("Service name cannot be empty"))
        sys.exit(1)
        
    if duration <= 0:
        click.echo(ctx_obj.formatter.format_error("Duration must be positive"))
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.create_service_downtime(
            host_name=host_name.strip(),
            service_name=service_name.strip(),
            duration_hours=duration,
            comment=comment.strip() if comment else "Scheduled downtime via CLI",
            start_time=start,
            fixed=fixed,
        )

        if result and result.get("success"):
            click.echo(
                ctx_obj.formatter.format_success(
                    f"Successfully created {duration}h downtime for {host_name}/{service_name}"
                )
            )
            if result.get("data"):
                click.echo(ctx_obj.formatter.format_downtime_result(result["data"]))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to create downtime: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error creating downtime for '{host_name}/{service_name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@services.command("discover")
@click.argument("host_name")
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["refresh", "new", "remove", "fixall"]),
    default="refresh",
    help="Discovery mode",
)
@click.pass_obj
@async_command
async def discover_services(
    ctx_obj: MCPCLIContext, 
    host_name: str, 
    mode: str
) -> None:
    """Discover services on a host"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not host_name or not host_name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.discover_services(
            host_name=host_name.strip(), mode=mode
        )

        if result and result.get("success"):
            click.echo(
                ctx_obj.formatter.format_success(
                    result.get("message", "Discovery completed")
                )
            )
            if result.get("data"):
                click.echo(ctx_obj.formatter.format_discovery_result(result["data"]))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to discover services: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error discovering services on host '{host_name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@cli.group()
@click.pass_obj
def status(ctx_obj: Optional[MCPCLIContext]) -> None:
    """Health and status monitoring commands"""
    if ctx_obj is None:
        click.echo("Error: CLI context not properly initialized")
        sys.exit(1)


@status.command("dashboard")
@click.option("--problems-only", is_flag=True, help="Show only hosts with problems")
@click.option("--critical-only", is_flag=True, help="Show only critical problems")
@click.option("--host-filter", "-h", help="Filter by host pattern")
@click.pass_obj
@async_command
async def health_dashboard(
    ctx_obj: MCPCLIContext, 
    problems_only: bool, 
    critical_only: bool, 
    host_filter: Optional[str]
) -> None:
    """Display infrastructure health dashboard"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.get_health_dashboard(
            host_filter=host_filter.strip() if host_filter else None,
            problems_only=problems_only,
            critical_only=critical_only,
        )

        if result and result.get("success"):
            data = result.get("data", {})
            if data:
                click.echo(ctx_obj.formatter.format_health_dashboard(data))
            else:
                click.echo(ctx_obj.formatter.format_info("No dashboard data available"))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to get health dashboard: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error getting health dashboard: {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@status.command("problems")
@click.argument("host_name", required=False)
@click.option("--category", "-c", help="Filter by problem category")
@click.option(
    "--severity",
    "-s",
    type=click.Choice(["critical", "warning", "unknown"]),
    help="Filter by severity",
)
@click.pass_obj
@async_command
async def show_problems(
    ctx_obj: MCPCLIContext, 
    host_name: Optional[str], 
    category: Optional[str], 
    severity: Optional[str]
) -> None:
    """Show current problems"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    try:
        if host_name and host_name.strip():
            # Get problems for specific host
            result = await ctx_obj.mcp_client.get_host_problems(
                host_name=host_name.strip(), 
                category_filter=category.strip() if category else None, 
                severity_filter=severity
            )
        else:
            # Get all critical problems
            result = await ctx_obj.mcp_client.get_critical_problems()

        if result and result.get("success"):
            data = result.get("data", {})
            if data:
                click.echo(ctx_obj.formatter.format_problem_summary(data))
            else:
                click.echo(ctx_obj.formatter.format_info("No problems found"))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to get problems: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error getting problems: {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@status.command("analyze")
@click.argument("host_name")
@click.option("--grade", is_flag=True, help="Include health grade")
@click.option("--recommendations", is_flag=True, help="Include recommendations")
@click.option("--compare", is_flag=True, help="Compare to peer hosts")
@click.pass_obj
@async_command
async def analyze_host(
    ctx_obj: MCPCLIContext, 
    host_name: str, 
    grade: bool, 
    recommendations: bool, 
    compare: bool
) -> None:
    """Analyze host health in detail"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    if not host_name or not host_name.strip():
        click.echo(ctx_obj.formatter.format_error("Host name cannot be empty"))
        sys.exit(1)
        
    try:
        result = await ctx_obj.mcp_client.analyze_host_health(
            host_name=host_name.strip(),
            include_grade=grade,
            include_recommendations=recommendations,
            compare_to_peers=compare,
        )

        if result and result.get("success"):
            data = result.get("data", {})
            if data:
                click.echo(ctx_obj.formatter.format_host_analysis(data))
            else:
                click.echo(ctx_obj.formatter.format_info(
                    f"No analysis data available for host '{host_name}'"))
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response received'
            click.echo(
                ctx_obj.formatter.format_error(
                    f"Failed to analyze host: {error_msg}"
                )
            )
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error analyzing host '{host_name}': {e}")
        click.echo(ctx_obj.formatter.format_error(f"Error: {str(e)}"))
        sys.exit(1)


@cli.command()
@click.option("--prompt", "-p", help="Initial prompt to send")
@click.option("--history", "-h", is_flag=True, help="Load command history")
@click.pass_obj
@async_command
async def interactive(
    ctx_obj: MCPCLIContext, 
    prompt: Optional[str], 
    history: bool
) -> None:
    """Start interactive mode with natural language interface"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    try:
        click.echo(ctx_obj.formatter.format_header("Checkmk Interactive Mode (MCP)"))
        click.echo("Type 'help' for available commands or 'exit' to quit.\n")

        # Import interactive components
        from .interactive.mcp_session import InteractiveSession

        # Create and run interactive session
        session = InteractiveSession(
            mcp_client=ctx_obj.mcp_client,
            formatter=ctx_obj.formatter,
            config=ctx_obj.config,
        )

        await session.run(
            initial_prompt=prompt.strip() if prompt else None, 
            load_history=history
        )
    except ImportError as e:
        logger.error(f"Interactive session not available: {e}")
        click.echo(ctx_obj.formatter.format_error(
            "Interactive mode not available. Missing interactive components."))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error running interactive session: {e}")
        click.echo(ctx_obj.formatter.format_error(f"Interactive mode failed: {e}"))
        sys.exit(1)


@cli.command()
@click.pass_obj
def resources(ctx_obj: Optional[MCPCLIContext]) -> None:
    """List available MCP resources"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    click.echo(ctx_obj.formatter.format_header("Available MCP Resources"))
    click.echo()

    resource_list = [
        ("checkmk://dashboard/health", "Real-time infrastructure health dashboard"),
        (
            "checkmk://dashboard/problems",
            "Current critical problems across infrastructure",
        ),
        ("checkmk://hosts/status", "Current status of all monitored hosts"),
        ("checkmk://services/problems", "Current service problems requiring attention"),
        ("checkmk://metrics/performance", "Real-time performance metrics and trends"),
    ]

    for uri, description in resource_list:
        click.echo(f"  {ctx_obj.formatter.format_info(uri)}")
        click.echo(f"    {description}")
        click.echo()


@cli.command()
@click.pass_obj
def prompts(ctx_obj: Optional[MCPCLIContext]) -> None:
    """List available MCP prompt templates"""
    if ctx_obj is None:
        click.echo("Error: CLI context not initialized")
        sys.exit(1)
        
    click.echo(ctx_obj.formatter.format_header("Available MCP Prompt Templates"))
    click.echo()

    prompt_list = [
        (
            "analyze_host_health",
            "Analyze the health of a specific host with detailed recommendations",
        ),
        (
            "troubleshoot_service",
            "Comprehensive troubleshooting analysis for a service problem",
        ),
        (
            "infrastructure_overview",
            "Get a comprehensive overview of infrastructure health and trends",
        ),
        (
            "optimize_parameters",
            "Get parameter optimization recommendations for a service",
        ),
    ]

    for name, description in prompt_list:
        click.echo(f"  {ctx_obj.formatter.format_info(name)}")
        click.echo(f"    {description}")
        click.echo()


def main() -> None:
    """Main entry point for MCP CLI"""
    try:
        cli()
    except KeyboardInterrupt:
        logger.info("CLI interrupted by user")
        click.echo("\nExiting...")
        sys.exit(130)  # Standard exit code for Ctrl+C
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        click.echo(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
