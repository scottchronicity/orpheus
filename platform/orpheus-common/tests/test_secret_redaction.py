"""Secrets must not survive a trip through logs or the debug config view."""

from orpheus_common.config import OrpheusConfig
from orpheus_common.utils import redact_url_credentials


class TestRedactUrlCredentials:
    def test_strips_userinfo_keeps_host(self):
        assert (
            redact_url_credentials("rtsp://alice:hunter2@cam-1:554/stream")
            == "rtsp://***@cam-1:554/stream"
        )

    def test_password_containing_at_sign(self):
        redacted = redact_url_credentials("nats://user:p@ss@broker:4222")
        assert "p@ss" not in redacted
        assert redacted.endswith("@broker:4222")

    def test_url_without_credentials_is_unchanged(self):
        url = "nats://127.0.0.1:4222"
        assert redact_url_credentials(url) == url

    def test_empty_and_non_url_input(self):
        assert redact_url_credentials("") == ""
        assert redact_url_credentials("not-a-url") == "not-a-url"


class TestMaskValue:
    def test_reveals_no_suffix(self):
        """Four trailing characters are enough to confirm a guessed secret."""
        masked = OrpheusConfig._mask_value("supersecretpassword")
        assert masked == "***"
        assert "word" not in masked

    def test_short_values_are_masked_too(self):
        assert OrpheusConfig._mask_value("abc") == "***"


class TestDebugSafeValues:
    def _config(self, monkeypatch, **env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        OrpheusConfig._instance = None
        OrpheusConfig._DOTENV_LOADED = False
        return OrpheusConfig(data={})

    def test_broker_url_credentials_are_stripped(self, monkeypatch):
        cfg = self._config(
            monkeypatch,
            ORPHEUS_EVENT_BUS__NATS_URL="nats://admin:supersecret@10.0.0.5:4222",
        )
        dumped = str(cfg.get_debug_safe_values())
        assert "supersecret" not in dumped
        assert "10.0.0.5" in dumped, "the host is the useful part; keep it"

    def test_query_string_is_dropped_from_url_values(self, monkeypatch):
        cfg = self._config(
            monkeypatch,
            ORPHEUS_EVENT_BUS__NATS_URL="nats://broker:4222?token=leakme",
        )
        dumped = str(cfg.get_debug_safe_values())
        assert "leakme" not in dumped
