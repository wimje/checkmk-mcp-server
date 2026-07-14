# Architecture Guide

This document provides a comprehensive overview of the Checkmk MCP Server's technical architecture, design decisions, and implementation details.

## Overview

The Checkmk MCP Server implements a **MCP-first architecture** that bridges AI assistants with Checkmk monitoring infrastructure through the Model Context Protocol (MCP). The system prioritizes scalability, maintainability, and production readiness.

## Architecture Diagram

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   LLM Clients       │     │   MCP Protocol   │     │  Checkmk API    │
│ • Claude Desktop    │────▶│ • MCP Server     │────▶│ • REST API v1.0 │
│ • VS Code           │     │ • Tools/Resources│     │ • Livestatus    │
│ • Custom Clients    │     │ • Streaming      │     │ • Setup API     │
└─────────────────────┘     └──────────────────┘     └─────────────────┘
                                      │
                            ┌─────────┴──────────┐
                            │  Service Layer     │
                            │ • Async Operations │
                            │ • Error Handling   │
                            │ • Type Safety      │
                            └────────────────────┘
```

## Core Design Principles

### 1. MCP-First Architecture
- **Primary Interface**: MCP server acts as the main entry point
- **Standardized Protocol**: All operations exposed through MCP tools and resources
- **Universal Compatibility**: Works with any MCP-compatible client
- **Tool-Based Operations**: Each monitoring function exposed as a discrete tool

### 2. Modular Service Layer
- **Separation of Concerns**: Business logic separated from presentation
- **Single Responsibility**: Each service handles one domain area
- **Dependency Injection**: Service container manages dependencies
- **Consistent Patterns**: Standardized error handling and response formats

### 3. Async-First Design
- **Non-blocking Operations**: Full async/await implementation
- **Concurrent Processing**: Efficient handling of multiple operations
- **Streaming Support**: Memory-efficient processing of large datasets
- **Performance Optimization**: Built for enterprise-scale environments

## Project Structure

```
checkmk_llm_agent/
├── checkmk_mcp_server/                    # Core package
│   ├── services/                     # Service layer (business logic)
│   │   ├── base.py                   # Base service with error handling
│   │   ├── host_service.py           # Host management operations
│   │   ├── service_service.py        # Service monitoring operations
│   │   ├── status_service.py         # Health monitoring and dashboards
│   │   ├── parameter_service.py      # Parameter and rule management
│   │   ├── streaming.py              # Streaming functionality
│   │   ├── cache.py                  # Caching layer
│   │   ├── batch.py                  # Batch processing
│   │   ├── metrics.py                # Performance monitoring
│   │   ├── recovery.py               # Error recovery patterns
│   │   └── handlers/                 # Specialized parameter handlers
│   │       ├── base.py               # Base handler and registry
│   │       ├── temperature.py        # Temperature monitoring handler
│   │       ├── database.py           # Database monitoring handler
│   │       ├── network.py            # Network service handler
│   │       └── custom_checks.py      # Custom check handler
│   ├── mcp_server/                   # MCP server implementation
│   │   ├── __init__.py
│   │   ├── server.py                 # MCP server orchestration (300 lines)
│   │   ├── service_container.py      # Dependency injection container
│   │   ├── tool_categories/          # Modular tool organization
│   │   │   ├── host_tools.py         # Host management tools (6 tools)
│   │   │   ├── service_tools.py      # Service operation tools (3 tools)
│   │   │   ├── monitoring_tools.py   # Status monitoring tools (3 tools)
│   │   │   ├── parameter_tools.py    # Parameter management tools (11 tools)
│   │   │   ├── event_tools.py        # Event console tools (5 tools)
│   │   │   ├── metrics_tools.py      # Metrics and performance tools (2 tools)
│   │   │   ├── business_tools.py     # Business intelligence tools (2 tools)
│   │   │   └── advanced_tools.py     # Advanced feature tools (5 tools)
│   │   └── prompts/                  # AI prompt system
│   │       ├── host_prompts.py       # Host management prompts
│   │       ├── service_prompts.py    # Service operation prompts
│   │       ├── monitoring_prompts.py # Status monitoring prompts
│   │       └── parameter_prompts.py  # Parameter management prompts
│   ├── api_client.py                 # Checkmk REST API client
│   ├── async_api_client.py           # Async wrapper for API client
│   ├── mcp_client.py                 # MCP client implementation
│   ├── cli.py                        # Legacy CLI (direct API)
│   ├── cli_mcp.py                    # MCP-based CLI
│   ├── config.py                     # Configuration management
│   └── models/                       # Pydantic data models
├── mcp_checkmk_server.py             # Unified MCP server entry point
├── checkmk_cli_mcp.py                # MCP-based CLI entry point
├── tests/                            # Comprehensive test suite
├── docs/                             # Documentation
└── examples/                         # Configuration examples
```

## Service Layer Architecture

### Base Service Pattern
All services inherit from `BaseService` which provides:
- **Consistent Error Handling**: Standardized `ServiceResult` wrapper
- **Logging Integration**: Structured logging with request IDs
- **Configuration Access**: Unified configuration management
- **Type Safety**: Pydantic models throughout

```python
class BaseService:
    def __init__(self, api_client: CheckmkAPIClient, config: Config):
        self.api_client = api_client
        self.config = config
        self.logger = get_logger(self.__class__.__name__)
    
    async def _handle_api_call(self, operation: str, api_call: Callable) -> ServiceResult:
        # Standardized error handling, logging, and response wrapping
```

### Service Implementations

#### HostService
- **Purpose**: Host management operations (CRUD)
- **Key Methods**: `list_hosts()`, `create_host()`, `update_host()`, `delete_host()`
- **Features**: Search, filtering, bulk operations

#### ServiceService  
- **Purpose**: Service monitoring and management
- **Key Methods**: `list_services()`, `acknowledge_problems()`, `create_downtime()`
- **Features**: Service discovery, problem management, downtime scheduling

#### StatusService
- **Purpose**: Health monitoring and dashboards
- **Key Methods**: `get_overview()`, `get_problems()`, `get_critical_services()`
- **Features**: Health dashboards, problem categorization, business impact analysis

#### ParameterService
- **Purpose**: Parameter and rule management
- **Key Methods**: `get_effective_parameters()`, `create_rule()`, `update_rule()`
- **Features**: Specialized handlers, parameter validation, bulk operations

## MCP Server Architecture (Refactored 2025-08-20)

### Modular Design
The MCP server was refactored from a 4,449-line monolith to a clean modular architecture:

#### Service Container
- **Dependency Injection**: Centralized service lifecycle management
- **Configuration Registry**: Unified configuration access
- **Protocol Handlers**: Standardized request/response handling

```python
class ServiceContainer:
    def __init__(self, config: Config):
        self.config = config
        self._services = {}
        self._initialize_services()
    
    def get_service(self, service_type: Type[T]) -> T:
        # Lazy initialization and dependency resolution
```

#### Tool Categories
Tools are organized into 8 focused categories:

1. **Host Tools** (6 tools): Host management operations
2. **Service Tools** (3 tools): Service monitoring and management  
3. **Monitoring Tools** (3 tools): Status monitoring and dashboards
4. **Parameter Tools** (11 tools): Parameter management with handlers
5. **Event Tools** (5 tools): Event console operations
6. **Metrics Tools** (2 tools): Performance metrics and historical data
7. **Business Tools** (2 tools): Business intelligence monitoring
8. **Advanced Tools** (5 tools): Streaming, caching, batch operations

#### Tool Registration Pattern
```python
@server.list_tools()
async def list_tools() -> list[types.Tool]:
    tools = []
    tools.extend(host_tools.get_tools())
    tools.extend(service_tools.get_tools())
    tools.extend(monitoring_tools.get_tools())
    # ... other categories
    return tools

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name in host_tools.TOOL_NAMES:
        return await host_tools.handle_tool(name, arguments, container)
    elif name in service_tools.TOOL_NAMES:
        return await service_tools.handle_tool(name, arguments, container)
    # ... other categories
```

## Advanced Features Architecture

### Streaming Support
- **Purpose**: Handle large datasets without memory exhaustion
- **Implementation**: Async generators with batch processing
- **Benefits**: Constant memory usage regardless of dataset size

```python
async def list_hosts_streamed(
    self, 
    batch_size: int = 100
) -> AsyncGenerator[StreamingBatch[Host], None]:
    offset = 0
    batch_number = 1
    
    while True:
        batch = await self._fetch_batch(offset, batch_size)
        if not batch:
            break
            
        yield StreamingBatch(
            items=batch,
            batch_number=batch_number,
            batch_size=len(batch)
        )
        
        offset += len(batch)
        batch_number += 1
```

### Caching Layer
- **Implementation**: LRU cache with TTL support
- **Features**: Pattern invalidation, automatic cleanup
- **Benefits**: 5-50x speedup for repeated queries

```python
@cached(ttl=300, key_prefix="hosts")
async def get_host_details(self, host_name: str) -> ServiceResult[Host]:
    # Method result cached for 5 minutes
    return await self.api_client.get_host(host_name)
```

### Batch Processing
- **Purpose**: Efficient bulk operations with concurrency control
- **Features**: Progress tracking, retry logic, rate limiting
- **Implementation**: Configurable concurrent workers

### Error Recovery
- **Circuit Breaker**: Prevents cascade failures
- **Retry Policies**: Exponential backoff with jitter
- **Fallback Handlers**: Graceful degradation

## Specialized Parameter Handlers

### Handler Registry Pattern
```python
class ParameterHandlerRegistry:
    def __init__(self):
        self._handlers: Dict[str, Type[ParameterHandler]] = {}
        self._patterns: List[Tuple[Pattern, Type[ParameterHandler]]] = []
    
    def register_handler(self, handler_class: Type[ParameterHandler]):
        # Register handler with service patterns
    
    def get_best_handler(self, service_name: str) -> ParameterHandler:
        # Find best matching handler using pattern matching
```

### Handler Implementations
- **TemperatureParameterHandler**: CPU, GPU, ambient, storage temperature
- **DatabaseParameterHandler**: Oracle, MySQL, PostgreSQL, MongoDB, Redis
- **NetworkServiceParameterHandler**: HTTP/HTTPS, TCP/UDP, DNS, SSH
- **CustomCheckParameterHandler**: MRPE, local checks, Nagios plugins

## Data Flow Architecture

### Request Flow
1. **Client Request**: Natural language query from AI client
2. **MCP Protocol**: Tool invocation through MCP
3. **Service Layer**: Business logic processing
4. **API Client**: Checkmk REST API calls
5. **Response Processing**: Data transformation and formatting
6. **MCP Response**: Structured response to AI client

### Error Handling Flow
1. **Exception Capture**: All errors caught at service layer
2. **Error Classification**: Retryable vs. permanent errors
3. **Recovery Strategies**: Circuit breaker, retry, fallback
4. **User Feedback**: Clear error messages with remediation

### Caching Flow
1. **Cache Check**: Look for cached data first
2. **Cache Miss**: Fetch from API if not cached
3. **Cache Update**: Store result with TTL
4. **Cache Invalidation**: Clear related entries on updates

## Performance Characteristics

### Benchmarks
- **Cache Performance**: 10,000+ read ops/second, 5,000+ write ops/second
- **Streaming Throughput**: 1,000+ items/second with constant memory
- **Batch Processing**: 500+ items/second with 10x concurrency
- **Memory Efficiency**: <100MB growth for 10,000 item processing

### Scalability
- **Large Environments**: Handles 50,000+ hosts/services
- **Concurrent Operations**: Up to 20 concurrent batch operations
- **Cache Efficiency**: 5-50x speedup for repeated queries
- **Memory Usage**: Scales with cache size, not dataset size

## Configuration Architecture

### Hierarchical Configuration
1. **Default Values**: Built-in sensible defaults
2. **Configuration File**: YAML-based configuration
3. **Environment Variables**: Runtime overrides
4. **Command Line Arguments**: Execution-time overrides

### Configuration Validation
- **Pydantic Models**: Type-safe configuration validation
- **Required Fields**: Validation of mandatory settings
- **Default Values**: Automatic fallback to sensible defaults

## Security Architecture

### Authentication
- **Checkmk Integration**: Uses Checkmk's authentication system
- **Automation Users**: Dedicated automation accounts
- **Permission Model**: Follows Checkmk's permission system

### Data Security
- **Credential Management**: Secure credential storage
- **API Security**: HTTPS-only communication
- **Input Validation**: All inputs validated and sanitized
- **Output Filtering**: Sensitive data filtered from responses

## Testing Architecture

### Test Categories
- **Unit Tests**: Individual component testing
- **Integration Tests**: Service interaction testing
- **Performance Tests**: Benchmarking and load testing
- **End-to-End Tests**: Full workflow testing

### Test Infrastructure
- **Mock Services**: Isolated testing environment
- **Test Fixtures**: Reusable test data
- **Continuous Integration**: Automated test execution
- **Coverage Reporting**: Code coverage analysis

## Deployment Architecture

### Entry Points
- **MCP Server**: `mcp_checkmk_server.py` - Primary deployment
- **CLI Interface**: `checkmk_cli_mcp.py` - Testing and automation
- **Legacy CLI**: Direct API access for debugging

### Where the LLM Lives

The two interfaces use fundamentally different intelligence:

- **MCP path** (`mcp_checkmk_server.py` + Claude Desktop or another MCP
  client): the LLM *is the MCP client*. Claude interprets natural language
  and decides which of the server's tools to call. The server itself makes
  no LLM calls, and the `llm:` configuration section is not used.
- **MCP CLI** (`checkmk_cli_mcp.py`, including `interactive`): no LLM at
  all. Natural-language input is handled by keyword-based intent matching
  in `interactive/mcp_session.py`. It exists for testing the MCP server
  and for scripted automation.
- **Direct CLI** (`checkmk_mcp_server/cli.py`): the only component that
  uses the `llm:` configuration (`anthropic_api_key`/`openai_api_key`),
  for parsing natural-language commands via `llm_client.py`.

### Production Considerations
- **Process Management**: Systemd/supervisord integration
- **Logging**: Structured logging with log rotation
- **Monitoring**: Health checks and metrics export
- **Scaling**: Horizontal scaling with load balancing

## Migration and Versioning

### API Compatibility
- **Checkmk 2.4+**: Full feature support
- **Backward Compatibility**: Graceful handling of older versions
- **Feature Detection**: Runtime feature availability checking

### Version Management
- **Semantic Versioning**: Clear version numbering
- **Migration Guides**: Step-by-step upgrade instructions
- **Rollback Support**: Safe rollback procedures

## Future Architecture Considerations

### Planned Enhancements
- **Multi-tenant Support**: Multiple Checkmk sites
- **Web UI Integration**: Browser-based interface
- **GraphQL API**: Alternative API interface
- **Kubernetes Integration**: Native K8s deployment

### Extension Points
- **Custom Handlers**: Pluggable parameter handlers
- **Custom Tools**: Additional MCP tools
- **Custom Clients**: Alternative client implementations
- **Custom Dashboards**: User-defined monitoring views

This architecture provides a solid foundation for scaling the Checkmk MCP Server to meet enterprise requirements while maintaining code quality, performance, and maintainability.

## Related Documentation

- **[Getting Started Guide](getting-started.md)** - Setup and configuration procedures
- **[Usage Examples](USAGE_EXAMPLES.md)** - Practical usage scenarios
- **[Advanced Features](ADVANCED_FEATURES.md)** - Detailed feature implementation
- **[Parameter Management](PARAMETER_MANAGEMENT_GUIDE.md)** - Parameter system details
- **[Troubleshooting](troubleshooting.md)** - Architecture-related troubleshooting