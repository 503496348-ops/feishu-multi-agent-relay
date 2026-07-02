"""
BarrenOrder runtime watchdog and health verification.

A process being alive is not enough for multi-agent collaboration. This module
checks the PID/cmdline, optional agent status probe, and recent heartbeat age,
then returns an observable health report with reason codes.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True)
class WatchSpec:
    name: str
    pid_file: Path
    expected_cmdline: str
    heartbeat_file: Optional[Path] = None
    max_heartbeat_age: float = 300


@dataclass(frozen=True)
class HealthReport:
    name: str
    status: HealthStatus
    reasons: tuple[str, ...] = ()
    pid: Optional[int] = None
    checked_at: float = field(default_factory=time.time)
    agent_status: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "pid": self.pid,
            "checked_at": self.checked_at,
            "agent_status": self.agent_status,
        }


def read_pid(path: Path) -> Optional[int]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_cmdline(pid: int) -> str:
    proc_path = Path(f"/proc/{pid}/cmdline")
    try:
        if proc_path.exists():
            return proc_path.read_bytes().decode("utf-8", errors="ignore").replace("\0", " ")
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=3)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def verify_health(
    spec: WatchSpec,
    *,
    agent_probe: Optional[Callable[[str], str]] = None,
    now: Optional[float] = None,
) -> HealthReport:
    """Verify PID, expected command line, heartbeat freshness, and agent probe."""
    now = now if now is not None else time.time()
    reasons: list[str] = []
    pid = read_pid(spec.pid_file)
    if pid is None:
        return HealthReport(spec.name, HealthStatus.DOWN, ("missing_pid",), None)
    if not pid_alive(pid):
        return HealthReport(spec.name, HealthStatus.DOWN, ("pid_dead",), pid)
    cmdline = read_cmdline(pid)
    if spec.expected_cmdline and spec.expected_cmdline not in cmdline:
        return HealthReport(spec.name, HealthStatus.DOWN, ("cmdline_mismatch",), pid)

    if spec.heartbeat_file is not None:
        try:
            age = now - spec.heartbeat_file.stat().st_mtime
            if age > spec.max_heartbeat_age:
                reasons.append("heartbeat_stale")
        except OSError:
            reasons.append("heartbeat_missing")

    agent_status = ""
    if agent_probe is not None:
        try:
            agent_status = agent_probe(spec.name)
            if agent_status not in ("idle", "busy", "ready", "healthy"):
                reasons.append(f"agent_{agent_status or 'unknown'}")
        except Exception:
            reasons.append("agent_probe_error")

    status = HealthStatus.DEGRADED if reasons else HealthStatus.HEALTHY
    return HealthReport(spec.name, status, tuple(reasons), pid, agent_status=agent_status)


def summarize_health(reports: list[HealthReport]) -> dict:
    """Compact health summary for dashboards/cards."""
    counts = {status.value: 0 for status in HealthStatus}
    for report in reports:
        counts[report.status.value] += 1
    return {
        "total": len(reports),
        "counts": counts,
        "reports": [report.to_dict() for report in reports],
    }
