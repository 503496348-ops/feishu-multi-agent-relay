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
