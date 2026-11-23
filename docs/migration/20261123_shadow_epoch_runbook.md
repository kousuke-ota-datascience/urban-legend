# Repository migration 2026-11-23 — Shadow Epoch runbook

> Status: PREPARED / NOT ACTIVATED. This document describes a proposed
> operator-controlled cutover. It does not authorize production migration.

## Immutable provenance and boundaries

- Source: `kousuke-ota-datascience/0015_zenn`, subdirectory
  `workspace/articles/f8fe59b49c2e1e`.
- Target: `kousuke-ota-datascience/urban-legend`, repository root.
- Baseline target commit: `7106d70967d14205e7a66c289e6ee26db8ea8ce3`.
- Source/target Git tree SHA: `497b385c7bd9ae094fdd5559a1197b99bb0c4487`.
- Historical Review files: `reviews/10_each_lore/<Entry_ID>/` (351 files,
  117 cycles, 27 entries). **Do not edit, rename, or delete.**
- New Review namespace: `reviews/active/10_each_lore/<Entry_ID>/`.
- New Review sequence: `max(previous active Seq, legacy maximum Seq) + 1`.
- Control Plane: **new shadow Notion data source**, never mutate the legacy
  source `3dee5855be39807e90c7000bb6d72cd3`.

The original Review target commit SHA is historical evidence, not an alias for
the new baseline commit. Some historical artifact paths are inconsistent; record
exceptions rather than rewriting the evidence.

## Implemented safety gates

The migration branch provides:

1. `python -m src.migration.audit` — read-only verification of immutable
   legacy Review tree, 81 canonical baseline blob SHAs and entry manifest.
2. Review readers that expose **active-only** verdicts to Workflow 00.
3. New append-only Review writer namespace and legacy-based Seq allocation.
4. No implicit fallback to the old Notion data source.
5. Preflight before Workflow 90 initial synchronization: correct shadow
   data source, correct Git repository and unique push URL, clean tree,
   non-default branch, migration ancestry and historical Review immutability.
6. Entries with historical `要修正` are blocked until their migration
   remediation is explicitly documented.

The manifest at `migration/20261123/manifest.json` intentionally has
`phase: prepared` and `shadow_controlplane_data_source_id: null`.
**Thus production Workflow 00 is designed to fail closed.**

## Follow-up work (NOT completed by this branch)

- [ ] Implement a read-only snapshot export and idempotent provisioning/verify
  procedure for the 406-entry / 1,218-row shadow Notion control plane.
- [ ] Provision an isolated test data source and validate it, without changing
  legacy Notion rows.
- [ ] Implement the explicit remediation record/provenance gate for the five
  Entries with legacy `要修正`, and verify that old Findings are not lost.
- [ ] Verify Review target path/commit anomalies against legacy Git history and
  store results in a provenance exceptions register.
- [ ] Extend unit/contract testing and demonstrate real Codex CLI E2E from
  a dedicated new-repository branch against an isolated test control plane.
- [ ] Prepare production shadow DB and compare every logical key, statuses,
  checkpoints and migration output with the snapshot.
- [ ] After a separate cutover gate, configure the shadow ID and explicitly
  transition manifest to `testing` (with `WORKFLOW_MIGRATION_TEST_MODE=1`)
  or `active`. Never activate while any blocking finding remains.
- [ ] Produce a final PASS/rollback record. Git main and historical Notion must
  remain untouched until cutover is approved.

## Intended cutover verification

All 1,218 shadow rows must be present with unique `(Entry_ID, 成果物)` keys.
The 379 unstarted Entries retain `未` statuses and empty checkpoints.
The 27 historic Entries must each have a new Epoch checkpoint derived from
their actual canonical last-change commit (not an arbitrary HEAD), no active
Review until a fresh Review is produced, and preserved historical dispositions
in the manifest. Never treat a historical Pass as an active Pass.

Run from a clean standalone clone and a dedicated non-default branch:

```bash
uv run python -m src.migration.audit
uv run --group dev python -m pytest -q tests
# Only after shadow DB is populated, validated and manifest activated:
export NOTION_CONTROLPLANE_DATA_SOURCE_ID=<SHADOW_DATA_SOURCE_ID>
export WORKFLOW_GIT_REMOTE=origin
uv run python -m src.orchestration.entry_pipeline <Entry_ID>
```

**Critical:** Workflow 00 can invoke Creator with `danger-full-access` and
`approval_policy="never"`. Use only a designated test Entry and isolated
working branch and control plane. Historical review inputs are not to be
mistaken for new semantic review results.

## Rollback

- Prior to cutover: discard test branch/data source; legacy repo/control plane
  remain unchanged. Preserve GitHub branch or PR for audit.
- After activation but before new writes: revert connection configuration to
  the previous production setup and keep manifest/testing branch for analysis.
- After new Epoch writes: **no automatic rollback**. Preserve all Git/Notion
  snapshots and manually reconcile new commits, reviews and checkpoints before
  choosing a new direction. Avoid rewriting commit history referenced by
  Notion or Review JSON.
