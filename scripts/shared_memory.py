"""
荒原序列-BarrenOrder · Shared Agent Memory
=============================================
Persistent shared memory and context management for multi-agent collaboration.

Features:
- Thread-safe shared memory store with TTL
- Namespace isolation per agent + shared namespace
- Context passing between workflow tasks
- Conversation history tracking with summarization
- Memory snapshots for checkpoint/restore
- Full-text search across memory entries
- Automatic cleanup of expired entries

Brand: AtomCollide-智械工坊
"""

from __future__ import annotations

import json
import time
import threading
import uuid
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MemoryScope(str, Enum):
    """Memory namespace scope."""
    GLOBAL = "global"          # shared across all agents
    AGENT = "agent"            # private to a specific agent
    SESSION = "session"        # tied to a conversation session
    WORKFLOW = "workflow"      # tied to a workflow run


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    AGENT = "agent"            # inter-agent messages


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """A single memory entry."""
    key: str
    value: Any
    scope: MemoryScope
    namespace: str                    # agent_id or session_id
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ttl: float = -1                   # seconds, -1 = no expiry
    metadata: dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        if self.ttl < 0:
            return False
        return time.time() > (self.updated_at + self.ttl)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "scope": self.scope.value,
            "namespace": self.namespace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ttl": self.ttl,
            "metadata": self.metadata,
        }


@dataclass
class ConversationMessage:
    """A message in the conversation history."""
    message_id: str
    role: MessageRole
    content: str
    sender_id: str                    # agent_id or "user"
    timestamp: float = field(default_factory=time.time)
    target_agent: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "role": self.role.value,
            "content": self.content,
            "sender_id": self.sender_id,
            "timestamp": self.timestamp,
            "target_agent": self.target_agent,
            "metadata": self.metadata,
        }


@dataclass
class MemorySnapshot:
    """A point-in-time snapshot of memory state for checkpoint/restore."""
    snapshot_id: str
    created_at: float
    entries: dict[str, dict] = field(default_factory=dict)
    conversation_history: list[dict] = field(default_factory=list)
    task_context: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared Memory Store
# ---------------------------------------------------------------------------

class SharedMemory:
    """
    Thread-safe shared memory for multi-agent collaboration.

    Features:
    - Namespace isolation (per-agent private + global shared)
    - TTL-based expiration
    - Context passing between tasks
    - Conversation history with role-based tracking
    - Snapshot/restore for workflow checkpoints
    - Full-text search across entries
    - Disk persistence (JSON)

    Usage:
        memory = SharedMemory(persist_path=Path("memory.json"))
        memory.set("user_query", "分析市场", scope=MemoryScope.GLOBAL)
        memory.add_conversation(MessageRole.USER, "请帮我分析", sender_id="user")
        context = memory.get_task_context()
    """

    def __init__(self, persist_path: Optional[Path] = None, max_history: int = 500):
        self._lock = threading.RLock()
        self._entries: dict[str, MemoryEntry] = {}
        self._conversation: list[ConversationMessage] = []
        self._task_context: dict[str, Any] = {}
        self._persist_path = persist_path
        self._max_history = max_history

        # Load from disk if available
        if persist_path and persist_path.exists():
            self._load_from_disk()

    # ---- Key-Value Memory ----

    def set(
        self,
        key: str,
        value: Any,
        scope: MemoryScope = MemoryScope.GLOBAL,
        namespace: str = "shared",
        ttl: float = -1,
        metadata: Optional[dict] = None,
    ) -> None:
        """Store a value in memory."""
        full_key = self._make_key(scope, namespace, key)
        with self._lock:
            existing = self._entries.get(full_key)
            if existing:
                existing.value = value
                existing.updated_at = time.time()
                existing.ttl = ttl
                if metadata:
                    existing.metadata.update(metadata)
            else:
                self._entries[full_key] = MemoryEntry(
                    key=key, value=value, scope=scope, namespace=namespace,
                    ttl=ttl, metadata=metadata or {},
                )
            self._auto_persist()

    def get(
        self,
        key: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        namespace: str = "shared",
        default: Any = None,
    ) -> Any:
        """Retrieve a value from memory."""
        full_key = self._make_key(scope, namespace, key)
        with self._lock:
            entry = self._entries.get(full_key)
            if entry and not entry.is_expired():
                return entry.value
            if entry and entry.is_expired():
                del self._entries[full_key]
            return default

    def delete(
        self,
        key: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        namespace: str = "shared",
    ) -> bool:
        """Delete a memory entry."""
        full_key = self._make_key(scope, namespace, key)
        with self._lock:
            if full_key in self._entries:
                del self._entries[full_key]
                self._auto_persist()
                return True
            return False

    def list_keys(
        self,
        scope: Optional[MemoryScope] = None,
        namespace: Optional[str] = None,
    ) -> list[str]:
        """List all non-expired keys, optionally filtered."""
        with self._lock:
            self._cleanup_expired()
            result = []
            for full_key, entry in self._entries.items():
                if scope and entry.scope != scope:
                    continue
                if namespace and entry.namespace != namespace:
                    continue
                result.append(entry.key)
            return result

    def search(self, query: str, scope: Optional[MemoryScope] = None) -> list[dict]:
        """Full-text search across memory keys and string values."""
        with self._lock:
            self._cleanup_expired()
            results = []
            query_lower = query.lower()
            for entry in self._entries.values():
                if scope and entry.scope != scope:
                    continue
                # Search in key
                if query_lower in entry.key.lower():
                    results.append(entry.to_dict())
                    continue
                # Search in string values
                if isinstance(entry.value, str) and query_lower in entry.value.lower():
                    results.append(entry.to_dict())
            return results

    def clear_namespace(self, scope: MemoryScope, namespace: str) -> int:
        """Clear all entries in a namespace. Returns count deleted."""
        with self._lock:
            to_delete = [
                k for k, v in self._entries.items()
                if v.scope == scope and v.namespace == namespace
            ]
            for k in to_delete:
                del self._entries[k]
            self._auto_persist()
            return len(to_delete)

    # ---- Task Context ----

    def set_task_context(self, key: str, value: Any) -> None:
        """Store a value in the workflow task context (shared across tasks)."""
        with self._lock:
            self._task_context[key] = value
            self._auto_persist()

    def get_task_context(self, key: Optional[str] = None, default: Any = None) -> Any:
        """Retrieve task context. If key is None, return entire context dict."""
        with self._lock:
            if key is None:
                return dict(self._task_context)
            return self._task_context.get(key, default)

    def update_task_context(self, data: dict) -> None:
        """Bulk update task context."""
        with self._lock:
            self._task_context.update(data)
            self._auto_persist()

    def clear_task_context(self) -> None:
        """Clear all task context."""
        with self._lock:
            self._task_context.clear()
            self._auto_persist()

    # ---- Conversation History ----

    def add_conversation(
        self,
        role: MessageRole,
        content: str,
        sender_id: str,
        target_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ConversationMessage:
        """Add a message to conversation history."""
        msg = ConversationMessage(
            message_id=f"msg_{uuid.uuid4().hex[:10]}",
            role=role,
            content=content,
            sender_id=sender_id,
            target_agent=target_agent,
            metadata=metadata or {},
        )
        with self._lock:
            self._conversation.append(msg)
            # Trim if exceeding max
            if len(self._conversation) > self._max_history:
                self._conversation = self._conversation[-self._max_history:]
            self._auto_persist()
        return msg

    def get_conversation(
        self,
        limit: int = 50,
        role: Optional[MessageRole] = None,
        sender_id: Optional[str] = None,
    ) -> list[dict]:
        """Get recent conversation messages, optionally filtered."""
        with self._lock:
            messages = self._conversation
            if role:
                messages = [m for m in messages if m.role == role]
            if sender_id:
                messages = [m for m in messages if m.sender_id == sender_id]
            return [m.to_dict() for m in messages[-limit:]]

    def get_conversation_summary(self, last_n: int = 20) -> str:
        """Generate a text summary of recent conversation for context injection."""
        with self._lock:
            recent = self._conversation[-last_n:]
            if not recent:
                return "(无对话记录)"

            lines = []
            for msg in recent:
                role_label = {
                    MessageRole.USER: "用户",
                    MessageRole.ASSISTANT: "助手",
                    MessageRole.SYSTEM: "系统",
                    MessageRole.AGENT: f"Agent({msg.sender_id})",
                }.get(msg.role, msg.role.value)

                target_info = f" → {msg.target_agent}" if msg.target_agent else ""
                lines.append(f"[{role_label}{target_info}] {msg.content[:200]}")

            return "\n".join(lines)

    def clear_conversation(self) -> None:
        """Clear conversation history."""
        with self._lock:
            self._conversation.clear()
            self._auto_persist()

    # ---- Snapshot / Restore ----

    def create_snapshot(self, metadata: Optional[dict] = None) -> MemorySnapshot:
        """Create a point-in-time snapshot of the entire memory state."""
        with self._lock:
            snapshot = MemorySnapshot(
                snapshot_id=f"snap_{uuid.uuid4().hex[:10]}",
                created_at=time.time(),
                entries={k: v.to_dict() for k, v in self._entries.items()},
                conversation_history=[m.to_dict() for m in self._conversation],
                task_context=dict(self._task_context),
                metadata=metadata or {},
            )
        return snapshot

    def restore_snapshot(self, snapshot: MemorySnapshot) -> int:
        """Restore memory state from a snapshot. Returns entries restored."""
        with self._lock:
            self._entries.clear()
            for full_key, entry_dict in snapshot.entries.items():
                self._entries[full_key] = MemoryEntry(
                    key=entry_dict["key"],
                    value=entry_dict["value"],
                    scope=MemoryScope(entry_dict["scope"]),
                    namespace=entry_dict["namespace"],
                    created_at=entry_dict["created_at"],
                    updated_at=entry_dict["updated_at"],
                    ttl=entry_dict["ttl"],
                    metadata=entry_dict.get("metadata", {}),
                )
            self._conversation = [
                ConversationMessage(
                    message_id=m["message_id"],
                    role=MessageRole(m["role"]),
                    content=m["content"],
                    sender_id=m["sender_id"],
                    timestamp=m["timestamp"],
                    target_agent=m.get("target_agent"),
                    metadata=m.get("metadata", {}),
                )
                for m in snapshot.conversation_history
            ]
            self._task_context = dict(snapshot.task_context)
            self._auto_persist()
            return len(self._entries)

    def save_snapshot_to_disk(self, path: Path, snapshot: Optional[MemorySnapshot] = None) -> None:
        """Save a snapshot to a JSON file."""
        snap = snapshot or self.create_snapshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "snapshot_id": snap.snapshot_id,
            "created_at": snap.created_at,
            "entries": snap.entries,
            "conversation_history": snap.conversation_history,
            "task_context": snap.task_context,
            "metadata": snap.metadata,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_snapshot_from_disk(self, path: Path) -> MemorySnapshot:
        """Load a snapshot from a JSON file and restore it."""
        data = json.loads(path.read_text(encoding="utf-8"))
        snapshot = MemorySnapshot(**data)
        self.restore_snapshot(snapshot)
        return snapshot

    # ---- Statistics ----

    def stats(self) -> dict:
        """Get memory statistics."""
        with self._lock:
            self._cleanup_expired()
            by_scope: dict[str, int] = {}
            for entry in self._entries.values():
                by_scope[entry.scope.value] = by_scope.get(entry.scope.value, 0) + 1

            return {
                "total_entries": len(self._entries),
                "by_scope": by_scope,
                "conversation_messages": len(self._conversation),
                "task_context_keys": len(self._task_context),
            }

    # ---- Persistence ----

    def persist(self) -> None:
        """Force save to disk."""
        self._auto_persist()

    def _auto_persist(self) -> None:
        """Persist to disk if path is configured."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "entries": {k: v.to_dict() for k, v in self._entries.items()},
                "conversation": [m.to_dict() for m in self._conversation],
                "task_context": self._task_context,
                "saved_at": time.time(),
            }
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[SharedMemory] Persist error: {e}")

    def _load_from_disk(self) -> None:
        """Load state from disk."""
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))

            for full_key, entry_dict in data.get("entries", {}).items():
                self._entries[full_key] = MemoryEntry(
                    key=entry_dict["key"],
                    value=entry_dict["value"],
                    scope=MemoryScope(entry_dict["scope"]),
                    namespace=entry_dict["namespace"],
                    created_at=entry_dict.get("created_at", 0),
                    updated_at=entry_dict.get("updated_at", 0),
                    ttl=entry_dict.get("ttl", -1),
                    metadata=entry_dict.get("metadata", {}),
                )

            for msg_dict in data.get("conversation", []):
                self._conversation.append(ConversationMessage(
                    message_id=msg_dict["message_id"],
                    role=MessageRole(msg_dict["role"]),
                    content=msg_dict["content"],
                    sender_id=msg_dict["sender_id"],
                    timestamp=msg_dict.get("timestamp", 0),
                    target_agent=msg_dict.get("target_agent"),
                    metadata=msg_dict.get("metadata", {}),
                ))

            self._task_context = data.get("task_context", {})
        except Exception as e:
            print(f"[SharedMemory] Load error: {e}")

    # ---- Internal ----

    @staticmethod
    def _make_key(scope: MemoryScope, namespace: str, key: str) -> str:
        return f"{scope.value}:{namespace}:{key}"

    def _cleanup_expired(self) -> None:
        """Remove expired entries."""
        expired = [k for k, v in self._entries.items() if v.is_expired()]
        for k in expired:
            del self._entries[k]


# ---------------------------------------------------------------------------
# Agent Context Builder
# ---------------------------------------------------------------------------

class AgentContextBuilder:
    """
    Build a structured context string for an agent based on memory state.
    Useful for injecting relevant context into agent prompts.
    """

    def __init__(self, memory: SharedMemory, agent_id: str):
        self.memory = memory
        self.agent_id = agent_id

    def build_context(
        self,
        include_global: bool = True,
        include_agent_private: bool = True,
        include_task_context: bool = True,
        include_recent_conversation: int = 10,
    ) -> str:
        """Build a context string for the agent."""
        parts = []

        if include_global:
            global_keys = self.memory.list_keys(scope=MemoryScope.GLOBAL)
            if global_keys:
                entries = []
                for key in global_keys:
                    val = self.memory.get(key, scope=MemoryScope.GLOBAL)
                    entries.append(f"  {key}: {val}")
                parts.append("[全局上下文]\n" + "\n".join(entries))

        if include_agent_private:
            agent_keys = self.memory.list_keys(scope=MemoryScope.AGENT, namespace=self.agent_id)
            if agent_keys:
                entries = []
                for key in agent_keys:
                    val = self.memory.get(key, scope=MemoryScope.AGENT, namespace=self.agent_id)
                    entries.append(f"  {key}: {val}")
                parts.append(f"[Agent {self.agent_id} 私有记忆]\n" + "\n".join(entries))

        if include_task_context:
            ctx = self.memory.get_task_context()
            if ctx:
                entries = [f"  {k}: {v}" for k, v in ctx.items()]
                parts.append("[工作流上下文]\n" + "\n".join(entries))

        if include_recent_conversation > 0:
            summary = self.memory.get_conversation_summary(last_n=include_recent_conversation)
            if summary and summary != "(无对话记录)":
                parts.append(f"[最近对话]\n{summary}")

        return "\n\n".join(parts) if parts else "(无上下文)"


# ---------------------------------------------------------------------------
# Team Experience Store
# ---------------------------------------------------------------------------

@dataclass
class TeamExperienceEntry:
    """Shared team experience item with optional pinning.

    Pinned entries are the always-injected core; unpinned long-tail entries are
    recalled on demand and evicted first when the cap is exceeded.
    """
    id: str
    kind: str
    content: str
    by: str = ""
    ref: str = ""
    pin: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "content": self.content,
            "by": self.by,
            "ref": self.ref,
            "pin": self.pin,
            "created_at": self.created_at,
        }


class TeamExperienceStore:
    """Append-only JSONL team experience store.

    This complements SharedMemory: SharedMemory is structured context; team
    experience is operational wisdom shared across agents.
    """

    def __init__(self, path: Optional[Path] = None, max_entries: int = 200):
        self.path = path
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._entries: list[TeamExperienceEntry] = []
        self._seq = 0
        if path and path.exists():
            self._load()

    def append(self, kind: str, content: str, *, by: str = "", ref: str = "", pin: bool = False) -> TeamExperienceEntry:
        if not content.strip():
            raise ValueError("experience content cannot be empty")
        with self._lock:
            self._seq += 1
            entry = TeamExperienceEntry(
                id=f"E-{self._seq}",
                kind=kind,
                content=content,
                by=by,
                ref=ref,
                pin=pin,
            )
            self._entries.append(entry)
            self._enforce_cap()
            self._persist()
            return entry

    def pinned(self) -> list[dict]:
        with self._lock:
            return [entry.to_dict() for entry in self._entries if entry.pin]

    def recall(self, query: str = "", *, limit: int = 10, include_pinned: bool = False) -> list[dict]:
        query_lower = query.lower().strip()
        with self._lock:
            results: list[TeamExperienceEntry] = []
            for entry in reversed(self._entries):
                if entry.pin and not include_pinned:
                    continue
                haystack = f"{entry.kind}\n{entry.content}\n{entry.by}\n{entry.ref}".lower()
                if not query_lower or query_lower in haystack:
                    results.append(entry)
                if len(results) >= limit:
                    break
            return [entry.to_dict() for entry in results]

    def build_core_prompt(self) -> str:
        pinned = self.pinned()
        if not pinned:
            return ""
        lines = ["[团队固定经验]"]
        for entry in pinned:
            lines.append(f"- {entry['id']} [{entry['kind']}] {entry['content']}")
        return "\n".join(lines)

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_entries": len(self._entries),
                "pinned_entries": sum(1 for e in self._entries if e.pin),
                "max_entries": self.max_entries,
            }

    def _enforce_cap(self) -> None:
        while len(self._entries) > self.max_entries:
            for idx, entry in enumerate(self._entries):
                if not entry.pin:
                    del self._entries[idx]
                    break
            else:
                # All entries are pinned; preserve them rather than deleting core.
                break

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(entry.to_dict(), ensure_ascii=False) for entry in self._entries)
        self.path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")

    def _load(self) -> None:
        if not self.path:
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            entry = TeamExperienceEntry(
                id=raw["id"],
                kind=raw["kind"],
                content=raw["content"],
                by=raw.get("by", ""),
                ref=raw.get("ref", ""),
                pin=raw.get("pin", False),
                created_at=raw.get("created_at", 0),
            )
            self._entries.append(entry)
            try:
                self._seq = max(self._seq, int(entry.id.split("-", 1)[1]))
            except (IndexError, ValueError):
                pass
        self._enforce_cap()


# ---------------------------------------------------------------------------
# CLI Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("荒原序列-BarrenOrder · Shared Memory Demo")
    print("Brand: AtomCollide-智械工坊")
    print("=" * 60)

    mem = SharedMemory()

    # Set global context
    mem.set("user_query", "分析2024年AI Agent市场趋势", scope=MemoryScope.GLOBAL)
    mem.set("group_id", "oc_demo123", scope=MemoryScope.GLOBAL)
    mem.set("secret_key", "bot_a_private_data", scope=MemoryScope.AGENT, namespace="bot_a")

    # Set task context (workflow shared state)
    mem.set_task_context("research_result", "AI Agent市场2024年预计增长45%")
    mem.set_task_context("data_sources", ["Gartner", "IDC", "CB Insights"])

    # Add conversation messages
    mem.add_conversation(MessageRole.USER, "请帮我分析AI Agent市场", sender_id="user")
    mem.add_conversation(MessageRole.AGENT, "收到，我先进行研究", sender_id="bot_a", target_agent="bot_b")
    mem.add_conversation(MessageRole.AGENT, "研究完成，结果如下：...", sender_id="bot_b", target_agent="bot_a")

    # Build context for an agent
    ctx_builder = AgentContextBuilder(mem, "bot_a")
    context = ctx_builder.build_context()
    print(f"\n📋 Context for bot_a:\n{context}")

    # Search
    results = mem.search("AI Agent")
    print(f"\n🔍 Search 'AI Agent': {len(results)} results")

    # Snapshot
    snap = mem.create_snapshot(metadata={"reason": "checkpoint before review"})
    print(f"\n📸 Snapshot: {snap.snapshot_id}")

    # Stats
    print(f"\n📊 Stats: {json.dumps(mem.stats(), ensure_ascii=False, indent=2)}")

    # Save snapshot
    snap_path = Path("/tmp/barren-order_snapshot_demo.json")
    mem.save_snapshot_to_disk(snap_path, snap)
    print(f"\n💾 Snapshot saved to: {snap_path}")
