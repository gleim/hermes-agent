"""Contract tests for PaaS / Railway bootstrap in docker/entrypoint.sh."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.sh"


@pytest.fixture(scope="module")
def entrypoint_text() -> str:
    if not ENTRYPOINT.exists():
        pytest.skip("docker/entrypoint.sh not present")
    return ENTRYPOINT.read_text()


def test_entrypoint_detects_railway_env(entrypoint_text):
    assert "RAILWAY_ENVIRONMENT" in entrypoint_text
    assert "RAILWAY_SERVICE_NAME" in entrypoint_text
    assert "HERMES_PAAS_HTTP" in entrypoint_text


def test_entrypoint_forces_wildcard_bind_on_paas(entrypoint_text):
    assert 'export API_SERVER_HOST="0.0.0.0"' in entrypoint_text
    assert "API_SERVER_ENABLED" in entrypoint_text


def test_entrypoint_persists_generated_api_key(entrypoint_text):
    assert ".api_server_key" in entrypoint_text
    assert "secrets.token_hex(32)" in entrypoint_text


def test_entrypoint_rewrites_empty_command_to_gateway(entrypoint_text):
    assert 'set -- gateway' in entrypoint_text
    assert "launching hermes gateway" in entrypoint_text


def test_entrypoint_skips_verbose_skill_sync_on_paas(entrypoint_text):
    assert "deferring bundled skill sync to gateway startup" in entrypoint_text
