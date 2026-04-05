# Orpheus Event Schemas

This directory contains JSON Schema definitions for all MQTT event types used in the Orpheus platform. These schemas serve as the single source of truth for data structures shared between Python agents and JavaScript frontend code.

## Purpose

- **Type Safety**: Provides validation for both Python (via `jsonschema`) and JavaScript (via TypeScript types or runtime validation)
- **Documentation**: Self-documenting format for all event structures
- **Consistency**: Ensures agents and dashboard agree on data formats
- **Validation**: Can be used to validate messages before publishing or after receiving

## Available Schemas

### Detection Events

| Schema | Description | Publisher | Topic |
| -------- | ------------- | ----------- | ------- |
| `audio-motion-event.schema.json` | Audio activity detected above threshold | orpheus-agent-audio-motion | `orpheus/audio/motion/events` |
| `bird-detection-event.schema.json` | Bird species identified via BirdNET | orpheus-agent-bird-detection | `orpheus/detection/bird/events` |
| `crow-detection-event.schema.json` | Crow vocalization analyzed (species, call type, quality) | orpheus-agent-crow-detection | `orpheus/detection/crow/events` |

## Usage

### Python (Agent Publishers)

```python
import json
import jsonschema
from pathlib import Path

# Load schema
schema_path = Path(__file__).parent.parent / "docs/schemas/crow-detection-event.schema.json"
with open(schema_path) as f:
    schema = json.load(f)

# Validate before publishing
detection_event = {
    "event_id": "crow_det_20251205T143023_ch1_d4e5f6",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "channel_id": "1",
    "detection": {
        "species": "american_crow",
        "call_type": "caw",
        "quality_score": 0.87
    },
    "audio_clip_path": str(audio_path),
    "inference_time_ms": 145
}

# Validate
jsonschema.validate(detection_event, schema)

# Publish
mqtt_client.publish("orpheus/detection/crow/events", detection_event)
```

### JavaScript (Dashboard Consumer)

```javascript
// Load schema and generate TypeScript types (using json-schema-to-typescript)
// Or validate at runtime:

async function validateCrowDetection(event) {
    const response = await fetch('/schemas/crow-detection-event.schema.json');
    const schema = await response.json();
    
    // Using Ajv for validation
    const ajv = new Ajv();
    const validate = ajv.compile(schema);
    
    if (!validate(event)) {
        console.error('Invalid event:', validate.errors);
        return false;
    }
    return true;
}
```

### Generating TypeScript Types

You can auto-generate TypeScript types from these schemas:

```bash
# Install json-schema-to-typescript
npm install -g json-schema-to-typescript

# Generate types
json2ts docs/schemas/crow-detection-event.schema.json > \
    services/orpheus-dashboard/static/types/crow-detection-event.d.ts
```

## Schema Evolution

When modifying schemas:

1. **Add new optional fields** - Safe, backward compatible
2. **Make required fields optional** - Safe, but may indicate agent needs update
3. **Add new enum values** - Safe, backward compatible
4. **Remove fields or enum values** - Breaking change, requires coordination
5. **Change field types** - Breaking change, requires coordination

For breaking changes:

- Update schema version in `$id` field
- Update all agents and dashboard code
- Test thoroughly before deployment

## Validation in CI

Schemas are validated in CI to ensure:

- Valid JSON Schema syntax
- Example values match schema constraints
- No duplicate field definitions

## Future Enhancements

- [ ] Generate Python Pydantic models from schemas
- [ ] Generate TypeScript types automatically
- [ ] Add runtime validation to dashboard
- [ ] Add runtime validation to agents (optional, for debugging)
- [ ] Version schemas and support multiple versions
