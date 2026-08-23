"""PaaS / Railway HTTP runtime defaults for api_server."""

from gateway.config import Platform, is_paas_http_runtime, load_gateway_config


def _clear_paas_env(monkeypatch):
    for key in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_SERVICE_NAME",
        "RAILWAY_PROJECT_ID",
        "HERMES_PAAS_HTTP",
        "API_SERVER_ENABLED",
        "API_SERVER_KEY",
        "API_SERVER_HOST",
        "API_SERVER_PORT",
        "PORT",
    ):
        monkeypatch.delenv(key, raising=False)


class TestIsPaasHttpRuntime:
    def test_off_by_default(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        assert is_paas_http_runtime() is False

    def test_railway_environment(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        assert is_paas_http_runtime() is True

    def test_railway_service_name(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("RAILWAY_SERVICE_NAME", "hermes-mutantdefi")
        assert is_paas_http_runtime() is True

    def test_explicit_opt_in(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("HERMES_PAAS_HTTP", "1")
        assert is_paas_http_runtime() is True

    def test_explicit_opt_out_wins_on_railway(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        monkeypatch.setenv("HERMES_PAAS_HTTP", "0")
        assert is_paas_http_runtime() is False

    def test_env_mapping_argument(self):
        assert is_paas_http_runtime({"RAILWAY_PROJECT_ID": "abc"}) is True
        assert is_paas_http_runtime({"HERMES_PAAS_HTTP": "false"}) is False


class TestPaasApiServerDefaults:
    def test_railway_enables_wildcard_bind_and_port(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        monkeypatch.setenv("PORT", "8080")
        config = load_gateway_config()
        platform = config.platforms[Platform.API_SERVER]
        assert platform.enabled is True
        assert platform.extra.get("host") == "0.0.0.0"
        assert platform.extra.get("port") == 8080

    def test_loopback_host_is_rewritten_on_railway(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("RAILWAY_SERVICE_NAME", "hermes-mutantdefi")
        monkeypatch.setenv("API_SERVER_HOST", "127.0.0.1")
        config = load_gateway_config()
        assert config.platforms[Platform.API_SERVER].extra.get("host") == "0.0.0.0"

    def test_explicit_non_loopback_host_is_kept(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        monkeypatch.setenv("API_SERVER_HOST", "10.0.0.8")
        config = load_gateway_config()
        assert config.platforms[Platform.API_SERVER].extra.get("host") == "10.0.0.8"

    def test_opt_out_does_not_enable_api_server(self, monkeypatch):
        _clear_paas_env(monkeypatch)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        monkeypatch.setenv("HERMES_PAAS_HTTP", "0")
        config = load_gateway_config()
        assert Platform.API_SERVER not in config.platforms
