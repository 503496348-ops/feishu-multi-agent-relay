# Team Runtime Command Surface

BarrenOrder extends its group-chat coordination model with a runtime command surface for standing multi-agent teams. The goal is not to let every worker consume user messages; the invariant remains: **human input enters through the coordinator, workers return evidence to the coordinator**.

## Runtime Invariants

1. **Manager-only ingress**: human messages route to the coordinator unless an explicit internal protocol message targets a worker.
2. **Worker evidence return**: workers report task evidence, status, and blockers back to the coordinator, not directly to the user.
3. **No self-loop**: bot-originated status cards, coordinator summaries, and worker cards must not be re-ingested as fresh user instructions.
4. **Dedup by message id**: every inbound message has a seen-set entry; replay/catchup must not duplicate work.
5. **Visibility filter**: publish filters decide which worker chatter appears in the external group; audit logs keep the full trace.
6. **Approval gate**: suspended or high-risk tasks require explicit approve/reject before continuing.

## Suggested Slash Commands

| Command | Purpose | Must Verify |
|---|---|---|
| `/team` | Show roster, role, status, and last heartbeat. | Agent exists in config and heartbeat is fresh. |
| `/health` | Show router, worker, queue, and resource health. | PID/cmdline/heartbeat/probe all agree. |
| `/task create` | Create a task with owner, acceptance, and risk level. | Intent anchor stored before dispatch. |
| `/task pause` | Suspend a task before risky action. | State becomes `suspended`; worker cannot advance status directly. |
| `/task approve` | Resume or complete a suspended task. | Approval note is attached to the task. |
| `/task reject` | Send task to rework or cancel. | Feedback is attached; terminal states cannot resurrect. |
| `/tmux` | Inspect an agent pane or latest transcript. | Output is read-only and redacted. |
| `/usage` | Summarize CLI/provider usage when available. | Missing data reports as unknown, not zero. |

## Event Routing State Machine

```text
raw event
  → normalize content/sender/chat/message_id
  → drop self/cross-chat/empty/duplicate
  → detect slash command
  → classify human/agent/internal message
  → route to coordinator or worker target
  → persist decision + seen id
  → deliver with wake/probe check
```

## Acceptance Evidence

A runtime enhancement is not complete until these are true:

- Route tests cover human → coordinator, worker → coordinator, self-loop drop, duplicate drop, cross-chat drop, unknown worker fallback.
- Task tests cover create, pause, approve, reject, terminal freeze, suspended-state guard.
- Health tests cover stale PID, cmdline mismatch, missing heartbeat, stale heartbeat, and live agent probe.
- A runbook explains how to recover a stuck router without losing pending events.
