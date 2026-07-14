"""Live-site tests for downtime and acknowledgement -- create and clean up."""

import time

import pytest

from checkmk_mcp_server.api_client import CheckmkAPIError

pytestmark = pytest.mark.integration


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)) or time.strftime(
        "%Y-%m-%dT%H:%M:%S+0000", time.gmtime(ts)
    )


class TestDowntime:
    COMMENT = "integration-test-downtime"

    def test_create_list_delete_host_downtime(self, live_client):
        now = time.time()
        live_client._make_request(
            "POST",
            "/domain-types/downtime/collections/host",
            json={
                "downtime_type": "host",
                "host_name": "cmk-test-local",
                "start_time": _iso(now),
                "end_time": _iso(now + 300),
                "comment": self.COMMENT,
            },
        )

        downtimes = live_client._make_request(
            "GET",
            "/domain-types/downtime/collections/all",
            params={"host_name": "cmk-test-local"},
        ).get("value", [])
        ours = [
            d
            for d in downtimes
            if d.get("extensions", {}).get("comment") == self.COMMENT
        ]
        assert ours, "created downtime should be listed"

        # Cleanup
        live_client._make_request(
            "POST",
            "/domain-types/downtime/actions/delete/invoke",
            json={
                "delete_type": "query",
                "query": (
                    '{"op": "=", "left": "host_name", "right": "cmk-test-local"}'
                ),
            },
        )


class TestAcknowledge:
    def test_acknowledge_host_problem_or_clean_rejection(self, live_client):
        """The dummy host (unreachable IP) is normally DOWN and can be
        acknowledged; on a fresh site it may still be PENDING/UP, in which
        case Checkmk rejects the acknowledgement -- both are valid API
        behavior, what we assert is: no crash and a well-formed response."""
        try:
            live_client._make_request(
                "POST",
                "/domain-types/acknowledge/collections/host",
                json={
                    "acknowledge_type": "host",
                    "host_name": "cmk-test-dummy",
                    "comment": "integration-test-ack",
                    "sticky": False,
                    "notify": False,
                    "persistent": False,
                },
            )
        except CheckmkAPIError as e:
            # Not currently in a problem state -- a clean, well-formed
            # rejection is acceptable
            assert e.status_code in (400, 422), f"unexpected error: {e}"
