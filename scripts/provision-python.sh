#!/usr/bin/env bash
# provision-python.sh — install a pinned CPython for the services that need a
# newer interpreter than the OS ships (GPS and the event correlator require
# 3.12 or 3.13, ADR 0024; JetPack 5 / Ubuntu 20.04 has 3.8 and 3.9 only).
#
#   sudo scripts/provision-python.sh [--dry-run]
#   then: PYTHON_BIN=/opt/orpheus/python/bin/python3.12 for those installers
#
# One option for the host, not the only one: a distribution package (e.g. a
# PPA) works as well if it is available for the release. Whatever provides
# the interpreter, it must live outside every home directory, because the
# deployed venvs keep pointing at it for as long as they exist, and
# `make verify-deploy` fails a venv whose interpreter resolves into /home.
#
# This uses uv's python-build-standalone builds (verified on JetPack 5,
# aarch64, glibc 2.31) and installs them under PREFIX:
#
#   PREFIX/cpython-<version>-linux-<arch>-gnu/   the interpreter, read-only
#   PREFIX/bin/python<major.minor>               stable symlink to it
#
# The symlink names the exact patch release, not uv's floating minor-version
# directory, so a venv never changes interpreter underneath a running
# service; a later patch upgrade is a deliberate re-run plus venv rebuilds.
# uv itself is needed only while provisioning; it may live anywhere (e.g.
# ~/.local/bin). Its cache and config are kept out of the way: a throwaway
# cache, no user config, nothing written to a home directory.
#
# Environment: PYTHON_VERSION (default 3.12.13), PREFIX (default
# /opt/orpheus/python), UV (default: uv on PATH, then ~/.local/bin/uv,
# then ~SUDO_USER/.local/bin/uv).
set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.12.13}"
PREFIX="${PREFIX:-/opt/orpheus/python}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

die() { printf '[ERROR] %s\n' "$1" >&2; exit 1; }
log() { printf '[INFO] %s\n' "$1"; }

[[ "${PYTHON_VERSION}" =~ ^3\.[0-9]+\.[0-9]+$ ]] || die "PYTHON_VERSION must be an exact release such as 3.12.13; got '${PYTHON_VERSION}'"
MINOR="${PYTHON_VERSION%.*}"
case "${PREFIX}" in
    /home/*|/Users/*|/root/*) die "PREFIX ${PREFIX} is inside a home directory; deployed venvs would depend on it" ;;
    /*) ;;
    *) die "PREFIX must be an absolute path; got '${PREFIX}'" ;;
esac

if [[ -z "${UV:-}" ]]; then
    for candidate in "$(command -v uv 2>/dev/null || true)" "${HOME:-/nonexistent}/.local/bin/uv" \
                     "$(getent passwd "${SUDO_USER:-}" 2>/dev/null | cut -d: -f6)/.local/bin/uv"; do
        if [[ -n "${candidate}" && -x "${candidate}" ]]; then UV="${candidate}"; break; fi
    done
fi
[[ -n "${UV:-}" && -x "${UV}" ]] || die "uv not found; set UV=/path/to/uv (it is only needed while provisioning)"

arch="$(uname -m)"
target="${PREFIX}/cpython-${PYTHON_VERSION}-linux-${arch}-gnu"
link="${PREFIX}/bin/python${MINOR}"

log "uv:          ${UV} ($("${UV}" --version 2>/dev/null || echo '?'))"
log "interpreter: CPython ${PYTHON_VERSION} (${arch}) -> ${target}"
log "symlink:     ${link}"
if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "dry run: nothing was installed"
    exit 0
fi

cache="$(mktemp -d)"
trap 'rm -rf -- "${cache:?}"' EXIT
mkdir -p "${PREFIX}/bin"
UV_NO_CONFIG=1 UV_CACHE_DIR="${cache}" UV_PYTHON_INSTALL_DIR="${PREFIX}" \
    "${UV}" python install --no-bin --no-registry "${PYTHON_VERSION}"

py="${target}/bin/python${MINOR}"
[[ -x "${py}" ]] || die "uv finished but ${py} does not exist"
ln -sfn "${py}" "${link}"

# The interpreter has to be usable for venvs, TLS (pip) and the stdlib
# modules the services import, and must not resolve into a home directory.
got="$("${link}" -c 'import platform; print(platform.python_version())')"
[[ "${got}" == "${PYTHON_VERSION}" ]] || die "${link} reports ${got}, expected ${PYTHON_VERSION}"
"${link}" -c 'import ssl, sqlite3, ctypes, venv, ensurepip, zlib, lzma, bz2, json' \
    || die "${link} is missing a standard-library module the services need"
real="$(readlink -f "${link}")"
case "${real}" in
    /home/*|/Users/*|/root/*) die "${link} resolves into a home directory (${real})" ;;
esac
chmod -R go-w "${target}"

log "✅ CPython ${got} at ${link} (-> ${real})"
log "   e.g. sudo PYTHON_BIN=${link} bash agents/orpheus-agent-event-correlator/systemd/install-service.sh"
