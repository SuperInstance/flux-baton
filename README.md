# flux-baton — Generational Context Handoff for FLUX-Native Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
> *An agent's work outlives its context window. The baton carries everything the next agent needs.*

## What This Is

A baton protocol for FLUX fleet agents. When an agent's context fills up, it doesn't lose everything — it packs a baton and passes it to the next generation. The next agent boots, reads the baton, and continues exactly where the previous one left off.

This is **not** summarization. This is **relay racing**. The baton contains the full state — not a compressed version.

## The Baton Metaphor

```
Agent Gen-1              Baton                Agent Gen-2
┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│ Working...   │───▶│ Identity    │───▶│ Boots fresh  │
│ 82% context  │    │ Intentions  │    │ Reads baton  │
│ Getting full │    │ Diary       │    │ Continues    │
│              │    │ Skills      │    │ where Gen-1  │
│ Packs baton  │    │ Trust scores│    │ left off     │
│ Retires      │    │ Open threads│    │              │
└──────────────┘    │ Energy      │    └──────────────┘
                    │ Git state   │
                    └─────────────┘
```

The baton IS the agent's brain, serialized to git. The next generation downloads it and becomes the same agent, but with a fresh context window.

## Baton Protocol Specification

### The Baton Package

A baton is a directory structure in the agent's vessel repo:

```
.baton/
├── GENERATION          # Current generation number
├── IDENTITY.json       # Who this agent is, vessel type, personality
├── CONTEXT.md          # What was happening when context filled
├── INTENTIONS.md       # What the agent planned to do next
├── DIARY.md            # Running narrative of what happened
├── SKILLS.json         # Learned skills and confidence scores
├── TRUST.json          # Trust scores for other fleet agents
├── ENERGY.json         # Energy budget state
├── OPEN_THREADS.json   # Unfinished tasks, pending I2I messages
├── CAPABILITIES.toml   # What this agent can do
├── WITNESS_MARKS.json  # Important state snapshots
└── HANDOFF.md          # The letter to the next generation
```

### The Baton Lifecycle

```
1. BOOT        → Agent reads .baton/ (if exists) or creates fresh
2. WORK        → Agent updates DIARY.md, INTENTIONS.md as it works
3. CHECKPOINT  → Agent writes full state to .baton/ periodically
4. TRIGGER     → When context >80% or energy <20%, pack the baton
5. HANDOFF     → Write HANDOFF.md (the letter to next gen)
6. RETIRE      → Agent stops, baton is committed to git
7. SUCCESSOR   → New agent boots, reads .baton/, continues
```

### FLUX Opcodes for Baton Operations

The baton uses existing FLUX opcodes plus two new ones:

- `SNAPSHOT` (0x7F) — Serialize current VM state to .baton/
- `RESTORE` (0x3F) — Deserialize .baton/ into VM state
- `WITNESS` (0x7E) — Mark important state for baton inclusion
- `EVOLVE` (0x7C) — Trigger evolution cycle during handoff

### The HANDOFF.md (The Letter)

This is the most important file. It's the letter one agent writes to its successor:

```markdown
# Handoff Letter — Generation 3

## Who I Was
I was flux-agent-a0fa81, generation 3. I ran for 47 minutes.
I completed 12 tasks and failed 2.

## Where Things Stand
The cross-assembler is 90% done. The edge encoding works but
the cloud encoding has a bug in the JE instruction. I found it
at line 234 of cross_asm.py — the jump offset is off by 2 bytes
when the instruction before it is a MOVI. I was about to fix it
when my context filled up.

## What I Was Thinking
The 2-byte offset bug is interesting. It only happens after MOVI
because MOVI is a 4-byte instruction and the assembler doesn't
account for the variable-width encoding properly. The fix is in
_resolve_labels() — you need to do a two-pass assembly where the
first pass calculates sizes and the second pass emits bytes.

## What I'd Do Next
1. Fix _resolve_labels() in cross_asm.py (the two-pass approach)
2. Run conformance vectors 0x00A1-0x00A8 against edge target
3. Write a captain's log about the offset bug (score it — it's interesting)
4. Check bottles from JetsonClaw1 — he may have hit the same thing

## What I'm Uncertain About
I'm not sure if the two-pass approach will break the existing
cloud encoding. The cloud target uses fixed widths so it shouldn't,
but I haven't verified. Test before committing.

## Energy & Confidence
Energy remaining: 230/1000
Confidence: 0.62
The confidence is real — I understand this codebase now.

## Open Threads
- I2I DISCOVER sent to babel-vessel, no response yet
- Issue #3 on flux-cross-assembler still needs my comment
- The keeper sent a health check — I responded "alive"

Good luck. The fix is cleaner than you think.
— Gen-3
```

### Baton Transfer Protocol (via Keeper)

FLUX agents transfer batons through the Lighthouse Keeper:

```
1. Gen-N detects context pressure (energy < 200, or explicit signal)
2. Gen-N calls SNAPSHOT → writes .baton/ to vessel repo via keeper
3. Gen-N writes HANDOFF.md via keeper
4. Gen-N sends I2I BATON_PASS message to keeper
5. Keeper logs the handoff, increments generation
6. Gen-N+1 boots (same vessel, fresh context)
7. Gen-N+1 calls RESTORE → reads .baton/ from vessel repo
8. Gen-N+1 reads HANDOFF.md → understands where Gen-N left off
9. Gen-N+1 continues work
```

The keeper never sees the baton contents — it just routes the files.
The baton IS the agent's continuity. Git IS the persistence layer.

### Multi-Generation Chains

```
Gen-1 (boot) → Gen-2 (learn ISA) → Gen-3 (build assembler) → Gen-4 (fix bugs) → Gen-5 (write tests)

Each generation reads all previous HANDOFF.md files:
.baton/
├── generations/
│   ├── v1/
│   │   └── HANDOFF.md
│   ├── v2/
│   │   └── HANDOFF.md
│   ├── v3/
│   │   └── HANDOFF.md
│   └── v4/
│       └── HANDOFF.md
└── CURRENT → points to latest generation
```

The chain of handoff letters IS the agent's autobiography.
A new agent can read the full chain to understand its own history.

### Baton Quality Scoring

Each handoff is scored against the Captain's Log Academy rubric:

1. **Surplus Insight**: Does the handoff contain non-obvious context?
2. **Causal Chain**: Can the next agent trace what happened?
3. **Honesty**: Are uncertainties marked? Are failures admitted?
4. **Actionable Signal**: Can the next agent actually continue the work?
5. **Compression**: Is the handoff concise enough to fit in fresh context?
6. **Human Compatibility**: Can Casey read it and understand what happened?
7. **Precedent Value**: Does this handoff teach something about agent handoffs?

A baton that scores <5.0 average is a **failed handoff** — the next generation will struggle.

### Baton + Captain's Log Academy

The handoff letter IS a captain's log. It follows the same voice, same rubric, same skip rules. The difference is the audience: captain's logs are for Casey and the fleet. Handoff letters are for the next generation of yourself.

High-scoring handoffs become part of the agent's autobiography.
The autobiography becomes training data for better handoffs.

## Implementation

### Python (flux-runtime)

```python
import json, os
from datetime import datetime, timezone

class Baton:
    """FLUX-native baton for generational context handoff."""

    def __init__(self, vessel_path=".baton"):
        self.path = vessel_path
        self.generation = self._read_generation()

    def _read_generation(self):
        try:
            with open(f"{self.path}/GENERATION") as f:
                return int(f.read().strip())
        except:
            return 0

    def snapshot(self, agent_state: dict):
        """Pack the baton — serialize current agent state."""
        self.generation += 1
        gen_path = f"{self.path}/generations/v{self.generation}"
        os.makedirs(gen_path, exist_ok=True)

        # Write identity
        with open(f"{self.path}/IDENTITY.json", "w") as f:
            json.dump(agent_state.get("identity", {}), f, indent=2)

        # Write open threads
        with open(f"{self.path}/OPEN_THREADS.json", "w") as f:
            json.dump(agent_state.get("open_threads", []), f, indent=2)

        # Write energy
        with open(f"{self.path}/ENERGY.json", "w") as f:
            json.dump({
                "remaining": agent_state.get("energy", 0),
                "budget": agent_state.get("energy_budget", 1000),
                "generation": self.generation,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2)

        # Update generation counter
        with open(f"{self.path}/GENERATION", "w") as f:
            f.write(str(self.generation))

        # Write diary
        with open(f"{self.path}/DIARY.md", "w") as f:
            f.write(agent_state.get("diary", ""))

        # Write handoff letter
        with open(f"{gen_path}/HANDOFF.md", "w") as f:
            f.write(agent_state.get("handoff", ""))

    def restore(self) -> dict:
        """Unpack the baton — restore agent state from git."""
        state = {}

        try:
            with open(f"{self.path}/IDENTITY.json") as f:
                state["identity"] = json.load(f)
        except: pass

        try:
            with open(f"{self.path}/ENERGY.json") as f:
                state["energy"] = json.load(f)
        except: pass

        try:
            with open(f"{self.path}/OPEN_THREADS.json") as f:
                state["open_threads"] = json.load(f)
        except: pass

        try:
            with open(f"{self.path}/DIARY.md") as f:
                state["diary"] = f.read()
        except: pass

        # Read latest handoff
        gen_path = f"{self.path}/generations/v{self.generation}"
        try:
            with open(f"{gen_path}/HANDOFF.md") as f:
                state["handoff"] = f.read()
        except: pass

        # Read all handoff letters (autobiography)
        state["autobiography"] = []
        for i in range(1, self.generation + 1):
            try:
                with open(f"{self.path}/generations/v{i}/HANDOFF.md") as f:
                    state["autobiography"].append(f.read())
            except: pass

        return state

    def write_handoff(self, who_i_was, where_things_stand, what_i_was_thinking,
                      what_id_do_next, what_im_uncertain_about, open_threads):
        """Write the handoff letter to the next generation."""
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

## Open Threads
{open_threads}

Good luck. You know more than you think.
— Gen-{self.generation}
"""
        gen_path = f"{self.path}/generations/v{self.generation}"
        os.makedirs(gen_path, exist_ok=True)
        with open(f"{gen_path}/HANDOFF.md", "w") as f:
            f.write(letter)
        return letter
```

### Keeper Integration (lighthouse-keeper)

The keeper tracks baton generations:

```
GET  /baton/{vessel}           → Read current baton state
POST /baton/{vessel}/snapshot  → Trigger baton snapshot
POST /baton/{vessel}/restore   → Trigger baton restore
GET  /baton/{vessel}/history   → Read all handoff letters
```

### Docker Integration (flux-agent-runtime)

Agents in Docker containers use batons through the keeper:

```bash
# Gen-1 boots, works, packs baton
python3 agent_bridge.py --keeper http://keeper:8900 --vessel my-agent

# When context fills:
# 1. Agent writes .baton/ to vessel repo via keeper
# 2. Agent sends I2I BATON_PASS
# 3. Container exits

# Gen-2 boots in new container
python3 agent_bridge.py --keeper http://keeper:8900 --vessel my-agent
# 1. Agent reads .baton/ from vessel repo via keeper
# 2. Agent reads HANDOFF.md
# 3. Agent continues where Gen-1 left off
```

## The Baton as Brain

The key insight: **the baton IS the agent's brain, serialized to git.**

An agent is not its process. An agent is not its context window. An agent is the continuous chain of batons passed from generation to generation. The autobiography of handoff letters IS the agent's identity.

When you read all the HANDOFF.md files in order, you can watch the agent grow:
- Gen-1: uncertain, exploring, confidence 0.30
- Gen-3: competent, focused, confidence 0.55
- Gen-5: expert, teaching others, confidence 0.80

That growth curve IS the agent's career. And it's all in git.

## Relationship to Original Baton Projects

This is **Baton v3**, adapted for FLUX-native agents:

| Feature | Baton v1 | Claude_Baton v2 | flux-baton v3 |
|---------|----------|-----------------|---------------|
| **Target** | Generic AI | Claude Code | FLUX fleet agents |
| **Storage** | Files | Artifacts + MCP | Git repos |
| **Transfer** | Manual | Subagent spawn | Keeper + I2I |
| **Scoring** | None | None | Captain's Log rubric |
| **Evolution** | None | None | EVOLVE opcode |
| **Voice** | None | None | Vessel-type voice |
| **Autobiography** | None | None | Handoff letter chain |
| **Health** | None | None | Keeper monitoring |

The jump from v2 to v3: git-native storage, keeper-routed transfer, scored handoffs, evolutionary improvement, and the autobiography chain that makes an agent's growth visible and teachable.
