"""Read-only baseline audit: python -m src.migration.audit.

This only reads the current local Git object store and migration manifest.
It NEVER calls Notion or changes the repository.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from .epoch import (
    ACTIVE_REVIEW_ROOT,
    LEGACY_REVIEW_ROOT,
    PROJECT_ROOT,
    MigrationGateError,
    _git,
    read_manifest,
    verify_baseline_canonical,
    verify_legacy_tree,
)


def audit() -> dict:
    manifest = read_manifest()
    verify_legacy_tree(manifest)
    verify_baseline_canonical(manifest)
    entries = manifest["entries"]

    review_files = sorted(LEGACY_REVIEW_ROOT.glob("*/Review_*.json"))
    if len(review_files) != manifest.get("legacy_review_files_expected"):
        raise MigrationGateError("legacy Review file count differs from manifest")
    for entry_id, item in entries.items():
        actual = _git("rev-parse", f"HEAD:reviews/10_each_lore/{entry_id}")
        if actual != item["legacy_review_dir_tree_sha"]:
            raise MigrationGateError(f"legacy Review directory changed: {entry_id}")
        for artifact in ("00", "10", "20"):
            path = item["baseline_canonical"][artifact]["path"]
            if not (PROJECT_ROOT / path).is_file():
                raise MigrationGateError(f"canonical artifact missing: {entry_id}/{artifact}")
        if item.get("migration_kind") not in {
            "fresh_review", "fresh_review_stale", "requires_correction"
        }:
            raise MigrationGateError(f"invalid migration_kind: {entry_id}")

    return {
        "result": "PASS",
        "phase": manifest["phase"],
        "migration_id": manifest["migration_id"],
        "legacy_review_files": len(review_files),
        "entry_count": len(entries),
        "canonical_baseline_count": len(entries) * 3,
        "active_review_files": len(list(ACTIVE_REVIEW_ROOT.glob("*/Review_*.json"))),
        "legacy_review_tree_sha": manifest["legacy_review_tree_sha"],
        "note": "baseline audit only: no Codex/Notion/E2E calls performed",
    }


def main() -> int:
    try:
        result = audit()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (MigrationGateError, OSError, ValueError) as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
