from .utils import helper
import json


def run() -> str:
    return json.dumps({"ok": helper()})
