Feature: End-to-end cognitive loop
  Validate the detection -> correlation -> entity -> persistence loop end to end,
  including entity_type derivation, corollary-discharge tagging, and multi-sensor
  correlation. Driven in-process against the real event-correlator (see
  tests/bdd/environment.py and docs/TESTING.md).

  Scenario: Single species detection through the full pipeline
    Given a synthetic audio signal matching "American Crow" frequency profile
    When the detection pipeline processes the audio chunk
    Then an EntityEvent is published with entity_type "Animal.Bird.Crow"
    And the event is stored in the SQLite database

  Scenario: Corollary discharge filters self-generated detections
    Given the system is playing a crow call
    And a synthetic crow detection arrives during playback
    When the correlation pipeline processes the detection
    Then the event is tagged with is_self_generated = true

  Scenario: Multi-sensor detection correlates into one entity
    Given a synthetic "American Crow" detection on sensor "mic-1"
    And a synthetic "American Crow" detection on sensor "mic-2"
    When the correlation pipeline processes all detections
    Then a single correlated multi-sensor EntityEvent is published
