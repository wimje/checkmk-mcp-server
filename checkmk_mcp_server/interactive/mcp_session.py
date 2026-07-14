"""Interactive session implementation for MCP-based CLI."""

import asyncio
import logging
import sys
from typing import Optional, Dict, Any, List
from datetime import datetime

import click

from ..mcp_client import CheckmkMCPClient
from ..formatters import CLIFormatter
from ..config import AppConfig
from .readline_handler import ReadlineHandler
from .command_parser import CommandParser
from .help_system import HelpSystem


logger = logging.getLogger(__name__)


class InteractiveSession:
    """Interactive session manager for MCP-based CLI."""

    def __init__(
        self, mcp_client: CheckmkMCPClient, formatter: CLIFormatter, config: AppConfig
    ):
        self.mcp_client = mcp_client
        self.formatter = formatter
        self.config = config

        # Initialize components
        self.readline_handler = ReadlineHandler()
        self.command_parser = CommandParser()
        self.help_system = HelpSystem()

        # Session state
        self.context = {
            "last_host": None,
            "last_service": None,
            "session_start": datetime.now(),
        }

    async def run(
        self, initial_prompt: Optional[str] = None, load_history: bool = True
    ):
        """Run the interactive session."""
        # Readline history is already loaded by ReadlineHandler's constructor
        # (_setup_readline/_load_history); nothing extra to do for load_history.

        # Process initial prompt if provided
        if initial_prompt:
            await self.process_command(initial_prompt)

        # Main interaction loop
        while True:
            try:
                # Get user input
                user_input = input(self.formatter.format_prompt("checkmk> "))

                if not user_input.strip():
                    continue

                # Save to history
                self.readline_handler.add_history(user_input)

                # Process the command
                should_exit = await self.process_command(user_input.strip())

                if should_exit:
                    break

            except KeyboardInterrupt:
                click.echo("\nUse 'exit' to quit.")
            except EOFError:
                click.echo()
                break
            except Exception as e:
                logger.exception("Error in interactive session")
                click.echo(self.formatter.format_error(f"Error: {str(e)}"))

        # Save history on exit
        self.readline_handler.save_history()
        click.echo("\nGoodbye!")

    async def process_command(self, command: str) -> bool:
        """Process a single command. Returns True if should exit."""
        # Check for exit commands
        if command.lower() in ["exit", "quit", "bye"]:
            return True

        # Check for help
        if command.lower() in ["help", "?"]:
            self.show_help()
            return False

        # Classify the command: inputs starting with a known command group
        # are structured (e.g. "hosts list", "status problems"); everything
        # else is treated as natural language. (CommandParser belongs to the
        # direct CLI and has a different interface -- parse_command() /
        # CommandIntent -- so it isn't used here.)
        tokens = command.split()
        if tokens and tokens[0].lower() in ("hosts", "services", "status"):
            parsed = {
                "type": "structured",
                "command": tokens[0].lower(),
                "args": tokens[1:],
                "options": {},
            }
            await self.handle_structured_command(parsed)
        else:
            await self.handle_natural_language(command)

        return False

    async def handle_natural_language(self, query: str):
        """Handle natural language queries using MCP tools."""
        try:
            # Analyze the query to determine intent
            intent = self._analyze_query_intent(query)

            if intent["action"] == "list_hosts":
                await self._list_hosts(intent.get("filter"))

            elif intent["action"] == "show_host":
                await self._show_host_details(intent["host_name"])

            elif intent["action"] == "list_services":
                await self._list_services(
                    intent.get("host_name"), intent.get("state_filter")
                )

            elif intent["action"] == "show_problems":
                await self._show_problems(
                    intent.get("host_name"), intent.get("critical_only")
                )

            elif intent["action"] == "health_dashboard":
                await self._show_health_dashboard(intent.get("problems_only"))

            elif intent["action"] == "analyze_host":
                await self._analyze_host(intent["host_name"])

            elif intent["action"] == "acknowledge":
                await self._acknowledge_service(
                    intent["host_name"],
                    intent["service_name"],
                    intent.get("comment", "Acknowledged via interactive mode"),
                )

            elif intent["action"] == "downtime":
                await self._create_downtime(
                    intent["host_name"],
                    intent["service_name"],
                    intent.get("duration", 2.0),
                    intent.get("comment", "Scheduled via interactive mode"),
                )

            else:
                # Fallback to AI analysis
                await self._ai_analysis(query, intent)

        except Exception as e:
            logger.exception("Error handling natural language query")
            click.echo(self.formatter.format_error(f"Error: {str(e)}"))

    async def handle_structured_command(self, parsed: Dict[str, Any]):
        """Handle structured commands."""
        command = parsed["command"]
        args = parsed.get("args", [])
        options = parsed.get("options", {})

        try:
            if command == "hosts":
                if args and args[0] == "list":
                    await self._list_hosts(options.get("search"))
                elif args and args[0] == "show":
                    if len(args) > 1:
                        await self._show_host_details(args[1])
                    else:
                        click.echo(self.formatter.format_error("Host name required"))

            elif command == "services":
                if args and args[0] == "list":
                    host_name = args[1] if len(args) > 1 else None
                    await self._list_services(host_name)
                elif args and args[0] == "acknowledge":
                    if len(args) > 2:
                        await self._acknowledge_service(args[1], args[2])
                    else:
                        click.echo(
                            self.formatter.format_error(
                                "Host and service names required"
                            )
                        )

            elif command == "status":
                if args and args[0] == "dashboard":
                    await self._show_health_dashboard()
                elif args and args[0] == "problems":
                    await self._show_problems()

            else:
                click.echo(self.formatter.format_error(f"Unknown command: {command}"))

        except Exception as e:
            logger.exception("Error handling structured command")
            click.echo(self.formatter.format_error(f"Error: {str(e)}"))

    def _analyze_query_intent(self, query: str) -> Dict[str, Any]:
        """Analyze natural language query to determine intent."""
        query_lower = query.lower()

        # Host listing
        if any(
            phrase in query_lower
            for phrase in ["list hosts", "show hosts", "all hosts"]
        ):
            return {"action": "list_hosts", "filter": self._extract_filter(query)}

        # Host details
        if any(
            phrase in query_lower
            for phrase in ["show host", "host details", "info about"]
        ):
            host_name = self._extract_host_name(query)
            if host_name:
                return {"action": "show_host", "host_name": host_name}

        # Service listing
        if any(
            phrase in query_lower
            for phrase in ["list services", "show services", "services on"]
        ):
            return {
                "action": "list_services",
                "host_name": self._extract_host_name(query),
                "state_filter": self._extract_state_filter(query),
            }

        # Problems
        if any(
            phrase in query_lower
            for phrase in ["show problems", "critical problems", "issues", "errors"]
        ):
            return {
                "action": "show_problems",
                "host_name": self._extract_host_name(query),
                "critical_only": "critical" in query_lower,
            }

        # Health dashboard
        if any(
            phrase in query_lower
            for phrase in ["health", "dashboard", "overview", "status"]
        ):
            return {
                "action": "health_dashboard",
                "problems_only": "problem" in query_lower,
            }

        # Host analysis
        if any(
            phrase in query_lower for phrase in ["analyze", "check health", "how is"]
        ):
            host_name = self._extract_host_name(query) or self.context.get("last_host")
            if host_name:
                return {"action": "analyze_host", "host_name": host_name}

        # Acknowledgement
        if any(phrase in query_lower for phrase in ["acknowledge", "ack "]):
            return self._extract_service_action(query, "acknowledge")

        # Downtime
        if any(
            phrase in query_lower
            for phrase in ["downtime", "maintenance", "schedule downtime"]
        ):
            action_data = self._extract_service_action(query, "downtime")
            action_data["duration"] = self._extract_duration(query)
            return action_data

        # Default to unknown
        return {"action": "unknown", "query": query}

    def _extract_host_name(self, query: str) -> Optional[str]:
        """Extract host name from query."""
        # Simple implementation - in real world would use NLP
        words = query.split()

        # Look for patterns like "host server01" or "on server01"
        for i, word in enumerate(words):
            if word.lower() in ["host", "on", "for"] and i + 1 < len(words):
                potential_host = words[i + 1].rstrip(".,!?")
                if not potential_host.lower() in ["the", "a", "an"]:
                    return potential_host

        # Look for words that look like hostnames
        for word in words:
            cleaned = word.rstrip(".,!?")
            if (
                any(char.isdigit() for char in cleaned)
                or "." in cleaned
                or "-" in cleaned
            ):
                return cleaned

        return None

    def _extract_filter(self, query: str) -> Optional[str]:
        """Extract filter pattern from query."""
        # Look for patterns like "matching web*" or "like db-"
        if "matching" in query or "like" in query:
            words = query.split()
            for i, word in enumerate(words):
                if word in ["matching", "like"] and i + 1 < len(words):
                    return words[i + 1].rstrip(".,!?")
        return None

    def _extract_state_filter(self, query: str) -> Optional[List[str]]:
        """Extract service state filter from query."""
        states = []
        query_lower = query.lower()

        if "critical" in query_lower:
            states.append("CRITICAL")
        if "warning" in query_lower:
            states.append("WARNING")
        if "unknown" in query_lower:
            states.append("UNKNOWN")
        if "ok" in query_lower:
            states.append("OK")

        return states if states else None

    def _extract_service_action(self, query: str, action: str) -> Dict[str, Any]:
        """Extract service action details from query."""
        result = {"action": action}

        # Try to extract host and service names
        # Look for patterns like "CPU on server01" or "server01/CPU"
        words = query.split()

        # Check for host/service pattern
        for word in words:
            if "/" in word:
                parts = word.split("/", 1)
                result["host_name"] = parts[0]
                result["service_name"] = parts[1]
                return result

        # Look for "service on host" pattern
        if " on " in query:
            parts = query.split(" on ")
            for part in parts[1:]:
                potential_host = part.split()[0].rstrip(".,!?")
                if potential_host:
                    result["host_name"] = potential_host
                    # Extract service name from first part
                    service_words = parts[0].split()
                    for word in reversed(service_words):
                        if word.lower() not in [
                            "the",
                            "service",
                            "acknowledge",
                            "downtime",
                        ]:
                            result["service_name"] = word
                            break
                    break

        # Use context if available
        if "host_name" not in result:
            result["host_name"] = self.context.get("last_host")
        if "service_name" not in result:
            result["service_name"] = self.context.get("last_service")

        return result

    def _extract_duration(self, query: str) -> float:
        """Extract duration from query."""
        import re

        # Look for patterns like "2 hours", "30 minutes", "1.5h"
        patterns = [
            (r"(\d+(?:\.\d+)?)\s*h(?:ours?)?", 1.0),
            (r"(\d+(?:\.\d+)?)\s*m(?:ins?|inutes?)?", 1 / 60.0),
            (r"(\d+(?:\.\d+)?)\s*d(?:ays?)?", 24.0),
        ]

        for pattern, multiplier in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return float(match.group(1)) * multiplier

        return 2.0  # Default 2 hours

    # MCP-based action methods

    async def _list_hosts(self, search_filter: Optional[str] = None):
        """List hosts using MCP."""
        result = await self.mcp_client.list_hosts(search=search_filter)

        if result.get("success"):
            data = result.get("data", {})
            click.echo(self.formatter.format_host_list(data))

            # Update context
            hosts = data.get("hosts", [])
            if hosts and len(hosts) == 1:
                self.context["last_host"] = hosts[0].get("name")
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to list hosts: {result.get('error', 'Unknown error')}"
                )
            )

    async def _show_host_details(self, host_name: str):
        """Show host details using MCP."""
        result = await self.mcp_client.get_host(name=host_name, include_status=True)

        if result.get("success"):
            data = result.get("data", {})
            click.echo(self.formatter.format_host_details(data))

            # Update context
            self.context["last_host"] = host_name
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to get host details: {result.get('error', 'Unknown error')}"
                )
            )

    async def _list_services(
        self, host_name: Optional[str] = None, state_filter: Optional[List[str]] = None
    ):
        """List services using MCP."""
        if host_name:
            result = await self.mcp_client.list_host_services(
                host_name=host_name, state_filter=state_filter
            )
        else:
            result = await self.mcp_client.list_all_services(state_filter=state_filter)

        if result.get("success"):
            data = result.get("data", {})
            click.echo(self.formatter.format_service_list(data))

            # Update context
            services = data.get("services", [])
            if services and len(services) == 1:
                self.context["last_service"] = services[0].get("service_name")
                self.context["last_host"] = services[0].get("host_name")
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to list services: {result.get('error', 'Unknown error')}"
                )
            )

    async def _show_problems(
        self, host_name: Optional[str] = None, critical_only: bool = False
    ):
        """Show problems using MCP."""
        if host_name:
            result = await self.mcp_client.get_host_problems(
                host_name=host_name,
                severity_filter="critical" if critical_only else None,
            )
        else:
            result = await self.mcp_client.get_critical_problems()

        if result.get("success"):
            data = result.get("data", {})
            click.echo(self.formatter.format_problem_summary(data))
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to get problems: {result.get('error', 'Unknown error')}"
                )
            )

    async def _show_health_dashboard(self, problems_only: bool = False):
        """Show health dashboard using MCP."""
        result = await self.mcp_client.get_health_dashboard(problems_only=problems_only)

        if result.get("success"):
            data = result.get("data", {})
            click.echo(self.formatter.format_health_dashboard(data))
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to get health dashboard: {result.get('error', 'Unknown error')}"
                )
            )

    async def _analyze_host(self, host_name: str):
        """Analyze host health using MCP."""
        result = await self.mcp_client.analyze_host_health(
            host_name=host_name, include_grade=True, include_recommendations=True
        )

        if result.get("success"):
            data = result.get("data", {})
            click.echo(self.formatter.format_host_analysis(data))

            # Update context
            self.context["last_host"] = host_name
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to analyze host: {result.get('error', 'Unknown error')}"
                )
            )

    async def _acknowledge_service(
        self, host_name: str, service_name: str, comment: str
    ):
        """Acknowledge service problem using MCP."""
        if not host_name or not service_name:
            click.echo(self.formatter.format_error("Host and service names required"))
            return

        result = await self.mcp_client.acknowledge_service_problem(
            host_name=host_name, service_name=service_name, comment=comment
        )

        if result.get("success"):
            click.echo(
                self.formatter.format_success(
                    f"Successfully acknowledged {host_name}/{service_name}"
                )
            )

            # Update context
            self.context["last_host"] = host_name
            self.context["last_service"] = service_name
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to acknowledge: {result.get('error', 'Unknown error')}"
                )
            )

    async def _create_downtime(
        self, host_name: str, service_name: str, duration: float, comment: str
    ):
        """Create service downtime using MCP."""
        if not host_name or not service_name:
            click.echo(self.formatter.format_error("Host and service names required"))
            return

        result = await self.mcp_client.create_service_downtime(
            host_name=host_name,
            service_name=service_name,
            duration_hours=duration,
            comment=comment,
        )

        if result.get("success"):
            click.echo(
                self.formatter.format_success(
                    f"Successfully created {duration}h downtime for {host_name}/{service_name}"
                )
            )

            # Update context
            self.context["last_host"] = host_name
            self.context["last_service"] = service_name
        else:
            click.echo(
                self.formatter.format_error(
                    f"Failed to create downtime: {result.get('error', 'Unknown error')}"
                )
            )

    async def _ai_analysis(self, query: str, intent: Dict[str, Any]):
        """Fallback to AI analysis using MCP prompts."""
        # Try to determine the best prompt template
        if "host_name" in intent:
            # Use host analysis prompt
            prompt = await self.mcp_client.get_host_analysis_prompt(
                intent["host_name"], include_grade=True
            )
            click.echo(
                self.formatter.format_header(f"AI Analysis for {intent['host_name']}")
            )
        else:
            # Use infrastructure overview
            prompt = await self.mcp_client.get_infrastructure_overview_prompt()
            click.echo(self.formatter.format_header("Infrastructure Overview"))

        click.echo(
            self.formatter.format_info(
                "Generated AI prompt. This would be sent to an LLM for analysis."
            )
        )
        click.echo()
        click.echo(prompt[:500] + "..." if len(prompt) > 500 else prompt)

    def show_help(self):
        """Show interactive mode help."""
        help_text = self.help_system.show_help()
        click.echo(self.formatter.format_help(help_text))
