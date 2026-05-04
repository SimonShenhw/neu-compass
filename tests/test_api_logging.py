"""Tests for api.logging — configure_logging idempotence + middleware contract."""

from __future__ import annotations

import logging

import structlog

from api.logging import configure_logging


def test_configure_logging_returns_bound_logger() -> None:
    log = configure_logging()
    # structlog 24+ wraps the stdlib BoundLogger; both forms are acceptable.
    assert hasattr(log, "info")
    assert hasattr(log, "bind")


def test_configure_logging_is_idempotent() -> None:
    """Lifespan and Streamlit can both call this; the second call must not
    duplicate handlers on the root logger."""
    configure_logging()
    handler_count_first = len(logging.getLogger().handlers)
    configure_logging()
    handler_count_second = len(logging.getLogger().handlers)
    assert handler_count_first == handler_count_second


def test_structlog_emits_through_configured_renderer(caplog) -> None:
    """Sanity: a log call after configure_logging produces a log record.

    caplog hooks into the stdlib logging module (via a special handler),
    which captures structlog's output regardless of where the StreamHandler
    pinned its stderr reference at configure-time."""
    log = configure_logging()
    with caplog.at_level("INFO"):
        log.info("test.event", foo="bar")
    assert any("test.event" in rec.message for rec in caplog.records)
