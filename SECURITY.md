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
- `orpheus-dashboard` - Web UI (FastAPI backend)
- `orpheus-agent-audio-motion` - Audio detection agent
- `orpheus-mqtt` - MQTT broker configuration

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
