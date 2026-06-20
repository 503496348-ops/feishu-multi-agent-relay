"""
荒原序列-BarrenOrder · Workflow Engine
========================================
DAG-based multi-agent workflow orchestration engine.

Features:
- Define workflows as directed acyclic graphs (DAG)
- Sequential, parallel, and conditional branching execution
- Task dependency resolution and topological ordering
- Timeout, retry, and error handling per task
- Integration with MessageRouter for agent dispatch
- Workflow state persistence and resume

Brand: AtomCollide-智械工坊
"""

from __future__ import annotations

import json
import time
import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_DEPS = "waiting_deps"
    RETRYING = "retrying"


class WorkflowStatus(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BranchCondition(str, enum.Enum):
    """Condition operators for conditional branching."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    SUCCESS = "success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class TaskDefinition:
    """A single task node in the workflow DAG."""
    task_id: str
    name: str
    agent_id: Optional[str] = None          # target agent (None = auto-route)
    prompt: str = ""                         # instruction/prompt for the agent
    keywords: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)   # task_ids
    timeout: float = 120.0                   # seconds
    max_retries: int = 2
    retry_delay: float = 5.0                # seconds between retries
    # Conditional branching
    condition: Optional[BranchCondition] = None
    condition_field: str = ""                # JSONPath-like field to check
    condition_value: Any = None
    # Output routing: which tasks to run next based on output
    on_success: list[str] = field(default_factory=list)  # next task_ids
    on_failure: list[str] = field(default_factory=list)  # fallback task_ids
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result of a single task execution."""
    task_id: str
    status: TaskStatus
    output: Any = None
    error: Optional[str] = None
    started_at: float = 0
    finished_at: float = 0
    attempt: int = 1
    agent_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempt": self.attempt,
            "agent_id": self.agent_id,
        }


@dataclass
class WorkflowDefinition:
    """A complete workflow composed of task nodes."""
    workflow_id: str
    name: str
    description: str = ""
    tasks: list[TaskDefinition] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    version: str = "1.0.0"

    def get_task(self, task_id: str) -> Optional[TaskDefinition]:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        return None

    def validate(self) -> list[str]:
        """Validate the DAG — return list of errors (empty = valid)."""
        errors = []
        task_ids = {t.task_id for t in self.tasks}

        for t in self.tasks:
            for dep in t.depends_on:
                if dep not in task_ids:
                    errors.append(f"Task '{t.task_id}' depends on unknown task '{dep}'")
            for nxt in t.on_success + t.on_failure:
                if nxt not in task_ids:
                    errors.append(f"Task '{t.task_id}' references unknown next task '{nxt}'")

        # Cycle detection via DFS
        if self._has_cycle():
            errors.append("Workflow DAG contains a cycle")

        return errors

    def _has_cycle(self) -> bool:
        adj: dict[str, list[str]] = {t.task_id: [] for t in self.tasks}
        for t in self.tasks:
            for dep in t.depends_on:
                adj[dep].append(t.task_id)
            for nxt in t.on_success + t.on_failure:
                adj[t.task_id].append(nxt)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in adj}

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for neighbor in adj.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node] = BLACK
            return False

        for n in adj:
            if color[n] == WHITE:
                if dfs(n):
                    return True
        return False

    def topological_order(self) -> list[str]:
        """Return a valid execution order (ignoring conditional branches)."""
        in_degree: dict[str, int] = {t.task_id: 0 for t in self.tasks}
        adj: dict[str, list[str]] = {t.task_id: [] for t in self.tasks}

        for t in self.tasks:
            for dep in t.depends_on:
                adj[dep].append(t.task_id)
                in_degree[t.task_id] += 1

        queue = [n for n, d in in_degree.items() if d == 0]
        order = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return order

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "name": t.name,
                    "agent_id": t.agent_id,
                    "prompt": t.prompt,
                    "depends_on": t.depends_on,
                    "timeout": t.timeout,
                    "max_retries": t.max_retries,
                    "on_success": t.on_success,
                    "on_failure": t.on_failure,
                }
                for t in self.tasks
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowDefinition":
        """Deserialize a WorkflowDefinition from a dict (e.g. loaded from JSON)."""
        tasks = []
        for td in data.get("tasks", []):
            tasks.append(TaskDefinition(
                task_id=td["task_id"],
                name=td.get("name", td["task_id"]),
                agent_id=td.get("agent_id"),
                prompt=td.get("prompt", ""),
                keywords=td.get("keywords", []),
                depends_on=td.get("depends_on", []),
                timeout=td.get("timeout", 120.0),
                max_retries=td.get("max_retries", 2),
                retry_delay=td.get("retry_delay", 5.0),
                on_success=td.get("on_success", []),
                on_failure=td.get("on_failure", []),
                condition=BranchCondition(td["condition"]) if td.get("condition") else None,
                condition_field=td.get("condition_field", ""),
                condition_value=td.get("condition_value"),
                metadata=td.get("metadata", {}),
            ))
        return cls(
            workflow_id=data["workflow_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            tasks=tasks,
            metadata=data.get("metadata", {}),
            version=data.get("version", "1.0.0"),
        )


@dataclass
class WorkflowRun:
    """A running/past instance of a workflow execution."""
    run_id: str
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.IDLE
    task_results: dict[str, TaskResult] = field(default_factory=dict)
    started_at: float = 0
    finished_at: float = 0
    context: dict = field(default_factory=dict)   # shared context between tasks

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "task_results": {k: v.to_dict() for k, v in self.task_results.items()},
            "context_keys": list(self.context.keys()),
        }


# ---------------------------------------------------------------------------
# Workflow Executor
# ---------------------------------------------------------------------------

# Type alias for the agent dispatch callback
# Signature: (agent_id, prompt, keywords, context) -> (output, error)
AgentDispatchFn = Callable[[Optional[str], str, list[str], dict], tuple[Any, Optional[str]]]


class WorkflowExecutor:
    """
    Execute a WorkflowDefinition by resolving dependencies, dispatching tasks
    to agents, handling retries, and evaluating conditional branches.

    Usage:
        executor = WorkflowExecutor(workflow_def, dispatch_fn=my_dispatch)
        result = executor.run(initial_context={"user_query": "..."})
    """

    def __init__(
        self,
        workflow: WorkflowDefinition,
        dispatch_fn: Optional[AgentDispatchFn] = None,
        state_path: Optional[Path] = None,
    ):
        errors = workflow.validate()
        if errors:
            raise ValueError(f"Invalid workflow: {'; '.join(errors)}")

        self.workflow = workflow
        self.dispatch_fn = dispatch_fn or self._default_dispatch
        self.state_path = state_path

    # ---- public API ----

    def run(self, initial_context: Optional[dict] = None) -> WorkflowRun:
        """Execute the full workflow synchronously."""
        run = WorkflowRun(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            workflow_id=self.workflow.workflow_id,
            status=WorkflowStatus.RUNNING,
            context=dict(initial_context or {}),
            started_at=time.time(),
        )

        self._save_state(run)

        ready = self._get_entry_tasks()
        executed: set[str] = set()

        while ready:
            # Execute all ready tasks (parallel execution for independent tasks)
            batch_results = self._execute_batch(ready, run)

            for task_id, result in batch_results.items():
                run.task_results[task_id] = result
                executed.add(task_id)

            # Determine next tasks based on results
            next_ready: set[str] = set()
            for task_id, result in batch_results.items():
                task_def = self.workflow.get_task(task_id)
                if not task_def:
                    continue

                if result.status == TaskStatus.SUCCESS:
                    next_ready.update(task_def.on_success)
                    # Auto-advance: tasks that depend solely on this one
                    for candidate in self.workflow.tasks:
                        if candidate.task_id in executed:
                            continue
                        if task_id in candidate.depends_on:
                            if all(d in executed for d in candidate.depends_on):
                                next_ready.add(candidate.task_id)
                elif result.status == TaskStatus.FAILED:
                    next_ready.update(task_def.on_failure)
                    # Mark downstream tasks as skipped
                    for candidate in self.workflow.tasks:
                        if task_id in candidate.depends_on and candidate.task_id not in executed:
                            run.task_results[candidate.task_id] = TaskResult(
                                task_id=candidate.task_id,
                                status=TaskStatus.SKIPPED,
                                error=f"Skipped: dependency '{task_id}' failed",
                            )
                            executed.add(candidate.task_id)

            # Filter out already executed
            ready = [t for t in next_ready if t not in executed]

            # Also check: any tasks whose ALL deps are now satisfied
            for candidate in self.workflow.tasks:
                if candidate.task_id in executed:
                    continue
                if candidate.depends_on and all(d in executed for d in candidate.depends_on):
                    # Check if any dependency failed
                    dep_failed = any(
                        run.task_results.get(d, TaskResult(task_id=d, status=TaskStatus.FAILED)).status == TaskStatus.FAILED
                        for d in candidate.depends_on
                    )
                    if not dep_failed and candidate.task_id not in next_ready:
                        next_ready.add(candidate.task_id)

            ready = list(next_ready - executed)

        # Final status
        all_success = all(
            r.status in (TaskStatus.SUCCESS, TaskStatus.SKIPPED)
            for r in run.task_results.values()
        )
        run.status = WorkflowStatus.SUCCESS if all_success else WorkflowStatus.FAILED
        run.finished_at = time.time()

        self._save_state(run)
        return run

    def run_task_only(self, task_id: str, context: Optional[dict] = None) -> TaskResult:
        """Run a single task (for testing/debugging)."""
        task_def = self.workflow.get_task(task_id)
        if not task_def:
            return TaskResult(task_id=task_id, status=TaskStatus.FAILED, error=f"Unknown task: {task_id}")
        run = WorkflowRun(
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            workflow_id=self.workflow.workflow_id,
            context=dict(context or {}),
        )
        return self._execute_task(task_def, run)

    # ---- internal ----

    def _get_entry_tasks(self) -> list[str]:
        """Tasks with no dependencies."""
        return [t.task_id for t in self.workflow.tasks if not t.depends_on]

    def _execute_batch(self, task_ids: list[str], run: WorkflowRun) -> dict[str, TaskResult]:
        """Execute a batch of tasks (sequentially for now; extend to threading)."""
        results: dict[str, TaskResult] = {}
        for tid in task_ids:
            task_def = self.workflow.get_task(tid)
            if not task_def:
                results[tid] = TaskResult(task_id=tid, status=TaskStatus.FAILED, error="Task not found")
                continue
            results[tid] = self._execute_task(task_def, run)
        return results

    def _execute_task(self, task: TaskDefinition, run: WorkflowRun) -> TaskResult:
        """Execute a single task with retry logic."""
        result = TaskResult(task_id=task.task_id, status=TaskStatus.RUNNING, started_at=time.time())

        # Evaluate condition if present
        if task.condition is not None:
            if not self._evaluate_condition(task, run):
                result.status = TaskStatus.SKIPPED
                result.output = "Condition not met"
                result.finished_at = time.time()
                return result

        # Resolve prompt with context interpolation
        resolved_prompt = self._interpolate(task.prompt, run.context)

        last_error = None
        for attempt in range(1, task.max_retries + 1):
            result.attempt = attempt
            result.status = TaskStatus.RUNNING

            try:
                output, error = self.dispatch_fn(
                    task.agent_id,
                    resolved_prompt,
                    task.keywords,
                    run.context,
                )

                if error:
                    last_error = error
                    result.status = TaskStatus.RETRYING
                    result.error = error
                    if attempt < task.max_retries:
                        time.sleep(task.retry_delay)
                        continue
                else:
                    result.status = TaskStatus.SUCCESS
                    result.output = output
                    result.agent_id = task.agent_id
                    # Store output in shared context
                    run.context[f"task_{task.task_id}_output"] = output
                    break

            except Exception as e:
                last_error = str(e)
                result.status = TaskStatus.RETRYING
                result.error = last_error
                if attempt < task.max_retries:
                    time.sleep(task.retry_delay)
                    continue

        if result.status == TaskStatus.RETRYING:
            result.status = TaskStatus.FAILED
            result.error = f"All {task.max_retries} attempts failed. Last error: {last_error}"

        result.finished_at = time.time()
        return result

    def _evaluate_condition(self, task: TaskDefinition, run: WorkflowRun) -> bool:
        """Evaluate the branching condition for a task."""
        if task.condition == BranchCondition.SUCCESS:
            # All deps must have succeeded
            return all(
                run.task_results.get(d, TaskResult(task_id=d, status=TaskStatus.FAILED)).status == TaskStatus.SUCCESS
                for d in task.depends_on
            )
        if task.condition == BranchCondition.FAILED:
            return any(
                run.task_results.get(d, TaskResult(task_id=d, status=TaskStatus.FAILED)).status == TaskStatus.FAILED
                for d in task.depends_on
            )

        # Field-based conditions
        field_value = run.context.get(task.condition_field)
        if field_value is None:
            return False

        if task.condition == BranchCondition.EQUALS:
            return field_value == task.condition_value
        if task.condition == BranchCondition.NOT_EQUALS:
            return field_value != task.condition_value
        if task.condition == BranchCondition.CONTAINS:
            return str(task.condition_value) in str(field_value)
        if task.condition == BranchCondition.GREATER_THAN:
            try:
                return float(field_value) > float(task.condition_value)
            except (TypeError, ValueError):
                return False
        if task.condition == BranchCondition.LESS_THAN:
            try:
                return float(field_value) < float(task.condition_value)
            except (TypeError, ValueError):
                return False

        return True

    @staticmethod
    def _interpolate(template: str, context: dict) -> str:
        """Replace {{key}} placeholders in prompt with context values."""
        result = template
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result

    @staticmethod
    def _default_dispatch(
        agent_id: Optional[str], prompt: str, keywords: list[str], context: dict
    ) -> tuple[Any, Optional[str]]:
        """Default dispatch — logs intent but cannot actually call agents."""
        print(f"[WorkflowEngine] Dispatch to agent={agent_id}, prompt={prompt[:80]}...")
        return {"status": "dispatched", "agent_id": agent_id, "prompt": prompt}, None

    def _save_state(self, run: WorkflowRun) -> None:
        """Persist workflow run state to disk for resume capability."""
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def load_state(state_path: Path) -> Optional[dict]:
        """Load a persisted workflow run state."""
        if state_path.exists():
            return json.loads(state_path.read_text(encoding="utf-8"))
        return None


# ---------------------------------------------------------------------------
# Workflow Builder (convenience API)
# ---------------------------------------------------------------------------

class WorkflowBuilder:
    """Fluent API to build WorkflowDefinition objects."""

    def __init__(self, workflow_id: str, name: str, description: str = ""):
        self._wf = WorkflowDefinition(
            workflow_id=workflow_id, name=name, description=description,
        )

    def add_task(
        self,
        task_id: str,
        name: str,
        prompt: str = "",
        agent_id: Optional[str] = None,
        depends_on: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        on_success: Optional[list[str]] = None,
        on_failure: Optional[list[str]] = None,
        condition: Optional[BranchCondition] = None,
        condition_field: str = "",
        condition_value: Any = None,
        **metadata,
    ) -> "WorkflowBuilder":
        self._wf.tasks.append(TaskDefinition(
            task_id=task_id,
            name=name,
            agent_id=agent_id,
            prompt=prompt,
            keywords=keywords or [],
            depends_on=depends_on or [],
            timeout=timeout,
            max_retries=max_retries,
            on_success=on_success or [],
            on_failure=on_failure or [],
            condition=condition,
            condition_field=condition_field,
            condition_value=condition_value,
            metadata=metadata,
        ))
        return self

    def build(self) -> WorkflowDefinition:
        return self._wf


# ---------------------------------------------------------------------------
# Built-in Workflow Templates
# ---------------------------------------------------------------------------

def create_research_report_workflow(
    researcher_id: str = "researcher",
    writer_id: str = "writer",
    reviewer_id: str = "reviewer",
) -> WorkflowDefinition:
    """
    Template: Research → Write Report → Review
    Demonstrates sequential pipeline with conditional approval.
    """
    return (
        WorkflowBuilder("wf_research_report", "研究-撰写-审核流水线", "三阶段研究报告生成")
        .add_task(
            "research", "信息采集",
            prompt="请对主题进行深入研究，收集关键数据和观点。主题：{{user_query}}",
            agent_id=researcher_id,
            keywords=["研究", "搜索", "数据"],
        )
        .add_task(
            "write", "撰写报告",
            prompt="基于研究结果撰写结构化报告。研究结果：{{task_research_output}}",
            agent_id=writer_id,
            depends_on=["research"],
            keywords=["写作", "报告", "文档"],
        )
        .add_task(
            "review", "审核报告",
            prompt="审核报告质量，给出通过/修改意见。报告：{{task_write_output}}",
            agent_id=reviewer_id,
            depends_on=["write"],
            keywords=["审核", "校对", "合规"],
        )
        .add_task(
            "revise", "修改报告",
            prompt="根据审核意见修改报告。审核意见：{{task_review_output}}",
            agent_id=writer_id,
            depends_on=["review"],
            keywords=["修改", "修订"],
            condition=BranchCondition.CONTAINS,
            condition_field="task_review_output",
            condition_value="修改",
        )
        .build()
    )


def create_parallel_analysis_workflow(
    agents: Optional[dict[str, str]] = None,
) -> WorkflowDefinition:
    """
    Template: Parallel multi-angle analysis → Synthesis
    Demonstrates fan-out/fan-in pattern.
    """
    agents = agents or {"data": "data_analyst", "market": "market_analyst", "tech": "tech_analyst"}
    builder = WorkflowBuilder("wf_parallel_analysis", "并行多维分析", "多Agent同时分析不同维度后综合")

    builder.add_task(
        "distribute", "任务分发",
        prompt="分析需求并准备数据：{{user_query}}",
    )

    for agent_key, agent_id in agents.items():
        builder.add_task(
            f"analyze_{agent_key}", f"{agent_key}维度分析",
            prompt=f"从{agent_key}角度分析问题。原始需求：{{{{user_query}}}}",
            agent_id=agent_id,
            depends_on=["distribute"],
            keywords=[agent_key, "分析"],
        )

    dep_ids = [f"analyze_{k}" for k in agents]
    builder.add_task(
        "synthesize", "综合报告",
        prompt="综合各维度分析结果，形成最终报告。",
        agent_id="synthesizer",
        depends_on=dep_ids,
        keywords=["综合", "汇总"],
    )

    return builder.build()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("荒原序列-BarrenOrder · Workflow Engine Demo")
    print("Brand: AtomCollide-智械工坊")
    print("=" * 60)

    # Demo 1: Research-Report pipeline
    wf = create_research_report_workflow()
    print(f"\n📋 Workflow: {wf.name}")
    print(f"   Tasks: {len(wf.tasks)}")
    print(f"   Validation errors: {wf.validate()}")
    print(f"   Topological order: {wf.topological_order()}")

    executor = WorkflowExecutor(wf)
    run = executor.run(initial_context={"user_query": "2024年AI Agent市场趋势"})
    print(f"\n✅ Run: {run.run_id}")
    print(f"   Status: {run.status.value}")
    for tid, result in run.task_results.items():
        print(f"   [{result.status.value:>10}] {tid} (attempt {result.attempt})")

    # Demo 2: Parallel analysis
    print("\n" + "-" * 60)
    wf2 = create_parallel_analysis_workflow()
    print(f"\n📋 Workflow: {wf2.name}")
    print(f"   Tasks: {len(wf2.tasks)}")
    print(f"   Topological order: {wf2.topological_order()}")

    executor2 = WorkflowExecutor(wf2)
    run2 = executor2.run(initial_context={"user_query": "评估进入东南亚市场的可行性"})
    print(f"\n✅ Run: {run2.run_id}")
    print(f"   Status: {run2.status.value}")
    for tid, result in run2.task_results.items():
        print(f"   [{result.status.value:>10}] {tid} (attempt {result.attempt})")

    # Demo 3: Custom workflow from JSON
    print("\n" + "-" * 60)
    wf3 = WorkflowDefinition.from_dict({
        "workflow_id": "wf_custom",
        "name": "自定义工作流",
        "tasks": [
            {"task_id": "a", "name": "步骤A", "prompt": "执行A", "agent_id": "bot_a", "depends_on": []},
            {"task_id": "b", "name": "步骤B", "prompt": "执行B", "agent_id": "bot_b", "depends_on": ["a"]},
            {"task_id": "c", "name": "步骤C", "prompt": "执行C", "agent_id": "bot_c", "depends_on": ["a"]},
            {"task_id": "d", "name": "汇总D", "prompt": "汇总B和C的结果", "agent_id": "bot_a", "depends_on": ["b", "c"]},
        ],
    })
    print(f"\n📋 Workflow: {wf3.name}")
    print(f"   Validation errors: {wf3.validate()}")
    print(f"   Topological order: {wf3.topological_order()}")
