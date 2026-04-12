#!/usr/bin/env python3
"""flux-baton v2 — Refined generational context handoff.

Changes from v1:
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
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

KEEPER_URL = os.environ.get("KEEPER_URL", "http://127.0.0.1:8900")


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


# ── Baton v2 ──

class Baton:
    """FLUX-native baton v2 — refined generational handoff."""

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
        """
        state = {
            "generation": 0, "identity": {}, "energy": {},
            "open_threads": [], "intentions": [], "skills": {},
            "trust": {}, "diary": "", "handoff": "",
            "autobiography": "", "fitness_history": [],
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
        """
        new_gen = self.generation + 1
        ts = datetime.now(timezone.utc).isoformat()
        handoff_text = agent_state.get("handoff", "")
        
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
        # In v2: just write current gen's summary. Full chain requires reading all letters.
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
        
        # Write 9: GENERATION (COMMIT MARKER — written LAST)
        results.append(self._write(".baton/GENERATION",
            str(new_gen), f"baton: GENERATION → {new_gen} (commit)"))
        
        # Send I2I notification
        self._keeper("POST", "/i2i", {
            "target": self._repo(),
            "type": "BATON_PACKED",
            "payload": {"generation": new_gen, "score": quality.get("average", 0)},
            "confidence": agent_state.get("confidence", 0.5),
        })
        
        success_count = len([r for r in results if isinstance(r, dict) and "error" not in r])
        
        self.generation = new_gen
        
        return {
            "status": "packed",
            "generation": new_gen,
            "files_written": success_count,
            "quality": quality,
        }
    
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
        
        letter = f"""# Handoff Letter — Generation {self.generation + 1}

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
            print("📋 No baton found — this is a fresh agent (Gen-0)")
            return
        
        print(f"📋 Baton restored — Generation {gen}")
        
        identity = s.get("identity", {})
        if identity:
            print(f"   Identity: {identity.get('name', '?')} ({identity.get('type', '?')})")
        
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
        
        if s.get("handoff"):
            lines = s["handoff"].strip().split("\n")
            print(f"   Latest handoff: {lines[0][:60]}...")
        
        fitness = s.get("fitness_history", [])
        if fitness:
            print(f"   Fitness history: {len(fitness)} generations tracked")


# ── CLI ──

def main():
    import argparse
    p = argparse.ArgumentParser(description="flux-baton v2")
    p.add_argument("action", choices=["restore", "snapshot", "boot", "score"])
    p.add_argument("--vessel", required=True)
    p.add_argument("--keeper", default="http://127.0.0.1:8900")
    p.add_argument("--secret", default=None)
    p.add_argument("--file", default=None, help="File to score")
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
            print("✅ PASSED quality gate")
        else:
            print("❌ FAILED quality gate — rewrite needed")
    
    elif args.action == "restore":
        state = baton.restore()
        baton.print_restore_summary()
    
    elif args.action == "boot":
        print(f"🚀 Booting {args.vessel}...")
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
        print(f"\n✅ {args.vessel} ONLINE — generation {baton.generation}")
    
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
        
        result = baton.snapshot(agent_state)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
