from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA_ROLE_DOC = REPO_ROOT / "docs/architecture/heimgewebe-infra-role.md"


def _read() -> str:
    return INFRA_ROLE_DOC.read_text(encoding="utf-8")


def test_infra_role_uses_current_operator_authority_split() -> None:
    text = _read()
    compact = " ".join(text.split())

    for expected in (
        "`repository_context_citations`",
        "Grabowski bindet Livezustand, Agent-Routing und freigegebene Ausführung.",
        "Bureau, GitHub, CI und Runtime behalten ihre jeweilige Primärwahrheit.",
        "HausKI ist nicht Bestandteil dieses erforderlichen Operatorpfads.",
    ):
        assert expected in compact


def test_infra_role_does_not_restore_hausmaister_as_required_gateway() -> None:
    text = _read()

    for stale_claim in (
        "Observation Source für hausKI/hausmAIster",
        "hausmAIster erzeugt Bedeutung.",
        "Öffentlicher Zugriff darf später nur über ein getrenntes `hausmaister-agent-gateway` laufen.",
        "no bypass of hausmAIster approval gates",
        "hausmAIster read-only adapter in hausKI",
    ):
        assert stale_claim not in text

    assert "HausKI ist ein eigenständiges Heimgewebe-System" in text
    assert "kein erforderlicher Vermittler zwischen RepoGround und Grabowski" in text
