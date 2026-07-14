# CLAUDE.md

Follow these rules at all times @/Users/jlk/code-local/checkmk_llm_agent/RULES.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Checkmk MCP Server** project designed to integrate with Checkmk's REST API using Large Language Models. The project enables natural language interactions with Checkmk monitoring systems through AI-powered automation.

## Current State

The project is a **FULLY OPERATIONAL** Checkmk MCP Server implementation with:
- Complete Checkmk REST API OpenAPI specification (`checkmk-rest-openapi.yaml`)
- Host management operations (CRUD)
- Rule management operations (CRUD)
- **Service status and management operations**
- **Comprehensive Service Parameter Management** - Universal parameter read/write for ALL service types
- **Specialized Parameter Handlers** - Temperature, database, network, and custom check handlers
- **Request ID Tracing System** - Complete request tracking with 6-digit hex IDs across all components
- Natural language processing capabilities
- CLI interface with interactive mode
- **Enhanced MCP Server Integration** - 37 tools with modular architecture and advanced parameter management capabilities
- **Robust error handling with syntax error detection**
- Test coverage for core functionality with 100% pass rate
- VS Code workspace configuration

## Current Focus

**Recently Completed - Version Compatibility, Checkmk 2.2 Support, and Integration Test Infrastructure** (2026-07-14):
- **Version Compatibility Checks**: `CheckmkClient.check_version_compatibility()` verifies Checkmk version (minimum 2.2.0) and REST API revision (majors 0/1); MCP server startup and direct CLI refuse cleanly (no traceback) on unsupported servers; `get_system_info` reports `version_supported`/`api_revision`
- **Checkmk 2.2 Support**: Audited all client endpoints against the bundled 2.2 spec (`docs/checkmk-rest-openapi-2.2.yaml`); only incompatibility was the 2.4-only POST variants of the service listing endpoints — new `_request_service_collection()` converts to GET with query params on servers < 2.4 (server version cached per client)
- **Integration Test Infrastructure**: `docker-compose.test.yml` (disposable 2.4 + 2.2 raw-edition sites), idempotent `scripts/seed_test_site.py`, `tests/integration/` suite (version compat, host listing + monitoring fallback, service listing, downtime/ack, MCP end-to-end over stdio) with localhost-only safety rail; verified 15/15 passing against both 2.4.0p34 and 2.2.0p47; see `docs/testing.md`
- **pytest Config Fix**: `pytest.ini` used `[tool:pytest]` (only valid in setup.cfg), silently disabling ALL pytest configuration including `asyncio_mode = auto`; corrected to `[pytest]`
- **Interactive Mode Polish**: Real `stats` command (health dashboard), complete help text documenting all structured commands and keyword patterns, hostname extraction skips filler nouns ("services for server pfc1001")
- **Documentation**: `docs/testing.md` testing guide; "Where the LLM Lives" section in architecture.md clarifying that the `llm:` config is only used by the direct CLI (MCP path: the AI client is the LLM; MCP CLI: keyword matching only)

**Previously Completed - MCP CLI End-to-End Repair** (2026-07-14):
- **Root Cause of "macOS stdio timeout" Found**: `ClientSession` was created but never entered (`__aenter__`), so its background receive loop never started and `initialize()` always timed out — the 2025-08-22 timeout/fallback machinery was working around this bug. Session is now properly entered/exited; connections initialize on the fast path
- **Connection Lifecycle Fix**: Each CLI subcommand runs in its own `asyncio.run()` loop, so `async_command` now opens a fresh MCP connection per command; `__aenter__` is no longer wrapped in `asyncio.wait_for` (anyio cancel scopes must be entered/exited in the same task); partial connections are cleaned up in-task, eliminating "Attempted to exit cancel scope in a different task" tracebacks at shutdown
- **Fallback Path Fix**: After falling back to the direct CLI, the process now exits instead of letting click invoke the MCP subcommand with an uninitialized context ("Error: CLI context not initialized")
- **Tool Call Fixes**: `call_tool` strips `None` arguments (server schema validation rejects nulls) and unwraps the double-serialized CallToolResult-shaped dict the server returns as an SDK bug workaround
- **CLIFormatter Completed**: Added 12 methods the MCP CLI referenced but never existed (format_header/info/success/warning/prompt/help, host details, acknowledge/downtime/discovery results, problem summary, host analysis)
- **Interactive Session Fixes**: Local command classification (CommandParser has a different interface), `add_history`/`show_help` method name fixes, prompt no longer doubles "> "
- **get_system_info Fix**: Tool now gets the API client from the service container (`async_client`) instead of the removed `server.checkmk_client` attribute
- **Host Listing Fallback**: `list_hosts` falls back to the monitoring endpoint (`/domain-types/host/collections/all`) when the Setup `host_config` endpoint is empty or 403 — monitoring-only automation users now see their hosts

**Previously Completed - Python 3.10 Compatibility and Startup Fixes** (2026-07-14):
- **ExceptionGroup Compatibility Shim**: Fixed `NameError: name 'ExceptionGroup' is not defined` in `mcp_checkmk_server.py` on Python < 3.11 by importing from the `exceptiongroup` backport with stub-class fallback
- **Clean Terminal Exit**: Replaced `sys.exit(0)` with `return` in the async `main()` manual-run guard, eliminating the SystemExit traceback when running the server in a terminal
- **CLI MCP Import Fix**: Fixed `NameError: name 'MCPCLIContext' is not defined` in `checkmk_mcp_server/cli_mcp.py` (forward reference in annotations) via `from __future__ import annotations`
- **Documentation Corrections**: Fixed connection-test snippet in `docs/getting-started.md` (correct `CheckmkClient(config.checkmk)` / `get_version_info()` usage), replaced stale `checkmk_llm_agent` paths, and added new entries to `docs/troubleshooting.md`

**Previously Completed - MCP Prompt Optimization Phase 1 and Python Type Fixes** (2025-08-23):
- **53% Reduction in Tool Selection Issues**: Achieved measurable improvement reducing from 71 to 33 potential confusion points across all 37 MCP tools
- **Enhanced Tool Guidance**: Added comprehensive "When to Use" sections for all tools with clear disambiguation rules and workflow context
- **Python Type Safety Enhancement**: Fixed 41 Python type annotation issues in async_api_client.py using modern Optional, Union, and proper generic types
- **Critical System Fix**: Resolved syntax error in monitoring tools preventing MCP server startup, ensuring production reliability
- **Production Quality**: Enhanced developer experience and system maintainability while preserving all functionality
- **Documentation Enhancement**: Created comprehensive optimization specification document for future phases

**Recently Completed - MCP Server Exit Error Elimination** (2025-08-23):
- **Multi-Layered Exception Handling**: Implemented comprehensive exception handling solution at MCP SDK level to eliminate ugly exit errors
- **Professional Shutdown Experience**: Fixed persistent MCP server exit errors displaying ExceptionGroup and BrokenPipeError tracebacks
- **Safe Stdio Server Wrapper**: Added protective wrapper around MCP stdio server to catch and suppress MCP-specific shutdown errors
- **Enhanced Entry Point**: Updated main entry point with stream suppression and exit handlers for clean resource management
- **User Experience Enhancement**: Added helpful guidance when MCP server is run manually in terminal instead of through Claude Desktop
- **Claude Desktop Configuration Fix**: Updated configuration path from old checkmk_llm_agent to checkmk_mcp_server for correct integration

**Recently Completed - MCP CLI stdio Communication Timeout Fix** (2025-08-22):
- **Root Cause Analysis**: Identified MCP SDK 1.12.0 stdio transport timeout issues specifically affecting macOS systems
- **Intelligent Fallback System**: Implemented automatic fallback from MCP to direct CLI when stdio communication fails
- **Enhanced Connection Logic**: Added multi-layered timeout strategy (5s fast, 60s patient, 15s overall) for robust connection handling
- **Comprehensive Error Handling**: Added robust resource cleanup and connection verification to prevent hanging processes
- **User Experience Enhancement**: Commands like `python checkmk_cli_mcp.py hosts list` now work correctly on macOS
- **Architecture Validation**: Senior Python architect confirmed production-ready implementation with clean separation of concerns

**Recently Completed - Documentation Reorganization for Open Source Release** (2025-08-22):
- **Documentation Restructuring**: Transformed 719-line README into focused 144-line user value proposition
- **Documentation Hub**: Created organized docs/ structure with logical navigation and cross-references
- **User Experience Enhancement**: Created clear getting-started workflow with prerequisites, setup, and configuration guides
- **Documentation Consolidation**: Removed redundant configuration examples in favor of centralized, maintainable documentation

**Previously Completed - Checkmk Scraper Refactoring Phase 7 Completion** (2025-08-21):
- **Complete Architecture Transformation**: Successfully eliminated 9,349 lines of monolithic code and replaced with 25+ focused, maintainable modules
- **Modular Web Scraping System**: Created sophisticated 8-module architecture (scraper_service, auth_handler, factory, 3 extractors, parser, error handling)
- **Perfect Integration**: Seamlessly integrated modular scraper with historical service, MCP tools, and CLI commands
- **Enhanced Historical Commands**: Added 3 new CLI commands (historical scrape, services, test) with natural language support
- **Code Quality Excellence**: Fixed Python errors, type safety issues, and enhanced error handling across all modules
- **100% Functionality Preservation**: Maintained all original capabilities (Temperature Zone 0 etc.) while dramatically improving maintainability
- **Production Ready**: Complete modular architecture with comprehensive error handling and zero breaking changes

**Previously Completed - MCP Server Architecture Refactoring** (2025-08-20):
- **MCP Server Refactoring Complete**: Successfully refactored monolithic 4,449-line server.py into modular 456-line architecture (93% code reduction)
- **Service Container Implementation**: Added centralized dependency injection system with configuration registry and protocol handlers
- **Modular Tool Organization**: Organized 37 tools into 8 focused categories (host, service, monitoring, parameters, business, events, metrics, advanced)
- **100% Backward Compatibility**: All existing functionality preserved while enabling improved maintainability
- **Comprehensive Testing**: Added 200+ new test files with 85% success rate (188/221 tests passing)

**Previously Completed - Effective Parameters Warning Fix and Code Quality** (2025-08-18):
- **Warning Resolution**: Fixed false positive "No matching rules found" warning in get_service_effective_parameters() calls
- **Data Structure Fix**: Added missing `rule_count` field to API response structure for proper rule detection
- **Async Client Enhancement**: Fixed async API client implementation preventing incomplete responses in some scenarios  
- **Type Safety Improvements**: Added explicit Dict[str, Any] annotations throughout codebase to prevent data structure mismatches
- **Code Quality**: Cleaned up unused imports, variables, and improved error handling across multiple files
- **Pydantic Enhancement**: Improved recovery.py with proper configuration and field validation

**Previously Completed - Request ID Tracing System Implementation** (2025-08-07):
- **Complete Request ID Infrastructure**: Implemented comprehensive request ID tracing system with 6-digit hex IDs (req_xxxxxx) propagated through all system components
- **Thread-Safe Context Propagation**: Used contextvars for thread-safe request ID handling across async and sync operations
- **Enhanced Logging System**: Added RequestIDFormatter for consistent log format showing request IDs in all log messages
- **System-Wide Integration**: Integrated request tracing in MCP server (47 tools), API clients (sync/async), CLI interfaces, and service layers
- **Always-Enabled Design**: Created configuration-free system that works out of the box with no user setup required
- **Comprehensive Testing**: Added 4 new test files with unit, integration, and performance testing coverage

**Previously Completed - Host Check Configuration Prompts** (2025-08-07):
- **3 New MCP Prompts**: Implemented comprehensive host check parameter management with adjust_host_check_attempts, adjust_host_retry_interval, and adjust_host_check_timeout
- **Intelligent Configuration**: Network-aware recommendations based on host location, connection type, and performance characteristics
- **Production Validation**: Comprehensive parameter validation with range checking (1-10 attempts, 0.1-60 minute intervals)
- **Checkmk API Integration**: Direct rule creation and management through REST API with proper folder handling
- **Documentation Accuracy**: Technical review of README removing marketing language, fixing tool count to 47, adding limitations section

**Previously Completed - Temperature Parameter API Fix** (2025-08-03):
- **Fixed Critical API Error**: Resolved "The value 75 has type int, but must be of type float" error for temperature parameter rules
- **Integer-to-Float Conversion**: Automatically converts integer temperature thresholds (75) to floats (75.0) for API compliance  
- **Backward Compatibility**: Preserves integers for non-temperature rulesets to maintain existing functionality
- **Comprehensive Testing**: Added test coverage for mixed data types, edge cases, and ruleset detection
- **Production Ready**: Fix applies to all temperature-related rulesets (temperature, hw_temperature, ipmi_sensors, etc.)

**Comprehensive Service Parameter Management** - Previously completed enterprise-grade parameter management system:
- **Universal Parameter Support**: Implemented complete system for reading/writing ALL service parameters including temperature sensors
- **Specialized Handlers**: Created 4 intelligent parameter handlers (temperature, database, network, custom checks) with domain expertise
- **Dynamic Discovery**: Implemented API-driven ruleset discovery supporting 50+ service types with fuzzy matching
- **Schema Validation**: Added comprehensive parameter validation using Checkmk API schemas with fallback validation
- **Enhanced MCP Server**: Added 12 new parameter management tools (40 total tools) for complete parameter operations
- **100% Test Coverage**: Achieved perfect test pass rate with comprehensive debugging and validation
- **Production Readiness**: Enterprise-grade parameter management with intelligent handlers and robust error handling

**Previously Completed**:
- **Real-time Error Monitoring**: Implemented live monitoring of MCP server logs during Claude testing
- **Service State Accuracy**: Fixed critical issue where services displayed "Unknown" instead of actual monitoring states (OK, WARNING, CRITICAL)
- **API Endpoint Correction**: Fixed CLI to use monitoring endpoint (/domain-types/service/collections/all) instead of configuration endpoint for accurate service data
- **Complete MCP Integration**: All 18 enhanced MCP tools fully functional with Claude, providing accurate real-time monitoring data
- MCP server tool registration and core functionality implementation
- Enhanced host service status functionality with rich dashboards and problem categorization
- Advanced CLI filtering and natural language query support
- Comprehensive service operations and discovery capabilities

## API Architecture

The project centers around the comprehensive Checkmk REST API v1.0 specification:

### Core API Categories
- **Monitoring Operations**: Acknowledge problems, downtimes, host/service status
- **Setup & Configuration**: Host/service management, user management, rules/rulesets
- **Service Discovery**: Automated service detection and configuration
- **Service Management**: Service status monitoring, acknowledgments, downtime scheduling
- **Business Intelligence**: BI operations and analytics
- **Internal Operations**: Certificate management, activation, agent downloads

### Key Endpoints Structure
- Authentication via Checkmk's auth mechanisms
- Resource-oriented REST design
- Comprehensive permission model for each endpoint
- Stateless HTTP/1.1 protocol

## Development Commands

Currently no build system is configured. When implementing:

### Python Implementation (Recommended)
```bash
# Setup virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run agent
python checkmk_mcp_server.py
```

## Architecture Considerations

### API Integration
- **Base URL**: Configure Checkmk server URL
- **Authentication**: Implement Checkmk auth (automation user tokens recommended)
- **Rate Limiting**: Implement throttling for API calls
- **Error Handling**: Robust handling of API errors and timeouts

### LLM Integration
- **Natural Language Processing**: Convert user queries to API calls
- **Response Formatting**: Convert API responses to human-readable format
- **Context Management**: Maintain conversation context for multi-step operations

### Security
- **Credential Management**: Secure storage of Checkmk credentials
- **Permission Validation**: Respect Checkmk's permission model
- **Data Sanitization**: Handle sensitive monitoring data appropriately

## File Structure

```
checkmk-rest-openapi.yaml     # Complete Checkmk REST API specification (21k+ lines)
checkmk_mcp_server.code-workspace  # VS Code workspace configuration
.claude/settings.local.json   # Claude Code permissions

checkmk_mcp_server/
├── __init__.py
├── api_client.py             # Core API client with service operations
├── cli.py                    # Enhanced CLI interface with interactive mode
├── config.py                 # Configuration management
├── host_operations.py        # Host management operations
├── service_operations.py     # Service management operations
├── service_parameters.py     # Service parameter management
├── llm_client.py            # LLM integration
├── logging_utils.py         # Logging utilities
├── utils.py                 # Utility functions
├── interactive/             # Enhanced interactive mode components
│   ├── __init__.py
│   ├── readline_handler.py   # Command history and readline integration
│   ├── command_parser.py     # Enhanced command parsing with fuzzy matching
│   ├── help_system.py        # Comprehensive contextual help system
│   ├── tab_completer.py      # Tab completion for commands and parameters
│   └── ui_manager.py         # Rich UI formatting and messaging
├── mcp_server/              # MCP Server Integration (FULLY FUNCTIONAL)
│   ├── __init__.py
│   └── server.py             # Enhanced MCP server - 40 tools exposed
└── services/                # Service Layer Architecture
    ├── __init__.py
    ├── parameter_service.py  # Comprehensive parameter management with specialized handlers
    ├── status_service.py     # Status operations with all methods implemented
    ├── cache_service.py      # Caching and performance optimization
    ├── batch_service.py      # Batch processing capabilities
    ├── streaming_service.py  # Real-time streaming operations
    └── handlers/             # Specialized Parameter Handlers
        ├── __init__.py
        ├── base.py           # Base handler class and registry
        ├── temperature.py    # Temperature monitoring handler
        ├── database.py       # Database monitoring handler
        ├── network.py        # Network service handler
        └── custom_checks.py  # Custom check handler

tests/
├── __init__.py
├── conftest.py
├── test_api_client.py
├── test_cli.py
├── test_host_operations.py
├── test_service_operations.py # Service operations tests
├── test_integration.py
├── test_llm_client.py
├── test_batch.py             # Batch processing tests
├── test_cache.py             # Caching functionality tests
├── test_performance.py       # Performance optimization tests
└── test_streaming.py         # Streaming operations tests

examples/
├── README.md
└── configs/
    ├── development.yaml
    ├── production.yaml
    └── testing.yaml
```

## Development Workflow

1. **API Client**: ✅ Checkmk REST API client with host/rule/service operations
2. **LLM Integration**: ✅ Natural language processing capabilities
3. **Agent Logic**: ✅ Conversation flow and command routing for hosts/rules/services
4. **MCP Server Integration**: ✅ Unified server with all advanced features fully functional
5. **Testing**: ✅ Test coverage for core operations
6. **Documentation**: ✅ Setup and usage guides

## MCP Server Integration

The project includes comprehensive MCP (Model Context Protocol) server integration for seamless Claude AI integration:

### Enhanced MCP Server (`checkmk_mcp_server/mcp_server/server.py`)
- **40 Tools Exposed**: Complete coverage of all Checkmk operations with advanced features and comprehensive parameter management
- **Status**: ✅ Fully Functional - Successfully tested with Claude, MCP CLI fully operational on macOS
- **Core Features**: Host operations, service management, status monitoring, problem analysis
- **Parameter Management**: 12 specialized tools for universal parameter read/write operations
- **Advanced Features**: Batch processing, streaming operations, caching, performance metrics, specialized handlers
- **MCP CLI Integration**: Robust stdio transport with intelligent fallback system for macOS compatibility
- **Entry Point**: `mcp_checkmk_server.py` - Single server for all use cases

### Recent Fixes (2025-07-25)
- Fixed tool registration using proper MCP SDK decorators (`@server.list_tools()`, `@server.call_tool()`)
- Implemented 6 missing StatusService methods for complete API coverage
- Added custom JSON serialization handling for datetime objects
- Worked around MCP SDK v1.12.0 CallToolResult construction bug
- Verified zero errors through real-time log monitoring

## Service Operations Architecture

The service operations functionality is built around these key components:

### 1. API Client Integration (`api_client.py`)
- **Service Status Methods**: `list_host_services()`, `list_all_services()`
- **Service Management**: `acknowledge_service_problems()`, `create_service_downtime()`
- **Service Discovery**: `get_service_discovery_result()`, `start_service_discovery()`
- **Pydantic Models**: Type-safe validation for all service operations

### 2. Service Operations Manager (`service_operations.py`)
- **Natural Language Processing**: Analyzes user commands for service operations
- **Command Routing**: Routes commands to appropriate API methods
- **Response Formatting**: Converts API responses to human-readable format
- **Error Handling**: Robust error handling with meaningful messages

### 3. CLI Interface (`cli.py`)
- **Services Command Group**: Complete CLI interface for service operations
  - `services list [host_name]` - List services
  - `services status <host> <service>` - Get service status
  - `services acknowledge <host> <service>` - Acknowledge problems
  - `services downtime <host> <service>` - Create downtime
  - `services discover <host>` - Discover services
  - `services stats` - Show service statistics
- **Interactive Mode**: Natural language service commands in interactive mode

### 4. Supported Service Operations

#### Service Status and Monitoring
- **List Services**: View all services for a host or across all hosts
- **Service Status**: Get detailed status information for specific services
- **Service Statistics**: Overview of service states across the infrastructure

#### Service Problem Management
- **Acknowledge Problems**: Acknowledge service problems with comments
- **Create Downtime**: Schedule downtime periods for planned maintenance
- **Sticky/Persistent Options**: Control acknowledgment behavior

#### Service Discovery
- **Automated Discovery**: Discover new services on hosts
- **Discovery Modes**: Multiple discovery modes (refresh, new, remove, fixall)
- **Discovery Results**: Review discovered, vanished, and ignored services

### 5. Natural Language Examples

The system understands commands like:
- `"list services for server01"`
- `"show all services"`
- `"acknowledge CPU load on server01"`
- `"create 4 hour downtime for disk space on server01"`
- `"discover services on server01"`

### 6. Error Handling and Validation

- **API Error Handling**: Comprehensive error handling for all API operations
- **Input Validation**: Pydantic models ensure type safety
- **User-Friendly Messages**: Clear error messages and success confirmations
- **Retry Logic**: Built-in retry mechanism with exponential backoff

## Conversation Storage

Conversations with the AI assistant should be saved to preserve context, decisions, and progress. Each conversation must follow this standardized format:

```
TITLE: [Brief topic descriptor]
DATE: YYYY-MM-DD
PARTICIPANTS: [Comma-separated list]
SUMMARY: [Key points and decisions]

INITIAL PROMPT: [User's first substantive message only - exclude any system instructions or project context references]

KEY DECISIONS:
- [Decision point 1]
- [Decision point 2]

FILES CHANGED:
- [File 1] Summary of changes
- [File 2] Summary of changes
```

### Storage Guidelines
- Conversations should be stored in `docs/conversations/` organized by date (YYYY-MM/)
- File naming convention: `YYYY-MM-DD-HHMM-[brief-topic-slug].md` 
- **Timestamp Requirements**:
  - Use todays date and time
  - Use **UTC timezone** for all timestamps
  - Use **24-hour format** (HHMM) 
  - Timestamp should reflect **conversation start time** (when user sends first substantive message)
  - To determine UTC time: check current UTC time when conversation begins, or convert local time to UTC
  - Example: If conversation starts at 2:30 PM EST (UTC-5), use `1930` (7:30 PM UTC)
- Conversations that result in architecture decisions should be referenced in the relevant architecture docs
- Conversations that define features should be linked from the project documentation
- **IMPORTANT**: The INITIAL PROMPT must contain only the user's actual first message, not any system instructions about reading project context or role assignments

## Implementation Notes

- The OpenAPI spec is comprehensive (21,353 lines) - use code generation tools when possible
- Focus on core monitoring operations first (acknowledge, downtimes, status checks)
- Consider async operations for real-time monitoring capabilities
- Implement proper logging for debugging API interactions