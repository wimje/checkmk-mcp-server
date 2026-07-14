"""CLI formatter for rich text output using existing UI manager."""

from typing import Dict, Any, List, Optional
from datetime import datetime

from .base_formatter import BaseFormatter
from ..interactive.ui_manager import UIManager, MessageType
from ..services.models.hosts import HostInfo, HostListResult
from ..services.models.services import ServiceInfo, ServiceListResult, ServiceState
from ..services.models.status import HealthDashboard, ServiceProblem, HostStatus


class CLIFormatter(BaseFormatter):
    """CLI formatter using rich text formatting."""

    def __init__(self, theme: str = "default", use_colors: Optional[bool] = None):
        super().__init__()
        self.ui = UIManager(theme=theme, use_colors=use_colors)

    def format_host_list(self, data: Dict[str, Any]) -> str:
        """Format host list data with rich output."""
        if isinstance(data, dict) and "hosts" in data:
            # Handle HostListResult structure
            hosts = data["hosts"]
            total_count = data.get("total_count", len(hosts))
            search_applied = data.get("search_applied")
            stats = data.get("stats", {})
        else:
            # Handle raw list
            hosts = data if isinstance(data, list) else []
            total_count = len(hosts)
            search_applied = None
            stats = {}

        if not hosts:
            return self.ui.format_message("No hosts found", MessageType.WARNING)

        # Header
        header_parts = [f"Found {total_count} host{'s' if total_count != 1 else ''}"]
        if search_applied:
            header_parts.append(f"matching '{search_applied}'")

        header = self.ui.format_message(" ".join(header_parts) + ":", MessageType.INFO)

        # Format hosts
        lines = [header, ""]
        for host in hosts:
            lines.append(self._format_single_host(host))

        # Add statistics if available
        if stats:
            lines.extend(["", self._format_host_stats(stats)])

        return "\n".join(lines)

    def format_service_list(self, data: Dict[str, Any]) -> str:
        """Format service list data with rich output."""
        if isinstance(data, dict) and "services" in data:
            services = data["services"]
            total_count = data.get("total_count", len(services))
            host_filter = data.get("host_filter")
            stats = data.get("stats", {})
        else:
            services = data if isinstance(data, list) else []
            total_count = len(services)
            host_filter = None
            stats = {}

        if not services:
            return self.ui.format_message("No services found", MessageType.WARNING)

        # Header
        header_parts = [f"Found {total_count} service{'s' if total_count != 1 else ''}"]
        if host_filter:
            header_parts.append(f"on host '{host_filter}'")

        header = self.ui.format_message(" ".join(header_parts) + ":", MessageType.INFO)

        # Format services
        lines = [header, ""]
        for service in services:
            lines.append(self._format_single_service(service))

        # Add statistics if available
        if stats:
            lines.extend(["", self._format_service_stats(stats)])

        return "\n".join(lines)

    def format_health_dashboard(self, data: Dict[str, Any]) -> str:
        """Format health dashboard with comprehensive metrics."""
        lines = []

        # Header
        lines.append(self.ui.colorize("📊 Service Health Dashboard", "header"))
        lines.append(self.ui.colorize("━" * 62, "separator"))
        lines.append("")

        # Overall health
        health_percentage = data.get("overall_health_percentage", 0)
        health_grade = data.get("overall_health_grade", "F")

        # Health indicator
        if health_percentage >= 95:
            health_icon = "🟢"
            health_color = "success"
        elif health_percentage >= 80:
            health_icon = "🟡"
            health_color = "warning"
        else:
            health_icon = "🔴"
            health_color = "error"

        health_bar = self._create_health_bar(health_percentage)
        health_line = f"{health_icon} Overall Health: {self.ui.colorize(f'{health_percentage}%', health_color)} [{health_bar}] (Grade: {health_grade})"
        lines.append(health_line)

        # Totals
        total_hosts = data.get("total_hosts", 0)
        total_services = data.get("total_services", 0)
        lines.append(f"📈 Total: {total_hosts} hosts, {total_services} services")

        # Service state distribution
        service_states = data.get("service_states", {})
        if service_states:
            lines.append("")
            lines.append(self.ui.colorize("📊 Service States:", "header"))

            ok_count = service_states.get("ok", 0)
            warning_count = service_states.get("warning", 0)
            critical_count = service_states.get("critical", 0)
            unknown_count = service_states.get("unknown", 0)

            lines.append(
                f"  ✅ OK: {self.ui.colorize(str(ok_count), 'success')} services"
            )
            if warning_count > 0:
                lines.append(
                    f"  ⚠️  WARNING: {self.ui.colorize(str(warning_count), 'warning')} services"
                )
            if critical_count > 0:
                lines.append(
                    f"  ❌ CRITICAL: {self.ui.colorize(str(critical_count), 'error')} services"
                )
            if unknown_count > 0:
                lines.append(
                    f"  ❓ UNKNOWN: {self.ui.colorize(str(unknown_count), 'info')} services"
                )

        # Problem summary
        problem_summary = data.get("problem_summary", {})
        if problem_summary:
            total_problems = problem_summary.get("total_problems", 0)
            urgent_problems = problem_summary.get("urgent_problems", 0)
            unacknowledged = problem_summary.get("unacknowledged_problems", 0)

            if total_problems > 0:
                lines.append("")
                lines.append(self.ui.colorize("🚨 Problems Summary:", "header"))
                lines.append(
                    f"  🔴 {urgent_problems} urgent problem{'s' if urgent_problems != 1 else ''} require immediate attention"
                )
                lines.append(
                    f"  💡 {unacknowledged} unacknowledged problem{'s' if unacknowledged != 1 else ''} need review"
                )
            else:
                lines.append("")
                lines.append(
                    self.ui.format_message(
                        "✅ No problems detected!", MessageType.SUCCESS
                    )
                )

        # Critical problems
        critical_problems = data.get("critical_problems", [])
        if critical_problems:
            lines.append("")
            lines.append(
                self.ui.colorize(
                    f"🔴 Critical Services ({len(critical_problems)}):", "error"
                )
            )
            for problem in critical_problems[:5]:  # Show top 5
                lines.append(
                    f"  ❌ {problem.get('host_name', '')}/{problem.get('service_name', '')}"
                )

            if len(critical_problems) > 5:
                lines.append(f"  ... and {len(critical_problems) - 5} more")

        # Recommendations
        recommendations = data.get("recommendations", [])
        if recommendations:
            lines.append("")
            lines.append(self.ui.colorize("💡 Recommendations:", "info"))
            for rec in recommendations:
                lines.append(f"  • {rec}")

        # Alerts
        alerts = data.get("alerts", [])
        if alerts:
            lines.append("")
            lines.append(self.ui.colorize("⚠️ Alerts:", "warning"))
            for alert in alerts:
                lines.append(f"  {alert}")

        # Footer
        last_updated = data.get("last_updated")
        if last_updated:
            if isinstance(last_updated, str):
                timestamp_str = last_updated
            else:
                timestamp_str = self.format_timestamp(last_updated)
            lines.append("")
            lines.append(self.ui.colorize(f"Last updated: {timestamp_str}", "muted"))

        return "\n".join(lines)

    def format_service_status(self, data: Dict[str, Any]) -> str:
        """Format detailed service status."""
        service = data.get("service", {})
        if not service:
            return self.ui.format_message(
                "No service data available", MessageType.ERROR
            )

        lines = []

        # Header
        host_name = service.get("host_name", "")
        service_name = service.get("service_name", "")
        lines.append(
            self.ui.colorize(f"📋 Service Status: {host_name}/{service_name}", "header")
        )
        lines.append(self.ui.colorize("━" * 60, "separator"))
        lines.append("")

        # Current state
        state = service.get("state", "UNKNOWN")
        state_icon = self._get_state_icon(state)
        state_color = self._get_state_color(state)
        lines.append(f"Status: {state_icon} {self.ui.colorize(state, state_color)}")

        # Plugin output
        plugin_output = service.get("plugin_output", "")
        if plugin_output:
            lines.append(f"Output: {plugin_output}")

        # Timing information
        last_check = service.get("last_check")
        if last_check:
            lines.append(f"Last Check: {self.format_timestamp(last_check)}")

        last_state_change = service.get("last_state_change")
        if last_state_change:
            lines.append(f"State Changed: {self.format_timestamp(last_state_change)}")

        # Problem management
        if service.get("acknowledged"):
            lines.append(
                f"🔕 Acknowledged by {service.get('acknowledgement_author', 'unknown')}"
            )
            ack_comment = service.get("acknowledgement_comment")
            if ack_comment:
                lines.append(f"   Comment: {ack_comment}")

        if service.get("in_downtime"):
            lines.append("⏸️  In scheduled downtime")
            downtime_comment = service.get("downtime_comment")
            if downtime_comment:
                lines.append(f"   Comment: {downtime_comment}")

        # Related services
        related_services = data.get("related_services", [])
        if related_services:
            lines.append("")
            lines.append(
                self.ui.colorize(f"Related Services on {host_name}:", "header")
            )
            for related in related_services[:10]:  # Show top 10
                rel_state = related.get("state", "UNKNOWN")
                rel_icon = self._get_state_icon(rel_state)
                lines.append(f"  {rel_icon} {related.get('service_name', '')}")

        return "\n".join(lines)

    def format_error(self, error: str, context: str = "") -> str:
        """Format error message."""
        if context:
            return self.ui.format_message(f"{context}: {error}", MessageType.ERROR)
        else:
            return self.ui.format_message(error, MessageType.ERROR)

    def format_info(self, message: str) -> str:
        """Format informational message."""
        return self.ui.format_message(message, MessageType.INFO)

    def format_success(self, message: str) -> str:
        """Format success message."""
        return self.ui.format_message(message, MessageType.SUCCESS)

    def format_warning(self, message: str) -> str:
        """Format warning message."""
        return self.ui.format_message(message, MessageType.WARNING)

    def format_header(self, title: str) -> str:
        """Format a section header."""
        line = "─" * max(len(title) + 4, 40)
        return self.ui.colorize(f"{line}\n  {title}\n{line}", "header")

    def format_prompt(self, prompt: str = "checkmk") -> str:
        """Format the interactive command prompt.

        UIManager.format_prompt appends its own "> ", so strip any trailing
        prompt characters from the caller's text to avoid "checkmk> >".
        """
        return self.ui.format_prompt(prompt.rstrip().rstrip(">").rstrip())

    def format_help(self, help_text: str) -> str:
        """Format help text."""
        return self.ui.format_message(help_text, MessageType.HELP)

    def format_host_details(self, data: Dict[str, Any]) -> str:
        """Format host details as key/value output."""
        return self._format_dict("Host Details", data)

    def format_acknowledge_result(self, data: Dict[str, Any]) -> str:
        """Format the result of a service acknowledgement."""
        return self._format_dict("Acknowledgement", data)

    def format_downtime_result(self, data: Dict[str, Any]) -> str:
        """Format the result of a downtime creation."""
        return self._format_dict("Downtime", data)

    def format_discovery_result(self, data: Dict[str, Any]) -> str:
        """Format a service discovery result."""
        return self._format_dict("Service Discovery", data)

    def format_problem_summary(self, data: Dict[str, Any]) -> str:
        """Format a problem summary."""
        problems = data.get("problems") if isinstance(data, dict) else None
        if isinstance(problems, list):
            if not problems:
                return self.ui.format_message("No problems found", MessageType.SUCCESS)
            lines = [self.ui.colorize(f"🚨 {len(problems)} problem(s):", "header")]
            for problem in problems:
                if isinstance(problem, dict):
                    lines.append(self._format_single_service(problem))
                else:
                    lines.append(f"  • {problem}")
            return "\n".join(lines)
        return self._format_dict("Problem Summary", data)

    def format_host_analysis(self, data: Dict[str, Any]) -> str:
        """Format a host health analysis."""
        return self._format_dict("Host Analysis", data)

    def _format_dict(self, title: str, data: Any, indent: int = 0) -> str:
        """Generic nested key/value renderer for structured results."""
        pad = "  " * indent
        if not isinstance(data, dict):
            return f"{pad}{data}"
        lines = []
        if indent == 0:
            lines.append(self.ui.colorize(f"📋 {title}:", "header"))
            indent = 1
            pad = "  "
        for key, value in data.items():
            label = str(key).replace("_", " ").title()
            if isinstance(value, dict):
                lines.append(f"{pad}{label}:")
                lines.append(self._format_dict(title, value, indent + 1))
            elif isinstance(value, list):
                lines.append(f"{pad}{label}:")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(self._format_dict(title, item, indent + 1))
                    else:
                        lines.append(f"{pad}  • {item}")
            else:
                lines.append(f"{pad}{label}: {value}")
        return "\n".join(lines)

    def _format_single_host(self, host: Dict[str, Any]) -> str:
        """Format a single host entry."""
        name = host.get("name", "")
        folder = host.get("folder", "/")
        ip_address = host.get("ip_address", "")
        state = host.get("state", "PENDING")

        # Host icon and state
        if state == "UP":
            icon = "📦"
            state_color = "success"
        elif state == "DOWN":
            icon = "📦"
            state_color = "error"
        elif state == "UNREACHABLE":
            icon = "📦"
            state_color = "warning"
        else:
            icon = "📦"
            state_color = "muted"

        lines = [f"  {icon} {self.ui.colorize(name, 'host')}"]
        lines.append(f"     📁 Folder: {folder}")

        if ip_address:
            lines.append(f"     🌐 IP: {ip_address}")

        if state != "PENDING":
            lines.append(f"     🔄 State: {self.ui.colorize(state, state_color)}")

        return "\n".join(lines)

    def _format_single_service(self, service: Dict[str, Any]) -> str:
        """Format a single service entry."""
        host_name = service.get("host_name", "")
        service_name = service.get("service_name", "")
        state = service.get("state", "UNKNOWN")
        plugin_output = service.get("plugin_output", "")

        state_icon = self._get_state_icon(state)
        state_color = self._get_state_color(state)

        line = f"  {state_icon} {host_name}/{self.ui.colorize(service_name, 'service')} ({self.ui.colorize(state, state_color)})"

        if plugin_output:
            # Truncate long output
            truncated_output = self.truncate_text(plugin_output, 60)
            line += f" - {truncated_output}"

        return line

    def _format_host_stats(self, stats: Dict[str, int]) -> str:
        """Format host statistics."""
        lines = [self.ui.colorize("📊 Host Statistics:", "header")]

        total = stats.get("total", 0)
        lines.append(f"  Total: {total}")

        if stats.get("up", 0) > 0:
            lines.append(f"  🟢 UP: {stats['up']}")
        if stats.get("down", 0) > 0:
            lines.append(f"  🔴 DOWN: {stats['down']}")
        if stats.get("unreachable", 0) > 0:
            lines.append(f"  🟡 UNREACHABLE: {stats['unreachable']}")
        if stats.get("pending", 0) > 0:
            lines.append(f"  ⚪ PENDING: {stats['pending']}")

        return "\n".join(lines)

    def _format_service_stats(self, stats: Dict[str, int]) -> str:
        """Format service statistics."""
        lines = [self.ui.colorize("📊 Service Statistics:", "header")]

        total = stats.get("total", 0)
        lines.append(f"  Total: {total}")

        if stats.get("ok", 0) > 0:
            lines.append(f"  ✅ OK: {stats['ok']}")
        if stats.get("warning", 0) > 0:
            lines.append(f"  ⚠️  WARNING: {stats['warning']}")
        if stats.get("critical", 0) > 0:
            lines.append(f"  ❌ CRITICAL: {stats['critical']}")
        if stats.get("unknown", 0) > 0:
            lines.append(f"  ❓ UNKNOWN: {stats['unknown']}")

        unhandled = stats.get("unhandled_problems", 0)
        if unhandled > 0:
            lines.append(
                f"  🚨 Unhandled Problems: {self.ui.colorize(str(unhandled), 'error')}"
            )

        return "\n".join(lines)

    def _get_state_icon(self, state: str) -> str:
        """Get icon for service state."""
        state_upper = state.upper()
        if state_upper == "OK":
            return "✅"
        elif state_upper == "WARNING":
            return "⚠️"
        elif state_upper == "CRITICAL":
            return "❌"
        elif state_upper == "UNKNOWN":
            return "❓"
        else:
            return "⚪"

    def _get_state_color(self, state: str) -> str:
        """Get color for service state."""
        state_upper = state.upper()
        if state_upper == "OK":
            return "success"
        elif state_upper == "WARNING":
            return "warning"
        elif state_upper == "CRITICAL":
            return "error"
        else:
            return "info"

    def _create_health_bar(self, percentage: float, width: int = 20) -> str:
        """Create a visual health bar."""
        filled = int((percentage / 100) * width)
        empty = width - filled

        if percentage >= 95:
            bar_color = "success"
        elif percentage >= 80:
            bar_color = "warning"
        else:
            bar_color = "error"

        bar = "█" * filled + "░" * empty
        return self.ui.colorize(bar, bar_color)
