"""Comprehensive tests for flux-baton module."""
import json
import pytest
from unittest.mock import patch, MagicMock
from flux_baton import (
    score_handoff,
    generate_autobiography,
    Baton,
    KEEPER_URL,
)


# ═══════════════════════════════════════════════════════════
# score_handoff()
# ═══════════════════════════════════════════════════════════

class TestScoreHandoff:
    def test_returns_required_keys(self):
        result = score_handoff("some text")
        assert "scores" in result
        assert "average" in result
        assert "passes" in result
        assert "word_count" in result

    def test_word_count(self):
        result = score_handoff("one two three four five")
        assert result["word_count"] == 5

    def test_empty_text(self):
        result = score_handoff("")
        assert result["word_count"] == 0
        # Even with 0 words, other categories may score above 0
        assert not result["passes"]
        # But average should be very low (not all categories score)
        assert result["average"] < 3.0

    def test_surplus_insight_specific_terms(self):
        letter = "Found a bug at line 42 in the register file. The error was at offset 0x00."
        result = score_handoff(letter)
        assert result["scores"]["surplus_insight"] >= 4  # "line", "0x", "register", "file", "error"

    def test_causal_chain_terms(self):
        letter = "The memory was corrupted because the pointer was null, which meant the write failed. This caused a crash."
        result = score_handoff(letter)
        assert result["scores"]["causal_chain"] >= 4

    def test_honesty_terms(self):
        letter = "I'm uncertain about the root cause. I don't know if this is the right approach. It might fail?"
        result = score_handoff(letter)
        assert result["scores"]["honesty"] >= 4

    def test_actionable_signal_next_steps(self):
        letter = "What I'd do next:\n1. Fix the bug\n2. Run tests\n3. Deploy"
        result = score_handoff(letter)
        assert result["scores"]["actionable_signal"] >= 8

    def test_actionable_signal_no_next_steps(self):
        letter = "Everything is fine. Nothing to do."
        result = score_handoff(letter)
        assert result["scores"]["actionable_signal"] == 3

    def test_compression_ideal_range(self):
        # 150-500 words is ideal → score 8
        words = "word " * 200  # ~200 words
        result = score_handoff(words)
        assert result["scores"]["compression"] == 8

    def test_compression_acceptable_range(self):
        # 100-150 words → score 5 (not ideal 150-500, but acceptable 100-700)
        words = "word " * 120  # ~120 words
        result = score_handoff(words)
        assert result["scores"]["compression"] == 5

    def test_compression_too_short(self):
        words = "word " * 50  # ~50 words
        result = score_handoff(words)
        assert result["scores"]["compression"] == 3

    def test_compression_too_long(self):
        words = "word " * 800  # ~800 words
        result = score_handoff(words)
        assert result["scores"]["compression"] == 3

    def test_human_compat_section_headers(self):
        letter = "## Who I Was\nAgent 1. ## Where Things Stand\nWorking. ## Uncertain about\nSomething."
        result = score_handoff(letter)
        assert result["scores"]["human_compat"] >= 6

    def test_precedent_value_lessons(self):
        letter = "The root cause was a pattern in the error handling. The fix is to check bounds first. This means we need to refactor."
        result = score_handoff(letter)
        assert result["scores"]["precedent_value"] >= 4

    def test_passes_threshold(self):
        """A well-written letter should pass the quality gate."""
        letter = """## Who I Was
I was flux-agent generation 3 working on the cross assembler for 47 minutes.

## Where Things Stand
The cross-assembler is 90% done. The bug is at line 234 of cross_asm.py.
The jump offset is off by 2 bytes at offset 0x00A1 in the register file.
This is a systemic error pattern.

## What I Was Thinking
The 2-byte offset bug happened because MOVI is a 4-byte instruction,
which meant the assembler didn't account for variable-width encoding.
This caused the jump targets to be wrong and led to a cascade of errors.
The root cause is in the _resolve_labels function. This means we need
a two-pass assembly where the first pass calculates sizes. The fix
is straightforward: iterate once for sizes, then emit bytes.

## What I'd Do Next
What I'd do next:
1. Fix _resolve_labels() in cross_asm.py using the two-pass approach
2. Run conformance vectors 0x00A1-0x00A8 against edge target
3. Write a captain's log about the offset bug

## What I'm Uncertain About
I'm uncertain if the two-pass approach will break cloud encoding.
I don't know if the existing tests cover this case. I might be wrong
about the root cause - it could also be in the byte encoder.

## Next steps
Review the fix carefully before committing."""

        result = score_handoff(letter)
        assert result["passes"] is True
        assert result["average"] >= 4.5

    def test_fails_threshold(self):
        """A terrible letter should fail."""
        letter = "ok bye"
        result = score_handoff(letter)
        assert result["passes"] is False

    def test_scores_capped_at_10(self):
        # Spam specific terms way beyond the cap
        letter = "line " * 20 + "0x " * 20 + "byte " * 20 + "offset " * 20
        result = score_handoff(letter)
        assert result["scores"]["surplus_insight"] <= 10

    def test_scores_capped_at_10_causal(self):
        letter = "because " * 20 + "caused " * 20
        result = score_handoff(letter)
        assert result["scores"]["causal_chain"] <= 10

    def test_all_score_categories_present(self):
        result = score_handoff("test")
        expected_keys = {
            "surplus_insight", "causal_chain", "honesty",
            "actionable_signal", "compression", "human_compat", "precedent_value",
        }
        assert set(result["scores"].keys()) == expected_keys


# ═══════════════════════════════════════════════════════════
# generate_autobiography()
# ═══════════════════════════════════════════════════════════

class TestGenerateAutobiography:
    def test_empty_handoffs(self):
        result = generate_autobiography([])
        assert "Generations: 0" in result
        assert "# Autobiography" in result

    def test_single_handoff(self):
        handoffs = [{
            "generation": 1,
            "letter": "## Where Things Stand\nWorking on the assembler.\nIt is 50% done.",
            "score": {"average": 7.0},
        }]
        result = generate_autobiography(handoffs)
        assert "Generations: 1" in result
        assert "Gen-1" in result
        assert "score: 7.0" in result

    def test_multiple_handoffs(self):
        handoffs = [
            {"generation": 1, "letter": "## Where Things Stand\nFirst gen.", "score": {"average": 5.0}},
            {"generation": 2, "letter": "## Where Things Stand\nSecond gen.", "score": {"average": 6.5}},
        ]
        result = generate_autobiography(handoffs)
        assert "Generations: 2" in result
        assert "Gen-1" in result
        assert "Gen-2" in result

    def test_extracts_where_things_stand(self):
        handoffs = [{
            "generation": 1,
            "letter": "## Where Things Stand\nThe assembler is done.\nAll tests pass.",
            "score": {"average": 8.0},
        }]
        result = generate_autobiography(handoffs)
        assert "assembler is done" in result

    def test_extracts_what_i_was_thinking(self):
        handoffs = [{
            "generation": 1,
            "letter": "## What I Was Thinking\nThe bug is in the loop.\nNeed to fix it.",
            "score": {"average": 7.0},
        }]
        result = generate_autobiography(handoffs)
        assert "bug is in the loop" in result

    def test_missing_generation_defaults_to_str(self):
        handoffs = [{"generation": None, "letter": "test", "score": {}}]
        result = generate_autobiography(handoffs)
        # None is present but value is None, which Python formats as 'None'
        assert "Gen-None" in result

    def test_missing_score_defaults_to_question_mark(self):
        handoffs = [{"generation": 1, "letter": "test", "score": {}}]
        result = generate_autobiography(handoffs)
        assert "score: ?" in result

    def test_no_matching_sections(self):
        handoffs = [{
            "generation": 1,
            "letter": "Just some random text without section headers.",
            "score": {"average": 3.0},
        }]
        result = generate_autobiography(handoffs)
        assert "Gen-1" in result
        # Summary should be empty since no matching sections
        lines = result.strip().split("\n")
        # Should have header, generation count, gen header, and empty summary
        assert len(lines) >= 3


# ═══════════════════════════════════════════════════════════
# Baton class
# ═══════════════════════════════════════════════════════════

class TestBatonInit:
    def test_default_init(self):
        b = Baton("my-vessel")
        assert b.vessel == "my-vessel"
        assert b.keeper_url == KEEPER_URL
        assert b.generation == 0
        assert b.state == {}
        assert b.handoff == ""
        assert b._lease_id is None

    def test_custom_keeper_url(self):
        b = Baton("vessel", keeper_url="http://custom:9000")
        assert b.keeper_url == "http://custom:9000"

    def test_keeper_url_trailing_slash_stripped(self):
        b = Baton("vessel", keeper_url="http://custom:9000/")
        assert b.keeper_url == "http://custom:9000"

    def test_with_credentials(self):
        b = Baton("vessel", agent_id="agent-1", agent_secret="secret-1")
        assert b.agent_id == "agent-1"
        assert b.agent_secret == "secret-1"

    def test_repo_with_slash(self):
        b = Baton("SuperInstance/my-vessel")
        assert b._repo() == "SuperInstance/my-vessel"

    def test_repo_without_slash(self):
        b = Baton("my-vessel")
        assert b._repo() == "SuperInstance/my-vessel"


class TestBatonRestore:
    def _make_baton(self, files=None):
        """Create a Baton with mocked keeper that returns given files."""
        files = files or {}
        b = Baton("test-vessel")

        def mock_keeper(method, path, body=None):
            repo_path = "/file/SuperInstance/test-vessel/"
            if path.startswith(repo_path):
                file_path = path[len(repo_path):]
                content = files.get(file_path)
                if content is not None:
                    return {"content": content}
                return {"error": "not found"}
            return {}

        b._keeper = mock_keeper
        return b

    def test_fresh_restore_no_baton(self):
        b = self._make_baton()
        state = b.restore()
        assert state["generation"] == 0
        assert state["identity"] == {}
        assert state["handoff"] == ""
        assert b.generation == 0

    def test_restore_generation(self):
        b = self._make_baton({".baton/GENERATION": "5"})
        state = b.restore()
        assert state["generation"] == 5
        assert b.generation == 5

    def test_restore_invalid_generation(self):
        b = self._make_baton({".baton/GENERATION": "not_a_number"})
        state = b.restore()
        assert state["generation"] == 0

    def test_restore_state_json(self):
        machine = json.dumps({
            "energy": {"remaining": 300, "budget": 1000},
            "open_threads": ["task-1", "task-2"],
            "skills": {"python": 0.9, "rust": 0.7},
            "trust": {"other-agent": 0.8},
            "intentions": ["finish-bug-fix"],
        })
        b = self._make_baton({
            ".baton/GENERATION": "1",
            ".baton/CURRENT/STATE.json": machine,
        })
        state = b.restore()
        assert state["energy"]["remaining"] == 300
        assert len(state["open_threads"]) == 2
        assert state["skills"]["python"] == 0.9

    def test_restore_handoff(self):
        handoff = "# Handoff Letter\n## Where Things Stand\nWorking on it."
        b = self._make_baton({
            ".baton/GENERATION": "2",
            ".baton/CURRENT/HANDOFF.md": handoff,
        })
        state = b.restore()
        assert state["handoff"] == handoff
        assert b.handoff == handoff

    def test_restore_identity(self):
        identity = json.dumps({"name": "flux-agent", "type": "builder"})
        b = self._make_baton({
            ".baton/GENERATION": "1",
            ".baton/IDENTITY.json": identity,
        })
        state = b.restore()
        assert state["identity"]["name"] == "flux-agent"

    def test_restore_autobiography(self):
        autobio = "# Autobiography\n## Gen-1\nWorked on assembler."
        b = self._make_baton({
            ".baton/GENERATION": "1",
            ".baton/AUTOBIOGRAPHY.md": autobio,
        })
        state = b.restore()
        assert state["autobiography"] == autobio
        assert b.autobiography_text == autobio

    def test_restore_fitness_history(self):
        fitness = json.dumps([{"generation": 1, "confidence": 0.5}])
        b = self._make_baton({
            ".baton/GENERATION": "1",
            ".baton/evolution/fitness_history.json": fitness,
        })
        state = b.restore()
        assert len(state["fitness_history"]) == 1
        assert state["fitness_history"][0]["confidence"] == 0.5

    def test_restore_invalid_json_gracefully(self):
        b = self._make_baton({
            ".baton/GENERATION": "1",
            ".baton/CURRENT/STATE.json": "NOT VALID JSON{{{",
        })
        state = b.restore()
        # Should not crash; energy remains default
        assert state["energy"] == {}

    def test_restore_full_baton(self):
        """Test restoring a complete baton with all files."""
        b = self._make_baton({
            ".baton/GENERATION": "3",
            ".baton/CURRENT/STATE.json": json.dumps({
                "energy": {"remaining": 150, "budget": 1000},
                "open_threads": ["bug-42"],
                "skills": {"asm": 0.95},
                "trust": {},
                "intentions": ["fix-bug"],
            }),
            ".baton/CURRENT/HANDOFF.md": "# Handoff\nWorking.",
            ".baton/IDENTITY.json": json.dumps({"name": "agent-3", "type": "fixer"}),
            ".baton/AUTOBIOGRAPHY.md": "# Auto\nGen 1-3 history.",
            ".baton/evolution/fitness_history.json": json.dumps([
                {"generation": 1, "confidence": 0.3},
                {"generation": 2, "confidence": 0.6},
                {"generation": 3, "confidence": 0.8},
            ]),
        })
        state = b.restore()
        assert state["generation"] == 3
        assert state["energy"]["remaining"] == 150
        assert state["identity"]["name"] == "agent-3"
        assert len(state["fitness_history"]) == 3


class TestBatonSnapshot:
    def _make_baton(self, write_results=None):
        """Create a Baton with mocked write and keeper."""
        write_results = write_results or {}
        b = Baton("test-vessel")

        write_log = []

        def mock_write(path, content, message):
            write_log.append({"path": path, "message": message})
            return write_results.get(path, {"ok": True})

        def mock_keeper(method, path, body=None):
            return {}

        b._write = mock_write
        b._keeper = mock_keeper
        b.write_log = write_log
        return b

    def test_snapshot_basic(self):
        b = self._make_baton()
        b.state = {"energy": {"remaining": 500}}
        # Use force=True to bypass quality gate for basic write testing
        result = b.snapshot({
            "handoff": "Found a bug at line 42.",
            "energy_remaining": 500,
            "confidence": 0.7,
        }, force=True)
        assert result["status"] == "packed"
        assert result["generation"] == 1
        assert b.generation == 1
        assert len(b.write_log) >= 8  # Multiple file writes

    def test_snapshot_writes_generation_last(self):
        b = self._make_baton()
        b.state = {}
        result = b.snapshot({
            "handoff": "",
            "energy_remaining": 500,
        })
        # GENERATION should be the last file written
        assert b.write_log[-1]["path"] == ".baton/GENERATION"

    def test_snapshot_quality_gate_fails(self):
        """A poor handoff should fail quality gate and not pack."""
        b = self._make_baton()
        b.state = {}
        result = b.snapshot({
            "handoff": "ok bye",  # Terrible handoff
            "energy_remaining": 500,
        })
        assert result["status"] == "quality_gate_failed"
        assert result["quality"]["passes"] is False
        # No files should be written when quality gate fails
        assert len(b.write_log) == 0

    def test_snapshot_force_bypass_quality(self):
        """force=True should pack regardless of quality."""
        b = self._make_baton()
        b.state = {}
        result = b.snapshot({
            "handoff": "ok bye",
            "energy_remaining": 500,
        }, force=True)
        assert result["status"] == "packed"
        assert result["generation"] == 1

    def test_snapshot_increments_generation(self):
        b = self._make_baton()
        b.generation = 2
        b.state = {}
        result = b.snapshot({
            "handoff": "",
            "energy_remaining": 500,
        })
        assert result["generation"] == 3
        assert b.generation == 3

    def test_snapshot_empty_handoff(self):
        """Empty handoff should still pack (no quality check)."""
        b = self._make_baton()
        b.state = {}
        result = b.snapshot({
            "handoff": "",
            "energy_remaining": 500,
        })
        assert result["status"] == "packed"

    def test_snapshot_good_handoff_passes(self):
        letter = """## Where Things Stand
The assembler is done. Found a bug at line 42 in the register file.
The error was caused by a missing bounds check on the byte offset.

## What I Was Thinking
The bug was caused by a missing bounds check. This meant writes
could overflow which led to memory corruption. The root cause is
in the _write_register function. The fix is to add a check at
the start of the function. This pattern is systemic.

## What I'd Do Next
What I'd do next:
1. Add bounds check to _write_register
2. Run tests against edge target
3. Commit the fix

## Uncertain
I'm uncertain if this breaks cloud encoding. I don't know the full
impact. It might need testing across all targets."""
        b = self._make_baton()
        b.state = {}
        result = b.snapshot({
            "handoff": letter,
            "energy_remaining": 500,
            "confidence": 0.8,
        })
        assert result["status"] == "packed"
        assert result["quality"]["passes"] is True

    def test_snapshot_writes_expected_files(self):
        b = self._make_baton()
        b.state = {}
        # Use force to bypass quality gate and test file writes
        b.snapshot({
            "handoff": "Some handoff about a bug at line 42.",
            "energy_remaining": 800,
        }, force=True)
        paths = [w["path"] for w in b.write_log]
        assert any("STATE.json" in p for p in paths)
        assert any("GENERATION" in p for p in paths)
        assert any("IDENTITY.json" in p for p in paths)
        assert any("SCORE.json" in p for p in paths)
        assert any("AUTOBIOGRAPHY.md" in p for p in paths)
        assert any("fitness_history.json" in p for p in paths)


class TestBatonWriteHandoff:
    def test_basic_handoff(self):
        b = Baton("test-vessel")
        b.state = {"energy": {"remaining": 500, "budget": 1000}, "identity": {"confidence": 0.7}}
        letter = b.write_handoff(
            who_i_was="Builder agent",
            where_things_stand="Assembler is 90% done",
            what_i_was_thinking="Need to fix offset bug",
            what_id_do_next="Fix the bug",
            what_im_uncertain_about="Not sure about cloud encoding",
        )
        assert "# Handoff Letter" in letter
        assert "Who I Was" in letter
        assert "Where Things Stand" in letter
        assert "Builder agent" in letter
        assert "90% done" in letter
        assert "Energy: 500/1000" in letter
        assert "Confidence: 0.7" in letter

    def test_handoff_with_open_threads(self):
        b = Baton("test-vessel")
        b.generation = 3
        b.state = {}
        letter = b.write_handoff(
            who_i_was="Agent",
            where_things_stand="Working",
            what_i_was_thinking="Thinking",
            what_id_do_next="Next steps",
            what_im_uncertain_about="Uncertain",
            open_threads=["task-1", "task-2"],
        )
        assert "- task-1" in letter
        assert "- task-2" in letter
        assert "Generation 4" in letter

    def test_handoff_includes_tasks(self):
        b = Baton("test-vessel")
        b.state = {}
        letter = b.write_handoff(
            who_i_was="Agent",
            where_things_stand="Working",
            what_i_was_thinking="Thinking",
            what_id_do_next="Next steps",
            what_im_uncertain_about="Uncertain",
            tasks_completed=12,
            tasks_failed=2,
        )
        assert "Tasks completed: 12" in letter
        assert "Tasks failed: 2" in letter

    def test_handoff_default_open_threads(self):
        b = Baton("test-vessel")
        b.state = {}
        letter = b.write_handoff(
            who_i_was="Agent",
            where_things_stand="Working",
            what_i_was_thinking="Thinking",
            what_id_do_next="Next steps",
            what_im_uncertain_about="Uncertain",
        )
        assert "- None" in letter


class TestBatonPrintRestoreSummary:
    def test_fresh_agent(self, capsys):
        b = Baton("test-vessel")
        b.state = {"generation": 0}
        b.print_restore_summary()
        output = capsys.readouterr().out
        assert "fresh agent" in output.lower() or "Gen-0" in output

    def test_restored_agent(self, capsys):
        b = Baton("test-vessel")
        b.state = {
            "generation": 3,
            "identity": {"name": "fixer", "type": "builder"},
            "energy": {"remaining": 400, "budget": 1000},
            "open_threads": ["task-1", "task-2", "task-3"],
            "skills": {"python": 0.95, "rust": 0.8, "go": 0.7},
            "handoff": "# Handoff Letter — Generation 3\n## Where Things Stand\nWorking on assembler.",
            "fitness_history": [{"generation": 1}, {"generation": 2}],
        }
        b.print_restore_summary()
        output = capsys.readouterr().out
        assert "Generation 3" in output
        assert "fixer" in output
        assert "400/1000" in output
        assert "3" in output  # open threads count
        assert "python" in output.lower()
        assert "Handoff Letter" in output
        assert "2 generations" in output


class TestBatonAcquireLease:
    def test_acquire_lease_success(self):
        b = Baton("test-vessel", agent_id="agent-1")
        b._keeper = MagicMock(return_value={"lease_id": "lease-123"})
        result = b.acquire_lease()
        assert result is True
        assert b._lease_id == "lease-123"

    def test_acquire_lease_failure(self):
        b = Baton("test-vessel", agent_id="agent-1")
        b._keeper = MagicMock(return_value={"error": "no lease available"})
        result = b.acquire_lease()
        assert result is False
        assert b._lease_id is None


class TestBatonKeeper:
    def test_keeper_url_construction(self):
        b = Baton("test-vessel", keeper_url="http://localhost:9000")
        assert b.keeper_url == "http://localhost:9000"

    @patch("flux_baton.urllib.request.urlopen")
    def test_keeper_handles_errors(self, mock_urlopen):
        b = Baton("test-vessel", agent_id="a1", agent_secret="s1")
        mock_urlopen.side_effect = Exception("Connection refused")
        result = b._keeper("GET", "/file/SuperInstance/test-vessel/.baton/GENERATION")
        assert "error" in result
        assert "Connection refused" in result["error"]
