

from merger.repoground.core.merge import scan_repo

def test_scan_repo_include_paths_tri_state(tmp_path):
    # Setup dummy repo
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "readme.md").write_text("info") # critical
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("code")
    (repo / "docs").mkdir()
    (repo / "docs" / "manual.md").write_text("manual")

    # 1. include_paths = None (All)
    res_none = scan_repo(repo, include_paths=None)
    files_none = [f.rel_path.as_posix() for f in res_none["files"]]
    assert "readme.md" in files_none
    assert "src/main.py" in files_none
    assert "docs/manual.md" in files_none

    # 2. include_paths = [] (Empty/Force-only)
    res_empty = scan_repo(repo, include_paths=[])
    files_empty = [f.rel_path.as_posix() for f in res_empty["files"]]
    assert "readme.md" in files_empty # Critical always included
    assert "src/main.py" not in files_empty
    assert "docs/manual.md" not in files_empty

    # 3. include_paths = ["."] (All)
    res_dot = scan_repo(repo, include_paths=["."])
    files_dot = [f.rel_path.as_posix() for f in res_dot["files"]]
    assert set(files_dot) == set(files_none)

    # 4. include_paths = ["src"] (Whitelist dir)
    res_src = scan_repo(repo, include_paths=["src"])
    files_src = [f.rel_path.as_posix() for f in res_src["files"]]
    assert "readme.md" in files_src # Critical
    assert "src/main.py" in files_src
    assert "docs/manual.md" not in files_src

def test_prescan_ignore_globs_relpath(tmp_path):
    from merger.repoground.core.merge import prescan_repo

    repo = tmp_path / "repo2"
    repo.mkdir()
    (repo / "foo.lock").write_text("lock")
    (repo / "sub").mkdir()
    (repo / "sub" / "foo.lock").write_text("lock")
    (repo / "keep.txt").write_text("keep")

    # Ignore *.lock (basename match)
    res_base = prescan_repo(repo, ignore_globs=["*.lock"])
    # We need to traverse tree to find files
    files_base = []
    def visit(node):
        if node["type"] == "file":
            files_base.append(node["path"])
        for c in node.get("children", []):
            visit(c)
    visit(res_base["tree"])

    assert "keep.txt" in files_base
    assert "foo.lock" not in files_base
    assert "sub/foo.lock" not in files_base

    # Ignore sub/ (relpath match)
    res_rel = prescan_repo(repo, ignore_globs=["sub/*"])
    files_rel = []
    def visit2(node):
        if node["type"] == "file":
            files_rel.append(node["path"])
        for c in node.get("children", []):
            visit2(c)
    visit2(res_rel["tree"])

    assert "keep.txt" in files_rel
    assert "foo.lock" in files_rel
    assert "sub/foo.lock" not in files_rel
