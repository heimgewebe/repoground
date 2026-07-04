import json
from pathlib import Path

from merger.lenskit.core.repobrief_preflight import run_consumption_preflight


def _artifact(root: Path, role: str, text: str = 'x\n') -> dict:
    path = root / f'{role}.txt'
    path.write_text(text, encoding='utf-8')
    return {'role': role, 'path': path.name, 'content_type': 'text/plain', 'bytes': path.stat().st_size, 'sha256': '0' * 64}


def _bundle(tmp_path: Path, roles, *, generator=True, post=True, capabilities=None):
    artifacts = [_artifact(tmp_path, role) for role in roles]
    data = {'kind': 'repobrief.bundle_manifest', 'created_at': '2026-07-04T06:00:00Z', 'artifacts': artifacts}
    if generator:
        data['generator'] = {'runtime': {'git_commit': 'a' * 40}}
    if capabilities:
        data['capabilities'] = capabilities
    manifest = tmp_path / 'sample.bundle.manifest.json'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    if post is True:
        (tmp_path / 'sample.bundle_health.post.json').write_text(json.dumps({'status': 'pass', 'checks': []}), encoding='utf-8')
    elif isinstance(post, dict):
        (tmp_path / 'sample.bundle_health.post.json').write_text(json.dumps(post), encoding='utf-8')
    return manifest


FULL_BASIC = ['agent_reading_pack', 'canonical_md', 'citation_map_jsonl', 'snapshot_plan_json']


def test_full_basic_bundle_passes(tmp_path):
    result = run_consumption_preflight(_bundle(tmp_path, FULL_BASIC), 'basic_repo_question')
    assert result['status'] == 'pass'
    assert result['missing_required_artifacts'] == []


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
    from merger.lenskit.cli.main import main

    rc = main([
        'repobrief',
        'preflight',
        '--bundle-manifest',
        str(tmp_path / 'missing.bundle.manifest.json'),
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert 'repobrief preflight: bundle manifest does not exist' in captured.err
    assert 'Traceback' not in captured.err


def test_preflight_cli_invalid_manifest_json_returns_usage_error(tmp_path, capsys):
    from merger.lenskit.cli.main import main

    manifest = tmp_path / 'bad.bundle.manifest.json'
    manifest.write_text('{bad json', encoding='utf-8')

    rc = main([
        'repobrief',
        'preflight',
        '--bundle-manifest',
        str(manifest),
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert 'repobrief preflight: bundle manifest is not valid JSON' in captured.err
    assert 'Traceback' not in captured.err
