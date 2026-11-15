#!/usr/bin/env bash
# verify-deploy-isolation.sh [DEPLOY_PREFIX] — READ-ONLY check that the
# deployment runs only what was deployed. Part of `make verify-deploy`.
#
# Fails on three things the other verify-deploy checks cannot see, each found
# on a real station:
#
#   1. Runtime unit state under /run/systemd: a drop-in (or a whole unit)
#      written with `systemctl edit --runtime` or by hand. It outranks
#      /etc/systemd/system, is in no repo and survives a redeploy, and it
#      silently disappears at the next reboot. One kept an agent running
#      experimental code from a home-directory checkout across a deploy.
#   2. A home-directory path (/home/..., /Users/...) in a unit's effective
#      ExecStart*, Environment (e.g. PYTHONPATH), WorkingDirectory, or in an
#      EnvironmentFile it loads. /run/user/<uid> (a session's PulseAudio
#      socket) is not a home directory and is fine.
#   3. A deployed venv that depends on a home directory: an interpreter
#      symlinked into one (a uv- or pyenv-managed Python), pyvenv.cfg, script
#      shebangs, .pth / .egg-link / editable-finder files, or an editable
#      install's direct_url.json. (A regular install *from* a checkout is a
#      copy and only records its origin, so it passes.) A copied dev venv once left 35 scripts and 4 editable
#      .pth files pointing into a checkout.
#
# Environment (for tests): SYSTEMCTL (default systemctl).
# Exit status: 0 clean, 1 if anything above was found.
set -uo pipefail

PREFIX="${1:-${DEPLOY_PREFIX:-/opt/orpheus}}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
HOME_RE='/(home|Users)/'
fail=0

ok() { printf '✅ %s\n' "$1"; }
bad() { printf '❌ %s\n' "$1"; fail=1; }
info() { printf '⚠️  %s\n' "$1"; }

# --- 1 + 2: unit state ---------------------------------------------------------
if command -v "${SYSTEMCTL}" >/dev/null 2>&1; then
    units="$("${SYSTEMCTL}" list-unit-files 'orpheus-*.service' 'orpheus-*.timer' --no-legend 2>/dev/null | awk '{print $1}')"
    if [[ -z "${units}" ]]; then
        info "no orpheus-* units installed on this host"
    fi
    unit_problems=0
    for u in ${units}; do
        props="$("${SYSTEMCTL}" show -p FragmentPath -p DropInPaths -p ExecStartPre -p ExecStart \
            -p ExecStartPost -p ExecStop -p Environment -p EnvironmentFiles -p WorkingDirectory "${u}" 2>/dev/null)"

        fragment="$(printf '%s\n' "${props}" | sed -n 's/^FragmentPath=//p')"
        if [[ "${fragment}" == /run/systemd/* ]]; then
            bad "${u}: the unit itself is runtime-only (${fragment}); it is lost at reboot"
            unit_problems=1
        fi
        for d in $(printf '%s\n' "${props}" | sed -n 's/^DropInPaths=//p'); do
            if [[ "${d}" == /run/systemd/* ]]; then
                bad "${u}: runtime drop-in ${d} (outranks /etc, survives a redeploy, lost at reboot)"
                unit_problems=1
            fi
        done

        while IFS= read -r line; do
            [[ -n "${line}" ]] || continue
            key="${line%%=*}"
            case "${key}" in
                FragmentPath|DropInPaths) continue ;;
            esac
            if printf '%s\n' "${line}" | grep -qE "${HOME_RE}"; then
                hit="$(printf '%s\n' "${line}" | grep -oE "[^ =:;\"']*${HOME_RE}[^ :;\"']*" | head -n 1)"
                bad "${u}: ${key} uses a home-directory path (${hit:-?})"
                unit_problems=1
            fi
        done <<< "${props}"

        # EnvironmentFiles=/path (ignore_errors=yes) — check what they set.
        for envfile in $(printf '%s\n' "${props}" | sed -n 's/^EnvironmentFiles=//p' | sed 's/ (ignore_errors=[a-z]*)//g'); do
            [[ -r "${envfile}" ]] || continue
            if grep -vE '^[[:space:]]*#' "${envfile}" | grep -qE "${HOME_RE}"; then
                bad "${u}: EnvironmentFile ${envfile} sets a home-directory path"
                unit_problems=1
            fi
        done
    done
    if [[ -n "${units}" && "${unit_problems}" -eq 0 ]]; then
        ok "units: no runtime (/run/systemd) overrides, no home-directory paths"
    fi
else
    info "${SYSTEMCTL} not found (not a systemd host) — unit checks skipped"
fi

# --- 3: deployed venvs -----------------------------------------------------------
if [[ ! -d "${PREFIX}" ]]; then
    info "nothing deployed at ${PREFIX} — venv checks skipped"
    exit "${fail}"
fi

shopt -s nullglob
venvs=("${PREFIX}"/platform/*/venv "${PREFIX}"/agents/*/venv "${PREFIX}"/services/*/venv "${PREFIX}"/ui/venv)
for v in "${venvs[@]}"; do
    [[ -d "${v}" ]] || continue
    hits=()
    if [[ -f "${v}/pyvenv.cfg" ]] && grep -qE "${HOME_RE}" "${v}/pyvenv.cfg"; then
        hits+=("pyvenv.cfg")
    fi
    for f in "${v}"/bin/*; do
        if [[ -L "${f}" ]]; then
            target="$(readlink -f "${f}" 2>/dev/null || readlink "${f}")"
            if printf '%s\n' "${target}" | grep -qE "^${HOME_RE}"; then
                hits+=("bin/$(basename "${f}") -> ${target}")
            fi
        elif [[ -f "${f}" ]] && head -n 1 "${f}" 2>/dev/null | grep -aqE "^#!.*${HOME_RE}"; then
            hits+=("bin/$(basename "${f}") (shebang)")
        fi
    done
    for f in "${v}"/lib/python3*/site-packages/*.pth "${v}"/lib/python3*/site-packages/*.egg-link \
             "${v}"/lib/python3*/site-packages/__editable___*_finder.py; do
        if grep -qE "${HOME_RE}" "${f}" 2>/dev/null; then
            hits+=("${f#"${v}"/lib/}")
        fi
    done
    # direct_url.json records where a package was installed from. Only an
    # editable install keeps importing from there; a regular install from a
    # checkout is a copy and merely remembers its origin.
    for f in "${v}"/lib/python3*/site-packages/*.dist-info/direct_url.json; do
        if grep -qE '"editable": *true' "${f}" 2>/dev/null && grep -qE "${HOME_RE}" "${f}"; then
            hits+=("${f#"${v}"/lib/} (editable)")
        fi
    done
    if [[ ${#hits[@]} -eq 0 ]]; then
        ok "${v}"
    else
        bad "${v}: ${#hits[@]} file(s) depend on a home directory, e.g."
        printf '     %s\n' "${hits[@]:0:3}"
    fi
done
if [[ ${#venvs[@]} -eq 0 ]]; then
    info "no deployed venvs under ${PREFIX}"
fi

exit "${fail}"
