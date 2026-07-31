"""Observed Call Overlay v1 (S2): run-bound observation, kept apart from S0/S1.

The fixture package below is deliberately shaped around the three acceptance
assertions of RPU-V1-T026:

``run binding``
    the overlay is produced by tracing one named command in one git checkout,
    and every relation carries that observation identity.

``separation``
    ``consumer.dynamic`` reaches its target through ``getattr``. The static
    producer cannot resolve it, so it stays S0 there — while the overlay
    records that the call was observed. The overlay never rewrites the static
    graph and never claims an S1 resolution.

``non-claims``
    ``consumer.never_exercised`` calls ``targets.leaf`` on a path the traced
    command does not take. The static graph knows the edge, the overlay does
    not, and that silence is not permitted to mean dead code.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.architecture.call_graph import generate_call_graph_document
from merger.repoground.architecture.observed_call_overlay import (
    build_observed_call_overlay_document,
    build_symbol_anchors,
    generate_observed_call_overlay_document,
)
from merger.repoground.architecture.observed_call_overlay_contract import (
    OVERLAY_KIND,
    REQUIRED_NONCLAIMS,
)
from merger.repoground.architecture.observed_call_trace import (
    ObservedEdgeKey,
    TraceResult,
    environment_identity,
    source_revision,
    trace_command,
)
from merger.repoground.core.observed_call_navigation import (
    _matches_name,
    get_observed_callees,
    get_observed_callers,
)
from merger.repoground.core.observed_call_overlay_validation import (
    counts_error,
    observation_error,
    records_error,
    static_separation_error,
    validate_observed_call_overlay,
)
from merger.repoground.cli.main import main as cli_main

CANONICAL_SHA = "a" * 64
RUN_ID = "RUN-RPU-V1-T026"
OBSERVED_AT = "2026-07-30T12:00:00Z"

FIXTURE_FILES = {
    "callobs/__init__.py": "",
    "callobs/targets.py": '''def memo(function):
    """Decorator, so the code object anchors at the decorator line."""
    return function


def leaf(value):
    return value * 2


@memo
def decorated_leaf(value):
    return leaf(value) + 1
''',
    "callobs/consumer.py": '''from . import targets
from .targets import leaf


def run(value):
    return leaf(value)


def decorated(value):
    return targets.decorated_leaf(value)


def dynamic(name, value):
    return getattr(targets, name)(value)


def never_exercised(value):
    return leaf(value) + 1000
''',
    "callobs/threaded.py": '''import threading

from .targets import leaf


def in_worker(value):
    return leaf(value)


def spawn(value):
    result = []

    def collect():
        result.append(in_worker(value))

    worker = threading.Thread(target=collect)
    worker.start()
    worker.join()
    return result


if __name__ == "__main__":
    spawn(7)
''',
    "callobs/main.py": '''from .consumer import decorated, dynamic, run


def entry():
    return run(2) + decorated(3) + dynamic("leaf", 4)


if __name__ == "__main__":
    entry()
''',
}


def _write_fixture_repo(root: Path) -> None:
    for relative, content in FIXTURE_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(root: Path) -> None:
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "t026@example.invalid")
    _git(root, "config", "user.name", "RPU-V1-T026")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "fixture")


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / "observed_repo"
    root.mkdir()
    _write_fixture_repo(root)
    _init_git_repo(root)
    return root.resolve()


@pytest.fixture(autouse=True)
def _isolated_fixture_imports():
    """Keep the traced fixture package out of the interpreter's module cache.

    Tracing runs the target in-process, so a module left in ``sys.modules``
    would make a later trace observe nothing but a cache hit.
    """

    yield
    for name in list(sys.modules):
        if name == "callobs" or name.startswith("callobs."):
            del sys.modules[name]


def _overlay(repo_root: Path, command=("-m", "callobs.main")) -> dict:
    return generate_observed_call_overlay_document(
        repo_root,
        RUN_ID,
        CANONICAL_SHA,
        list(command),
        observed_at=OBSERVED_AT,
    )


def _schema() -> dict:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "contracts"
        / "python-observed-call-overlay.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _relation(overlay: dict, caller: str, callee: str) -> dict | None:
    for row in overlay["relations"]:
        if (
            row["caller_qualified_name"] == caller
            and row["callee_qualified_name"] == callee
        ):
            return row
    return None


def test_trace_records_repo_local_edges_only(fixture_repo: Path) -> None:
    trace = trace_command(fixture_repo, ["-m", "callobs.main"])

    assert trace.exit_status in ("completed", "exited")
    assert trace.edges
    assert all(key.callee_path.startswith("callobs/") for key in trace.edges)
    # ``value * 2`` and the decorator machinery are builtins or stdlib; nothing
    # outside the repository may appear as an observed callee.
    assert not any("site-packages" in key.callee_path for key in trace.edges)


def test_overlay_matches_the_v1_contract(fixture_repo: Path) -> None:
    overlay = _overlay(fixture_repo)

    jsonschema.validate(overlay, _schema())
    assert overlay["kind"] == OVERLAY_KIND
    assert validate_observed_call_overlay(overlay) is None


def test_every_relation_is_bound_to_one_observation(fixture_repo: Path) -> None:
    """Acceptance rpu-v1-t026-run-binding."""

    overlay = _overlay(fixture_repo)
    observation = overlay["observation"]

    assert observation["command"] == ["-m", "callobs.main"]
    assert observation["command_string"] == "-m callobs.main"
    assert observation["environment"]["python_version"] == (
        environment_identity()["python_version"]
    )
    revision = observation["source_revision"]
    assert revision["status"] in ("clean", "dirty")
    assert len(revision["commit"]) == 40
    assert revision["commit"] == source_revision(fixture_repo)["commit"]
    assert overlay["relations"]
    assert {row["observation_run_id"] for row in overlay["relations"]} == {
        observation["observation_run_id"]
    }


def test_relation_bound_to_a_foreign_observation_is_refused(fixture_repo: Path) -> None:
    overlay = _overlay(fixture_repo)
    overlay["relations"][0]["observation_run_id"] = "OBS-somewhere-else"

    failure = records_error(overlay)

    assert failure is not None
    assert failure["error_code"] == "observed_call_overlay_relation_run_binding_mismatch"


@pytest.mark.parametrize(
    "mutation, expected_code",
    [
        ({"command": []}, "observed_call_overlay_command_invalid"),
        ({"command_string": "something else"}, "observed_call_overlay_command_string_mismatch"),
        ({"observation_run_id": ""}, "observed_call_overlay_run_identity_invalid"),
        ({"environment": {}}, "observed_call_overlay_environment_invalid"),
        (
            {"source_revision": {"vcs": "git", "commit": None, "dirty": None, "status": "unavailable"}},
            "observed_call_overlay_source_revision_invalid",
        ),
    ],
)
def test_incomplete_observation_identity_is_refused(
    fixture_repo: Path, mutation: dict, expected_code: str
) -> None:
    """Acceptance rpu-v1-t026-run-binding: no identity, no S2 record."""

    overlay = _overlay(fixture_repo)
    overlay["observation"].update(mutation)

    failure = observation_error(overlay)

    assert failure is not None
    assert failure["error_code"] == expected_code


def test_producer_refuses_a_checkout_without_a_revision(tmp_path: Path) -> None:
    root = tmp_path / "no_vcs"
    root.mkdir()
    _write_fixture_repo(root)

    with pytest.raises(ValueError, match="resolvable source revision"):
        _overlay(root.resolve())


def test_observed_edges_stay_separate_from_static_evidence(fixture_repo: Path) -> None:
    """Acceptance rpu-v1-t026-separation."""

    overlay = _overlay(fixture_repo)
    static_graph = generate_call_graph_document(fixture_repo, RUN_ID, CANONICAL_SHA)

    assert "calls" not in overlay
    assert "resolution_statuses" not in overlay
    assert {row["evidence_level"] for row in overlay["relations"]} == {"S2"}
    assert {row["evidence_level"] for row in static_graph["calls"]} <= {"S0", "S1"}
    assert static_separation_error(overlay, static_graph) is None

    # The dynamically dispatched call is observed, and stays S0 statically.
    observed_dynamic = _relation(overlay, "dynamic", "leaf")
    assert observed_dynamic is not None
    assert observed_dynamic["evidence_level"] == "S2"
    dynamic_static_rows = [
        row
        for row in static_graph["calls"]
        if row["caller_qualified_name"] == "dynamic"
        and row["path"] == "callobs/consumer.py"
    ]
    assert dynamic_static_rows
    assert all(row["evidence_level"] == "S0" for row in dynamic_static_rows)
    assert all(not row["resolved_target_ids"] for row in dynamic_static_rows)


def test_static_graph_carrying_observed_evidence_is_refused(fixture_repo: Path) -> None:
    overlay = _overlay(fixture_repo)
    static_graph = generate_call_graph_document(fixture_repo, RUN_ID, CANONICAL_SHA)
    static_graph["calls"][0]["evidence_level"] = "S2"

    failure = static_separation_error(overlay, static_graph)

    assert failure is not None
    assert failure["error_code"] == "python_call_graph_observed_evidence_present"


def test_overlay_carrying_static_evidence_is_refused(fixture_repo: Path) -> None:
    overlay = _overlay(fixture_repo)
    overlay["relations"][0]["evidence_level"] = "S1"

    assert static_separation_error(overlay) is not None
    assert records_error(overlay) is not None


def test_absence_from_the_trace_is_not_dead_code(fixture_repo: Path) -> None:
    """Acceptance rpu-v1-t026-nonclaims."""

    overlay = _overlay(fixture_repo)
    static_graph = generate_call_graph_document(fixture_repo, RUN_ID, CANONICAL_SHA)

    # The static graph resolves never_exercised -> leaf; the trace never took
    # that path, so the overlay is silent about it.
    static_never = [
        row
        for row in static_graph["calls"]
        if row["caller_qualified_name"] == "never_exercised"
        and row["resolution_status"] == "resolved"
    ]
    assert static_never
    assert _relation(overlay, "never_exercised", "leaf") is None

    # That silence carries an explicit, machine-readable disclaimer.
    assert "dead_code" in overlay["does_not_establish"]
    assert "unreachable_code" in overlay["does_not_establish"]
    assert set(REQUIRED_NONCLAIMS).issubset(overlay["does_not_establish"])
    assert "not mean" in overlay["absence_semantics"]


def test_decorated_definitions_bind_to_their_symbol(fixture_repo: Path) -> None:
    """CPython anchors a decorated code object at its first decorator line."""

    anchors = build_symbol_anchors(fixture_repo)[0]
    decorated_anchor = [
        key for key in anchors["callobs/targets.py"] if key[0] == "decorated_leaf"
    ]
    assert len(decorated_anchor) == 1
    anchor_line = decorated_anchor[0][1]
    definition_line = anchors["callobs/targets.py"][decorated_anchor[0]][0]["start_line"]
    assert anchor_line < definition_line

    overlay = _overlay(fixture_repo)
    relation = _relation(overlay, "decorated", "decorated_leaf")
    assert relation is not None
    assert relation["callee_binding_status"] == "bound"
    assert relation["callee_symbol_id"].endswith(":function:decorated_leaf")


def test_module_frames_are_reported_as_module_scope(fixture_repo: Path) -> None:
    overlay = _overlay(fixture_repo)

    module_relations = [
        row for row in overlay["relations"] if row["caller_binding_status"] == "module_scope"
    ]
    assert module_relations
    assert all(row["caller_symbol_id"] is None for row in module_relations)
    assert all(row["caller_kind"] == "module" for row in module_relations)
    assert all(row["caller_binding_reason"] == "module_frame" for row in module_relations)


def test_callers_outside_the_repository_report_no_call_site(fixture_repo: Path) -> None:
    """The import machinery calls into the repository from files we cannot cite."""

    overlay = _overlay(fixture_repo)

    foreign = [row for row in overlay["relations"] if row["caller_path"] is None]
    assert foreign
    assert all(row["caller_binding_status"] == "unbound" for row in foreign)
    assert all(
        row["caller_binding_reason"] == "path_outside_repository" for row in foreign
    )
    assert all(row["call_site_line"] is None for row in foreign)
    assert all(row["call_site_range_ref"] is None for row in foreign)


def test_counts_track_the_relations(fixture_repo: Path) -> None:
    overlay = _overlay(fixture_repo)

    assert counts_error(overlay) is None
    overlay["observed_call_total"] += 1
    failure = counts_error(overlay)
    assert failure is not None
    assert failure["error_code"] == "observed_call_overlay_observed_call_total_mismatch"


def _write_artifacts(
    tmp_path: Path, fixture_repo: Path, command=("-m", "callobs.main")
) -> tuple[Path, Path]:
    overlay_path = tmp_path / "overlay.json"
    graph_path = tmp_path / "call-graph.json"
    overlay_path.write_text(
        json.dumps(_overlay(fixture_repo, command=command)), encoding="utf-8"
    )
    graph_path.write_text(
        json.dumps(generate_call_graph_document(fixture_repo, RUN_ID, CANONICAL_SHA)),
        encoding="utf-8",
    )
    return overlay_path, graph_path


def test_navigation_reports_observed_callers_with_static_correspondence(
    tmp_path: Path, fixture_repo: Path
) -> None:
    overlay_path, graph_path = _write_artifacts(tmp_path, fixture_repo)

    result = get_observed_callers(overlay_path, "leaf", call_graph=graph_path)

    assert result["status"] == "available"
    assert result["evidence_level"] == "S2"
    assert result["static_correspondence_supplied"] is True
    correspondences = {
        row["caller_qualified_name"]: row["static_correspondence"]
        for row in result["observed_callers"]
    }
    assert correspondences["run"] == "matches_s1"
    # Observed, but the static graph never resolved this edge: the overlay adds
    # evidence next to S0 instead of upgrading it.
    assert correspondences["dynamic"] == "absent_from_static_graph"
    assert "dead_code" in result["does_not_establish"]
    assert result["mutation_boundary"]["writes"] == []


def test_navigation_reports_observed_callees(tmp_path: Path, fixture_repo: Path) -> None:
    overlay_path, graph_path = _write_artifacts(tmp_path, fixture_repo)

    result = get_observed_callees(overlay_path, "entry", call_graph=graph_path)

    assert result["status"] == "available"
    callees = {row["callee_qualified_name"] for row in result["observed_callees"]}
    assert {"run", "decorated", "dynamic"} <= callees
    assert "never_exercised" not in callees


def test_navigation_without_a_static_graph_states_so(
    tmp_path: Path, fixture_repo: Path
) -> None:
    overlay_path, _ = _write_artifacts(tmp_path, fixture_repo)

    result = get_observed_callers(overlay_path, "leaf")

    assert result["static_correspondence_supplied"] is False
    assert {row["static_correspondence"] for row in result["observed_callers"]} == {
        "static_graph_not_supplied"
    }


@pytest.mark.parametrize(
    "name, k, expected_code",
    [
        ("", 25, "name_invalid"),
        ("leaf", 0, "k_out_of_bounds"),
        ("leaf", 10_000, "k_out_of_bounds"),
    ],
)
def test_navigation_refuses_invalid_queries(
    tmp_path: Path, fixture_repo: Path, name: str, k: int, expected_code: str
) -> None:
    overlay_path, _ = _write_artifacts(tmp_path, fixture_repo)

    result = get_observed_callers(overlay_path, name, k=k)

    assert result["status"] == "invalid"
    assert result["error_code"] == expected_code
    assert result["observed_callers"] == []


def test_navigation_refuses_an_invalid_overlay(tmp_path: Path) -> None:
    overlay_path = tmp_path / "overlay.json"
    overlay_path.write_text(json.dumps({"kind": "something.else"}), encoding="utf-8")

    result = get_observed_callers(overlay_path, "leaf")

    assert result["status"] == "invalid"
    assert result["error_code"] == "observed_call_overlay_invalid_kind"


def _produce_argv(repo_root: Path, out_path: Path, *command: str) -> list[str]:
    return [
        "observed-calls",
        "produce",
        "--repo-root",
        str(repo_root),
        "--run-id",
        RUN_ID,
        "--canonical-dump-index-sha256",
        CANONICAL_SHA,
        "--output",
        str(out_path),
        *command,
    ]


def test_producer_cli_writes_a_valid_overlay(tmp_path: Path, fixture_repo: Path) -> None:
    out_path = tmp_path / "cli" / "overlay.json"

    exit_code = cli_main(
        _produce_argv(fixture_repo, out_path, "--", "-m", "callobs.main")
    )

    assert exit_code == 0
    document = json.loads(out_path.read_text(encoding="utf-8"))
    assert validate_observed_call_overlay(document) is None
    assert document["observation"]["command"] == ["-m", "callobs.main"]


def test_producer_cli_requires_a_command(tmp_path: Path, fixture_repo: Path) -> None:
    out_path = tmp_path / "overlay.json"

    exit_code = cli_main(_produce_argv(fixture_repo, out_path))

    assert exit_code == 2
    assert not out_path.exists()


def test_producer_cli_refuses_a_checkout_without_a_revision(tmp_path: Path) -> None:
    root = tmp_path / "no_vcs"
    root.mkdir()
    _write_fixture_repo(root)
    out_path = tmp_path / "overlay.json"

    exit_code = cli_main(
        _produce_argv(root.resolve(), out_path, "--", "-m", "callobs.main")
    )

    assert exit_code == 2
    assert not out_path.exists()


def test_read_cli_emits_the_observed_projection(
    tmp_path: Path, fixture_repo: Path, capsys
) -> None:
    overlay_path, graph_path = _write_artifacts(tmp_path, fixture_repo)

    exit_code = cli_main(
        [
            "observed-calls",
            "callers",
            str(overlay_path),
            "leaf",
            "--call-graph",
            str(graph_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["evidence_level"] == "S2"
    assert payload["observed_callers"]


def test_failed_command_still_reports_what_it_observed(fixture_repo: Path) -> None:
    (fixture_repo / "callobs" / "boom.py").write_text(
        "from .consumer import run\n\n\ndef go():\n    run(1)\n    raise RuntimeError('boom')\n\n\ngo()\n",
        encoding="utf-8",
    )

    overlay = _overlay(fixture_repo, command=("-m", "callobs.boom"))

    assert overlay["execution_outcome"]["exit_status"] == "failed"
    assert overlay["skipped_errors"]
    assert "RuntimeError" in overlay["skipped_errors"][0]
    assert _relation(overlay, "go", "run") is not None


def test_inner_separator_tokens_survive_the_cli(
    tmp_path: Path, fixture_repo: Path, monkeypatch
) -> None:
    """Only argparse's own '--' is stripped; the traced command keeps its own."""

    seen: dict[str, list[str]] = {}

    def _capture(repo_root, command):
        seen["command"] = list(command)
        return trace_command(repo_root, ["-m", "callobs.main"])

    monkeypatch.setattr(
        "merger.repoground.architecture.observed_call_trace.trace_command",
        _capture,
    )
    exit_code = cli_main(
        _produce_argv(
            fixture_repo,
            tmp_path / "overlay.json",
            "--",
            "-m",
            "callobs.main",
            "--",
            "-k",
            "selected",
        )
    )

    assert exit_code == 0
    assert seen["command"] == ["-m", "callobs.main", "--", "-k", "selected"]


def test_keyboard_interrupt_aborts_instead_of_being_recorded(fixture_repo: Path) -> None:
    """An operator aborting a long trace must abort it, not get a 'failed' run."""

    (fixture_repo / "callobs" / "aborted.py").write_text(
        "from .consumer import run\n\nrun(1)\nraise KeyboardInterrupt\n",
        encoding="utf-8",
    )

    with pytest.raises(KeyboardInterrupt):
        trace_command(fixture_repo, ["-m", "callobs.aborted"])

    # The profile hooks are still handed back on the way out.
    assert sys.getprofile() is None


def test_trace_restores_existing_thread_profile(fixture_repo: Path) -> None:
    """Tracing must not erase a process-wide profile hook owned by its caller."""

    previous = threading.getprofile()

    def sentinel(frame, event, arg):
        del frame, event, arg

    threading.setprofile(sentinel)
    try:
        trace_command(fixture_repo, ["-m", "callobs.main"])
        assert threading.getprofile() is sentinel
    finally:
        threading.setprofile(previous)


def test_calls_in_worker_threads_are_observed(fixture_repo: Path) -> None:
    """threading.setprofile reaches threads the traced command starts."""

    overlay = _overlay(fixture_repo, command=("-m", "callobs.threaded"))

    assert _relation(overlay, "spawn.collect", "in_worker") is not None
    assert _relation(overlay, "in_worker", "leaf") is not None
    assert "concurrent_thread_completeness" in overlay["does_not_establish"]
    assert "native_frame_completeness" in overlay["does_not_establish"]


def test_truncation_keeps_the_most_observed_relations(
    fixture_repo: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "merger.repoground.architecture.observed_call_overlay.MAX_RELATIONS", 3
    )

    overlay = _overlay(fixture_repo)

    assert overlay["relations_truncated"] is True
    assert overlay["relation_count"] == 3
    assert overlay["observed_relation_total_count"] > 3
    # Emission stays in structural order even though selection ranked by count.
    emitted = [
        (row["callee_path"], row["callee_runtime_first_line"], row["callee_runtime_name"])
        for row in overlay["relations"]
    ]
    assert emitted == sorted(emitted)
    assert counts_error(overlay) is None


def test_anchors_are_built_only_for_observed_files(fixture_repo: Path) -> None:
    """A syntax error in an untouched file cannot poison the overlay."""

    (fixture_repo / "callobs" / "broken.py").write_text("def (\n", encoding="utf-8")

    overlay = _overlay(fixture_repo)

    assert overlay["skipped_files_count"] == 0
    assert overlay["skipped_errors"] == []
    assert build_symbol_anchors(fixture_repo)[1] == 1


def test_skipped_error_total_is_not_capped_by_the_retained_list(
    fixture_repo: Path,
) -> None:
    """The retained diagnostics are capped; the count of failures is not."""

    broken = []
    for index in range(25):
        name = f"callobs/broken_{index}.py"
        (fixture_repo / name).write_text("def (\n", encoding="utf-8")
        broken.append(name)
    trace = TraceResult(
        edges={
            ObservedEdgeKey(
                caller_path=None,
                caller_name="<module>",
                caller_first_line=0,
                call_line=0,
                callee_path=name,
                callee_name="missing",
                callee_first_line=1,
            ): 1
            for name in broken
        },
        command=["-m", "callobs.main"],
        exit_status="completed",
        exit_code=0,
        frame_event_count=25,
        skipped_errors=(),
        skipped_errors_total_count=0,
    )
    document = build_observed_call_overlay_document(
        repo_root=fixture_repo,
        run_id=RUN_ID,
        canonical_dump_index_sha256=CANONICAL_SHA,
        observation=_overlay(fixture_repo)["observation"],
        trace=trace,
    )

    assert len(document["skipped_errors"]) == 20
    assert document["skipped_files_count"] == 25
    assert document["skipped_errors_total_count"] == 25
    assert document["skipped_errors_truncated"] is True
    assert validate_observed_call_overlay(document) is None


def test_a_call_site_without_a_caller_path_is_refused(fixture_repo: Path) -> None:
    overlay = _overlay(fixture_repo)
    foreign = next(row for row in overlay["relations"] if row["caller_path"] is None)
    foreign["call_site_line"] = 5

    assert records_error(overlay) is not None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(overlay, _schema())


def test_schema_and_validator_agree_on_unbound_endpoints(fixture_repo: Path) -> None:
    """An unbound endpoint may not carry a symbol kind."""

    overlay = _overlay(fixture_repo)
    foreign = next(row for row in overlay["relations"] if row["caller_path"] is None)
    foreign["caller_kind"] = "function"

    assert records_error(overlay) is not None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(overlay, _schema())


@pytest.mark.parametrize(
    "value, query, expected",
    [
        ("Runner.go", "runner.go", True),
        ("Runner.go", "go", True),
        ("Outer.Runner.go", "runner.go", True),
        ("Outer.Runner.go", "unner.go", False),
        ("OtherRunner.go", "runner.go", False),
        (None, "go", False),
    ],
)
def test_name_matching_accepts_exact_simple_and_dotted_suffix(
    value, query: str, expected: bool
) -> None:
    """A dotted query selects a whole segment boundary, never a partial word."""

    assert _matches_name(value, query) is expected


def test_navigation_matches_a_nested_qualified_name(
    tmp_path: Path, fixture_repo: Path
) -> None:
    overlay_path, _ = _write_artifacts(
        tmp_path, fixture_repo, command=("-m", "callobs.threaded")
    )

    nested = get_observed_callees(overlay_path, "spawn.collect")

    assert nested["hit_count"] >= 1
    assert all(
        row["caller_qualified_name"] == "spawn.collect"
        for row in nested["observed_callees"]
    )
