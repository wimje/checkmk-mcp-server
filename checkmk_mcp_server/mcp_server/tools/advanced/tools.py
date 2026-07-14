"""Advanced tools for the Checkmk MCP server.

This module contains all advanced operational MCP tools extracted from the main server.
"""

import logging
from typing import Any, Dict, Optional, List, TYPE_CHECKING
from mcp.types import Tool
from datetime import datetime

if TYPE_CHECKING:
    pass  # Services would be imported here

logger = logging.getLogger(__name__)


class AdvancedTools:
    """Advanced operational tools for MCP server."""
    
    def __init__(self, server=None):
        """Initialize advanced tools with required services.
        
        Args:
            server: MCP server instance for service access
        """
        self.server = server
        self._tool_handlers: Dict[str, Any] = {}
        self._tools: Dict[str, Tool] = {}
        
    def get_tools(self) -> Dict[str, Tool]:
        """Get all advanced tool definitions."""
        return self._tools.copy()
        
    def get_handlers(self) -> Dict[str, Any]:
        """Get all advanced tool handlers."""
        return self._tool_handlers.copy()
        
    def _get_service(self, service_name: str):
        """Helper to get service from server."""
        if self.server and hasattr(self.server, '_get_service'):
            return self.server._get_service(service_name)
        return None
        
    def register_tools(self) -> None:
        """Register all advanced tools and handlers."""
        from ...utils.errors import sanitize_error
        
        # Get system info tool
        self._tools["get_system_info"] = Tool(
            name="get_system_info",
            description="Get Checkmk system version and basic information",
            inputSchema={"type": "object", "properties": {}},
        )

        async def get_system_info():
            try:
                # The async API client is registered in the service container
                # (the old server.checkmk_client attribute no longer exists).
                client = self._get_service('async_client')
                if client is None:
                    return {
                        "success": False,
                        "error": "Checkmk client not available"
                    }

                version_info = await client.get_version_info()

                # Extract key information
                versions = version_info.get("versions", {})
                site_info = version_info.get("site", "unknown")
                edition = version_info.get("edition", "unknown")

                # Compatibility assessment (no extra API call)
                from ....api_client import CheckmkClient

                checkmk_version = versions.get("checkmk", "unknown")
                parsed = CheckmkClient.parse_checkmk_version(checkmk_version)
                version_supported = (
                    parsed >= CheckmkClient.MIN_CHECKMK_VERSION
                    if parsed is not None
                    else None
                )
                api_revision = (version_info.get("rest_api") or {}).get(
                    "revision", "unknown"
                )

                return {
                    "success": True,
                    "checkmk_version": checkmk_version,
                    "edition": edition,
                    "site": site_info,
                    "python_version": versions.get("python", "unknown"),
                    "apache_version": versions.get("apache", "unknown"),
                    "api_revision": api_revision,
                    "version_supported": version_supported,
                    "minimum_supported_version": ".".join(
                        str(x) for x in CheckmkClient.MIN_CHECKMK_VERSION
                    ),
                }
            except Exception as e:
                logger.exception("Error getting system info")
                return {"success": False, "error": sanitize_error(e)}

        self._tool_handlers["get_system_info"] = get_system_info

        # Stream hosts tool
        self._tools["stream_hosts"] = Tool(
            name="stream_hosts",
            description="Stream hosts in batches for large environments",
            inputSchema={
                "type": "object",
                "properties": {
                    "batch_size": {
                        "type": "integer",
                        "description": "Number of hosts per batch",
                        "default": 100,
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional search filter",
                    },
                    "folder": {
                        "type": "string",
                        "description": "Optional folder filter",
                    },
                },
            },
        )

        async def stream_hosts(batch_size=100, search=None, folder=None):
            try:
                streaming_host_service = getattr(self.server, 'streaming_host_service', None)
                if not streaming_host_service:
                    return {"success": False, "error": "Streaming not enabled"}

                batches = []
                async for batch in streaming_host_service.list_hosts_streamed(
                    batch_size=batch_size, search=search, folder=folder
                ):
                    batch_data = batch.model_dump()
                    batches.append(
                        {
                            "batch_number": batch_data["batch_number"],
                            "items_count": len(batch_data["items"]),
                            "has_more": batch_data["has_more"],
                            "timestamp": batch_data["timestamp"],
                        }
                    )

                    # Limit to prevent overwhelming response
                    if len(batches) >= 10:
                        break

                return {
                    "success": True,
                    "data": {
                        "total_batches_processed": len(batches),
                        "batches": batches,
                        "message": f"Processed {len(batches)} batches with {batch_size} items each",
                    },
                }

            except Exception as e:
                logger.exception("Error streaming hosts")
                return {"success": False, "error": sanitize_error(e)}

        self._tool_handlers["stream_hosts"] = stream_hosts

        # Batch create hosts tool
        self._tools["batch_create_hosts"] = Tool(
            name="batch_create_hosts",
            description="Create multiple hosts in a batch operation",
            inputSchema={
                "type": "object",
                "properties": {
                    "hosts_data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of host creation data",
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "description": "Maximum concurrent operations",
                        "default": 5,
                    },
                },
                "required": ["hosts_data"],
            },
        )

        async def batch_create_hosts(hosts_data, max_concurrent=5):
            try:
                # Use batch processor for efficient creation
                batch_processor = getattr(self.server, 'batch_processor', None)
                host_service = getattr(self.server, 'host_service', None)
                
                if not batch_processor or not host_service:
                    return {"success": False, "error": "Batch processing not available"}

                batch_processor.max_concurrent = max_concurrent

                async def create_single_host(host_data: Dict[str, Any]):
                    return await host_service.create_host(**host_data)

                result = await batch_processor.process_batch(
                    items=hosts_data,
                    operation=create_single_host,
                    batch_id=f"create_hosts_{datetime.now().timestamp()}",
                )

                return {
                    "success": True,
                    "data": {
                        "batch_id": result.batch_id,
                        "total_items": result.progress.total_items,
                        "successful": result.progress.success,
                        "failed": result.progress.failed,
                        "skipped": result.progress.skipped,
                        "duration_seconds": result.progress.duration,
                        "items_per_second": result.progress.items_per_second,
                    },
                    "message": f"Batch completed: {result.progress.success} created, {result.progress.failed} failed",
                }

            except Exception as e:
                logger.exception("Error in batch create hosts")
                return {"success": False, "error": sanitize_error(e)}

        self._tool_handlers["batch_create_hosts"] = batch_create_hosts

        # Get server metrics tool
        self._tools["get_server_metrics"] = Tool(
            name="get_server_metrics",
            description="Get comprehensive server performance metrics",
            inputSchema={"type": "object", "properties": {}},
        )

        async def get_server_metrics():
            try:
                # Get metrics from various sources - simplified for extraction
                server_stats = {}
                service_metrics = {}
                cache_stats = {}
                recovery_stats = {}
                
                # Try to get cache stats if available
                cached_host_service = getattr(self.server, 'cached_host_service', None)
                if cached_host_service:
                    cache_stats = await cached_host_service.get_cache_stats()

                return {
                    "success": True,
                    "data": {
                        "server_metrics": server_stats,
                        "service_metrics": service_metrics,
                        "cache_metrics": cache_stats,
                        "recovery_metrics": recovery_stats,
                        "timestamp": datetime.now().isoformat(),
                    },
                }

            except Exception as e:
                logger.exception("Error getting server metrics")
                return {"success": False, "error": sanitize_error(e)}

        self._tool_handlers["get_server_metrics"] = get_server_metrics

        # Clear cache tool
        self._tools["clear_cache"] = Tool(
            name="clear_cache",
            description="Clear specific cache entries or entire cache using pattern matching to resolve stale data issues and improve performance. When to use: After configuration changes, when experiencing stale data issues, troubleshooting performance problems, forced cache refresh needs. Prerequisites: Administrative privileges recommended. WARNING: May temporarily impact performance while caches rebuild. Use pattern parameter to target specific cache entries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Optional pattern to match cache keys",
                    }
                },
            },
        )

        async def clear_cache(pattern=None):
            try:
                cached_host_service = getattr(self.server, 'cached_host_service', None)
                if not cached_host_service:
                    return {"success": False, "error": "Cache not enabled"}

                if pattern:
                    cleared = await cached_host_service.invalidate_cache_pattern(
                        pattern
                    )
                    message = f"Cleared {cleared} cache entries matching '{pattern}'"
                else:
                    await cached_host_service._cache.clear()
                    message = "Cleared all cache entries"

                return {
                    "success": True,
                    "data": {"cleared_entries": cleared if pattern else "all"},
                    "message": message,
                }

            except Exception as e:
                logger.exception("Error clearing cache")
                return {"success": False, "error": sanitize_error(e)}

        self._tool_handlers["clear_cache"] = clear_cache