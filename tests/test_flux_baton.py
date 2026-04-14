"""Comprehensive tests for flux-baton v2.

Covers:
- Baton creation and serialization
- Context handoff between agents
- Workshop (shipyard) integration
- Edge cases (empty baton, large context, corruption)
"""

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call

# Ensure parent directory is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flux_baton import Baton, score_handoff, generate_autobiography, KEEPER_URL
from shipyard import Shipyard, call_zai, keeper_req


# ─── Helpers ───────────────────────────────────────────────────────────────────

GOOD_HANDOFF = """# Handoff Letter — Generation 1

## Who I Was
I was flux-agent-a0fa81, generation 1. I ran for 12 minutes.
I completed 3 tasks and failed 0.

## Where Things Stand
The cross-assembler is 90% done. The bug is at line 234 of cross_asm.py.
This caused a crash which meant we need to fix the offset because the jump
offset is off by 2 bytes when the instruction before it is MOVI.

## What I Was Thinking
The 2-byte offset bug is interesting. It only happens after MOVI
because MOVI is a 4-byte instruction and the assembler doesn't
account for the variable-width encoding properly. This means we need
to do a two-pass assembly where the first pass calculates sizes.

## What I'd Do Next
1. Fix _resolve_labels() in cross_asm.py (the two-pass approach)
2. Run conformance vectors 0x00A1-0x00A8 against edge target
3. Write a captain's log about the offset bug

## What I'm Uncertain About
I'm not sure if the two-pass approach will break the existing
cloud encoding. I might be wrong about the root cause.

## Open Threads
- I2I DISCOVER sent to babel-vessel, no response yet

Good luck. You know more than you think.
-- Gen-1
"""

MINIMAL_HANDOFF = "# Handoff Letter\n## Where Things Stand\nDone.\n## What I'd Do Next\n1. Exit\n## What I'm Uncertain About\nNothing"

BAD_HANDOFF = "hello world this is very short and lacks detail"


def _mock_keeper_read(files):
    """Return a mock _read function that serves from a dict."""
    def _read(path):
        return files.get(path)
    return _read


def _mock_keeper_write(files):
    """Return a mock _write function that stores into a dict."""
    def _write(path, content, message):
        files[path] = content
        return {}
    return _write


def _mock_keeper_method(files):
    """Return a mock _keeper method that handles reads/writes."""
    def _keeper(method, path, body=None):
        if method == "GET" and path.startswith("/file/"):
            key = path.split("/file/", 1)[1]
            content = files.get(key)
            return {"content": content} if content else {}
        if method == "POST" and path.startswith("/file/"):
            key = path.split("/file/", 1)[1]
            files[key] = body.get("content", "") if body else ""
            return {}
        return {}
    return _keeper


# ═══════════════════════════════════════════════════════════════════════════════
#  score_handoff tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreHandoff(unittest.TestCase):
    """Tests for the score_handoff() function."""

    def test_returns_dict_with_required_keys(self):
        result = score_handoff("some text")
        self.assertIn("scores", result)
        self.assertIn("average", result)
        self.assertIn("passes", result)
        self.assertIn("word_count", result)

    def test_scores_has_all_rubric_categories(self):
        result = score_handoff("some text")
        expected_keys = {
            "surplus_insight", "causal_chain", "honesty",
            "actionable_signal", "compression", "human_compat", "precedent_value",
        }
        self.assertEqual(set(result["scores"].keys()), expected_keys)

    def test_good_handoff_passes(self):
        result = score_handoff(GOOD_HANDOFF)
        self.assertTrue(result["passes"], "Good handoff should pass quality gate")
        self.assertGreaterEqual(result["average"], 4.5)

    def test_bad_handoff_fails(self):
        result = score_handoff(BAD_HANDOFF)
        self.assertFalse(result["passes"], "Bad handoff should fail quality gate")

    def test_word_count(self):
        result = score_handoff(GOOD_HANDOFF)
        wc = len(GOOD_HANDOFF.split())
        self.assertEqual(result["word_count"], wc)

    def test_surplus_insight_detects_specifics(self):
        text = "The bug is at line 42. The offset is 0x2F. The byte register is broken."
        result = score_handoff(text)
        self.assertGreater(result["scores"]["surplus_insight"], 0)

    def test_surplus_insight_cap_at_10(self):
        text = "line 0x byte offset register file bug error line 0x byte offset register file bug error line"
        result = score_handoff(text)
        self.assertLessEqual(result["scores"]["surplus_insight"], 10)

    def test_causal_chain_detects_causation(self):
        text = "The bug caused a crash because of the offset which meant nothing worked."
        result = score_handoff(text)
        self.assertGreater(result["scores"]["causal_chain"], 0)

    def test_honesty_detects_uncertainty(self):
        text = "I'm uncertain about this. I might be wrong. I'm not sure."
        result = score_handoff(text)
        self.assertGreater(result["scores"]["honesty"], 0)

    def test_actionable_signal_with_numbered_steps(self):
        text = "## What I'd Do Next\n1. Fix the bug\n2. Run tests\n3. Ship it"
        result = score_handoff(text)
        self.assertEqual(result["scores"]["actionable_signal"], 8)

    def test_actionable_signal_without_steps(self):
        text = "Some random text without any next steps or numbered items"
        result = score_handoff(text)
        self.assertEqual(result["scores"]["actionable_signal"], 3)

    def test_compression_ideal_range(self):
        # 150-500 words -> score 8
        words = "word " * 250  # ~250 words
        result = score_handoff(words)
        self.assertEqual(result["scores"]["compression"], 8)

    def test_compression_medium_range(self):
        # too few words -> score 3
        words = "word " * 80
        result = score_handoff(words)
        self.assertEqual(result["scores"]["compression"], 3)

    def test_compression_long_range(self):
        # >700 words -> score 3
        words = "word " * 800
        result = score_handoff(words)
        self.assertEqual(result["scores"]["compression"], 3)

    def test_human_compat_detects_sections(self):
        text = "## Who I Was\nAgent\n## Where Things Stand\nWorking\n## What I'm Uncertain About\nHmm\n## Next"
        result = score_handoff(text)
        self.assertGreater(result["scores"]["human_compat"], 0)

    def test_precedent_value_detects_lessons(self):
        text = "The lesson learned is the pattern of the root cause. The fix is systemic."
        result = score_handoff(text)
        self.assertGreater(result["scores"]["precedent_value"], 0)

    def test_empty_string(self):
        result = score_handoff("")
        self.assertEqual(result["word_count"], 0)
        self.assertFalse(result["passes"])

    def test_single_word(self):
        result = score_handoff("hello")
        self.assertEqual(result["word_count"], 1)


# ═══════════════════════════════════════════════════════════════════════════════
#  generate_autobiography tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateAutobiography(unittest.TestCase):
    """Tests for the generate_autobiography() function."""

    def test_empty_handoffs(self):
        result = generate_autobiography([])
        self.assertIn("# Autobiography", result)
        self.assertIn("Generations: 0", result)

    def test_single_handoff(self):
        handoffs = [{
            "generation": 1,
            "letter": GOOD_HANDOFF,
            "score": {"average": 7.0},
        }]
        result = generate_autobiography(handoffs)
        self.assertIn("Gen-1", result)
        self.assertIn("score: 7.0", result)

    def test_multiple_handoffs(self):
        handoffs = [
            {"generation": 1, "letter": GOOD_HANDOFF, "score": {"average": 6.0}},
            {"generation": 2, "letter": GOOD_HANDOFF, "score": {"average": 7.5}},
        ]
        result = generate_autobiography(handoffs)
        self.assertIn("Gen-1", result)
        self.assertIn("Gen-2", result)
        self.assertIn("Generations: 2", result)

    def test_missing_generation_defaults_to_question_mark(self):
        handoffs = [{"letter": "text", "score": {"average": 5}}]
        result = generate_autobiography(handoffs)
        self.assertIn("Gen-?", result)

    def test_missing_score_defaults_to_question_mark(self):
        handoffs = [{"generation": 1, "letter": "text"}]
        result = generate_autobiography(handoffs)
        self.assertIn("score: ?", result)

    def test_extracts_where_things_stand(self):
        handoffs = [{
            "generation": 1,
            "letter": GOOD_HANDOFF,
            "score": {"average": 7.0},
        }]
        result = generate_autobiography(handoffs)
        self.assertIn("90%", result)

    def test_extracts_what_i_was_thinking(self):
        handoffs = [{
            "generation": 1,
            "letter": GOOD_HANDOFF,
            "score": {"average": 7.0},
        }]
        result = generate_autobiography(handoffs)
        self.assertIn("2-byte offset", result.lower())

    def test_missing_letter_no_crash(self):
        handoffs = [{"generation": 1, "score": {"average": 5}}]
        result = generate_autobiography(handoffs)
        self.assertIsInstance(result, str)
        self.assertIn("Gen-1", result)


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — creation and initialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonCreation(unittest.TestCase):
    """Tests for Baton initialization."""

    def test_basic_creation(self):
        b = Baton("my-vessel")
        self.assertEqual(b.vessel, "my-vessel")
        self.assertEqual(b.generation, 0)
        self.assertEqual(b.state, {})
        self.assertEqual(b.handoff, "")

    def test_custom_keeper_url(self):
        b = Baton("my-vessel", keeper_url="http://localhost:9999")
        self.assertEqual(b.keeper_url, "http://localhost:9999")

    def test_keeper_url_trailing_slash_stripped(self):
        b = Baton("my-vessel", keeper_url="http://localhost:9999/")
        self.assertEqual(b.keeper_url, "http://localhost:9999")

    def test_agent_credentials(self):
        b = Baton("my-vessel", agent_id="agent-1", agent_secret="secret-1")
        self.assertEqual(b.agent_id, "agent-1")
        self.assertEqual(b.agent_secret, "secret-1")

    def test_repo_format_simple_name(self):
        b = Baton("my-vessel")
        self.assertEqual(b._repo(), "SuperInstance/my-vessel")

    def test_repo_format_full_name(self):
        b = Baton("org/my-vessel")
        self.assertEqual(b._repo(), "org/my-vessel")

    def test_default_keeper_url_from_env(self):
        self.assertIsInstance(KEEPER_URL, str)
        self.assertTrue(len(KEEPER_URL) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — restore
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonRestore(unittest.TestCase):
    """Tests for Baton.restore() — Gen-N+1 reads baton."""

    def test_restore_fresh_agent(self):
        """No baton exists — returns default state."""
        files = {}
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["generation"], 0)
        self.assertEqual(state["identity"], {})
        self.assertEqual(state["energy"], {})
        self.assertEqual(state["open_threads"], [])

    def test_restore_with_generation(self):
        files = {".baton/GENERATION": "3"}
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["generation"], 3)
        self.assertEqual(b.generation, 3)

    def test_restore_with_state_json(self):
        files = {
            ".baton/GENERATION": "1",
            ".baton/CURRENT/STATE.json": json.dumps({
                "energy": {"remaining": 200, "budget": 1000},
                "open_threads": ["task-1", "task-2"],
                "skills": {"python": 0.8},
                "trust": {"agent-b": 0.6},
                "intentions": ["fix bug"],
            }),
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["energy"]["remaining"], 200)
        self.assertEqual(len(state["open_threads"]), 2)
        self.assertEqual(state["skills"]["python"], 0.8)
        self.assertEqual(state["trust"]["agent-b"], 0.6)
        self.assertEqual(state["intentions"], ["fix bug"])

    def test_restore_with_handoff(self):
        files = {
            ".baton/GENERATION": "2",
            ".baton/CURRENT/HANDOFF.md": GOOD_HANDOFF,
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertIn("cross-assembler", state["handoff"])
        self.assertEqual(b.handoff, GOOD_HANDOFF)

    def test_restore_with_identity(self):
        files = {
            ".baton/GENERATION": "1",
            ".baton/IDENTITY.json": json.dumps({
                "name": "test-agent",
                "type": "vessel",
                "confidence": 0.72,
            }),
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["identity"]["name"], "test-agent")
        self.assertEqual(state["identity"]["confidence"], 0.72)

    def test_restore_with_autobiography(self):
        files = {
            ".baton/GENERATION": "3",
            ".baton/AUTOBIOGRAPHY.md": "# Autobiography\nGen-1 was great.",
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertIn("Gen-1", state["autobiography"])

    def test_restore_with_fitness_history(self):
        history = [{"generation": 1, "confidence": 0.5}]
        files = {
            ".baton/GENERATION": "1",
            ".baton/evolution/fitness_history.json": json.dumps(history),
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(len(state["fitness_history"]), 1)
        self.assertEqual(state["fitness_history"][0]["generation"], 1)

    def test_restore_corrupted_state_json(self):
        """Corrupted STATE.json is handled gracefully."""
        files = {
            ".baton/GENERATION": "1",
            ".baton/CURRENT/STATE.json": "NOT VALID JSON {{{",
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["generation"], 1)
        self.assertEqual(state["energy"], {})

    def test_restore_corrupted_generation(self):
        """Non-numeric GENERATION file returns gen 0."""
        files = {".baton/GENERATION": "not-a-number"}
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["generation"], 0)

    def test_restore_corrupted_identity(self):
        files = {
            ".baton/GENERATION": "1",
            ".baton/IDENTITY.json": "BROKEN",
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["identity"], {})

    def test_restore_corrupted_fitness(self):
        files = {
            ".baton/GENERATION": "1",
            ".baton/evolution/fitness_history.json": "BROKEN",
        }
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["fitness_history"], [])

    def test_restore_state_set_on_instance(self):
        files = {".baton/GENERATION": "2"}
        b = Baton("my-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertIs(b.state, state)


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — snapshot
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonSnapshot(unittest.TestCase):
    """Tests for Baton.snapshot() — Gen-N packs baton."""

    def _make_baton(self):
        files = {}
        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._write = _mock_keeper_write(files)
        b._read = _mock_keeper_read(files)
        return b, files

    def test_snapshot_basic(self):
        b, files = self._make_baton()
        result = b.snapshot({"handoff": GOOD_HANDOFF}, force=True)

        self.assertEqual(result["status"], "packed")
        self.assertEqual(result["generation"], 1)
        self.assertGreater(result["files_written"], 0)

    def test_snapshot_increments_generation(self):
        b, files = self._make_baton()
        b.snapshot({"handoff": GOOD_HANDOFF}, force=True)
        self.assertEqual(b.generation, 1)

        b.snapshot({"handoff": GOOD_HANDOFF}, force=True)
        self.assertEqual(b.generation, 2)

    def test_snapshot_writes_generation_file(self):
        b, files = self._make_baton()
        b.snapshot({"handoff": GOOD_HANDOFF}, force=True)

        self.assertIn(".baton/GENERATION", files)
        self.assertEqual(files[".baton/GENERATION"].strip(), "1")

    def test_snapshot_writes_state_json(self):
        b, files = self._make_baton()
        state = {
            "energy_remaining": 150,
            "energy_budget": 1000,
            "confidence": 0.75,
            "tasks_completed": 5,
            "tasks_failed": 1,
            "handoff": GOOD_HANDOFF,
        }
        b.snapshot(state, force=True)

        current_state = json.loads(files[".baton/CURRENT/STATE.json"])
        self.assertEqual(current_state["energy"]["remaining"], 150)
        self.assertEqual(current_state["energy"]["budget"], 1000)
        self.assertEqual(current_state["confidence"], 0.75)
        self.assertEqual(current_state["tasks_completed"], 5)

    def test_snapshot_writes_identity(self):
        b, files = self._make_baton()
        identity = {"name": "test-agent", "type": "scout", "field": "security"}
        b.snapshot({"handoff": GOOD_HANDOFF, "identity": identity}, force=True)

        written_identity = json.loads(files[".baton/IDENTITY.json"])
        self.assertEqual(written_identity["name"], "test-agent")
        self.assertEqual(written_identity["type"], "scout")

    def test_snapshot_writes_handoff(self):
        b, files = self._make_baton()
        b.snapshot({"handoff": GOOD_HANDOFF}, force=True)

        self.assertIn(".baton/generations/v1/HANDOFF.md", files)
        self.assertIn(".baton/CURRENT/HANDOFF.md", files)

    def test_snapshot_writes_score_json(self):
        b, files = self._make_baton()
        b.snapshot({"handoff": GOOD_HANDOFF}, force=True)

        score = json.loads(files[".baton/generations/v1/SCORE.json"])
        self.assertIn("average", score)
        self.assertIn("scores", score)
        self.assertGreater(score["average"], 0)

    def test_snapshot_writes_fitness_history(self):
        b, files = self._make_baton()
        b.snapshot({"handoff": GOOD_HANDOFF, "confidence": 0.8, "tasks_completed": 10}, force=True)

        fitness = json.loads(files[".baton/evolution/fitness_history.json"])
        self.assertEqual(len(fitness), 1)
        self.assertEqual(fitness[0]["generation"], 1)
        self.assertEqual(fitness[0]["confidence"], 0.8)

    def test_snapshot_writes_autobiography(self):
        b, files = self._make_baton()
        b.snapshot({"handoff": GOOD_HANDOFF}, force=True)

        self.assertIn(".baton/AUTOBIOGRAPHY.md", files)
        self.assertIn("Gen-1", files[".baton/AUTOBIOGRAPHY.md"])

    def test_snapshot_quality_gate_blocks_bad_handoff(self):
        b, files = self._make_baton()
        result = b.snapshot({"handoff": BAD_HANDOFF}, force=False)

        self.assertEqual(result["status"], "quality_gate_failed")
        self.assertFalse(result["quality"]["passes"])
        self.assertEqual(result["generation"], 1)

    def test_snapshot_quality_gate_passes_good_handoff(self):
        b, files = self._make_baton()
        result = b.snapshot({"handoff": GOOD_HANDOFF}, force=False)

        self.assertEqual(result["status"], "packed")
        self.assertTrue(result["quality"]["passes"])

    def test_snapshot_force_bypasses_quality_gate(self):
        b, files = self._make_baton()
        result = b.snapshot({"handoff": BAD_HANDOFF}, force=True)

        self.assertEqual(result["status"], "packed")

    def test_snapshot_without_handoff(self):
        b, files = self._make_baton()
        result = b.snapshot({}, force=True)

        self.assertEqual(result["status"], "packed")
        self.assertGreater(result["files_written"], 0)

    def test_snapshot_multiple_generations(self):
        b, files = self._make_baton()
        for i in range(5):
            result = b.snapshot({"handoff": GOOD_HANDOFF}, force=True)
            self.assertEqual(result["generation"], i + 1)

        self.assertEqual(b.generation, 5)
        self.assertEqual(files[".baton/GENERATION"].strip(), "5")

    def test_snapshot_state_json_has_timestamp(self):
        b, files = self._make_baton()
        b.snapshot({"handoff": GOOD_HANDOFF}, force=True)

        state = json.loads(files[".baton/CURRENT/STATE.json"])
        self.assertIn("timestamp", state)
        datetime.fromisoformat(state["timestamp"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — write_handoff
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonWriteHandoff(unittest.TestCase):
    """Tests for Baton.write_handoff()."""

    def test_basic_handoff_letter(self):
        b = Baton("test-vessel")
        letter = b.write_handoff(
            who_i_was="I was Gen-1 agent.",
            where_things_stand="Code is 50% done.",
            what_i_was_thinking="Need to refactor.",
            what_id_do_next="1. Refactor\n2. Test",
            what_im_uncertain_about="Not sure about performance.",
        )
        self.assertIn("Gen-1", letter)
        self.assertIn("Who I Was", letter)
        self.assertIn("Where Things Stand", letter)
        self.assertIn("What I Was Thinking", letter)
        self.assertIn("What I'd Do Next", letter)
        self.assertIn("What I'm Uncertain About", letter)
        self.assertIn("Good luck", letter)

    def test_handoff_includes_open_threads(self):
        b = Baton("test-vessel")
        letter = b.write_handoff(
            who_i_was="Agent", where_things_stand="Working",
            what_i_was_thinking="Thinking", what_id_do_next="Continue",
            what_im_uncertain_about="Nothing",
            open_threads=["task-a", "task-b"],
        )
        self.assertIn("- task-a", letter)
        self.assertIn("- task-b", letter)

    def test_handoff_default_open_threads(self):
        b = Baton("test-vessel")
        letter = b.write_handoff(
            who_i_was="Agent", where_things_stand="Working",
            what_i_was_thinking="Thinking", what_id_do_next="Continue",
            what_im_uncertain_about="Nothing",
        )
        self.assertIn("- None", letter)

    def test_handoff_includes_energy(self):
        b = Baton("test-vessel")
        b.state = {"energy": {"remaining": 300, "budget": 1000}}
        letter = b.write_handoff(
            who_i_was="Agent", where_things_stand="Working",
            what_i_was_thinking="Thinking", what_id_do_next="Continue",
            what_im_uncertain_about="Nothing",
        )
        self.assertIn("300/1000", letter)

    def test_handoff_includes_task_counts(self):
        b = Baton("test-vessel")
        letter = b.write_handoff(
            who_i_was="Agent", where_things_stand="Working",
            what_i_was_thinking="Thinking", what_id_do_next="Continue",
            what_im_uncertain_about="Nothing",
            tasks_completed=10, tasks_failed=2,
        )
        self.assertIn("10", letter)
        self.assertIn("2", letter)

    def test_handoff_uses_next_generation_number(self):
        b = Baton("test-vessel")
        b.generation = 3
        letter = b.write_handoff(
            who_i_was="Agent", where_things_stand="Working",
            what_i_was_thinking="Thinking", what_id_do_next="Continue",
            what_im_uncertain_about="Nothing",
        )
        self.assertIn("Generation 4", letter)
        self.assertIn("Gen-4", letter)

    def test_handoff_includes_confidence(self):
        b = Baton("test-vessel")
        b.state = {"identity": {"confidence": 0.85}}
        letter = b.write_handoff(
            who_i_was="Agent", where_things_stand="Working",
            what_i_was_thinking="Thinking", what_id_do_next="Continue",
            what_im_uncertain_about="Nothing",
        )
        self.assertIn("0.85", letter)


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — print_restore_summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonPrintRestoreSummary(unittest.TestCase):
    """Tests for Baton.print_restore_summary()."""

    def test_fresh_agent_summary(self):
        b = Baton("test-vessel")
        b.state = {"generation": 0}
        with patch("sys.stdout"):
            b.print_restore_summary()
            self.assertEqual(b.generation, 0)

    def test_restored_agent_summary(self):
        b = Baton("test-vessel")
        b.state = {
            "generation": 3,
            "identity": {"name": "test-agent", "type": "scout"},
            "energy": {"remaining": 500, "budget": 1000},
            "open_threads": ["a", "b", "c"],
            "skills": {"python": 0.9, "rust": 0.7, "go": 0.6},
            "handoff": GOOD_HANDOFF,
            "fitness_history": [{"gen": 1}, {"gen": 2}],
        }
        with patch("sys.stdout"):
            b.print_restore_summary()

    def test_summary_with_empty_identity(self):
        b = Baton("test-vessel")
        b.state = {"generation": 1, "identity": {}}
        with patch("sys.stdout"):
            b.print_restore_summary()


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — acquire_lease
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonAcquireLease(unittest.TestCase):
    """Tests for Baton.acquire_lease()."""

    def test_acquire_lease_success(self):
        b = Baton("test-vessel")
        b._keeper = MagicMock(return_value={"lease_id": "lease-123"})
        result = b.acquire_lease()
        self.assertTrue(result)
        self.assertEqual(b._lease_id, "lease-123")

    def test_acquire_lease_failure(self):
        b = Baton("test-vessel")
        b._keeper = MagicMock(return_value={"error": "no lease"})
        result = b.acquire_lease()
        self.assertFalse(result)
        self.assertIsNone(b._lease_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — _keeper (HTTP layer)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonKeeperHTTP(unittest.TestCase):
    """Tests for Baton._keeper() HTTP helper."""

    @patch("flux_baton.urllib.request.urlopen")
    def test_keeper_get_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"content": "hello"}).encode()
        mock_urlopen.return_value = mock_resp

        b = Baton("test-vessel")
        result = b._keeper("GET", "/file/repo/path")

        self.assertEqual(result["content"], "hello")

    @patch("flux_baton.urllib.request.urlopen")
    def test_keeper_post_with_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_resp

        b = Baton("test-vessel")
        result = b._keeper("POST", "/file/repo/path", {"content": "data"})

        self.assertEqual(result["status"], "ok")
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.method, "POST")

    @patch("flux_baton.urllib.request.urlopen")
    def test_keeper_empty_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_urlopen.return_value = mock_resp

        b = Baton("test-vessel")
        result = b._keeper("GET", "/some/path")
        self.assertEqual(result, {})

    @patch("flux_baton.urllib.request.urlopen")
    def test_keeper_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")

        b = Baton("test-vessel")
        result = b._keeper("GET", "/some/path")
        self.assertIn("error", result)

    @patch("flux_baton.urllib.request.urlopen")
    def test_keeper_sends_auth_headers(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_urlopen.return_value = mock_resp

        b = Baton("test-vessel", agent_id="agent-1", agent_secret="secret-1")
        b._keeper("GET", "/some/path")

        req = mock_urlopen.call_args[0][0]
        hdrs = dict(req.headers)
        self.assertEqual(hdrs.get("X-agent-id"), "agent-1")
        self.assertEqual(hdrs.get("X-agent-secret"), "secret-1")

    @patch("flux_baton.urllib.request.urlopen")
    def test_keeper_no_auth_headers_by_default(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_urlopen.return_value = mock_resp

        b = Baton("test-vessel")
        b._keeper("GET", "/some/path")

        req = mock_urlopen.call_args[0][0]
        self.assertNotIn("x-agent-id", {k.lower() for k in req.headers.keys()})


# ═══════════════════════════════════════════════════════════════════════════════
#  Baton class — _read and _write helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatonReadWrite(unittest.TestCase):
    """Tests for Baton._read() and _write()."""

    @patch.object(Baton, "_keeper")
    def test_read_success(self, mock_keeper):
        mock_keeper.return_value = {"content": "file contents"}
        b = Baton("test-vessel")
        result = b._read(".baton/GENERATION")
        self.assertEqual(result, "file contents")

    @patch.object(Baton, "_keeper")
    def test_read_not_found(self, mock_keeper):
        mock_keeper.return_value = {}
        b = Baton("test-vessel")
        result = b._read(".baton/GENERATION")
        self.assertIsNone(result)

    @patch.object(Baton, "_keeper")
    def test_write_calls_keeper(self, mock_keeper):
        mock_keeper.return_value = {}
        b = Baton("test-vessel")
        b._write(".baton/GENERATION", "1", "init gen")
        mock_keeper.assert_called_once()
        args = mock_keeper.call_args
        self.assertEqual(args[0][0], "POST")
        self.assertIn(".baton/GENERATION", args[0][1])


# ═══════════════════════════════════════════════════════════════════════════════
#  Context handoff between agents (integration-style)
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextHandoff(unittest.TestCase):
    """Test full handoff cycle: Gen-1 snapshots, Gen-2 restores."""

    def _shared_files(self):
        return {}

    def test_single_generation_handoff(self):
        files = self._shared_files()

        # Gen-1 packs baton
        b1 = Baton("test-vessel")
        b1._keeper = _mock_keeper_method(files)
        b1._write = _mock_keeper_write(files)
        b1._read = _mock_keeper_read(files)

        state1 = {
            "identity": {"name": "test-vessel", "type": "vessel", "confidence": 0.6},
            "energy_remaining": 150,
            "energy_budget": 1000,
            "handoff": GOOD_HANDOFF,
            "open_threads": ["finish assembler", "write tests"],
            "skills": {"python": 0.8, "asm": 0.5},
            "trust": {"oracle1": 0.9},
            "intentions": ["fix bug at line 234"],
            "tasks_completed": 8,
            "tasks_failed": 1,
            "confidence": 0.6,
        }
        result = b1.snapshot(state1, force=True)
        self.assertEqual(result["generation"], 1)

        # Gen-2 restores baton
        b2 = Baton("test-vessel")
        b2._keeper = _mock_keeper_method(files)
        b2._read = _mock_keeper_read(files)

        restored = b2.restore()
        self.assertEqual(restored["generation"], 1)
        self.assertEqual(restored["identity"]["name"], "test-vessel")
        self.assertEqual(restored["energy"]["remaining"], 150)
        self.assertIn("finish assembler", restored["open_threads"])
        self.assertEqual(restored["skills"]["python"], 0.8)

    def test_multi_generation_chain(self):
        files = self._shared_files()

        for gen in range(1, 4):
            b = Baton("test-vessel")
            b._keeper = _mock_keeper_method(files)
            b._write = _mock_keeper_write(files)
            b._read = _mock_keeper_read(files)
            b.generation = gen - 1

            state = {
                "identity": {"name": "test-vessel", "type": "vessel"},
                "energy_remaining": 1000 - gen * 200,
                "energy_budget": 1000,
                "handoff": GOOD_HANDOFF,
                "confidence": 0.3 + gen * 0.1,
                "tasks_completed": gen * 3,
                "tasks_failed": 0,
            }
            b.snapshot(state, force=True)

        # Final agent reads
        b_final = Baton("test-vessel")
        b_final._keeper = _mock_keeper_method(files)
        b_final._read = _mock_keeper_read(files)

        restored = b_final.restore()
        self.assertEqual(restored["generation"], 3)

        # The latest state should reflect Gen-3
        current_state = json.loads(files[".baton/CURRENT/STATE.json"])
        self.assertEqual(current_state["generation"], 3)
        self.assertAlmostEqual(current_state["confidence"], 0.6, places=5)

    def test_handoff_survives_corrupted_file(self):
        """If one file is corrupted, others still load."""
        files = {
            ".baton/GENERATION": "1",
            ".baton/CURRENT/STATE.json": "BROKEN JSON",
            ".baton/IDENTITY.json": json.dumps({"name": "test"}),
        }

        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["generation"], 1)
        self.assertEqual(state["identity"]["name"], "test")
        self.assertEqual(state["energy"], {})


# ═══════════════════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):
    """Edge cases: empty baton, large context, corruption, unicode."""

    def test_empty_agent_state_snapshot(self):
        files = {}
        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._write = _mock_keeper_write(files)
        b._read = _mock_keeper_read(files)

        result = b.snapshot({}, force=True)
        self.assertEqual(result["status"], "packed")
        self.assertEqual(result["generation"], 1)

    def test_large_handoff(self):
        """Very large handoff text should work."""
        large_text = "## Where Things Stand\n" + ("The bug at line 42 needs fixing. " * 500)
        large_text += "\n## What I'd Do Next\n1. Fix it\n2. Test\n3. Ship\n"
        large_text += "## What I'm Uncertain About\nI might be wrong about the fix.\n"

        result = score_handoff(large_text)
        self.assertGreater(result["word_count"], 1000)

    def test_unicode_in_handoff(self):
        text = "## Where Things Stand\nBug in cafe resume naive - the UTF-8 encoding is broken."
        result = score_handoff(text)
        self.assertIsInstance(result["average"], float)

    def test_special_characters_in_handoff(self):
        text = "## Where Things Stand\nError: <script>alert('xss')</script> and \"quotes\""
        result = score_handoff(text)
        self.assertIsInstance(result["average"], float)

    def test_null_bytes_in_content(self):
        """Baton should handle null bytes without crashing."""
        files = {".baton/GENERATION": "1\x00"}
        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertIn("generation", state)

    def test_very_long_vessel_name(self):
        name = "a" * 500
        b = Baton(name)
        self.assertEqual(b.vessel, name)
        self.assertEqual(b._repo(), f"SuperInstance/{name}")

    def test_snapshot_with_all_fields(self):
        """Snapshot with every possible field populated."""
        files = {}
        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._write = _mock_keeper_write(files)
        b._read = _mock_keeper_read(files)

        state = {
            "identity": {"name": "full-agent", "type": "mechanic", "field": "debugging"},
            "energy_remaining": 42,
            "energy_budget": 1000,
            "handoff": GOOD_HANDOFF,
            "open_threads": ["a", "b", "c", "d", "e"],
            "skills": {"python": 0.95, "rust": 0.85, "go": 0.75, "asm": 0.9},
            "trust": {"agent-a": 0.9, "agent-b": 0.7, "agent-c": 0.5},
            "intentions": ["fix bug", "write tests", "deploy"],
            "tasks_completed": 42,
            "tasks_failed": 3,
            "confidence": 0.92,
        }
        result = b.snapshot(state, force=True)
        self.assertEqual(result["generation"], 1)
        self.assertGreater(result["files_written"], 5)

    def test_restore_missing_all_files(self):
        """No files at all -- returns defaults."""
        files = {}
        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._read = _mock_keeper_read(files)

        state = b.restore()
        self.assertEqual(state["generation"], 0)
        self.assertEqual(state["identity"], {})
        self.assertEqual(state["diary"], "")

    def test_score_handoff_with_markdown_formatting(self):
        text = ("# Handoff\n## Who I Was\nAgent\n## Where Things Stand\nWorking on **bold** and *italic*\n"
                "## What I'd Do Next\n1. Step one\n2. Step two\n3. Step three\n"
                "## What I'm Uncertain About\nNot sure")
        result = score_handoff(text)
        self.assertIsInstance(result["average"], float)

    def test_score_handoff_with_code_blocks(self):
        text = "## Where Things Stand\n```python\ndef fix():\n    pass\n```\nThe bug is at line 42."
        result = score_handoff(text)
        self.assertGreater(result["scores"]["surplus_insight"], 0)

    def test_fitness_efficiency_calculation(self):
        """Energy efficiency should be tasks_completed / energy_used."""
        files = {}
        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._write = _mock_keeper_write(files)
        b._read = _mock_keeper_read(files)

        b.snapshot({
            "handoff": GOOD_HANDOFF,
            "energy_remaining": 200,
            "tasks_completed": 80,
        }, force=True)

        fitness = json.loads(files[".baton/evolution/fitness_history.json"])
        self.assertAlmostEqual(fitness[0]["energy_efficiency"], 0.1, places=3)

    def test_fitness_efficiency_zero_energy_remaining(self):
        files = {}
        b = Baton("test-vessel")
        b._keeper = _mock_keeper_method(files)
        b._write = _mock_keeper_write(files)
        b._read = _mock_keeper_read(files)

        b.snapshot({
            "handoff": GOOD_HANDOFF,
            "energy_remaining": 0,
            "tasks_completed": 50,
        }, force=True)

        fitness = json.loads(files[".baton/evolution/fitness_history.json"])
        self.assertAlmostEqual(fitness[0]["energy_efficiency"], 0.05, places=3)

    def test_quality_gate_average_calculation(self):
        """Average should be sum / 7 (number of categories)."""
        result = score_handoff(GOOD_HANDOFF)
        scores = result["scores"]
        expected_avg = round(sum(scores.values()) / len(scores), 1)
        self.assertEqual(result["average"], expected_avg)


# ═══════════════════════════════════════════════════════════════════════════════
#  Shipyard integration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestShipyard(unittest.TestCase):
    """Tests for Shipyard class."""

    def test_shipyard_creation(self):
        s = Shipyard(keeper_url="http://localhost:9999")
        self.assertEqual(s.keeper_url, "http://localhost:9999")

    def test_academy_has_all_subjects(self):
        expected = {
            "git_navigation", "fleet_protocol", "captains_log",
            "baton_handoff", "code_analysis", "fleet_coordination",
        }
        self.assertEqual(set(Shipyard.ACADEMY.keys()), expected)

    def test_vessel_types(self):
        expected = {"lighthouse", "vessel", "scout", "mechanic", "greenhorn"}
        self.assertEqual(set(Shipyard.VESSEL_TYPES.keys()), expected)

    def test_birth_phase(self):
        s = Shipyard()
        with patch("shipyard.keeper_req") as mock_keeper:
            mock_keeper.return_value = {"secret": "abc123", "status": "registered"}
            result = s.birth("test-vessel", "scout", "security")

        self.assertEqual(result["vessel"], "test-vessel")
        self.assertEqual(result["identity"]["type"], "scout")
        self.assertEqual(result["identity"]["field"], "security")
        self.assertEqual(result["identity"]["confidence"], 0.3)
        self.assertFalse(result["identity"]["academy_graduate"])
        mock_keeper.assert_called_once()

    def test_birth_vessel_voice_mapping(self):
        s = Shipyard()
        with patch("shipyard.keeper_req") as mock_keeper:
            mock_keeper.return_value = {"secret": "x", "status": "ok"}

            r1 = s.birth("v1", "lighthouse")
            self.assertEqual(r1["identity"]["voice"], "fleet-commander")

            r2 = s.birth("v2", "scout")
            self.assertEqual(r2["identity"]["voice"], "research/oracle")

            r3 = s.birth("v3", "mechanic")
            self.assertEqual(r3["identity"]["voice"], "debug/analysis")

    def test_birth_sets_born_timestamp(self):
        s = Shipyard()
        with patch("shipyard.keeper_req") as mock_keeper:
            mock_keeper.return_value = {"secret": "x", "status": "ok"}
            result = s.birth("test", "vessel")

        born = result["identity"]["born"]
        datetime.fromisoformat(born)

    def test_train_phase_with_mocked_ai(self):
        s = Shipyard()
        agent = {
            "identity": {"name": "test", "type": "vessel"},
            "vessel": "test",
            "secret": "secret",
        }

        with patch("shipyard.call_zai") as mock_ai:
            mock_ai.return_value = (
                "First I would use git log to find the commits. "
                "Then I would analyze the changes because that gives context. "
                "Step 1 is to read the file, step 2 is to test."
            )
            result = s.train(agent, curriculum=["git_navigation"])

        self.assertIn("git_navigation", result["academy"])
        self.assertIn("score", result["academy"]["git_navigation"])

    def test_train_phase_updates_confidence(self):
        s = Shipyard()
        agent = {
            "identity": {"name": "test", "type": "vessel", "confidence": 0.3},
            "vessel": "test",
            "secret": "secret",
        }

        with patch("shipyard.call_zai") as mock_ai:
            mock_ai.return_value = "First, then step 1 because of the file repo commit error 0x line git test flux."
            result = s.train(agent, curriculum=["git_navigation", "code_analysis"])

        self.assertGreater(result["identity"]["confidence"], 0.3)

    def test_build_vessel_phase(self):
        s = Shipyard()
        agent = {
            "identity": {"name": "test", "type": "vessel", "academy_graduate": True,
                         "field": "general", "voice": "build/coordination", "born": "2024-01-01"},
            "vessel": "test",
            "secret": "secret",
            "academy": {"git_navigation": {"name": "Git", "score": 8, "passed": True}},
        }

        with patch("shipyard.keeper_req") as mock_keeper:
            mock_keeper.return_value = {}
            result = s.build_vessel(agent)

        self.assertTrue(result["identity"]["vessel_built"])
        self.assertEqual(result["repo"], "SuperInstance/test")

    def test_build_vessel_writes_charter(self):
        s = Shipyard()
        agent = {
            "identity": {"name": "test", "type": "vessel", "academy_graduate": True,
                         "field": "security", "voice": "build/coordination", "born": "2024-01-01"},
            "vessel": "test",
            "secret": "secret",
            "academy": {},
        }

        with patch("shipyard.keeper_req") as mock_keeper:
            mock_keeper.return_value = {}
            s.build_vessel(agent)

        self.assertGreater(mock_keeper.call_count, 4)

    def test_launch_full_pipeline(self):
        s = Shipyard()
        with patch("shipyard.keeper_req") as mock_keeper:
            mock_keeper.return_value = {"secret": "x", "status": "ok"}
            with patch("shipyard.call_zai") as mock_ai:
                mock_ai.return_value = "First step because of the file repo. Step 1: git commit. Next: test."
                result = s.launch("test-vessel", "vessel", "security")

        self.assertIn("identity", result)
        self.assertEqual(result["vessel"], "test-vessel")

    def test_academy_training_handles_ai_error(self):
        s = Shipyard()
        agent = {
            "identity": {"name": "test", "type": "vessel"},
            "vessel": "test",
            "secret": "secret",
        }

        with patch("shipyard.call_zai") as mock_ai:
            mock_ai.side_effect = Exception("AI service down")
            result = s.train(agent, curriculum=["git_navigation"])

        self.assertIn("git_navigation", result["academy"])
        self.assertFalse(result["academy"]["git_navigation"]["passed"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Shipyard keeper_req tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestShipyardKeeperReq(unittest.TestCase):
    """Tests for shipyard.keeper_req() HTTP helper."""

    @patch("shipyard.urllib.request.urlopen")
    def test_keeper_req_get(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_resp

        result = keeper_req("GET", "/repo/test")
        self.assertEqual(result["status"], "ok")

    @patch("shipyard.urllib.request.urlopen")
    def test_keeper_req_with_auth(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_urlopen.return_value = mock_resp

        keeper_req("POST", "/file/repo/README.md", {"content": "hello"}, auth=("agent", "secret"))
        req = mock_urlopen.call_args[0][0]
        hdrs = dict(req.headers)
        self.assertEqual(hdrs.get("X-agent-id"), "agent")
        self.assertEqual(hdrs.get("X-agent-secret"), "secret")

    @patch("shipyard.urllib.request.urlopen")
    def test_keeper_req_empty_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_urlopen.return_value = mock_resp

        result = keeper_req("GET", "/repo/test")
        self.assertEqual(result, {})


# ═══════════════════════════════════════════════════════════════════════════════
#  call_zai tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCallZai(unittest.TestCase):
    """Tests for shipyard.call_zai() AI helper."""

    @patch("shipyard.urllib.request.urlopen")
    def test_call_zai_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Hello world"}}]
        }).encode()
        mock_urlopen.return_value = mock_resp

        result = call_zai([{"role": "user", "content": "Say hello"}])
        self.assertEqual(result, "Hello world")

    @patch("shipyard.urllib.request.urlopen")
    def test_call_zai_uses_correct_url(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode()
        mock_urlopen.return_value = mock_resp

        call_zai([{"role": "user", "content": "test"}])
        req = mock_urlopen.call_args[0][0]
        self.assertIn("chat/completions", req.full_url)


if __name__ == "__main__":
    unittest.main()
