import argparse

from merger.repoground.cli import cmd_federation, cmd_ground, cmd_query, main as cli_main
from merger.repoground.retrieval import federation_query


def test_direct_query_cli_forwards_history_scope(monkeypatch):
    captured = {}

    def fake_run_query(args):
        captured["archive_scope"] = args.archive_scope
        return 0

    monkeypatch.setattr(cmd_query, "run_query", fake_run_query)

    rc = cli_main.main(
        [
            "query",
            "--index",
            "unused.index.sqlite",
            "--archive-scope",
            "history",
        ]
    )

    assert rc == 0
    assert captured == {"archive_scope": "history"}


def test_ground_query_cli_parses_history_scope():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    cmd_ground.register_ground_command(subparsers)

    args = parser.parse_args(
        [
            "ground",
            "query",
            "--bundle-manifest",
            "unused.bundle.manifest.json",
            "--archive-scope",
            "history",
        ]
    )

    assert args.archive_scope == "history"


def test_ground_query_forwards_history_scope(monkeypatch, capsys):
    captured = {}

    def fake_query_existing_index(*args, **kwargs):
        captured["filters"] = kwargs["filters"]
        return {"status": "available"}

    from merger.repoground.core import bundle_access

    monkeypatch.setattr(bundle_access, "query_existing_index", fake_query_existing_index)
    args = argparse.Namespace(
        bundle_manifest="unused.bundle.manifest.json",
        q="maintenance",
        k=10,
        repo=None,
        path=None,
        ext=None,
        layer=None,
        artifact_type=None,
        archive_scope="history",
        raw_index_result=True,
        no_project_sources=True,
    )

    assert cmd_ground.run_query_existing_index(args) == 0
    assert captured["filters"]["archive_scope"] == "history"
    capsys.readouterr()


def test_federation_query_cli_forwards_history_scope(monkeypatch, tmp_path, capsys):
    captured = {}
    index_path = tmp_path / "federation.json"
    index_path.write_text('{"bundles": []}', encoding="utf-8")

    def fake_execute_federated_query(*args, **kwargs):
        captured["filters"] = kwargs["filters"]
        return {"count": 0}

    monkeypatch.setattr(
        federation_query,
        "execute_federated_query",
        fake_execute_federated_query,
    )

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    cmd_federation.register_federation_commands(subparsers)
    args = parser.parse_args(
        [
            "federation",
            "query",
            "--index",
            str(index_path),
            "--query",
            "maintenance",
            "--archive-scope",
            "history",
        ]
    )

    assert cmd_federation.handle_federation_command(args) == 0
    assert captured["filters"]["archive_scope"] == "history"
    capsys.readouterr()
