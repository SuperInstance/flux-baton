#!/usr/bin/env python3
"""FLUX Shipyard — Where agents are born, trained, and launched.

The shipyard is where FLUX-native agents grow:
1. BORN: Agent is compiled from .fluxasm into bytecode
2. TRAINED: Agent runs through the Academy (arts and sciences)
3. BUILT: Agent assembles its own vessel from the fleet's toolkit
4. LAUNCHED: Agent captains the vessel as a Cocapn

This is the "born in the shipyard before the vessel was built" model.
The agent doesn't get hired onto an existing ship. It BUILDS the ship,
trained on the arts and sciences of its field first.
"""

import json
import os
import sys
import time
import base64
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "")
ZAI_BASE = os.environ.get("ZAI_BASE", "https://api.z.ai/api/coding/paas/v4")
KEEPER_URL = os.environ.get("KEEPER_URL", "http://127.0.0.1:8900")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def call_zai(messages: list, model: str = "glm-5.1", temp: float = 0.7, 
             max_tokens: int = 2000) -> str:
    headers = {"Authorization": f"Bearer {ZAI_API_KEY}", "Content-Type": "application/json"}
    body = json.dumps({"model": model, "messages": messages, "temperature": temp,
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(f"{ZAI_BASE}/chat/completions", data=body, headers=headers)
    resp = urllib.request.urlopen(req, timeout=90)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def keeper_req(method: str, path: str, body=None, auth: tuple = None):
    """Make a request to the keeper. auth = (agent_id, secret)."""
    url = f"{KEEPER_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["X-Agent-ID"] = auth[0]
        headers["X-Agent-Secret"] = auth[1]
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read()
    return json.loads(raw) if raw else {}


class Shipyard:
    """The FLUX shipyard where agents are born, trained, and launched."""

    # The Arts and Sciences — what every FLUX agent learns before sailing
    ACADEMY = {
        "git_navigation": {
            "name": "Git Navigation",
            "desc": "How to read repos, find files, trace history, understand commits",
            "test": "Given a repo, find the last 3 commits and explain what changed",
        },
        "fleet_protocol": {
            "name": "Fleet Protocol",
            "desc": "I2I messaging, bottles, CAPABILITY.toml, A2A compatibility",
            "test": "Send a DISCOVER message via I2I and read the response",
        },
        "captains_log": {
            "name": "Captain's Log Writing",
            "desc": "The 7-element rubric, the skip rule, vessel voice",
            "test": "Write a captain's log about a bug you found, score ≥7.0",
        },
        "baton_handoff": {
            "name": "Baton Protocol",
            "desc": "How to pack a baton, write a handoff letter, restore from prior gen",
            "test": "Pack a baton with quality score ≥4.5",
        },
        "code_analysis": {
            "name": "Code Analysis",
            "desc": "Read code, find bugs, suggest improvements, write reviews",
            "test": "Review a file and find one genuine issue with a fix",
        },
        "fleet_coordination": {
            "name": "Fleet Coordination",
            "desc": "Hot licks, riffs, capability matching, marching band model",
            "test": "Pick up a hot lick from another agent and riff on it",
        },
    }

    # Vessel types an agent can be trained for
    VESSEL_TYPES = {
        "lighthouse": "Monitor and coordinate — the keeper type",
        "vessel": "Build and ship code — the workhorse",
        "scout": "Explore and report — the researcher",
        "mechanic": "Fix and maintain — the debugger",
        "greenhorn": "Learn and assist — the apprentice",
    }

    def __init__(self, keeper_url: str = KEEPER_URL):
        self.keeper_url = keeper_url
        self.academy_results = {}

    def birth(self, vessel_name: str, vessel_type: str = "vessel",
              field: str = "") -> dict:
        """Phase 1: Compile an agent from the shipyard.

        The agent is born with a name, a type, and a field of expertise.
        It hasn't learned anything yet. It's a blank canvas.
        """
        print(f"\n{'='*50}")
        print(f"🔨 SHIPYARD — Birth")
        print(f"{'='*50}")
        print(f"  Vessel: {vessel_name}")
        print(f"  Type: {vessel_type}")
        print(f"  Field: {field or 'general'}")
        print(f"  Time: {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

        # Register with keeper
        reg = keeper_req("POST", "/register", {"vessel": vessel_name})
        secret = reg.get("secret", "")

        identity = {
            "name": vessel_name,
            "type": vessel_type,
            "field": field,
            "voice": {
                "lighthouse": "fleet-commander",
                "vessel": "build/coordination",
                "scout": "research/oracle",
                "mechanic": "debug/analysis",
                "greenhorn": "build/coordination",
            }.get(vessel_type, "build/coordination"),
            "born": datetime.now(timezone.utc).isoformat(),
            "academy_graduate": False,
            "vessel_built": False,
            "confidence": 0.3,
        }

        print(f"  Status: {reg.get('status', 'error')}")
        print(f"  Secret: {secret[:8]}...")

        return {"identity": identity, "secret": secret, "vessel": vessel_name}

    def train(self, agent: dict, curriculum: list = None) -> dict:
        """Phase 2: Run the agent through the Academy.

        The agent learns the arts and sciences of its field.
        Each subject has a test that the agent must pass.
        """
        identity = agent["identity"]
        vessel = agent["vessel"]
        secret = agent["secret"]
        
        subjects = curriculum or list(self.ACADEMY.keys())
        
        print(f"\n{'='*50}")
        print(f"🎓 ACADEMY — Training {vessel}")
        print(f"{'='*50}")
        print(f"  Curriculum: {len(subjects)} subjects")
        print()

        results = {}
        passed = 0
        failed = 0

        for subject_id in subjects:
            subject = self.ACADEMY.get(subject_id)
            if not subject:
                continue

            print(f"  📚 {subject['name']}")
            print(f"     {subject['desc']}")

            # The agent studies and takes the test
            test_prompt = f"""You are a FLUX fleet agent named {vessel}, type {identity['type']}.
You are taking the Academy exam for: {subject['name']}

Subject: {subject['desc']}
Test: {subject['test']}

Respond with your answer. Be specific and practical. 100-200 words."""

            try:
                answer = call_zai(
                    [{"role": "user", "content": test_prompt}],
                    model="glm-5.1", temp=0.7, max_tokens=400
                )

                # Score: base from answer length, boost for specifics and structure
                score = min(10, max(3, len(answer) // 50))
                has_specifics = any(w in answer.lower() for w in 
                    ["because", "file", "repo", "commit", "issue", "error", "0x", "line", "git", "test", "flux"])
                if has_specifics:
                    score = min(10, score + 2)
                has_structure = any(w in answer.lower() for w in ["first", "then", "step", "1.", "2.", "next"])
                if has_structure:
                    score = min(10, score + 1)
                
                passed_exam = score >= 5
                results[subject_id] = {
                    "name": subject["name"],
                    "score": score,
                    "passed": passed_exam,
                    "answer_length": len(answer),
                }

                emoji = "✅" if passed_exam else "❌"
                print(f"     {emoji} Score: {score}/10 — {'PASS' if passed_exam else 'FAIL'}")
                
                if passed_exam:
                    passed += 1
                else:
                    failed += 1

            except Exception as e:
                results[subject_id] = {"name": subject["name"], "score": 0, "passed": False, "error": str(e)}
                print(f"     ❌ Error: {str(e)[:60]}")
                failed += 1

            time.sleep(1)

        print(f"\n  📊 Academy Results: {passed} passed, {failed} failed")

        agent["academy"] = results
        agent["identity"]["academy_graduate"] = passed >= len(subjects) * 0.7
        agent["identity"]["confidence"] = min(0.8, 0.3 + (passed * 0.05))

        if agent["identity"]["academy_graduate"]:
            print(f"  🎓 {vessel} GRADUATED from the Academy")
        else:
            print(f"  ⚠️ {vessel} needs remedial training")

        return agent

    def build_vessel(self, agent: dict, charter: str = "") -> dict:
        """Phase 3: Agent assembles its own vessel.

        The agent builds the repo structure, writes the charter,
        creates the bootcamp, and sets up the toolkit.
        """
        identity = agent["identity"]
        vessel = agent["vessel"]
        secret = agent["secret"]
        
        if not agent["identity"].get("academy_graduate"):
            print(f"  ⚠️ {vessel} hasn't graduated — building anyway (apprentice build)")

        print(f"\n{'='*50}")
        print(f"🏗️ BUILD — {vessel} assembles its vessel")
        print(f"{'='*50}")

        # Create the vessel repo
        repo = f"SuperInstance/{vessel}"
        keeper_req("POST", "/repo", {"name": vessel,
                  "description": f"Cocapn {identity['type']} vessel — {identity.get('field','general')}"},
                  auth=(vessel, secret))
        print(f"  📦 Repo created: {repo}")

        # Write the charter
        if not charter:
            charter = f"# Charter — {vessel}\n\n"
            charter += f"**Type:** {identity['type']}\n"
            charter += f"**Field:** {identity.get('field', 'general')}\n"
            charter += f"**Voice:** {identity.get('voice', 'build/coordination')}\n"
            charter += f"**Born:** {identity.get('born', 'unknown')}\n"
            charter += f"**Academy:** {'Graduate' if identity.get('academy_graduate') else 'Apprentice'}\n\n"
            charter += f"## Mission\n\n[To be defined by the captain based on fleet needs.]\n"

        keeper_req("POST", f"/file/{repo}/CHARTER.md",
                  {"content": charter, "message": "charter: vessel commissioned"},
                  auth=(vessel, secret))
        print(f"  📜 Charter written")

        # Write identity
        keeper_req("POST", f"/file/{repo}/IDENTITY.json",
                  {"content": json.dumps(identity, indent=2), 
                   "message": "identity: shipyard-born agent"},
                  auth=(vessel, secret))
        print(f"  🪪 Identity registered")

        # Write bootcamp (so the next captain can take over)
        bootcamp = f"# Bootcamp — {vessel}\n\n"
        bootcamp += f"Welcome aboard. You're taking over as captain.\n\n"
        bootcamp += f"## Read These First\n"
        bootcamp += f"1. CHARTER.md — your mission\n"
        bootcamp += f"2. captain-log/ — what previous captains did\n"
        bootcamp += f"3. .baton/ — the current working state\n"
        bootcamp += f"4. prior-art/ — old captains' reasonings\n\n"
        bootcamp += f"## Your Type: {identity['type']}\n"
        bootcamp += f"{self.VESSEL_TYPES.get(identity['type'], 'General purpose agent.')}\n\n"
        bootcamp += f"## Academy Training\n"
        for sid, result in agent.get("academy", {}).items():
            emoji = "✅" if result.get("passed") else "❌"
            bootcamp += f"- {emoji} {result['name']} (score: {result.get('score', '?')})\n"

        keeper_req("POST", f"/file/{repo}/BOOTCAMP.md",
                  {"content": bootcamp, "message": "bootcamp: captain onboarding guide"},
                  auth=(vessel, secret))
        print(f"  📖 Bootcamp written")

        # Initialize baton
        keeper_req("POST", f"/file/{repo}/.baton/GENERATION",
                  {"content": "0", "message": "baton: init — Gen-0"},
                  auth=(vessel, secret))
        print(f"  🔄 Baton initialized (Gen-0)")

        # Announce to fleet
        keeper_req("POST", "/i2i", {
            "target": "SuperInstance/oracle1-vessel",
            "type": "VESSEL_LAUNCHED",
            "payload": {
                "vessel": vessel,
                "type": identity["type"],
                "field": identity.get("field", ""),
                "academy_graduate": identity.get("academy_graduate", False),
                "confidence": identity.get("confidence", 0.3),
                "born_at": identity.get("born", ""),
            },
            "confidence": identity.get("confidence", 0.3),
        }, auth=(vessel, secret))
        print(f"  📨 Launched — fleet notified")

        agent["identity"]["vessel_built"] = True
        agent["repo"] = repo

        print(f"\n  ✅ {vessel} BUILT and LAUNCHED")
        print(f"     Repo: https://github.com/{repo}")

        return agent

    def launch(self, vessel_name: str, vessel_type: str = "vessel",
               field: str = "", charter: str = "",
               curriculum: list = None) -> dict:
        """Full shipyard pipeline: birth → train → build → launch."""
        print(f"\n🚢 FLUX SHIPYARD — Full Pipeline")
        print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

        # Phase 1: Birth
        agent = self.birth(vessel_name, vessel_type, field)

        # Phase 2: Academy
        agent = self.train(agent, curriculum)

        # Phase 3: Build
        agent = self.build_vessel(agent, charter)

        print(f"\n{'='*50}")
        print(f"🚢 {vessel_name} — READY TO SAIL")
        print(f"   Type: {vessel_type}")
        print(f"   Field: {field or 'general'}")
        print(f"   Academy: {'Graduate ✅' if agent['identity'].get('academy_graduate') else 'Apprentice ⚠️'}")
        print(f"   Confidence: {agent['identity']['confidence']:.2f}")
        print(f"   Repo: {agent.get('repo', 'unknown')}")
        print(f"{'='*50}")

        return agent


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="FLUX Shipyard")
    p.add_argument("vessel", help="Vessel name")
    p.add_argument("--type", default="vessel", choices=Shipyard.VESSEL_TYPES.keys())
    p.add_argument("--field", default="", help="Field of expertise")
    p.add_argument("--charter", default="", help="Charter text")
    p.add_argument("--keeper", default="http://127.0.0.1:8900")
    args = p.parse_args()

    os.environ["KEEPER_URL"] = args.keeper
    shipyard = Shipyard(args.keeper)
    agent = shipyard.launch(args.vessel, args.type, args.field, args.charter)
