from click.testing import CliRunner

from armoire.cli import main


def test_serve_rejects_a_missing_folder(tmp_path):
    result = CliRunner().invoke(main, ["serve", str(tmp_path / "nope")])
    assert result.exit_code != 0


def test_serve_rejects_a_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    result = CliRunner().invoke(main, ["serve", str(f)])
    assert result.exit_code != 0


def test_serve_binds_loopback_only(tmp_path, monkeypatch):
    captured = {}

    def fake_run(app, host, port, log_level):
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("armoire.cli.uvicorn.run", fake_run)
    result = CliRunner().invoke(main, ["serve", str(tmp_path)])
    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8420


def test_port_flag_is_honoured(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "armoire.cli.uvicorn.run",
        lambda app, host, port, log_level: captured.update(port=port),
    )
    CliRunner().invoke(main, ["serve", str(tmp_path), "--port", "9000"])
    assert captured["port"] == 9000
