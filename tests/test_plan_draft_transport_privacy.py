"""A UI-only process must not leak read refs through HTTPX's own INFO logs."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("ref,path", [("CS-5800", "/course/c-cs-5800"),
    ("SYNTHETIC_PRIVATE_REF", "/course/SYNTHETIC_PRIVATE_ID/requisites")])
def test_plain_frontend_logging_handlers_do_not_see_course_identifiers(ref, path):
    script = r'''
import io, logging, sys
import httpx
from app.api_client import ApiClient
stream = io.StringIO()
logger = logging.getLogger("httpx")
logger.handlers[:] = [logging.StreamHandler(stream)]
logger.setLevel(logging.INFO)
logger.propagate = False
def response(request):
    return httpx.Response(200, json={"matches": []})
with ApiClient(base_url="http://synthetic-only", transport=httpx.MockTransport(response)) as api:
    api.resolve_course(sys.argv[1])
    api._get(sys.argv[2])
output = stream.getvalue()
assert sys.argv[1] not in output, output
assert sys.argv[2] not in output, output
assert "SYNTHETIC_PRIVATE" not in output and "ref=" not in output, output
assert "200" in output and "GET" in output, output
print("UI-only HTTPX logs retain status and method, not ref or course ID")
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, ref, path],
        env={**os.environ, "GEMINI_API_KEY": "ci-placeholder-not-a-secret", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_httpx_source_filter_removes_fragments_and_preserves_unrelated_urls():
    import logging

    import httpx

    from app.api_client import _CourseReadTransportFilter

    private = httpx.URL("http://synthetic-only/course/private?ref=PRIVATE#SYNTHETIC_PRIVATE_FRAGMENT")
    public = httpx.URL("http://synthetic-only/ready?ordinary=value")
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "%s %s", (private, public), None)
    assert _CourseReadTransportFilter().filter(record)
    shown = record.getMessage()
    assert "PRIVATE" not in shown and "private" not in shown
    assert str(public) in shown
