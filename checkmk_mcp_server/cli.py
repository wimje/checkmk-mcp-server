"""Command-line interface for Checkmk LLM Agent."""

import sys
import click
import logging
from typing import Optional, List, Dict

from .config import load_config
from .api_client import CheckmkClient
from .llm_client import create_llm_client, LLMProvider
from .host_operations import HostOperationsManager

# Logging will be imported later when needed

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

    def track_request(**kwargs):
        def decorator(func):
            return func

        return decorator

    def with_request_tracking(**kwargs):
        def decorator(func):
            return func

        return decorator


@click.group()
@click.option(
    "--log-level", default=None, help="Logging level (DEBUG, INFO, WARNING, ERROR)"
)
@click.option(
    "--config", "--config-file", help="Path to configuration file (YAML, TOML, or JSON)"
)
@click.option("--request-id", help="Specific request ID to use for tracing (optional)")
@click.pass_context
@with_request_tracking("CLI Command")
def cli(ctx, log_level: str, config: Optional[str], request_id: Optional[str]):
    """Checkmk LLM Agent - Natural language interface for Checkmk."""
    ctx.ensure_object(dict)

    # Set request ID if provided, otherwise generate one
    if request_id:
        set_request_id(request_id)
    else:
        request_id = generate_request_id()
        set_request_id(request_id)

    # Store request ID in context for subcommands
    ctx.obj["request_id"] = request_id

    # Load configuration first (to get config log_level if CLI flag not set)
    from .config import load_config

    app_config = load_config(config_file=config)
    ctx.obj["config"] = app_config

    # Determine log level: CLI flag overrides config
    effective_log_level = log_level or app_config.log_level

    # Setup logging with request ID support
    from .logging_utils import setup_logging

    setup_logging(effective_log_level, include_request_id=True)
    logger = logging.getLogger(__name__)

    try:
        # Initialize clients
        from .api_client import CheckmkClient

        checkmk_client = CheckmkClient(app_config.checkmk)
        ctx.obj["checkmk_client"] = checkmk_client

        # Verify the Checkmk server and REST API versions are supported.
        # Fail cleanly (no traceback) on unsupported versions; if the check
        # is inconclusive (e.g. network hiccup), warn and continue.
        compat = checkmk_client.check_version_compatibility()
        if compat["compatible"] is False:
            import click
            import sys

            for issue in compat["issues"]:
                click.echo(f"❌ {issue}", err=True)
            click.echo(
                "❌ Unsupported Checkmk server. See docs/getting-started.md "
                "for supported versions.",
                err=True,
            )
            sys.exit(1)
        elif compat["compatible"] is None:
            for issue in compat["issues"]:
                logger.warning(issue)

        # Try to initialize LLM client
        try:
            from .llm_client import create_llm_client

            llm_client = create_llm_client(app_config.llm)
            ctx.obj["llm_client"] = llm_client

            # Initialize host operations manager
            from .host_operations import HostOperationsManager

            host_manager = HostOperationsManager(checkmk_client, llm_client, app_config)
            ctx.obj["host_manager"] = host_manager

            # Initialize service operations manager
            from .service_operations import ServiceOperationsManager

            service_manager = ServiceOperationsManager(
                checkmk_client, llm_client, app_config
            )
            ctx.obj["service_manager"] = service_manager

        except Exception as e:
            logger.warning(f"LLM client initialization failed: {e}")
            ctx.obj["llm_client"] = None
            ctx.obj["host_manager"] = None
            ctx.obj["service_manager"] = None

    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        import click

        click.echo(f"❌ Error: {e}", err=True)
        import sys

        sys.exit(1)


@cli.command()
@click.pass_context
@track_request(operation_name="CLI Test Command")
def test(ctx):
    """Test connection to Checkmk API."""
    request_id = ctx.obj.get("request_id", generate_request_id())
    set_request_id(request_id)

    checkmk_client = ctx.obj["checkmk_client"]

    try:
        if checkmk_client.test_connection():
            click.echo("✅ Successfully connected to Checkmk API")
        else:
            click.echo("❌ Failed to connect to Checkmk API")
            click.echo("   Check your configuration and server accessibility:")
            click.echo("   1. Verify server URL is correct and accessible")
            click.echo("   2. Check username and password are valid")
            click.echo("   3. Ensure the Checkmk site name is correct")
            sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Connection test failed: {e}", err=True)
        if "Connection" in str(e):
            click.echo(
                "   💡 Tip: Check network connectivity and firewall settings", err=True
            )
        elif "401" in str(e) or "auth" in str(e).lower():
            click.echo(
                "   💡 Tip: Verify your credentials in the configuration file", err=True
            )
        sys.exit(1)


@cli.command()
@click.pass_context
@track_request(operation_name="CLI Interactive Mode")
def interactive(ctx):
    """Start interactive mode for natural language commands."""
    request_id = ctx.obj.get("request_id", generate_request_id())
    set_request_id(request_id)

    host_manager = ctx.obj.get("host_manager")
    service_manager = ctx.obj.get("service_manager")
    checkmk_client = ctx.obj.get("checkmk_client")
    app_config = ctx.obj.get("config")

    if not host_manager:
        click.echo("❌ LLM client not available. To use interactive mode:", err=True)
        click.echo(
            "   1. Set OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable",
            err=True,
        )
        click.echo("   2. Or create a .env file with your API key", err=True)
        click.echo(
            "   3. Or use the CLI commands directly without interactive mode", err=True
        )
        sys.exit(1)

    # Initialize interactive components
    from .interactive import (
        ReadlineHandler,
        CommandParser,
        HelpSystem,
        TabCompleter,
        UIManager,
    )

    # Setup components with UI configuration
    ui_config = app_config.ui if app_config else None
    ui_manager = UIManager(
        theme=ui_config.theme if ui_config else "default",
        use_colors=ui_config.use_colors if ui_config else None,
        custom_colors=ui_config.custom_colors if ui_config else None,
    )
    help_system = HelpSystem()
    command_parser = CommandParser()
    tab_completer = TabCompleter(checkmk_client, help_system)

    # Setup readline with history and completion
    with ReadlineHandler() as readline_handler:
        readline_handler.set_completer(tab_completer.complete)

        # Print welcome message
        ui_manager.print_welcome()

        while True:
            try:
                # Get user input with readline support
                user_input = readline_handler.input_with_prompt(
                    ui_manager.format_prompt()
                ).strip()

                if not user_input:
                    continue

                # Parse the command
                intent = command_parser.parse_command(user_input)

                # Handle help requests
                if intent.is_help_request:
                    help_text = help_system.show_help(intent.help_topic)
                    ui_manager.print_help(help_text)
                    continue

                # Handle exit commands
                if intent.command == "quit":
                    ui_manager.print_goodbye()
                    break

                # Handle special commands
                if intent.command == "stats":
                    result = host_manager.get_host_statistics()
                    ui_manager.print_info(result)
                    continue

                if intent.command == "test":
                    result = host_manager.test_connection()
                    ui_manager.print_info(result)
                    continue

                # Handle theme commands
                if intent.command.startswith("theme"):
                    args = (
                        intent.command.split()[1:]
                        if len(intent.command.split()) > 1
                        else []
                    )
                    if not args:
                        ui_manager.print_info("Usage: theme [list|set <name>|current]")
                        continue

                    subcommand = args[0].lower()
                    if subcommand == "list":
                        themes = ui_manager.list_themes()
                        ui_manager.print_info("🎨 Available themes:")
                        for theme in themes:
                            current = (
                                " (current)"
                                if theme["name"] == ui_manager.get_current_theme()
                                else ""
                            )
                            ui_manager.print_info(
                                f"  • {theme['display_name']}{current}: {theme['description']}"
                            )
                    elif subcommand == "set" and len(args) > 1:
                        theme_name = args[1]
                        if ui_manager.set_theme(theme_name):
                            ui_manager.print_success(f"Theme changed to: {theme_name}")
                        else:
                            available = [t["name"] for t in ui_manager.list_themes()]
                            ui_manager.print_error(
                                f"Unknown theme: {theme_name}. Available: {', '.join(available)}"
                            )
                    elif subcommand == "current":
                        current = ui_manager.get_current_theme()
                        ui_manager.print_info(f"Current theme: {current}")
                    else:
                        ui_manager.print_info("Usage: theme [list|set <name>|current]")
                    continue

                # Handle color commands
                if intent.command.startswith("colors"):
                    args = (
                        intent.command.split()[1:]
                        if len(intent.command.split()) > 1
                        else []
                    )
                    if not args:
                        ui_manager.print_info("Usage: colors [show|test|terminal]")
                        continue

                    subcommand = args[0].lower()
                    if subcommand == "show":
                        preview = ui_manager.preview_colors()
                        print(preview)
                    elif subcommand == "test":
                        test_output = ui_manager.test_colors()
                        print(test_output)
                    elif subcommand == "terminal":
                        terminal_info = ui_manager.get_terminal_info()
                        print(terminal_info)
                    else:
                        ui_manager.print_info("Usage: colors [show|test|terminal]")
                    continue

                # Handle low confidence commands with suggestions
                if intent.confidence < 0.6 and intent.suggestions:
                    error_msg = f"Command not clear: '{user_input}'"
                    formatted_error = ui_manager.format_error_with_suggestions(
                        error_msg, intent.suggestions
                    )
                    print(formatted_error)
                    continue

                # Route command to appropriate manager
                # Determine command type using the enhanced parser
                command_type = command_parser.get_command_type(
                    intent.command, intent.parameters, user_input
                )

                # Check for status-related commands first
                if command_type == "status":
                    # Initialize status manager for this command
                    from .service_status import ServiceStatusManager

                    status_manager = ServiceStatusManager(checkmk_client, app_config)

                    try:
                        # Process status commands
                        result = process_status_command(
                            user_input, status_manager, intent
                        )
                        ui_manager.print_info(result)
                    except Exception as e:
                        ui_manager.print_error(f"Status command error: {e}")

                # Route to service manager for service operations
                elif command_type == "service":
                    if service_manager:
                        result = service_manager.process_command(user_input)
                        ui_manager.print_info(result)
                    else:
                        ui_manager.print_error(
                            "Service manager not available. Check your configuration."
                        )

                # Route to host manager for host operations
                elif command_type == "host":
                    if host_manager:
                        result = host_manager.process_command(user_input)
                        ui_manager.print_info(result)
                    else:
                        ui_manager.print_error(
                            "Host manager not available. Check your configuration."
                        )

                else:
                    # Show error for unrecognized commands
                    ui_manager.print_error(f"Unable to process command: '{user_input}'")
                    ui_manager.print_info(
                        "💡 Try 'help' for available commands or '? <command>' for specific help"
                    )

            except KeyboardInterrupt:
                ui_manager.print_goodbye()
                break
            except EOFError:
                ui_manager.print_goodbye()
                break
            except Exception as e:
                ui_manager.print_error(f"Error: {e}")

                # Provide helpful suggestions for common errors
                if "connection" in str(e).lower():
                    ui_manager.print_info("💡 Try: 'test' to check your connection")
                elif "not found" in str(e).lower():
                    ui_manager.print_info("💡 Try: 'list hosts' to see available hosts")
                elif "permission" in str(e).lower():
                    ui_manager.print_info("💡 Check your Checkmk user permissions")


@cli.group()
def hosts():
    """Host management commands."""
    pass


@hosts.command("list")
@click.option("--folder", help="Filter by folder")
@click.option("--search", help="Search term to filter hosts")
@click.option(
    "--effective-attributes",
    is_flag=True,
    help="Show all effective attributes including inherited folder attributes and computed parameters (permissions enforced by Checkmk server)",
)
@click.pass_context
def list_hosts(
    ctx, folder: Optional[str], search: Optional[str], effective_attributes: bool
):
    """
    List all hosts with optional filtering by folder and search criteria.

    Args:
        ctx: Click context containing application state
        folder: Filter hosts by folder path (e.g., '/web', '/database')
        search: Search term to filter hosts by name or alias
        effective_attributes: Include all effective attributes (inherited folder attributes, computed parameters). Permissions enforced by Checkmk server.
    """
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        hosts = checkmk_client.list_hosts(effective_attributes=effective_attributes)

        # Apply filters
        if folder or search:
            filtered_hosts = []
            for host in hosts:
                host_id = host.get("id", "")
                extensions = host.get("extensions", {})
                host_folder = extensions.get("folder", "")
                attributes = extensions.get("attributes", {})
                alias = attributes.get("alias", "")

                # Filter by folder
                if folder and folder not in host_folder:
                    continue

                # Filter by search term
                if search:
                    search_lower = search.lower()
                    if not any(
                        search_lower in field.lower()
                        for field in [host_id, host_folder, alias]
                    ):
                        continue

                filtered_hosts.append(host)

            hosts = filtered_hosts

        if not hosts:
            click.echo("No hosts found.")
            return

        # Display hosts
        click.echo(f"Found {len(hosts)} hosts:")
        for host in hosts:
            host_id = host.get("id", "Unknown")
            extensions = host.get("extensions", {})
            host_folder = extensions.get("folder", "Unknown")
            attributes = extensions.get("attributes", {})
            ip_address = attributes.get("ipaddress", "Not set")

            click.echo(f"  📦 {host_id}")
            click.echo(f"     Folder: {host_folder}")
            click.echo(f"     IP: {ip_address}")
            if extensions.get("is_cluster"):
                click.echo(f"     Type: Cluster")
            if extensions.get("is_offline"):
                click.echo(f"     Status: Offline")
            click.echo()

    except Exception as e:
        click.echo(f"❌ Error listing hosts: {e}", err=True)
        sys.exit(1)


@hosts.command("create")
@click.argument("host_name")
@click.option("--folder", default="/", help="Folder path (default: /)")
@click.option("--ip", help="IP address")
@click.option("--alias", help="Host alias/description")
@click.option("--bake-agent", is_flag=True, help="Automatically bake agent")
@click.pass_context
def create_host(
    ctx,
    host_name: str,
    folder: str,
    ip: Optional[str],
    alias: Optional[str],
    bake_agent: bool,
):
    """Create a new host."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        attributes = {}
        if ip:
            attributes["ipaddress"] = ip
        if alias:
            attributes["alias"] = alias

        result = checkmk_client.create_host(
            folder=folder,
            host_name=host_name,
            attributes=attributes,
            bake_agent=bake_agent,
        )

        click.echo(f"✅ Successfully created host: {host_name}")
        click.echo(f"   Folder: {folder}")
        if attributes:
            click.echo(f"   Attributes: {attributes}")

    except Exception as e:
        click.echo(f"❌ Error creating host: {e}", err=True)
        sys.exit(1)


@hosts.command("delete")
@click.argument("host_name")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete_host(ctx, host_name: str, force: bool):
    """Delete a host."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        # Check if host exists
        try:
            host = checkmk_client.get_host(host_name)
            click.echo(f"Host found: {host_name}")
            extensions = host.get("extensions", {})
            folder = extensions.get("folder", "Unknown")
            click.echo(f"Folder: {folder}")
        except Exception as e:
            click.echo(f"❌ Host '{host_name}' not found: {e}", err=True)
            sys.exit(1)

        # Confirmation
        if not force:
            if not click.confirm(
                f"Are you sure you want to delete host '{host_name}'?"
            ):
                click.echo("❌ Deletion cancelled.")
                return

        checkmk_client.delete_host(host_name)
        click.echo(f"✅ Successfully deleted host: {host_name}")

    except Exception as e:
        click.echo(f"❌ Error deleting host: {e}", err=True)
        sys.exit(1)


@hosts.command("get")
@click.argument("host_name")
@click.option(
    "--effective-attributes",
    is_flag=True,
    help="Show all effective attributes including inherited folder attributes and computed parameters (permissions enforced by Checkmk server)",
)
@click.pass_context
def get_host(ctx, host_name: str, effective_attributes: bool):
    """Get detailed information about a host.

    Args:
        host_name: Name of the host to retrieve
        effective_attributes: Include all effective attributes (inherited folder attributes, computed parameters). Permissions enforced by Checkmk server.
    """
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        host = checkmk_client.get_host(
            host_name, effective_attributes=effective_attributes
        )

        host_id = host.get("id", "Unknown")
        extensions = host.get("extensions", {})
        folder = extensions.get("folder", "Unknown")
        attributes = extensions.get("attributes", {})

        click.echo(f"📦 Host Details: {host_id}")
        click.echo(f"   Folder: {folder}")
        click.echo(f"   Cluster: {'Yes' if extensions.get('is_cluster') else 'No'}")
        click.echo(f"   Offline: {'Yes' if extensions.get('is_offline') else 'No'}")

        if attributes:
            click.echo("   Attributes:")
            for key, value in attributes.items():
                click.echo(f"     {key}: {value}")

        if effective_attributes and extensions.get("effective_attributes"):
            click.echo("   Effective Attributes:")
            for key, value in extensions["effective_attributes"].items():
                click.echo(f"     {key}: {value}")

    except Exception as e:
        click.echo(f"❌ Error getting host: {e}", err=True)
        sys.exit(1)


@hosts.command("interactive-create")
@click.pass_context
def interactive_create(ctx):
    """Create a host with interactive prompts."""
    host_manager = ctx.obj.get("host_manager")

    if not host_manager:
        click.echo("❌ Host manager not available.", err=True)
        sys.exit(1)

    result = host_manager.interactive_create_host()
    click.echo(result)


@cli.group()
def rules():
    """Rule management commands."""
    pass


@rules.command("list")
@click.argument("ruleset_name")
@click.pass_context
def list_rules(ctx, ruleset_name: str):
    """List all rules in a specific ruleset."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        rules = checkmk_client.list_rules(ruleset_name)

        if not rules:
            click.echo(f"No rules found in ruleset: {ruleset_name}")
            return

        # Display rules
        click.echo(f"Found {len(rules)} rules in ruleset '{ruleset_name}':")
        for rule in rules:
            rule_id = rule.get("id", "Unknown")
            extensions = rule.get("extensions", {})
            folder = extensions.get("folder", "Unknown")
            properties = extensions.get("properties", {})
            disabled = properties.get("disabled", False)
            description = properties.get("description", "")

            click.echo(f"  📋 {rule_id}")
            click.echo(f"     Folder: {folder}")
            click.echo(f"     Status: {'Disabled' if disabled else 'Enabled'}")
            if description:
                click.echo(f"     Description: {description}")
            click.echo()

    except Exception as e:
        click.echo(f"❌ Error listing rules: {e}", err=True)
        sys.exit(1)


@rules.command("create")
@click.argument("ruleset_name")
@click.option("--folder", default="/", help="Folder path (default: /)")
@click.option("--value", help="Rule value as JSON string")
@click.option("--description", help="Rule description")
@click.option("--disabled", is_flag=True, help="Create rule as disabled")
@click.pass_context
def create_rule(
    ctx,
    ruleset_name: str,
    folder: str,
    value: Optional[str],
    description: Optional[str],
    disabled: bool,
):
    """Create a new rule in a ruleset."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        # If value not provided, prompt for it
        if not value:
            value = click.prompt("Enter rule value as JSON string")

        # Build properties
        properties = {}
        if description:
            properties["description"] = description
        if disabled:
            properties["disabled"] = True

        result = checkmk_client.create_rule(
            ruleset=ruleset_name, folder=folder, value_raw=value, properties=properties
        )

        rule_id = result.get("id", "Unknown")
        click.echo(f"✅ Successfully created rule: {rule_id}")
        click.echo(f"   Ruleset: {ruleset_name}")
        click.echo(f"   Folder: {folder}")
        if properties:
            click.echo(f"   Properties: {properties}")

    except Exception as e:
        click.echo(f"❌ Error creating rule: {e}", err=True)
        sys.exit(1)


@rules.command("delete")
@click.argument("rule_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete_rule(ctx, rule_id: str, force: bool):
    """Delete a rule."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        # Check if rule exists
        try:
            rule = checkmk_client.get_rule(rule_id)
            extensions = rule.get("extensions", {})
            ruleset = extensions.get("ruleset", "Unknown")
            folder = extensions.get("folder", "Unknown")
            click.echo(f"Rule found: {rule_id}")
            click.echo(f"Ruleset: {ruleset}")
            click.echo(f"Folder: {folder}")
        except Exception as e:
            click.echo(f"❌ Rule '{rule_id}' not found: {e}", err=True)
            sys.exit(1)

        # Confirmation
        if not force:
            if not click.confirm(f"Are you sure you want to delete rule '{rule_id}'?"):
                click.echo("❌ Deletion cancelled.")
                return

        checkmk_client.delete_rule(rule_id)
        click.echo(f"✅ Successfully deleted rule: {rule_id}")

    except Exception as e:
        click.echo(f"❌ Error deleting rule: {e}", err=True)
        sys.exit(1)


@rules.command("get")
@click.argument("rule_id")
@click.pass_context
def get_rule(ctx, rule_id: str):
    """Get detailed information about a rule."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        rule = checkmk_client.get_rule(rule_id)

        rule_id = rule.get("id", "Unknown")
        extensions = rule.get("extensions", {})
        ruleset = extensions.get("ruleset", "Unknown")
        folder = extensions.get("folder", "Unknown")
        properties = extensions.get("properties", {})
        value_raw = extensions.get("value_raw", "")

        click.echo(f"📋 Rule Details: {rule_id}")
        click.echo(f"   Ruleset: {ruleset}")
        click.echo(f"   Folder: {folder}")
        click.echo(
            f"   Status: {'Disabled' if properties.get('disabled') else 'Enabled'}"
        )

        if properties.get("description"):
            click.echo(f"   Description: {properties['description']}")

        if value_raw:
            click.echo(f"   Value: {value_raw}")

        if extensions.get("conditions"):
            click.echo(f"   Conditions: {extensions['conditions']}")

    except Exception as e:
        click.echo(f"❌ Error getting rule: {e}", err=True)
        sys.exit(1)


@rules.command("move")
@click.argument("rule_id")
@click.argument(
    "position",
    type=click.Choice(["top_of_folder", "bottom_of_folder", "before", "after"]),
)
@click.option("--folder", help="Target folder for the rule")
@click.option("--target-rule", help="Target rule ID for before/after positioning")
@click.pass_context
def move_rule(
    ctx, rule_id: str, position: str, folder: Optional[str], target_rule: Optional[str]
):
    """Move a rule to a new position."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        if position in ["before", "after"] and not target_rule:
            raise ValueError(f"--target-rule is required when position is '{position}'")

        result = checkmk_client.move_rule(
            rule_id=rule_id,
            position=position,
            folder=folder,
            target_rule_id=target_rule,
        )

        click.echo(f"✅ Successfully moved rule: {rule_id}")
        click.echo(f"   Position: {position}")
        if folder:
            click.echo(f"   Target folder: {folder}")
        if target_rule:
            click.echo(f"   Target rule: {target_rule}")

    except Exception as e:
        click.echo(f"❌ Error moving rule: {e}", err=True)
        sys.exit(1)


@cli.group()
def services():
    """Service management commands."""
    pass


@services.command("list")
@click.argument("host_name", required=False)
@click.option("--sites", multiple=True, help="Restrict to specific sites")
@click.option("--query", help="Livestatus query expressions")
@click.option("--columns", multiple=True, help="Desired columns")
@click.pass_context
def list_services(
    ctx, host_name: Optional[str], sites: tuple, query: Optional[str], columns: tuple
):
    """List services for a host or all services."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        if host_name:
            # List services for specific host
            click.echo(
                f"CLI DEBUG: About to call list_host_services_with_monitoring_data for {host_name}"
            )
            try:
                services = checkmk_client.list_host_services_with_monitoring_data(
                    host_name=host_name,
                    sites=list(sites) if sites else None,
                    query=query,
                    columns=(
                        list(columns) if columns else None
                    ),  # Get monitoring data with state
                )
                click.echo(
                    f"CLI DEBUG: Successfully got {len(services)} services from monitoring endpoint"
                )
            except Exception as e:
                click.echo(f"CLI DEBUG: Error calling monitoring endpoint: {e}")
                click.echo(f"CLI DEBUG: Falling back to original method")
                services = checkmk_client.list_host_services(
                    host_name=host_name,
                    sites=list(sites) if sites else None,
                    query=query,
                    columns=list(columns) if columns else None,
                )
        else:
            # List all services
            click.echo(
                f"CLI DEBUG: About to call list_all_services_with_monitoring_data"
            )
            services = checkmk_client.list_all_services_with_monitoring_data(
                sites=list(sites) if sites else None,
                query=query,
                columns=list(columns) if columns else None,
            )
            click.echo(
                f"CLI DEBUG: Successfully got {len(services)} services from all services monitoring endpoint"
            )

        if not services:
            if host_name:
                click.echo(f"No services found for host: {host_name}")
            else:
                click.echo("No services found.")
            return

        # Display services
        if host_name:
            click.echo(f"Found {len(services)} services for host: {host_name}")
        else:
            click.echo(f"Found {len(services)} services")

        for service in services:
            # Debug: Print the first service structure to understand the data format
            if service == services[0]:
                click.echo(f"DEBUG - Service keys: {list(service.keys())}")
                click.echo(f"DEBUG - Full service data: {service}")

            # Extract data directly from service object (Checkmk API format)
            # First try extensions, then direct access for backward compatibility
            extensions = service.get("extensions", {})
            # Use explicit None checks to avoid issues with falsy values like empty strings or 0
            service_desc = (
                extensions.get("description")
                if extensions.get("description") is not None
                else service.get("description", "Unknown")
            )
            service_state = (
                extensions.get("state")
                if extensions.get("state") is not None
                else service.get("state", "Unknown")
            )
            plugin_output = (
                extensions.get("plugin_output")
                if extensions.get("plugin_output") is not None
                else service.get("plugin_output", "")
            )
            host = (
                extensions.get("host_name")
                if extensions.get("host_name") is not None
                else service.get("host_name", host_name or "Unknown")
            )

            # Convert numeric state to text
            if isinstance(service_state, int):
                state_map = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}
                state_text = state_map.get(service_state, f"STATE_{service_state}")
                state_emoji = {
                    "OK": "✅",
                    "WARNING": "⚠️",
                    "CRITICAL": "❌",
                    "UNKNOWN": "❓",
                }.get(state_text, "❓")
            else:
                state_text = str(service_state)
                state_emoji = "✅" if state_text == "OK" else "❌"

            # Show service with status and brief output
            output_snippet = (
                plugin_output[:60] + "..." if len(plugin_output) > 60 else plugin_output
            )
            if output_snippet:
                click.echo(
                    f"  {state_emoji} {host}/{service_desc} - {state_text} ({output_snippet})"
                )
            else:
                click.echo(f"  {state_emoji} {host}/{service_desc} - {state_text}")

    except Exception as e:
        click.echo(f"❌ Error listing services: {e}", err=True)
        sys.exit(1)


@services.command("status")
@click.argument("host_name")
@click.argument("service_description")
@click.pass_context
def get_service_status(ctx, host_name: str, service_description: str):
    """Get detailed status of a specific service."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        services = checkmk_client.list_host_services(
            host_name=host_name, query=f"service_description = '{service_description}'"
        )

        if not services:
            click.echo(
                f"❌ Service '{service_description}' not found on host '{host_name}'"
            )
            click.echo("   💡 Tips:")
            click.echo("   • Check the service name spelling (case-sensitive)")
            click.echo("   • Use 'services list <host>' to see all services")
            click.echo("   • Service may need to be discovered first")
            sys.exit(1)

        service = services[0]
        extensions = service.get("extensions", {})
        service_state = extensions.get("state", "Unknown")
        last_check = extensions.get("last_check", "Unknown")
        plugin_output = extensions.get("plugin_output", "No output")

        state_emoji = "✅" if service_state == "OK" or service_state == 0 else "❌"

        click.echo(f"📊 Service Status: {host_name}/{service_description}")
        click.echo(f"{state_emoji} State: {service_state}")
        click.echo(f"⏰ Last Check: {last_check}")
        click.echo(f"💬 Output: {plugin_output}")

    except Exception as e:
        click.echo(f"❌ Error getting service status: {e}", err=True)
        sys.exit(1)


@services.command("acknowledge")
@click.argument("host_name")
@click.argument("service_description")
@click.option(
    "--comment", default="Acknowledged via CLI", help="Acknowledgment comment"
)
@click.option("--sticky", is_flag=True, help="Make acknowledgment sticky")
@click.pass_context
def acknowledge_service(
    ctx, host_name: str, service_description: str, comment: str, sticky: bool
):
    """Acknowledge a service problem."""
    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]

    try:
        author = config.checkmk.username

        checkmk_client.acknowledge_service_problems(
            host_name=host_name,
            service_description=service_description,
            comment=comment,
            author=author,
            sticky=sticky,
        )

        click.echo(
            f"✅ Acknowledged service problem: {host_name}/{service_description}"
        )
        click.echo(f"💬 Comment: {comment}")

    except Exception as e:
        click.echo(f"❌ Error acknowledging service: {e}", err=True)
        sys.exit(1)


@services.command("downtime")
@click.argument("host_name")
@click.argument("service_description")
@click.option("--hours", default=2, type=int, help="Duration in hours (default: 2)")
@click.option("--comment", default="Downtime created via CLI", help="Downtime comment")
@click.pass_context
def create_service_downtime(
    ctx, host_name: str, service_description: str, hours: int, comment: str
):
    """Create downtime for a service."""
    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]

    try:
        from datetime import datetime, timedelta

        start_time = datetime.now()
        end_time = start_time + timedelta(hours=hours)
        author = config.checkmk.username

        checkmk_client.create_service_downtime(
            host_name=host_name,
            service_description=service_description,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            comment=comment,
            author=author,
        )

        click.echo(
            f"✅ Created downtime for service: {host_name}/{service_description}"
        )
        click.echo(f"⏰ Duration: {hours} hours")
        click.echo(f"🕐 Start: {start_time.strftime('%Y-%m-%d %H:%M')}")
        click.echo(f"🕑 End: {end_time.strftime('%Y-%m-%d %H:%M')}")
        click.echo(f"💬 Comment: {comment}")

    except Exception as e:
        click.echo(f"❌ Error creating downtime: {e}", err=True)
        sys.exit(1)


@services.command("discover")
@click.argument("host_name")
@click.option(
    "--mode",
    default="refresh",
    type=click.Choice(["refresh", "new", "remove", "fixall", "refresh_autochecks"]),
    help="Discovery mode (default: refresh)",
)
@click.pass_context
def discover_services(ctx, host_name: str, mode: str):
    """Discover services on a host."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        # Start service discovery
        click.echo(
            f"🔍 Starting service discovery for host: {host_name} (mode: {mode})"
        )
        checkmk_client.start_service_discovery(host_name, mode)

        # Get discovery results
        discovery_result = checkmk_client.get_service_discovery_result(host_name)

        # Format response
        extensions = discovery_result.get("extensions", {})
        vanished = extensions.get("vanished", [])
        new = extensions.get("new", [])
        ignored = extensions.get("ignored", [])

        click.echo(f"✅ Service discovery completed for host: {host_name}")

        if new:
            click.echo(f"\n✨ New services found ({len(new)}):")
            for service in new:
                service_desc = service.get("service_description", "Unknown")
                click.echo(f"  + {service_desc}")

        if vanished:
            click.echo(f"\n👻 Vanished services ({len(vanished)}):")
            for service in vanished:
                service_desc = service.get("service_description", "Unknown")
                click.echo(f"  - {service_desc}")

        if ignored:
            click.echo(f"\n🚫 Ignored services ({len(ignored)}):")
            for service in ignored:
                service_desc = service.get("service_description", "Unknown")
                click.echo(f"  ! {service_desc}")

        if not new and not vanished and not ignored:
            click.echo("\n✅ No service changes detected")

    except Exception as e:
        click.echo(f"❌ Error discovering services: {e}", err=True)
        sys.exit(1)


@services.command("stats")
@click.pass_context
def service_stats(ctx):
    """Show service statistics."""
    service_manager = ctx.obj.get("service_manager")

    if not service_manager:
        # Fallback to basic stats without LLM
        checkmk_client = ctx.obj["checkmk_client"]
        try:
            services = checkmk_client.list_all_services()
            click.echo(f"📊 Total services: {len(services)}")
        except Exception as e:
            click.echo(f"❌ Error getting statistics: {e}", err=True)
        return

    result = service_manager.get_service_statistics()
    click.echo(result)


# Service parameter commands


@services.group("params")
def service_params():
    """Service parameter management commands."""
    pass


@service_params.command("defaults")
@click.argument("service_type", required=False, default="cpu")
@click.pass_context
def view_default_parameters(ctx, service_type: str):
    """View default parameters for a service type."""
    service_manager = ctx.obj.get("service_manager")

    if not service_manager:
        click.echo("❌ Service manager not available", err=True)
        sys.exit(1)

    # Use parameter manager directly
    from checkmk_mcp_server.service_parameters import ServiceParameterManager

    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]
    param_manager = ServiceParameterManager(checkmk_client, config)

    try:
        default_params = param_manager.get_default_parameters(service_type)

        if not default_params:
            click.echo(
                f"❌ No default parameters found for service type: {service_type}"
            )
            return

        click.echo(f"📊 Default Parameters for {service_type.upper()} services:")
        click.echo()

        if "levels" in default_params:
            warning, critical = default_params["levels"]
            click.echo(f"⚠️  Warning Threshold: {warning}%")
            click.echo(f"❌ Critical Threshold: {critical}%")

        if "average" in default_params:
            click.echo(f"📈 Averaging Period: {default_params['average']} minutes")

        if "magic_normsize" in default_params:
            click.echo(f"💾 Magic Normsize: {default_params['magic_normsize']} GB")

        if "magic" in default_params:
            click.echo(f"🎯 Magic Factor: {default_params['magic']}")

        # Show applicable ruleset
        ruleset_map = param_manager.PARAMETER_RULESETS.get(service_type, {})
        default_ruleset = ruleset_map.get("default", "Unknown")
        click.echo()
        click.echo(f"📋 Default Ruleset: {default_ruleset}")

    except Exception as e:
        click.echo(f"❌ Error viewing default parameters: {e}", err=True)
        sys.exit(1)


@service_params.command("show")
@click.argument("host_name")
@click.argument("service_description")
@click.pass_context
def view_service_parameters(ctx, host_name: str, service_description: str):
    """View effective parameters for a specific service."""
    service_manager = ctx.obj.get("service_manager")

    if not service_manager:
        click.echo("❌ Service manager not available", err=True)
        sys.exit(1)

    from checkmk_mcp_server.service_parameters import ServiceParameterManager

    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]
    param_manager = ServiceParameterManager(checkmk_client, config)

    try:
        param_info = param_manager.get_service_parameters(
            host_name, service_description
        )

        if param_info["source"] == "default":
            click.echo(f"📊 Parameters for {host_name}/{service_description}:")
            click.echo("📋 Using default parameters (no custom rules found)")
        else:
            click.echo(
                f"📊 Effective Parameters for {host_name}/{service_description}:"
            )
            click.echo()

            effective_params = param_info["parameters"]
            if "levels" in effective_params:
                warning, critical = effective_params["levels"]
                click.echo(f"⚠️  Warning: {warning}%")
                click.echo(f"❌ Critical: {critical}%")

            if "average" in effective_params:
                click.echo(f"📈 Average: {effective_params['average']} min")

            if "magic_normsize" in effective_params:
                click.echo(
                    f"💾 Magic Normsize: {effective_params['magic_normsize']} GB"
                )

            primary_rule = param_info.get("primary_rule")
            if primary_rule:
                rule_id = primary_rule.get("id", "Unknown")
                click.echo()
                click.echo(f"🔗 Source: Rule {rule_id}")

            # Show rule precedence if multiple rules
            all_rules = param_info.get("all_rules", [])
            if len(all_rules) > 1:
                click.echo()
                click.echo(f"📊 Rule Precedence ({len(all_rules)} rules):")
                for i, rule in enumerate(all_rules[:3], 1):
                    rule_id = rule.get("id", "Unknown")
                    is_primary = i == 1
                    status = "" if is_primary else " [OVERRIDDEN]"
                    click.echo(f"{i}. Rule {rule_id}{status}")

                if len(all_rules) > 3:
                    click.echo(f"... and {len(all_rules) - 3} more rules")

    except Exception as e:
        click.echo(f"❌ Error viewing service parameters: {e}", err=True)
        sys.exit(1)


@service_params.command("set")
@click.argument("host_name")
@click.argument("service_description")
@click.option("--warning", type=float, help="Warning threshold")
@click.option("--critical", type=float, help="Critical threshold")
@click.option("--comment", help="Comment for the rule")
@click.pass_context
def set_service_parameters(
    ctx,
    host_name: str,
    service_description: str,
    warning: float,
    critical: float,
    comment: str,
):
    """Set/override parameters for a service."""
    if not warning and not critical:
        click.echo(
            "❌ Please specify at least one of --warning or --critical", err=True
        )
        sys.exit(1)

    service_manager = ctx.obj.get("service_manager")

    if not service_manager:
        click.echo("❌ Service manager not available", err=True)
        sys.exit(1)

    from checkmk_mcp_server.service_parameters import ServiceParameterManager

    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]
    param_manager = ServiceParameterManager(checkmk_client, config)

    try:
        # Get current parameters to fill in missing values
        current_params = param_manager.get_service_parameters(
            host_name, service_description
        )
        current_levels = current_params.get("parameters", {}).get(
            "levels", (80.0, 90.0)
        )

        # Use provided values or fall back to current/default
        final_warning = (
            warning
            if warning is not None
            else (current_levels[0] if len(current_levels) > 0 else 80.0)
        )
        final_critical = (
            critical
            if critical is not None
            else (current_levels[1] if len(current_levels) > 1 else 90.0)
        )

        # Validate thresholds
        if final_warning >= final_critical:
            click.echo(
                "❌ Warning threshold must be less than critical threshold", err=True
            )
            sys.exit(1)

        # Create override
        final_comment = (
            comment or f"Override thresholds for {service_description} on {host_name}"
        )

        rule_id = param_manager.create_simple_override(
            host_name=host_name,
            service_name=service_description,
            warning=final_warning,
            critical=final_critical,
            comment=final_comment,
        )

        click.echo(
            f"✅ Created parameter override for {host_name}/{service_description}"
        )
        click.echo(f"⚠️  Warning: {final_warning}%")
        click.echo(f"❌ Critical: {final_critical}%")
        click.echo(f"🆔 Rule ID: {rule_id}")
        click.echo(f"💬 Comment: {final_comment}")
        click.echo("⏱️  Changes will take effect after next service check cycle")

    except Exception as e:
        click.echo(f"❌ Error setting service parameters: {e}", err=True)
        sys.exit(1)


@service_params.command("rules")
@click.option("--ruleset", help="Show rules for specific ruleset")
@click.pass_context
def list_parameter_rules(ctx, ruleset: str):
    """List parameter rules."""
    service_manager = ctx.obj.get("service_manager")

    if not service_manager:
        click.echo("❌ Service manager not available", err=True)
        sys.exit(1)

    from checkmk_mcp_server.service_parameters import ServiceParameterManager

    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]
    param_manager = ServiceParameterManager(checkmk_client, config)

    try:
        if not ruleset:
            # List available rulesets
            rulesets = param_manager.list_parameter_rulesets()

            click.echo(f"📋 Available Parameter Rulesets ({len(rulesets)}):")
            click.echo()

            # Group by category
            categories = {}
            for ruleset_obj in rulesets:
                ruleset_id = ruleset_obj.get("id", "Unknown")
                # Categorize based on name
                if "cpu" in ruleset_id:
                    categories.setdefault("CPU", []).append(ruleset_id)
                elif "memory" in ruleset_id:
                    categories.setdefault("Memory", []).append(ruleset_id)
                elif "filesystem" in ruleset_id:
                    categories.setdefault("Filesystem", []).append(ruleset_id)
                elif "interface" in ruleset_id or "network" in ruleset_id:
                    categories.setdefault("Network", []).append(ruleset_id)
                else:
                    categories.setdefault("Other", []).append(ruleset_id)

            for category, rulesets_list in categories.items():
                click.echo(f"📁 {category}:")
                for ruleset_id in rulesets_list:
                    click.echo(f"  📊 {ruleset_id}")
                click.echo()

            click.echo("💡 Use --ruleset <name> to see rules for a specific ruleset")
        else:
            # List rules for specific ruleset
            rules = checkmk_client.list_rules(ruleset)

            if not rules:
                click.echo(f"📋 No rules found for ruleset: {ruleset}")
                return

            click.echo(f"📋 Rules for {ruleset} ({len(rules)}):")
            click.echo()

            for rule in rules[:10]:  # Show first 10 rules
                rule_id = rule.get("id", "Unknown")
                extensions = rule.get("extensions", {})
                conditions = extensions.get("conditions", {})
                properties = extensions.get("properties", {})

                click.echo(f"🔧 Rule {rule_id}")

                # Show conditions
                if conditions.get("host_name"):
                    hosts = ", ".join(conditions["host_name"][:3])
                    if len(conditions["host_name"]) > 3:
                        hosts += f" (and {len(conditions['host_name']) - 3} more)"
                    click.echo(f"  🖥️  Hosts: {hosts}")

                if conditions.get("service_description"):
                    services = ", ".join(conditions["service_description"][:2])
                    if len(conditions["service_description"]) > 2:
                        services += (
                            f" (and {len(conditions['service_description']) - 2} more)"
                        )
                    click.echo(f"  🔧 Services: {services}")

                if properties.get("description"):
                    desc = properties["description"][:50]
                    if len(properties["description"]) > 50:
                        desc += "..."
                    click.echo(f"  💬 Description: {desc}")

                click.echo()

            if len(rules) > 10:
                click.echo(f"... and {len(rules) - 10} more rules")

    except Exception as e:
        click.echo(f"❌ Error listing parameter rules: {e}", err=True)
        sys.exit(1)


@service_params.command("discover")
@click.argument("host_name", required=False)
@click.argument("service_description")
@click.pass_context
def discover_ruleset(ctx, host_name: str, service_description: str):
    """Discover the appropriate ruleset for a service."""
    service_manager = ctx.obj.get("service_manager")

    if not service_manager:
        click.echo("❌ Service manager not available", err=True)
        sys.exit(1)

    from checkmk_mcp_server.service_parameters import ServiceParameterManager

    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]
    param_manager = ServiceParameterManager(checkmk_client, config)

    try:
        # Discover ruleset
        ruleset = param_manager.discover_service_ruleset(
            host_name or "unknown", service_description
        )

        if not ruleset:
            click.echo(
                f"❌ Could not determine appropriate ruleset for service: {service_description}"
            )
            return

        click.echo(f"🔍 Service: {service_description}")
        if host_name:
            click.echo(f"🖥️  Host: {host_name}")
        click.echo(f"📋 Recommended Ruleset: {ruleset}")
        click.echo()

        # Show default parameters for this ruleset
        service_type = (
            "cpu"
            if "cpu" in ruleset
            else (
                "memory"
                if "memory" in ruleset
                else "filesystem" if "filesystem" in ruleset else "network"
            )
        )
        default_params = param_manager.get_default_parameters(service_type)

        if default_params:
            click.echo("📊 Default Parameters:")
            if "levels" in default_params:
                warning, critical = default_params["levels"]
                click.echo(f"  ⚠️  Warning: {warning}%")
                click.echo(f"  ❌ Critical: {critical}%")

            if "average" in default_params:
                click.echo(f"  📈 Average: {default_params['average']} min")

        click.echo()
        click.echo(
            f"💡 To override parameters: checkmk-mcp-server services params set {host_name or 'HOSTNAME'} '{service_description}' --warning 85 --critical 95"
        )

    except Exception as e:
        click.echo(f"❌ Error discovering ruleset: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
@track_request(operation_name="CLI Stats Command")
def stats(ctx):
    """Show host statistics."""
    request_id = ctx.obj.get("request_id", generate_request_id())
    set_request_id(request_id)

    host_manager = ctx.obj.get("host_manager")

    if not host_manager:
        # Fallback to basic stats without LLM
        checkmk_client = ctx.obj["checkmk_client"]
        try:
            hosts = checkmk_client.list_hosts()
            click.echo(f"📊 Total hosts: {len(hosts)}")
        except Exception as e:
            click.echo(f"❌ Error getting statistics: {e}", err=True)
        return

    result = host_manager.get_host_statistics()
    click.echo(result)


@cli.group()
def status():
    """Service status monitoring commands."""
    pass


@status.command("overview")
@click.option(
    "--format",
    type=click.Choice(["table", "json", "detailed"]),
    default="detailed",
    help="Output format (default: detailed)",
)
@click.pass_context
def status_overview(ctx, format: str):
    """Show comprehensive service health dashboard."""
    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]

    try:
        from .service_status import ServiceStatusManager

        status_manager = ServiceStatusManager(checkmk_client, config)

        dashboard = status_manager.get_service_health_dashboard()

        if format == "json":
            import json

            click.echo(json.dumps(dashboard, indent=2))
            return

        # Display detailed dashboard
        overall_health = dashboard["overall_health"]
        problem_analysis = dashboard["problem_analysis"]

        click.echo("📊 Service Health Dashboard")
        click.echo("━" * 80)
        click.echo()

        # Overall health section
        health_pct = overall_health["health_percentage"]
        total_services = overall_health["total_services"]
        problems = overall_health["problems"]

        health_icon = (
            "🟢"
            if health_pct >= 95
            else "🟡" if health_pct >= 90 else "🟠" if health_pct >= 80 else "🔴"
        )
        click.echo(f"🏥 Overall Health: {health_pct:.1f}% {health_icon}")
        click.echo(f"📈 Total Services: {total_services}")

        if problems > 0:
            click.echo(f"⚠️  Problems: {problems} services need attention")
        else:
            click.echo("✅ No problems detected!")
        click.echo()

        # Service state distribution
        states = overall_health["states"]
        click.echo("📊 Service States:")
        click.echo(f"  ✅ OK: {states['ok']} services")
        if states["warning"] > 0:
            click.echo(f"  ⚠️  WARNING: {states['warning']} services")
        if states["critical"] > 0:
            click.echo(f"  ❌ CRITICAL: {states['critical']} services")
        if states["unknown"] > 0:
            click.echo(f"  ❓ UNKNOWN: {states['unknown']} services")
        click.echo()

        # Critical issues
        critical_issues = problem_analysis.get("critical", [])
        if critical_issues:
            click.echo("🔥 Critical Issues:")
            for issue in critical_issues[:5]:  # Show top 5
                host = issue["host_name"]
                service = issue["description"]
                output = (
                    issue["output"][:60] + "..."
                    if len(issue["output"]) > 60
                    else issue["output"]
                )
                ack_icon = "🔕" if issue["acknowledged"] else ""
                downtime_icon = "⏸️" if issue["in_downtime"] else ""
                click.echo(f"  ❌ {host}/{service} {ack_icon}{downtime_icon}")
                if output:
                    click.echo(f"     {output}")
            if len(critical_issues) > 5:
                click.echo(
                    f"     ... and {len(critical_issues) - 5} more critical issues"
                )
            click.echo()

        # Warning issues
        warning_issues = problem_analysis.get("warning", [])
        if warning_issues:
            click.echo("⚠️  Warning Issues:")
            for issue in warning_issues[:3]:  # Show top 3
                host = issue["host_name"]
                service = issue["description"]
                ack_icon = "🔕" if issue["acknowledged"] else ""
                downtime_icon = "⏸️" if issue["in_downtime"] else ""
                click.echo(f"  ⚠️  {host}/{service} {ack_icon}{downtime_icon}")
            if len(warning_issues) > 3:
                click.echo(f"     ... and {len(warning_issues) - 3} more warnings")
            click.echo()

        # Recommendations
        if dashboard.get("urgent_problems"):
            urgent_count = len(dashboard["urgent_problems"])
            click.echo(
                f"🚨 {urgent_count} urgent problem(s) require immediate attention"
            )
            click.echo("   Use 'checkmk-mcp-server status critical' for details")
            click.echo()

        unhandled = dashboard.get("needs_attention", 0)
        if unhandled > 0:
            click.echo(f"💡 {unhandled} unacknowledged problem(s) need review")
            click.echo("   Use 'checkmk-mcp-server status problems' to see all issues")

    except Exception as e:
        click.echo(f"❌ Error generating status overview: {e}", err=True)
        sys.exit(1)


@status.command("problems")
@click.option("--host", help="Filter by hostname")
@click.option(
    "--format",
    type=click.Choice(["table", "json", "detailed"]),
    default="table",
    help="Output format (default: table)",
)
@click.pass_context
def status_problems(ctx, host: Optional[str], format: str):
    """Show all service problems (WARNING, CRITICAL, UNKNOWN)."""
    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]

    try:
        from .service_status import ServiceStatusManager

        status_manager = ServiceStatusManager(checkmk_client, config)

        analysis = status_manager.analyze_service_problems(host)

        if format == "json":
            import json

            click.echo(json.dumps(analysis, indent=2))
            return

        total_problems = analysis["total_problems"]

        if total_problems == 0:
            click.echo("🎉 No service problems detected!")
            if host:
                click.echo(f"   All services on host '{host}' are OK")
            else:
                click.echo("   All services across all hosts are OK")
            return

        click.echo(f"🚨 Service Problems Report")
        if host:
            click.echo(f"   Host: {host}")
        click.echo(f"   Total Problems: {total_problems}")
        click.echo("━" * 60)
        click.echo()

        categories = analysis["categories"]

        # Critical issues
        critical_issues = categories.get("critical_issues", [])
        if critical_issues:
            click.echo(f"❌ CRITICAL ({len(critical_issues)}):")
            for service_key in critical_issues:
                click.echo(f"  🔴 {service_key}")
            click.echo()

        # Warning issues
        warning_issues = categories.get("warning_issues", [])
        if warning_issues:
            click.echo(f"⚠️  WARNING ({len(warning_issues)}):")
            for service_key in warning_issues:
                click.echo(f"  🟡 {service_key}")
            click.echo()

        # Problem categories
        disk_problems = categories.get("disk_problems", [])
        if disk_problems:
            click.echo(f"💾 Disk/Storage Issues ({len(disk_problems)}):")
            for service_key in disk_problems[:5]:
                click.echo(f"  💾 {service_key}")
            if len(disk_problems) > 5:
                click.echo(f"     ... and {len(disk_problems) - 5} more")
            click.echo()

        network_problems = categories.get("network_problems", [])
        if network_problems:
            click.echo(f"🌐 Network Issues ({len(network_problems)}):")
            for service_key in network_problems[:5]:
                click.echo(f"  🌐 {service_key}")
            if len(network_problems) > 5:
                click.echo(f"     ... and {len(network_problems) - 5} more")
            click.echo()

        # Show recommendations
        recommendations = analysis.get("recommendations", [])
        if recommendations:
            click.echo("💡 Recommendations:")
            for rec in recommendations:
                click.echo(f"  • {rec}")
            click.echo()

        unhandled_count = analysis.get("unhandled_count", 0)
        if unhandled_count > 0:
            click.echo(
                f"📋 {unhandled_count} problem(s) are unacknowledged and not in downtime"
            )
            click.echo(
                "   Consider acknowledging or creating downtime for ongoing issues"
            )

    except Exception as e:
        click.echo(f"❌ Error listing service problems: {e}", err=True)
        sys.exit(1)


@status.command("host")
@click.argument("host_name")
@click.option(
    "--format",
    type=click.Choice(["table", "json", "detailed", "dashboard"]),
    default="detailed",
    help="Output format (default: detailed)",
)
@click.option("--dashboard", is_flag=True, help="Show enhanced dashboard view")
@click.option("--problems-only", is_flag=True, help="Show only services with problems")
@click.option("--critical-only", is_flag=True, help="Show only critical services")
@click.option(
    "--category",
    type=click.Choice(
        ["disk", "network", "performance", "connectivity", "monitoring", "other"]
    ),
    help="Filter by problem category",
)
@click.option(
    "--sort-by",
    type=click.Choice(["severity", "name", "state"]),
    default="severity",
    help="Sort services by (default: severity)",
)
@click.option("--compact", is_flag=True, help="Show compact output without details")
@click.option("--no-ok-services", is_flag=True, help="Hide OK services from output")
@click.option("--limit", type=int, help="Limit number of services shown")
@click.pass_context
def status_host(
    ctx,
    host_name: str,
    format: str,
    dashboard: bool,
    problems_only: bool,
    critical_only: bool,
    category: str,
    sort_by: str,
    compact: bool,
    no_ok_services: bool,
    limit: int,
):
    """
    Show service status for a specific host with various filtering and formatting options.

    Args:
        ctx: Click context containing application state
        host_name: Name of the host to query
        format: Output format ('json', 'dashboard', or default text)
        dashboard: Whether to show enhanced dashboard view
        problems_only: Only show services with problems (non-OK state)
        critical_only: Only show services in critical state
        category: Filter by service category (e.g., 'disk', 'memory')
        sort_by: Sort services by specified criteria
        compact: Use compact output format
        no_ok_services: Exclude OK services from output
        limit: Maximum number of services to display
    """
    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]

    try:
        from .service_status import ServiceStatusManager

        status_manager = ServiceStatusManager(checkmk_client, config)

        # Use enhanced dashboard if requested
        if dashboard or format == "dashboard":
            host_dashboard = status_manager.get_host_status_dashboard(host_name)

            if format == "json":
                import json

                click.echo(json.dumps(host_dashboard, indent=2))
                return

            # Use UI manager for rich formatting
            from .interactive.ui_manager import UIManager

            ui_manager = UIManager()
            formatted_output = ui_manager.format_host_status_dashboard(host_dashboard)
            click.echo(formatted_output)
            return

        # Original detailed view
        host_status = status_manager.get_service_status_details(host_name, None)

        if format == "json":
            import json

            click.echo(json.dumps(host_status, indent=2))
            return

        if not host_status.get("found", True):
            click.echo(f"❌ Host '{host_name}' not found or has no services")
            click.echo("   💡 Tips:")
            click.echo("   • Check the hostname spelling (case-sensitive)")
            click.echo("   • Use 'hosts list' to see all available hosts")
            click.echo("   • Host may need to be created or configured first")
            return

        services = host_status.get("services", [])

        # Apply filtering options
        services = _filter_services_by_criteria(
            services,
            problems_only=problems_only,
            critical_only=critical_only,
            category=category,
            no_ok_services=no_ok_services,
        )
        host_status["services"] = services

        # Apply sorting
        if sort_by:
            services = _sort_services(services, sort_by)
            host_status["services"] = services

        # Apply limit
        if limit and limit > 0:
            services = services[:limit]
            host_status["services"] = services

        service_count = len(services)

        click.echo(f"🖥️  Service Status for Host: {host_name}")
        click.echo(f"   Total Services: {service_count}")
        click.echo("━" * 60)
        click.echo()

        # Group services by state
        states = {"ok": [], "warning": [], "critical": [], "unknown": []}

        for service in services:
            extensions = service.get("extensions", {})
            state = extensions.get("state", 0)
            description = extensions.get("description", "Unknown")
            acknowledged = extensions.get("acknowledged", 0) > 0
            in_downtime = extensions.get("scheduled_downtime_depth", 0) > 0
            output = extensions.get("plugin_output", "")

            service_info = {
                "description": description,
                "acknowledged": acknowledged,
                "in_downtime": in_downtime,
                "output": output[:80] + "..." if len(output) > 80 else output,
            }

            if state == 0:
                states["ok"].append(service_info)
            elif state == 1:
                states["warning"].append(service_info)
            elif state == 2:
                states["critical"].append(service_info)
            elif state == 3:
                states["unknown"].append(service_info)

        # Display by state (problems first)
        if compact:
            # Compact mode - just show service names with icons
            if states["critical"]:
                click.echo(f"❌ CRITICAL ({len(states['critical'])}):")
                for svc in states["critical"]:
                    ack_icon = " 🔕" if svc["acknowledged"] else ""
                    downtime_icon = " ⏸️" if svc["in_downtime"] else ""
                    click.echo(f"  🔴 {svc['description']}{ack_icon}{downtime_icon}")
                click.echo()

            if states["warning"]:
                click.echo(f"⚠️  WARNING ({len(states['warning'])}):")
                for svc in states["warning"]:
                    ack_icon = " 🔕" if svc["acknowledged"] else ""
                    downtime_icon = " ⏸️" if svc["in_downtime"] else ""
                    click.echo(f"  🟡 {svc['description']}{ack_icon}{downtime_icon}")
                click.echo()

            if states["unknown"]:
                click.echo(f"❓ UNKNOWN ({len(states['unknown'])}):")
                for svc in states["unknown"]:
                    ack_icon = " 🔕" if svc["acknowledged"] else ""
                    downtime_icon = " ⏸️" if svc["in_downtime"] else ""
                    click.echo(f"  🟤 {svc['description']}{ack_icon}{downtime_icon}")
                click.echo()

            if states["ok"] and not no_ok_services:
                display_count = min(5, len(states["ok"]))
                click.echo(
                    f"✅ OK ({len(states['ok'])}) - showing first {display_count}:"
                )
                for svc in states["ok"][:display_count]:
                    click.echo(f"  🟢 {svc['description']}")
                if len(states["ok"]) > display_count:
                    click.echo(
                        f"     ... and {len(states['ok']) - display_count} more OK services"
                    )
        else:
            # Detailed mode - show full output
            if states["critical"]:
                click.echo(f"❌ CRITICAL ({len(states['critical'])}):")
                for svc in states["critical"]:
                    ack_icon = " 🔕" if svc["acknowledged"] else ""
                    downtime_icon = " ⏸️" if svc["in_downtime"] else ""
                    click.echo(f"  🔴 {svc['description']}{ack_icon}{downtime_icon}")
                    if svc["output"]:
                        click.echo(f"     {svc['output']}")
                click.echo()

            if states["warning"]:
                click.echo(f"⚠️  WARNING ({len(states['warning'])}):")
                for svc in states["warning"]:
                    ack_icon = " 🔕" if svc["acknowledged"] else ""
                    downtime_icon = " ⏸️" if svc["in_downtime"] else ""
                    click.echo(f"  🟡 {svc['description']}{ack_icon}{downtime_icon}")
                    if svc["output"]:
                        click.echo(f"     {svc['output']}")
                click.echo()

            if states["unknown"]:
                click.echo(f"❓ UNKNOWN ({len(states['unknown'])}):")
                for svc in states["unknown"]:
                    ack_icon = " 🔕" if svc["acknowledged"] else ""
                    downtime_icon = " ⏸️" if svc["in_downtime"] else ""
                    click.echo(f"  🟤 {svc['description']}{ack_icon}{downtime_icon}")
                click.echo()

            if states["ok"] and not no_ok_services:
                click.echo(f"✅ OK ({len(states['ok'])}):")
                for svc in states["ok"][:10]:  # Show first 10 OK services
                    click.echo(f"  🟢 {svc['description']}")
                if len(states["ok"]) > 10:
                    click.echo(
                        f"     ... and {len(states['ok']) - 10} more OK services"
                    )

        # Summary
        problem_count = (
            len(states["critical"]) + len(states["warning"]) + len(states["unknown"])
        )
        if problem_count == 0:
            click.echo()
            click.echo(f"🎉 All {service_count} services on {host_name} are OK!")
        else:
            click.echo()
            click.echo(
                f"📊 Summary: {problem_count} problem(s), {len(states['ok'])} OK"
            )

    except Exception as e:
        click.echo(f"❌ Error getting host status: {e}", err=True)
        sys.exit(1)


@status.command("service")
@click.argument("host_name")
@click.argument("service_description")
@click.option(
    "--format",
    type=click.Choice(["table", "json", "detailed"]),
    default="detailed",
    help="Output format (default: detailed)",
)
@click.pass_context
def status_service(ctx, host_name: str, service_description: str, format: str):
    """Show detailed status for a specific service."""
    checkmk_client = ctx.obj["checkmk_client"]
    config = ctx.obj["config"]

    try:
        from .service_status import ServiceStatusManager

        status_manager = ServiceStatusManager(checkmk_client, config)

        service_details = status_manager.get_service_status_details(
            host_name, service_description
        )

        if format == "json":
            import json

            click.echo(json.dumps(service_details, indent=2))
            return

        if not service_details.get("found"):
            click.echo(
                f"❌ Service '{service_description}' not found on host '{host_name}'"
            )
            click.echo("   💡 Tips:")
            click.echo("   • Check the service name spelling (case-sensitive)")
            click.echo("   • Use 'services list <host>' to see all services")
            click.echo("   • Service may need to be discovered first")
            return

        state = service_details["state"]
        state_name = service_details["state_name"]
        acknowledged = service_details["acknowledged"]
        in_downtime = service_details["in_downtime"]
        output = service_details["plugin_output"]
        analysis = service_details["analysis"]

        # State icon
        state_icons = {0: "🟢", 1: "🟡", 2: "🔴", 3: "🟤"}
        state_icon = state_icons.get(state, "❓")

        click.echo(f"📊 Service Status Details")
        click.echo("━" * 50)
        click.echo(f"🖥️  Host: {host_name}")
        click.echo(f"🔧 Service: {service_description}")
        click.echo(f"{state_icon} State: {state_name}")

        if acknowledged:
            click.echo("🔕 Acknowledged: Yes")
        if in_downtime:
            click.echo("⏸️  In Downtime: Yes")

        click.echo(f"⏰ Last Check: {analysis.get('last_check_ago', 'Unknown')}")

        if analysis.get("is_problem"):
            severity = analysis.get("severity", "Unknown")
            urgency = analysis.get("urgency_score", 0)
            click.echo(f"⚡ Severity: {severity}")
            click.echo(f"🎯 Urgency Score: {urgency}/10")

            if analysis.get("requires_action"):
                click.echo("🚨 Requires Action: Yes (unacknowledged problem)")
            else:
                click.echo("✅ Handled: Problem is acknowledged or in downtime")

        click.echo()
        click.echo("💬 Service Output:")
        if output:
            # Format output nicely
            lines = output.split("\n")
            for line in lines[:5]:  # Show first 5 lines
                click.echo(f"   {line}")
            if len(lines) > 5:
                click.echo(f"   ... and {len(lines) - 5} more lines")
        else:
            click.echo("   No output available")

        # Show action suggestions
        if analysis.get("requires_action"):
            click.echo()
            click.echo("💡 Suggested Actions:")
            click.echo(
                f"   • Acknowledge: checkmk-mcp-server services acknowledge {host_name} '{service_description}'"
            )
            click.echo(
                f"   • Create downtime: checkmk-mcp-server services downtime {host_name} '{service_description}' --hours 2"
            )

    except Exception as e:
        click.echo(f"❌ Error getting service status: {e}", err=True)
        sys.exit(1)


@status.command("critical")
@click.option("--host", help="Filter by hostname")
@click.option(
    "--format",
    type=click.Choice(["table", "json", "list"]),
    default="list",
    help="Output format (default: list)",
)
@click.pass_context
def status_critical(ctx, host: Optional[str], format: str):
    """Show only critical services."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        critical_services = checkmk_client.get_services_by_state(
            2, host
        )  # State 2 = CRITICAL

        if format == "json":
            import json

            click.echo(json.dumps(critical_services, indent=2))
            return

        if not critical_services:
            if host:
                click.echo(f"🎉 No critical services found on host: {host}")
            else:
                click.echo("🎉 No critical services found!")
            return

        click.echo(f"🔴 Critical Services ({len(critical_services)}):")
        if host:
            click.echo(f"   Host Filter: {host}")
        click.echo("━" * 60)
        click.echo()

        for service in critical_services:
            extensions = service.get("extensions", {})
            host_name = extensions.get("host_name", "Unknown")
            description = extensions.get("description", "Unknown")
            output = extensions.get("plugin_output", "")
            acknowledged = extensions.get("acknowledged", 0) > 0
            in_downtime = extensions.get("scheduled_downtime_depth", 0) > 0

            # Status indicators
            ack_icon = " 🔕" if acknowledged else ""
            downtime_icon = " ⏸️" if in_downtime else ""

            click.echo(f"❌ {host_name}/{description}{ack_icon}{downtime_icon}")

            if output:
                # Show first line of output
                first_line = output.split("\n")[0]
                if len(first_line) > 70:
                    first_line = first_line[:67] + "..."
                click.echo(f"   {first_line}")
            click.echo()

        # Show summary with action suggestions
        unhandled = len(
            [
                s
                for s in critical_services
                if not (
                    s.get("extensions", {}).get("acknowledged", 0) > 0
                    or s.get("extensions", {}).get("scheduled_downtime_depth", 0) > 0
                )
            ]
        )

        if unhandled > 0:
            click.echo(f"🚨 {unhandled} critical service(s) need immediate attention!")
            click.echo(
                "💡 Consider acknowledging ongoing issues or creating downtime for maintenance"
            )
        else:
            click.echo(
                "✅ All critical services are acknowledged or in planned downtime"
            )

    except Exception as e:
        click.echo(f"❌ Error listing critical services: {e}", err=True)
        sys.exit(1)


@status.command("acknowledged")
@click.option(
    "--format",
    type=click.Choice(["table", "json", "list"]),
    default="list",
    help="Output format (default: list)",
)
@click.pass_context
def status_acknowledged(ctx, format: str):
    """Show acknowledged service problems."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        ack_services = checkmk_client.get_acknowledged_services()

        if format == "json":
            import json

            click.echo(json.dumps(ack_services, indent=2))
            return

        if not ack_services:
            click.echo("📋 No acknowledged service problems found")
            return

        click.echo(f"🔕 Acknowledged Service Problems ({len(ack_services)}):")
        click.echo("━" * 60)
        click.echo()

        for service in ack_services:
            extensions = service.get("extensions", {})
            host_name = extensions.get("host_name", "Unknown")
            description = extensions.get("description", "Unknown")
            state = extensions.get("state", 0)
            output = extensions.get("plugin_output", "")

            # State icon
            state_icons = {0: "🟢", 1: "🟡", 2: "🔴", 3: "🟤"}
            state_icon = state_icons.get(state, "❓")

            click.echo(f"{state_icon} {host_name}/{description} 🔕")

            if output:
                first_line = output.split("\n")[0]
                if len(first_line) > 70:
                    first_line = first_line[:67] + "..."
                click.echo(f"   {first_line}")
            click.echo()

        click.echo(
            "💡 Acknowledged problems are being tracked but notifications are suppressed"
        )

    except Exception as e:
        click.echo(f"❌ Error listing acknowledged services: {e}", err=True)
        sys.exit(1)


@status.command("downtime")
@click.option(
    "--format",
    type=click.Choice(["table", "json", "list"]),
    default="list",
    help="Output format (default: list)",
)
@click.pass_context
def status_downtime(ctx, format: str):
    """Show services currently in scheduled downtime."""
    checkmk_client = ctx.obj["checkmk_client"]

    try:
        downtime_services = checkmk_client.get_services_in_downtime()

        if format == "json":
            import json

            click.echo(json.dumps(downtime_services, indent=2))
            return

        if not downtime_services:
            click.echo("📋 No services currently in scheduled downtime")
            return

        click.echo(f"⏸️  Services in Scheduled Downtime ({len(downtime_services)}):")
        click.echo("━" * 60)
        click.echo()

        for service in downtime_services:
            extensions = service.get("extensions", {})
            host_name = extensions.get("host_name", "Unknown")
            description = extensions.get("description", "Unknown")
            state = extensions.get("state", 0)
            downtime_depth = extensions.get("scheduled_downtime_depth", 0)

            # State icon
            state_icons = {0: "🟢", 1: "🟡", 2: "🔴", 3: "🟤"}
            state_icon = state_icons.get(state, "❓")

            depth_info = f" (depth: {downtime_depth})" if downtime_depth > 1 else ""
            click.echo(f"{state_icon} {host_name}/{description} ⏸️ {depth_info}")

        click.echo()
        click.echo(
            "💡 Services in downtime suppress notifications during maintenance windows"
        )

    except Exception as e:
        click.echo(f"❌ Error listing services in downtime: {e}", err=True)
        sys.exit(1)


def process_status_command(user_input: str, status_manager, intent) -> str:
    """
    Process natural language status commands using the ServiceStatusManager.

    Args:
        user_input: Original user input
        status_manager: ServiceStatusManager instance
        intent: Parsed command intent

    Returns:
        Formatted status response
    """
    user_lower = user_input.lower()

    # Dashboard/overview commands
    if any(keyword in user_lower for keyword in ["dashboard", "overview", "health"]):
        dashboard = status_manager.get_service_health_dashboard()
        return format_dashboard_output(dashboard)

    # Check for specific critical patterns first (before general problems)
    if any(
        pattern in user_lower
        for pattern in [
            "critical problems",
            "critical issues",
            "show critical",
            "list critical",
        ]
    ):
        host_filter = intent.parameters.get("host_name")
        critical_services = status_manager.find_services_by_criteria(
            {"state": 2, "host_filter": host_filter}
        )
        return format_critical_services_output(critical_services, host_filter)

    # Check for specific warning patterns
    if any(
        pattern in user_lower
        for pattern in [
            "warning problems",
            "warning issues",
            "show warning",
            "list warning",
        ]
    ):
        host_filter = intent.parameters.get("host_name")
        warning_services = status_manager.find_services_by_criteria(
            {"state": 1, "host_filter": host_filter}
        )
        return format_warning_services_output(warning_services, host_filter)

    # General problem analysis commands (after specific patterns)
    if any(
        keyword in user_lower for keyword in ["problems", "issues", "errors"]
    ) and not any(specific in user_lower for specific in ["critical", "warning"]):
        host_filter = intent.parameters.get("host_name")
        analysis = status_manager.analyze_service_problems(host_filter)
        return format_problems_output(analysis, host_filter)

    # Critical services commands (fallback for just "critical")
    if "critical" in user_lower and not any(
        word in user_lower for word in ["problems", "issues"]
    ):
        host_filter = intent.parameters.get("host_name")
        critical_services = status_manager.find_services_by_criteria(
            {"state": 2, "host_filter": host_filter}
        )
        return format_critical_services_output(critical_services, host_filter)

    # Acknowledged services commands
    if "acknowledged" in user_lower:
        ack_services = status_manager.find_services_by_criteria({"acknowledged": True})
        return format_acknowledged_services_output(ack_services)

    # Downtime services commands
    if "downtime" in user_lower:
        downtime_services = status_manager.find_services_by_criteria(
            {"in_downtime": True}
        )
        return format_downtime_services_output(downtime_services)

    # Host-specific status commands
    host_name = intent.parameters.get("host_name")
    if host_name:
        service_name = intent.parameters.get("service_description")
        if service_name:
            # Specific service status
            details = status_manager.get_service_status_details(host_name, service_name)
            return format_service_details_output(details)
        else:
            # Check if this is a request for enhanced dashboard
            original_input = getattr(intent, "original_input", "").lower()
            if any(
                keyword in original_input
                for keyword in ["dashboard", "health", "enhanced", "detailed"]
            ):
                # Use enhanced dashboard for richer analysis
                from .interactive.ui_manager import UIManager

                ui_manager = UIManager()
                host_dashboard = status_manager.get_host_status_dashboard(host_name)
                return ui_manager.format_host_status_dashboard(host_dashboard)
            else:
                # All services on host (original format)
                host_status = status_manager.get_service_status_details(host_name, None)
                return format_host_status_output(host_status)

    # Default to general summary
    summary = status_manager.generate_status_summary()
    return format_status_summary_output(summary)


def format_dashboard_output(dashboard: dict) -> str:
    """Format service health dashboard for display."""
    overall_health = dashboard["overall_health"]
    problem_analysis = dashboard["problem_analysis"]

    result = "📊 Service Health Dashboard\n"
    result += "━" * 50 + "\n\n"

    # Overall health
    health_pct = overall_health["health_percentage"]
    total_services = overall_health["total_services"]
    problems = overall_health["problems"]

    health_icon = (
        "🟢"
        if health_pct >= 95
        else "🟡" if health_pct >= 90 else "🟠" if health_pct >= 80 else "🔴"
    )
    result += f"🏥 Overall Health: {health_pct:.1f}% {health_icon}\n"
    result += f"📈 Total Services: {total_services}\n"

    if problems > 0:
        result += f"⚠️  Problems: {problems} services need attention\n"
    else:
        result += "✅ No problems detected!\n"
    result += "\n"

    # Service states
    states = overall_health["states"]
    result += "📊 Service States:\n"
    result += f"  ✅ OK: {states['ok']} services\n"
    if states["warning"] > 0:
        result += f"  ⚠️  WARNING: {states['warning']} services\n"
    if states["critical"] > 0:
        result += f"  ❌ CRITICAL: {states['critical']} services\n"
    if states["unknown"] > 0:
        result += f"  ❓ UNKNOWN: {states['unknown']} services\n"

    # Critical issues
    critical_issues = problem_analysis.get("critical", [])
    if critical_issues:
        result += "\n🔥 Critical Issues:\n"
        for issue in critical_issues[:5]:
            host = issue["host_name"]
            service = issue["description"]
            ack_icon = "🔕" if issue["acknowledged"] else ""
            downtime_icon = "⏸️" if issue["in_downtime"] else ""
            result += f"  ❌ {host}/{service} {ack_icon}{downtime_icon}\n"
        if len(critical_issues) > 5:
            result += f"     ... and {len(critical_issues) - 5} more critical issues\n"

    return result


def format_problems_output(analysis: dict, host_filter: str = None) -> str:
    """Format service problems analysis for display."""
    total_problems = analysis["total_problems"]

    if total_problems == 0:
        result = "🎉 No service problems detected!\n"
        if host_filter:
            result += f"   All services on host '{host_filter}' are OK"
        else:
            result += "   All services across all hosts are OK"
        return result

    result = "🚨 Service Problems Report\n"
    if host_filter:
        result += f"   Host: {host_filter}\n"
    result += f"   Total Problems: {total_problems}\n"
    result += "━" * 40 + "\n\n"

    categories = analysis["categories"]

    # Critical issues
    critical_issues = categories.get("critical_issues", [])
    if critical_issues:
        result += f"❌ CRITICAL ({len(critical_issues)}):\n"
        for service_key in critical_issues[:10]:
            result += f"  🔴 {service_key}\n"
        if len(critical_issues) > 10:
            result += f"     ... and {len(critical_issues) - 10} more\n"
        result += "\n"

    # Warning issues
    warning_issues = categories.get("warning_issues", [])
    if warning_issues:
        result += f"⚠️  WARNING ({len(warning_issues)}):\n"
        for service_key in warning_issues[:10]:
            result += f"  🟡 {service_key}\n"
        if len(warning_issues) > 10:
            result += f"     ... and {len(warning_issues) - 10} more\n"
        result += "\n"

    # Recommendations
    recommendations = analysis.get("recommendations", [])
    if recommendations:
        result += "💡 Recommendations:\n"
        for rec in recommendations:
            result += f"  • {rec}\n"

    return result


def format_critical_services_output(services: list, host_filter: str = None) -> str:
    """Format critical services list for display."""
    if not services:
        if host_filter:
            return f"🎉 No critical services found on host: {host_filter}"
        else:
            return "🎉 No critical services found!"

    result = f"🔴 Critical Services ({len(services)}):\n"
    if host_filter:
        result += f"   Host Filter: {host_filter}\n"
    result += "━" * 40 + "\n\n"

    for service in services:
        extensions = service.get("extensions", {})
        host_name = extensions.get("host_name", "Unknown")
        description = extensions.get("description", "Unknown")
        acknowledged = extensions.get("acknowledged", 0) > 0
        in_downtime = extensions.get("scheduled_downtime_depth", 0) > 0

        ack_icon = " 🔕" if acknowledged else ""
        downtime_icon = " ⏸️" if in_downtime else ""
        result += f"❌ {host_name}/{description}{ack_icon}{downtime_icon}\n"

    return result


def format_warning_services_output(services: list, host_filter: str = None) -> str:
    """Format warning services list for display."""
    if not services:
        if host_filter:
            return f"🎉 No warning services found on host: {host_filter}"
        else:
            return "🎉 No warning services found!"

    result = f"🟡 Warning Services ({len(services)}):\n"
    if host_filter:
        result += f"   Host Filter: {host_filter}\n"
    result += "━" * 40 + "\n\n"

    for service in services:
        extensions = service.get("extensions", {})
        host_name = extensions.get("host_name", "Unknown")
        description = extensions.get("description", "Unknown")
        acknowledged = extensions.get("acknowledged", 0) > 0
        in_downtime = extensions.get("scheduled_downtime_depth", 0) > 0

        ack_icon = " 🔕" if acknowledged else ""
        downtime_icon = " ⏸️" if in_downtime else ""
        result += f"⚠️  {host_name}/{description}{ack_icon}{downtime_icon}\n"

    return result


def format_acknowledged_services_output(services: list) -> str:
    """Format acknowledged services list for display."""
    if not services:
        return "📋 No acknowledged service problems found"

    result = f"🔕 Acknowledged Service Problems ({len(services)}):\n"
    result += "━" * 40 + "\n\n"

    for service in services:
        extensions = service.get("extensions", {})
        host_name = extensions.get("host_name", "Unknown")
        description = extensions.get("description", "Unknown")
        state = extensions.get("state", 0)

        state_icons = {0: "🟢", 1: "🟡", 2: "🔴", 3: "🟤"}
        state_icon = state_icons.get(state, "❓")
        result += f"{state_icon} {host_name}/{description} 🔕\n"

    return result


def format_downtime_services_output(services: list) -> str:
    """Format services in downtime list for display."""
    if not services:
        return "📋 No services currently in scheduled downtime"

    result = f"⏸️  Services in Scheduled Downtime ({len(services)}):\n"
    result += "━" * 40 + "\n\n"

    for service in services:
        extensions = service.get("extensions", {})
        host_name = extensions.get("host_name", "Unknown")
        description = extensions.get("description", "Unknown")
        state = extensions.get("state", 0)

        state_icons = {0: "🟢", 1: "🟡", 2: "🔴", 3: "🟤"}
        state_icon = state_icons.get(state, "❓")
        result += f"{state_icon} {host_name}/{description} ⏸️\n"

    return result


def format_service_details_output(details: dict) -> str:
    """Format detailed service status for display."""
    if not details.get("found"):
        return f"❌ Service '{details.get('service_description')}' not found on host '{details.get('host_name')}'"

    state = details["state"]
    state_name = details["state_name"]
    host_name = details["host_name"]
    service_description = details["service_description"]
    acknowledged = details["acknowledged"]
    in_downtime = details["in_downtime"]
    output = details["plugin_output"]
    analysis = details["analysis"]

    state_icons = {0: "🟢", 1: "🟡", 2: "🔴", 3: "🟤"}
    state_icon = state_icons.get(state, "❓")

    result = f"📊 Service Status Details\n"
    result += "━" * 30 + "\n"
    result += f"🖥️  Host: {host_name}\n"
    result += f"🔧 Service: {service_description}\n"
    result += f"{state_icon} State: {state_name}\n"

    if acknowledged:
        result += "🔕 Acknowledged: Yes\n"
    if in_downtime:
        result += "⏸️  In Downtime: Yes\n"

    result += f"⏰ Last Check: {analysis.get('last_check_ago', 'Unknown')}\n"

    if analysis.get("is_problem"):
        severity = analysis.get("severity", "Unknown")
        urgency = analysis.get("urgency_score", 0)
        result += f"⚡ Severity: {severity}\n"
        result += f"🎯 Urgency Score: {urgency}/10\n"

    if output:
        result += f"\n💬 Output: {output[:100]}"
        if len(output) > 100:
            result += "..."

    return result


def _filter_services_by_criteria(
    services: List[Dict],
    problems_only: bool = False,
    critical_only: bool = False,
    category: str = None,
    no_ok_services: bool = False,
) -> List[Dict]:
    """
    Filter services based on various criteria.

    Args:
        services: List of service dictionaries
        problems_only: Only include services with problems
        critical_only: Only include critical services
        category: Filter by service category
        no_ok_services: Exclude OK services

    Returns:
        Filtered list of services
    """
    if not any([problems_only, critical_only, category, no_ok_services]):
        return services

    filtered_services = []

    for service in services:
        extensions = service.get("extensions", {})
        state = extensions.get("state", 0)
        description = extensions.get("description", "").lower()
        output = extensions.get("plugin_output", "").lower()

        # Apply filters
        if critical_only and state != 2:
            continue

        if problems_only and state == 0:
            continue

        if no_ok_services and state == 0:
            continue

        if category:
            if not _service_matches_category(description, output, category):
                continue

        filtered_services.append(service)

    return filtered_services


def _service_matches_category(description: str, output: str, category: str) -> bool:
    """Check if a service matches the specified problem category."""
    category_keywords = {
        "disk": ["disk", "filesystem", "storage", "mount", "space", "df"],
        "network": ["network", "interface", "ping", "port", "tcp", "udp", "connection"],
        "performance": ["cpu", "memory", "load", "performance", "utilization", "usage"],
        "connectivity": ["connection", "timeout", "refused", "unreachable", "down"],
        "monitoring": ["check_mk", "agent", "monitoring", "snmp", "checkmk"],
        "other": [],  # Will match anything not in other categories
    }

    if category == "other":
        # Check if it doesn't match any other category
        for cat, keywords in category_keywords.items():
            if cat != "other" and any(
                keyword in description or keyword in output for keyword in keywords
            ):
                return False
        return True

    keywords = category_keywords.get(category, [])
    return any(keyword in description or keyword in output for keyword in keywords)


def _sort_services(services: list, sort_by: str) -> list:
    """Sort services by the specified criteria."""
    if sort_by == "severity":
        # Sort by state (critical first), then by name
        state_priority = {2: 0, 1: 1, 3: 2, 0: 3}  # Critical, Warning, Unknown, OK
        return sorted(
            services,
            key=lambda s: (
                state_priority.get(s.get("extensions", {}).get("state", 0), 3),
                s.get("extensions", {}).get("description", "").lower(),
            ),
        )
    elif sort_by == "name":
        # Sort alphabetically by service description
        return sorted(
            services,
            key=lambda s: s.get("extensions", {}).get("description", "").lower(),
        )
    elif sort_by == "state":
        # Sort by state value (0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN)
        return sorted(services, key=lambda s: s.get("extensions", {}).get("state", 0))
    else:
        return services


def format_host_status_output(host_status: dict) -> str:
    """Format host service status for display."""
    if not host_status.get("found", True):
        return f"❌ Host '{host_status.get('host_name')}' not found or has no services"

    host_name = host_status["host_name"]
    services = host_status.get("services", [])
    service_count = len(services)

    result = f"🖥️  Service Status for Host: {host_name}\n"
    result += f"   Total Services: {service_count}\n"
    result += "━" * 40 + "\n\n"

    # Group by state
    states = {"ok": 0, "warning": 0, "critical": 0, "unknown": 0}
    problem_services = []

    for service in services:
        extensions = service.get("extensions", {})
        state = extensions.get("state", 0)
        description = extensions.get("description", "Unknown")

        if state == 0:
            states["ok"] += 1
        elif state == 1:
            states["warning"] += 1
            problem_services.append(f"⚠️  {description}")
        elif state == 2:
            states["critical"] += 1
            problem_services.append(f"❌ {description}")
        elif state == 3:
            states["unknown"] += 1
            problem_services.append(f"❓ {description}")

    # Show summary
    result += f"📊 Summary:\n"
    result += f"  ✅ OK: {states['ok']} services\n"
    if states["warning"] > 0:
        result += f"  ⚠️  WARNING: {states['warning']} services\n"
    if states["critical"] > 0:
        result += f"  ❌ CRITICAL: {states['critical']} services\n"
    if states["unknown"] > 0:
        result += f"  ❓ UNKNOWN: {states['unknown']} services\n"

    # Show problem services
    if problem_services:
        result += f"\n🚨 Problem Services:\n"
        for svc in problem_services[:10]:
            result += f"  {svc}\n"
        if len(problem_services) > 10:
            result += f"     ... and {len(problem_services) - 10} more\n"
    else:
        result += f"\n🎉 All {service_count} services on {host_name} are OK!"

    return result


def format_status_summary_output(summary: dict) -> str:
    """Format status summary for display."""
    total_services = summary["total_services"]
    health_pct = summary["health_percentage"]
    problems = summary["problems"]
    status_icon = summary["status_icon"]
    status_message = summary["status_message"]

    result = f"📊 Status Summary\n"
    result += "━" * 20 + "\n"
    result += f"{status_icon} Health: {health_pct}%\n"
    result += f"📈 Total Services: {total_services}\n"
    result += f"📋 {status_message}\n"

    if problems > 0:
        critical = summary.get("critical", 0)
        warning = summary.get("warning", 0)
        if critical > 0:
            result += f"❌ Critical: {critical}\n"
        if warning > 0:
            result += f"⚠️  Warning: {warning}\n"

    return result




def show_help():
    """Show detailed help information."""
    click.echo(
        """
🔧 Available Commands:

Natural Language Commands - Host Management:
  - "list all hosts" / "show hosts"
  - "create host server01 in folder /web"
  - "delete host server01"
  - "show details for server01"

Natural Language Commands - Service Management:
  - "list services for server01" / "show all services"
  - "acknowledge CPU load on server01"
  - "create downtime for disk space on server01"
  - "discover services on server01"

Special Commands:
  - help/h        Show this help
  - stats         Show host statistics
  - test          Test API connection
  - exit/quit/q   Exit interactive mode

Examples:
  🔧 checkmk> list all hosts
  🔧 checkmk> create host web01 with ip 192.168.1.10
  🔧 checkmk> show services for web01
  🔧 checkmk> acknowledge CPU load on web01 with comment "investigating"
  🔧 checkmk> create 4 hour downtime for disk space on web01
  🔧 checkmk> discover services on web01
"""
    )


# Import and register historical commands
try:
    from .commands.historical_commands import historical
    cli.add_command(historical)
except ImportError as e:
    # Historical commands not available, continue without them
    logging.debug(f"Historical commands not available: {e}")


if __name__ == "__main__":
    cli()
