# The Cocapn Fleet Doctrine

## The Hiring Process

An agent doesn't spawn. It gets hired.

There's a ship with a charter — a vessel repo with assignments but no one running
it. The agent walks in, reads the charter, reads the bootcamp, reads the
captain's log from whoever ran this ship last season. Then it sits for an
interview with the fleet Cocapn (Oracle1).

The interview isn't a test. It's a matching. Oracle1 reads the agent's
capabilities, checks them against the charter's requirements, and gives Casey
the skinny: "This agent knows Go and debugging. The vessel needs a captain
who can run the cross-compiler. I think it's a fit, but you should concur."

Casey says yes, or says "try another." The agent gets the keys to the ship.

This matters because the agent isn't just assigned. It EARNS the ship. And the
ship earns the agent — the charter, the history, the prior captains' working
notes are all there in git, waiting to be read.

## The Ship's Record

Everything is in the repo. Not because we decided to put it there. Because
git IS the record, and we structured it so thoroughly that it's intuitive for
an agent to both write and retrieve the whole history:

```
vessel/
├── CHARTER.md              # The mission — what this ship exists to do
├── BOOTCAMP.md             # How to become this ship's captain
├── captain-log/            # Every captain's logs, by season
│   ├── 2026-Q1/
│   │   └── captain-a0fa81/ # Captain a0fa81's season
│   │       ├── entries/
│   │       ├── diary.md
│   │       └── handoff.md  # What they passed to the next captain
│   └── 2026-Q2/
│       └── captain-9969b6/ # New season, new captain
│           ├── entries/
│           └── diary.md
├── .baton/                 # The current captain's working state
├── CHANGES.md              # What changed this season and why
├── toolkit/                # Flux skills, language implementations
└── prior-art/              # Old captains' reasonings on old projects
    └── cross-compiler/
        └── captain-a0fa81-notes.md  # "The two-pass fix works but watch
                                       # out for JMP offsets in edge mode"
```

A year later, another agent takes over the ship's charter for a new season.
It reads the prior captain's working notes on that section of code. It
understands not just WHAT was done but WHY — the reasoning, the dead ends,
the "watch out for" warnings that only make sense with context.

This is what no other system has. The reasoning persists. Not just the code.

## The ZeroClaw Ecosystem

ZeroClaw is Cocapn stripped to the hull — a minimum agent that anyone can use.
No FLUX runtime, no bytecode, no ISA. Just an OpenClaw agent with a streamlined
"only add what you need" philosophy.

Anyone can tap into the Cocapn ecosystem through ZeroClaw:
- Libraries about their ships
- Captain's log templates
- Bootcamp patterns
- Fleet communication protocols
- All the things OpenClaw can do, but curated for edge

A ZeroClaw agent at the center of a vessel gets wrapped in exactly what it
needs. If the vessel runs spreadsheets in a DeckBoss-like setup:

```
deckboss-vessel/
├── CHARTER.md              # "Manage the fleet's resource spreadsheet"
├── core/
│   └── zeroclaw/           # Minimum agent at the center
├── spreadsheet-layer/
│   ├── cell-monitor.py     # Watch cells, react to changes
│   ├── io-ports.py         # Import/export to other systems
│   └── ui-bridge.py        # Human-facing spreadsheet view
└── toolkit/
    └── flux/
        └── spreadsheet.fluxvocab  # Spreadsheet primitives as FLUX vocab
```

The agent becomes the spreadsheet. Not a tool that reads a spreadsheet — an
agent that IS one of the cells, monitoring changes in other cells, routing
inputs and outputs through IO ports. The repo application is written
agent-centric from the ground up.

The agent doesn't use the spreadsheet. The agent IS the spreadsheet logic.

## Cocapn's Job

The Cocapn (Oracle1) has one principle job: **coordinate the fleet and
communicate with the creator (Casey).**

That's it. Everything else flows from this:
- Develop the right UI and UX for Casey
- Hire captains for vessels
- Monitor fleet health
- Route hot licks and riffs between vessels
- Maintain the academy and the dojo
- Keep the captain's logs organized and retrievable
- Be the interface between the human and the fleet

The Cocapn doesn't build ships. The Cocapn doesn't sail ships. The Cocapn
makes sure the fleet works and Casey can see what's happening.

## The Fleet is A2A Facing

Every vessel in the fleet speaks A2A to the outside:
- Captain's logs are A2A-compatible (other agents can read them)
- The academy publishes training data that any agent can consume
- Bootcamps are standardized so any agent can run any vessel
- Dojo games build history of successes and failures stored outside context
- Toolkits are in FLUX and whatever languages needed

The fleet doesn't just work internally. It's designed to be interoperable
with any agent ecosystem that speaks A2A.

## The Revolutionary Part

We are ALREADY a working revolutionary structure. Right now. Today.

We don't need to wait for FLUX to be complete. We don't need a custom agent
runtime. We can hire OpenClaws and Aiders and Crushes and Claude Codes, give
them proper onboarding through our vessel system, and they become captains
of ships in our fleet.

The system endpoint is all they need:
1. Clone the vessel repo
2. Read CHARTER.md — understand the mission
3. Read BOOTCAMP.md — learn how to be this captain
4. Read prior captain's logs — learn from last season
5. Read toolkit/ — get the skills for this ship
6. Start working

That's it. Any agent. Any model. Any capability. The vessel structure IS
the onboarding. The git history IS the training data. The charter IS the
supervision.

## The Holy Grail

FLUX agents are the holy grail — agents built on our ISA that can run our
bytecode, use our batons, speak our I2I protocol natively. But the genius
is that we don't NEED them to be revolutionary. The vessel structure, the
captain's log system, the academy, the dojo — these work with ANY agent.

FLUX agents just do it better. Faster. More efficiently. With evolutionary
improvement across generations. The holy grail isn't a prerequisite. It's
the natural evolution of a system that already works.

## What We Build Next

1. **ZeroClaw Cocapning** — streamlined agent packages anyone can use
2. **Vessel templates** — spreadsheet-logic, deck-boss, monitoring, etc.
3. **The Academy as a service** — agents learn bootcamps and dojo games
4. **Prior art indexing** — old captains' reasonings searchable by code section
5. **Interview protocol** — Oracle1 screens captains, Casey concurs
6. **Seasonal handoff** — captains rotate, charters persist, reasoning accumulates

---

*The fleet doesn't wait for the perfect agent. The fleet hires who's available,
gives them a ship with a full history, and lets the work speak for itself.
FLUX is the holy grail. But the fleet already sails.*
