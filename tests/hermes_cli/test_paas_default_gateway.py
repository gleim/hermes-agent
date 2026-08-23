"""Bare `hermes` redirects to gateway on a PaaS HTTP edge."""

from hermes_cli.main import _should_default_to_gateway


def _clear_paas_env(monkeypatch):
    for key in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_SERVICE_NAME",
        "RAILWAY_PROJECT_ID",
        "HERMES_PAAS_HTTP",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_is_chat_off_paas(monkeypatch):
    _clear_paas_env(monkeypatch)
    assert _should_default_to_gateway() is False


def test_default_is_gateway_on_railway(monkeypatch):
    _clear_paas_env(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    assert _should_default_to_gateway() is True


def test_opt_out_keeps_chat_default(monkeypatch):
    _clear_paas_env(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("HERMES_PAAS_HTTP", "0")
    assert _should_default_to_gateway() is False
