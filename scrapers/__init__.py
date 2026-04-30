"""Scrapers package — data ingestion for NEU-Compass.

Public utilities exposed here. Per-source scrapers (syllabus, neu_catalog,
rmp, reddit) live in submodules and are imported lazily by callers to
avoid pulling httpx / praw / fitz when only one source is needed.
"""

from scrapers._base import create_client, fetch_with_retry, logger

__all__ = ["create_client", "fetch_with_retry", "logger"]
