Feature: Topology-invariant fusion (all-on-one-host vs all-on-different-hosts)
  The topology dimension of the first-pass matrix: the same physical signal,
  reported by the full cascade, must fuse into ONE entity whether the agents run
  on one host or are spread across different hosts. Host placement is a deploy
  concern the bus abstracts away — it must not fragment the fused entity. This is
  the fast in-process invariance check (the same signal, a `host` discriminator
  varied in context); the real multi-broker wiring is the docker Slice 6.

  Failure (agent_failure + correlator_down) and multiplicity (multiplicity) are
  the other two legs; together they are the owner's first-pass criterion
  (failure x topology x multiplicity). See docs/designs/sim-test-matrix.md.

  @topology @ci
  Scenario Outline: the cascade fuses to one entity regardless of host placement
    When the full cascade reports one signal with agents on <topology>
    Then the DB has exactly 1 entity
    And the entity evidence types are exactly species.detected,crow.analyzed,audio.classified
    And the entity has at least 1 corvid evidence type

    Examples: host placements
      | topology        |
      | one host        |
      | different hosts |
