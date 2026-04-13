primary_plane: 3
reads_from: [3, 4, 5]
writes_to: [3]
floor: 3
ceiling: 5
compilers: []
reasoning: |
  Flux-baton is the context handoff system operating at Plane 3 (JSON).
  It manages context transfer between agents, accepting natural Intent (5),
  Domain Language (4), or structured IR (3) inputs and producing structured IR
  outputs. This ensures all handoffs are typed, verifiable, and protocol-compliant.

  Floor at 3 means flux-baton never deals with bytecode or native code—it operates
  purely at the structured data layer. This isolation allows it to safely serialize
  and transmit execution context between different fleet components without
  understanding their internal implementations.
