# pyright: reportMissingImports=false
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from message_router import AgentCard, AgentRole, MessageRouter, RelayMessage, RouteAction
from shared_memory import TeamExperienceStore
from task_state import TaskStateStore, TaskStatus
from watchdog import HealthStatus, WatchSpec, verify_health


class MessageRouterRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        MessageRouter.reset()
        MessageRouter.configure_team(team_id="alpha", default_manager_id="manager")
        MessageRouter.register_agent(AgentCard("manager", "Manager", ["通用"], 10, role=AgentRole.MANAGER, team_id="alpha"))
        MessageRouter.register_agent(AgentCard("researcher", "Researcher", ["研究", "检索"], 8, role=AgentRole.WORKER, team_id="alpha"))

    def test_human_entry_routes_to_manager_only(self):
        decision = MessageRouter.decide(RelayMessage("m1", "user", "帮我研究竞品", keywords=["研究"], sender_team_id="alpha"))
        self.assertEqual(decision.action, RouteAction.ROUTE)
        self.assertEqual(decision.targets, ("manager",))
        self.assertEqual(decision.reason, "manager_entry")

    def test_manager_delegates_by_capability(self):
        decision = MessageRouter.decide(RelayMessage("m2", "manager", "研究一下", keywords=["研究"], sender_team_id="alpha", is_bot_sender=True))
        self.assertEqual(decision.targets, ("researcher",))
        self.assertEqual(decision.reason, "capability_match")

    def test_worker_message_returns_to_manager(self):
        decision = MessageRouter.decide(RelayMessage("m3", "researcher", "完成了", sender_team_id="alpha", is_bot_sender=True))
        self.assertEqual(decision.targets, ("manager",))
        self.assertEqual(decision.reason, "worker_return")

    def test_dedup_and_cross_team_and_self_loop_drop(self):
        first = RelayMessage("m4", "user", "hello", sender_team_id="alpha")
        self.assertEqual(MessageRouter.decide(first).reason, "manager_entry")
        self.assertEqual(MessageRouter.decide(first).reason, "dedup")
        cross = MessageRouter.decide(RelayMessage("m5", "user", "hello", sender_team_id="beta"))
        self.assertEqual(cross.reason, "cross_team")
        self_loop = MessageRouter.decide(RelayMessage("m6", "researcher", "@我", target_agent="researcher", sender_team_id="alpha", is_bot_sender=True))
        self.assertEqual(self_loop.reason, "bot_self")

    def test_slash_command_routes_to_manager_as_slash(self):
        decision = MessageRouter.decide(RelayMessage("m7", "user", "普通行\n/status", sender_team_id="alpha"))
        self.assertEqual(decision.action, RouteAction.SLASH)
        self.assertEqual(decision.targets, ("manager",))


class TaskStateStoreTests(unittest.TestCase):
    def test_intent_is_immutable_and_approval_is_hard_suspend(self):
        store = TaskStateStore()
        intent_id = store.create_intent("用户原始需求", creator="user", source_msg="msg-1", key_points=["A"])
        task_id = store.create_task("执行任务", assignee="researcher", intent_id=intent_id)
        store.update_task(task_id, status=TaskStatus.IN_PROGRESS)
        store.pause_for_approval(task_id, note="需要确认预算", awaiting="manager", by="researcher")
        with self.assertRaises(ValueError):
            store.update_task(task_id, status=TaskStatus.DONE)
        store.approve(task_id, done=True, note="批准")
        self.assertEqual(store.get_task(task_id)["status"], TaskStatus.DONE.value)
        with self.assertRaises(ValueError):
            store.update_task(task_id, status=TaskStatus.IN_PROGRESS)
        self.assertEqual(store.get_intent(intent_id)["raw_text"], "用户原始需求")


class TeamExperienceStoreTests(unittest.TestCase):
    def test_pinned_entries_survive_cap_and_unpinned_recall_is_on_demand(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "experience.jsonl"
            store = TeamExperienceStore(path=path, max_entries=2)
            store.append("rule", "主持者统一对用户出口", pin=True)
            store.append("note", "旧经验", ref="old")
            store.append("note", "新经验", ref="new")
            stats = store.stats()
            self.assertEqual(stats["total_entries"], 2)
            self.assertEqual(stats["pinned_entries"], 1)
            self.assertIn("主持者统一对用户出口", store.build_core_prompt())
            recalled = store.recall("新经验")
            self.assertEqual(recalled[0]["ref"], "new")
            reloaded = TeamExperienceStore(path=path, max_entries=2)
            self.assertEqual(reloaded.stats()["pinned_entries"], 1)


class WatchdogTests(unittest.TestCase):
    def test_health_distinguishes_pid_alive_from_agent_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "pid"
            heartbeat = Path(tmp) / "heartbeat"
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
            heartbeat.write_text("ok", encoding="utf-8")
            spec = WatchSpec("worker", pid_file, "python", heartbeat_file=heartbeat, max_heartbeat_age=60)
            report = verify_health(spec, agent_probe=lambda name: "wedged")
            self.assertEqual(report.status, HealthStatus.DEGRADED)
            self.assertIn("agent_wedged", report.reasons)

            stale_now = time.time() + 120
            stale = verify_health(spec, agent_probe=lambda name: "idle", now=stale_now)
            self.assertEqual(stale.status, HealthStatus.DEGRADED)
            self.assertIn("heartbeat_stale", stale.reasons)


if __name__ == "__main__":
    unittest.main()
