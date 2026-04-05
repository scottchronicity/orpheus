# Node.js Version Management for orpheus_ui

## Overview

The orpheus_ui service uses a **self-contained Node.js installation** to ensure consistent versions between development and production deployment on Jetson hardware. This avoids conflicts with system Node.js versions that may be too old (e.g., v16.19.1 on Ubuntu 20.04).

## Architecture

### Local Node.js Installation

- **Version:** 20.18.0 (configurable via `NODE_VERSION` env var)
- **Location:** `services/orpheus_ui/.node/`
- **Installed by:** `systemd/install-service.sh`
- **Platforms:** x86_64 (x64), aarch64 (arm64)

### Deployment Flow

```
make install-service
    ↓
install-service.sh
    ↓
1. Download Node.js v20.18.0 to .node/
    ↓
2. Export PATH="${NODE_LOCAL_DIR}/bin:${PATH}"
    ↓
3. Run npm install && npm run build
    ↓
4. Copy .node/ to /opt/orpheus/ui/.node/
    ↓
5. Generate systemd service with PATH set to use local Node.js
```

## Key Implementation Details

### 1. Install Script PATH Export

**File:** `systemd/install-service.sh`

```bash
# Export PATH to ensure npm child processes use local Node.js
export PATH="${NODE_LOCAL_DIR}/bin:${PATH}"

# Verify versions before building
echo "Using Node.js version: $(node --version)"
echo "Using npm version: $(npm --version)"

# Now npm commands use the correct Node.js
npm install
npm run build
```

**Why this matters:**

- Even when calling `/path/to/.node/bin/npm` directly, npm spawns child processes that search PATH for `node`
- Build tools like Vite, TypeScript, and Rollup all invoke `node` as subprocesses
- Without PATH export, these subprocesses would find the system's old Node.js v16.19.1 instead of v20.18.0
- This causes `EBADENGINE` warnings and cryptographic errors (`crypto.getRandomValues is not a function`)

### 2. Frontend Makefile Auto-Detection

**File:** `frontend/Makefile`

```makefile
# Detect and prefer local Node.js installation
NODE_LOCAL_DIR := ../.node
NODE_LOCAL := $(wildcard $(NODE_LOCAL_DIR)/bin/node)
ifdef NODE_LOCAL
	NPM := $(NODE_LOCAL_DIR)/bin/npm
	$(info Using local Node.js: $(shell $(NODE_LOCAL_DIR)/bin/node --version))
else
	NPM := npm
	$(info Using system npm)
endif
```

**Benefits:**

- Development workflow (`make install-frontend`, `make build`) automatically uses local Node.js if available
- Falls back to system npm gracefully if `.node/` doesn't exist
- Provides clear feedback about which Node.js version is being used
- Ensures consistent behavior between `make build` and `make install-service`

### 3. Systemd Service Configuration

**Generated service file:** `/opt/orpheus/ui/systemd/orpheus-ui.service`

```ini
[Service]
Environment="PATH=/opt/orpheus/ui/.node/bin:/opt/orpheus/ui/venv/bin:/usr/local/bin:/usr/bin:/bin"
```

**Runtime behavior:**

- Service always uses the bundled Node.js v20.18.0 from `/opt/orpheus/ui/.node/`
- Independent of system Node.js version
- Backend can serve pre-built static frontend assets
- Frontend can be rebuilt on the server if needed (e.g., for hotfixes)

## Testing Strategy

### Pre-Deployment Testing (Development Machine)

```bash
# Clean any previous builds
cd services/orpheus_ui
make clean
rm -rf .node

# Test the installation flow
make install-service

# Verify Node.js version in output:
# Should show: "Using Node.js version: v20.18.0"
# Should NOT show warnings about Node.js v16.x
```

### Post-Deployment Testing (Jetson)

```bash
# Deploy to Jetson
cd ~/runtime/orpheus/services/orpheus_ui
git pull
make install-service

# Check service is using correct Node.js
systemctl status orpheus-ui
sudo journalctl -u orpheus-ui -n 50

# Verify frontend assets were built
ls -lh /opt/orpheus/ui/src/orpheus_ui/static/

# Test the dashboard
curl http://localhost:8082/
curl http://localhost:8082/api/health
```

### Verification Checklist

- [ ] **No EBADENGINE warnings** during `npm install`
- [ ] **No crypto.getRandomValues errors** during Vite build
- [ ] **Node.js v20.18.0 version reported** in build output
- [ ] **npm v10.8.2 version reported** in build output
- [ ] **Frontend dist/ directory created** with assets
- [ ] **Service starts successfully** after installation
- [ ] **Dashboard loads** in browser (http://jetson-ip:8082)

## Troubleshooting

### Error: Still using Node.js v16.19.1

**Symptoms:**
```
npm warn cli npm v10.8.2 does not support Node.js v16.19.1
npm warn EBADENGINE Unsupported engine...
```

**Diagnosis:**
```bash
# Check if .node/ was created
ls -la services/orpheus_ui/.node/bin/

# Verify PATH during build
grep "export PATH" services/orpheus_ui/systemd/install-service.sh
```

**Solution:**
- Ensure `export PATH="${NODE_LOCAL_DIR}/bin:${PATH}"` is present in install script
- Run `make clean-node && make install-service` to reinstall

### Error: crypto.getRandomValues is not a function

**Cause:** Vite is running under Node.js v16.x which lacks Web Crypto API support

**Solution:** This is fixed by ensuring PATH is exported before npm commands (see above)

### Error: Node.js download fails

**Symptoms:**
```
ERROR: Failed to download Node.js from https://nodejs.org/dist/...
```

**Diagnosis:**
```bash
# Test connectivity
curl -I https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-arm64.tar.xz

# Check architecture
uname -m  # Should be aarch64 or x86_64
```

**Solution:**
- Verify internet connectivity
- Check if architecture is supported (x86_64 or aarch64)
- Try manually downloading to verify URL works

## Development Workflow

### Local Development (macOS/Ubuntu)

```bash
# Install dependencies (uses local Node.js if present)
make install-frontend

# Run dev server (uses local Node.js if present)
make run-frontend

# Build for production
make build-frontend
```

### Production Deployment (Jetson)

```bash
# Full service installation (downloads Node.js, builds frontend, installs service)
make install-service

# Update after code changes
make update

# Clean and reinstall Node.js
make clean-node
make install-service
```

## Version Upgrade Path

To upgrade Node.js version:

```bash
# Set new version
export NODE_VERSION=20.21.0

# Reinstall
make clean-node
make install-service
```

Or update default in `systemd/install-service.sh`:

```bash
NODE_VERSION="${NODE_VERSION:-20.21.0}"  # Change default here
```

## References

- **PR:** [#103 - Add self-contained Node.js installation](https://github.com/scottchronicity/orpheus/pull/103)
- **Issue:** Node.js v16.19.1 on Ubuntu 20.04 too old for modern frontend tooling (Vite 5, Vitest 2)
- **Solution:** Bundle Node.js v20.18.0 with service, control PATH at build and runtime
- **Pattern:** Similar to how Python venvs are managed for backend services
