"""Repository-scoped agent and flow contracts for long-running teams."""
from __future__ import annotations

from dataclasses import dataclass, field
from string import Template
from typing import Any, Mapping


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    allowed_paths: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()


@dataclass
class FlowAction:
    name: str
    agent: str
    input_template: str
    requires_approval: bool = False
    rendered_input: str | None = field(default=None, init=False)

    def render(self, context: Mapping[str, Any]) -> str:
        missing = [part for part in _template_keys(self.input_template) if part not in context]
        if missing:
            raise ValueError(f"missing flow context keys: {', '.join(sorted(missing))}")
        self.rendered_input = Template(self.input_template).safe_substitute({k: str(v) for k, v in context.items()})
        return self.rendered_input


def _template_keys(template: str) -> set[str]:
    keys: set[str] = set()
    for _, named, braced, _ in Template.pattern.findall(template):
        key = named or braced
        if key:
            keys.add(key)
    return keys


def validate_flow(agents: list[AgentSpec], actions: list[FlowAction]) -> list[str]:
    errors: list[str] = []
    agent_names = {agent.name for agent in agents}
    for action in actions:
        if action.agent not in agent_names:
            errors.append(f"action {action.name} references unknown agent {action.agent}")
        if action.requires_approval and "approval_id" not in _template_keys(action.input_template):
            errors.append(f"action {action.name} requires approval but does not bind approval_id")
    return errors
