#!/bin/bash
set -e

echo "Installing Orpheus UI systemd service..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
COMMON_RELATIVE="../../platform/orpheus-common"
COMMON_PATH="${PROJECT_ROOT}/${COMMON_RELATIVE}"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"

# Node.js configuration
NODE_VERSION="${NODE_VERSION:-20.18.0}"
NODE_LOCAL_DIR="${PROJECT_ROOT}/.node"
SERVICE_DIR="/opt/orpheus/ui"

# User database location (persists across installs)
USER_DB_DIR="/data/orpheus"
USER_DB_PATH="${USER_DB_DIR}/users.db"

if [ ! -d "${COMMON_PATH}" ]; then
    echo "ERROR: Could not locate orpheus-common at ${COMMON_PATH}" >&2
    exit 1
fi

COMMON_PATH="$(cd "${COMMON_PATH}" && pwd)"

# Install or verify Node.js installation
install_nodejs() {
    if [ -d "${NODE_LOCAL_DIR}" ] && [ -x "${NODE_LOCAL_DIR}/bin/node" ]; then
        INSTALLED_VERSION=$(${NODE_LOCAL_DIR}/bin/node --version | sed 's/v//')
        echo "✓ Node.js ${INSTALLED_VERSION} already installed at ${NODE_LOCAL_DIR}"
        return 0
    fi

    echo "Installing Node.js v${NODE_VERSION} locally..."
    
    # Detect architecture
    ARCH=$(uname -m)
    case "${ARCH}" in
        x86_64)
            NODE_ARCH="x64"
            ;;
        aarch64)
            NODE_ARCH="arm64"
            ;;
        *)
            echo "ERROR: Unsupported architecture: ${ARCH}" >&2
            echo "Supported architectures: x86_64, aarch64" >&2
            exit 1
            ;;
    esac
    
    NODE_TARBALL="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
    DOWNLOAD_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}"
    
    echo "Downloading Node.js for ${ARCH} (${NODE_ARCH})..."
    echo "URL: ${DOWNLOAD_URL}"
    
    # Create temporary directory for download
    TEMP_DIR=$(mktemp -d)
    # Validate that TEMP_DIR is safe before using it in trap
    if [ -z "${TEMP_DIR}" ] || [ "${TEMP_DIR}" = "/" ] || [[ ! "${TEMP_DIR}" =~ ^/tmp/ ]]; then
        echo "ERROR: Failed to create safe temporary directory" >&2
        exit 1
    fi
    trap '[ -n "${TEMP_DIR}" ] && [ "${TEMP_DIR}" != "/" ] && rm -rf "${TEMP_DIR}"' EXIT
    
    # Download Node.js tarball
    if ! curl -fSL "${DOWNLOAD_URL}" -o "${TEMP_DIR}/${NODE_TARBALL}"; then
        echo "ERROR: Failed to download Node.js from ${DOWNLOAD_URL}" >&2
        exit 1
    fi
    
    # Extract to .node directory
    echo "Extracting Node.js to ${NODE_LOCAL_DIR}..."
    mkdir -p "${NODE_LOCAL_DIR}"
    if ! tar -xJf "${TEMP_DIR}/${NODE_TARBALL}" -C "${NODE_LOCAL_DIR}" --strip-components=1; then
        echo "ERROR: Failed to extract Node.js tarball" >&2
        exit 1
    fi
    
    # Verify installation
    if [ ! -x "${NODE_LOCAL_DIR}/bin/node" ]; then
        echo "ERROR: Node.js installation failed - node binary not found or not executable" >&2
        exit 1
    fi
    
    INSTALLED_VERSION=$(${NODE_LOCAL_DIR}/bin/node --version)
    echo "✓ Node.js ${INSTALLED_VERSION} installed successfully"
}

# Install Node.js before proceeding
install_nodejs

TMP_REQUIREMENTS="$(mktemp)"
trap 'rm -f "${TMP_REQUIREMENTS}"' EXIT

# Strip editable install for deployment
grep -vE '^-e[[:space:]]+\.\./\.\./\.\./platform/orpheus-common([[:space:]]+.*)?$' "${BACKEND_DIR}/requirements.txt" > "${TMP_REQUIREMENTS}"

DEFAULT_ORPHEUS_CONFIG="${COMMON_PATH}/config/orpheus.yaml"

# Create directories
mkdir -p /opt/orpheus/ui

# Ensure user database directory exists and is writable
if [ ! -d "${USER_DB_DIR}" ]; then
    echo "Creating user database directory at ${USER_DB_DIR}..."
    mkdir -p "${USER_DB_DIR}"
    # Try to set ownership (may fail if orpheus user doesn't exist yet)
    if id orpheus >/dev/null 2>&1; then
        chown orpheus:orpheus "${USER_DB_DIR}"
    else
        echo "ℹ orpheus user not found, directory will be owned by root"
    fi
fi

# Preserve existing user database
if [ -f "${USER_DB_PATH}" ]; then
    echo "✓ Existing user database found at ${USER_DB_PATH} - will be preserved"
else
    echo "ℹ No existing user database - a new one will be created on first run"
fi

# Build frontend BEFORE copying (Vite builds to backend/src/orpheus_ui/static/)
if [ -f "${FRONTEND_DIR}/package.json" ]; then
    echo "Building frontend..."
    
    # Determine the user to run as (avoid creating root-owned files)
    if [ -n "${SUDO_USER}" ]; then
        BUILD_USER="${SUDO_USER}"
    else
        BUILD_USER="$(whoami)"
    fi
    
    echo "Building as user: ${BUILD_USER}"
    
    # Run build as the non-root user to avoid permission issues
    if [ "${BUILD_USER}" != "root" ] && [ "$(whoami)" = "root" ]; then
        sudo -u "${BUILD_USER}" bash -c "cd ${FRONTEND_DIR} && export PATH=${NODE_LOCAL_DIR}/bin:\${PATH} && npm install && npm run build"
    else
        cd "${FRONTEND_DIR}"
        export PATH="${NODE_LOCAL_DIR}/bin:${PATH}"
        npm install
        npm run build
        cd "${PROJECT_ROOT}"
    fi
    
    echo "✓ Frontend built to backend/src/orpheus_ui/static/"
fi

# Copy backend application files (including built frontend)
cp -r "${BACKEND_DIR}/src" /opt/orpheus/ui/
cp "${BACKEND_DIR}/requirements.txt" /opt/orpheus/ui/
cp "${BACKEND_DIR}/pyproject.toml" /opt/orpheus/ui/
cp "${BACKEND_DIR}/setup.py" /opt/orpheus/ui/

# Copy systemd files
cp -r "${PROJECT_ROOT}/systemd" /opt/orpheus/ui/

# Copy local Node.js installation to service directory
echo "Copying Node.js installation to ${SERVICE_DIR}/.node..."
mkdir -p "${SERVICE_DIR}/.node"
if [ -d "${NODE_LOCAL_DIR}" ] && [ "$(ls -A "${NODE_LOCAL_DIR}")" ]; then
    cp -r "${NODE_LOCAL_DIR}/." "${SERVICE_DIR}/.node/"
else
    echo "ERROR: Node.js installation directory is empty or does not exist" >&2
    exit 1
fi

# Setup virtual environment
cd /opt/orpheus/ui
# Remove existing venv to ensure correct Python version
if [ -d "venv" ]; then
    echo "Removing existing virtual environment..."
    rm -rf venv
fi
${PYTHON_BIN} -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install "${COMMON_PATH}"
venv/bin/pip install -r "${TMP_REQUIREMENTS}"

# Generate systemd service file with dynamic paths
echo "Generating systemd service file..."
cat > /opt/orpheus/ui/systemd/orpheus-ui.service <<EOF
[Unit]
Description=Orpheus UI Web Service
After=network.target time-sync.target
Documentation=https://github.com/scottchronicity/orpheus

[Service]
Type=simple
User=orpheus
Group=orpheus
WorkingDirectory=${SERVICE_DIR}
Environment="PYTHONUNBUFFERED=1"
Environment="PATH=${SERVICE_DIR}/.node/bin:${SERVICE_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="ORPHEUS_CONFIG_PATH=/etc/orpheus/orpheus.yaml"
Environment="PYTHONPATH=${SERVICE_DIR}/src"
Environment="ORPHEUS_UI_DATABASE_URL=sqlite+aiosqlite:////data/orpheus/users.db"
ExecStart=${SERVICE_DIR}/venv/bin/uvicorn orpheus_ui.main:app --host 0.0.0.0 --port 8082
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=orpheus-ui

[Install]
WantedBy=multi-user.target
EOF

# Install systemd service
cp /opt/orpheus/ui/systemd/orpheus-ui.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable orpheus-ui
systemctl restart orpheus-ui

echo ""
echo "✓ Service installed and started"
echo "✓ Node.js ${NODE_VERSION} installed at ${SERVICE_DIR}/.node"
echo "✓ UI backend runs on port 8082"
echo "✓ User database stored at ${USER_DB_PATH} (persists across updates)"
echo "✓ Config at /etc/orpheus/orpheus.yaml"
echo "✓ Service enabled (will auto-start on boot)"
echo ""
echo "Check service status:"
echo "  make service-status"
echo "  make service-logs"
echo ""
echo "Note: nginx should proxy port 80 to port 8082 (backend) in production"
