

from merger.repoground.service.models import JobRequest, calculate_job_hash

def test_include_paths_hash_idempotency_tri_state():
    """
    Verify that include_paths behaves as a tri-state in hash calculation:
    - None (All) != [] (Empty/Force-only)
    - None == ["."] (All)
    - ["a"] == ["a"]
    """

    base_req = JobRequest(
        repos=["repo1"],
        level="dev",
        plan_only=True
    )

    # Helper for Pydantic v1/v2 compatibility
    def _copy(model):
        return model.model_copy() if hasattr(model, "model_copy") else model.copy()

    # 1. None vs []
    req_none = _copy(base_req)
    req_none.include_paths = None
    hash_none = calculate_job_hash(req_none, "/hub", "v1")

    req_empty = _copy(base_req)
    req_empty.include_paths = []
    hash_empty = calculate_job_hash(req_empty, "/hub", "v1")

    assert hash_none != hash_empty, "Hash should differ for include_paths=None (all) vs [] (none)"

    # 2. None vs ["."]
    req_dot = _copy(base_req)
    req_dot.include_paths = ["."]
    hash_dot = calculate_job_hash(req_dot, "/hub", "v1")

    assert hash_none == hash_dot, "Hash should be identical for include_paths=None vs ['.']"

    # 3. None vs ["", "."]
    req_mixed = _copy(base_req)
    req_mixed.include_paths = ["", "."]
    hash_mixed = calculate_job_hash(req_mixed, "/hub", "v1")

    assert hash_none == hash_mixed, "Hash should be identical for include_paths=None vs ['', '.']"

    # 4. Explicit paths
    req_paths = _copy(base_req)
    req_paths.include_paths = ["src/main.py"]
    hash_paths = calculate_job_hash(req_paths, "/hub", "v1")

    assert hash_paths != hash_none
    assert hash_paths != hash_empty
