from pathlib import Path


path = Path("scripts/finalize_graph_bundle_sources_once.py")
text = path.read_text(encoding="utf-8")
old = '''        "if __name__ == '__main__':
    print('hello')
",
'''
new = '''        "if __name__ == '__main__':\\n    print('hello')\\n",
'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one test fixture string, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

import finalize_graph_bundle_sources_once_v2  # noqa: E402,F401
