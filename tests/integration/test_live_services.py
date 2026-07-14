"""Live-site tests for service listing -- exercises the version-aware
GET/POST selection in CheckmkClient._request_service_collection (POST is
2.4+, GET-only on 2.2/2.3)."""

import pytest

pytestmark = pytest.mark.integration


class TestServiceListing:
    def test_list_all_services(self, live_client):
        services = live_client.list_all_services_with_monitoring_data()
        assert isinstance(services, list)
        # Seeded localhost host should have discovered services once the
        # site has run checks; tolerate empty on a very fresh site.
        for svc in services[:5]:
            ext = svc.get("extensions", {})
            assert "host_name" in ext or "host_name" in svc.get("title", "")

    def test_list_services_for_host(self, live_client):
        services = live_client.list_host_services_with_monitoring_data(
            "cmk-test-local"
        )
        assert isinstance(services, list)

    def test_list_services_with_query(self, live_client):
        """Query expressions must survive the GET conversion on 2.2."""
        services = live_client.list_all_services_with_monitoring_data(
            query='{"op": "=", "left": "host_name", "right": "cmk-test-local"}'
        )
        assert isinstance(services, list)
        for svc in services:
            ext = svc.get("extensions", {})
            if "host_name" in ext:
                assert ext["host_name"] == "cmk-test-local"

    def test_service_health_summary(self, live_client):
        summary = live_client.get_service_health_summary()
        assert isinstance(summary, dict)

    def test_readonly_user_can_list_services(self, live_ro_client):
        services = live_ro_client.list_all_services_with_monitoring_data()
        assert isinstance(services, list)
