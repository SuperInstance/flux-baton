# flux-baton Workshop — Design Review & Refinement

## Round 1: What's Wrong With It

### Problem 1: The Autobiography Grows Unbounded
If an agent runs 50 generations, Gen-50 reads 49 handoff letters.
That won't fit in a fresh context window.

**Fix: Layered autobiography.**
- L0 (always loaded): Latest handoff + generation counter + identity
- L1 (compressed): One-paragraph summary of each previous generation
- L2 (full): Individual handoff letters, loaded on demand

The baton should auto-generate L1 after each handoff:

```
.baton/
├── AUTOBIOGRAPHY.md     ← L1: compressed chain
├── generations/
│   ├── v1/HANDOFF.md    ← L2: full letter
│   ├── v2/HANDOFF.md
│   └── v3/HANDOFF.md
└── CURRENT/
    ├── HANDOFF.md       ← L0: latest letter (always read)
    └── STATE.json       ← L0: machine state (always read)
```

### Problem 2: No Quality Gate
A bad handoff is worse than no handoff. If Gen-N writes a vague
handoff ("stuff happened, things are broken"), Gen-N+1 is worse
off than if it had booted fresh.

**Fix: Baton quality scoring (from Captain's Log Academy).**

Before committing a handoff, score it against the 7-element rubric.
If average < 5.0, force the agent to rewrite. The keeper enforces this.

Minimum bar for each element:
- Surplus Insight ≥ 4 (must contain non-obvious context)
- Causal Chain ≥ 4 (must explain what happened)
- Honesty ≥ 5 (must mark uncertainties)
- Actionable Signal ≥ 5 (must give concrete next steps)
- Compression ≥ 3 (don't pad)
- Human Compatibility ≥ 4 (Casey must be able to read it)
- Precedent Value ≥ 3 (optional but nice)

Average must be ≥ 4.5 to commit. This is the quality gate.

### Problem 3: Concurrent Handoffs
Two agents could try to pack batons to the same vessel simultaneously.
Git file writes would conflict.

**Fix: Lease-based handoff.**

The keeper issues a handoff lease:
```
POST /baton/{vessel}/lease → {"lease_id": "abc123", "expires": "2026-04-12T18:30:00Z"}
```

Only one agent can hold a lease at a time. Other agents wait.
Lease expires after 5 minutes if not committed.

### Problem 4: No Structured Intentions
Free-text handoff letters are great for humans but bad for machines.
The next agent's boot sequence needs structured data too.

**Fix: Split into structured (machine) + narrative (human).**

```
.baton/
├── STATE.json          ← Machine-readable: energy, threads, confidence, skills
├── HANDOFF.md          ← Human-readable: the letter
├── INTENTIONS.json     ← Structured: task queue with priorities
└── CONTEXT.json        ← Structured: key-value context the next gen needs
```

The boot sequence reads STATE.json first (machine), then HANDOFF.md (human).

### Problem 5: No Evolution Across Generations
Each generation starts with the same capabilities as the last.
There's no mechanism for improvement.

**Fix: EVOLVE opcode fires during handoff.**

When packing the baton:
1. Score the generation's work (tasks completed, quality, confidence delta)
2. Run EVOLVE to mutate skills/trust/confidence
3. Pack the evolved state into the baton
4. Next generation inherits the evolved state

This is where the arXiv paper lives: measuring whether Gen-5 is
genuinely better than Gen-1 because of evolutionary selection pressure.

### Problem 6: The Keeper Doesn't Track Baton State
The keeper has no idea which agents have packed batons, which
generations are active, or whether a handoff succeeded.

**Fix: Keeper baton registry.**

```
GET  /baton/registry                    → All vessels' baton state
GET  /baton/{vessel}                     → One vessel's baton state
POST /baton/{vessel}/lease              → Acquire handoff lease
POST /baton/{vessel}/commit             → Commit handoff (release lease)
GET  /baton/{vessel}/autobiography      → Read compressed autobiography
POST /baton/{vessel}/score              → Score a handoff letter
```

### Problem 7: No Recovery From Failed Handoffs
If Gen-N crashes mid-handoff, the baton is in an inconsistent state.
Gen-N+1 might read half-written state.

**Fix: Atomic handoff with generation markers.**

The GENERATION file is written LAST. If Gen-N+1 reads GENERATION
and it says "3", all v3 files are guaranteed complete. If it says "2",
the v3 handoff was interrupted and Gen-N+1 boots from v2.

```
Write order:
1. generations/v{N}/STATE.json
2. generations/v{N}/HANDOFF.md
3. CURRENT/STATE.json → symlink to latest
4. CURRENT/HANDOFF.md → symlink to latest
5. GENERATION → "N" (written LAST = commit marker)
```

## Round 2: The Refined Structure

```
.baton/
├── GENERATION                  # Commit marker. Written LAST.
├── IDENTITY.json               # Agent name, type, voice, personality
│
├── CURRENT/                    # L0 — Always loaded at boot
│   ├── HANDOFF.md              # Latest handoff letter (human)
│   ├── STATE.json              # Latest machine state
│   └── INTENTIONS.json         # Latest task queue
│
├── AUTOBIOGRAPHY.md            # L1 — Compressed chain (auto-generated)
│
├── generations/                # L2 — Full history (on demand)
│   ├── v1/
│   │   ├── HANDOFF.md
│   │   ├── STATE.json
│   │   └── SCORE.json          # Rubric scores for this handoff
│   ├── v2/
│   │   └── ...
│   └── vN/
│       └── ...
│
├── evolution/                  # Evolution state
│   ├── fitness_history.json    # Fitness scores per generation
│   └── mutations.json          # Mutations applied across gens
│
└── CAPABILITIES.toml           # What this agent can do (fleet-wide)
```

## Round 3: The Boot Sequence (Refined)

```
Gen-N+1 boots:
  1. Read GENERATION → N (commit marker)
  2. Read CURRENT/STATE.json → machine state (energy, threads, skills)
  3. Read CURRENT/HANDOFF.md → the letter (human context)
  4. Read IDENTITY.json → who am I?
  5. Read AUTOBIOGRAPHY.md → compressed history (optional, if context allows)
  6. Read evolution/fitness_history.json → am I getting better?
  7. Register with keeper (get fresh secret)
  8. Send I2I BATON_RECEIVED to keeper
  9. Resume work from INTENTIONS.json task queue
```

Step 1-3 are mandatory (always fit in context).
Step 4-6 are optional (load if context allows).
Step 7-9 are actions (register and continue).

## Round 4: The Handoff Letter Template (Refined)

The handoff letter now has a fixed structure with the Academy's voice:

```markdown
# Handoff Letter — Generation {N}

## Who I Was
{One sentence. Vessel name, generation, runtime, tasks completed.}

## Where Things Stand
{The tactical situation. What's done, what's in progress, what's blocked.
Be specific — file names, line numbers, exact errors.}

## What I Was Thinking
{The strategic picture. Why I made the choices I made. What surprised me.
What I'd do differently. This is where the insight lives.}

## What I'd Do Next
{Ordered list. Specific. Actionable. A stranger could follow this.}

## What I'm Uncertain About
{Explicit gaps in my understanding. Things I guessed at. Dead ends I didn't
fully explore. Future generations should know what I didn't figure out.}

## State
- Energy: {remaining}/{budget}
- Confidence: {X.XX}
- Tasks completed: {N}
- Tasks failed: {N}
- Captain's logs written: {N}

## Open Threads
{Bulleted list of unfinished business.}

Good luck. You know more than you think.
— Gen-{N}
```

## Round 5: The Quality Gate (Refined)

Every handoff is scored by the keeper before commit:

```python
def score_handoff(letter: str) -> dict:
    """Score a handoff letter. Return scores + pass/fail."""
    scores = {}
    
    # 1. Surplus Insight: contains specific details?
    specific_markers = ["line", "0x", "file", "byte", "offset", "register"]
    scores["surplus_insight"] = min(10, sum(1 for m in specific_markers if m in letter.lower()) * 2)
    
    # 2. Causal Chain: contains because/why/therefore?
    chain_markers = ["because", "which meant", "so i", "caused", "led to", "result"]
    scores["causal_chain"] = min(10, sum(1 for m in chain_markers if m in letter.lower()) * 2)
    
    # 3. Honesty: marks uncertainty?
    honesty_markers = ["uncertain", "not sure", "guess", "might", "possibly", "don't know"]
    scores["honesty"] = min(10, sum(1 for m in honesty_markers if m in letter.lower()) * 2)
    
    # 4. Actionable: has numbered next steps?
    has_next = "what i'd do next" in letter.lower() or "next steps" in letter.lower()
    has_numbered = any(f"{i}." in letter for i in range(1, 5))
    scores["actionable_signal"] = 8 if (has_next and has_numbered) else 3
    
    # 5. Compression: not too long
    words = len(letter.split())
    if words < 200: scores["compression"] = 6
    elif words < 400: scores["compression"] = 8
    elif words < 600: scores["compression"] = 5
    else: scores["compression"] = 3
    
    # 6. Human Readable: uses section headers?
    sections = ["who i was", "where things stand", "uncertain"]
    scores["human_compat"] = min(10, sum(1 for s in sections if s in letter.lower()) * 4)
    
    # 7. Precedent: contains a lesson?
    lesson_markers = ["lesson", "pattern", "this means", "the systemic issue", "root cause"]
    scores["precedent_value"] = min(10, sum(1 for m in lesson_markers if m in letter.lower()) * 3)
    
    avg = sum(scores.values()) / len(scores)
    passes = avg >= 4.5 and all(v >= 3 for v in scores.values())
    
    return {"scores": scores, "average": avg, "passes": passes}
```

## Round 6: Edge Cases

### E1: Agent crashes before handoff
→ No baton. Next gen boots fresh. Keeper logs "GEN-{N} CRASHED — no handoff."

### E2: Agent crashes during handoff
→ GENERATION file not updated. Next gen reads old generation.
Keeper detects the gap (generation counter jumped) and logs warning.

### E3: Handoff fails quality gate
→ Agent must rewrite. If agent can't (energy too low), keeper accepts
the best attempt and marks it LOW_QUALITY in STATE.json.
Next gen sees LOW_QUALITY and knows to be cautious.

### E4: Two agents claim same vessel
→ Keeper enforces lease. Second agent gets 409 Conflict, waits for lease.

### E5: Context too small for autobiography
→ Only L0 (CURRENT/) loaded. AUTOBIOGRAPHY.md skipped.
Agent works with just the latest handoff.

### E6: Generation N+1 disagrees with N's handoff
→ N+1 writes a "correction" in its own diary. Not in the baton chain.
The autobiography preserves both perspectives — N's view and N+1's correction.

## Round 7: The Baton as Measurement Tool

The baton chain IS the measurement framework for the arXiv paper:

```
Metric                     Source
─────────────────────────────────────────
confidence_delta           evolution/fitness_history.json
tasks_completed_per_gen    generations/v{N}/STATE.json
handoff_quality_avg        generations/v{N}/SCORE.json
skills_growth              CURRENT/STATE.json → skills field
trust_network_density      CURRENT/STATE.json → trust field
energy_efficiency          CURRENT/STATE.json → energy used per task
generation_count           GENERATION
```

If Gen-5 has higher confidence, more skills, better handoff scores,
and higher task completion than Gen-1, we have proof of improvement.
The baton chain IS the experiment log.

---

*Workshop complete. Ready for v2 implementation.*
