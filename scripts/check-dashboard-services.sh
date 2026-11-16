#!/bin/bash
# Check that every dashboard.services entry names a real, installed unit.
#
# The dashboard's Service Status card shows exactly the units listed in
# dashboard.services. An upgrade that renames or retires a service keeps the
# operator's list as it was, so without this check the dashboard goes on
# showing the old names: a retired unit as "stopped", or a renamed one as
# "running" through its leftover Alias=. Reads only; changes nothing.
#
#   check-dashboard-services.sh [CONFIG]   (default /opt/orpheus/config/orpheus.yaml)
#
# Prints one line per entry and exits 0 when all are current, 1 when any is
# stale. SYSTEMCTL overrides the systemctl binary (tests).
set -uo pipefail

config="${1:-/opt/orpheus/config/orpheus.yaml}"
systemctl="${SYSTEMCTL:-systemctl}"

if [[ ! -r "${config}" ]]; then
    echo "⚠️  ${config} not readable — dashboard.services not checked"
    exit 0
fi

services=$(python3 - "${config}" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as fh:
    data = yaml.safe_load(fh) or {}
value = (data.get("dashboard") or {}).get("services")
if value is None:
    sys.exit(3)
if isinstance(value, str):
    value = [item.strip() for item in value.split(",") if item.strip()]
for item in value:
    print(item)
PY
)
rc=$?
if [[ "${rc}" -eq 3 ]]; then
    echo "✅ dashboard.services not set — the built-in default inventory is used"
    exit 0
elif [[ "${rc}" -ne 0 ]]; then
    echo "⚠️  could not read dashboard.services from ${config}"
    exit 0
fi

stale=0
while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    unit="${name}.service"
    props=$("${systemctl}" show "${unit}" --property=Id,LoadState 2>/dev/null || true)
    load=$(sed -n 's/^LoadState=//p' <<< "${props}")
    id=$(sed -n 's/^Id=//p' <<< "${props}")
    if [[ "${load}" == "not-found" ]]; then
        echo "⚠️  ${name}: not installed — remove it from dashboard.services (retired or renamed)"
        stale=1
    elif [[ -n "${id}" && "${id}" != "${unit}" ]]; then
        echo "⚠️  ${name}: an alias of ${id} — list '${id%.service}' in dashboard.services instead"
        stale=1
    elif [[ -z "${load}" ]]; then
        echo "⚠️  ${name}: systemd returned no state"
        stale=1
    else
        echo "✅ ${name}"
    fi
done <<< "${services}"

if [[ "${stale}" -ne 0 ]]; then
    echo "   The dashboard shows these names as listed; config/orpheus.example.yaml has the current inventory."
fi
exit "${stale}"
