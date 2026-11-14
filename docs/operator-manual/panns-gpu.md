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
the agent environment. The standard audio-events service installer and deploy
target also install the IPC library in the service’s Python 3.9 environment.
Install the CUDA worker separately with the command below.

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
    max_pending_clips: 2
```

- `inprocess` (default) retains the existing model and `device: auto` selection
  inside Python 3.9. Set `device: cpu` for explicit CPU operation.
- `auto` selects the isolated GPU worker on Linux aarch64 when the configured
  executable exists and is executable, and host memory passes the start gate.
  This applies only to `cnn14_sed` and `device: auto` or `cuda`; `device: cpu`
  keeps execution in process. Otherwise it uses the in-process model, with CPU
  for `device: auto`, while an explicit `cuda` still requires available CUDA.
  Selection happens once at agent startup. The
  worker itself validates Python, Torch, CUDA and checkpoint during loading;
  those later failures remain visible recovery failures, not silent CPU fallback.
- `gpu_worker` requires the worker. A missing executable is a startup error;
  loading/runtime failures leave worker readiness false while supervision runs.
  The worker requires CUDA; pairing it with `device: cpu` is a configuration error.

PANNs supports `device: auto`, `cpu` or `cuda`. `mps`, indexed devices such as
`cuda:1`, and unknown names fail at configuration loading: those placements are
not implemented by this model wrapper. The agent and worker runtimes are
independent; other components do not need the worker's Python/NVIDIA stack.

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

A full queue or unavailable worker can cause a clip to be skipped before
decoding. Use the health counters and input readiness markers to distinguish
skipped clips from differences in model output. The experiment uses the
configured `clip_ttl_seconds` if you set one.
An unmatched label alone does not prove a model disagreement, and zero matched
labels is not a parity result. This is a live observation experiment, not replay.

CPU and GPU share the Jetson's physical RAM. This test adds the GPU model
while the CPU model remains resident. It uses the start gate and running floor
from the resolved experiment configuration. If the station lacks the configured
headroom, the experiment waits in `memory_blocked`.

## Budget memory and overload

The archived prototype passed 24 historical tests with bit-identical direct-GPU
results and 15.2 ms median IPC overhead. Its model load lowered host
`MemAvailable` by **4,702 MiB**, although its cgroup recorded only **1,734 MiB**.
On that cgroup-v1 station `MemoryHigh` was ineffective. Use host memory readings;
do not add RSS, allocator reservations and MemAvailable drops together.

| Setting | Default | Meaning |
|---|---:|---|
| `start_memory_mib` | 8704 | Minimum MemAvailable before starting/loading a worker. |
| `floor_memory_mib` | 3800 | Worker watchdog stop threshold. Queued work waits while the worker recovers from memory pressure. |
| `max_pending_clips` | 2 | Maximum waiting clip references in addition to one active clip. A full queue blocks the input callback until a slot opens. |
| `clip_ttl_seconds` | unset | Optional maximum age after recording ends for PANNs to classify a clip. Set a positive number of seconds to enable it. |
| `max_clip_seconds` | 40 | Maximum decoded clip duration; header checked before decoding. |
| `startup_timeout_seconds` | 60 | Model load and warm-up deadline. |
| `request_timeout_seconds` | 5 | Hard timeout for a worker request. |
| `shutdown_drain_timeout_seconds` | 60 | Maximum graceful drain wait before forced worker stop and explicit accounting for unfinished clips. |
| `restart_backoff_seconds` | 2 | Initial restart delay, increasing to 30 seconds. |
| `max_starts` | 3 | Maximum starts within `restart_window_seconds` (default 300). |

Set the budgets under `audio_events.gpu_worker` for your deployment. Specify
positive whole MiB values and set the start gate above the running floor. Use
measured memory during model load and maximum-length clips alongside the
station's other models and encodes to choose the gap. The worker checks host
memory during loading, inference and idle time and exits on pressure or an
unreadable memory source. The parent checks memory before decoding clips.

These defaults describe the tested PANNs workload, not universal hardware
minimums. A smaller measured deployment budget is valid if it is positive and
the start gate exceeds the running floor. The configured duration must fit both
32 kHz float32 audio and 527-class framewise output in the IPC's 64 MiB payload
limit (including output-frame tolerance); invalid values fail before loading.
Increasing duration also increases warm-up and peak memory. Revalidate those
measurements and the request/startup timeouts for longer recordings.

`max_concurrent_clips` is a positive integer controlling the in-process executor
(default 2); it does not change the isolated worker's serial execution. The GPU
agent keeps at most one active clip plus `max_pending_clips` waiting references
in FIFO order. When full, the event callback blocks until an execution slot
opens; the agent does not reject clips due to queue capacity. Sustained demand
above inference throughput therefore backpressures event delivery and increases
latency. See
[ADR 0019](../adr/0019-agent-owned-inference-workers.md).

The agent publishes and persists `audio.classified` detections for completed
clips using its usual thresholds and source lineage. By default it applies
no age cutoff. If you configure `clip_ttl_seconds`, its budget starts when
recording ends and includes delivery, queueing and classification. The
correlator manages its own timing. The
[storage retention policy](index.md#7-data-retention) governs recording deletion.

The request timeout bounds an exchange with the worker. A worker reload took
12–15 seconds in the prototype. Accepted clips wait through temporary worker
unavailability, then resume in FIFO order. Graceful shutdown drains active and
queued work before closing the worker, for up to
`shutdown_drain_timeout_seconds`. If that drain expires, the agent stops the
worker, cancels queued jobs and counts unfinished work under
`clips_rejected.shutdown`; shutdown logs the count. This lifecycle bound avoids
an unending service stop. Increase it if measured worker recovery takes longer.
The queue is process memory and cannot survive a host or agent crash.
The input bus and shadow stream do not provide the durable
acknowledgement/idempotency contract needed for automatic replay; see the
existing [replay contract](../designs/event-sourcing-determinism-contract.md).
An IPC or child failure before inference returns retries that same accepted
clip after worker recovery; no detection is published until inference completes.

`clips_rejected` reports deliberate TTL expiry and overlength recordings.
Non-recoverable worker or model failures update error counters and worker
health; no synthetic detection is emitted. Configuring `clip_ttl_seconds`
explicitly trades coverage for a bounded age. No age cutoff is applied by default.

This is bounded callback backpressure, not durable delivery. NATS core
subscriptions are at-most-once, and the shared NATS callback dispatch queue is
itself bounded with its existing drop-oldest overflow policy. Sustained overload
can therefore lose work before this agent receives the callback; enabling the
optional domain shadow does not turn it into a classifier work queue. Guaranteed
delivery requires a future durable `audio.motion` consumer that acknowledges
after classification persistence, with replay/idempotency and recording-retention
semantics designed together. Until then, do not claim production-grade
at-least-once classification.

The agent resolves these settings through normal YAML/KV/environment precedence;
for example `ORPHEUS_AUDIO_EVENTS__GPU_WORKER__FLOOR_MEMORY_MIB` reaches both the
parent admission checks and child watchdog. Settings take effect at startup.
Service `MemoryHigh` is a separate host-level soft limit, configurable with a
systemd drop-in; it is not a reservation or a replacement for the worker's host
memory guards, and may be ineffective on cgroup v1. Installing the optional
worker changes neither the service unit nor its drop-ins.

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
