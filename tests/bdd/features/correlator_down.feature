Feature: The fuser is necessary (correlator-down + all-down canary)
  The failure dimension's k that removes the FUSER itself, not a classifier. The
  generated powerset (test_matrix_generated.py) downs classifiers with the
  correlator always present; these are the complementary corners:

    - correlator down: the classifiers still emit their detections onto the bus,
      but with no fuser consuming them NOTHING is fused — the entities projection
      stays empty (detections do not self-fuse into entities).
    - every classifier down: an idle correlator invents no entities.

  Together they pin both ends of the failure axis: no fuser ⇒ no entities even
  with full classifier signal, and no signal ⇒ no entities even with the fuser up.
  Fast in-process surface — real correlator + Mock bus + tmp DB, no models, no
  docker. See docs/designs/sim-test-matrix.md §3.

  @fault @correlator-down @ci
  Scenario: correlator down — classifiers emit but no entity is fused
    Given the correlator is down
    When all classifiers report on one signal onto the bus
    Then 3 classifier detections were emitted
    And the DB has 0 entities

  @fault @all-down @ci
  Scenario: every classifier down — the idle correlator invents no entities
    Given the correlator is up with no classifiers reporting
    When the correlator processes its empty backlog
    Then the DB has 0 entities
