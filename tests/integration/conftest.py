"""Fixtures for integration tests against a live Checkmk site.

Configuration via environment variables (see .env.test.example):
    CHECKMK_TEST_URL       e.g. http://localhost:8080  (required)
    CHECKMK_TEST_SITE      site name, default "cmk"
    CHECKMK_TEST_USER      automation user, default "cmk-test-admin"
    CHECKMK_TEST_PASSWORD  its secret, default "cmk-test-admin-secret"
    CHECKMK_TEST_RO_USER / CHECKMK_TEST_RO_PASSWORD
                           monitoring-only user for permission tests
    CHECKMK_TEST_ALLOW     extra allowed hostnames (comma-separated)

All tests here are marked "integration" and are skipped when
CHECKMK_TEST_URL is unset or the site is unreachable. Run with:

    pytest -m integration tests/integration/

Safety: writes are confined to the /test folder and to hosts prefixed
"cmk-test-". The URL must point at localhost or an explicitly allowlisted
host -- this suite refuses to run against anything else.
"""

import os
import uuid
from urllib.parse import urlparse

import pytest

from checkmk_mcp_server.api_client import CheckmkClient, CheckmkAPIError
from checkmk_mcp_server.config import CheckmkConfig

pytestmark = pytest.mark.integration

TEST_FOLDER = "/test"
TEST_HOST_PREFIX = "cmk-test-"
_ALWAYS_ALLOWED = {"localhost", "127.0.0.1", "::1"}


def _test_url() -> str:
    return os.environ.get("CHECKMK_TEST_URL", "")


def _url_allowed(url: str) -> bool:
    host = urlparse(url).hostname or ""
    allowed = _ALWAYS_ALLOWED | {
        h.strip()
        for h in os.environ.get("CHECKMK_TEST_ALLOW", "").split(",")
        if h.strip()
    }
    return host in allowed


def _make_config(user_env: str, password_env: str, defaults) -> CheckmkConfig:
    return CheckmkConfig(
        server_url=_test_url(),
        site=os.environ.get("CHECKMK_TEST_SITE", "cmk"),
        username=os.environ.get(user_env, defaults[0]),
        password=os.environ.get(password_env, defaults[1]),
    )


@pytest.fixture(scope="session")
def live_client() -> CheckmkClient:
    """Admin client against the live test site (skips if unavailable)."""
    url = _test_url()
    if not url:
        pytest.skip("CHECKMK_TEST_URL not set -- skipping integration tests")
    if not _url_allowed(url):
        pytest.skip(
            f"Refusing to run integration tests against {url!r}: host is not "
            "localhost and not in CHECKMK_TEST_ALLOW"
        )

    client = CheckmkClient(
        _make_config(
            "CHECKMK_TEST_USER",
            "CHECKMK_TEST_PASSWORD",
            ("cmk-test-admin", "cmk-test-admin-secret"),
        )
    )
    try:
        client.get_version_info()
    except CheckmkAPIError as e:
        pytest.skip(f"Checkmk test site not reachable: {e}")
    return client


@pytest.fixture(scope="session")
def live_ro_client(live_client) -> CheckmkClient:
    """Monitoring-only client (for permission/fallback tests)."""
    return CheckmkClient(
        _make_config(
            "CHECKMK_TEST_RO_USER",
            "CHECKMK_TEST_RO_PASSWORD",
            ("cmk-test-ro", "cmk-test-ro-secret"),
        )
    )


@pytest.fixture
def temp_host(live_client):
    """A uniquely named host in /test, deleted afterwards."""
    host_name = f"{TEST_HOST_PREFIX}{uuid.uuid4().hex[:8]}"
    live_client._make_request(
        "POST",
        "/domain-types/host_config/collections/all",
        json={
            "host_name": host_name,
            "folder": TEST_FOLDER,
            "attributes": {"ipaddress": "192.0.2.99"},
        },
    )
    yield host_name
    try:
        live_client._make_request("DELETE", f"/objects/host_config/{host_name}")
    except CheckmkAPIError:
        pass  # already deleted by the test
