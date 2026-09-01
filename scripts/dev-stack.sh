#!/usr/bin/env bash
# ===========================================================================
# Orpheus Dev Stack — Background process manager for macOS development
# ===========================================================================
# Manages the Observe stack as background processes with PID tracking,
# per-service log files, and individual restart capability.
#
# Usage:
#   ./scripts/dev-stack.sh start   [name...]   # Start all or named services
#   ./scripts/dev-stack.sh stop    [name...]   # Stop all or named services
#   ./scripts/dev-stack.sh restart [name...]   # Restart all or named services
#   ./scripts/dev-stack.sh status              # Show running/stopped status
#   ./scripts/dev-stack.sh logs    [name]      # Tail logs (all or one service)
#
# Makefile integration:
#   make dev-stack       →  start
#   make dev-stop        →  stop
#   make dev-restart     →  restart
#   make dev-status      →  status
#   make dev-logs        →  logs
# ===========================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
LOG_DIR="${REPO_ROOT}/logs"
PID_DIR="${REPO_ROOT}/.dev-stack/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

# Per-service log files are unbounded: a chatty agent in a long session grows
# logs/<service>.log until the checkout fills the disk. Services append with
# >>, which holds an open fd — renaming the file would leave the writer
# appending to the renamed inode, so the cap has to truncate IN PLACE. O_APPEND
# means the next write lands at offset 0, which is why this works without
# restarting anything.
LOG_MAX_BYTES="${ORPHEUS_DEV_LOG_MAX_BYTES:-52428800}"   # 50 MB per service
LOG_KEEP_LINES="${ORPHEUS_DEV_LOG_KEEP_LINES:-2000}"     # tail kept across a trim
REAPER_PID_FILE="${PID_DIR}/.log-reaper.pid"

trim_oversized_logs() {
    local f size keep
    for f in "$LOG_DIR"/*.log; do
        [ -f "$f" ] || continue
        size="$(wc -c < "$f" 2>/dev/null | tr -d ' ')"
        [ -n "$size" ] || continue
        [ "$size" -gt "$LOG_MAX_BYTES" ] || continue
        keep="${f}.trim"
        tail -n "$LOG_KEEP_LINES" "$f" > "$keep" 2>/dev/null || : > "$keep"
        : > "$f"
        cat "$keep" >> "$f" 2>/dev/null || true
        rm -f "$keep"
        echo "[dev-stack] log passed ${LOG_MAX_BYTES} bytes and was trimmed to the last ${LOG_KEEP_LINES} lines" >> "$f"
    done
}

start_log_reaper() {
    stop_log_reaper
    (
        while true; do
            sleep 60
            trim_oversized_logs
        done
    ) >/dev/null 2>&1 &
    echo "$!" > "$REAPER_PID_FILE"
}

stop_log_reaper() {
    local pid
    [ -f "$REAPER_PID_FILE" ] || return 0
    pid="$(cat "$REAPER_PID_FILE" 2>/dev/null || true)"
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    rm -f "$REAPER_PID_FILE"
}

# ---------------------------------------------------------------------------
# Colors and helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

log()  { echo -e "${GREEN}[dev-stack]${NC} $*"; }
warn() { echo -e "${YELLOW}[dev-stack]${NC} $*"; }
err()  { echo -e "${RED}[dev-stack]${NC} $*" >&2; }
ok()   { echo -e "  ${GREEN}✔${NC} $*"; }
fail() { echo -e "  ${RED}✘${NC} $*"; }
skip() { echo -e "  ${DIM}–${NC} $*"; }

# ---------------------------------------------------------------------------
# Service registry
# ---------------------------------------------------------------------------
# Format: name|directory|command
# Order matters — services start top-to-bottom.
SERVICES=(
    "backplane|_backplane_|_backplane_"
    "audio-motion|agents/orpheus-agent-audio-motion|make run"
    "audio-events|agents/orpheus-agent-audio-events|make run"
    "audio-playback|agents/orpheus-agent-audio-playback|make run"
    "bird-detection|agents/orpheus-agent-bird-detection|make run"
    "crow-detection|agents/orpheus-agent-crow-detection|make run"
    "video-motion|agents/orpheus-agent-video-motion|make run"
    "video-snapshotter|agents/orpheus-agent-video-snapshotter|make run"
    "video-timelapser|agents/orpheus-agent-video-timelapser|make run"
    "event-correlator|agents/orpheus-agent-event-correlator|make run"
    "gps|services/orpheus-gps|make run"
    "orpheus-ui-backend|services/orpheus_ui|make run-backend"
    "orpheus-ui-frontend|services/orpheus_ui|make run-frontend"
)

service_name() { echo "$1" | cut -d'|' -f1; }
service_dir()  { echo "$1" | cut -d'|' -f2; }
service_cmd()  { echo "$1" | cut -d'|' -f3; }

all_service_names() {
    for entry in "${SERVICES[@]}"; do
        service_name "$entry"
    done
}

find_service() {
    local target="$1"
    for entry in "${SERVICES[@]}"; do
        if [ "$(service_name "$entry")" = "$target" ]; then
            echo "$entry"
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# Model provisioning
# ---------------------------------------------------------------------------
provision_models() {
    local model_dir="${ORPHEUS_STORAGE__BASE_PATH}/models"
    local artifact_dir="${REPO_ROOT}/artifacts/models"

    mkdir -p "$model_dir"

    if [ ! -d "$artifact_dir" ]; then
        warn "artifacts/models/ not found — run 'git lfs pull' to fetch models."
        return 0
    fi

    # Check for LFS pointer files (not yet pulled)
    local sample_file="${artifact_dir}/birdnet.onnx"
    if [ -f "$sample_file" ]; then
        local size
        size="$(wc -c < "$sample_file" | tr -d ' ')"
        if [ "$size" -lt 1000 ]; then
            warn "Models appear to be LFS pointers (not pulled)."
            warn "  Run: git lfs pull"
            return 0
        fi
    fi

    local linked=0
    for src in "$artifact_dir"/*; do
        local fname
        fname="$(basename "$src")"
        local dest="${model_dir}/${fname}"
        if [ ! -e "$dest" ]; then
            ln -sf "$src" "$dest"
            linked=$((linked + 1))
        fi
    done
    if [ "$linked" -gt 0 ]; then
        ok "Linked ${linked} model file(s) → ${model_dir}/"
    else
        ok "Models already in ${model_dir}/"
    fi
}

# ---------------------------------------------------------------------------
# Environment setup (shared by start/restart)
# ---------------------------------------------------------------------------
load_env() {
    # Use the canonical Jetson config as the base. macOS-specific overrides
    # (audio channels, storage path) live in config/.env.orpheus which
    # OrpheusConfig loads automatically.
    ORPHEUS_CONFIG_PATH="${REPO_ROOT}/config/orpheus.example.yaml"
    if [ ! -f "$ORPHEUS_CONFIG_PATH" ]; then
        err "Config not found: $ORPHEUS_CONFIG_PATH"
        err "Run from the repo root or check your clone."
        exit 1
    fi
    export ORPHEUS_CONFIG_PATH

    # Source macOS / local overrides (e.g. single laptop mic instead of
    # four-channel ALSA).  The dotenv file sets env vars like
    # ORPHEUS_AUDIO__CHANNELS that OrpheusConfig picks up.  We source it
    # here so the variables are exported into the child processes (agents
    # cd into their own directories, so the relative dotenv path inside
    # OrpheusConfig won't resolve).
    local dotenv="${REPO_ROOT}/config/.env.orpheus"
    if [ -f "$dotenv" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$dotenv"
        set +a
        ok "Loaded overrides from config/.env.orpheus"
    fi

    # Storage path: use env override if set, otherwise default to ~/data/orpheus.
    # To override: ORPHEUS_STORAGE__BASE_PATH=~/data/orpheus make dev-stack
    if [ -z "${ORPHEUS_STORAGE__BASE_PATH:-}" ]; then
        export ORPHEUS_STORAGE__BASE_PATH="${HOME}/data/orpheus"
    fi
    mkdir -p "${ORPHEUS_STORAGE__BASE_PATH}"

    # Provision models: symlink from artifacts/models/ if not already present
    provision_models
}

# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------
pid_file()    { echo "${PID_DIR}/${1}.pid"; }
read_pid()    { [ -f "$(pid_file "$1")" ] && cat "$(pid_file "$1")" || echo ""; }
write_pid()   { echo "$2" > "$(pid_file "$1")"; }
remove_pid()  { rm -f "$(pid_file "$1")"; }

is_running() {
    local pid
    pid="$(read_pid "$1")"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
preflight() {
    log "Preflight checks..."

    # Python
    PYTHON_BIN=""
    if command -v python3.9 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3.9)"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    elif command -v uv >/dev/null 2>&1; then
        UV_PYTHON="$(uv python find 3.9.5 2>/dev/null || true)"
        if [ -n "$UV_PYTHON" ]; then
            PYTHON_BIN="$UV_PYTHON"
        fi
    fi
    if [ -z "$PYTHON_BIN" ]; then
        err "Python 3.9+ not found. Install via: uv python install 3.9.5"
        exit 1
    fi
    if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
        err "Python at ${PYTHON_BIN} is not 3.9+."
        exit 1
    fi
    ok "Python $(${PYTHON_BIN} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"

    # Messaging backplane broker (NATS + JetStream is the default transport)
    if ! command -v nats-server >/dev/null 2>&1; then
        err "nats-server not found. Install via: brew install nats-server"
        err "  (or: make -C services/orpheus-backplane install)"
        exit 1
    fi
    ok "nats-server installed"

    # Venvs
    local missing=()
    for dir in \
        agents/orpheus-agent-audio-motion \
        agents/orpheus-agent-audio-playback \
        agents/orpheus-agent-audio-events \
        agents/orpheus-agent-bird-detection \
        agents/orpheus-agent-crow-detection \
        agents/orpheus-agent-video-motion \
        agents/orpheus-agent-video-snapshotter \
        agents/orpheus-agent-video-timelapser \
        agents/orpheus-agent-event-correlator \
        services/orpheus-gps \
        services/orpheus_ui/backend; do
        if [ ! -d "${dir}/venv" ]; then
            missing+=("$dir")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        warn "Missing venvs — installing now..."
        for dir in "${missing[@]}"; do
            log "  Installing ${dir}..."
            make -C "$dir" install
        done
    fi

    # Frontend node_modules
    if [ ! -d "services/orpheus_ui/frontend/node_modules" ]; then
        warn "Missing frontend node_modules — installing now..."
        make -C services/orpheus_ui/frontend install
    fi
    ok "All venvs ready"
    echo ""
}

# ---------------------------------------------------------------------------
# Start a single service
# ---------------------------------------------------------------------------
start_one() {
    local name="$1"

    if is_running "$name"; then
        skip "${name} already running (pid $(read_pid "$name"))"
        return 0
    fi

    local entry
    if ! entry="$(find_service "$name")"; then
        err "Unknown service: ${name}"
        return 1
    fi

    local dir cmd logfile

    # --- Messaging backplane (NATS + JetStream) is special ---
    if [ "$name" = "backplane" ]; then
        if pgrep -x nats-server >/dev/null 2>&1; then
            local existing_pid
            existing_pid="$(pgrep -x nats-server)"
            write_pid "backplane" "$existing_pid"
            ok "backplane (nats-server) already running (pid ${existing_pid}, external)"
            return 0
        fi
        logfile="${LOG_DIR}/backplane.log"
        local store="${ORPHEUS_DATA_ROOT:-/tmp/orpheus}/backplane/jetstream"
        mkdir -p "$store"
        ORPHEUS_BACKPLANE_STORE="$store" nats-server \
            -c services/orpheus-backplane/config/nats.conf > "$logfile" 2>&1 &
        write_pid "backplane" "$!"
        sleep 1
        if kill -0 "$(read_pid backplane)" 2>/dev/null; then
            ok "backplane (NATS+JetStream) started (pid $(read_pid backplane))"
        else
            fail "backplane failed to start — check ${logfile}"
            return 1
        fi
        return 0
    fi

    # --- orpheus-ui-backend: kill stale processes on port 8082 ---
    if [ "$name" = "orpheus-ui-backend" ]; then
        local stale_pids
        stale_pids="$(lsof -ti :8082 2>/dev/null || true)"
        if [ -n "$stale_pids" ]; then
            warn "Killing stale process(es) on port 8082: ${stale_pids}"
            echo "$stale_pids" | xargs kill -9 2>/dev/null || true
            sleep 0.5
        fi
    fi

    # --- Crow detection: skip if model missing ---
    if [ "$name" = "crow-detection" ]; then
        local aves_model="${ORPHEUS_STORAGE__BASE_PATH}/models/aves-base-bio.pt"
        if [ ! -f "$aves_model" ]; then
            skip "crow-detection (AVES model not found at ${aves_model})"
            return 0
        fi
    fi

    # --- Bird detection: skip if model missing ---
    if [ "$name" = "bird-detection" ]; then
        local birdnet_model="${ORPHEUS_STORAGE__BASE_PATH}/models/birdnet.onnx"
        if [ ! -f "$birdnet_model" ]; then
            skip "bird-detection (birdnet.onnx not found at ${birdnet_model})"
            return 0
        fi
    fi

    dir="$(service_dir "$entry")"
    cmd="$(service_cmd "$entry")"
    logfile="${LOG_DIR}/${name}.log"

    if [ ! -d "${REPO_ROOT}/${dir}" ]; then
        skip "${name} — directory not found: ${dir}"
        return 0
    fi

    # Truncate old log for a clean start
    : > "$logfile"

    # Launch in background, capture the shell PID
    (
        cd "${REPO_ROOT}/${dir}"
        exec $cmd >> "$logfile" 2>&1
    ) &
    local pid=$!
    write_pid "$name" "$pid"

    # Brief pause to check it didn't die immediately
    sleep 0.5
    if kill -0 "$pid" 2>/dev/null; then
        ok "${name} started (pid ${pid}) → logs/${name}.log"
    else
        fail "${name} exited immediately — check logs/${name}.log"
        remove_pid "$name"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Stop a single service
# ---------------------------------------------------------------------------
# The recorded pid is the launch wrapper (`exec make run` → make), and the
# real service process is its CHILD — make does not forward signals, so
# killing only the recorded pid would orphan the actual python/node process
# with its ports still bound. Collect the descendant tree BEFORE signalling
# (children reparent to launchd the moment their parent dies and become
# unfindable), then signal deepest-first.
# Only pids reached from OUR recorded pid are ever touched.
collect_tree() {
    local pid="$1"
    local child
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        collect_tree "$child"
    done
    echo "$pid"
}

stop_one() {
    local name="$1"
    local pid
    pid="$(read_pid "$name")"

    if [ -z "$pid" ]; then
        skip "${name} not tracked"
        remove_pid "$name"
        return 0
    fi

    if ! kill -0 "$pid" 2>/dev/null; then
        skip "${name} already stopped (stale pid ${pid})"
        remove_pid "$name"
        return 0
    fi

    # Kill the recorded pid and every live descendant (external brokers
    # adopted by pid match have no wrapper, so this degrades to the old
    # single-pid kill for them).
    local victims v
    victims="$(collect_tree "$pid")"
    for v in $victims; do
        kill "$v" 2>/dev/null || true
    done

    # Wait up to 5 seconds for the whole tree to exit gracefully
    local waited=0 alive=1
    while [ $waited -lt 5 ]; do
        alive=0
        for v in $victims; do
            if kill -0 "$v" 2>/dev/null; then
                alive=1
                break
            fi
        done
        [ "$alive" = "0" ] && break
        sleep 1
        waited=$((waited + 1))
    done

    # Force kill any stragglers
    for v in $victims; do
        if kill -0 "$v" 2>/dev/null; then
            kill -9 "$v" 2>/dev/null || true
        fi
    done

    remove_pid "$name"
    ok "${name} stopped (was pid ${pid})"
}

# ---------------------------------------------------------------------------
# Resolve service list: either explicit names or all
# ---------------------------------------------------------------------------
resolve_services() {
    if [ $# -gt 0 ]; then
        echo "$@"
    else
        all_service_names
    fi
}

# ===========================================================================
# Commands
# ===========================================================================

cmd_start() {
    load_env
    preflight

    local services
    services=($(resolve_services "$@"))
    local started=0 failed=0 skipped_count=0

    trim_oversized_logs
    start_log_reaper

    log "Starting Orpheus dev stack..."
    echo ""

    for name in "${services[@]}"; do
        if start_one "$name"; then
            started=$((started + 1))
        else
            failed=$((failed + 1))
        fi
    done

    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}  Orpheus Observe Stack${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  UI backend:  ${CYAN}http://localhost:8082${NC}  (API)"
    echo -e "  UI frontend: ${CYAN}http://localhost:5173${NC}  (dev server)"
    echo -e "  Backplane (NATS+JetStream): ${CYAN}localhost:4222${NC}"
    echo ""
    echo -e "  ${DIM}Logs:   logs/<service>.log${NC}"
    echo -e "  ${DIM}PIDs:   .dev-stack/pids/<service>.pid${NC}"
    echo ""
    echo -e "  ${BOLD}Commands:${NC}"
    echo -e "    make dev-status    — see what's running"
    echo -e "    make dev-logs      — tail all logs"
    echo -e "    make dev-stop      — stop everything"
    echo -e "    make dev-restart   — restart everything"
    echo -e "    make dev-restart SVC=orpheus-ui-backend  — restart one service"
    echo ""

    if [ "$failed" -gt 0 ]; then
        warn "${failed} service(s) failed to start — check logs above."
    fi
}

cmd_stop() {
    local services
    services=($(resolve_services "$@"))

    stop_log_reaper

    log "Stopping services..."
    echo ""

    # Stop in reverse order
    local reversed=()
    for name in "${services[@]}"; do
        reversed=("$name" "${reversed[@]}")
    done

    for name in "${reversed[@]}"; do
        stop_one "$name"
    done

    echo ""
    log "Done."
}

cmd_restart() {
    local services
    services=($(resolve_services "$@"))

    log "Restarting services..."
    echo ""

    # Stop
    local reversed=()
    for name in "${services[@]}"; do
        reversed=("$name" "${reversed[@]}")
    done
    for name in "${reversed[@]}"; do
        stop_one "$name"
    done

    echo ""

    # Start
    load_env
    if [ ${#services[@]} -eq $(echo "${SERVICES[@]}" | tr ' ' '\n' | wc -l) ]; then
        preflight
    fi

    for name in "${services[@]}"; do
        start_one "$name"
    done

    echo ""
    log "Restart complete."
}

cmd_status() {
    local running=0 stopped=0

    echo ""
    echo -e "${BOLD}  Orpheus Dev Stack Status${NC}"
    echo -e "  ─────────────────────────────────────────"
    printf "  ${BOLD}%-20s %-10s %-8s %s${NC}\n" "SERVICE" "STATUS" "PID" "LOG"
    echo -e "  ─────────────────────────────────────────"

    for entry in "${SERVICES[@]}"; do
        local name
        name="$(service_name "$entry")"
        local pid
        pid="$(read_pid "$name")"
        local logfile="logs/${name}.log"

        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            printf "  ${GREEN}%-20s${NC} ${GREEN}%-10s${NC} %-8s %s\n" "$name" "running" "$pid" "$logfile"
            running=$((running + 1))
        elif [ -n "$pid" ]; then
            printf "  ${RED}%-20s${NC} ${RED}%-10s${NC} %-8s %s\n" "$name" "dead" "$pid" "$logfile"
            stopped=$((stopped + 1))
        else
            printf "  ${DIM}%-20s %-10s %-8s %s${NC}\n" "$name" "stopped" "–" "$logfile"
            stopped=$((stopped + 1))
        fi
    done

    echo -e "  ─────────────────────────────────────────"
    echo -e "  ${GREEN}${running} running${NC}  ${DIM}${stopped} stopped${NC}"
    echo ""
}

cmd_logs() {
    if [ $# -gt 0 ]; then
        local name="$1"
        local logfile="${LOG_DIR}/${name}.log"
        if [ ! -f "$logfile" ]; then
            err "No log file for '${name}' — expected ${logfile}"
            exit 1
        fi
        echo -e "${DIM}[tailing logs/${name}.log — Ctrl+C to stop]${NC}"
        tail -f "$logfile"
    else
        # Tail all active log files
        local logfiles=()
        for entry in "${SERVICES[@]}"; do
            local name
            name="$(service_name "$entry")"
            local logfile="${LOG_DIR}/${name}.log"
            if [ -f "$logfile" ]; then
                logfiles+=("$logfile")
            fi
        done
        if [ ${#logfiles[@]} -eq 0 ]; then
            err "No log files found in ${LOG_DIR}/"
            exit 1
        fi
        echo -e "${DIM}[tailing ${#logfiles[@]} log files — Ctrl+C to stop]${NC}"
        tail -f "${logfiles[@]}"
    fi
}

cmd_help() {
    echo "Orpheus Dev Stack — background process manager"
    echo ""
    echo "Usage:"
    echo "  $0 start   [name...]   Start all or named services"
    echo "  $0 stop    [name...]   Stop all or named services"
    echo "  $0 restart [name...]   Restart all or named services"
    echo "  $0 status              Show running/stopped status"
    echo "  $0 logs    [name]      Tail logs (all or one service)"
    echo ""
    echo "Services:"
    for entry in "${SERVICES[@]}"; do
        printf "  %-20s %s\n" "$(service_name "$entry")" "$(service_dir "$entry")"
    done
    echo ""
    echo "Examples:"
    echo "  $0 start                    # Start everything"
    echo "  $0 restart bird-detection   # Restart just bird-detection"
    echo "  $0 logs orpheus-ui-backend  # Tail UI backend logs"
    echo "  $0 stop                     # Stop everything"
}

# ===========================================================================
# Dispatch
# ===========================================================================
COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    start)   cmd_start "$@" ;;
    stop)    cmd_stop "$@" ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status ;;
    logs)    cmd_logs "$@" ;;
    help|--help|-h)  cmd_help ;;
    *)
        err "Unknown command: ${COMMAND}"
        echo ""
        cmd_help
        exit 1
        ;;
esac
