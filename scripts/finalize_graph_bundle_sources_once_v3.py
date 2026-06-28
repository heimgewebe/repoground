from pathlib import Path


path = Path("scripts/finalize_graph_bundle_sources_once.py")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
indexes = []
for index, line in enumerate(lines):
    if "if __name__ == '__main__'" in line and "\\n" in line:
        indexes.append(index)
if len(indexes) != 1:
    raise RuntimeError(f"expected one fixture line, found {len(indexes)}")
index = indexes[0]
lines[index] = lines[index].replace("\\n", "\\\\n")
path.write_text("".join(lines), encoding="utf-8")

manifest_test = Path(
    "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py"
)
test_lines = manifest_test.read_text(encoding="utf-8").splitlines(keepends=True)
def_index = next(
    index
    for index, line in enumerate(test_lines)
    if line.strip() == "def build_with_current_sources("
)
signature_end = next(
    index
    for index in range(def_index + 1, len(test_lines))
    if test_lines[index].strip() == "):"
)
if not any("repo_summaries" in line for line in test_lines[def_index:signature_end]):
    test_lines.insert(signature_end, "        repo_summaries=None,\n")

return_index = next(
    index
    for index in range(signature_end + 1, len(test_lines))
    if test_lines[index].strip() == "return original_build("
)
call_end = next(
    index
    for index in range(return_index + 1, len(test_lines))
    if test_lines[index] == "        )\n"
)
if not any("repo_summaries=" in line for line in test_lines[return_index:call_end]):
    test_lines.insert(call_end, "            repo_summaries=repo_summaries,\n")
manifest_test.write_text("".join(test_lines), encoding="utf-8")

import finalize_graph_bundle_sources_once_v2  # noqa: E402,F401
