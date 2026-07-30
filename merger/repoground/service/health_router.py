from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

from fastapi import APIRouter

from .router_support import AttributeProxy, dynamic_callable

router = APIRouter()


def _value(provider_attr: Callable[[], Any]) -> Any:
    return provider_attr()


@router.get("/api/version")
def api_version():
    build_commit = _get_build_commit()
    return {
        "product_version": _get_product_version(),
        "build_commit": build_commit,
        "build_id": _get_build_id(),
        "started_at": _get_server_start_time(),
        # Deprecated: historically aliased the build commit identity, not the
        # product release version. Kept for backward compatibility; new clients
        # should read "build_commit" instead. Do not repurpose this key to mean
        # the product version — that is "product_version" above.
        "version": build_commit,
    }


@router.get("/api/health")
def health():
    contract_version = _get_contract_version()
    build_commit = _get_build_commit()
    return {
        "status": "ok",
        # Unambiguous version identities — see the module-level comment above
        # CONTRACT_VERSION/BUILD_COMMIT for what each one is authoritative for.
        "product_version": _get_product_version(),
        "contract_version": contract_version,
        "build_commit": build_commit,
        # Deprecated legacy fields, kept for backward compatibility with older
        # clients. Do not use these for new integrations:
        #   "version" historically held the report/spec CONTRACT_VERSION, not the
        #   product release version.
        #   "server_version" historically held the BUILD_COMMIT identity.
        "version": contract_version,
        "server_version": build_commit,
        "hub": str(state.hub),
        "merges_dir": str(state.merges_dir) if state.merges_dir else None,
        "auth_enabled": bool(get_security_config().token),
        "running_jobs": _count_active_jobs(),
    }


def build_router(app_provider: Callable[[], ModuleType]):
    global state, get_security_config, _count_active_jobs
    global _get_build_commit, _get_build_id, _get_contract_version
    global _get_product_version, _get_server_start_time

    state = AttributeProxy(app_provider, "state")
    get_security_config = dynamic_callable(app_provider, "get_security_config")
    _count_active_jobs = dynamic_callable(app_provider, "_count_active_jobs")

    def _attr(name: str) -> Callable[[], Any]:
        def read() -> Any:
            return getattr(app_provider(), name)

        return read

    _get_build_commit = _attr("BUILD_COMMIT")
    _get_build_id = _attr("BUILD_ID")
    _get_contract_version = _attr("CONTRACT_VERSION")
    _get_product_version = _attr("PRODUCT_VERSION")
    _get_server_start_time = _attr("SERVER_START_TIME")
    return (router, api_version, health)
