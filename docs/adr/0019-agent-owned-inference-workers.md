# ADR 0019: Agent-owned inference workers

**Status:** Implemented for PANNs on the feature branch. Capacity and
deployment policy remain open.

**Date:** 2026-11-14

## Context

The tested Jetson GPU runtime uses Python 3.8 and NVIDIA Torch. Orpheus agents
use Python 3.9. Audio-events must preserve the detection stream it owns under
[ADR 0012](0012-agents-own-their-detection-stream.md) and resolve settings via
[ADR 0018](0018-distributed-backplane-and-config-service.md). A deployment can
change its microphone count, run audio and video models together, or move
agents to another host.

## Decision

The audio-events agent can run PANNs in an opt-in local child process. The agent
subscribes to motion events, admits and decodes clips, post-processes scores,
and publishes and persists detections. The child loads the model once and
exchanges arrays and results with its parent. The shared `orpheus-inference`
library handles the process and pipe protocol. Each agent can select its own
runtime and configure its own policy. The in-process backend remains available.

| Architecture | Benefit | Cost and when to consider it |
|---|---|---|
| Agent-owned child with a shared library | Preserves agent ownership and isolates incompatible runtimes and worker crashes. An agent restarts its own model. | Each model has its own process and memory footprint. Independent workers have no shared admission or fairness policy. This is the PANNs implementation. |
| Host-level admission across agent-owned workers | Coordinates model loads or inference capacity across audio and video while agents retain their workers and streams. | Requires a shared view of capacity, priority, and recovery. Consider when measurements show independent workers miss deadlines or repeatedly shed load under contention. |
| Shared inference service | Can share model residency when several agents need the same model and can schedule across callers. | Adds a service failure domain and ties callers to its supported runtimes. Moving different models into one service does not itself reduce their memory usage. |
| Run workloads on different hosts | Separates memory and compute budgets while retaining the existing agent and event-bus boundaries. | Adds hardware and requires access to each agent's inputs, including clip files. See [distributed deployment](../designs/distributed-deployment.md). |

## Queue capacity and detection stream

One PANNs subprocess runs one inference at a time across the microphones
feeding that audio-events agent. The agent queues clip references and decodes
one clip at a time. Microphone count and queue capacity are independent.
The agent publishes and persists `audio.classified` with its existing lineage.
The correlator owns temporal correlation, including whether a detection
enriches a previously emitted entity.

An earlier revision applied a three-second cutoff after recording end. That
cutoff hurt coverage and was unrelated to the correlator's inactivity timer.
The default now has no age cutoff. A deployment can explicitly set
`clip_ttl_seconds` if it wants to trade coverage for bounded age. The
request timeout independently bounds an exchange with the subprocess, and
the storage sweep owns recording retention.

| Pending slots | Effect |
|---:|---|
| 0 | One active clip. Every arrival while that slot is occupied is refused. |
| 2 (default) | One active plus two waiting. The `e83e2eb` trial refused a clip in each of two four-channel bursts. |
| 3 | One active plus three waiting. Can hold a burst from four microphones when the queue starts empty. At the trial's roughly 0.8 seconds per clip, a batch of four takes about 3.2 seconds of serial processing. |
| N − 1 for N sources | Holds one simultaneous clip per source from an empty queue. At the same illustrative rate, batches of eight and twenty take about 6.4 and 16 seconds. |

Deeper queues absorb brief bursts and increase how long a detection can
take. They cannot keep up if demand persistently exceeds throughput. Size
the queue using workload measurements and the deployment's latency and
coverage needs. If serial processing cannot meet those needs, measure
batching or concurrent inference on the same hardware before adding model
processes, which would have separate model allocations.

The `e83e2eb` trial could turn clip expiry during inference into a worker
restart. `f8ca37b` separates any configured cutoff from the hard exchange
timeout. A hung exchange still causes recovery. The rolling restart budget
permits new starts as earlier attempts age out.

## Memory and deployment

Use host `MemAvailable` for the start gate and running watchdog on the tested
Jetson. CPU and GPU share physical RAM. The prototype measured a 4,702 MiB
drop from start to ready while its cgroup registered only 1,734 MiB. The
prototype chose a 3,800 MiB stop line. The branch's 8,704 MiB start default
leaves 202 MiB above that stop line plus the measured startup drop. These
measurements do not establish universal minimums.

The live run reached 4,078 MiB during sequential midnight encodes, 278 MiB
above the configured floor. GPU inference continued without restarts or
new rejections during that watch. One detection reached both NATS and SQLite
with the same ID. The run did not exercise overlapping encodes or a competing
video inference model. A worker's host memory checks are not reservations.
Two workers can see the same headroom and start together. Once GPU inference
has been selected, recovery does not load a second CPU model under pressure.

Resolve PANNs limits through `audio_events.gpu_worker` and pass them to the
parent checks and child watchdog. Both budgets are positive and the start
gate exceeds the running floor. The isolated experiment uses the budgets
from its resolved configuration. The shared library takes memory budgets
from each caller, so a future inference agent can choose policy for its own
model and deployment. At the host level, budget for the sum of measured
resident model and peak workload demands, including simultaneous cold starts.
The earlier trial does not establish the required headroom for a different
mix of models or input sources.

On the next candidate revision, measure overload and expiry separately,
recording-to-publication age, worker reloads, and minimum available memory
under representative simultaneous audio and video load. Test representative
and maximum clip lengths, bursts at the deployment's channel count, and
recovery through a real memory-pressure stop. The
[operator guide](../operator-manual/panns-gpu.md) describes setup, isolated
comparison and CPU rollback.
