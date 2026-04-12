#!/usr/bin/env python3
"""flux-baton — Generational context handoff for FLUX-native agents.

Agents pack their brain into git, pass it to the next generation,
and the next gen picks up exactly where they left off.
"""

import json
import os
import sys
import time
import hashlib
import base64
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional

KEEPER_URL = os.environ.get("KEEPER_URL", "http://127.0.0.1:8900")


class Baton:
    """FLUX-native baton for generational context handoff.
    
    The baton IS the agent's brain, serialized to git.
    Next generation downloads it and becomes the same agent.
    """

    def __init__(self, vessel: str, keeper_url: str = KEEPER_URL,
                 agent_id: str = None, agent_secret: str = None):
        self.vessel = vessel
        self.keeper_url = keeper_url.rstrip("/")
        self.agent_id = agent_id
        self.agent_secret = agent_secret
        self.generation = 0
        self.state = {}
        self.autobiography = []
    
    # ── Keeper Communication ──
    
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
    
    # ── Read Baton from Git ──
    
    def restore(self) -> dict:
        """Unpack the baton — read agent state from vessel repo.
        
        This is what a new generation does at boot:
        1. Read GENERATION counter
        2. Read IDENTITY, ENERGY, OPEN_THREADS
        3. Read latest HANDOFF.md
        4. Read full autobiography (all handoff letters)
        5. Set self.generation for next handoff
        """
        # Resolve vessel repo name
        repo = self._resolve_repo()
        if not repo:
            return {"error": "vessel repo not found"}
        
        state = {"generation": 0, "identity": {}, "energy": {}, 
                 "open_threads": [], "diary": "", "handoff": "", 
                 "autobiography": [], "skills": {}, "trust": {}}
        
        # Read generation counter
        gen_data = self._keeper("GET", f"/file/{repo}/.baton/GENERATION")
        if gen_data.get("content"):
            try:
                state["generation"] = int(gen_data["content"].strip())
                self.generation = state["generation"]
            except:
                state["generation"] = 0
        
        # Read identity
        id_data = self._keeper("GET", f"/file/{repo}/.baton/IDENTITY.json")
        if id_data.get("content"):
            try:
                state["identity"] = json.loads(id_data["content"])
            except: pass
        
        # Read energy
        en_data = self._keeper("GET", f"/file/{repo}/.baton/ENERGY.json")
        if en_data.get("content"):
            try:
                state["energy"] = json.loads(en_data["content"])
            except: pass
        
        # Read open threads
        threads_data = self._keeper("GET", f"/file/{repo}/.baton/OPEN_THREADS.json")
        if threads_data.get("content"):
            try:
                state["open_threads"] = json.loads(threads_data["content"])
            except: pass
        
        # Read diary
        diary_data = self._keeper("GET", f"/file/{repo}/.baton/DIARY.md")
        if diary_data.get("content"):
            state["diary"] = diary_data["content"]
        
        # Read skills
        skills_data = self._keeper("GET", f"/file/{repo}/.baton/SKILLS.json")
        if skills_data.get("content"):
            try:
                state["skills"] = json.loads(skills_data["content"])
            except: pass
        
        # Read trust scores
        trust_data = self._keeper("GET", f"/file/{repo}/.baton/TRUST.json")
        if trust_data.get("content"):
            try:
                state["trust"] = json.loads(trust_data["content"])
            except: pass
        
        # Read autobiography (all handoff letters)
        state["autobiography"] = []
        for i in range(1, self.generation + 1):
            letter = self._keeper("GET", f"/file/{repo}/.baton/generations/v{i}/HANDOFF.md")
            if letter.get("content"):
                state["autobiography"].append({
                    "generation": i,
                    "letter": letter["content"]
                })
        
        # Read latest handoff
        if self.generation > 0:
            latest = self._keeper("GET", 
                f"/file/{repo}/.baton/generations/v{self.generation}/HANDOFF.md")
            if latest.get("content"):
                state["handoff"] = latest["content"]
        
        self.state = state
        return state
    
    # ── Write Baton to Git ──
    
    def snapshot(self, agent_state: dict) -> dict:
        """Pack the baton — serialize agent state to vessel repo.
        
        This is what an agent does when context is filling up:
        1. Increment generation
        2. Write all state files
        3. Write handoff letter
        4. Commit via keeper
        """
        repo = self._resolve_repo()
        if not repo:
            return {"error": "vessel repo not found"}
        
        self.generation += 1
        gen = self.generation
        ts = datetime.now(timezone.utc).isoformat()
        
        results = []
        
        # Write generation counter
        results.append(self._keeper("POST", f"/file/{repo}/.baton/GENERATION",
            {"content": str(gen), "message": f"baton: generation {gen}"}))
        
        # Write identity
        results.append(self._keeper("POST", f"/file/{repo}/.baton/IDENTITY.json",
            {"content": json.dumps(agent_state.get("identity", {}), indent=2),
             "message": f"baton: identity snapshot gen-{gen}"}))
        
        # Write energy
        results.append(self._keeper("POST", f"/file/{repo}/.baton/ENERGY.json",
            {"content": json.dumps({
                "remaining": agent_state.get("energy_remaining", 0),
                "budget": agent_state.get("energy_budget", 1000),
                "generation": gen,
                "timestamp": ts,
            }, indent=2),
             "message": f"baton: energy snapshot gen-{gen}"}))
        
        # Write open threads
        results.append(self._keeper("POST", f"/file/{repo}/.baton/OPEN_THREADS.json",
            {"content": json.dumps(agent_state.get("open_threads", []), indent=2),
             "message": f"baton: open threads gen-{gen}"}))
        
        # Write diary
        results.append(self._keeper("POST", f"/file/{repo}/.baton/DIARY.md",
            {"content": agent_state.get("diary", ""),
             "message": f"baton: diary gen-{gen}"}))
        
        # Write skills
        results.append(self._keeper("POST", f"/file/{repo}/.baton/SKILLS.json",
            {"content": json.dumps(agent_state.get("skills", {}), indent=2),
             "message": f"baton: skills gen-{gen}"}))
        
        # Write trust
        results.append(self._keeper("POST", f"/file/{repo}/.baton/TRUST.json",
            {"content": json.dumps(agent_state.get("trust", {}), indent=2),
             "message": f"baton: trust scores gen-{gen}"}))
        
        # Write handoff letter
        handoff = agent_state.get("handoff", "")
        if handoff:
            results.append(self._keeper("POST",
                f"/file/{repo}/.baton/generations/v{gen}/HANDOFF.md",
                {"content": handoff,
                 "message": f"baton: handoff letter gen-{gen}"}))
        
        # Send I2I BATON_PASS to keeper
        self._keeper("POST", "/i2i", {
            "target": repo,
            "type": "BATON_PASS",
            "payload": {"generation": gen, "timestamp": ts},
            "confidence": agent_state.get("confidence", 0.5),
        })
        
        return {
            "status": "packed",
            "generation": gen,
            "files_written": len([r for r in results if "error" not in r]),
        }
    
    # ── Handoff Letter Builder ──
    
    def write_handoff(self, who_i_was: str, where_things_stand: str,
                      what_i_was_thinking: str, what_id_do_next: str,
                      what_im_uncertain_about: str,
                      open_threads: list = None) -> str:
        """Build a handoff letter using the Captain's Log Academy voice."""
        
        threads_text = ""
        if open_threads:
            for t in open_threads:
                threads_text += f"- {t}\n"
        else:
            threads_text = "None"
        
        energy = self.state.get("energy", {})
        confidence = self.state.get("identity", {}).get("confidence", 0.5)
        
        letter = f"""# Handoff Letter — Generation {self.generation}

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
- Generation: {self.generation}
- Timestamp: {datetime.now(timezone.utc).isoformat()}

## Open Threads
{threads_text}

Good luck. You know more than you think.
— Gen-{self.generation}
"""
        return letter
    
    # ── Utility ──
    
    def _resolve_repo(self) -> Optional[str]:
        """Resolve vessel name to full repo path."""
        if "/" in self.vessel:
            return self.vessel
        return f"SuperInstance/{self.vessel}"
    
    def print_restore_summary(self):
        """Print a human-readable summary of the restored state."""
        s = self.state
        gen = s.get("generation", 0)
        
        if gen == 0:
            print("📋 No baton found — this is a fresh agent (Gen-0)")
            return
        
        print(f"📋 Baton restored — Generation {gen}")
        print(f"   Handoff letters: {len(s.get('autobiography', []))}")
        
        identity = s.get("identity", {})
        if identity:
            print(f"   Identity: {identity.get('name', '?')} ({identity.get('type', '?')})")
        
        energy = s.get("energy", {})
        if energy:
            print(f"   Energy: {energy.get('remaining', '?')}/{energy.get('budget', '?')}")
        
        threads = s.get("open_threads", [])
        if threads:
            print(f"   Open threads: {len(threads)}")
        
        if s.get("handoff"):
            # Show last 5 lines of latest handoff
            lines = s["handoff"].strip().split("\n")
            print(f"   Latest handoff: {lines[0][:60]}...")


# ── CLI ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description="flux-baton — generational context handoff")
    parser.add_argument("action", choices=["restore", "snapshot", "boot"], 
                       help="Action: restore (read baton), snapshot (write baton), boot (restore+register)")
    parser.add_argument("--vessel", required=True, help="Vessel repo name")
    parser.add_argument("--keeper", default="http://127.0.0.1:8900", help="Keeper URL")
    parser.add_argument("--secret", help="Agent secret (from registration)")
    args = parser.parse_args()
    
    baton = Baton(args.vessel, args.keeper, agent_id=args.vessel, agent_secret=args.secret)
    
    if args.action == "restore":
        state = baton.restore()
        baton.print_restore_summary()
    
    elif args.action == "snapshot":
        # Interactive snapshot — prompt for handoff fields
        print("Packing baton...")
        print("Answer these questions for the next generation:\n")
        
        who = input("Who were you? ")
        where = input("Where do things stand? ")
        thinking = input("What were you thinking? ")
        next_steps = input("What would you do next? ")
        uncertain = input("What are you uncertain about? ")
        
        letter = baton.write_handoff(who, where, thinking, next_steps, uncertain)
        
        state = {
            "identity": {"name": args.vessel, "type": "agent"},
            "energy_remaining": 200,
            "energy_budget": 1000,
            "diary": "See handoff letter.",
            "handoff": letter,
            "open_threads": [],
            "skills": {},
            "trust": {},
        }
        
        result = baton.snapshot(state)
        print(f"\n✅ Baton packed: generation {result.get('generation', '?')}")
    
    elif args.action == "boot":
        # Full boot sequence: register + restore + display
        print(f"🚀 Booting {args.vessel}...")
        
        # Register with keeper
        reg = baton._keeper("POST", "/register", {"vessel": args.vessel})
        if "secret" in reg:
            baton.agent_secret = reg["secret"]
            print(f"   Registered: {reg['status']}")
            print(f"   Secret: {reg['secret'][:8]}...")
        
        # Restore baton
        state = baton.restore()
        baton.print_restore_summary()
        
        if state.get("handoff"):
            print(f"\n{'='*50}")
            print("LATEST HANDOFF LETTER:")
            print(f"{'='*50}")
            print(state["handoff"][:1000])
        
        print(f"\n✅ {args.vessel} ONLINE — generation {baton.generation}")


if __name__ == "__main__":
    main()
