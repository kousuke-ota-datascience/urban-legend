"""Migration safety gates are deterministic and do not make external calls."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.migration import epoch
from src.reviewing import review_writer
from src.status_management import review_state


def test_manifest_pins_baseline_and_27_entries():
    manifest = epoch.read_manifest()
    assert manifest["phase"] == "prepared"
    assert manifest["entry_count"] == 27
    assert manifest["legacy_review_files_expected"] == 351
    assert manifest["shadow_controlplane_data_source_id"] is None
    assert manifest["entries"]["0001"]["legacy_review_seq"] == 7


def test_read_only_baseline_audit_passes():
    # Git working tree may include new code, but legacy subtrees must remain immutable.
    from src.migration.audit import audit
    result = audit()
    assert result["result"] == "PASS"
    assert result["canonical_baseline_count"] == 81
    assert result["legacy_review_files"] == 351


def test_legacy_review_is_excluded_from_active_state():
    active = review_state.load_entry_review_state("0001")
    assert not active.all_reviews
    legacy = review_state.load_entry_legacy_review_state("0001")
    assert legacy.all_reviews
    assert review_writer._next_review_seq("0001") == 8


def test_future_review_uses_legacy_max_seq():
    assert epoch.legacy_review_seq("0179") == 13
    assert epoch.legacy_review_seq("9999") == 0


@pytest.mark.parametrize("url", [
    "https://github.com/kousuke-ota-datascience/urban-legend.git",
    "git@github.com:kousuke-ota-datascience/urban-legend.git",
    "ssh://git@github.com/kousuke-ota-datascience/urban-legend",
])
def test_allowed_push_urls(url):
    assert epoch._github_repo_from_push_url(url) == epoch.EXPECTED_REPOSITORY


@pytest.mark.parametrize("url", [
    "https://github.com/kousuke-ota-datascience/0015_zenn.git",
    "https://github.com.evil.test/kousuke-ota-datascience/urban-legend.git",
    "https://someone:secret@github.com/kousuke-ota-datascience/urban-legend.git",
    "file:///tmp/urban-legend.git",
    "/tmp/urban-legend.git",
])
def test_reject_unsafe_push_urls(url):
    assert epoch._github_repo_from_push_url(url) != epoch.EXPECTED_REPOSITORY


def test_prepared_manifest_rejects_shadow_access(monkeypatch):
    monkeypatch.setenv("NOTION_CONTROLPLANE_DATA_SOURCE_ID", "a" * 32)
    with pytest.raises(epoch.MigrationGateError):
        epoch.require_shadow_controlplane()


def test_shadow_id_requires_exact_manifest_and_explicit_testing_mode(monkeypatch):
    manifest = copy.deepcopy(epoch.read_manifest())
    manifest["phase"] = "testing"
    manifest["shadow_controlplane_data_source_id"] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    monkeypatch.setenv("NOTION_CONTROLPLANE_DATA_SOURCE_ID", "a" * 32)
    monkeypatch.delenv("WORKFLOW_MIGRATION_TEST_MODE", raising=False)
    with pytest.raises(epoch.MigrationGateError, match="WORKFLOW_MIGRATION_TEST_MODE"):
        epoch.require_shadow_controlplane(manifest)
    monkeypatch.setenv("WORKFLOW_MIGRATION_TEST_MODE", "1")
    assert epoch.require_shadow_controlplane(manifest) == "a" * 32
    monkeypatch.setenv("NOTION_CONTROLPLANE_DATA_SOURCE_ID", epoch.OLD_CONTROLPLANE_ID)
    with pytest.raises(epoch.MigrationGateError):
        epoch.require_shadow_controlplane(manifest)


def test_push_destination_validation_rejects_multi_and_old_remote(monkeypatch):
    manifest = epoch.read_manifest()
    monkeypatch.setattr(
        epoch, "_git",
        lambda *_args: (
            "https://github.com/kousuke-ota-datascience/urban-legend.git\n"
            "https://github.com/kousuke-ota-datascience/0015_zenn.git"
        ),
    )
    with pytest.raises(epoch.MigrationGateError):
        epoch.require_git_destination("origin", manifest)
    monkeypatch.setattr(
        epoch, "_git",
        lambda *_args: "https://github.com/kousuke-ota-datascience/0015_zenn.git",
    )
    with pytest.raises(epoch.MigrationGateError):
        epoch.require_git_destination("origin", manifest)


def test_legacy_tree_mutation_is_detected(monkeypatch):
    monkeypatch.setattr(epoch, "_git", lambda *_args: "a" * 40)
    with pytest.raises(epoch.MigrationGateError, match="legacy Review tree"):
        epoch.verify_legacy_tree(epoch.read_manifest())


def test_legacy_findings_require_explicit_remediation_before_execution(monkeypatch):
    manifest = copy.deepcopy(epoch.read_manifest())
    manifest["phase"] = "testing"
    manifest["shadow_controlplane_data_source_id"] = "a" * 32
    monkeypatch.setattr(epoch, "read_manifest", lambda: manifest)
    monkeypatch.setattr(epoch, "_git", lambda *args: {
        ("rev-parse", "--show-toplevel"): str(epoch.PROJECT_ROOT),
        ("branch", "--show-current"): "migration/test",
        ("status", "--porcelain"): "",
    }.get(args, "ac67031892f83df65652428c3720a839104204f6"))
    monkeypatch.setattr(epoch, "verify_legacy_tree", lambda _m: None)
    monkeypatch.setattr(epoch, "require_git_destination", lambda *_args: None)
    monkeypatch.setattr(epoch.subprocess, "run", lambda *_a, **_k: type("P", (), {"returncode": 0})())
    monkeypatch.setenv("NOTION_CONTROLPLANE_DATA_SOURCE_ID", "a" * 32)
    monkeypatch.setenv("WORKFLOW_MIGRATION_TEST_MODE", "1")
    with pytest.raises(epoch.MigrationGateError, match="legacy Finding remediation"):
        epoch.require_production_preflight("0081", "origin")


def test_workflow00_preflight_blocks_before_initial_notion_sync(monkeypatch):
    from src.orchestration import entry_pipeline as pipeline

    monkeypatch.setattr(pipeline, "_resolve_push_remote", lambda _root: "origin")

    def deny(*_args):
        raise epoch.MigrationGateError("manifest remains prepared")

    def no_notions(*_args, **_kwargs):
        raise AssertionError("Workflow 90 may not run before migration preflight")

    monkeypatch.setattr(pipeline, "require_production_preflight", deny)
    monkeypatch.setattr(pipeline, "sync_controlplane", no_notions)
    result = pipeline.run_entry_pipeline("0001")
    assert result.result == "BLOCKED"
    assert result.reason_code == "MIGRATION_PREFLIGHT_FAILED"
    assert not result.control_plane_synchronized


def test_old_notion_data_source_cannot_be_accessed_via_new_client(monkeypatch):
    from src.status_management import notion_controlplane

    monkeypatch.delenv("NOTION_CONTROLPLANE_DATA_SOURCE_ID", raising=False)

    def no_network(*_args, **_kwargs):
        raise AssertionError("Notion must not be called before shadow validation")

    monkeypatch.setattr(notion_controlplane, "_request", no_network)
    with pytest.raises(epoch.MigrationGateError):
        notion_controlplane._list_rows()
