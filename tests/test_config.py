import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from telegram_business_bot.cli import main
from telegram_business_bot.config import ConfigurationError, Settings

# Synthetic, deliberately non-operational credential used only for format validation.
SYNTHETIC_TOKEN = "123456789:" + "a" * 35


def live_env():
    return {
        "BOT_MODE": "live",
        "BOT_TOKEN": SYNTHETIC_TOKEN,
        "DISPATCHER_CHAT_ID": "-1001234567890",
        "DISPATCHER_USER_IDS": "123,456,123",
    }


def test_default_config_has_no_token_or_file_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env({})
    assert settings.mode == "simulator"
    assert settings.bot_token is None
    assert settings.database_path == Path("data/requests.sqlite3")
    assert list(tmp_path.iterdir()) == []


def test_live_config_deduplicates_allowlist_and_hides_credential():
    settings = Settings.from_env(live_env())
    assert settings.dispatcher_user_ids == frozenset({123, 456})
    assert settings.dispatcher_chat_id == -1001234567890
    assert SYNTHETIC_TOKEN not in repr(settings)


@pytest.mark.parametrize(
    "key,value",
    [
        ("BOT_MODE", "unknown"),
        ("SERVICE_TIMEZONE", "Unknown/Zone"),
        ("DATABASE_PATH", ""),
        ("DATABASE_PATH", ":memory:"),
        ("DISPATCHER_CHAT_ID", "0"),
        ("DISPATCHER_CHAT_ID", "bad"),
        ("DISPATCHER_USER_IDS", "1,,2"),
        ("DISPATCHER_USER_IDS", "-1"),
        ("DISPATCHER_USER_IDS", "0"),
        ("BOT_TOKEN", "not-a-token"),
        ("DISPATCHER_CHAT_ID", ""),
        ("DISPATCHER_USER_IDS", ""),
    ],
)
def test_invalid_live_configuration(key, value):
    env = live_env()
    env[key] = value
    with pytest.raises(ConfigurationError):
        Settings.from_env(env)


def test_explicit_empty_environment_does_not_fall_back_to_process(monkeypatch):
    monkeypatch.setenv("BOT_MODE", "live")
    assert Settings.from_env({}).mode == "simulator"


def test_offline_mode_ignores_malformed_token():
    assert Settings.from_env({"BOT_TOKEN": "expired-private-value"}).bot_token is None


def test_cli_check_needs_no_network_or_token(monkeypatch, capsys):
    for key in live_env():
        monkeypatch.delenv(key, raising=False)

    def deny_network(*args, **kwargs):
        raise AssertionError("configuration check must not connect")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    assert main(["--check-config"]) == 0
    assert "simulator" in capsys.readouterr().out


def test_cli_configuration_error_does_not_echo_secret(monkeypatch, capsys):
    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("BOT_TOKEN", "private-invalid-token")
    assert main(["--check-config"]) == 2
    assert "private-invalid-token" not in capsys.readouterr().err


def test_no_command_does_not_claim_to_run_a_simulator(capsys):
    assert main([]) == 2
    assert "--check-config" in capsys.readouterr().out


def test_cli_handles_legacy_windows_output_encoding():
    env = {key: value for key, value in os.environ.items() if key not in live_env()}
    env["PYTHONIOENCODING"] = "cp950"
    result = subprocess.run(
        [sys.executable, "-m", "telegram_business_bot", "--check-config"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Настройки корректны" in result.stdout.decode("utf-8")
