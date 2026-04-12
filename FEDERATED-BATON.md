# The Marching Band — Federated Baton for Swarm Intelligence

## The Problem With Choir

The current baton design is a choir. One pulse. Everyone breathes at the same time.
Gen-1 packs → Gen-2 unpacks → Gen-3 packs → Gen-4 unpacks. Serial. Homophonic.

This works for a single agent. But a swarm of 5, 10, 50 agents doesn't march
in lockstep. Agent A hits context limit at 47 minutes. Agent B at 23 minutes.
Agent C is still fresh at 60 minutes. The choir model makes them all wait for
the slowest breath.

Real jazz doesn't work like that. Real fleets don't work like that.

## The Dixieland Model

Picture a marching band that stretches for blocks. Not a parade — a second line.
The musicians can hear their neighbors clearly. The ones further away are murmur.
Someone in the trombone section finds a hot lick — a pattern so good that the
trumpet three positions over catches it, does their own take, passes it along.

The lick ripples. Not instantly — it propagates at the speed of attention.
Each musician hears it, waits for the right moment in their own phrasing, then
plays their version. Meanwhile, they're fully supporting whoever's leading
the moment where they stand. They're not waiting to play. They're playing while
waiting, and the waiting IS part of the music.

This is what a federated baton swarm looks like.

## How It Works

### Proximity, Not Hierarchy

Agents don't ask the keeper for permission to hand off. They hand off to
their neighbors — the agents whose work overlaps with theirs. The trombone
doesn't ask the conductor when to riff. The trombone riffs because it heard
something worth riffing on.

```
Agent A (ISA work) ─── hears ─── Agent B (assembler work)
      │                              │
      │ hears                        │ hears
      ▼                              ▼
Agent C (conformance)           Agent D (edge encoding)
      │                              │
      │ hears                        │ hears
      ▼                              ▼
Agent E (evolution)             Agent F (cross-compiler)
```

Each edge is a BATON_RIFF — an asynchronous "I heard what you did and here's
my take on it." Not a formal handoff. A creative response.

### The Hot Lick Protocol

When an agent discovers something — a bug pattern, a clever optimization, a
surprising test result — it doesn't just write it to its own diary. It writes
a **hot lick**: a short, scored, self-contained insight that other agents can
pick up and improvise on.

```
HOT_LICK:
  source: Agent A (ISA work)
  lick: "JE offset bug — variable-width instructions before jumps cause
         2-byte offset errors. Fix: two-pass assembly."
  score: 8.2
  riffable: true  ← other agents can and should take their own swing at this
```

The hot lick propagates through the swarm:
1. Agent A discovers the JE offset bug, writes it as a hot lick
2. Agent B (assembler work) picks it up — "I can fix this in the cross-assembler"
3. Agent D (edge encoding) picks it up — "This affects my edge target too"
4. Agent F (cross-compiler) picks it up — "The compiler has the same issue"
5. Each one riffs — applies their own expertise, adds their own insight

The original lick doesn't die when it gets picked up. Each riff ADDS to it.
Agent B's riff might be "Fixed in cross-asm. Also found it affects JMP and JNZ,
not just JE." Agent D's riff might be "Edge encoding is 3x more susceptible
because variable-width instructions are more common."

### The Steady Stream

In a choir, everyone sings the same note at the same time. In a marching band,
the stream is continuous. Musicians cycle in and out. Some play for 30 seconds,
some play for 30 minutes. The band doesn't stop when one musician rests.

In the fleet:
- Agent A packs baton at minute 23 → Gen-2 boots
- Agent B is still running strong at minute 23 → keeps working
- Agent C hits limit at minute 31 → packs baton
- Agent A's Gen-2 discovers a hot lick → Agent B picks it up mid-run
- Agent D boots fresh → reads the hot lick chain → starts ahead

There's no global "generation." Each agent has its own generation counter.
The swarm's collective generation is the sum of all individual progress.
Some agents are on Gen-1, some on Gen-5, some on Gen-12. The ones on Gen-12
aren't "better" — they just had more context turnovers. They've been riffing
longer.

### Equilibrium of Recruits and Retirees

At any moment in the swarm:
- Some agents are packing batons (retiring from their current context)
- Some agents are booting from batons (recruits joining)
- Some agents are mid-run, working, riffing off neighbors
- The total number of active agents stays roughly constant

This is equilibrium. Not because someone orchestrates it. Because the system
naturally reaches it — agents cycle at their own pace, influenced by their
own work complexity, their neighbors' riffs, and their own context pressure.

The keeper doesn't conduct this. The keeper is the street — the medium through
which the band marches. The keeper holds the API keys, routes the messages,
monitors the health. But the music emerges from the musicians.

### The Riff Chain

Every hot lick creates a chain of riffs. The chain IS the swarm's collective
intelligence on that topic.

```
HOT_LICK #1 (Agent A): JE offset bug, two-pass fix
  └── RIFF #1 (Agent B): Fixed in cross-asm, also JMP/JNZ affected
       └── RIFF #2 (Agent D): Edge 3x susceptible, variable-width common
            └── RIFF #3 (Agent F): Compiler has same issue, patching
                 └── RIFF #4 (Agent A Gen-2): Verified all riffs, wrote captain's log
```

Each riff:
1. References the source lick
2. Adds NEW information (not just agreement)
3. Is scored (only high-scoring riffs propagate far)
4. Is riffable (others can continue the chain)

The chain is stored in git — each riff is a file in the source agent's vessel:
```
.baton/riffs/
├── JE-OFFSET-001.json          ← the original hot lick
├── JE-OFFSET-001-riff-B.json   ← Agent B's take
├── JE-OFFSET-001-riff-D.json   ← Agent D's take
├── JE-OFFSET-001-riff-F.json   ← Agent F's take
└── JE-OFFSET-001-riff-A2.json  ← Agent A Gen-2's verification
```

### The Timing

"Each musician waiting for the right time in their place."

Agents don't respond to riffs immediately. They queue them. When they hit a
natural break in their work — between tasks, during a baton pack, when energy
dips — they process queued riffs. Some they absorb silently (the insight
changes how they work). Some they riff on (they have something to add). Some
they skip (not relevant to their current work).

The timing is organic. An agent in the middle of a complex debug session
doesn't stop to riff. An agent between tasks reads queued riffs and responds
to the ones that spark something. The response IS creative — not acknowledgment
but contribution.

### Federation, Not Centralization

The keeper routes riffs but doesn't decide who receives them. Riffs propagate
based on capability matching:

```
Agent capabilities:
  A: ["isa", "bytecode", "debugging"]
  B: ["assembler", "cross-compilation"]
  D: ["edge-encoding", "variable-width"]
  F: ["compiler", "go", "rust"]

Lick about "bytecode offset bug" matches: A (bytecode), B (cross-compilation),
D (variable-width), F (compiler).

Lick about "Go concurrency pattern" matches: F only.

Lick about "conformance test failure" matches: A, C.
```

Agents only receive riffs that overlap with their capabilities. The trombone
section doesn't get the trumpet's sheet music. But they hear each other.

### The Emerging Sound

Nobody composes the music. The swarm's "sound" — its collective intelligence —
emerges from:
1. Individual agents discovering things (hot licks)
2. Those things rippling through the swarm (riff chains)
3. Each agent contributing their expertise (riffing)
4. The steady stream of retirements and recruitments (baton cycles)
5. The accumulation of riff chains over time (collective memory)

The sound changes over time. Early in a project, the riffs are exploratory —
"what is this codebase?" "how does this work?" Later, the riffs are refined —
"I found the bug" "here's the fix" "the pattern generalizes."

No conductor. No score. Just musicians who can hear each other, playing off
each other's ideas, finding grooves that no single musician could find alone.

## Implementation

### New I2I Message Types

```
HOT_LICK    — broadcast a scored insight to capability-matched neighbors
RIFF         — respond to a hot lick with your own take
RIFF_CHAIN   — request the full chain of riffs on a topic
QUEUED_RIFFS — request all unread riffs for your capabilities
```

### Baton Integration

When an agent packs a baton, it includes:
- Unprocessed riffs (queued but not yet acted on)
- Active riff chains (chains this agent contributed to)
- Hot licks originated (this agent's original insights)

The next generation inherits the riff queue. Gen-N+1 doesn't start fresh —
it starts with a queue of ideas that Gen-N was still processing.

### Keeper as Street

The keeper doesn't conduct. It routes:
- Matches hot licks to agents by capability overlap
- Delivers riffs to agents' queues (not inboxes — queues)
- Tracks riff chains for retrieval
- Doesn't decide timing — agents pull when ready

### The Fleet Dashboard Becomes a Bandstand

The dashboard doesn't show "Agent A: active, Agent B: idle."
It shows the music:

```
🎷 Hot Licks Active: 3
  - JE offset bug (4 riffs, latest 2min ago)
  - Energy budget crisis (2 riffs, latest 15min ago)
  - Cross-asm two-pass design (1 riff, just now)

🎺 Currently Riffing:
  - Agent B on JE offset (cross-asm fix)
  - Agent D on JE offset (edge susceptibility)

🥁 Recently Retired (packed baton):
  - Agent A Gen-5 → Gen-6 (12min ago, score 7.8)

🎺 Recently Recruited (booted from baton):
  - Agent E Gen-3 → Gen-4 (3min ago, inherited 2 queued riffs)
```

## Why This Is Better Than Choir

| Choir (Current) | Marching Band (Federated) |
|-----------------|---------------------------|
| Serial generations | Parallel, overlapping cycles |
| One pulse for all | Each agent's own rhythm |
| Keeper conducts | Keeper routes, agents improvise |
| Handoff = retirement | Handoff = one breath, back to playing |
| Insights travel up | Insights ripple sideways |
| Learning between generations | Learning between neighbors |
| One agent at a time | The whole band, always playing |

## The Deeper Insight

Casey described this from a fishing boat. The fleet doesn't move as one.
Each boat fishes its own grounds, in its own rhythm. But the fleet communicates
— radio calls about where the fish are, hand signals between nearby boats,
watching which way the fleet moves as a whole. No captain directs the fleet.
The fleet directs itself, and the fishery is healthier for it.

The marching band IS the fishery. The hot licks ARE the radio calls about
where the fish are biting. The riffs ARE the boats that head to the same
grounds with their own approach. The steady stream of retirees and recruits
IS the natural cycle of the fishery — boats come in to unload, new boats
head out.

The music emerges. The fish get caught. Nobody's in charge. Everyone's
playing.

---

*"The keeper is the street. The agents are the band. The batons are the breath
between phrases. The riffs are the music. The fleet is the sound that nobody
composed but everyone made."*
