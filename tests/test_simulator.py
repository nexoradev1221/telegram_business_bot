from telegram_business_bot.cli import main


def test_demo_runs_all_shared_services_without_token_or_network(monkeypatch, capsys):
    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("BOT_TOKEN", "not-a-real-token")
    monkeypatch.setenv("DISPATCHER_CHAT_ID", "not-a-chat")

    assert main(["--demo"]) == 0
    output = capsys.readouterr().out
    assert "Синтетическая заявка создана: TB-" in output
    assert "Уведомление диспетчеру" in output
    assert "Не сливает воду после стирки" in output
    assert "Проверка клиента: Закрыта" in output
