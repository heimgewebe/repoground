from merger.lenskit.cli import rlens


def test_server_disables_access_log_to_avoid_query_token_leaks(monkeypatch, tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    captured = {}

    monkeypatch.setattr(
        "sys.argv",
        ["rlens", "--hub", str(hub), "--token", "synthetic-token"],
    )
    monkeypatch.setattr(rlens, "init_service", lambda **kwargs: captured.setdefault("init", kwargs))
    monkeypatch.setattr(rlens.uvicorn, "run", lambda app, **kwargs: captured.setdefault("run", kwargs))

    rlens.main()

    assert captured["run"]["access_log"] is False
    assert captured["run"]["host"] == "127.0.0.1"
    assert captured["init"]["token"] == "synthetic-token"
