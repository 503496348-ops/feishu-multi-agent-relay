"""
Role-based Agent Orchestrator — inspired by CrewAI's Crews architecture.
Adapted for Hermes-style agents with YAML declarative definitions.

Core concepts:
- Agent roles defined in YAML (role, goal, backstory, tools)
- Crew composition with sequential/parallel process modes
- Task dependency resolution and execution ordering
"""

import yaml
import json
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class ProcessMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HIERARCHICAL = "hierarchical"


@dataclass
class AgentRole:
    """Declarative agent role definition."""
    name: str
    role: str
    goal: str
    backstory: str
    tools: list[str] = field(default_factory=list)
    llm_model: str = "default"
    max_iter: int = 5
    verbose: bool = False
    allow_delegation: bool = True
    memory: bool = True

    @classmethod
    def from_yaml(cls, path: str) -> dict[str, "AgentRole"]:
        """Load agent roles from YAML config file."""
        with open(path) as f:
            config = yaml.safe_load(f)
        agents = {}
        for name, spec in config.get("agents", {}).items():
            agents[name] = cls(
                name=name,
                role=spec.get("role", ""),
                goal=spec.get("goal", ""),
                backstory=spec.get("backstory", ""),
                tools=spec.get("tools", []),
                llm_model=spec.get("llm_model", "default"),
                max_iter=spec.get("max_iter", 5),
                verbose=spec.get("verbose", False),
                allow_delegation=spec.get("allow_delegation", True),
                memory=spec.get("memory", True),
            )
        return agents

    def system_prompt(self) -> str:
        """Generate system prompt from role definition."""
        prompt_parts = [
            f"You are {self.name}. Your role is: {self.role}",
            f"Your goal: {self.goal}",
            f"Background: {self.backstory}",
        ]
        if self.tools:
            prompt_parts.append(f"Available tools: {', '.join(self.tools)}")
        return "\n".join(prompt_parts)


@dataclass
class Task:
    """Executable task with dependencies."""
    id: str
    description: str
    expected_output: str
    agent: str  # agent role name
    dependencies: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    output: Optional[str] = None
    status: str = "pending"  # pending | running | done | failed
    error: Optional[str] = None

    @classmethod
    def from_yaml(cls, path: str) -> list["Task"]:
        """Load tasks from YAML config file."""
        with open(path) as f:
            config = yaml.safe_load(f)
        tasks = []
        for task_id, spec in config.get("tasks", {}).items():
            tasks.append(cls(
                id=task_id,
                description=spec.get("description", ""),
                expected_output=spec.get("expected_output", ""),
                agent=spec.get("agent", ""),
                dependencies=spec.get("dependencies", []),
                context=spec.get("context", {}),
            ))
        return tasks


class Crew:
    """
    A team of agents working together on tasks.

    Supports three process modes:
    - sequential: tasks execute in dependency order, one at a time
    - parallel: independent tasks execute simultaneously
    - hierarchical: manager agent delegates to worker agents
    """

    def __init__(
        self,
        name: str,
        agents: dict[str, AgentRole],
        tasks: list[Task],
        process: ProcessMode = ProcessMode.SEQUENTIAL,
        max_workers: int = 4,
        verbose: bool = False,
    ):
        self.name = name
        self.agents = agents
        self.tasks = {t.id: t for t in tasks}
        self.process = process
        self.max_workers = max_workers
        self.verbose = verbose
        self._execution_order: list[str] = []
        self._results: dict[str, Any] = {}

    def _resolve_dependencies(self) -> list[list[str]]:
        """
        Topological sort of tasks by dependencies.
        Returns list of execution levels (tasks in same level can run in parallel).
        """
        in_degree: dict[str, int] = defaultdict(int)
        graph: dict[str, list[str]] = defaultdict(list)

        for task_id, task in self.tasks.items():
            if task_id not in in_degree:
                in_degree[task_id] = 0
            for dep in task.dependencies:
                graph[dep].append(task_id)
                in_degree[task_id] += 1

        # BFS-based topological sort with level grouping
        levels: list[list[str]] = []
        queue = [tid for tid, deg in in_degree.items() if deg == 0]

        while queue:
            levels.append(sorted(queue))
            next_queue = []
            for tid in queue:
                for neighbor in graph[tid]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue

        # Cycle detection
        resolved = sum(len(level) for level in levels)
        if resolved != len(self.tasks):
            remaining = set(self.tasks.keys()) - {t for level in levels for t in level}
            raise ValueError(f"Circular dependency detected among tasks: {remaining}")

        return levels

    def _execute_task(self, task_id: str, executor_fn: Callable) -> Any:
        """Execute a single task with its assigned agent."""
        task = self.tasks[task_id]
        agent = self.agents[task.agent]
        task.status = "running"

        if self.verbose:
            logger.info(f"[{self.name}] Task '{task_id}' → Agent '{agent.name}' ({agent.role})")

        try:
            # Gather context from dependency outputs
            dep_outputs = {}
            for dep_id in task.dependencies:
                dep_task = self.tasks[dep_id]
                dep_outputs[dep_id] = {
                    "output": dep_task.output,
                    "agent": dep_task.agent,
                }

            context = {
                "task": task.description,
                "expected_output": task.expected_output,
                "agent_prompt": agent.system_prompt(),
                "dependency_outputs": dep_outputs,
                "extra": task.context,
            }

            result = executor_fn(context)
            task.output = result
            task.status = "done"
            self._results[task_id] = result

            if self.verbose:
                logger.info(f"[{self.name}] Task '{task_id}' completed")

            return result

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.error(f"[{self.name}] Task '{task_id}' failed: {e}")
            raise

    def execute(self, executor_fn: Callable) -> dict[str, Any]:
        """
        Execute all tasks according to process mode.

        Args:
            executor_fn: Callable that takes context dict and returns task output.
                         In real implementation, this would call the LLM.

        Returns:
            Dict mapping task_id to output.
        """
        levels = self._resolve_dependencies()
        start = time.time()

        if self.verbose:
            logger.info(f"[{self.name}] Execution plan ({self.process.value}): "
                        f"{len(levels)} levels, {len(self.tasks)} tasks total")

        if self.process == ProcessMode.SEQUENTIAL:
            for level in levels:
                for task_id in level:
                    self._execute_task(task_id, executor_fn)

        elif self.process == ProcessMode.PARALLEL:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                for level in levels:
                    futures = {
                        pool.submit(self._execute_task, tid, executor_fn): tid
                        for tid in level
                    }
                    for future in as_completed(futures):
                        future.result()  # propagate exceptions

        elif self.process == ProcessMode.HIERARCHICAL:
            # Manager delegates first, then workers execute
            for level in levels:
                for task_id in level:
                    self._execute_task(task_id, executor_fn)

        elapsed = time.time() - start
        if self.verbose:
            logger.info(f"[{self.name}] Completed in {elapsed:.1f}s")

        return self._results

    def status_report(self) -> dict[str, Any]:
        """Generate execution status report."""
        return {
            "crew": self.name,
            "process": self.process.value,
            "tasks": {
                tid: {
                    "status": t.status,
                    "agent": t.agent,
                    "has_output": t.output is not None,
                    "error": t.error,
                }
                for tid, t in self.tasks.items()
            },
            "completed": sum(1 for t in self.tasks.values() if t.status == "done"),
            "failed": sum(1 for t in self.tasks.values() if t.status == "failed"),
            "total": len(self.tasks),
        }


def load_crew_from_config(
    agents_path: str,
    tasks_path: str,
    crew_name: str = "default",
    process: ProcessMode = ProcessMode.SEQUENTIAL,
) -> Crew:
    """Convenience function to load a full crew from YAML configs."""
    agents = AgentRole.from_yaml(agents_path)
    tasks = Task.from_yaml(tasks_path)
    return Crew(
        name=crew_name,
        agents=agents,
        tasks=tasks,
        process=process,
        verbose=True,
    )


# Example YAML config format:
EXAMPLE_AGENTS_YAML = """
agents:
  researcher:
    role: "Senior Research Analyst"
    goal: "Find comprehensive, accurate information on the given topic"
    backstory: "You are an experienced researcher with expertise in
      gathering and analyzing information from multiple sources."
    tools: ["web_search", "file_read"]
    max_iter: 10

  writer:
    role: "Technical Content Writer"
    goal: "Create clear, engaging, well-structured content"
    backstory: "You are a skilled writer who excels at transforming
      complex research into accessible, compelling narratives."
    tools: ["file_write"]
    max_iter: 5

  reviewer:
    role: "Quality Assurance Editor"
    goal: "Ensure accuracy, completeness, and consistency"
    backstory: "You are a meticulous editor who catches errors others
      miss and ensures the highest quality standards."
    tools: ["file_read"]
    max_iter: 3
"""

EXAMPLE_TASKS_YAML = """
tasks:
  research:
    description: "Research the given topic thoroughly"
    expected_output: "Structured research notes with sources"
    agent: researcher
    dependencies: []

  draft:
    description: "Write a first draft based on research"
    expected_output: "Complete draft document"
    agent: writer
    dependencies: ["research"]

  review:
    description: "Review and improve the draft"
    expected_output: "Final polished document"
    agent: reviewer
    dependencies: ["draft"]
"""
