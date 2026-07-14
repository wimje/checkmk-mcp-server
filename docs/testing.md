# Testing Guide

## Test Tiers

**Unit tests** (existing, mocked, no site needed):

```bash
pytest -m "not integration"
```

**Integration tests** (live Checkmk site required):

```bash
pytest -m integration tests/integration/
```

Integration tests are skipped automatically when `CHECKMK_TEST_URL` is
unset or the site is unreachable, so the full `pytest` run stays green
without a site.

## Setting Up Disposable Test Sites

```bash
# Start Checkmk 2.4 (port 8080) and 2.2 (port 8081) containers
docker compose -f docker-compose.test.yml up -d

# Wait for initialization (~1-2 min), then seed each site with the /test
# folder, automation users, and test hosts:
python scripts/seed_test_site.py --url http://localhost:8080 --site cmk
python scripts/seed_test_site.py --url http://localhost:8081 --site cmk

# Configure and run
cp .env.test.example .env.test
set -a; source .env.test; set +a
pytest -m integration tests/integration/

# Run the same suite against 2.2 to exercise version-compatibility paths
CHECKMK_TEST_URL=http://localhost:8081 pytest -m integration tests/integration/
```

Web UI for debugging: http://localhost:8080/cmk/ (cmkadmin / test123).

## What the Integration Suite Covers

- `test_live_basics.py` -- version parsing and compatibility check, host
  listing (including the monitoring-endpoint fallback for the
  monitoring-only user), host CRUD in the `/test` folder
- `test_live_services.py` -- service listing via the version-aware
  GET/POST selection, query expressions, health summary
- `test_live_ack_downtime.py` -- downtime create/list/delete,
  acknowledgement (with cleanup)
- `test_mcp_e2e.py` -- spawns `mcp_checkmk_server.py` as a subprocess and
  drives it through the real MCP client over stdio: session lifecycle,
  argument stripping, response unwrapping. This is the layer where unit
  tests can't catch regressions.

## Safety Rails

- Tests refuse to run unless the target host is `localhost` or listed in
  `CHECKMK_TEST_ALLOW` (comma-separated hostnames).
- All write operations are confined to the `/test` folder and hosts
  prefixed `cmk-test-`; fixtures clean up what they create.
- The seed script is idempotent -- rerun it any time.

## Working With AI Agents

For sessions where an AI agent (Claude Code / Cowork) should iterate on
this codebase autonomously, start the session inside WSL in the project
directory so the agent has shell access, bring the Docker sites up first,
and export the `.env.test` variables. The agent can then run the
integration suite itself after each change instead of asking you to test.
