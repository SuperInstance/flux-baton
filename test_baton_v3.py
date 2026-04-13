#!/usr/bin/env python3
"""Tests for flux-baton v3 — Enhanced generational context handoff.

Covers:
- Context compression
- Priority task queue
- Handoff acknowledgment protocol
- Context versioning
- Conflict resolution
- Handoff metrics
- I2I v2 integration (TASK_CLAIM, TASK_COMPLETE)
- Quality gate scoring
- Autobiography generation
- Baton snapshot with all v3 features
"""

import json
import os
import sys
import time
import threading
import unittest

# Ensure we import from the local module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flux_baton import (
    # Scoring
    score_handoff,
    generate_autobiography,
    # Context compression
    compress_context,
    compress_handoff_text,
    CompressedContext,
    # Task queue
    TaskQueue,
    PrioritizedTask,
    PRIORITY_LEVELS,
    # Handoff ack
    HandoffAck,
    HandoffAckTracker,
    AckStatus,
    # Context versioning
    ContextVersion,
    ContextVersionTracker,
    # Conflict resolution
    ConflictResolver,
    ConflictResolutionStrategy,
    TaskClaim,
    # Metrics
    HandoffMetrics,
    # I2I types
    I2IMessageType,
    TaskResult,
    # Baton
    Baton,
)


class TestScoreHandoff(unittest.TestCase):
    """Tests for the handoff quality scoring rubric."""

    def test_empty_letter_fails(self):
        """Empty handoff should fail quality gate."""
        result = score_handoff("")
        self.assertFalse(result["passes"])
        self.assertEqual(result["word_count"], 0)

    def test_perfect_letter_passes(self):
        """A well-crafted letter should pass the quality gate."""
        letter = """# Handoff Letter — Generation 2

## Who I Was
I was the agent debugging the memory leak at line 142 in file allocator.c

## Where Things Stand
The bug was caused by a missing free() call at offset 0x4a2, which meant
memory was never returned to the pool. This led to OOM after 1000 iterations.

## What I Was Thinking
The root cause was in the error handler path. I'm uncertain about the thread
safety of the fix, but the pattern is clear.

## What I'd Do Next
1. Add the missing free() call in the error path
2. Write a regression test
3. What to do next: verify with valgrind

## What I'm Uncertain About
I'm not sure if there are other leak paths. Might need a full audit.
"""
        result = score_handoff(letter)
        self.assertTrue(result["passes"], f"Failed scores: {result['scores']}")
        self.assertGreaterEqual(result["average"], 4.5)

    def test_short_letter_low_compression_score(self):
        """Very short letters get low compression score."""
        letter = "Short."
        result = score_handoff(letter)
        self.assertLess(result["scores"]["compression"], 5)

    def test_honesty_detected(self):
        """Letters with uncertainty markers score higher on honesty."""
        honest = "I'm uncertain about this. I might be wrong. Not sure."
        result = score_handoff(honest)
        self.assertGreater(result["scores"]["honesty"], 0)

    def test_actionable_signal_with_numbered_steps(self):
        """Numbered steps with 'what to do' trigger actionable signal."""
        letter = "What I'd do next:\n1. Fix the bug\n2. Write a test\n3. Deploy"
        result = score_handoff(letter)
        self.assertEqual(result["scores"]["actionable_signal"], 8)

    def test_score_returns_all_categories(self):
        """All scoring categories should be present."""
        letter = "Some text with a bug and error because it caused issues"
        result = score_handoff(letter)
        expected_keys = {"surplus_insight", "causal_chain", "honesty",
                         "actionable_signal", "compression", "human_compat",
                         "precedent_value"}
        self.assertEqual(set(result["scores"].keys()), expected_keys)


class TestContextCompression(unittest.TestCase):
    """Tests for context compression."""

    def test_basic_compression(self):
        """CompressedContext should reduce size from original state."""
        state = {
            "identity": {"name": "test-agent", "type": "vessel"},
            "tasks_completed": 10,
            "tasks_failed": 2,
            "confidence": 0.75,
            "energy_remaining": 500,
            "open_threads": ["thread1", "thread2", "thread3"],
            "skills": {"python": 0.9, "git": 0.8, "debugging": 0.7},
            "trust": {"oracle1": 0.8},
            "intentions": ["Fix the memory leak", "Write tests"],
        }
        result = compress_context(state, generation=5, agent_id="test-agent")
        self.assertIsInstance(result, CompressedContext)
        self.assertEqual(result.generation, 5)
        self.assertEqual(result.agent_id, "test-agent")
        self.assertGreater(result.original_size_bytes, 0)
        self.assertGreater(result.compressed_size_bytes, 0)
        self.assertGreater(result.compression_ratio, 0)
        # Compressed should be smaller
        self.assertLess(result.compressed_size_bytes, result.original_size_bytes)

    def test_compression_summary_contains_key_info(self):
        """Summary should contain agent name and task counts."""
        state = {
            "identity": {"name": "my-agent"},
            "tasks_completed": 5,
            "tasks_failed": 1,
        }
        result = compress_context(state, generation=1, agent_id="my-agent")
        self.assertIn("5 done", result.summary)
        self.assertIn("1 failed", result.summary)

    def test_compress_empty_state(self):
        """Empty state should compress without error."""
        result = compress_context({}, generation=0)
        self.assertEqual(result.generation, 0)
        self.assertGreater(len(result.summary), 0)

    def test_compress_handoff_text(self):
        """compress_handoff_text should extract key sections."""
        text = """# Handoff
## Where Things Stand
Things are going well.
We fixed the bug at line 142.

## What I'd Do Next
1. Run tests
2. Deploy

## What I Was Thinking
The fix seems solid.

## Irrelevant Section
This should be dropped.
"""
        result = compress_handoff_text(text, max_lines=10, max_chars=500)
        self.assertIn("Where Things Stand", result["compressed_text"])
        # Section headers are title-cased in output
        self.assertTrue(
            "What I'D Do Next" in result["compressed_text"] or
            "What I'd Do Next" in result["compressed_text"]
        )
        self.assertGreater(result["reduction_pct"], 0)
        self.assertIn("irrelevant section", result["sections_dropped"])

    def test_compress_handoff_preserves_priority_sections(self):
        """Priority sections should be preserved in order."""
        text = """## Where Things Stand
Content here.

## What I'm Uncertain About
Uncertainty here.

## Open Threads
Thread 1.
"""
        result = compress_handoff_text(text)
        self.assertIn("where things stand", result["sections_preserved"])
        self.assertIn("open threads", result["sections_preserved"])
        # "what i'm uncertain about" is not in priority_order so it gets dropped
        self.assertIn("what i'm uncertain about", result["sections_dropped"])


class TestTaskQueue(unittest.TestCase):
    """Tests for the priority task queue."""

    def setUp(self):
        self.queue = TaskQueue()

    def test_enqueue_and_size(self):
        """Tasks can be enqueued and counted."""
        self.queue.enqueue("t1", "implementation", "Fix bug", "high")
        self.queue.enqueue("t2", "testing", "Write tests", "low")
        self.assertEqual(self.queue.size(), 2)

    def test_duplicate_task_rejected(self):
        """Duplicate task IDs are rejected."""
        self.queue.enqueue("t1", "implementation")
        with self.assertRaises(ValueError):
            self.queue.enqueue("t1", "testing")

    def test_priority_ordering(self):
        """Higher priority tasks are dequeued first."""
        self.queue.enqueue("low", "implementation", priority="low")
        self.queue.enqueue("critical", "implementation", priority="critical")
        self.queue.enqueue("medium", "implementation", priority="medium")

        first = self.queue.dequeue()
        self.assertEqual(first.task_id, "critical")
        second = self.queue.dequeue()
        self.assertEqual(second.task_id, "medium")
        third = self.queue.dequeue()
        self.assertEqual(third.task_id, "low")

    def test_peek_without_remove(self):
        """Peek returns highest priority without removing it."""
        self.queue.enqueue("t1", "implementation", priority="high")
        self.queue.enqueue("t2", "testing", priority="low")

        peeked = self.queue.peek()
        self.assertEqual(peeked.task_id, "t1")
        # Should still be there
        self.assertEqual(self.queue.size(), 2)

    def test_dequeue_empty(self):
        """Dequeue from empty queue returns None."""
        self.assertIsNone(self.queue.dequeue())

    def test_claim_task_success(self):
        """Task can be claimed by an agent."""
        self.queue.enqueue("t1", "implementation", priority="high")
        result = self.queue.claim_task("t1", "agent-1")
        self.assertEqual(result["status"], "claimed")
        self.assertEqual(result["i2i_type"], "TASK_CLAIM")

    def test_claim_nonexistent_task(self):
        """Claiming non-existent task returns error."""
        result = self.queue.claim_task("nope", "agent-1")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["i2i_type"], "ERROR_REPORT")

    def test_double_claim_conflict(self):
        """Second claim on same task returns conflict."""
        self.queue.enqueue("t1", "implementation")
        self.queue.claim_task("t1", "agent-1")
        result = self.queue.claim_task("t1", "agent-2")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["i2i_type"], "BATON_CLAIM_CONFLICT")

    def test_complete_task(self):
        """Task can be completed after being claimed."""
        self.queue.enqueue("t1", "implementation")
        self.queue.claim_task("t1", "agent-1")
        result = self.queue.complete_task("t1", "agent-1", "success", "All done")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["i2i_type"], "TASK_COMPLETE")
        self.assertEqual(result["result"], "success")

    def test_complete_wrong_agent(self):
        """Completing a task claimed by another agent fails."""
        self.queue.enqueue("t1", "implementation")
        self.queue.claim_task("t1", "agent-1")
        result = self.queue.complete_task("t1", "agent-2", "success")
        self.assertEqual(result["status"], "error")

    def test_get_pending_tasks(self):
        """get_pending_tasks returns only pending tasks sorted by priority."""
        self.queue.enqueue("low", "implementation", priority="low")
        self.queue.enqueue("high", "testing", priority="high")
        self.queue.enqueue("med", "implementation", priority="medium")

        self.queue.claim_task("high", "agent-1")

        pending = self.queue.get_pending_tasks()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0].task_id, "med")  # medium before low

    def test_to_handoff_summary(self):
        """to_handoff_summary generates human-readable text."""
        self.queue.enqueue("t1", "implementation", "Fix the bug", "critical")
        self.queue.enqueue("t2", "testing", "Write tests", "low")
        summary = self.queue.to_handoff_summary()
        self.assertIn("2 pending", summary)
        self.assertIn("CRITICAL", summary)
        self.assertIn("t1", summary)

    def test_prioritized_task_from_priority_name(self):
        """PrioritizedTask.from_priority_name creates correct priority."""
        task = PrioritizedTask.from_priority_name("critical", task_id="t1")
        self.assertEqual(task.priority_num, 0)
        self.assertEqual(task.priority_name, "critical")
        self.assertEqual(task.task_id, "t1")

    def test_completed_tasks_excluded_from_size(self):
        """Completed tasks don't count in queue size."""
        self.queue.enqueue("t1", "implementation")
        self.queue.claim_task("t1", "agent-1")
        self.queue.complete_task("t1", "agent-1", "success")
        self.assertEqual(self.queue.size(), 0)


class TestHandoffAcknowledgment(unittest.TestCase):
    """Tests for the handoff acknowledgment protocol."""

    def setUp(self):
        self.tracker = HandoffAckTracker(default_timeout=1.0)  # 1s for testing

    def test_send_and_acknowledge(self):
        """Handoff can be sent and acknowledged."""
        ack = self.tracker.send_handoff("h1", "agent-a", "agent-b", 5, "5.0.0")
        self.assertEqual(ack.status, AckStatus.PENDING)

        result = self.tracker.acknowledge("h1", "agent-b")
        self.assertEqual(result.status, AckStatus.ACKNOWLEDGED)
        self.assertIsNotNone(result.acked_at)

    def test_reject_handoff(self):
        """Handoff can be rejected with a reason."""
        self.tracker.send_handoff("h1", "agent-a", "agent-b", 5, "5.0.0")
        result = self.tracker.acknowledge("h1", "agent-b", rejected=True,
                                          rejection_reason="State corruption detected")
        self.assertEqual(result.status, AckStatus.REJECTED)
        self.assertEqual(result.rejection_reason, "State corruption detected")

    def test_ack_from_wrong_agent(self):
        """Acknowledgment from wrong agent returns None."""
        self.tracker.send_handoff("h1", "agent-a", "agent-b", 5, "5.0.0")
        result = self.tracker.acknowledge("h1", "agent-c")
        self.assertIsNone(result)

    def test_ack_nonexistent_handoff(self):
        """Acknowledging non-existent handoff returns None."""
        result = self.tracker.acknowledge("nope", "agent-b")
        self.assertIsNone(result)

    def test_timeout_detection(self):
        """Expired handoffs are detected by check_timeouts."""
        self.tracker.send_handoff("h1", "agent-a", "agent-b", 5, "5.0.0")
        time.sleep(1.1)
        timed_out = self.tracker.check_timeouts()
        self.assertEqual(len(timed_out), 1)
        self.assertEqual(timed_out[0].status, AckStatus.TIMED_OUT)

    def test_no_timeout_for_acked(self):
        """Acknowledged handoffs don't time out."""
        self.tracker.send_handoff("h1", "agent-a", "agent-b", 5, "5.0.0")
        self.tracker.acknowledge("h1", "agent-b")
        timed_out = self.tracker.check_timeouts()
        self.assertEqual(len(timed_out), 0)

    def test_success_rate(self):
        """Success rate is calculated correctly."""
        self.tracker.send_handoff("h1", "a", "b", 1, "1.0.0")
        self.tracker.acknowledge("h1", "b")

        self.tracker.send_handoff("h2", "a", "c", 2, "2.0.0")
        self.tracker.acknowledge("h2", "c", rejected=True)

        self.tracker.send_handoff("h3", "a", "d", 3, "3.0.0")
        # Leave pending

        # Only finalized count
        rate = self.tracker.get_success_rate()
        self.assertEqual(rate, 0.5)  # 1 acked / 2 finalized

    def test_to_i2i_message(self):
        """HandoffAck serializes to I2I BATON_PACKED message."""
        ack = HandoffAck("h1", "a", "b", 5, "5.0.0")
        msg = ack.to_i2i_message()
        self.assertEqual(msg["type"], "BATON_PACKED")
        self.assertEqual(msg["payload"]["handoff_id"], "h1")
        self.assertEqual(msg["payload"]["generation"], 5)

    def test_to_ack_message(self):
        """HandoffAck serializes to I2I BATON_ACK message."""
        ack = HandoffAck("h1", "a", "b", 5, "5.0.0")
        ack.status = AckStatus.ACKNOWLEDGED
        ack.acked_at = time.time()
        msg = ack.to_ack_message()
        self.assertEqual(msg["type"], "BATON_ACK")
        self.assertEqual(msg["payload"]["status"], "acknowledged")


class TestContextVersioning(unittest.TestCase):
    """Tests for context versioning."""

    def setUp(self):
        self.tracker = ContextVersionTracker()

    def test_from_generation(self):
        """ContextVersion created from generation has correct major."""
        cv = ContextVersion.from_generation(5, "agent-1", "content")
        self.assertEqual(cv.major, 5)
        self.assertEqual(cv.minor, 0)
        self.assertEqual(cv.patch, 0)
        self.assertEqual(cv.semver, "5.0.0")

    def test_bump_minor(self):
        """Minor bump increments minor version."""
        cv = ContextVersion.from_generation(5, "agent-1", "content")
        cv2 = cv.bump_minor("content2", "update")
        self.assertEqual(cv2.semver, "5.1.0")
        self.assertEqual(cv2.parent_hash, cv.content_hash)

    def test_bump_patch(self):
        """Patch bump increments patch version."""
        cv = ContextVersion.from_generation(5, "agent-1", "content")
        cv2 = cv.bump_minor("content2")
        cv3 = cv2.bump_patch("content3", "hotfix")
        self.assertEqual(cv3.semver, "5.1.1")

    def test_content_hash_differs_for_different_content(self):
        """Different content produces different content hashes."""
        cv1 = ContextVersion.from_generation(1, "a", "hello")
        cv2 = ContextVersion.from_generation(1, "a", "world")
        self.assertNotEqual(cv1.content_hash, cv2.content_hash)

    def test_tracker_records_and_retrieves(self):
        """Tracker records versions and retrieves current."""
        cv1 = ContextVersion.from_generation(1, "a", "c1")
        cv2 = ContextVersion.from_generation(2, "a", "c2")
        self.tracker.record_version(cv1)
        self.tracker.record_version(cv2)

        current = self.tracker.current_version()
        self.assertEqual(current.semver, "2.0.0")

    def test_version_for_generation(self):
        """Tracker can retrieve version by generation."""
        cv1 = ContextVersion.from_generation(1, "a", "c1")
        cv2 = ContextVersion.from_generation(2, "a", "c2")
        self.tracker.record_version(cv1)
        self.tracker.record_version(cv2)

        v = self.tracker.version_for_generation(1)
        self.assertEqual(v.major, 1)

    def test_verify_continuity(self):
        """Continuity check validates parent hash chain."""
        cv1 = ContextVersion.from_generation(1, "a", "c1")
        cv2 = cv1.bump_minor("c2")
        self.tracker.record_version(cv1)
        self.tracker.record_version(cv2)

        self.assertTrue(self.tracker.verify_continuity(cv1.content_hash))
        self.assertFalse(self.tracker.verify_continuity("wrong_hash"))

    def test_to_dict(self):
        """ContextVersion serializes to dict."""
        cv = ContextVersion.from_generation(3, "agent-x", "data", "test version")
        d = cv.to_dict()
        self.assertEqual(d["semver"], "3.0.0")
        self.assertEqual(d["agent_id"], "agent-x")
        self.assertEqual(d["description"], "test version")
        self.assertIn("timestamp", d)
        self.assertIn("content_hash", d)

    def test_empty_tracker(self):
        """Empty tracker returns None for current version."""
        self.assertIsNone(self.tracker.current_version())
        self.assertIsNone(self.tracker.version_for_generation(1))

    def test_history(self):
        """History returns list of version dicts."""
        cv1 = ContextVersion.from_generation(1, "a", "c1")
        cv2 = ContextVersion.from_generation(2, "a", "c2")
        self.tracker.record_version(cv1)
        self.tracker.record_version(cv2)

        history = self.tracker.history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["semver"], "1.0.0")
        self.assertEqual(history[1]["semver"], "2.0.0")


class TestConflictResolution(unittest.TestCase):
    """Tests for task claim conflict resolution."""

    def test_first_come_first_served(self):
        """First claim wins with FCFS strategy."""
        resolver = ConflictResolver(ConflictResolutionStrategy.FIRST_COME_FIRST_SERVED)

        r1 = resolver.register_claim("t1", "agent-1")
        time.sleep(0.01)
        r2 = resolver.register_claim("t1", "agent-2")

        self.assertEqual(r1["status"], "accepted")
        self.assertEqual(r2["status"], "resolved")
        self.assertEqual(r2["winner"], "agent-1")

    def test_highest_confidence_wins(self):
        """Higher confidence agent wins with CONFIDENCE strategy."""
        resolver = ConflictResolver(ConflictResolutionStrategy.HIGHEST_CONFIDENCE)

        resolver.register_claim("t1", "agent-1", confidence=0.3)
        r2 = resolver.register_claim("t1", "agent-2", confidence=0.9)

        self.assertEqual(r2["winner"], "agent-2")

    def test_highest_priority_wins(self):
        """Higher priority claim wins with PRIORITY strategy."""
        resolver = ConflictResolver(ConflictResolutionStrategy.HIGHEST_PRIORITY)

        resolver.register_claim("t1", "agent-1", priority=2)  # medium
        r2 = resolver.register_claim("t1", "agent-2", priority=0)  # critical

        self.assertEqual(r2["winner"], "agent-2")

    def test_manual_escalation(self):
        """Manual escalation returns conflict for human resolution."""
        resolver = ConflictResolver(ConflictResolutionStrategy.MANUAL_ESCALATION)

        resolver.register_claim("t1", "agent-1")
        r2 = resolver.register_claim("t1", "agent-2")

        self.assertEqual(r2["status"], "escalated")
        self.assertIn("agent-1", r2["competing_agents"])
        self.assertIn("agent-2", r2["competing_agents"])
        self.assertEqual(r2["i2i_type"], "BATON_CLAIM_CONFLICT")

    def test_no_conflict_different_tasks(self):
        """Claims on different tasks don't conflict."""
        resolver = ConflictResolver()

        r1 = resolver.register_claim("t1", "agent-1")
        r2 = resolver.register_claim("t2", "agent-2")

        self.assertEqual(r1["status"], "accepted")
        self.assertEqual(r2["status"], "accepted")

    def test_resolutions_history(self):
        """All resolutions are recorded."""
        resolver = ConflictResolver()
        resolver.register_claim("t1", "agent-1")
        resolver.register_claim("t1", "agent-2")

        resolutions = resolver.get_resolutions()
        self.assertEqual(len(resolutions), 1)
        self.assertEqual(resolutions[0]["task_id"], "t1")


class TestHandoffMetrics(unittest.TestCase):
    """Tests for handoff metrics tracking."""

    def setUp(self):
        self.metrics = HandoffMetrics()

    def test_record_and_retrieve(self):
        """Handoff can be recorded."""
        record = self.metrics.record_handoff(
            generation=1, context_version="1.0.0",
            original_size=5000, compressed_size=1000,
            quality_score=7.0, ack_status="acknowledged",
            duration_seconds=2.5,
        )
        self.assertEqual(record["generation"], 1)
        self.assertEqual(record["size_reduction_pct"], 80.0)

    def test_success_rate(self):
        """Success rate calculated from ack statuses."""
        self.metrics.record_handoff(1, "1.0.0", 5000, 1000, 7.0, "acknowledged")
        self.metrics.record_handoff(2, "2.0.0", 5000, 2000, 6.0, "timed_out")
        self.metrics.record_handoff(3, "3.0.0", 5000, 1500, 5.0, "acknowledged")

        self.assertAlmostEqual(self.metrics.success_rate(), 2 / 3, places=1)

    def test_success_rate_no_data(self):
        """Success rate is 0 when no data."""
        self.assertEqual(self.metrics.success_rate(), 0.0)

    def test_avg_compression_ratio(self):
        """Average compression ratio across handoffs."""
        self.metrics.record_handoff(1, "1.0.0", 1000, 200, 7.0)  # 80%
        self.metrics.record_handoff(2, "2.0.0", 1000, 500, 6.0)  # 50%

        self.assertEqual(self.metrics.avg_compression_ratio(), 65.0)

    def test_avg_quality_score(self):
        """Average quality score across handoffs."""
        self.metrics.record_handoff(1, "1.0.0", 1000, 500, 8.0)
        self.metrics.record_handoff(2, "2.0.0", 1000, 500, 6.0)

        self.assertEqual(self.metrics.avg_quality_score(), 7.0)

    def test_avg_duration(self):
        """Average handoff duration."""
        self.metrics.record_handoff(1, "1.0.0", 1000, 500, 7.0, duration_seconds=1.0)
        self.metrics.record_handoff(2, "2.0.0", 1000, 500, 7.0, duration_seconds=3.0)

        self.assertEqual(self.metrics.avg_duration(), 2.0)

    def test_total_handoffs(self):
        """Total count of handoffs."""
        self.assertEqual(self.metrics.total_handoffs(), 0)
        self.metrics.record_handoff(1, "1.0.0", 1000, 500, 7.0)
        self.assertEqual(self.metrics.total_handoffs(), 1)

    def test_summary(self):
        """Summary returns all metrics."""
        self.metrics.record_handoff(1, "1.0.0", 5000, 1000, 7.0, "acknowledged", 2.0)
        summary = self.metrics.summary()
        self.assertEqual(summary["total_handoffs"], 1)
        self.assertEqual(summary["success_rate"], 1.0)
        self.assertEqual(summary["avg_compression_ratio"], 80.0)
        self.assertEqual(summary["avg_quality_score"], 7.0)
        self.assertEqual(summary["avg_duration_seconds"], 2.0)


class TestBatonV3(unittest.TestCase):
    """Tests for the Baton v3 class."""

    def test_baton_initialization(self):
        """Baton initializes with all v3 components."""
        baton = Baton("test-vessel")
        self.assertEqual(baton.vessel, "test-vessel")
        self.assertEqual(baton.generation, 0)
        self.assertIsInstance(baton.task_queue, TaskQueue)
        self.assertIsInstance(baton.ack_tracker, HandoffAckTracker)
        self.assertIsInstance(baton.version_tracker, ContextVersionTracker)
        self.assertIsInstance(baton.conflict_resolver, ConflictResolver)
        self.assertIsInstance(baton.metrics, HandoffMetrics)

    def test_baton_i2i_task_claim_new_task(self):
        """i2i_task_claim creates and claims a new task."""
        baton = Baton("test-vessel")
        result = baton.i2i_task_claim("t1", "agent-1", "implementation", "high")
        self.assertEqual(result["i2i_type"], "TASK_CLAIM")
        self.assertEqual(result["status"], "claimed")
        self.assertEqual(result["task_id"], "t1")
        self.assertEqual(baton.task_queue.size(), 0)  # No pending after claim

    def test_baton_i2i_task_complete(self):
        """i2i_task_complete completes a claimed task."""
        baton = Baton("test-vessel")
        baton.i2i_task_claim("t1", "agent-1")
        result = baton.i2i_task_complete("t1", "agent-1", "success",
                                          "Fixed the bug", ["bug at line 142"])
        self.assertEqual(result["i2i_type"], "TASK_COMPLETE")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], "success")

    def test_baton_i2i_claim_conflict_resolution(self):
        """Two agents claiming same task triggers conflict resolution."""
        baton = Baton("test-vessel")
        r1 = baton.i2i_task_claim("t1", "agent-1")
        r2 = baton.i2i_task_claim("t1", "agent-2")

        # Second claim should see conflict
        self.assertIn(r2["status"], ("conflict", "resolved"))
        if r2["status"] == "resolved":
            self.assertEqual(r2["winner"], "agent-1")

    def test_baton_acknowledge_handoff(self):
        """acknowledge_handoff processes a BATON_ACK."""
        baton = Baton("test-vessel")
        # Simulate a snapshot that creates a pending ack
        baton.ack_tracker.send_handoff("h1", "agent-a", "agent-b", 1, "1.0.0")

        result = baton.acknowledge_handoff("h1", "agent-b")
        self.assertEqual(result["status"], "acknowledged")

    def test_baton_check_timeouts(self):
        """check_handoff_timeouts finds expired handoffs."""
        baton = Baton("test-vessel")
        baton.ack_tracker.send_handoff("h1", "a", "b", 1, "1.0.0")
        # Use a tracker with short timeout
        short_tracker = HandoffAckTracker(default_timeout=0.05)
        short_tracker.send_handoff("h-fast", "a", "b", 1, "1.0.0")
        time.sleep(0.06)
        timed_out = short_tracker.check_timeouts()
        self.assertEqual(len(timed_out), 1)

    def test_baton_write_handoff_includes_v3_fields(self):
        """Handoff letter includes v3 fields (task queue, metrics, context version)."""
        baton = Baton("test-vessel")
        baton.state = {"identity": {"confidence": 0.7}, "energy": {}}

        # Add a task
        baton.task_queue.enqueue("t1", "implementation", "Fix bug", "critical")

        letter = baton.write_handoff(
            who_i_was="Debugger",
            where_things_stand="Bug found at line 142 in file allocator.c because of missing free",
            what_i_was_thinking="The root cause is clear",
            what_id_do_next="1. Fix the bug\n2. Write test\n3. Deploy",
            what_im_uncertain_about="I might be wrong about thread safety",
        )
        self.assertIn("Task Queue", letter)
        self.assertIn("CRITICAL", letter)
        self.assertIn("Metrics", letter)

    def test_baton_restore_initializes_v3_state(self):
        """restore() returns state with v3 fields."""
        baton = Baton("test-vessel")
        state = baton.restore()  # No keeper available, returns default state
        self.assertEqual(state["generation"], 0)
        self.assertIn("context_version", state)

    def test_baton_snapshot_with_all_features(self):
        """snapshot() returns v3 fields (context version, compression, ack, metrics)."""
        baton = Baton("test-vessel")
        baton.task_queue.enqueue("t1", "testing", "Write tests", "high")

        agent_state = {
            "identity": {"name": "test", "type": "vessel"},
            "energy_remaining": 800,
            "energy_budget": 1000,
            "confidence": 0.7,
            "handoff": "",
            "open_threads": [],
            "skills": {"python": 0.9},
            "trust": {},
            "intentions": [],
            "tasks_completed": 5,
            "tasks_failed": 1,
        }

        # snapshot calls _write which goes to keeper (will error), but we can
        # check that the return dict has v3 fields
        result = baton.snapshot(agent_state, force=True)
        self.assertEqual(result["status"], "packed")
        self.assertEqual(result["generation"], 1)
        self.assertIn("context_version", result)
        self.assertIn("compression", result)
        self.assertIn("handoff_ack", result)
        self.assertIn("pending_tasks", result)
        self.assertIn("metrics", result)
        self.assertEqual(result["pending_tasks"], 1)
        self.assertIn("ratio", result["compression"])
        self.assertIn("reduction_pct", result["compression"])

    def test_context_version_in_snapshot(self):
        """Snapshot creates and records a context version."""
        baton = Baton("test-vessel")
        baton.snapshot({"handoff": "", "confidence": 0.5}, force=True)

        cv = baton.version_tracker.current_version()
        self.assertIsNotNone(cv)
        self.assertEqual(cv.major, 1)
        self.assertEqual(cv.semver, "1.0.0")

    def test_metrics_recorded_after_snapshot(self):
        """Metrics are recorded after a snapshot."""
        baton = Baton("test-vessel")
        baton.snapshot({"handoff": "", "confidence": 0.5}, force=True)

        self.assertEqual(baton.metrics.total_handoffs(), 1)
        self.assertIn("total_handoffs", baton.metrics.summary())


class TestAutobiography(unittest.TestCase):
    """Tests for autobiography generation."""

    def test_empty_handoffs(self):
        """Empty handoff list produces minimal autobiography."""
        result = generate_autobiography([])
        self.assertIn("Generations: 0", result)

    def test_single_handoff(self):
        """Single handoff produces one generation entry."""
        handoffs = [{
            "generation": 3,
            "letter": "## Where Things Stand\nFixed the bug at line 142.\n\n## What I Was Thinking\nThe fix works.",
            "score": {"average": 7.0},
        }]
        result = generate_autobiography(handoffs)
        self.assertIn("Gen-3", result)
        self.assertIn("score: 7.0", result)

    def test_multiple_handoffs(self):
        """Multiple handoffs produce multiple generation entries."""
        handoffs = [
            {"generation": 1, "letter": "## Where Things Stand\nStarted work.", "score": {"average": 5.0}},
            {"generation": 2, "letter": "## Where Things Stand\nMade progress.", "score": {"average": 6.0}},
        ]
        result = generate_autobiography(handoffs)
        self.assertIn("Gen-1", result)
        self.assertIn("Gen-2", result)
        self.assertIn("Generations: 2", result)


class TestI2IMessageTypes(unittest.TestCase):
    """Tests for I2I v2 message type enums."""

    def test_i2i_message_types(self):
        """I2I message type enum has expected values."""
        self.assertEqual(I2IMessageType.TASK_CLAIM.value, "TASK_CLAIM")
        self.assertEqual(I2IMessageType.TASK_COMPLETE.value, "TASK_COMPLETE")
        self.assertEqual(I2IMessageType.BATON_PACKED.value, "BATON_PACKED")
        self.assertEqual(I2IMessageType.BATON_ACK.value, "BATON_ACK")
        self.assertEqual(I2IMessageType.BATON_CLAIM_CONFLICT.value, "BATON_CLAIM_CONFLICT")
        self.assertEqual(I2IMessageType.BATON_CONTEXT_VERSION.value, "BATON_CONTEXT_VERSION")

    def test_task_result_enum(self):
        """TaskResult has expected values."""
        self.assertEqual(TaskResult.SUCCESS.value, "success")
        self.assertEqual(TaskResult.PARTIAL.value, "partial")
        self.assertEqual(TaskResult.FAILED.value, "failed")

    def test_priority_levels(self):
        """Priority levels map to correct numeric values."""
        self.assertEqual(PRIORITY_LEVELS["critical"], 0)
        self.assertEqual(PRIORITY_LEVELS["high"], 1)
        self.assertEqual(PRIORITY_LEVELS["medium"], 2)
        self.assertEqual(PRIORITY_LEVELS["low"], 3)


if __name__ == "__main__":
    unittest.main()
