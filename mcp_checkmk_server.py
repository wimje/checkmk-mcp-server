#!/usr/bin/env python3
"""
Checkmk MCP Server Entry Point

This script starts the Checkmk MCP server with advanced features:
- Streaming support for large datasets
- Caching layer for improved performance  
- Batch operations for bulk processing
- Performance monitoring and metrics
- Advanced error recovery and resilience

Usage:
    python mcp_checkmk_server.py [--config CONFIG_FILE] [--log-level LEVEL]

The server will run on stdio by default for MCP client integration.
"""

import sys
import asyncio
import logging
import argparse
import signal
import warnings
import contextlib
import io
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from checkmk_mcp_server.config import load_config
from checkmk_mcp_server.mcp_server import CheckmkMCPServer

# ExceptionGroup/BaseExceptionGroup are builtins only in Python 3.11+.
# On older versions, use the exceptiongroup backport (a dependency of anyio),
# falling back to stub classes so `except (ExceptionGroup, ...)` stays valid.
if sys.version_info < (3, 11):
    try:
        from exceptiongroup import ExceptionGroup, BaseExceptionGroup
    except ImportError:

        class BaseExceptionGroup(BaseException):  # type: ignore[no-redef]
            pass

        class ExceptionGroup(BaseExceptionGroup, Exception):  # type: ignore[no-redef]
            pass


def _is_client_disconnect_error(exception: Exception) -> bool:
    """Check if an exception represents a client disconnect."""
    # Direct pipe/connection errors
    if isinstance(exception, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
        
    # String-based detection for wrapped errors
    error_str = str(exception)
    error_indicators = [
        "Broken pipe", "Connection reset", "Connection aborted",
        "BrokenResourceError", "ClosedResourceError", 
        "[Errno 32]", "[Errno 104]"
    ]
    
    return any(indicator in error_str for indicator in error_indicators)


def _is_client_disconnect_group(exception_group) -> bool:
    """Check if ExceptionGroup contains only client disconnect errors."""
    try:
        # Handle both ExceptionGroup and BaseExceptionGroup
        if hasattr(exception_group, 'exceptions'):
            exceptions = exception_group.exceptions
        else:
            return False
            
        # Check if all exceptions are client disconnects
        if not exceptions:
            return False
            
        for exc in exceptions:
            # Handle nested exception groups recursively
            if isinstance(exc, (ExceptionGroup, BaseExceptionGroup)):
                if not _is_client_disconnect_group(exc):
                    return False
            elif not _is_client_disconnect_error(exc):
                return False
                
        return True
        
    except Exception:
        # If we can't analyze the exception group, assume it's not a disconnect
        return False


@contextlib.contextmanager
def _suppress_pipe_errors():
    """Context manager to suppress pipe errors on stdout/stderr during shutdown."""
    original_stderr = sys.stderr
    original_stdout = sys.stdout
    
    class PipeErrorSuppressingStream:
        def __init__(self, original_stream):
            self.original_stream = original_stream
            
        def write(self, data):
            try:
                return self.original_stream.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # Suppress pipe errors during shutdown
                return len(data)
                
        def flush(self):
            try:
                return self.original_stream.flush()
            except (BrokenPipeError, ConnectionResetError):
                # Suppress flush errors during shutdown
                pass
                
        def __getattr__(self, name):
            return getattr(self.original_stream, name)
    
    try:
        # Only wrap streams if they're the original stdout/stderr
        if sys.stderr is original_stderr:
            sys.stderr = PipeErrorSuppressingStream(original_stderr)
        if sys.stdout is original_stdout:
            sys.stdout = PipeErrorSuppressingStream(original_stdout)
        yield
    finally:
        # Restore original streams
        sys.stderr = original_stderr
        sys.stdout = original_stdout


def setup_logging(log_level: str = "INFO"):
    """Setup logging configuration with request ID support."""
    # Import the proper logging setup function
    from checkmk_mcp_server.logging_utils import setup_logging as proper_setup_logging
    
    # Use the proper setup with request ID support but output to stderr for MCP
    proper_setup_logging(log_level, include_request_id=True)
    
    # Ensure all handlers output to stderr to avoid interfering with stdio MCP transport
    root_logger = logging.getLogger()
    handlers_to_replace = []
    for handler in root_logger.handlers[:]:  # Use slice to iterate over a copy
        if isinstance(handler, logging.StreamHandler) and hasattr(handler, 'stream'):
            if handler.stream not in (sys.stderr, sys.__stderr__):
                handlers_to_replace.append(handler)
    
    # Replace handlers that don't use stderr
    for old_handler in handlers_to_replace:
        # Create new handler with same formatter but using stderr
        new_handler = logging.StreamHandler(sys.stderr)
        new_handler.setLevel(old_handler.level)
        if old_handler.formatter:
            new_handler.setFormatter(old_handler.formatter)
        
        # Replace the old handler
        root_logger.removeHandler(old_handler)
        root_logger.addHandler(new_handler)
    
    # Suppress common shutdown-related warnings and pipe errors
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="anyio")
    
    # Suppress broken pipe errors during normal shutdown
    logging.getLogger("mcp.server.stdio").setLevel(logging.CRITICAL)
    logging.getLogger("anyio").setLevel(logging.WARNING)
    logging.getLogger("anyio._backends._asyncio").setLevel(logging.CRITICAL)
    
    # Create a custom handler to suppress pipe errors
    class PipeErrorSuppressingHandler(logging.Handler):
        def emit(self, record):
            # Suppress specific pipe error messages
            if record.exc_info:
                exc_type, exc_value, exc_traceback = record.exc_info
                if isinstance(exc_value, (BrokenPipeError, ConnectionResetError)):
                    return
                if (isinstance(exc_value, (ExceptionGroup, BaseExceptionGroup)) and 
                    "Broken pipe" in str(exc_value)):
                    return
    
    # Add the suppressing handler to the root logger
    root_logger.addHandler(PipeErrorSuppressingHandler())


# Global shutdown flag and server reference for signal handling
_shutdown_event = None
_server_instance = None

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    global _shutdown_event, _server_instance
    
    # Track if we've already received a signal
    received_signal = False
    
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        nonlocal received_signal
        
        signal_name = signal.Signals(signum).name
        
        if not received_signal:
            received_signal = True
            # Silent shutdown - no print statements that could interfere with stdio
            
            # Set shutdown event for graceful shutdown
            if _shutdown_event and not _shutdown_event.is_set():
                _shutdown_event.set()
            
            # For immediate shutdown when event loop is not running or blocked
            # Schedule a task to exit cleanly rather than raising KeyboardInterrupt
            try:
                # Try to get the current event loop
                loop = asyncio.get_running_loop()
                if loop and not loop.is_closed():
                    # Schedule graceful shutdown through the event loop
                    def set_shutdown():
                        if _shutdown_event and not _shutdown_event.is_set():
                            _shutdown_event.set()
                    loop.call_soon_threadsafe(set_shutdown)
                    return
            except RuntimeError:
                # No running event loop, will handle below
                pass
                
            # If no event loop is running, exit immediately but cleanly
            if signum == signal.SIGINT:
                # Exit cleanly without traceback
                sys.exit(0)
        else:
            # Second signal - force immediate exit
            sys.exit(1)
    
    # Handle common termination signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # On Unix systems, handle SIGHUP as well
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)

async def main():
    """Main entry point for the Checkmk MCP server."""
    global _shutdown_event, _server_instance
    
    parser = argparse.ArgumentParser(description="Checkmk MCP Server")
    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Path to configuration file"
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level"
    )
    parser.add_argument(
        "--transport", "-t",
        choices=["stdio"],
        default="stdio",
        help="Transport type for MCP server"
    )
    parser.add_argument(
        "--enable-caching",
        action="store_true",
        help="Enable caching layer for improved performance"
    )
    parser.add_argument(
        "--enable-streaming",
        action="store_true", 
        help="Enable streaming for large datasets"
    )
    parser.add_argument(
        "--enable-metrics",
        action="store_true",
        help="Enable performance monitoring and metrics collection"
    )
    parser.add_argument(
        "--force-mcp",
        action="store_true",
        help="Force MCP server mode even when run in terminal"
    )
    
    args = parser.parse_args()
    
    # Check if this is being run manually in a terminal
    if sys.stdin.isatty() and sys.stdout.isatty() and not args.force_mcp:
        print("╭─────────────────────────────────────────────────────────────────╮")
        print("│                      Checkmk MCP Server                         │")
        print("╰─────────────────────────────────────────────────────────────────╯")
        print()
        print("This is an MCP (Model Context Protocol) server designed to be")
        print("called by AI clients like Claude Desktop, not run manually.")
        print()
        print("For interactive use, try:")
        print("  python checkmk_cli_mcp.py interactive")
        print()
        print("For MCP client setup, see:")
        print("  docs/getting-started.md")
        print()
        print("To force MCP server mode anyway, use: --force-mcp")
        return
    
    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    
    # Setup signal handlers and shutdown event
    _shutdown_event = asyncio.Event()
    setup_signal_handlers()
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        logger.info("Starting Checkmk MCP Server...")
        logger.info(f"Checkmk URL: {config.checkmk.server_url}")
        logger.info(f"Transport: {args.transport}")

        # Verify the Checkmk server and REST API versions are supported
        from checkmk_mcp_server.api_client import CheckmkClient

        compat = CheckmkClient(config.checkmk).check_version_compatibility()
        if compat["compatible"] is False:
            for issue in compat["issues"]:
                logger.error(issue)
            logger.error(
                "Unsupported Checkmk server -- refusing to start. "
                "See docs/getting-started.md for supported versions."
            )
            sys.exit(1)
        elif compat["compatible"] is None:
            # Could not be determined (e.g. transient network problem or
            # unusual version string) -- warn but keep starting.
            for issue in compat["issues"]:
                logger.warning(issue)
        else:
            logger.info(
                f"Checkmk {compat['checkmk_version']} "
                f"(REST API {compat['api_revision']}) -- supported"
            )
        
         # Log advanced features only if enabled
        advanced_features = []
        if args.enable_streaming:
            advanced_features.append("  - ✓ Streaming support for large datasets")
        if args.enable_caching:
            advanced_features.append("  - ✓ Caching layer for improved performance")
        if args.enable_metrics:
            advanced_features.append("  - ✓ Performance monitoring and metrics collection")
        
        if advanced_features:
            logger.info("Features Enabled:")
            for feature in advanced_features:
                logger.info(feature)

        # Create and initialize the server with feature flags
        server = CheckmkMCPServer(config)
        _server_instance = server
        
        # Advanced feature flags can be passed during initialization if needed
        # For now, these are available as command-line arguments for future use
        # feature_config = {
        #     'caching': args.enable_caching,
        #     'streaming': args.enable_streaming,
        #     'metrics': args.enable_metrics
        # }
        
        await server.initialize()
        
        logger.info("MCP Server initialized, starting transport...")
        
        # Ensure stdio streams are properly configured for MCP communication
        if args.transport == "stdio":
            # Flush any remaining output to stderr before starting MCP
            sys.stderr.flush()
        
        # Run the server with graceful shutdown handling
        try:
            # Suppress any stderr output during server operation to prevent interference
            with _suppress_pipe_errors():
                await server.run(transport_type=args.transport, shutdown_event=_shutdown_event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Client disconnected - this is normal, don't log as error
            logger.debug("Client disconnected")
        except (ExceptionGroup, BaseExceptionGroup) as eg:
            # Handle exception groups from anyio task groups
            if _is_client_disconnect_group(eg):
                logger.debug("Client disconnected (exception group)")
            else:
                raise
        except asyncio.CancelledError:
            # Task was cancelled - normal during shutdown
            logger.debug("Server task cancelled")
        except Exception as e:
            # Check if this is a connection error hidden in another exception type
            if _is_client_disconnect_error(e):
                logger.debug(f"Client disconnected (wrapped): {type(e).__name__}")
            else:
                raise
        
    except KeyboardInterrupt:
        # This is now handled by signal handler, but keep as final backstop
        # Exit silently without additional logging
        pass
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        # Direct pipe errors during startup - client disconnected
        logger.debug("Client disconnected during startup")
    except (ExceptionGroup, BaseExceptionGroup) as eg:
        # Handle exception groups from startup
        if _is_client_disconnect_group(eg):
            logger.debug("Client disconnected during startup (exception group)")
        else:
            logger.exception("Fatal error in MCP server (exception group)")
            sys.exit(1)
    except Exception as e:
        # Only log as fatal error if it's not a connection/pipe issue
        if _is_client_disconnect_error(e):
            logger.debug(f"Client disconnected during startup: {type(e).__name__}")
        else:
            logger.exception("Fatal error in MCP server")
            sys.exit(1)
    finally:
        # Ensure clean shutdown
        if _server_instance:
            try:
                await _server_instance.shutdown()
            except Exception:
                # Suppress shutdown errors - already shutting down
                pass


if __name__ == "__main__":
    try:
        # Suppress "Exception ignored" messages during shutdown
        import atexit
        
        def suppress_stderr_on_exit():
            """Suppress stderr during final cleanup to prevent pipe error messages."""
            try:
                # Try to close stderr gracefully
                if hasattr(sys.stderr, 'close') and not sys.stderr.closed:
                    sys.stderr.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            # Redirect stderr to devnull for final cleanup
            sys.stderr = open('/dev/null', 'w') if hasattr(sys, '_getframe') else sys.stderr
        
        # Register exit handler to suppress final pipe errors
        atexit.register(suppress_stderr_on_exit)
        
        asyncio.run(main())
    except KeyboardInterrupt:
        # Final catch for any KeyboardInterrupt that escapes signal handling
        # Exit silently without traceback
        sys.exit(0)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        # Final catch for pipe errors during startup/shutdown
        sys.exit(0)
    except (ExceptionGroup, BaseExceptionGroup) as eg:
        # Final catch for exception groups
        if _is_client_disconnect_group(eg):
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        # Final catch for any other errors
        if _is_client_disconnect_error(e):
            sys.exit(0)
        else:
            sys.exit(1)