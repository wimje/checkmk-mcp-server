"""Live-site tests: version compatibility, host listing, permission fallback."""

import pytest

pytestmark = pytest.mark.integration


class TestVersionCompatibility:
    def test_version_info(self, live_client):
        info = live_client.get_version_info()
        assert "versions" in info
        assert live_client.parse_checkmk_version(
            info["versions"].get("checkmk", "")
        ), "server version should be parseable"

    def test_compatibility_check(self, live_client):
        compat = live_client.check_version_compatibility()
        assert compat["compatible"] is True, compat["issues"]
        assert compat["checkmk_version"]
        assert compat["api_revision"]


class TestHostListing:
    def test_list_hosts_contains_seeded_hosts(self, live_client):
        hosts = live_client.list_hosts()
        names = {h.get("id") for h in hosts}
        assert "cmk-test-local" in names, (
            "expected seeded host; run scripts/seed_test_site.py first"
        )

    def test_monitoring_fallback_for_readonly_user(self, live_ro_client):
        """Monitoring-only users must still see hosts (monitoring endpoint
        fallback when host_config is empty/403)."""
        hosts = live_ro_client.list_hosts()
        names = {h.get("id") for h in hosts}
        assert "cmk-test-local" in names

    def test_get_host(self, live_client):
        host = live_client.get_host("cmk-test-local")
        assert host.get("id") == "cmk-test-local"


class TestHostCrud:
    def test_create_get_delete(self, temp_host, live_client):
        host = live_client.get_host(temp_host)
        assert host.get("id") == temp_host
        ext = host.get("extensions", {})
        assert ext.get("folder", "").strip("/") == "test"

        live_client._make_request("DELETE", f"/objects/host_config/{temp_host}")
        hosts = {h.get("id") for h in live_client.list_hosts()}
        assert temp_host not in hosts
