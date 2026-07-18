from merger.repoground.cli import serve


def test_server_disables_access_log_to_avoid_query_token_leaks(monkeypatch, tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    captured = {}

    monkeypatch.setattr(
        "sys.argv",
        ["repoground", "--hub", str(hub), "--token", "synthetic-token"],
    )
    monkeypatch.setattr(serve, "init_service", lambda **kwargs: captured.setdefault("init", kwargs))
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kwargs: captured.setdefault("run", kwargs))

    serve.main()

    assert captured["run"]["access_log"] is False
    assert captured["run"]["host"] == "127.0.0.1"
    assert captured["init"]["token"] == "synthetic-token"
