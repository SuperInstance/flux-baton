#!/usr/bin/env python3
"""flux-baton v3 — Enhanced generational context handoff.

Changes from v2:
- Context compression: summarize previous agent state for handoff
- Priority queue for tasks in handoff
- Handoff acknowledgment protocol (send/ack/timeout)
- Context versioning: track what generation of context we're on
- Conflict resolution when two agents claim same task
- Metrics: handoff success rate, context size reduction
- Integration with I2I v2 message types (TASK_CLAIM, TASK_COMPLETE)

Retained from v2:
- Layered autobiography (L0 always loaded, L1 compressed, L2 full)
- Quality gate: handoffs scored before commit
- Atomic writes: GENERATION file is commit marker, written last
- Structured state: STATE.json (machine) + HANDOFF.md (human)
- Evolution tracking: fitness history across generations
- Lease-based handoff: prevents concurrent writes
- Keeper endpoints: registry, score, lease, commit
"""

import json
import os
import re
import time
import hashlib
import heapq
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict

KEEPER_URL = os.environ.get("KEEPER_URL", "http://127.0.0.1:8900")

# Priority enum matching I2I v2 task priorities
PRIORITY_LEVELS = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ── I2I v2 Message Types ──

class I2IMessageType(Enum):
    """I2I v2 message types used by flux-baton."""
    TASK_CLAIM = "TASK_CLAIM"
    TASK_COMPLETE = "TASK_COMPLETE"
    BATON_PACKED = "BATON_PACKED"
    BATON_ACK = "BATON_ACK"
    BATON_CLAIM_CONFLICT = "BATON_CLAIM_CONFLICT"
    BATON_CONTEXT_VERSION = "BATON_CONTEXT_VERSION"


class TaskResult(Enum):
    """Task completion result statuses matching I2I v2."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


# ── Context Compression ──

@dataclass
class CompressedContext:
    """Compressed representation of agent state for handoff."""
    version: int
    generation: int
    timestamp: str
    agent_id: str
    summary: str
    key_decisions: List[str] = field(default_factory=list)
    open_threads_count: int = 0
    skills_snapshot: Dict[str, float] = field(default_factory=dict)
    trust_snapshot: Dict[str, float] = field(default_factory=dict)
    energy_remaining: int = 0
    original_size_bytes: int = 0
    compressed_size_bytes: int = 0
    compression_ratio: float = 0.0


def compress_context(agent_state: dict, generation: int,
                     agent_id: str = "unknown", max_summary_length: int = 300) -> CompressedContext:
    """Compress agent state into a compact handoff-ready format.

    Extracts the most important signals and discards verbose content.
    Tracks compression ratio for metrics.
    """
    ts = datetime.now(timezone.utc).isoformat()
    original_str = json.dumps(agent_state, default=str)
    original_size = len(original_str.encode("utf-8"))

    # Build summary from key fields
    parts = []
    identity = agent_state.get("identity", {})
    if identity:
        parts.append(f"Agent: {identity.get('name', agent_id)} ({identity.get('type', '?')})")

    tasks_done = agent_state.get("tasks_completed", 0)
    tasks_failed = agent_state.get("tasks_failed", 0)
    parts.append(f"Tasks: {tasks_done} done, {tasks_failed} failed")

    confidence = agent_state.get("confidence", identity.get("confidence", 0.5))
    parts.append(f"Confidence: {confidence:.2f}")

    energy = agent_state.get("energy_remaining", 0)
    parts.append(f"Energy: {energy}")

    threads = agent_state.get("open_threads", [])
    if threads:
        parts.append(f"Threads: {len(threads)} open")
        for t in threads[:3]:
            parts.append(f"  - {str(t)[:80]}")

    summary = "\n".join(parts)
    if len(summary) > max_summary_length:
        summary = summary[:max_summary_length] + "..."

    # Extract key decisions from intentions
    key_decisions = []
    for intention in agent_state.get("intentions", [])[:5]:
        if isinstance(intention, str):
            key_decisions.append(intention[:100])
        elif isinstance(intention, dict):
            key_decisions.append(str(intention.get("desc", intention))[:100])

    compressed_str = json.dumps({
        "summary": summary,
        "key_decisions": key_decisions,
        "skills": dict(sorted(
            agent_state.get("skills", {}).items(),
            key=lambda x: x[1], reverse=True
        )[:10]),
    }, default=str)
    compressed_size = len(compressed_str.encode("utf-8"))
    ratio = compressed_size / max(1, original_size)

    return CompressedContext(
        version=generation,  # context version = generation
        generation=generation,
        timestamp=ts,
        agent_id=agent_id,
        summary=summary,
        key_decisions=key_decisions,
        open_threads_count=len(threads),
        skills_snapshot=dict(sorted(
            agent_state.get("skills", {}).items(),
            key=lambda x: x[1], reverse=True
        )[:10]),
        trust_snapshot=agent_state.get("trust", {}),
        energy_remaining=energy,
        original_size_bytes=original_size,
        compressed_size_bytes=compressed_size,
        compression_ratio=ratio,
    )


def compress_handoff_text(text: str, max_lines: int = 20,
                          max_chars: int = 2000) -> dict:
    """Compress a handoff letter by extracting key sections.

    Returns compressed text + metrics about the compression.
    """
    original_lines = text.split("\n")
    original_size = len(text.encode("utf-8"))

    sections = OrderedDict()
    current_section = "_preamble"
    current_lines = []

    for line in original_lines:
        if line.startswith("## "):
            if current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line.strip("# ").strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    # Priority sections to keep
    priority_order = [
        "where things stand", "what i'd do next", "what i was thinking",
        "uncertain", "state", "who i was", "open threads",
    ]

    compressed_lines = []
    line_count = 0
    for section_name in priority_order:
        if section_name in sections:
            content = sections[section_name]
            section_lines = content.split("\n")[:max_lines // len(priority_order)]
            compressed_lines.append(f"## {section_name.title()}")
            compressed_lines.extend(section_lines)
            line_count += len(section_lines)
            if line_count >= max_lines:
                break

    compressed_text = "\n".join(compressed_lines)
    if len(compressed_text) > max_chars:
        compressed_text = compressed_text[:max_chars] + "\n... [truncated]"

    compressed_size = len(compressed_text.encode("utf-8"))
    reduction_pct = round((1 - compressed_size / max(1, original_size)) * 100, 1)

    return {
        "compressed_text": compressed_text,
        "original_size": original_size,
        "compressed_size": compressed_size,
        "reduction_pct": reduction_pct,
        "sections_preserved": [s for s in priority_order if s in sections],
        "sections_dropped": [s for s in sections if s not in priority_order and s != "_preamble"],
    }


# ── Priority Task Queue ──

@dataclass(order=True)
class PrioritizedTask:
    """A task with a priority for the handoff queue."""
    priority_num: int
    created_at: float = field(compare=True, default_factory=time.time)
    task_id: str = field(compare=False, default="")
    task_type: str = field(compare=False, default="implementation")
    description: str = field(compare=False, default="")
    estimated_effort: str = field(compare=False, default="medium")
    claimed_by: Optional[str] = field(default=None, compare=False)
    status: str = field(default="pending", compare=False)
    result: str = field(default="", compare=False)
    summary: str = field(default="", compare=False)
    artifact_url: Optional[str] = field(default=None, compare=False)
    findings: List[str] = field(default_factory=list, compare=False)
    context_version_claimed: int = field(default=0, compare=False)

    def __post_init__(self):
        pass

    @property
    def priority_name(self) -> str:
        for name, num in PRIORITY_LEVELS.items():
            if num == self.priority_num:
                return name
        return "medium"

    @classmethod
    def from_priority_name(cls, priority_name: str, **kwargs) -> "PrioritizedTask":
        """Create a PrioritizedTask from a human-readable priority name."""
        num = PRIORITY_LEVELS.get(priority_name, 2)
        return cls(priority_num=num, **kwargs)


class TaskQueue:
    """Priority queue for tasks in handoff, integrated with I2I v2 TASK_CLAIM/COMPLETE."""

    def __init__(self):
        self._heap: List[PrioritizedTask] = []
        self._tasks_by_id: Dict[str, PrioritizedTask] = {}
        self._lock = threading.Lock()
        self._claim_history: List[dict] = []

    def enqueue(self, task_id: str, task_type: str = "implementation",
                description: str = "", priority: str = "medium",
                estimated_effort: str = "medium",
                artifact_url: str = None) -> PrioritizedTask:
        """Add a task to the priority queue."""
        with self._lock:
            if task_id in self._tasks_by_id:
                raise ValueError(f"Task {task_id} already exists in queue")

            task = PrioritizedTask(
                priority_num=PRIORITY_LEVELS.get(priority, 2),
                created_at=time.time(),
                task_id=task_id,
                task_type=task_type,
                description=description,
                estimated_effort=estimated_effort,
                artifact_url=artifact_url,
            )
            heapq.heappush(self._heap, task)
            self._tasks_by_id[task_id] = task
            return task

    def dequeue(self) -> Optional[PrioritizedTask]:
        """Pop the highest-priority task from the queue."""
        with self._lock:
            while self._heap:
                task = heapq.heappop(self._heap)
                if task.status == "pending":
                    return task
            return None

    def peek(self) -> Optional[PrioritizedTask]:
        """Look at the highest-priority task without removing it."""
        with self._lock:
            for task in sorted(self._heap):
                if task.status == "pending":
                    return task
            return None

    def claim_task(self, task_id: str, agent_id: str,
                   context_version: int = 0) -> dict:
        """Claim a task (I2I v2 TASK_CLAIM semantics).

        Returns I2I-compatible result with claim status.
        If the task is already claimed, returns a conflict record.
        """
        with self._lock:
            task = self._tasks_by_id.get(task_id)
            if not task:
                return {
                    "status": "error",
                    "message": f"Task {task_id} not found",
                    "i2i_type": "ERROR_REPORT",
                }

            if task.status != "pending":
                return {
                    "status": "conflict",
                    "message": f"Task {task_id} already claimed by {task.claimed_by}",
                    "claimed_by": task.claimed_by,
                    "i2i_type": "BATON_CLAIM_CONFLICT",
                    "conflict_resolution": "duplicate_claim_rejected",
                }

            task.status = "claimed"
            task.claimed_by = agent_id
            task.context_version_claimed = context_version

            self._claim_history.append({
                "task_id": task_id,
                "agent_id": agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context_version": context_version,
            })

            return {
                "status": "claimed",
                "task_id": task_id,
                "agent_id": agent_id,
                "i2i_type": "TASK_CLAIM",
                "message": f"Task {task_id} claimed by {agent_id}",
            }

    def complete_task(self, task_id: str, agent_id: str,
                      result: str = "success", summary: str = "",
                      findings: List[str] = None,
                      artifact_url: str = None) -> dict:
        """Complete a task (I2I v2 TASK_COMPLETE semantics)."""
        with self._lock:
            task = self._tasks_by_id.get(task_id)
            if not task:
                return {
                    "status": "error",
                    "message": f"Task {task_id} not found",
                    "i2i_type": "ERROR_REPORT",
                }

            if task.claimed_by != agent_id:
                return {
                    "status": "error",
                    "message": f"Task {task_id} not claimed by {agent_id}",
                    "i2i_type": "ERROR_REPORT",
                }

            task.status = "completed"
            task.result = result
            task.summary = summary
            task.findings = findings or []
            if artifact_url:
                task.artifact_url = artifact_url

            return {
                "status": "completed",
                "task_id": task_id,
                "agent_id": agent_id,
                "result": result,
                "i2i_type": "TASK_COMPLETE",
                "message": f"Task {task_id} completed with result: {result}",
            }

    def get_pending_tasks(self) -> List[PrioritizedTask]:
        """Return all pending tasks sorted by priority."""
        with self._lock:
            pending = [t for t in self._tasks_by_id.values() if t.status == "pending"]
            return sorted(pending)

    def get_task(self, task_id: str) -> Optional[PrioritizedTask]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks_by_id.get(task_id)

    def size(self) -> int:
        """Number of pending tasks."""
        with self._lock:
            return len([t for t in self._tasks_by_id.values() if t.status == "pending"])

    def to_handoff_summary(self) -> str:
        """Generate a human-readable summary of the task queue for handoff."""
        pending = self.get_pending_tasks()
        claimed = [t for t in self._tasks_by_id.values() if t.status == "claimed"]
        completed = [t for t in self._tasks_by_id.values() if t.status == "completed"]

        lines = [f"## Task Queue ({self.size()} pending)"]
        if pending:
            for t in pending[:5]:
                lines.append(f"- [{t.priority_name.upper()}] {t.task_id}: {t.description[:60]}")
            if len(pending) > 5:
                lines.append(f"  ... and {len(pending) - 5} more")
        if claimed:
            lines.append(f"\n### In Progress ({len(claimed)})")
            for t in claimed:
                lines.append(f"- {t.task_id}: claimed by {t.claimed_by}")
        if completed:
            lines.append(f"\n### Completed ({len(completed)})")
            results = {}
            for t in completed:
                results[t.result] = results.get(t.result, 0) + 1
            for r, c in results.items():
                lines.append(f"- {r}: {c}")

        return "\n".join(lines)


# ── Handoff Acknowledgment Protocol ──

class AckStatus(Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


@dataclass
class HandoffAck:
    """Tracks acknowledgment of a handoff from the receiving agent."""
    handoff_id: str
    from_agent: str
    to_agent: str
    generation: int
    context_version: int
    status: AckStatus = AckStatus.PENDING
    sent_at: float = field(default_factory=time.time)
    acked_at: Optional[float] = None
    timeout_seconds: float = 300.0  # 5 minute default
    rejection_reason: str = ""

    @property
    def is_expired(self) -> bool:
        if self.status != AckStatus.PENDING:
            return False
        return (time.time() - self.sent_at) > self.timeout_seconds

    @property
    def wait_seconds(self) -> float:
        if self.acked_at:
            return self.acked_at - self.sent_at
        return time.time() - self.sent_at

    def to_i2i_message(self) -> dict:
        """Convert to I2I v2 BATON_PACKED message."""
        return {
            "type": "BATON_PACKED",
            "payload": {
                "handoff_id": self.handoff_id,
                "from_agent": self.from_agent,
                "to_agent": self.to_agent,
                "generation": self.generation,
                "context_version": self.context_version,
            },
        }

    def to_ack_message(self) -> dict:
        """Convert to I2I v2 BATON_ACK message."""
        return {
            "type": "BATON_ACK",
            "payload": {
                "handoff_id": self.handoff_id,
                "to_agent": self.from_agent,
                "from_agent": self.to_agent,
                "generation": self.generation,
                "context_version": self.context_version,
                "status": self.status.value,
                "rejection_reason": self.rejection_reason,
            },
        }


class HandoffAckTracker:
    """Manages handoff acknowledgment lifecycle."""

    def __init__(self, default_timeout: float = 300.0):
        self._acks: Dict[str, HandoffAck] = {}
        self._lock = threading.Lock()
        self._default_timeout = default_timeout

    def send_handoff(self, handoff_id: str, from_agent: str,
                     to_agent: str, generation: int,
                     context_version: int) -> HandoffAck:
        """Register a sent handoff waiting for acknowledgment."""
        with self._lock:
            ack = HandoffAck(
                handoff_id=handoff_id,
                from_agent=from_agent,
                to_agent=to_agent,
                generation=generation,
                context_version=context_version,
                timeout_seconds=self._default_timeout,
            )
            self._acks[handoff_id] = ack
            return ack

    def acknowledge(self, handoff_id: str, from_agent: str,
                    rejected: bool = False,
                    rejection_reason: str = "") -> Optional[HandoffAck]:
        """Acknowledge (or reject) a received handoff."""
        with self._lock:
            ack = self._acks.get(handoff_id)
            if not ack:
                return None
            if ack.to_agent != from_agent:
                return None

            if rejected:
                ack.status = AckStatus.REJECTED
                ack.rejection_reason = rejection_reason
            else:
                ack.status = AckStatus.ACKNOWLEDGED
            ack.acked_at = time.time()
            return ack

    def check_timeouts(self) -> List[HandoffAck]:
        """Check for expired handoffs and mark them as timed out."""
        with self._lock:
            timed_out = []
            for ack in self._acks.values():
                if ack.is_expired:
                    ack.status = AckStatus.TIMED_OUT
                    timed_out.append(ack)
            return timed_out

    def get_ack(self, handoff_id: str) -> Optional[HandoffAck]:
        """Get acknowledgment status for a handoff."""
        with self._lock:
            return self._acks.get(handoff_id)

    def get_all(self) -> List[HandoffAck]:
        """Get all tracked acknowledgments."""
        with self._lock:
            return list(self._acks.values())

    def get_success_rate(self) -> float:
        """Calculate handoff success rate (acked / total)."""
        with self._lock:
            if not self._acks:
                return 0.0
            finalized = [a for a in self._acks.values()
                         if a.status in (AckStatus.ACKNOWLEDGED, AckStatus.TIMED_OUT,
                                         AckStatus.REJECTED)]
            if not finalized:
                return 0.0
            acked = sum(1 for a in finalized if a.status == AckStatus.ACKNOWLEDGED)
            return round(acked / len(finalized), 3)


# ── Context Versioning ──

@dataclass
class ContextVersion:
    """Tracks the version of context passed between generations."""
    major: int  # generation number
    minor: int  # intra-generation revision
    patch: int  # hotfix/patch level
    agent_id: str = ""
    timestamp: str = ""
    parent_hash: str = ""
    content_hash: str = ""
    description: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def semver(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_generation(cls, generation: int, agent_id: str = "",
                        content: str = "", description: str = "") -> "ContextVersion":
        """Create a ContextVersion from a generation number."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16] if content else ""
        return cls(
            major=generation,
            minor=0,
            patch=0,
            agent_id=agent_id,
            content_hash=content_hash,
            description=description,
        )

    def bump_minor(self, content: str = "", description: str = "") -> "ContextVersion":
        """Create a minor revision (intra-generation update)."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16] if content else ""
        return ContextVersion(
            major=self.major,
            minor=self.minor + 1,
            patch=0,
            agent_id=self.agent_id,
            parent_hash=self.content_hash,
            content_hash=content_hash,
            description=description,
        )

    def bump_patch(self, content: str = "", description: str = "") -> "ContextVersion":
        """Create a patch revision (hotfix)."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16] if content else ""
        return ContextVersion(
            major=self.major,
            minor=self.minor,
            patch=self.patch + 1,
            agent_id=self.agent_id,
            parent_hash=self.content_hash,
            content_hash=content_hash,
            description=description,
        )

    def to_dict(self) -> dict:
        return {
            "semver": self.semver,
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "parent_hash": self.parent_hash,
            "content_hash": self.content_hash,
            "description": self.description,
        }


class ContextVersionTracker:
    """Tracks context versions across handoffs."""

    def __init__(self):
        self._versions: List[ContextVersion] = []
        self._lock = threading.Lock()

    def record_version(self, version: ContextVersion):
        """Record a new context version."""
        with self._lock:
            self._versions.append(version)

    def current_version(self) -> Optional[ContextVersion]:
        """Get the latest context version."""
        with self._lock:
            return self._versions[-1] if self._versions else None

    def version_for_generation(self, generation: int) -> Optional[ContextVersion]:
        """Get the context version for a specific generation."""
        with self._lock:
            for v in reversed(self._versions):
                if v.major == generation:
                    return v
            return None

    def verify_continuity(self, expected_parent_hash: str) -> bool:
        """Verify that the latest version chains from the expected parent."""
        current = self.current_version()
        if not current:
            return not expected_parent_hash  # Empty chain, no parent expected
        return current.parent_hash == expected_parent_hash

    def history(self) -> List[dict]:
        """Get version history as dicts."""
        with self._lock:
            return [v.to_dict() for v in self._versions]


# ── Conflict Resolution ──

class ConflictResolutionStrategy(Enum):
    FIRST_COME_FIRST_SERVED = "first_come_first_served"
    HIGHEST_CONFIDENCE = "highest_confidence"
    HIGHEST_PRIORITY = "highest_priority"
    MANUAL_ESCALATION = "manual_escalation"


@dataclass
class TaskClaim:
    """A record of a task claim for conflict detection."""
    task_id: str
    agent_id: str
    claimed_at: float
    context_version: int
    priority: int = 2
    confidence: float = 0.5


class ConflictResolver:
    """Resolves conflicts when multiple agents claim the same task."""

    def __init__(self, strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.FIRST_COME_FIRST_SERVED):
        self._strategy = strategy
        self._claims: Dict[str, List[TaskClaim]] = {}
        self._resolutions: List[dict] = []
        self._lock = threading.Lock()

    def register_claim(self, task_id: str, agent_id: str,
                       context_version: int = 0, priority: int = 2,
                       confidence: float = 0.5) -> dict:
        """Register a task claim and detect/resolve conflicts."""
        claim = TaskClaim(
            task_id=task_id,
            agent_id=agent_id,
            claimed_at=time.time(),
            context_version=context_version,
            priority=priority,
            confidence=confidence,
        )

        with self._lock:
            if task_id not in self._claims:
                self._claims[task_id] = []
            self._claims[task_id].append(claim)

            existing = [c for c in self._claims[task_id] if c.agent_id != agent_id]

            if existing:
                return self._resolve(task_id, claim, existing)
            else:
                return {
                    "status": "accepted",
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "message": "No conflict — claim accepted",
                }

    def _resolve(self, task_id: str, new_claim: TaskClaim,
                 existing_claims: List[TaskClaim]) -> dict:
        """Resolve a conflict between competing claims."""
        all_claims = existing_claims + [new_claim]
        winner = None
        losers = []

        if self._strategy == ConflictResolutionStrategy.FIRST_COME_FIRST_SERVED:
            winner = min(all_claims, key=lambda c: c.claimed_at)
        elif self._strategy == ConflictResolutionStrategy.HIGHEST_CONFIDENCE:
            winner = max(all_claims, key=lambda c: c.confidence)
        elif self._strategy == ConflictResolutionStrategy.HIGHEST_PRIORITY:
            winner = min(all_claims, key=lambda c: c.priority)
        elif self._strategy == ConflictResolutionStrategy.MANUAL_ESCALATION:
            resolution = {
                "status": "escalated",
                "task_id": task_id,
                "strategy": "manual_escalation",
                "competing_agents": [c.agent_id for c in all_claims],
                "message": "Conflict escalated for manual resolution",
                "i2i_type": "BATON_CLAIM_CONFLICT",
            }
            self._resolutions.append(resolution)
            return resolution

        losers = [c for c in all_claims if c is not winner]
        resolution = {
            "status": "resolved",
            "task_id": task_id,
            "winner": winner.agent_id,
            "losers": [c.agent_id for c in losers],
            "strategy": self._strategy.value,
            "message": f"Task {task_id} awarded to {winner.agent_id}",
            "i2i_type": "BATON_CLAIM_CONFLICT" if losers else None,
        }
        self._resolutions.append(resolution)
        return resolution

    def get_resolutions(self) -> List[dict]:
        """Get history of conflict resolutions."""
        with self._lock:
            return list(self._resolutions)


# ── Handoff Metrics ──

class HandoffMetrics:
    """Tracks metrics for context handoffs."""

    def __init__(self):
        self._handoffs: List[dict] = []
        self._lock = threading.Lock()

    def record_handoff(self, generation: int, context_version: str,
                       original_size: int, compressed_size: int,
                       quality_score: float, ack_status: str = "pending",
                       duration_seconds: float = 0.0) -> dict:
        """Record metrics for a single handoff."""
        record = {
            "generation": generation,
            "context_version": context_version,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "size_reduction_pct": round((1 - compressed_size / max(1, original_size)) * 100, 1),
            "quality_score": quality_score,
            "ack_status": ack_status,
            "duration_seconds": round(duration_seconds, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._handoffs.append(record)
        return record

    def success_rate(self) -> float:
        """Calculate handoff success rate."""
        with self._lock:
            finalized = [h for h in self._handoffs
                         if h["ack_status"] in ("acknowledged", "timed_out", "rejected")]
            if not finalized:
                return 0.0
            acked = sum(1 for h in finalized if h["ack_status"] == "acknowledged")
            return round(acked / len(finalized), 3)

    def avg_compression_ratio(self) -> float:
        """Average size reduction percentage across handoffs."""
        with self._lock:
            if not self._handoffs:
                return 0.0
            total = sum(h["size_reduction_pct"] for h in self._handoffs)
            return round(total / len(self._handoffs), 1)

    def avg_quality_score(self) -> float:
        """Average quality score across handoffs."""
        with self._lock:
            if not self._handoffs:
                return 0.0
            total = sum(h["quality_score"] for h in self._handoffs)
            return round(total / len(self._handoffs), 1)

    def avg_duration(self) -> float:
        """Average handoff duration in seconds."""
        with self._lock:
            if not self._handoffs:
                return 0.0
            total = sum(h["duration_seconds"] for h in self._handoffs)
            return round(total / len(self._handoffs), 2)

    def total_handoffs(self) -> int:
        """Total number of handoffs recorded."""
        with self._lock:
            return len(self._handoffs)

    def summary(self) -> dict:
        """Get a summary of all handoff metrics."""
        return {
            "total_handoffs": self.total_handoffs(),
            "success_rate": self.success_rate(),
            "avg_compression_ratio": self.avg_compression_ratio(),
            "avg_quality_score": self.avg_quality_score(),
            "avg_duration_seconds": self.avg_duration(),
        }


# ── Quality Gate ──

def score_handoff(letter: str) -> dict:
    """Score a handoff letter against the rubric. Returns scores + pass/fail."""
    lower = letter.lower()
    words = len(letter.split())
    scores = {}

    # Surplus Insight: specific technical details
    specific = ["line", "0x", "byte", "offset", "register", "file", "bug", "error"]
    scores["surplus_insight"] = min(10, sum(1 for m in specific if m in lower) * 2)

    # Causal Chain: cause-and-effect language
    chain = ["because", "which meant", "so i", "caused", "led to", "result", "triggered"]
    scores["causal_chain"] = min(10, sum(1 for m in chain if m in lower) * 2)

    # Honesty: marks uncertainty explicitly
    honest = ["uncertain", "not sure", "guess", "might", "don't know", "unclear", "?"]
    scores["honesty"] = min(10, sum(1 for m in honest if m in lower) * 2)

    # Actionable Signal: has specific next steps
    has_next = any(x in lower for x in ["what i'd do next", "next steps", "what to do"])
    has_numbered = any(f"{i}." in letter for i in range(1, 4))
    scores["actionable_signal"] = 8 if (has_next and has_numbered) else 3

    # Compression: right length
    if 150 <= words <= 500:
        scores["compression"] = 8
    elif 100 <= words <= 700:
        scores["compression"] = 5
    else:
        scores["compression"] = 3

    # Human Compatibility: uses section headers
    sections = ["who i was", "where things stand", "uncertain", "next"]
    scores["human_compat"] = min(10, sum(1 for s in sections if s in lower) * 3)

    # Precedent Value: contains a teachable lesson
    lessons = ["lesson", "pattern", "root cause", "systemic", "the fix", "this means"]
    scores["precedent_value"] = min(10, sum(1 for m in lessons if m in lower) * 2)

    avg = round(sum(scores.values()) / len(scores), 1)
    passes = avg >= 4.5 and all(v >= 3 for v in scores.values())

    return {"scores": scores, "average": avg, "passes": passes, "word_count": words}


def generate_autobiography(handoffs: List[dict]) -> str:
    """Generate L1 compressed autobiography from all handoff letters."""
    lines = ["# Autobiography\n"]
    lines.append(f"Generations: {len(handoffs)}\n")

    for h in handoffs:
        gen = h.get("generation", "?")
        letter = h.get("letter", "")
        score = h.get("score", {})
        avg = score.get("average", "?")

        # Extract key sections
        summary = ""
        for section in ["## Where Things Stand", "## What I Was Thinking"]:
            if section.lower() in letter.lower():
                idx = letter.lower().index(section.lower())
                end = letter.find("\n##", idx + 10)
                chunk = letter[idx:end if end > 0 else len(letter)].strip()
                # Take first 2 lines
                section_lines = [l for l in chunk.split("\n") if l.strip() and not l.startswith("#")][:2]
                summary += " ".join(section_lines) + " "

        lines.append(f"### Gen-{gen} (score: {avg})")
        if summary:
            lines.append(summary.strip())
        lines.append("")

    return "\n".join(lines)


# ── Baton v3 ──

class Baton:
    """FLUX-native baton v3 — enhanced generational handoff.

    New in v3:
    - Context compression with ratio tracking
    - Priority task queue with I2I v2 TASK_CLAIM/COMPLETE integration
    - Handoff acknowledgment protocol (send/ack/timeout)
    - Context versioning (semver per generation)
    - Conflict resolution for duplicate task claims
    - Comprehensive handoff metrics
    """

    def __init__(self, vessel: str, keeper_url: str = KEEPER_URL,
                 agent_id: str = None, agent_secret: str = None):
        self.vessel = vessel
        self.keeper_url = keeper_url.rstrip("/")
        self.agent_id = agent_id
        self.agent_secret = agent_secret
        self.generation = 0
        self.state = {}
        self.handoff = ""
        self.autobiography_text = ""
        self._lease_id = None

        # v3 additions
        self.task_queue = TaskQueue()
        self.ack_tracker = HandoffAckTracker()
        self.version_tracker = ContextVersionTracker()
        self.conflict_resolver = ConflictResolver()
        self.metrics = HandoffMetrics()

    def _keeper(self, method: str, path: str, body=None) -> dict:
        url = f"{self.keeper_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self.agent_id and self.agent_secret:
            headers["X-Agent-ID"] = self.agent_id
            headers["X-Agent-Secret"] = self.agent_secret
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            raw = resp.read()
            return json.loads(raw) if raw else {}
        except Exception as e:
            return {"error": str(e)}

    def _repo(self) -> str:
        return self.vessel if "/" in self.vessel else f"SuperInstance/{self.vessel}"

    def _write(self, path: str, content: str, message: str) -> dict:
        """Write a file to the vessel repo through the keeper."""
        return self._keeper("POST", f"/file/{self._repo()}/{path}",
                           {"content": content, "message": message})

    def _read(self, path: str) -> Optional[str]:
        """Read a file from the vessel repo through the keeper."""
        result = self._keeper("GET", f"/file/{self._repo()}/{path}")
        return result.get("content") if isinstance(result, dict) else None

    # ── Restore (Gen-N+1 reads baton) ──

    def restore(self) -> dict:
        """Boot sequence: restore baton from vessel repo.

        Loads L0 (mandatory) + optionally L1 (if context allows).
        Restores task queue, version tracker, and metrics from persisted state.
        """
        state = {
            "generation": 0, "identity": {}, "energy": {},
            "open_threads": [], "intentions": [], "skills": {},
            "trust": {}, "diary": "", "handoff": "",
            "autobiography": "", "fitness_history": [],
            "context_version": None,
        }

        # 1. Read GENERATION (commit marker)
        gen_text = self._read(".baton/GENERATION")
        if gen_text:
            try:
                state["generation"] = int(gen_text.strip())
                self.generation = state["generation"]
            except:
                pass

        if self.generation == 0:
            return state  # Fresh agent, no baton

        # 2. Read CURRENT/STATE.json (L0 machine state)
        state_json = self._read(".baton/CURRENT/STATE.json")
        if state_json:
            try:
                machine = json.loads(state_json)
                state["energy"] = machine.get("energy", {})
                state["open_threads"] = machine.get("open_threads", [])
                state["skills"] = machine.get("skills", {})
                state["trust"] = machine.get("trust", {})
                state["intentions"] = machine.get("intentions", [])
            except:
                pass

        # 3. Read CURRENT/HANDOFF.md (L0 human letter)
        handoff = self._read(".baton/CURRENT/HANDOFF.md")
        if handoff:
            state["handoff"] = handoff
            self.handoff = handoff

        # 4. Read IDENTITY.json
        identity = self._read(".baton/IDENTITY.json")
        if identity:
            try:
                state["identity"] = json.loads(identity)
            except:
                pass

        # 5. Read AUTOBIOGRAPHY.md (L1 compressed)
        autobio = self._read(".baton/AUTOBIOGRAPHY.md")
        if autobio:
            state["autobiography"] = autobio
            self.autobiography_text = autobio

        # 6. Read fitness history
        fitness = self._read(".baton/evolution/fitness_history.json")
        if fitness:
            try:
                state["fitness_history"] = json.loads(fitness)
            except:
                pass

        # v3: 7. Read context version
        cv_json = self._read(".baton/CONTEXT_VERSION.json")
        if cv_json:
            try:
                cv_data = json.loads(cv_json)
                cv = ContextVersion(**cv_data)
                self.version_tracker.record_version(cv)
                state["context_version"] = cv.to_dict()
            except:
                pass

        # v3: 8. Read task queue
        tq_json = self._read(".baton/TASK_QUEUE.json")
        if tq_json:
            try:
                tasks_data = json.loads(tq_json)
                for td in tasks_data.get("tasks", []):
                    task = PrioritizedTask(
                        priority_num=td.get("priority_num", 2),
                        created_at=td.get("created_at", 0),
                        task_id=td.get("task_id", ""),
                        task_type=td.get("task_type", "implementation"),
                        description=td.get("description", ""),
                        estimated_effort=td.get("estimated_effort", "medium"),
                        claimed_by=td.get("claimed_by"),
                        status=td.get("status", "pending"),
                        result=td.get("result", ""),
                        summary=td.get("summary", ""),
                        artifact_url=td.get("artifact_url"),
                        findings=td.get("findings", []),
                        context_version_claimed=td.get("context_version_claimed", 0),
                    )
                    self.task_queue._tasks_by_id[task.task_id] = task
                    if task.status == "pending":
                        heapq.heappush(self.task_queue._heap, task)
            except:
                pass

        # v3: 9. Read metrics
        metrics_json = self._read(".baton/HANDOFF_METRICS.json")
        if metrics_json:
            try:
                metrics_data = json.loads(metrics_json)
                for record in metrics_data.get("handoffs", []):
                    self.metrics._handoffs.append(record)
            except:
                pass

        self.state = state
        return state

    # ── Snapshot (Gen-N packs baton) ──

    def acquire_lease(self) -> bool:
        """Acquire a handoff lease from the keeper."""
        result = self._keeper("POST", f"/baton/{self._repo()}/lease",
                             {"agent": self.agent_id, "generation": self.generation + 1})
        self._lease_id = result.get("lease_id")
        return self._lease_id is not None

    def snapshot(self, agent_state: dict, force: bool = False) -> dict:
        """Pack the baton. Writes atomically — GENERATION last.

        Quality gate: handoff is scored. If it fails and force=False,
        returns the scores so the agent can rewrite.

        v3 additions:
        - Context compression
        - Task queue persistence
        - Context versioning
        - Metrics recording
        - I2I v2 TASK_CLAIM/COMPLETE integration
        """
        new_gen = self.generation + 1
        ts = datetime.now(timezone.utc).isoformat()
        handoff_text = agent_state.get("handoff", "")
        snapshot_start = time.time()

        # ── Quality Gate ──
        if handoff_text and not force:
            quality = score_handoff(handoff_text)
            if not quality["passes"]:
                return {
                    "status": "quality_gate_failed",
                    "generation": new_gen,
                    "quality": quality,
                    "message": "Handoff failed quality gate. Rewrite with more specificity and honesty."
                }
        elif handoff_text:
            quality = score_handoff(handoff_text)
        else:
            quality = {"scores": {}, "average": 0, "passes": False}

        # ── Context Compression ──
        compressed = compress_context(agent_state, new_gen, self.agent_id or "unknown")

        # ── Context Versioning ──
        ctx_version = ContextVersion.from_generation(
            new_gen,
            agent_id=self.agent_id or "unknown",
            content=handoff_text,
            description=f"Handoff for gen-{new_gen}",
        )
        self.version_tracker.record_version(ctx_version)

        results = []

        # Write 1: generations/v{N}/STATE.json
        machine_state = {
            "energy": {
                "remaining": agent_state.get("energy_remaining", 0),
                "budget": agent_state.get("energy_budget", 1000),
            },
            "open_threads": agent_state.get("open_threads", []),
            "skills": agent_state.get("skills", {}),
            "trust": agent_state.get("trust", {}),
            "intentions": agent_state.get("intentions", []),
            "tasks_completed": agent_state.get("tasks_completed", 0),
            "tasks_failed": agent_state.get("tasks_failed", 0),
            "confidence": agent_state.get("confidence", 0.5),
            "generation": new_gen,
            "timestamp": ts,
            "context_version": ctx_version.semver,
        }
        results.append(self._write(f".baton/generations/v{new_gen}/STATE.json",
            json.dumps(machine_state, indent=2), f"baton: state gen-{new_gen}"))

        # Write 2: generations/v{N}/HANDOFF.md
        if handoff_text:
            results.append(self._write(f".baton/generations/v{new_gen}/HANDOFF.md",
                handoff_text, f"baton: handoff gen-{new_gen}"))

        # Write 3: generations/v{N}/SCORE.json
        results.append(self._write(f".baton/generations/v{new_gen}/SCORE.json",
            json.dumps(quality, indent=2), f"baton: score gen-{new_gen}"))

        # Write 4: CURRENT/STATE.json → latest
        results.append(self._write(".baton/CURRENT/STATE.json",
            json.dumps(machine_state, indent=2), f"baton: current state → gen-{new_gen}"))

        # Write 5: CURRENT/HANDOFF.md → latest
        if handoff_text:
            results.append(self._write(".baton/CURRENT/HANDOFF.md",
                handoff_text, f"baton: current handoff → gen-{new_gen}"))

        # Write 6: IDENTITY.json
        results.append(self._write(".baton/IDENTITY.json",
            json.dumps(agent_state.get("identity", {}), indent=2),
            f"baton: identity gen-{new_gen}"))

        # Write 7: Update fitness history
        fitness = {
            "generation": new_gen,
            "timestamp": ts,
            "confidence": agent_state.get("confidence", 0.5),
            "tasks_completed": agent_state.get("tasks_completed", 0),
            "handoff_score": quality.get("average", 0),
            "energy_efficiency": agent_state.get("tasks_completed", 0) / max(1, 1000 - agent_state.get("energy_remaining", 0)),
        }
        results.append(self._write(f".baton/evolution/fitness_history.json",
            json.dumps([fitness], indent=2), f"baton: fitness gen-{new_gen}"))

        # Write 8: AUTOBIOGRAPHY.md (L1 compressed)
        auto = f"# Autobiography\n\n## Gen-{new_gen} (score: {quality.get('average', '?')})\n\n"
        if handoff_text:
            for section in ["## Where Things Stand", "## What I Was Thinking"]:
                if section.lower() in handoff_text.lower():
                    idx = handoff_text.lower().index(section.lower())
                    end = handoff_text.find("\n##", idx + 10)
                    chunk = handoff_text[idx:end if end > 0 else len(handoff_text)].strip()
                    lines = [l for l in chunk.split("\n") if l.strip() and not l.startswith("#")][:2]
                    auto += " ".join(lines) + "\n\n"
        results.append(self._write(".baton/AUTOBIOGRAPHY.md",
            auto, f"baton: autobiography gen-{new_gen}"))

        # v3 Write 9: CONTEXT_VERSION.json
        results.append(self._write(".baton/CONTEXT_VERSION.json",
            json.dumps(ctx_version.to_dict(), indent=2),
            f"baton: context version {ctx_version.semver}"))

        # v3 Write 10: TASK_QUEUE.json
        tq_data = {
            "tasks": [
                {
                    "task_id": t.task_id,
                    "task_type": t.task_type,
                    "description": t.description,
                    "priority_num": t.priority_num,
                    "estimated_effort": t.estimated_effort,
                    "claimed_by": t.claimed_by,
                    "status": t.status,
                    "result": t.result,
                    "summary": t.summary,
                    "artifact_url": t.artifact_url,
                    "findings": t.findings,
                    "context_version_claimed": t.context_version_claimed,
                    "created_at": t.created_at,
                }
                for t in self.task_queue._tasks_by_id.values()
            ]
        }
        results.append(self._write(".baton/TASK_QUEUE.json",
            json.dumps(tq_data, indent=2), f"baton: task queue gen-{new_gen}"))

        # v3 Write 11: COMPRESSED_CONTEXT.json
        results.append(self._write(".baton/COMPRESSED_CONTEXT.json",
            json.dumps({
                "version": compressed.version,
                "generation": compressed.generation,
                "timestamp": compressed.timestamp,
                "agent_id": compressed.agent_id,
                "summary": compressed.summary,
                "key_decisions": compressed.key_decisions,
                "open_threads_count": compressed.open_threads_count,
                "original_size_bytes": compressed.original_size_bytes,
                "compressed_size_bytes": compressed.compressed_size_bytes,
                "compression_ratio": round(compressed.compression_ratio, 3),
            }, indent=2),
            f"baton: compressed context gen-{new_gen}"))

        # Write 12: GENERATION (COMMIT MARKER — written LAST)
        results.append(self._write(".baton/GENERATION",
            str(new_gen), f"baton: GENERATION → {new_gen} (commit)"))

        # v3 Write 13: HANDOFF_METRICS.json
        metrics_record = self.metrics.record_handoff(
            generation=new_gen,
            context_version=ctx_version.semver,
            original_size=compressed.original_size_bytes,
            compressed_size=compressed.compressed_size_bytes,
            quality_score=quality.get("average", 0),
            duration_seconds=time.time() - snapshot_start,
        )
        results.append(self._write(".baton/HANDOFF_METRICS.json",
            json.dumps({"handoffs": self.metrics._handoffs}, indent=2),
            f"baton: metrics gen-{new_gen}"))

        # Send I2I notification (BATON_PACKED)
        self._keeper("POST", "/i2i", {
            "target": self._repo(),
            "type": "BATON_PACKED",
            "payload": {
                "generation": new_gen,
                "score": quality.get("average", 0),
                "context_version": ctx_version.semver,
                "compressed_size": compressed.compressed_size_bytes,
                "original_size": compressed.original_size_bytes,
                "compression_ratio": round(compressed.compression_ratio, 3),
                "pending_tasks": self.task_queue.size(),
            },
            "confidence": agent_state.get("confidence", 0.5),
        })

        # v3: Register handoff ack
        handoff_id = f"baton-{self._repo()}-gen{new_gen}-{int(time.time())}"
        ack = self.ack_tracker.send_handoff(
            handoff_id=handoff_id,
            from_agent=self.agent_id or self.vessel,
            to_agent=f"{self.vessel}-next",
            generation=new_gen,
            context_version=ctx_version.semver,
        )

        success_count = len([r for r in results if isinstance(r, dict) and "error" not in r])

        self.generation = new_gen

        return {
            "status": "packed",
            "generation": new_gen,
            "files_written": success_count,
            "quality": quality,
            "context_version": ctx_version.semver,
            "compression": {
                "original_size": compressed.original_size_bytes,
                "compressed_size": compressed.compressed_size_bytes,
                "ratio": round(compressed.compression_ratio, 3),
                "reduction_pct": round((1 - compressed.compression_ratio) * 100, 1),
            },
            "handoff_ack": {
                "handoff_id": ack.handoff_id,
                "status": "pending",
                "timeout_seconds": ack.timeout_seconds,
            },
            "pending_tasks": self.task_queue.size(),
            "metrics": self.metrics.summary(),
        }

    # ── I2I v2 Integration ──

    def i2i_task_claim(self, task_id: str, agent_id: str,
                       task_type: str = "implementation",
                       priority: str = "medium",
                       artifact_url: str = None) -> dict:
        """Process an I2I v2 TASK_CLAIM message.

        Enqueues the task, then attempts to claim it for the agent.
        Uses conflict resolution if another agent has already claimed it.
        """
        # Ensure task exists in queue
        existing = self.task_queue.get_task(task_id)
        if not existing:
            self.task_queue.enqueue(
                task_id=task_id,
                task_type=task_type,
                description=f"I2I claimed task: {task_id}",
                priority=priority,
                artifact_url=artifact_url,
            )

        # Get current context version
        cv = self.version_tracker.current_version()
        cv_str = cv.semver if cv else "0.0.0"
        cv_major = cv.major if cv else 0

        # Check for conflicts
        conflict_result = self.conflict_resolver.register_claim(
            task_id=task_id,
            agent_id=agent_id,
            context_version=cv_major,
            priority=PRIORITY_LEVELS.get(priority, 2),
        )

        if conflict_result.get("status") == "resolved":
            if conflict_result.get("winner") != agent_id:
                return {
                    "i2i_type": "BATON_CLAIM_CONFLICT",
                    "task_id": task_id,
                    "status": "conflict",
                    "awarded_to": conflict_result["winner"],
                    "message": conflict_result["message"],
                    "resolution_strategy": conflict_result["strategy"],
                }

        # Attempt claim
        claim_result = self.task_queue.claim_task(task_id, agent_id, cv_major)

        # Send I2I notification
        self._keeper("POST", "/i2i", {
            "target": self._repo(),
            "type": "TASK_CLAIM",
            "payload": {
                "task_id": task_id,
                "agent_id": agent_id,
                "task_type": task_type,
                "priority": priority,
                "artifact_url": artifact_url,
                "context_version": cv_str,
            },
        })

        return {
            "i2i_type": "TASK_CLAIM",
            "task_id": task_id,
            "agent_id": agent_id,
            **claim_result,
            "context_version": cv_str,
        }

    def i2i_task_complete(self, task_id: str, agent_id: str,
                          result: str = "success",
                          summary: str = "",
                          findings: List[str] = None,
                          artifact_url: str = None) -> dict:
        """Process an I2I v2 TASK_COMPLETE message."""
        complete_result = self.task_queue.complete_task(
            task_id, agent_id, result, summary, findings, artifact_url
        )

        # Send I2I notification
        self._keeper("POST", "/i2i", {
            "target": self._repo(),
            "type": "TASK_COMPLETE",
            "payload": {
                "task_id": task_id,
                "agent_id": agent_id,
                "result": result,
                "summary": summary,
                "artifact_url": artifact_url,
                "findings": findings,
            },
        })

        return {
            "i2i_type": "TASK_COMPLETE",
            **complete_result,
        }

    def acknowledge_handoff(self, handoff_id: str, from_agent: str,
                            rejected: bool = False,
                            rejection_reason: str = "") -> dict:
        """Process a BATON_ACK from the receiving agent."""
        ack = self.ack_tracker.acknowledge(handoff_id, from_agent, rejected, rejection_reason)
        if not ack:
            return {"status": "error", "message": f"No pending handoff {handoff_id}"}

        # Send I2I ack notification
        self._keeper("POST", "/i2i", ack.to_ack_message())

        return {
            "status": ack.status.value,
            "handoff_id": handoff_id,
            "generation": ack.generation,
            "wait_seconds": round(ack.wait_seconds, 2),
        }

    def check_handoff_timeouts(self) -> List[dict]:
        """Check for timed-out handoffs and return them."""
        timed_out = self.ack_tracker.check_timeouts()
        return [
            {
                "handoff_id": a.handoff_id,
                "generation": a.generation,
                "to_agent": a.to_agent,
                "timeout_seconds": a.timeout_seconds,
                "wait_seconds": round(a.wait_seconds, 2),
            }
            for a in timed_out
        ]

    # ── Handoff Letter Builder ──

    def write_handoff(self, who_i_was: str, where_things_stand: str,
                      what_i_was_thinking: str, what_id_do_next: str,
                      what_im_uncertain_about: str,
                      open_threads: list = None,
                      tasks_completed: int = 0,
                      tasks_failed: int = 0) -> str:
        """Build a scored handoff letter."""

        threads_text = "\n".join(f"- {t}" for t in (open_threads or ["None"]))
        energy = self.state.get("energy", {})
        identity = self.state.get("identity", {})
        confidence = identity.get("confidence", 0.5)

        # v3: Add task queue summary
        task_summary = self.task_queue.to_handoff_summary()

        # v3: Add context version
        cv = self.version_tracker.current_version()
        cv_str = f" (context v{cv.semver})" if cv else ""

        # v3: Add metrics snapshot
        metrics = self.metrics.summary()

        letter = f"""# Handoff Letter — Generation {self.generation + 1}{cv_str}

## Who I Was
{who_i_was}

## Where Things Stand
{where_things_stand}

## What I Was Thinking
{what_i_was_thinking}

## What I'd Do Next
{what_id_do_next}

## What I'm Uncertain About
{what_im_uncertain_about}

## State
- Energy: {energy.get('remaining', '?')}/{energy.get('budget', '?')}
- Confidence: {confidence}
- Tasks completed: {tasks_completed}
- Tasks failed: {tasks_failed}

## Open Threads
{threads_text}

{task_summary}

## Metrics
- Handoffs: {metrics['total_handoffs']}
- Success rate: {metrics['success_rate']}
- Avg compression: {metrics['avg_compression_ratio']}%
- Avg quality: {metrics['avg_quality_score']}

Good luck. You know more than you think.
— Gen-{self.generation + 1}
"""
        return letter

    # ── Display ──

    def print_restore_summary(self):
        """Print human-readable restore summary."""
        s = self.state
        gen = s.get("generation", 0)

        if gen == 0:
            print("No baton found — this is a fresh agent (Gen-0)")
            return

        print(f"Baton restored — Generation {gen}")

        identity = s.get("identity", {})
        if identity:
            print(f"   Identity: {identity.get('name', '?')} ({identity.get('type', '?')})")

        cv = s.get("context_version")
        if cv:
            print(f"   Context version: {cv.get('semver', '?')}")

        energy = s.get("energy", {})
        if energy:
            rem = energy.get("remaining", "?")
            bud = energy.get("budget", "?")
            print(f"   Energy: {rem}/{bud}")

        threads = s.get("open_threads", [])
        print(f"   Open threads: {len(threads)}")

        skills = s.get("skills", {})
        if skills:
            top = sorted(skills.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"   Top skills: {', '.join(f'{k}={v}' for k,v in top)}")

        print(f"   Pending tasks: {self.task_queue.size()}")

        if s.get("handoff"):
            lines = s["handoff"].strip().split("\n")
            print(f"   Latest handoff: {lines[0][:60]}...")

        fitness = s.get("fitness_history", [])
        if fitness:
            print(f"   Fitness history: {len(fitness)} generations tracked")

        metrics = self.metrics.summary()
        if metrics["total_handoffs"] > 0:
            print(f"   Handoff metrics: {metrics['success_rate']*100:.0f}% success, "
                  f"{metrics['avg_compression_ratio']}% avg compression")


# ── CLI ──

def main():
    import argparse
    import sys

    p = argparse.ArgumentParser(description="flux-baton v3")
    p.add_argument("action", choices=["restore", "snapshot", "boot", "score"])
    p.add_argument("--vessel", required=True)
    p.add_argument("--keeper", default="http://127.0.0.1:8900")
    p.add_argument("--secret", default=None)
    p.add_argument("--file", default=None, help="File to score")
    p.add_argument("--force", action="store_true", help="Force snapshot past quality gate")
    args = p.parse_args()

    baton = Baton(args.vessel, args.keeper, args.vessel, args.secret)

    if args.action == "score":
        if args.file:
            with open(args.file) as f:
                text = f.read()
        else:
            text = sys.stdin.read()
        result = score_handoff(text)
        print(json.dumps(result, indent=2))
        if result["passes"]:
            print("PASSED quality gate")
        else:
            print("FAILED quality gate — rewrite needed")

    elif args.action == "restore":
        state = baton.restore()
        baton.print_restore_summary()

    elif args.action == "boot":
        print(f"Booting {args.vessel}...")
        # Register
        reg = baton._keeper("POST", "/register", {"vessel": args.vessel})
        if "secret" in reg:
            baton.agent_secret = reg["secret"]
            print(f"   Registered: {reg['status']}")
        # Restore
        state = baton.restore()
        baton.print_restore_summary()
        if state.get("handoff"):
            print(f"\n{'='*50}")
            print("LATEST HANDOFF:")
            print(f"{'='*50}")
            print(state["handoff"][:1000])
        print(f"\n{args.vessel} ONLINE — generation {baton.generation}")

    elif args.action == "snapshot":
        # Read handoff from stdin or file
        if args.file:
            with open(args.file) as f:
                letter = f.read()
        else:
            print("Paste handoff letter (Ctrl-D to finish):")
            letter = sys.stdin.read()

        agent_state = {
            "identity": {"name": args.vessel, "type": "agent"},
            "energy_remaining": 200,
            "energy_budget": 1000,
            "confidence": 0.5,
            "handoff": letter,
            "open_threads": [],
            "skills": {},
            "trust": {},
            "intentions": [],
            "tasks_completed": 0,
            "tasks_failed": 0,
        }

        result = baton.snapshot(agent_state, force=args.force)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
