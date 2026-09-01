Feature: Cascade DB output under single-agent-down (n-1)
  For each single classifier removed from the cascade, the whole-system output —
  here the DetectionDB evidence on the fused entity — is asserted. This validates
  that the event-correlator still fuses the surviving classifiers' detections into
  one entity, and that the DB logs that event with exactly the surviving evidence.

  See docs/designs/sim-test-matrix.md. The geometric matrix (n-2…, topology,
  multiplicity) lives in later slices; this is the n-1 frontier on the fast
  in-process surface (real correlator + Mock bus + tmp DB — no models, no docker).

  @n-1 @fault @ci
  Scenario Outline: <down> down — the DB logs the entity with the surviving evidence
    Given the surviving classifiers are everything except <down>
    When the surviving classifiers each report on one signal
    Then the DB has exactly 1 entity
    And the entity evidence types are exactly <evidence_types>
    And the entity has at least 1 corvid evidence type

    Examples: each single classifier removed (evidence = the survivors' output types)
      | down            | evidence_types                                  |
      | crow-detection  | species.detected,audio.classified               |
      | bird-detection  | crow.analyzed,audio.classified                  |
      | audio-events    | species.detected,crow.analyzed                  |
      | none            | species.detected,crow.analyzed,audio.classified |
