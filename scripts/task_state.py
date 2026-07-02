"""
BarrenOrder runtime task state machine.

This module keeps the user's original intent immutable and separates task
progress from approval gates. It is deliberately small and dependency-free so
agents can use it from CLI scripts, Feishu handlers, or tests.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class TaskStatus(str, Enum):
    PENDING = "待处理"
    IN_PROGRESS = "进行中"
    NEEDS_APPROVAL = "需审批"
    DONE = "已完成"
    CANCELLED = "已取消"


TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.CANCELLED}
GENERIC_TRANSITIONS = {
    TaskStatus.PENDING: {TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.PENDING, TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.NEEDS_APPROVAL},
    TaskStatus.NEEDS_APPROVAL: set(),
    TaskStatus.DONE: set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class IntentRecord:
    id: str
    raw_text: str
    creator: str = ""
    source_msg: str = ""
    key_points: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "raw_text": self.raw_text,
            "creator": self.creator,
            "source_msg": self.source_msg,
            "key_points": list(self.key_points),
            "created_at": self.created_at,
        }


@dataclass
class TaskRecord:
    id: str
    title: str
    assignee: str = ""
    description: str = ""
    creator: str = ""
    intent_id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    awaiting: str = ""
    approval_note: str = ""
    paused_by: str = ""
    paused_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "assignee": self.assignee,
            "description": self.description,
            "creator": self.creator,
            "intent_id": self.intent_id,
            "status": self.status.value,
            "awaiting": self.awaiting,
            "approval_note": self.approval_note,
            "paused_by": self.paused_by,
            "paused_at": self.paused_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class TaskStateStore:
    """JSON-backed task/intent store with approval-safe transitions."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self.tasks: dict[str, TaskRecord] = {}
        self.intents: dict[str, IntentRecord] = {}
        self._task_seq = 0
        self._intent_seq = 0
        if path and path.exists():
            self._load()

    def create_intent(
        self,
        raw_text: str,
        *,
        creator: str = "",
        source_msg: str = "",
        key_points: Optional[list[str]] = None,
    ) -> str:
        if not raw_text.strip():
            raise ValueError("intent raw_text cannot be empty")
        self._intent_seq += 1
        intent_id = f"I-{self._intent_seq}"
        self.intents[intent_id] = IntentRecord(
            id=intent_id,
            raw_text=raw_text,
            creator=creator,
            source_msg=source_msg,
            key_points=key_points or [],
        )
        self._persist()
        return intent_id

    def create_task(
        self,
        title: str,
        *,
        assignee: str = "",
        description: str = "",
        creator: str = "",
        intent_id: str = "",
    ) -> str:
        if not title.strip():
            raise ValueError("task title cannot be empty")
        if intent_id and intent_id not in self.intents:
            raise ValueError(f"unknown intent_id: {intent_id}")
        self._task_seq += 1
        task_id = f"T-{self._task_seq}"
        self.tasks[task_id] = TaskRecord(
            id=task_id,
            title=title,
            assignee=assignee,
            description=description,
            creator=creator,
            intent_id=intent_id,
        )
        self._persist()
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        task = self.tasks.get(task_id)
        return task.to_dict() if task else None

    def get_intent(self, intent_id: str) -> Optional[dict]:
        intent = self.intents.get(intent_id)
        return intent.to_dict() if intent else None

    def update_task(
        self,
        task_id: str,
        *,
        status: Optional[TaskStatus | str] = None,
        assignee: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        task = self._require_task(task_id)
        if task.status in TERMINAL_STATUSES:
            raise ValueError(f"terminal task cannot be updated: {task.status.value}")
        if task.status == TaskStatus.NEEDS_APPROVAL:
            raise ValueError("task is suspended for approval; use approve() or reject()")

        changed = False
        if status is not None:
            next_status = TaskStatus(status)
            if next_status not in GENERIC_TRANSITIONS[task.status]:
                raise ValueError(f"illegal transition: {task.status.value} -> {next_status.value}")
            task.status = next_status
            task.completed_at = time.time() if next_status in TERMINAL_STATUSES else 0.0
            changed = True
        if assignee is not None:
            task.assignee = assignee
            changed = True
        if title is not None:
            task.title = title
            changed = True
        if description is not None:
            task.description = description
            changed = True
        if changed:
            task.updated_at = time.time()
            self._persist()
        return changed

    def pause_for_approval(
        self,
        task_id: str,
        *,
        note: str,
        awaiting: str = "manager",
        by: str = "",
    ) -> None:
        task = self._require_task(task_id)
        if task.status in TERMINAL_STATUSES:
            raise ValueError("terminal task cannot be paused")
        task.status = TaskStatus.NEEDS_APPROVAL
        task.awaiting = awaiting
        task.approval_note = note
        task.paused_by = by
        task.paused_at = time.time()
        task.updated_at = task.paused_at
        self._persist()

    def approve(self, task_id: str, *, done: bool = False, note: str = "") -> None:
        task = self._require_task(task_id)
        if task.status != TaskStatus.NEEDS_APPROVAL:
            raise ValueError("task is not waiting for approval")
        task.status = TaskStatus.DONE if done else TaskStatus.IN_PROGRESS
        task.awaiting = ""
        task.approval_note = note or task.approval_note
        task.updated_at = time.time()
        task.completed_at = task.updated_at if done else 0.0
        self._persist()

    def reject(self, task_id: str, feedback: str, *, cancel: bool = False) -> None:
        task = self._require_task(task_id)
        if task.status != TaskStatus.NEEDS_APPROVAL:
            raise ValueError("task is not waiting for approval")
        task.status = TaskStatus.CANCELLED if cancel else TaskStatus.IN_PROGRESS
        task.awaiting = ""
        task.approval_note = feedback
        task.updated_at = time.time()
        task.completed_at = task.updated_at if cancel else 0.0
        self._persist()

    def list_tasks(self, *, status: Optional[TaskStatus | str] = None, assignee: str = "") -> list[dict]:
        wanted = TaskStatus(status) if status is not None else None
        result = []
        for task in self.tasks.values():
            if wanted and task.status != wanted:
                continue
            if assignee and task.assignee != assignee:
                continue
            result.append(task.to_dict())
        return result

    def to_dict(self) -> dict:
        return {
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "intents": {k: v.to_dict() for k, v in self.intents.items()},
            "_meta": {"task_seq": self._task_seq, "intent_seq": self._intent_seq},
        }

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task_id: {task_id}")
        return task

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        assert self.path is not None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._task_seq = data.get("_meta", {}).get("task_seq", 0)
        self._intent_seq = data.get("_meta", {}).get("intent_seq", 0)
        for intent_id, raw in data.get("intents", {}).items():
            self.intents[intent_id] = IntentRecord(
                id=raw["id"],
                raw_text=raw["raw_text"],
                creator=raw.get("creator", ""),
                source_msg=raw.get("source_msg", ""),
                key_points=raw.get("key_points", []),
                created_at=raw.get("created_at", 0),
            )
        for task_id, raw in data.get("tasks", {}).items():
            self.tasks[task_id] = TaskRecord(
                id=raw["id"],
                title=raw["title"],
                assignee=raw.get("assignee", ""),
                description=raw.get("description", ""),
                creator=raw.get("creator", ""),
                intent_id=raw.get("intent_id", ""),
                status=TaskStatus(raw.get("status", TaskStatus.PENDING.value)),
                awaiting=raw.get("awaiting", ""),
                approval_note=raw.get("approval_note", ""),
                paused_by=raw.get("paused_by", ""),
                paused_at=raw.get("paused_at", 0),
                created_at=raw.get("created_at", 0),
                updated_at=raw.get("updated_at", 0),
                completed_at=raw.get("completed_at", 0),
            )
