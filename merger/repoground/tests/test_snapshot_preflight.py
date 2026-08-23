import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import merger.repoground.core.snapshot_preflight as snapshot_preflight
from merger.repoground.core.snapshot_preflight import run_consumption_preflight


def _artifact(root: Path, role: str, text: str = 'x\n') -> dict:
    path = root / f'{role}.txt'
    path.write_text(text, encoding='utf-8')
    return {'role': role, 'path': path.name, 'content_type': 'text/plain', 'bytes': path.stat().st_size, 'sha256': '0' * 64}


def _bundle(
    tmp_path: Path,
    roles,
    *,
    generator=True,
    snapshot=True,
    post=True,
    capabilities=None,
    snapshot_commit='b' * 40,
    snapshot_repo_root=None,
):
    artifacts = [_artifact(tmp_path, role) for role in roles]
    data = {
        'kind': 'repobrief.bundle_manifest',
        'run_id': 'run-1',
        'created_at': '2026-07-04T06:00:00Z',
        'artifacts': artifacts,
    }
    if generator:
        data['generator'] = {'runtime': {'git_commit': 'a' * 40}}
    if snapshot:
        data['snapshot_provenance'] = {'version': 'v1', 'repositories': [{'name': 'repo', 'repo_root': str(snapshot_repo_root or tmp_path), 'repo_remote': None, 'git_commit': snapshot_commit, 'git_dirty': False, 'git_branch': 'main', 'provenance_status': 'present', 'freshness_basis': 'git_commit'}], 'does_not_establish': ['freshness_against_remote']}
    if capabilities:
        data['capabilities'] = capabilities
    manifest = tmp_path / 'sample.bundle.manifest.json'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    if post is True:
        (tmp_path / 'sample.bundle_health.post.json').write_text(
            json.dumps({
                'kind': 'lenskit.post_emit_health',
                'version': '1.0',
                'bundle_manifest_path': str(manifest.resolve()),
                'bundle_run_id': 'run-1',
                'status': 'pass',
                'checks': [],
            }),
            encoding='utf-8',
        )
    elif isinstance(post, dict):
        post = {
            'kind': 'lenskit.post_emit_health',
            'version': '1.0',
            'bundle_manifest_path': str(manifest.resolve()),
            'bundle_run_id': data['run_id'],
            **post,
        }
        (tmp_path / 'sample.bundle_health.post.json').write_text(json.dumps(post), encoding='utf-8')
    return manifest


FULL_BASIC = ['agent_reading_pack', 'canonical_md', 'citation_map_jsonl', 'snapshot_plan_json']


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ['git', *args],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _live_repository_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    source = tmp_path / 'source'
    source.mkdir()
    _git(source, 'init')
    _git(source, 'config', 'user.name', 'RepoGround Test')
    _git(source, 'config', 'user.email', 'repoground-test@example.invalid')
    _git(source, 'checkout', '-b', 'fleet-default')
    (source / 'tracked.txt').write_text('one\n', encoding='utf-8')
    _git(source, 'add', 'tracked.txt')
    _git(source, 'commit', '-m', 'initial')
    snapshot_commit = _git(source, 'rev-parse', 'HEAD')

    remote = tmp_path / 'remote.git'
    _git(tmp_path, 'clone', '--bare', str(source), str(remote))
    repository = tmp_path / 'consumer'
    _git(tmp_path, 'clone', str(remote), str(repository))
    return source, repository, snapshot_commit


def _advance_remote(source: Path, repository: Path) -> str:
    tracked = source / 'tracked.txt'
    tracked.write_text(tracked.read_text(encoding='utf-8') + 'two\n', encoding='utf-8')
    _git(source, 'add', 'tracked.txt')
    _git(source, 'commit', '-m', 'advance remote')
    remote_commit = _git(source, 'rev-parse', 'HEAD')
    remote_url = _git(repository, 'remote', 'get-url', 'origin')
    _git(source, 'push', remote_url, 'HEAD:refs/heads/fleet-default')
    return remote_commit


def test_full_basic_bundle_passes(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, FULL_BASIC), 'basic_repo_question')
    assert result['status'] == 'pass'
    assert result['missing_required_artifacts'] == []


def test_live_head_exact_advertised_remote_head_match_passes(tmp_path):
    _, repository, snapshot_commit = _live_repository_fixture(tmp_path)
    bundle_dir = tmp_path / 'bundle'
    bundle_dir.mkdir()
    manifest = _bundle(
        bundle_dir,
        FULL_BASIC,
        snapshot_commit=snapshot_commit,
        snapshot_repo_root=repository,
    )

    result = run_consumption_preflight(
        manifest, 'basic_repo_question', live_repo=repository
    )

    assert result['status'] == 'pass'
    assert result['live_head'] == {
        'status': 'fresh',
        'reason': 'head_matches_snapshot_commit',
        'snapshot_commit': snapshot_commit,
        'remote_commit': snapshot_commit,
        'remote_ref': 'refs/heads/fleet-default',
        'head_drift': False,
        'repository': str(repository.resolve()),
    }
    assert next(check for check in result['checks'] if check['name'] == 'live_head')['status'] == 'pass'


def test_live_head_remote_advance_fails_stale_with_both_commits(tmp_path):
    source, repository, snapshot_commit = _live_repository_fixture(tmp_path)
    bundle_dir = tmp_path / 'bundle'
    bundle_dir.mkdir()
    manifest = _bundle(
        bundle_dir,
        FULL_BASIC,
        snapshot_commit=snapshot_commit,
        snapshot_repo_root=repository,
    )
    remote_commit = _advance_remote(source, repository)
    local_origin_before = _git(
        repository, 'rev-parse', 'refs/remotes/origin/fleet-default'
    )

    result = run_consumption_preflight(
        manifest, 'basic_repo_question', live_repo=repository
    )

    assert result['status'] == 'fail'
    assert result['live_head']['status'] == 'stale'
    assert result['live_head']['snapshot_commit'] == snapshot_commit
    assert result['live_head']['remote_commit'] == remote_commit
    assert result['live_head']['remote_ref'] == 'refs/heads/fleet-default'
    assert result['live_head']['head_drift'] is True
    finding = next(f for f in result['findings'] if f['code'] == 'live_head_stale')
    assert finding['context']['status'] == 'stale'
    assert finding['context']['reason'] == 'head_drift'
    assert finding['context']['snapshot_commit'] == snapshot_commit
    assert finding['context']['remote_commit'] == remote_commit
    assert 'Refresh or republish' in finding['context']['remediation']
    assert 'no refresh was attempted' in finding['context']['remediation']
    assert local_origin_before == snapshot_commit
    assert (
        _git(repository, 'rev-parse', 'refs/remotes/origin/fleet-default')
        == snapshot_commit
    )
    assert _git(repository, 'status', '--porcelain') == ''


def test_live_head_missing_repository_or_origin_fails_closed_unknown(tmp_path):
    missing_repository = tmp_path / 'missing-repository'
    missing_bundle = tmp_path / 'missing-bundle'
    missing_bundle.mkdir()
    missing_result = run_consumption_preflight(
        _bundle(
            missing_bundle,
            FULL_BASIC,
            snapshot_repo_root=missing_repository,
        ),
        'basic_repo_question',
        live_repo=missing_repository,
    )

    assert missing_result['status'] == 'fail'
    assert missing_result['live_head']['status'] == 'unknown'
    assert missing_result['live_head']['reason'] == 'live_repository_unavailable'
    assert missing_result['live_head']['head_drift'] is None

    repository_without_origin = tmp_path / 'repository-without-origin'
    repository_without_origin.mkdir()
    _git(repository_without_origin, 'init')
    no_origin_bundle = tmp_path / 'no-origin-bundle'
    no_origin_bundle.mkdir()
    no_origin_result = run_consumption_preflight(
        _bundle(
            no_origin_bundle,
            FULL_BASIC,
            snapshot_repo_root=repository_without_origin,
        ),
        'basic_repo_question',
        live_repo=repository_without_origin,
    )

    assert no_origin_result['status'] == 'fail'
    assert no_origin_result['live_head']['status'] == 'unknown'
    assert no_origin_result['live_head']['reason'] == 'origin_default_head_unproven'
    finding = next(
        f for f in no_origin_result['findings'] if f['code'] == 'live_head_unknown'
    )
    assert finding['severity'] == 'fail'
    assert finding['context']['status'] == 'unknown'
    assert 'no refresh was attempted' in finding['context']['remediation']


def test_offline_preflight_keeps_git_free_compatible_path(tmp_path, monkeypatch):
    def fail_if_git_runs(*args, **kwargs):
        raise AssertionError('offline preflight must not run a subprocess')

    monkeypatch.setattr(snapshot_preflight.subprocess, 'run', fail_if_git_runs)

    result = run_consumption_preflight(
        _bundle(tmp_path, FULL_BASIC), 'basic_repo_question'
    )

    assert result['status'] == 'pass'
    assert 'live_head' not in result
    assert all(check['name'] != 'live_head' for check in result['checks'])


def test_live_head_gate_stays_separate_from_age_warning(tmp_path):
    _, repository, snapshot_commit = _live_repository_fixture(tmp_path)
    bundle_dir = tmp_path / 'bundle'
    bundle_dir.mkdir()
    manifest = _bundle(
        bundle_dir,
        FULL_BASIC,
        snapshot_commit=snapshot_commit,
        snapshot_repo_root=repository,
    )

    result = run_consumption_preflight(
        manifest,
        'basic_repo_question',
        live_repo=repository,
        max_age_seconds=1,
        as_of=datetime(2026, 7, 4, 7, 0, tzinfo=timezone.utc),
    )

    assert result['status'] == 'warn'
    assert result['freshness']['status'] == 'stale'
    assert result['live_head']['status'] == 'fresh'
    assert not any(
        finding['code'] == 'live_head_stale' for finding in result['findings']
    )


def test_missing_required_fails(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, ['agent_reading_pack', 'citation_map_jsonl', 'snapshot_plan_json']), 'basic_repo_question')
    assert result['status'] == 'fail'
    assert 'canonical_md' in result['missing_required_artifacts']


def test_missing_recommended_warns(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, ['agent_reading_pack', 'canonical_md']), 'basic_repo_question')
    assert result['status'] == 'warn'
    assert 'citation_map_jsonl' in result['missing_recommended_artifacts']


def test_skipped_validation_is_visible(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC, post={'status': 'pass', 'checks': [{'name': 'range_refs', 'status': 'skipped'}]})
    result = run_consumption_preflight(manifest, 'basic_repo_question')
    assert result['status'] == 'warn'
    assert any(f['code'] == 'validation_checks_skipped' for f in result['findings'])


def test_missing_provenance_is_visible(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, FULL_BASIC, generator=False), 'basic_repo_question')
    assert result['status'] == 'warn'
    assert result['freshness']['status'] == 'unknown'
    assert any(f['code'] == 'generator_provenance_missing' and f['severity'] == 'warn' for f in result['findings'])


def test_missing_git_commit_marks_freshness_unknown(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['generator'] = {'runtime': {}}
    manifest.write_text(json.dumps(data), encoding='utf-8')
    result = run_consumption_preflight(manifest, 'basic_repo_question')
    assert result['status'] == 'warn'
    assert result['freshness']['status'] == 'unknown'
    assert any(f['code'] == 'generator_git_commit_missing' for f in result['findings'])


def test_missing_negative_semantics_fails(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, FULL_BASIC), 'basic_repo_question', declaration={'does_not_establish': []})
    assert result['status'] == 'fail'
    assert any(f['code'] == 'declaration_missing_negative_semantics' for f in result['findings'])


def test_unknown_task_profile_is_not_applicable(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, FULL_BASIC), 'no_such_profile')
    assert result['status'] == 'not_applicable'


def test_pr_delta_not_required_for_basic_profile(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, FULL_BASIC + ['pr_delta_cards_jsonl']), 'basic_repo_question')
    assert result['status'] == 'pass'
    assert 'pr_delta_cards_jsonl' not in result['missing_required_artifacts']


def test_security_profile_without_export_safety_fails(tmp_path):
    manifest = _bundle(tmp_path, ['agent_reading_pack', 'canonical_md', 'post_emit_health'], capabilities={'repobrief_profile': 'security-export-review'})
    result = run_consumption_preflight(manifest, 'security_export_review')
    assert result['status'] == 'fail'
    assert 'export_safety_report' in result['missing_required_artifacts']


def test_unresolved_citation_fails(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    (tmp_path / 'citation_map_jsonl.txt').write_text('{"citation_id":"known"}\n', encoding='utf-8')
    result = run_consumption_preflight(manifest, 'basic_repo_question', used_citations=['missing'])
    assert result['status'] == 'fail'
    assert any(f['code'] == 'used_citation_unresolved' for f in result['findings'])


def test_unresolved_range_fails(tmp_path):
    result = run_consumption_preflight(
        _bundle(tmp_path, FULL_BASIC),
        'basic_repo_question',
        used_ranges=[{'artifact': 'canonical_md', 'range_ref': {'artifact_line_start': 1, 'artifact_line_end': 3}}],
    )
    assert result['status'] == 'fail'
    assert any(f['code'] == 'used_range_unresolved' for f in result['findings'])


def test_preflight_cli_missing_manifest_returns_usage_error(tmp_path, capsys):
    from merger.repoground.cli.main import main

    rc = main([
        'ground',
        'preflight',
        '--bundle-manifest',
        str(tmp_path / 'missing.bundle.manifest.json'),
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert 'repoground ground preflight: bundle manifest does not exist' in captured.err
    assert 'Traceback' not in captured.err


def test_preflight_cli_invalid_manifest_json_returns_usage_error(tmp_path, capsys):
    from merger.repoground.cli.main import main

    manifest = tmp_path / 'bad.bundle.manifest.json'
    manifest.write_text('{bad json', encoding='utf-8')

    rc = main([
        'ground',
        'preflight',
        '--bundle-manifest',
        str(manifest),
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert 'repoground ground preflight: bundle manifest is not valid JSON' in captured.err
    assert 'Traceback' not in captured.err


def test_start_end_line_range_exceeding_artifact_length_fails(tmp_path):
    result = run_consumption_preflight(
        _bundle(tmp_path, FULL_BASIC),
        'basic_repo_question',
        used_ranges=[{'artifact': 'canonical_md', 'range_ref': {'start_line': 1, 'end_line': 3}}],
    )
    assert result['status'] == 'fail'
    assert any(f['code'] == 'used_range_unresolved' for f in result['findings'])


def test_start_end_line_range_within_artifact_length_passes(tmp_path):
    result = run_consumption_preflight(
        _bundle(tmp_path, FULL_BASIC, post=True),
        'basic_repo_question',
        used_ranges=[{'artifact': 'canonical_md', 'range_ref': {'start_line': 1, 'end_line': 1}}],
    )
    assert result['status'] == 'pass'
    assert result['used_ranges']['resolved'][0]['resolution'] == 'artifact_lines_verified'


def test_bundle_surface_sidecar_fail_fails_even_without_recorded_manifest_status(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    surface = tmp_path / 'surface.json'
    surface.write_text(json.dumps({'status': 'fail'}), encoding='utf-8')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['links'] = {'bundle_surface_validation_path': surface.name}
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(manifest, 'basic_repo_question')

    assert result['status'] == 'fail'
    assert any(f['artifact'] == 'bundle_surface_validation' and f['severity'] == 'fail' for f in result['findings'])


def test_bundle_surface_sidecar_warn_warns(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    surface = tmp_path / 'surface.json'
    surface.write_text(json.dumps({'status': 'warn'}), encoding='utf-8')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['links'] = {'bundle_surface_validation_path': surface.name}
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(manifest, 'basic_repo_question')

    assert result['status'] == 'warn'
    assert any(f['artifact'] == 'bundle_surface_validation' and f['severity'] == 'warn' for f in result['findings'])


def test_preflight_cli_valid_manifest_prints_preflight_json(tmp_path, capsys):
    from merger.repoground.cli.main import main

    rc = main(['ground', 'preflight', '--bundle-manifest', str(_bundle(tmp_path, FULL_BASIC))])

    captured = capsys.readouterr()
    assert rc == 0
    emitted = json.loads(captured.out)
    assert emitted['kind'] == 'repobrief.consumption_preflight'
    assert emitted['status'] == 'pass'
    assert emitted['mutation_boundary']['writes'] == []


def test_required_linked_surface_sidecar_unreadable_fails(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    surface = tmp_path / 'surface.json'
    surface.mkdir()
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['links'] = {'bundle_surface_validation_path': surface.name}
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(manifest, 'artifact_surface_review')

    assert result['status'] == 'fail'
    assert any(
        f['code'] == 'validation_required_sidecar_unreadable'
        and f['artifact'] == 'bundle_surface_validation'
        and f['severity'] == 'fail'
        for f in result['findings']
    )


def test_bundle_surface_recorded_status_mismatch_warns(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    surface = tmp_path / 'surface.json'
    surface.write_text(json.dumps({'status': 'pass'}), encoding='utf-8')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['links'] = {
        'bundle_surface_validation_path': surface.name,
        'bundle_surface_validation_status': 'warn',
    }
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(manifest, 'basic_repo_question')

    assert result['status'] == 'warn'
    assert result['validation']['bundle_surface_validation']['recorded_status'] == 'warn'
    assert result['validation']['bundle_surface_validation']['sidecar_status'] == 'pass'
    assert any(f['code'] == 'validation_surface_status_mismatch' for f in result['findings'])


def test_used_range_resolves_bundle_manifest_lines(tmp_path):
    result = run_consumption_preflight(
        _bundle(tmp_path, FULL_BASIC),
        'basic_repo_question',
        used_ranges=[{'artifact': 'bundle_manifest', 'range_ref': {'start_line': 1, 'end_line': 1}}],
    )

    assert result['status'] == 'pass'
    assert result['used_ranges']['resolved'][0]['artifact'] == 'bundle_manifest'


def test_used_range_resolves_linked_post_emit_health_lines(tmp_path):
    result = run_consumption_preflight(
        _bundle(tmp_path, FULL_BASIC),
        'basic_repo_question',
        used_ranges=[{'artifact': 'post_emit_health', 'range_ref': {'start_line': 1, 'end_line': 1}}],
    )

    assert result['status'] == 'pass'
    assert result['used_ranges']['resolved'][0]['artifact'] == 'post_emit_health'


def test_used_range_resolves_bundle_surface_validation_lines(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    surface = tmp_path / 'surface.json'
    surface.write_text(json.dumps({'status': 'pass'}), encoding='utf-8')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['links'] = {'bundle_surface_validation_path': surface.name}
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(
        manifest,
        'basic_repo_question',
        used_ranges=[{'artifact': 'bundle_surface_validation', 'range_ref': {'start_line': 1, 'end_line': 1}}],
    )

    assert result['status'] == 'pass'
    assert result['used_ranges']['resolved'][0]['artifact'] == 'bundle_surface_validation'


def test_used_range_prefers_existing_duplicate_role_path(tmp_path):
    existing = tmp_path / 'canonical_existing.txt'
    existing.write_text('ok\n', encoding='utf-8')

    manifest = _bundle(tmp_path, ['agent_reading_pack', 'citation_map_jsonl', 'snapshot_plan_json'])
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['artifacts'].append({
        'role': 'canonical_md',
        'path': 'canonical_missing.txt',
        'content_type': 'text/plain',
        'bytes': 1,
        'sha256': '0' * 64,
    })
    data['artifacts'].append({
        'role': 'canonical_md',
        'path': existing.name,
        'content_type': 'text/plain',
        'bytes': existing.stat().st_size,
        'sha256': '1' * 64,
    })
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(
        manifest,
        'basic_repo_question',
        used_ranges=[{'artifact': 'canonical_md', 'range_ref': {'start_line': 1, 'end_line': 1}}],
    )

    assert result['status'] == 'pass'
    assert result['used_ranges']['resolved'][0]['artifact'] == 'canonical_md'


def test_snapshot_profile_fail_counts_in_validation_state(tmp_path):
    manifest = _bundle(
        tmp_path,
        FULL_BASIC,
        capabilities={'repobrief_profile': 'security-export-review'},
    )

    result = run_consumption_preflight(manifest, 'basic_repo_question')

    validation_check = next(c for c in result['checks'] if c['name'] == 'validation_state')
    assert validation_check['status'] == 'fail'
    assert any(f['code'] == 'snapshot_profile_missing_required' for f in result['findings'])


def test_declaration_must_include_required_negative_semantics(tmp_path):
    result = run_consumption_preflight(
        _bundle(tmp_path, FULL_BASIC),
        'basic_repo_question',
        declaration={'does_not_establish': ['irgendwas']},
    )

    assert result['status'] == 'fail'
    assert any(f['code'] == 'declaration_missing_negative_semantics' for f in result['findings'])


def test_artifact_status_exposes_resolved_duplicate_role_path(tmp_path):
    existing = tmp_path / 'canonical_existing.txt'
    existing.write_text('ok\n', encoding='utf-8')

    manifest = _bundle(tmp_path, ['agent_reading_pack', 'citation_map_jsonl', 'snapshot_plan_json'])
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['artifacts'].append({
        'role': 'canonical_md',
        'path': 'canonical_missing.txt',
        'content_type': 'text/plain',
        'bytes': 1,
        'sha256': '0' * 64,
    })
    data['artifacts'].append({
        'role': 'canonical_md',
        'path': existing.name,
        'content_type': 'text/plain',
        'bytes': existing.stat().st_size,
        'sha256': '1' * 64,
    })
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(
        manifest,
        'basic_repo_question',
        used_ranges=[{'artifact': 'canonical_md', 'range_ref': {'start_line': 1, 'end_line': 1}}],
    )

    status = next(s for s in result['artifact_statuses'] if s['role'] == 'canonical_md')
    assert result['status'] == 'pass'
    assert status['path'] == 'canonical_missing.txt'
    assert status['resolved_path'].endswith('canonical_existing.txt')


def test_linked_directory_sidecar_is_not_available(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    surface = tmp_path / 'surface.json'
    surface.mkdir()
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['links'] = {'bundle_surface_validation_path': surface.name}
    manifest.write_text(json.dumps(data), encoding='utf-8')

    result = run_consumption_preflight(manifest, 'basic_repo_question')

    status = next(s for s in result['artifact_statuses'] if s['role'] == 'bundle_surface_validation')
    assert result['status'] == 'warn'
    assert status['availability'] == 'file_missing'
    assert status['file_exists'] is False
    assert any(
        f['artifact'] == 'bundle_surface_validation' and 'not a regular file' in f['detail']
        for f in result['findings']
    )


def _write_bound_post_health(manifest: Path, *, status='pass', bundle_run_id='run-1', manifest_path=None):
    target_manifest = manifest if manifest_path is None else manifest_path
    (manifest.parent / 'sample.bundle_health.post.json').write_text(
        json.dumps({
            'kind': 'lenskit.post_emit_health',
            'version': '1.0',
            'bundle_manifest_path': str(target_manifest.resolve()),
            'bundle_run_id': bundle_run_id,
            'status': status,
            'checks': [],
        }),
        encoding='utf-8',
    )



def test_post_emit_health_must_have_expected_kind(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC, post={'kind': 'not.post.emit.health', 'status': 'pass'})

    result = run_consumption_preflight(manifest, 'pr_review')

    assert result['status'] == 'fail'
    assert result['validation']['post_emit_health']['binding_status'] == 'fail'
    assert any(
        f['artifact'] == 'post_emit_health' and 'kind mismatch' in f['detail']
        for f in result['findings']
    )


def test_post_emit_health_must_have_expected_version(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC, post={'version': '2.0', 'status': 'pass'})

    result = run_consumption_preflight(manifest, 'pr_review')

    assert result['status'] == 'fail'
    assert result['validation']['post_emit_health']['binding_status'] == 'fail'
    assert any(
        f['artifact'] == 'post_emit_health' and 'version mismatch' in f['detail']
        for f in result['findings']
    )


def test_post_emit_health_rejects_invalid_status(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC, post={'status': 'degraded'})

    result = run_consumption_preflight(manifest, 'pr_review')

    assert result['status'] == 'fail'
    assert result['validation']['post_emit_health']['binding_status'] == 'fail'
    assert any(
        f['artifact'] == 'post_emit_health' and 'invalid status' in f['detail']
        for f in result['findings']
    )

def test_post_emit_health_must_bind_to_manifest_path(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['run_id'] = 'run-1'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    other_manifest = tmp_path / 'other.bundle.manifest.json'
    other_manifest.write_text(json.dumps({'kind': 'repobrief.bundle_manifest', 'run_id': 'other'}), encoding='utf-8')
    _write_bound_post_health(manifest, manifest_path=other_manifest)

    result = run_consumption_preflight(manifest, 'pr_review')

    assert result['status'] == 'fail'
    assert result['validation']['post_emit_health']['binding_status'] == 'fail'
    assert any(
        f['code'] == 'validation_required_sidecar_unreadable'
        and f['artifact'] == 'post_emit_health'
        and 'bundle_manifest_path does not match' in f['detail']
        for f in result['findings']
    )


def test_post_emit_health_pass_must_bind_to_manifest_run_id(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['run_id'] = 'run-1'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    _write_bound_post_health(manifest, bundle_run_id='other-run')

    result = run_consumption_preflight(manifest, 'pr_review')

    assert result['status'] == 'fail'
    assert result['validation']['post_emit_health']['binding_status'] == 'fail'
    assert any(
        f['artifact'] == 'post_emit_health'
        and 'bundle_run_id does not match' in f['detail']
        for f in result['findings']
    )


def test_post_emit_health_valid_binding_passes(tmp_path):
    manifest = _bundle(tmp_path, FULL_BASIC)
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['run_id'] = 'run-1'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    _write_bound_post_health(manifest, bundle_run_id='run-1')

    result = run_consumption_preflight(manifest, 'pr_review')

    assert result['validation']['post_emit_health']['binding_status'] == 'pass'
    assert not any(
        f['artifact'] == 'post_emit_health' and 'does not match' in f['detail']
        for f in result['findings']
    )
