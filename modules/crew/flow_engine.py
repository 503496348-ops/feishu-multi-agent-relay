"""
Flow Engine — event-driven workflow orchestration inspired by CrewAI Flows.
Supports @start, @listen, @router decorators for complex triggering.

Core concepts:
- Decorator-based event wiring
- Logical operators (and_, or_) for multi-event triggers
- State management with typed flow state
- Router functions for conditional branching
"""

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional
from collections import defaultdict
from functools import wraps

logger = logging.getLogger(__name__)


class TriggerType(Enum):
    START = "start"
    LISTEN = "listen"
    ROUTER = "router"


@dataclass
class FlowEvent:
    """An event in the flow execution."""
    name: str
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None


@dataclass
class FlowState:
    """Mutable state shared across flow steps."""
    data: dict[str, Any] = field(default_factory=dict)
    history: list[FlowEvent] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def update(self, updates: dict[str, Any]) -> None:
        self.data.update(updates)

    def record(self, event: FlowEvent) -> None:
        self.history.append(event)


class FlowStep:
    """Wrapper for a flow step function with its trigger configuration."""

    def __init__(
        self,
        fn: Callable,
        trigger_type: TriggerType,
        events: list[str],
        operator: str = "and",  # "and" or "or"
    ):
        self.fn = fn
        self.trigger_type = trigger_type
        self.events = events
        self.operator = operator
        self.name = fn.__name__
        self.executed = False
        self.result: Any = None

    def should_fire(self, fired_events: set[str]) -> bool:
        """Check if this step's trigger conditions are met."""
        if self.trigger_type == TriggerType.START:
            return True
        if self.operator == "and":
            return all(e in fired_events for e in self.events)
        elif self.operator == "or":
            return any(e in fired_events for e in self.events)
        return False


class Flow:
    """
    Event-driven workflow engine.

    Usage:
        flow = Flow("my_workflow")

        @flow.start()
        def init(state):
            state.set("initialized", True)
            return "init_done"

        @flow.listen("init_done")
        def process(state):
            return "processed"

        @flow.listen("processed")
        @flow.router()
        def decide(state):
            if state.get("needs_review"):
                return "review"
            return "publish"

        @flow.listen("review")
        def review(state):
            return "reviewed"

        flow.run()
    """

    def __init__(self, name: str, max_steps: int = 100):
        self.name = name
        self.max_steps = max_steps
        self.state = FlowState()
        self.steps: dict[str, FlowStep] = {}
        self._event_handlers: dict[str, list[str]] = defaultdict(list)
        self._start_steps: list[str] = []

    def start(self) -> Callable:
        """Decorator: marks a step as a flow entry point."""
        def decorator(fn: Callable) -> Callable:
            step = FlowStep(fn, TriggerType.START, [], "and")
            self.steps[step.name] = step
            self._start_steps.append(step.name)

            @wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    def listen(self, *events: str, operator: str = "and") -> Callable:
        """Decorator: step fires when specified events have occurred."""
        def decorator(fn: Callable) -> Callable:
            step = FlowStep(fn, TriggerType.LISTEN, list(events), operator)
            self.steps[step.name] = step
            for event in events:
                self._event_handlers[event].append(step.name)

            @wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    def router(self) -> Callable:
        """Decorator: marks a step as a router (returns event name to fire next)."""
        def decorator(fn: Callable) -> Callable:
            # Find the step for this function
            if fn.__name__ in self.steps:
                self.steps[fn.__name__].trigger_type = TriggerType.ROUTER

            @wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    def run(self, initial_context: Optional[dict] = None) -> FlowState:
        """
        Execute the flow from start steps.

        Args:
            initial_context: Optional initial state data.

        Returns:
            The final FlowState after execution.
        """
        if initial_context:
            self.state.update(initial_context)

        fired_events: set[str] = set()
        execution_queue: list[str] = list(self._start_steps)
        step_count = 0

        while execution_queue and step_count < self.max_steps:
            step_name = execution_queue.pop(0)
            step = self.steps[step_name]

            if step.executed:
                continue

            # Check trigger conditions
            if not step.should_fire(fired_events):
                continue

            # Execute the step
            step_count += 1
            event = FlowEvent(name=step_name, source=step_name)
            self.state.record(event)

            try:
                logger.info(f"[{self.name}] Executing: {step_name}")
                result = step.fn(self.state)
                step.result = result
                step.executed = True

                # Fire the event
                fired_events.add(step_name)

                # If this is a router, the result is the next event to fire
                if step.trigger_type == TriggerType.ROUTER and isinstance(result, str):
                    fired_events.add(result)
                    # Queue handlers for the routed event
                    for handler in self._event_handlers.get(result, []):
                        if handler not in [s for s in execution_queue]:
                            execution_queue.append(handler)
                else:
                    # Queue handlers for this step's output event
                    for handler in self._event_handlers.get(step_name, []):
                        if handler not in [s for s in execution_queue]:
                            execution_queue.append(handler)

            except Exception as e:
                logger.error(f"[{self.name}] Step '{step_name}' failed: {e}")
                step.executed = True  # Don't retry
                fired_events.add(f"{step_name}_error")

        return self.state

    def execution_summary(self) -> dict[str, Any]:
        """Generate execution summary."""
        return {
            "flow": self.name,
            "steps": {
                name: {
                    "executed": step.executed,
                    "trigger": step.trigger_type.value,
                    "events": step.events,
                    "has_result": step.result is not None,
                }
                for name, step in self.steps.items()
            },
            "state_keys": list(self.state.data.keys()),
            "history_length": len(self.state.history),
        }


# Convenience decorators for common patterns
def and_(*events: str) -> dict:
    """Helper: all events must fire."""
    return {"events": list(events), "operator": "and"}


def or_(*events: str) -> dict:
    """Helper: any event must fire."""
    return {"events": list(events), "operator": "or"}


# === Example Usage ===
EXAMPLE_FLOW = """
from flow_engine import Flow

flow = Flow("content_pipeline")

@flow.start()
def analyze_topic(state):
    topic = state.get("topic", "untitled")
    state.set("analysis", {"topic": topic, "subtopics": ["intro", "body", "conclusion"]})
    return "analyzed"

@flow.listen("analyzed")
def research(state):
    analysis = state.get("analysis")
    state.set("research_data", f"Research for {analysis['topic']}")
    return "researched"

@flow.listen("researched")
def write_draft(state):
    state.set("draft", "First draft content...")
    return "drafted"

@flow.listen("drafted")
@flow.router()
def quality_check(state):
    draft = state.get("draft", "")
    if len(draft) > 100:
        return "approved"
    return "needs_revision"

@flow.listen("needs_revision")
def revise(state):
    state.set("draft", "Revised and improved draft...")
    return "revised"

@flow.listen("approved")
def publish(state):
    state.set("published", True)
    return "published"

result = flow.run({"topic": "AI Agent Architecture"})
print(flow.execution_summary())
"""
