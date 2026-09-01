Feature: Multi-instance fusion (multiplicity)
  Multiple instances of a sensing type — e.g. audio-motion on N mics across hosts —
  observing one signal must fuse into ONE entity carrying all N sensors, not N
  orphan entities. This is the in-process multiplicity dimension (distinct
  sensor_ids); the docker multi-instance-via-instance_id path is a later slice.

  See docs/designs/sim-test-matrix.md §5.

  @multi-instance @ci
  Scenario Outline: <count> instances on distinct sensors fuse into one entity
    Given <count> instances of the same type observe one signal
    When the correlator processes all instance detections
    Then the DB has 1 entity fused from <count> sensors

    Examples: instance counts (audio-motion x N mics)
      | count |
      | 2     |
      | 3     |
      | 4     |
