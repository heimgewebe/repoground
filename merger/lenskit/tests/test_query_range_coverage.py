import json

from merger.lenskit.retrieval.query_range_coverage import build_query_range_coverage_report


def _ref(role='canonical_md', *, file_path='merge.md', start_byte=0, end_byte=10):
    return {
        'artifact_role': role,
        'repo_id': 'lenskit',
        'file_path': file_path,
        'start_byte': start_byte,
        'end_byte': end_byte,
        'start_line': 1,
        'end_line': 2,
        'content_sha256': 'a' * 64,
    }


def test_query_range_coverage_counts_per_hit_statuses():
    result = {
        'results': [
            {'chunk_id': 'canonical', 'path': 'merge.md', 'range': '1-2', 'range_ref': _ref('canonical_md')},
            {'chunk_id': 'noncanonical', 'path': 'src/example.py', 'range': '1-2', 'range_ref': _ref('source_file', file_path='src/example.py')},
            {'chunk_id': 'derived', 'path': 'src/derived.py', 'range': '1-2', 'derived_range_ref': _ref('source_file', file_path='src/derived.py')},
            {'chunk_id': 'unresolved', 'path': 'src/unresolved.py', 'range': '1-2'},
            {'chunk_id': 'malformed', 'path': 'src/broken.py', 'range': '1-2', 'range_ref': {'artifact_role': 'canonical_md'}},
        ]
    }

    report = build_query_range_coverage_report(result)

    assert report['total_hits'] == 5
    assert report['counts'] == {
        'hits_with_explicit_range_ref': 2,
        'hits_with_explicit_canonical_md_range_ref': 1,
        'hits_with_derived_range_ref': 1,
        'unresolved_hits': 1,
        'malformed_hits': 1,
        'citation_id_candidate_hits': 0,
    }
    assert report['status_counts'] == {
        'canonical_explicit': 1,
        'explicit_noncanonical': 1,
        'derived_source': 1,
        'unresolved': 1,
        'malformed': 1,
    }
    assert [hit['status'] for hit in report['per_hit']] == [
        'canonical_explicit',
        'explicit_noncanonical',
        'derived_source',
        'unresolved',
        'malformed',
    ]
    assert 'truth' in report['diagnostic_semantics']['does_not_establish']
    assert report['diagnostic_semantics']['canonical_preference'] == 'explicit canonical_md range_ref'


def test_query_range_coverage_adds_citation_id_candidates(tmp_path):
    canonical_ref = _ref('canonical_md')
    citation_map = tmp_path / 'citation_map.jsonl'
    citation_map.write_text(
        json.dumps({
            'citation_id': 'cite-123',
            'repo_id': 'lenskit',
            'chunk_id': 'chunk-a',
            'canonical_range': {
                'file_path': canonical_ref['file_path'],
                'start_byte': canonical_ref['start_byte'],
                'end_byte': canonical_ref['end_byte'],
                'start_line': canonical_ref['start_line'],
                'end_line': canonical_ref['end_line'],
                'content_sha256': canonical_ref['content_sha256'],
            },
        }) + '\n',
        encoding='utf-8',
    )
    result = {'results': [{'chunk_id': 'chunk-a', 'path': 'merge.md', 'range': '1-2', 'range_ref': canonical_ref}]}

    report = build_query_range_coverage_report(result, citation_map_jsonl=citation_map)

    assert report['counts']['citation_id_candidate_hits'] == 1
    assert report['per_hit'][0]['citation_id_candidates'] == [
        {'citation_id': 'cite-123', 'match_reasons': ['chunk_id', 'canonical_range']}
    ]
    assert report['citation_map']['status'] == 'loaded'


def test_query_range_coverage_missing_citation_map_is_diagnostic(tmp_path):
    missing = tmp_path / 'missing.citation_map.jsonl'
    report = build_query_range_coverage_report({'results': []}, citation_map_jsonl=missing)

    assert report['citation_map']['status'] == 'unusable'
    assert 'not found' in report['citation_map']['warnings'][0]
    assert report['total_hits'] == 0
    assert report['coverage']['explicit_range_ref_ratio'] == 0.0


def _ref_v2(role='canonical_md', *, artifact_path='merge.md', start_byte=0, end_byte=10):
    return {
        'range_ref_version': '2',
        'artifact_role': role,
        'repo_id': 'lenskit',
        'artifact_path': artifact_path,
        'artifact_byte_start': start_byte,
        'artifact_byte_end': end_byte,
        'artifact_line_start': 1,
        'artifact_line_end': 2,
        'source_file_path': 'src/example.py',
        'source_line_start': 3,
        'source_line_end': 4,
        'content_sha256': 'b' * 64,
        'range_content_sha256': 'a' * 64,
    }


def test_query_range_coverage_accepts_v2_canonical_refs_and_citation_candidates(tmp_path):
    canonical_ref = _ref_v2('canonical_md')
    citation_map = tmp_path / 'citation_map.jsonl'
    citation_map.write_text(
        json.dumps({
            'citation_id': 'cite-v2',
            'repo_id': 'lenskit',
            'chunk_id': 'chunk-v2',
            'canonical_range': {
                'file_path': canonical_ref['artifact_path'],
                'start_byte': canonical_ref['artifact_byte_start'],
                'end_byte': canonical_ref['artifact_byte_end'],
                'start_line': canonical_ref['artifact_line_start'],
                'end_line': canonical_ref['artifact_line_end'],
                'content_sha256': canonical_ref['range_content_sha256'],
            },
        }) + '\n',
        encoding='utf-8',
    )

    report = build_query_range_coverage_report(
        {'results': [{'chunk_id': 'chunk-v2', 'path': 'merge.md', 'range': '1-2', 'range_ref': canonical_ref}]},
        citation_map_jsonl=citation_map,
    )

    assert report['per_hit'][0]['status'] == 'canonical_explicit'
    assert report['counts']['hits_with_explicit_canonical_md_range_ref'] == 1
    assert report['per_hit'][0]['citation_id_candidates'] == [
        {'citation_id': 'cite-v2', 'match_reasons': ['chunk_id', 'canonical_range']}
    ]
