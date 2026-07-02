"""
Feishu Multi-Agent Relay — Message Router
==========================================

BarrenOrder's zero-LLM router for Feishu multi-bot collaboration.

The router keeps the original capability/priority routing API while adding
runtime guardrails for production multi-agent team operation:

- explicit route decisions with stable reason codes
- manager-only human entry by default
- worker-to-manager return path
- message deduplication
- bot self-loop and cross-team drops
- slash command detection without LLM inference
- circuit breaker for failing agents
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentStatus(str, Enum):
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"
    CIRCUIT_OPEN = "circuit_open"


class AgentRole(str, Enum):
    MANAGER = "manager"
    WORKER = "worker"


class RouteAction(str, Enum):
    DROP = "drop"
    ROUTE = "route"
    SLASH = "slash"
    BROADCAST = "broadcast"


@dataclass
class AgentCard:
    """Agent capability card for routing decisions."""
    agent_id: str
    name: str
    capabilities: list[str] = field(default_factory=list)
    priority: int = 0
    status: AgentStatus = AgentStatus.ONLINE
    failure_count: int = 0
    last_response_time: float = 0  # ms
    circuit_open_until: float = 0  # timestamp
    role: AgentRole = AgentRole.WORKER
    team_id: str = "default"
    open_id: str = ""

    def can_handle(self, keyword: str) -> bool:
        return any(keyword.lower() in cap.lower() for cap in self.capabilities)

    def is_available(self) -> bool:
        if self.status == AgentStatus.CIRCUIT_OPEN:
            if time.time() > self.circuit_open_until:
                self.status = AgentStatus.ONLINE
                self.failure_count = 0
                return True
            return False
        return self.status in (AgentStatus.ONLINE, AgentStatus.BUSY)


@dataclass
class RelayMessage:
    """Message to be routed between agents."""
    message_id: str
    sender_id: str
    content: str
    target_agent: Optional[str] = None  # explicit routing
    keywords: list[str] = field(default_factory=list)
    priority: int = 0
    timestamp: float = field(default_factory=time.time)
    sender_team_id: str = "default"
    mentioned_agents: list[str] = field(default_factory=list)
    is_bot_sender: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    """Observable routing decision.

    `reason` is intentionally stable so monitoring/Blastogene-style dashboards
    can count drop causes without LLM rewriting numbers.
    """
    action: RouteAction
    targets: tuple[str, ...] = ()
    sender: str = ""
    text: str = ""
    msg_id: str = ""
    reason: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def target(self) -> Optional[str]:
        return self.targets[0] if self.targets else None

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "targets": list(self.targets),
            "sender": self.sender,
            "text": self.text,
            "msg_id": self.msg_id,
            "reason": self.reason,
            "created_at": self.created_at,
        }


class MessageRouter:
    """Route messages to the best-fit agent based on team runtime rules."""
    _agents: dict[str, AgentCard] = {}
    _dedup_window: dict[str, float] = {}
    _dedup_ttl: float = 24 * 60 * 60
    _default_manager_id: Optional[str] = None
    _team_id: str = "default"

    @classmethod
    def reset(cls) -> None:
        """Clear process-local router state. Useful for tests and demos."""
        cls._agents = {}
        cls._dedup_window = {}
        cls._default_manager_id = None
        cls._team_id = "default"

    @classmethod
    def configure_team(cls, team_id: str = "default", default_manager_id: Optional[str] = None) -> None:
        cls._team_id = team_id
        cls._default_manager_id = default_manager_id

    @classmethod
    def register_agent(cls, agent: AgentCard):
        cls._agents[agent.agent_id] = agent
        if agent.role == AgentRole.MANAGER and cls._default_manager_id is None:
            cls._default_manager_id = agent.agent_id

    @classmethod
    def decide(cls, message: RelayMessage) -> RoutingDecision:
        """Return an explicit route/drop/slash decision.

        Runtime priority:
        1. reject malformed/duplicate/cross-team/self-loop/empty messages
        2. slash command to manager
        3. explicit target if available
        4. human/unknown sender to manager only
        5. worker messages without explicit target return to manager
        6. capability/priority fallback for manager-originated delegation
        """
        text = (message.content or "").strip()

        if not message.message_id:
            return cls._decision(RouteAction.DROP, message, reason="no_msg_id")
        cls._cleanup_dedup_window()
        if message.message_id in cls._dedup_window:
            return cls._decision(RouteAction.DROP, message, reason="dedup")
        cls._dedup_window[message.message_id] = time.time()

        if message.sender_team_id and message.sender_team_id != cls._team_id:
            return cls._decision(RouteAction.DROP, message, reason="cross_team")

        sender_agent = cls._agents.get(message.sender_id)
        if message.is_bot_sender or sender_agent is not None:
            if message.target_agent == message.sender_id or message.sender_id in message.mentioned_agents:
                return cls._decision(RouteAction.DROP, message, reason="bot_self")

        if not text:
            return cls._decision(RouteAction.DROP, message, reason="empty")

        if cls._is_slash_command(text):
            manager = cls._available_manager()
            targets = (manager,) if manager else ()
            reason = "slash" if manager else "no_manager"
            action = RouteAction.SLASH if manager else RouteAction.DROP
            return cls._decision(action, message, targets=targets, reason=reason)

        if message.target_agent:
            return cls._explicit_decision(message)

        manager = cls._available_manager()

        # Human/unknown user entry always lands on the manager. Workers should
        # not improvise direct user-facing answers unless the manager delegates.
        if sender_agent is None:
            if manager:
                return cls._decision(RouteAction.ROUTE, message, targets=(manager,), reason="manager_entry")
            return cls._decision(RouteAction.DROP, message, reason="no_manager")

        # Worker reports go back to the manager unless explicitly addressed.
        if sender_agent.role == AgentRole.WORKER:
            if manager:
                return cls._decision(RouteAction.ROUTE, message, targets=(manager,), reason="worker_return")
            return cls._decision(RouteAction.DROP, message, reason="agent_no_target")

        # Manager delegation may use capability/priority matching.
        target = cls._capability_target(message, exclude={message.sender_id})
        if target:
            return cls._decision(RouteAction.ROUTE, message, targets=(target,), reason="capability_match")
        return cls._decision(RouteAction.DROP, message, reason="agent_no_target")

    @classmethod
    def route(cls, message: RelayMessage) -> Optional[str]:
        """Backward-compatible API: return first target agent id or None."""
        return cls.decide(message).target

    @classmethod
    def report_failure(cls, agent_id: str):
        agent = cls._agents.get(agent_id)
        if agent:
            agent.failure_count += 1
            if agent.failure_count >= 3:
                agent.status = AgentStatus.CIRCUIT_OPEN
                agent.circuit_open_until = time.time() + 300  # 5min cooldown

    @classmethod
    def status_report(cls) -> dict:
        return {
            aid: {
                "name": a.name,
                "status": a.status.value,
                "role": a.role.value,
                "team_id": a.team_id,
                "capabilities": a.capabilities,
                "failures": a.failure_count,
                "priority": a.priority,
            }
            for aid, a in cls._agents.items()
        }

    @classmethod
    def get_agent(cls, agent_id: str) -> Optional[AgentCard]:
        """Retrieve an agent card by ID."""
        return cls._agents.get(agent_id)

    @classmethod
    def find_agents_by_capability(cls, keyword: str) -> list[AgentCard]:
        """Find all available agents that can handle a given keyword."""
        return [
            a for a in cls._agents.values()
            if a.is_available() and a.can_handle(keyword)
        ]

    @classmethod
    def unregister_agent(cls, agent_id: str) -> bool:
        """Remove an agent from the registry."""
        if agent_id in cls._agents:
            del cls._agents[agent_id]
            if cls._default_manager_id == agent_id:
                cls._default_manager_id = None
            return True
        return False

    @classmethod
    def route_with_context(
        cls,
        message: RelayMessage,
        context: dict,
    ) -> Optional[str]:
        """Route with shared context — enables memory-aware routing."""
        preferred = context.get("preferred_agent")
        if preferred and preferred in cls._agents:
            agent = cls._agents[preferred]
            if agent.is_available():
                # Consume dedup consistently with route().
                decision = cls.decide(RelayMessage(
                    message_id=message.message_id,
                    sender_id=message.sender_id,
                    content=message.content,
                    target_agent=preferred,
                    keywords=message.keywords,
                    priority=message.priority,
                    timestamp=message.timestamp,
                    sender_team_id=message.sender_team_id,
                    mentioned_agents=message.mentioned_agents,
                    is_bot_sender=message.is_bot_sender,
                ))
                return decision.target
        return cls.route(message)

    @classmethod
    def _explicit_decision(cls, message: RelayMessage) -> RoutingDecision:
        agent = cls._agents.get(message.target_agent or "")
        if agent is None:
            return cls._decision(RouteAction.DROP, message, reason="unknown_target")
        if agent.team_id != cls._team_id:
            return cls._decision(RouteAction.DROP, message, reason="cross_team")
        if not agent.is_available():
            return cls._decision(RouteAction.DROP, message, reason="target_unavailable")
        return cls._decision(RouteAction.ROUTE, message, targets=(agent.agent_id,), reason="explicit_target")

    @classmethod
    def _capability_target(cls, message: RelayMessage, exclude: Optional[set[str]] = None) -> Optional[str]:
        exclude = exclude or set()
        candidates: list[tuple[AgentCard, int]] = []
        for agent in cls._agents.values():
            if agent.agent_id in exclude or agent.role == AgentRole.MANAGER:
                continue
            if agent.team_id != cls._team_id or not agent.is_available():
                continue
            matches = sum(1 for kw in message.keywords if agent.can_handle(kw))
            if matches > 0:
                candidates.append((agent, matches))
        if candidates:
            candidates.sort(key=lambda x: (-x[1], -x[0].priority))
            return candidates[0][0].agent_id

        available = [
            a for a in cls._agents.values()
            if a.agent_id not in exclude
            and a.role == AgentRole.WORKER
            and a.team_id == cls._team_id
            and a.is_available()
        ]
        if available:
            available.sort(key=lambda a: -a.priority)
            return available[0].agent_id
        return None

    @classmethod
    def _available_manager(cls) -> Optional[str]:
        manager_id = cls._default_manager_id
        if manager_id:
            manager = cls._agents.get(manager_id)
            if manager and manager.team_id == cls._team_id and manager.is_available():
                return manager.agent_id
        managers = [
            a for a in cls._agents.values()
            if a.role == AgentRole.MANAGER and a.team_id == cls._team_id and a.is_available()
        ]
        managers.sort(key=lambda a: -a.priority)
        return managers[0].agent_id if managers else None

    @staticmethod
    def _is_slash_command(text: str) -> bool:
        return any(re.match(r"^\s*/[\w\-]+", line) for line in text.splitlines())

    @classmethod
    def _cleanup_dedup_window(cls) -> None:
        now = time.time()
        expired = [mid for mid, ts in cls._dedup_window.items() if now - ts > cls._dedup_ttl]
        for mid in expired:
            del cls._dedup_window[mid]

    @staticmethod
    def _decision(
        action: RouteAction,
        message: RelayMessage,
        *,
        targets: tuple[str, ...] = (),
        reason: str = "",
    ) -> RoutingDecision:
        return RoutingDecision(
            action=action,
            targets=targets,
            sender=message.sender_id,
            text=message.content,
            msg_id=message.message_id,
            reason=reason,
        )


if __name__ == "__main__":
    MessageRouter.reset()
    MessageRouter.configure_team(team_id="demo", default_manager_id="老6")
    MessageRouter.register_agent(AgentCard(
        agent_id="老6", name="丞相老六", capabilities=["通用", "飞书", "代码", "分析"],
        priority=10, role=AgentRole.MANAGER, team_id="demo",
    ))
    MessageRouter.register_agent(AgentCard(
        agent_id="爱教授", name="爱教授", capabilities=["教育", "英语", "课程"], priority=8,
        role=AgentRole.WORKER, team_id="demo",
    ))
    MessageRouter.register_agent(AgentCard(
        agent_id="林小黑", name="林小黑", capabilities=["运营", "排期", "数据"], priority=7,
        role=AgentRole.WORKER, team_id="demo",
    ))

    msg = RelayMessage(message_id="test_1", sender_id="user", content="帮我查一下今天的日程", keywords=["日程", "日历"], sender_team_id="demo")
    decision = MessageRouter.decide(msg)
    print(f"路由决策: {json.dumps(decision.to_dict(), ensure_ascii=False, indent=2)}")
    print(f"\nAgent状态: {json.dumps(MessageRouter.status_report(), ensure_ascii=False, indent=2)}")
