# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

1. **Do NOT** create a public GitHub issue for security vulnerabilities
2. Email security concerns to the repository maintainers via GitHub (use the Security tab to report vulnerabilities privately)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

- **Response Time**: We aim to respond within 48 hours
- **Updates**: We'll keep you informed of progress
- **Credit**: We'll credit you in the security advisory (unless you prefer anonymity)

### Scope

This security policy applies to:
- `orpheus-common` - Core platform library
- `orpheus-dashboard` - Web dashboard (FastAPI backend)
- `orpheus_ui` - Web UI (FastAPI backend + React frontend)
- `orpheus-mqtt` - MQTT broker service
- `orpheus-gps` - GPS service
- `orpheus-bluetooth-autoconnect` - Bluetooth autoconnect service
- `orpheus-agent-audio-motion` - Audio motion detection agent
- `orpheus-agent-audio-playback` - Audio playback agent
- `orpheus-agent-bird-detection` - Bird detection agent
- `orpheus-agent-crow-detection` - Crow detection agent
- `orpheus-agent-event-correlator` - Event correlator agent
- `orpheus-agent-video-motion` - Video motion detection agent
- `orpheus-agent-video-snapshotter` - Video snapshotter agent
- `orpheus-agent-video-timelapser` - Video timelapse agent

### Out of Scope

- Third-party dependencies (report to upstream maintainers)
- Issues in development/test environments only
- Social engineering attacks

## Security Best Practices

When contributing to Orpheus:

1. **Never commit secrets** - Use environment variables or config files
2. **Validate inputs** - Especially for web endpoints and MQTT messages
3. **Use secure defaults** - MQTT should use authentication in production
4. **Keep dependencies updated** - Run `make check-deps` regularly
5. **Review permissions** - Minimize filesystem and network access
