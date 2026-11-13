# PANNs GPU worker (opt-in)

This page covers installing and running PANNs in a separate GPU environment on a
Jetson Orin NX 16 GB with JetPack 5.1.3 (L4T R35.5), CUDA 11.4 and Python 3.8.
The audio-events agent stays in Python 3.9. Its existing in-process backend is
the default; no GPU worker is installed or started by a normal CPU installation.
A short side-by-side Jetson trial passed. Complete the validation below before
enabling the GPU backend for production.

## Install the optional environment

From your local checkout, install the agent as usual with
`make install-audio-events`. This also installs the small shared IPC library in
the agent environment. It does not install NVIDIA Torch or alter services.

On a compatible Jetson, obtain the exact NVIDIA wheel
`torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl` from
[NVIDIA's JetPack 5.1.2 wheel directory](https://developer.download.nvidia.com/compute/redist/jp/v512/pytorch/).
Its SHA-256 must be
`5112e2ef5051f1003ae2ffb545ae596377df66979d62a954d774f18009064dbe`.
Keep downloads under `$ORPHEUS_DATA_ROOT`. Then, from the checkout:

```bash
make install-panns-gpu PYTHON38=/usr/bin/python3.8 \
  NVIDIA_TORCH_WHEEL="$ORPHEUS_DATA_ROOT/downloads/torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl"
```

The target verifies the wheel and interpreter, creates
`$ORPHEUS_DATA_ROOT/venvs/panns-gpu`, and installs the archived dependency pins
and worker. It does not install `orpheus-common` in Python 3.8, use the generic
service installer, modify systemd, or replace the agent's Torch installation.
Do not upgrade dependencies inside this environment independently. The
`constraints.txt` and `wheels.sha256` beside the worker record the tested runtime.

Provision the normal Cnn14 DecisionLevelMax checkpoint through
`make download-models`; the worker verifies SHA-256
`dd3b4043a87d4ec13df8082c0fcfee3fb5084151808e47e060987a95eabdd142`.
A missing/different checkpoint fails visibly; the worker cannot download over it.
Labels and caches are staged under `$ORPHEUS_DATA_ROOT/gpu-workers/panns`.
Use the same writable data root for agent and worker.

## Select a backend

Add this to your local `orpheus.yaml`:

```yaml
audio_events:
  backend: auto
  gpu_worker:
    clip_ttl_seconds: 3.0
    max_pending_clips: 2
```

- `inprocess` (default) retains the existing model and `device: auto` selection
  inside Python 3.9. Set `device: cpu` for explicit CPU operation.
- `auto` selects the isolated GPU worker on Linux aarch64 when the configured
  executable exists and is executable, and host memory passes the start gate.
  Otherwise it selects CPU. Selection happens once at agent startup. The
  worker itself validates Python, Torch, CUDA and checkpoint during loading;
  those later failures remain visible recovery failures, not silent CPU fallback.
- `gpu_worker` requires the worker. A missing executable is a startup error;
  loading/runtime failures leave worker readiness false while supervision runs.
  The worker always requires CUDA, independently of `device`.

The default worker executable follows `$ORPHEUS_DATA_ROOT/venvs/panns-gpu/bin/python`.
Override it with `audio_events.gpu_worker.python` if needed. Launch the local
agent with `make -C agents/orpheus-agent-audio-events run`; existing service
deployment procedures are outside this optional install target.

## Run alongside the live CPU service

Use this one-off experiment from a separate checkout of this branch on the
station. Keep the CPU service running. The checkout needs its own Python 3.9
agent environment (`make install-audio-events`) and the separately installed
Python 3.8 worker from [the optional install](#install-the-optional-environment).
The launcher installs nothing and does not start, stop, restart or alter services.

Run from that checkout's root. These commands assume your station data root is
already exported as `ORPHEUS_DATA_ROOT` and the live YAML is
`/opt/orpheus/config/orpheus.yaml`. The command also points to the CPU
service's optional environment file. Use the service's paths if they differ.
If the environment file is absent, the loader skips it.

```bash
PANN_GPU_RUN="gpu-test-$(date -u +%Y%m%dT%H%M%S | tr '[:upper:]' '[:lower:]')"
PANN_GPU_SCRATCH="${ORPHEUS_DATA_ROOT:?}/experiments/$PANN_GPU_RUN"

ORPHEUS_DOTENV_PATH=/opt/orpheus/config/.env \
make --no-print-directory -C agents/orpheus-agent-audio-events run-gpu-experiment \
  ARGS="--backend gpu_worker \
    --live-config /opt/orpheus/config/orpheus.yaml \
    --scratch-root $PANN_GPU_SCRATCH \
    --instance-id $PANN_GPU_RUN \
    --checkpoint $ORPHEUS_DATA_ROOT/models/panns_cnn14_decision_level_max.pth \
    --worker-python $ORPHEUS_DATA_ROOT/venvs/panns-gpu/bin/python"
```

The scratch directory must **not exist**. Use a new run ID for each experiment.
The ID must begin `gpu-test-`, contain lowercase letters/digits/underscores/hyphens,
and differ from an inherited live `ORPHEUS_AGENT_INSTANCE_ID`. The launcher sets
that variable only inside the experiment process. It requires explicit
`gpu_worker`; `auto` and CPU fallback are unavailable on this launch path.

The test configuration is derived **in memory** from the live YAML and its normal
environment/dotenv overrides. It preserves the resolved NATS URL and connection
policy, input topic, CPU result topic and classification thresholds. Configuration
KV merging is disabled. After resolution, the launcher fixes the scratch root,
worker interpreter, read-only checkpoint reference, GPU backend and test output;
config/env overrides cannot redirect those to production. The checkpoint stays
in place, is read and hash-checked by the worker, and is never copied or rewritten.
Worker labels, home, temporary files and caches go under the scratch root.

With the standard live topics, the instance subscribes to
`orpheus/audio/motion/events` alongside the CPU service, and observes CPU results
on `orpheus/detection/audio/events`. Both receive the same clips; there is no
load-sharing queue group. Test detections publish only on:

```text
orpheus/experiments/panns-gpu/<run-id>/detections
```

The dotted NATS subject is
`orpheus.experiments.panns-gpu.<run-id>.detections`. A restricted EventBus rejects
production publications, retained messages and all KV/JetStream writes. Production
event-sourcing shadow, presence and health KV writes are disabled independently
of their live settings. Identifiable health uses the existing Actor instance
topic `orpheus/system/audio-events/<run-id>/health` and is also recorded locally.
The only writable detection DB is
`$PANN_GPU_SCRATCH/detections/orpheus.db`, explicitly supplied to the agent.

**Stop:** press **Ctrl-C** in the launch terminal. This stops the experiment and
reaps its worker; the CPU service keeps running. No cleanup command is required;
scratch results remain for inspection. Allow CPU results to catch up before
stopping, since CPU detections may arrive later than GPU detections.

### Read and compare the results

In a second terminal, set `PANN_GPU_SCRATCH` to the printed experiment path, then:

```bash
tail -f "$PANN_GPU_SCRATCH/health.jsonl"
```

Wait for `payload.worker.ready: true` and watch `events_processed`,
`detections_emitted`, `clips_rejected`, worker failures and available memory.
Logs also identify the run. The scratch directory contains:

| File | Contents |
|---|---|
| `run.json` | Run identity, topics, checkpoint/interpreter paths, TTL and thresholds; no broker credentials or full config. |
| `clips.jsonl` | Received live input events, receipt times and `experiment_worker_ready` at receipt. |
| `cpu.jsonl` | Observed live CPU detections, without reading or writing the production DB. |
| `gpu.jsonl` | Test GPU detections, also stored in the scratch SQLite DB. |
| `health.jsonl` | Startup, periodic and shutdown health for this instance. |

After stopping, or while it runs, compare captured results from the checkout root:

```bash
make --no-print-directory -C agents/orpheus-agent-audio-events compare-gpu-experiment \
  ARGS="--scratch-root $PANN_GPU_SCRATCH" > "$PANN_GPU_SCRATCH/comparison.json"
```

The report matches `(source_event_id, AudioSet taxonomy.id)`, lists CPU/GPU event
IDs, absolute confidence differences, intervals and per-clip inference times, and
lists unmatched labels. Detection `event_id` values differ because the two agents
create independent detections. Their `source_event_id` points to the same live
audio-motion event; `root_event_id` remains the original acoustic lineage. Duplicate
deliveries of the same source/class use the last captured result in the report.
The comparison reads scratch JSONL only and never opens the production database.

The normal clip TTL still applies: by default, three seconds after the source
recording ends, including queueing, preprocessing and inference. A motion timestamp
marks the start; its recorded duration is included, so a 35-second recording is
not immediately stale. Expired or overloaded clips are skipped before decoding;
clips received during loading/recovery are refused. Reload takes 12–15 seconds,
so those clips expire rather than waiting for recovery. Use the health counters
and input readiness markers to distinguish missing work from numerical differences.
An unmatched label alone does not prove a model disagreement, and zero matched
labels is not a parity result. This is a live observation experiment, not replay.

CPU and GPU share the Jetson's physical RAM. This test adds a roughly 4,702 MiB
startup footprint while the CPU model remains resident. The existing 8,704 MiB
start gate and 3,800 MiB running floor remain in force (or stricter live settings).
If the station lacks that headroom, the experiment stays memory-blocked; do not
lower the protections to force it to load.

## Budget memory and overload

The archived prototype passed 24 historical tests with bit-identical direct-GPU
results and 15.2 ms median IPC overhead. Its model load lowered host
`MemAvailable` by **4,702 MiB**, although its cgroup recorded only **1,734 MiB**.
On that cgroup-v1 station `MemoryHigh` was ineffective. Use host memory readings;
do not add RSS, allocator reservations and MemAvailable drops together.

| Setting | Default | Meaning |
|---|---:|---|
| `start_memory_mib` | 8704 | Minimum MemAvailable before starting/loading a worker. |
| `floor_memory_mib` | 3800 | Worker watchdog stop and agent admission floor. |
| `max_pending_clips` | 2 | Waiting clip references, in addition to one active clip. |
| `clip_ttl_seconds` | 3 | Lifetime after the source recording ends, including queueing, preprocessing and inference. |
| `max_clip_seconds` | 40 | Maximum decoded clip duration; header checked before decoding. |
| `startup_timeout_seconds` | 60 | Model load and warm-up deadline. |
| `request_timeout_seconds` | 5 | IPC deadline, shortened to the remaining clip lifetime. |
| `restart_backoff_seconds` | 2 | Initial restart delay, increasing to 30 seconds. |
| `max_starts` | 3 | Maximum starts within `restart_window_seconds` (default 300). |

Configuration cannot lower the floor below 3800 MiB or the start gate below the
floor plus 4702 MiB. These are provisional guards, not a guarantee against OOM.
Validate maximum clips with the complete station workload. The worker checks
host memory during loading, inference and idle time and exits on pressure or an
unreadable memory source. The parent stops admitting clips before decoding them.

Only one inference runs at a time. A full queue refuses new clips; expired clips
are discarded. Requests never wait for a model reload or transparently retry.
Reload took 12–15 seconds in the prototype, longer than a clip's default lifetime:
clips arriving during recovery are refused, and new clips resume after readiness.
Recorded audio remains available under normal retention; refused work is not
automatically replayed. Core NATS delivery is not a durable inference-job queue.
Late results can fragment correlation when late enrichment is disabled; keep
queue age short and inspect rejection counts before increasing the TTL.

## Check health and roll back

The existing audio-events health payload adds `backend`, `worker` and
`clips_rejected`. `model_loaded` reflects worker readiness, rather than the
existence of a proxy. Worker health includes state (`loading`, `ready`,
`recovering`, `memory_blocked`, `circuit_open`, `reap_failed`, `stopped`), starts, failures, last
error/exit code, PID, host memory and handshake runtime information. It uses the
same health topic and optional KV path as the agent; no new worker service or
dashboard panel is required. Worker logs go to the agent's stderr.

Supervision reaps idle crashes and reloads in the background. It disables recovery
and kills/reaps the child on agent shutdown. The child also exits on stdin EOF
or process-parent death, including during inference; it deliberately does not use
thread-scoped `PR_SET_PDEATHSIG`. Memory pressure or runtime failure never loads
a second CPU model automatically after GPU selection.

For CPU rollback, set `backend: inprocess` and `device: cpu`, then restart the
agent through your usual procedure. No database migration or data conversion is
needed. The optional environment may remain installed.

## Validation still required on the Jetson

Run the acoustic regression dataset through direct GPU inference and the worker.
Compare labels, intervals and confidence scores with CPU results. Check the
longest supported clips, worker recovery during native inference and the host
memory-pressure stop. Run a longer soak that includes peak station activity
and scheduled transcodes.
