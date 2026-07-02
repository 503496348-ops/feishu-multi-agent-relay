# Changelog

All notable changes to `barren-order` should be documented in this file.

This repository follows a lightweight Keep-a-Changelog style and semantic versioning where applicable.

## Unreleased

- Governance baseline initialized.

## 1.3.0 - Standing team runtime command surface

- Added team runtime command-surface reference for manager-only ingress, worker evidence return, slash commands, deduplication, visibility filters, and approval gates.
- Expanded Skill metadata and workflow guidance for observable standing multi-agent teams.

## 1.2.0 - Runtime semantics enhancement

- Added explicit `RoutingDecision` router state machine with stable reason codes.
- Added manager-only human entry and worker-to-manager return semantics.
- Added self-loop, cross-team, duplicate, empty-message, unknown/unavailable-target guards.
- Added immutable intent + task approval state machine in `scripts/task_state.py`.
- Added `TeamExperienceStore` with pinned core, on-demand recall, and unpinned-first eviction.
- Added PID/cmdline/heartbeat/agent-probe health verification in `scripts/watchdog.py`.
- Added unittest coverage for routing, approval gates, team experience, and watchdog health.
## 2026-07-02 融合增强

- 荒原序列新增阶段证据 manifest：每个 passed 阶段必须带 artifact 与 verifier，防止无证据推进。

## v1.4.0 — 会前情报任务流

- 新增 `scripts/pre_meeting_taskflow.py`：四线并行人物情报计划、worker证据包、完整性门禁。
- 新增 `tests/test_pre_meeting_taskflow.py`：验证四线任务生成、manager-only可见性、证据完整性检查。
