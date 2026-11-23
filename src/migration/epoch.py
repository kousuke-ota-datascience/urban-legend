"""Fail-closed migration Epoch contract for the standalone urban-legend repository.

No mutation is performed by this module. Legacy Review JSON is immutable.
A prepared manifest does NOT authorize production execution or Notion writes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "migration/20261123/manifest.json"
OLD_CONTROLPLANE_ID = "3dee5855be39807e90c7000bb6d72cd3"
EXPECTED_LEGACY_REVIEW_TREE_SHA = "ac67031892f83df65652428c3720a839104204f6"
EXPECTED_REPOSITORY = "kousuke-ota-datascience/urban-legend"
LEGACY_REVIEW_ROOT = PROJECT_ROOT / "reviews/10_each_lore"
ACTIVE_REVIEW_ROOT = PROJECT_ROOT / "reviews/active/10_each_lore"


class MigrationGateError(RuntimeError):
    """Safety invariant prevents activation or a production side effect."""


def read_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_file = path or MANIFEST_PATH
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MigrationGateError(f"migration manifest not readable: {manifest_file}: {exc}") from exc
    if not isinstance(data, dict):
        raise MigrationGateError("migration manifest must be an object")
    if data.get("schema_version") != 1 or data.get("migration_id") != "repo-move-20261123":
        raise MigrationGateError("migration manifest schema/version/id mismatch")
    if data.get("target_repository") != EXPECTED_REPOSITORY:
        raise MigrationGateError("migration manifest target repository mismatch")
    if data.get("source_tree_sha") != "497b385c7bd9ae094fdd5559a1197b99bb0c4487":
        raise MigrationGateError("migration manifest source baseline mismatch")
    if data.get("target_baseline_commit") != "7106d70967d14205e7a66c289e6ee26db8ea8ce3":
        raise MigrationGateError("migration manifest target baseline mismatch")
    if data.get("legacy_review_tree_sha") != EXPECTED_LEGACY_REVIEW_TREE_SHA:
        raise MigrationGateError("immutable legacy Review tree SHA mismatch")
    if data.get("legacy_review_files_expected") != 351 or data.get("entry_count") != 27:
        raise MigrationGateError("unexpected legacy Review/Entry inventory")
    entries = data.get("entries")
    if not isinstance(entries, dict) or len(entries) != 27:
        raise MigrationGateError("migration manifest must describe exactly 27 historical entries")
    if not all(re.fullmatch(r"[0-9]{4}", key) for key in entries):
        raise MigrationGateError("invalid Entry_ID in migration manifest")
    return data


def _git(*arguments: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise MigrationGateError(
            f"git command failed: {arguments!r}: {(proc.stderr or proc.stdout).strip()}"
        )
    return proc.stdout.strip()


def verify_legacy_tree(manifest: dict[str, Any] | None = None) -> None:
    """Tree hash detects any addition, removal, or modification under legacy Review."""
    manifest = manifest or read_manifest()
    actual = _git("rev-parse", "HEAD:reviews/10_each_lore")
    if actual != manifest.get("legacy_review_tree_sha"):
        raise MigrationGateError(
            f"legacy Review tree was modified: expected={manifest.get('legacy_review_tree_sha')} "
            f"actual={actual}"
        )


def verify_baseline_canonical(manifest: dict[str, Any] | None = None) -> None:
    """Compare the immutable migration baseline; current canonicals may later evolve."""
    manifest = manifest or read_manifest()
    baseline = manifest["target_baseline_commit"]
    for entry_id, item in manifest["entries"].items():
        mapping = item.get("baseline_canonical")
        if not isinstance(mapping, dict) or set(mapping) != {"00", "10", "20"}:
            raise MigrationGateError(f"invalid baseline canonical mapping: {entry_id}")
        for artifact, fact in mapping.items():
            path = fact.get("path")
            expected = fact.get("blob_sha")
            if not isinstance(path, str) or not path.startswith("docs/10_each_lore/"):
                raise MigrationGateError(f"invalid baseline artifact path: {entry_id}/{artifact}")
            actual = _git("rev-parse", f"{baseline}:{path}")
            if actual != expected:
                raise MigrationGateError(f"baseline blob mismatch: {entry_id}/{artifact}")


def legacy_review_seq(entry_id: str, manifest: dict[str, Any] | None = None) -> int:
    manifest = manifest or read_manifest()
    entry = manifest["entries"].get(entry_id)
    return int(entry["legacy_review_seq"]) if entry is not None else 0


def _normalize_id(value: str) -> str:
    return value.replace("-", "").strip().lower()


def require_shadow_controlplane(manifest: dict[str, Any] | None = None) -> str:
    """Never silently fall back to the legacy Notion data source."""
    manifest = manifest or read_manifest()
    expected = manifest.get("shadow_controlplane_data_source_id")
    configured = os.environ.get("NOTION_CONTROLPLANE_DATA_SOURCE_ID", "")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9-]{32,36}", expected):
        raise MigrationGateError("shadow control-plane ID is not provisioned")
    if not configured or _normalize_id(configured) != _normalize_id(expected):
        raise MigrationGateError("NOTION_CONTROLPLANE_DATA_SOURCE_ID does not match manifest")
    if _normalize_id(configured) == OLD_CONTROLPLANE_ID:
        raise MigrationGateError("legacy Notion control-plane access is forbidden")
    if manifest.get("phase") not in {"testing", "active"}:
        raise MigrationGateError("migration is not activated")
    if manifest["phase"] == "testing" and os.environ.get("WORKFLOW_MIGRATION_TEST_MODE") != "1":
        raise MigrationGateError("testing phase requires WORKFLOW_MIGRATION_TEST_MODE=1")
    return _normalize_id(configured)


def _github_repo_from_push_url(url: str) -> str | None:
    """Accept only an unambiguous GitHub.com SSH/HTTPS repository URL."""
    url = url.strip()
    if url.startswith("git@github.com:"):
        path = url[len("git@github.com:"):]
    else:
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.netloc == "github.com":
            path = parsed.path.lstrip("/")
        elif (parsed.scheme == "ssh" and parsed.netloc == "git@github.com"):
            path = parsed.path.lstrip("/")
        else:
            return None
    if path.endswith(".git"):
        path = path[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        return None
    return path.lower()


def require_git_destination(remote: str, manifest: dict[str, Any] | None = None) -> None:
    manifest = manifest or read_manifest()
    if not remote or not re.fullmatch(r"[A-Za-z0-9_./-]+", remote):
        raise MigrationGateError("invalid Git remote name")
    urls = [line for line in _git("remote", "get-url", "--push", "--all", remote).splitlines() if line]
    if len(urls) != 1 or _github_repo_from_push_url(urls[0]) != EXPECTED_REPOSITORY:
        raise MigrationGateError(
            "Git push destination must be exactly the standalone urban-legend repository"
        )


def require_production_preflight(entry_id: str, remote: str) -> None:
    """Call BEFORE initial Workflow 90 synchronization or any Creator invocation."""
    manifest = read_manifest()
    require_shadow_controlplane(manifest)
    repo_root = Path(_git("rev-parse", "--show-toplevel")).resolve()
    if repo_root != PROJECT_ROOT:
        raise MigrationGateError("module location does not match Git working-tree root")
    baseline = manifest["target_baseline_commit"]
    if subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "merge-base", "--is-ancestor", baseline, "HEAD"],
        check=False,
    ).returncode != 0:
        raise MigrationGateError("migration baseline not in current Git ancestry")
    branch = _git("branch", "--show-current")
    if not branch or branch in {"main", "master"}:
        raise MigrationGateError("dedicated non-default work branch is mandatory")
    if _git("status", "--porcelain"):
        raise MigrationGateError("Git working tree must be clean before Workflow 00")
    verify_legacy_tree(manifest)
    require_git_destination(remote, manifest)
    record = manifest["entries"].get(entry_id)
    if record and record.get("migration_kind") == "requires_correction":
        if not record.get("legacy_correction_acknowledged"):
            raise MigrationGateError(
                f"legacy Finding remediation for Entry {entry_id} is not yet documented"
            )
    if not (os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_TOKEN")):
        raise MigrationGateError("Notion credentials are not configured")
