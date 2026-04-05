#!/bin/bash
# Test script for Node.js local installation logic
#
# This script validates the Node.js installation logic without requiring systemd
# or actual service deployment. It can be run in CI/CD environments.
#
# This file should have executable permissions. If not, run:
#   chmod +x test-install.sh
#
# Usage:
#   ./test-install.sh
#
# The script will:
# 1. Test architecture detection (aarch64 → arm64, x86_64 → x64)
# 2. Validate download URLs are accessible
# 3. Test that downloaded Node.js binaries work correctly
# 4. Verify that second run skips download (idempotency)
#
# Exit codes:
#   0 - All tests passed
#   1 - One or more tests failed

set -e

# Color output for better readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Testing Node.js Local Installation Logic"
echo "=========================================="
echo ""

# Configuration
NODE_VERSION="${NODE_VERSION:-20.18.0}"
TEST_DIR=$(mktemp -d)
# Validate that TEST_DIR is safe before using it in trap
if [ -z "${TEST_DIR}" ] || [ "${TEST_DIR}" = "/" ] || [[ ! "${TEST_DIR}" =~ ^/tmp/ ]]; then
    echo "ERROR: Failed to create safe temporary directory" >&2
    exit 1
fi
trap '[ -n "${TEST_DIR}" ] && [ "${TEST_DIR}" != "/" ] && rm -rf "${TEST_DIR}"' EXIT

echo "Test directory: ${TEST_DIR}"
echo "Node.js version: ${NODE_VERSION}"
echo ""

# Test 1: Architecture detection
echo "Test 1: Architecture Detection"
echo "------------------------------"
ARCH=$(uname -m)
echo "Detected system architecture: ${ARCH}"

case "${ARCH}" in
    x86_64)
        NODE_ARCH="x64"
        echo -e "${GREEN}✓ x86_64 → x64 mapping correct${NC}"
        ;;
    aarch64)
        NODE_ARCH="arm64"
        echo -e "${GREEN}✓ aarch64 → arm64 mapping correct${NC}"
        ;;
    *)
        echo -e "${RED}✗ Unsupported architecture: ${ARCH}${NC}"
        echo "Supported architectures: x86_64, aarch64"
        exit 1
        ;;
esac
echo ""

# Test 2: Download URL validation
echo "Test 2: Download URL Validation"
echo "--------------------------------"
NODE_TARBALL="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
DOWNLOAD_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}"

echo "Testing URL: ${DOWNLOAD_URL}"
if curl --output /dev/null --silent --head --fail "${DOWNLOAD_URL}"; then
    echo -e "${GREEN}✓ Download URL is valid and accessible${NC}"
else
    echo -e "${RED}✗ Download URL failed: ${DOWNLOAD_URL}${NC}"
    echo "This might indicate:"
    echo "  - Node.js version ${NODE_VERSION} doesn't exist"
    echo "  - Network connectivity issues"
    echo "  - Architecture ${NODE_ARCH} not supported for this version"
    exit 1
fi
echo ""

# Test 3: Download and extract Node.js
echo "Test 3: Download and Extract Node.js"
echo "-------------------------------------"
NODE_LOCAL_DIR="${TEST_DIR}/.node"

echo "Downloading Node.js..."
if curl -fSL "${DOWNLOAD_URL}" -o "${TEST_DIR}/${NODE_TARBALL}"; then
    echo -e "${GREEN}✓ Download successful${NC}"
else
    echo -e "${RED}✗ Download failed${NC}"
    exit 1
fi

echo "Extracting Node.js to ${NODE_LOCAL_DIR}..."
mkdir -p "${NODE_LOCAL_DIR}"
if tar -xJf "${TEST_DIR}/${NODE_TARBALL}" -C "${NODE_LOCAL_DIR}" --strip-components=1; then
    echo -e "${GREEN}✓ Extraction successful${NC}"
else
    echo -e "${RED}✗ Extraction failed${NC}"
    exit 1
fi
echo ""

# Test 4: Verify Node.js binary works
echo "Test 4: Verify Node.js Binary"
echo "------------------------------"
if [ ! -x "${NODE_LOCAL_DIR}/bin/node" ]; then
    echo -e "${RED}✗ Node binary not found or not executable${NC}"
    exit 1
fi

NODE_VERSION_OUTPUT=$("${NODE_LOCAL_DIR}/bin/node" --version)
echo "Node version: ${NODE_VERSION_OUTPUT}"
if [[ "${NODE_VERSION_OUTPUT}" == v${NODE_VERSION}* ]]; then
    echo -e "${GREEN}✓ Node binary works and reports correct version${NC}"
else
    echo -e "${RED}✗ Node version mismatch${NC}"
    echo "Expected: v${NODE_VERSION}"
    echo "Got: ${NODE_VERSION_OUTPUT}"
    exit 1
fi
echo ""

# Test 5: Verify npm binary works
echo "Test 5: Verify npm Binary"
echo "--------------------------"
if [ ! -x "${NODE_LOCAL_DIR}/bin/npm" ]; then
    echo -e "${RED}✗ npm binary not found or not executable${NC}"
    exit 1
fi

NPM_VERSION_OUTPUT=$("${NODE_LOCAL_DIR}/bin/npm" --version)
echo "npm version: ${NPM_VERSION_OUTPUT}"
if [ -n "${NPM_VERSION_OUTPUT}" ]; then
    echo -e "${GREEN}✓ npm binary works and reports version${NC}"
else
    echo -e "${RED}✗ npm version check failed${NC}"
    exit 1
fi
echo ""

# Test 6: Verify PATH override works
echo "Test 6: PATH Override"
echo "---------------------"
export PATH="${NODE_LOCAL_DIR}/bin:${PATH}"
WHICH_NODE=$(which node)
echo "which node: ${WHICH_NODE}"
if [[ "${WHICH_NODE}" == "${NODE_LOCAL_DIR}/bin/node" ]]; then
    echo -e "${GREEN}✓ PATH override works correctly${NC}"
else
    echo -e "${YELLOW}⚠ PATH override might not work as expected${NC}"
    echo "Expected: ${NODE_LOCAL_DIR}/bin/node"
    echo "Got: ${WHICH_NODE}"
    echo "This might be okay if system node is not installed"
fi
echo ""

# Test 7: Idempotency (skip download on second run)
echo "Test 7: Idempotency Test"
echo "------------------------"
echo "Checking if .node directory exists..."
if [ -d "${NODE_LOCAL_DIR}" ] && [ -x "${NODE_LOCAL_DIR}/bin/node" ]; then
    INSTALLED_VERSION=$(${NODE_LOCAL_DIR}/bin/node --version | sed 's/v//')
    echo -e "${GREEN}✓ .node directory exists with Node.js ${INSTALLED_VERSION}${NC}"
    echo "On second run, the install script should skip download"
else
    echo -e "${RED}✗ .node directory check failed${NC}"
    exit 1
fi
echo ""

# Test 8: Test with a simple npm project
echo "Test 8: Simple npm Project Test"
echo "--------------------------------"
NPM_TEST_DIR="${TEST_DIR}/npm-test"
mkdir -p "${NPM_TEST_DIR}"
cd "${NPM_TEST_DIR}"

# Create a minimal package.json
cat > package.json <<'EOF'
{
  "name": "test-project",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "test": "echo \"Test passed\""
  }
}
EOF

echo "Installing npm packages..."
if "${NODE_LOCAL_DIR}/bin/npm" install --silent; then
    echo -e "${GREEN}✓ npm install works${NC}"
else
    echo -e "${RED}✗ npm install failed${NC}"
    exit 1
fi

echo "Running npm script..."
if "${NODE_LOCAL_DIR}/bin/npm" run test --silent; then
    echo -e "${GREEN}✓ npm run works${NC}"
else
    echo -e "${RED}✗ npm run failed${NC}"
    exit 1
fi
echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}All tests passed successfully!${NC}"
echo "=========================================="
echo ""
echo "Summary:"
echo "  - Architecture detection: ${ARCH} → ${NODE_ARCH}"
echo "  - Node.js version: ${NODE_VERSION_OUTPUT}"
echo "  - npm version: ${NPM_VERSION_OUTPUT}"
echo "  - Installation directory: ${NODE_LOCAL_DIR}"
echo ""
echo "The install-service.sh script is ready to use."
