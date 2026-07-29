#!/usr/bin/env python3
"""Canonical RBAW-V1-T004 Patch Evaluation Sidecar entry point."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_LEGACY_PATH = _ROOT / "patch_evaluation_sidecar_legacy.py"
_HARDENING_PATH = _ROOT / "patch_evaluation_sidecar_hardening.py"
_HOST_READBACK_PATH = _ROOT / "patch_evaluation_sidecar_host_readback.py"
_PROCESS_BUDGET_PATH = _ROOT / "patch_evaluation_sidecar_process_budget.py"


def _load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_legacy = _load("patch_evaluation_sidecar_legacy", _LEGACY_PATH)
_hardening = _load("patch_evaluation_sidecar_hardening", _HARDENING_PATH)
_host_readback = _load("patch_evaluation_sidecar_host_readback", _HOST_READBACK_PATH)
_process_budget = _load(
    "patch_evaluation_sidecar_process_budget", _PROCESS_BUDGET_PATH
)
_hardening.apply_hardening(_legacy, wrapper_path=__file__)
_host_readback.apply_host_readback_hardening(
    _legacy, _hardening, wrapper_path=__file__
)
_process_budget.apply_process_budget(
    _legacy,
    _hardening,
    _host_readback,
    wrapper_path=__file__,
)


class _SidecarProxy(types.ModuleType):
    def __getattr__(self, name: str):
        return getattr(_legacy, name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("__") or name in {
            "_legacy",
            "_hardening",
            "_host_readback",
            "_process_budget",
        }:
            super().__setattr__(name, value)
            return
        setattr(_legacy, name, value)


sys.modules[__name__].__class__ = _SidecarProxy


if __name__ == "__main__":
    raise SystemExit(_legacy.main())
