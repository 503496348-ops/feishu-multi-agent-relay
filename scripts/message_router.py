"""
Feishu Multi-Agent Relay — Message Router
==========================================
Enhanced message routing for multi-bot collaboration.

Features:
- Priority-based message routing
- Agent capability matching
- Message deduplication
- Circuit breaker for failing agents
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentStatus(str, Enum):
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"
    CIRCUIT_OPEN = "circuit_open"


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


class MessageRouter:
    """Route messages to the best-fit agent based on capabilities."""
    _agents: dict[str, AgentCard] = {}
    _dedup_window: dict[str, float] = {}

    @classmethod
    def register_agent(cls, agent: AgentCard):
        cls._agents[agent.agent_id] = agent

    @classmethod
    def route(cls, message: RelayMessage) -> Optional[str]:
        """Find the best agent for a message.
        
        Priority: explicit target > keyword match > priority ranking
        """
        # Dedup check
        if message.message_id in cls._dedup_window:
            return None
        cls._dedup_window[message.message_id] = time.time()

        # Explicit routing
        if message.target_agent and message.target_agent in cls._agents:
            agent = cls._agents[message.target_agent]
            if agent.is_available():
                return message.target_agent

        # Keyword matching
        candidates = []
        for agent in cls._agents.values():
            if not agent.is_available():
                continue
            matches = sum(1 for kw in message.keywords if agent.can_handle(kw))
            if matches > 0:
                candidates.append((agent, matches))

        if candidates:
            candidates.sort(key=lambda x: (-x[1], -x[0].priority))
            return candidates[0][0].agent_id

        # Fallback: highest priority available agent
        available = [a for a in cls._agents.values() if a.is_available()]
        if available:
            available.sort(key=lambda a: -a.priority)
            return available[0].agent_id

        return None

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
            aid: {"name": a.name, "status": a.status.value, "capabilities": a.capabilities,
                  "failures": a.failure_count, "priority": a.priority}
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
            return True
        return False

    @classmethod
    def route_with_context(
        cls,
 message: RelayMessage,
 context: dict,
 ) -> Optional[str]:
        """Route with shared context — enables memory-aware routing.

        If context contains 'preferred_agent', try that first.
        Falls back to standard routing logic.
        """
        preferred = context.get("preferred_agent")
        if preferred and preferred in cls._agents:
            agent = cls._agents[preferred]
            if agent.is_available():
                return preferred
        return cls.route(message)


if __name__ == "__main__":
    MessageRouter.register_agent(AgentCard(
        agent_id="老6", name="丞相老六", capabilities=["通用", "飞书", "代码", "分析"], priority=10,
    ))
    MessageRouter.register_agent(AgentCard(
        agent_id="爱教授", name="爱教授", capabilities=["教育", "英语", "课程"], priority=8,
    ))
    MessageRouter.register_agent(AgentCard(
        agent_id="林小黑", name="林小黑", capabilities=["运营", "排期", "数据"], priority=7,
    ))

    msg = RelayMessage(message_id="test_1", sender_id="user", content="帮我查一下今天的日程", keywords=["日程", "日历"])
    target = MessageRouter.route(msg)
    print(f"路由结果: {target}")
    print(f"\nAgent状态: {json.dumps(MessageRouter.status_report(), ensure_ascii=False, indent=2)}")
