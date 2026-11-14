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

## Queue and deadline

The PANNs worker runs one inference at a time across all microphones feeding
that agent instance. `max_pending_clips` counts waiting clip references in
addition to that one active slot. It does not allocate one slot per mic or
buffer decoded audio for every admitted clip. The default clip lifetime is
3 seconds from the end of recording, including delivery, queueing,
preprocessing and inference. Extending it can affect correlation because a
cluster may have closed when the result arrives and late enrichment defaults off.

| Pending slots | Effect |
|---:|---|
| 0 | Admit one clip at a time. Gives up burst capacity and avoids waiting behind another clip. |
| 2 (current default) | Admit up to three clips. At 0.8 seconds each, three close arrivals take about 2.4 seconds of serial processing, leaving about 0.6 seconds of a 3-second lifetime for other delays. A fourth can be refused immediately. |
| 3 | Admit up to four clips. The fourth can finish on time if arrivals are staggered or inference is fast. With simultaneous arrivals at 0.8 seconds each, four take about 3.2 seconds. A late request can occupy the worker while other clips wait. |
| N − 1 for N sources | Holds one simultaneous clip per source. At the same illustrative rate, eight simultaneous clips take 6.4 seconds and twenty take 16 seconds. Long queues can turn overload rejections into expiries. |

Two pending is a provisional default for the measured PANNs workload and
lifetime. Microphone count alone cannot size the queue. Use burst overlap,
clip lengths and end-to-end age at publication under the full station load.
If timely coverage is insufficient, evaluate a longer lifetime with the
correlator, batching or parallel inference with measured GPU and memory cost,
or distributing the workload. A shared scheduler would coordinate contention
between models. It would not make one serial model process clips faster.

The live run used `e83e2eb`. It dropped one clip in each of two four-channel
bursts. Estimated from recording and inference timestamps, an extra slot
would have been marginal on the first burst and likely useful on the second.
That revision could turn a mid-inference clip expiry into a worker restart.
`f8ca37b` separates clip expiry from the hard IPC timeout: a late result can
be discarded while the worker stays healthy. A hung exchange still causes
recovery. The restart budget is rolling and permits new starts as earlier
attempts age out. The live burst results do not validate the new timeout path.

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

**Open configuration issue.** The branch exposes the limits through
`audio_events.gpu_worker`, but the agent and worker validate against fixed
prototype values, the experiment separately clamps the start gate, and the
shared library has PANNs memory defaults. Resolve the deployment-level
values once through the existing config path and pass them through to the
checks. Review the validation rules and required headroom before changing
production policy. Keep the watchdog active.

On the next candidate revision, measure overload and expiry separately,
recording-to-publication age, worker reloads, and minimum available memory
under representative simultaneous audio and video load. Test representative
and maximum clip lengths, bursts at the deployment's channel count, and
recovery through a real memory-pressure stop. The
[operator guide](../operator-manual/panns-gpu.md) describes setup, isolated
comparison and CPU rollback.
