#!/usr/bin/env python3
"""Seed a (disposable) Checkmk test site for integration testing.

Creates:
- A /test folder (all test writes are confined here)
- Automation users:
    cmk-test-admin  - full admin, for tests that need Setup write access
    cmk-test-ro     - monitoring-only, for permission/fallback tests
- Test hosts in /test: one monitoring localhost (gets real services via
  discovery), one with a dummy IP, one without an IP address
- Activates changes and starts service discovery on the localhost host

Usage:
    python scripts/seed_test_site.py --url http://localhost:8080 --site cmk \
        [--admin-user cmkadmin] [--admin-password test123]

Idempotent: safe to run repeatedly.
"""

import argparse
import sys
import time
from pathlib import Path

import requests

TEST_FOLDER = "test"
TEST_HOSTS = [
    {"host_name": "cmk-test-local", "attributes": {"ipaddress": "127.0.0.1"}},
    {"host_name": "cmk-test-dummy", "attributes": {"ipaddress": "192.0.2.10"}},
    {"host_name": "cmk-test-noip", "attributes": {}},
]
AUTOMATION_USERS = [
    {
        "username": "cmk-test-admin",
        "fullname": "Integration test admin",
        "roles": ["admin"],
        "password": "cmk-test-admin-secret",
    },
    {
        "username": "cmk-test-ro",
        "fullname": "Integration test read-only",
        "roles": ["guest"],
        "password": "cmk-test-ro-secret",
    },
]


class Api:
    def __init__(self, url: str, site: str, user: str, password: str):
        self.base = f"{url.rstrip('/')}/{site}/check_mk/api/1.0"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {user} {password}",
                "Accept": "application/json",
            }
        )

    def call(self, method: str, endpoint: str, expect=(200, 204), **kwargs):
        resp = self.session.request(method, self.base + endpoint, **kwargs)
        if resp.status_code not in expect:
            raise RuntimeError(
                f"{method} {endpoint} -> {resp.status_code}: {resp.text[:500]}"
            )
        return resp

    def exists(self, endpoint: str) -> bool:
        return self.session.get(self.base + endpoint).status_code == 200


def wait_for_site(api: Api, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = api.session.get(api.base + "/version", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        print("  waiting for site to come up...")
        time.sleep(10)
    raise RuntimeError(f"Site not reachable after {timeout}s")


def ensure_folder(api: Api) -> None:
    if api.exists(f"/objects/folder_config/~{TEST_FOLDER}"):
        print(f"  folder /{TEST_FOLDER} exists")
        return
    api.call(
        "POST",
        "/domain-types/folder_config/collections/all",
        json={"name": TEST_FOLDER, "title": "Integration tests", "parent": "~"},
    )
    print(f"  created folder /{TEST_FOLDER}")


def ensure_users(api: Api) -> None:
    for user in AUTOMATION_USERS:
        if api.exists(f"/objects/user_config/{user['username']}"):
            print(f"  user {user['username']} exists")
            continue
        api.call(
            "POST",
            "/domain-types/user_config/collections/all",
            json={
                "username": user["username"],
                "fullname": user["fullname"],
                "auth_option": {
                    "auth_type": "automation",
                    "secret": user["password"],
                },
                "roles": user["roles"],
            },
        )
        print(f"  created automation user {user['username']}")


def ensure_hosts(api: Api) -> None:
    for host in TEST_HOSTS:
        if api.exists(f"/objects/host_config/{host['host_name']}"):
            print(f"  host {host['host_name']} exists")
            continue
        api.call(
            "POST",
            "/domain-types/host_config/collections/all",
            json={
                "host_name": host["host_name"],
                "folder": f"/{TEST_FOLDER}",
                "attributes": host["attributes"],
            },
        )
        print(f"  created host {host['host_name']}")


def activate_changes(api: Api) -> None:
    resp = api.call(
        "POST",
        "/domain-types/activation_run/actions/activate-changes/invoke",
        expect=(200, 204, 302, 422),  # 422: no pending changes
        json={"redirect": False, "force_foreign_changes": True},
        headers={"If-Match": "*", "Content-Type": "application/json"},
    )
    if resp.status_code == 422:
        print("  no pending changes to activate")
    else:
        print("  activated changes")


def start_discovery(api: Api) -> None:
    resp = api.call(
        "POST",
        "/domain-types/service_discovery_run/actions/start/invoke",
        expect=(200, 204, 302, 404, 409),
        json={"host_name": "cmk-test-local", "mode": "fix_all"},
        headers={"Content-Type": "application/json"},
    )
    print(f"  discovery on cmk-test-local: HTTP {resp.status_code}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="e.g. http://localhost:8080")
    parser.add_argument("--site", default="cmk")
    parser.add_argument("--admin-user", default="cmkadmin")
    parser.add_argument("--admin-password", default="test123")
    args = parser.parse_args()

    api = Api(args.url, args.site, args.admin_user, args.admin_password)

    print(f"Seeding {args.url} (site {args.site})")
    info = wait_for_site(api)
    print(f"  Checkmk {info.get('versions', {}).get('checkmk', 'unknown')}")

    ensure_folder(api)
    ensure_users(api)
    ensure_hosts(api)
    activate_changes(api)
    start_discovery(api)
    activate_changes(api)

    print("Done. Test credentials:")
    for user in AUTOMATION_USERS:
        print(f"  {user['username']} / {user['password']} (roles: {user['roles']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
