# Integration test harnesses

Local-machine smoke tests that exercise the running system end-to-end
without needing Jetson hardware or real ML models.

## `pump_fake_animal_events.py`

Pumps fake bird-detection, audio-events, and crow-detection events
through MQTT to verify the event-correlator's clustering, the lineage
chain, and Layer 3 auto-discovery all work together as designed.

### Repro

```bash
# 1. Start a local mosquitto on a non-default port.
cat > /tmp/orpheus-mosquitto.conf << 'EOF'
listener 1884
allow_anonymous true
persistence false
log_type error
EOF
mosquitto -c /tmp/orpheus-mosquitto.conf &

# 2. Write a test orpheus.yaml that uses port 1884 + lists all three
#    detection topics (bird, crow, audio-events).
cp config/orpheus.example.yaml /tmp/orpheus-test.yaml
# (sed/perl-edit broker_port to 1884 and add orpheus/detection/audio/events
#  to correlation.input_topics — see the test script in this directory)

# 3. Start the event-correlator agent against the test config.
export ORPHEUS_DATA_ROOT=/tmp/orpheus-test-data
export ORPHEUS_CONFIG_PATH=/tmp/orpheus-test.yaml
mkdir -p $ORPHEUS_DATA_ROOT
(cd agents/orpheus-agent-event-correlator && \
  venv/bin/python -m orpheus_agent_event_correlator.main) &

# 4. Subscribe to the emitted Entities so we can see what comes out.
mosquitto_sub -h localhost -p 1884 -t 'orpheus/entities/animal' -v &

# 5. Run the pump.
(cd agents/orpheus-agent-event-correlator && \
  venv/bin/python ../../tools/integration/pump_fake_animal_events.py)

# 6. Verify the DB has the right shape.
python3 -c "
import sqlite3
db = sqlite3.connect('/tmp/orpheus-test-data/detections/orpheus.db')
db.row_factory = sqlite3.Row
print('Detections by type:')
for r in db.execute('SELECT detection_type, COUNT(*) FROM detections GROUP BY detection_type'):
    print(f'  {r[0]:18}: {r[1]}')
print(f'Entities: {db.execute(\"SELECT COUNT(*) FROM entities\").fetchone()[0]}')
"

# 7. Trigger auto-discovery and confirm equivalences are learned.
ORPHEUS_DATA_ROOT=/tmp/orpheus-test-data python3 -c "
from orpheus_common.detection import (
    DetectionDB, TaxonomyEquivalenceDB, discover_equivalences, TaxonomyRef
)
proposals = discover_equivalences(
    DetectionDB(), TaxonomyEquivalenceDB(),
    lookback_days=30, min_cooccurrences=2,
)
for p in proposals:
    print(f\"{p['a']['namespace']}:{p['a']['id']} <-> {p['b']['namespace']}:{p['b']['id']}\"
          f\"  jaccard={p['jaccard']:.2f} action={p['action']}\")
"

# 8. Tear down.
pkill -f orpheus_agent_event_correlator
pkill -f mosquitto
```

### Last verified live run

Output (2026-05-22 reproduction):

```
Detections by type:
  audio.classified  : 5
  audio.motion      : 5
  crow.analyzed     : 5
  species.detected  : 10  (2 species/event × 5 events)
Entities: 5

Auto-discovery learned 3 equivalences from 5 events:
  audioset:/m/04s8yn <-> ioc:Corvus brachyrhynchos  jaccard=1.00 action=recorded
  audioset:/m/04s8yn <-> ioc:Corvus corax            jaccard=1.00 action=recorded
  ioc:Corvus brachyrhynchos <-> ioc:Corvus corax     jaccard=1.00 action=recorded

equivalent_taxa(TaxonomyRef("ioc", "Corvus brachyrhynchos")) =
  {ioc:Corvus brachyrhynchos, ioc:Corvus corax, audioset:/m/04s8yn}
```

— the whole cross-classifier-identity stack works as designed.
