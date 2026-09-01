"""
Logging utilities for Orpheus services.

Provides standardized logging setup with structlog for structured, colorful logging.
Integrates with systemd journal in production and provides console output for development.
"""

import logging
import os
import sys
from typing import Optional

import structlog


def _is_running_under_systemd() -> bool:
    """
    Detect if the process is running under systemd.

    Returns:
        True if running under systemd, False otherwise
    """
    # Check for INVOCATION_ID environment variable, which is set by systemd
    if os.environ.get("INVOCATION_ID"):
        return True

    # Check for JOURNAL_STREAM, another systemd-specific variable
    if os.environ.get("JOURNAL_STREAM"):
        return True

    return False


def setup_logging(service_name: str, level: str = "INFO", use_json: bool = False) -> logging.Logger:
    """
    Configure logging for an Orpheus service or agent.

    Uses structlog for structured, colorful logging in development and JSON logging
    in production. Integrates with systemd journal when available.

    This configures the root logger so all loggers in the application inherit
    the configuration, ensuring consistent behavior across modules.

    Args:
        service_name: Name of the service (e.g., "orpheus-ui") - used for SYSLOG_IDENTIFIER
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Can be overridden by LOG_LEVEL env var.
        use_json: Output structured JSON logs (useful for log aggregation)

    Returns:
        Root logger instance

    Example:
        >>> from orpheus_common.logging import setup_logging, get_logger
        >>> setup_logging("my-agent", level="DEBUG")
        >>> logger = get_logger(__name__)  # This will inherit the configuration
        >>> logger.info("Service started", event_id="test_001")
        >>> logger.error("Something went wrong", error="Connection failed")
    """
    # Allow LOG_LEVEL environment variable to override
    log_level = os.environ.get("LOG_LEVEL", level).upper()

    # Configure the root logger so all loggers inherit the configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))

    # Remove any existing handlers from root logger
    root_logger.handlers.clear()

    # Detect if running under systemd
    running_under_systemd = _is_running_under_systemd()

    # Configure structlog processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    if use_json or running_under_systemd:
        # JSON output for production/systemd
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Colorful console output for development
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if running_under_systemd:
        # Use systemd journal handler for direct integration
        try:
            from systemd.journal import JournalHandler

            handler = JournalHandler(SYSLOG_IDENTIFIER=service_name)
            handler.setLevel(getattr(logging, log_level))

            # Journal handles its own timestamps and metadata
            formatter = structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
            )
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)

            # Also add stdout handler for backwards compatibility
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setLevel(getattr(logging, log_level))
            stdout_formatter = structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer()
                if use_json
                else structlog.dev.ConsoleRenderer(colors=True),
            )
            stdout_handler.setFormatter(stdout_formatter)
            root_logger.addHandler(stdout_handler)

        except ImportError:
            # Fallback to stdout if systemd.journal is not available
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(getattr(logging, log_level))
            formatter = structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer()
                if use_json
                else structlog.dev.ConsoleRenderer(colors=True),
            )
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)
    else:
        # Development mode: colorful console output
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, log_level))
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer()
            if use_json
            else structlog.dev.ConsoleRenderer(colors=True),
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    return root_logger


def get_logger(name: Optional[str] = None):
    """
    Get a structlog logger instance for a module.

    Returns a structlog BoundLogger that supports keyword arguments for structured logging.

    Args:
        name: Logger name (typically __name__). If None, returns root logger.

    Returns:
        structlog.BoundLogger instance

    Example:
        >>> from orpheus_common.logging import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("User logged in", user_id=123, ip="192.168.1.1")
        >>> logger.error("Failed to connect", error="timeout", retry_count=3)
    """
    # Return a structlog logger which wraps stdlib logging but supports keyword args
    return structlog.get_logger(name) if name else structlog.get_logger()


def log_exception_context(logger, message: str, exception: Exception, **kwargs):
    """
    Log an exception with context in a standardized way.

    This helper ensures consistent exception logging across the codebase.
    It automatically adds the exception message as 'error' and uses logger.exception()
    when called from within an exception handler.

    Args:
        logger: The logger instance (from get_logger)
        message: Static message describing what failed
        exception: The exception that was caught
        **kwargs: Additional context as keyword arguments

    Example:
        >>> try:
        ...     risky_operation()
        ... except ValueError as e:
        ...     log_exception_context(logger, "Operation failed", e, operation_id=123)
    """
    kwargs["error"] = str(exception)
    kwargs["exception_type"] = type(exception).__name__
    logger.exception(message, **kwargs)


def log_with_timing(logger, message: str, duration_seconds: float, **kwargs):
    """
    Log an operation with timing information in a standardized format.

    Args:
        logger: The logger instance (from get_logger)
        message: Static message describing the operation
        duration_seconds: Duration of the operation in seconds
        **kwargs: Additional context as keyword arguments

    Example:
        >>> import time
        >>> start = time.time()
        >>> do_work()
        >>> log_with_timing(logger, "Work completed", time.time() - start, items_processed=100)
    """
    kwargs["duration_ms"] = f"{duration_seconds * 1000:.2f}"
    logger.info(message, **kwargs)


def log_health_status(logger, component: str, status: str, **kwargs):
    """
    Log health/status information in a standardized format.

    Args:
        logger: The logger instance (from get_logger)
        component: Name of the component reporting health (e.g., "audio_input", "mqtt_client")
        status: Health status (e.g., "healthy", "degraded", "unhealthy", "unknown")
        **kwargs: Additional health metrics as keyword arguments

    Example:
        >>> log_health_status(logger, "audio_input", "healthy",
        ...                   device="hw:0,0", sample_rate=48000, channels=4)
    """
    kwargs["component"] = component
    kwargs["health_status"] = status
    logger.info("Health status report", **kwargs)


def log_metric(logger, metric_name: str, metric_value, **kwargs):
    """
    Log a metric in a standardized format for easy parsing.

    Args:
        logger: The logger instance (from get_logger)
        metric_name: Name of the metric
        metric_value: Value of the metric (will be converted to string)
        **kwargs: Additional context as keyword arguments

    Example:
        >>> log_metric(logger, "audio_level_db", -25.5, channel_id="1")
        >>> log_metric(logger, "frames_processed", 1000, camera_id="front")
    """
    kwargs["metric_name"] = metric_name
    kwargs["metric_value"] = str(metric_value)
    logger.debug("Metric", **kwargs)
