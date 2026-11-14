# Local inference infrastructure

`orpheus-inference` is a dependency-free Python 3.8+ library for one persistent
local subprocess per owning agent. It supplies the verified OGW1 pipe framing,
deadline I/O, background supervision, host-memory admission, worker-side guards
and stdout isolation. It does not depend on `orpheus-common`, numpy, CUDA or NATS.

The [architecture contract](../../docs/ARCHITECTURE.md#architecture-contract) and
[ADR 0020](../../docs/adr/0020-portable-capabilities-and-runtime-boundaries.md)
separate domain, model, hardware execution, IPC and host coordination. This
package keeps its current name and infrastructure boundary. Callers own resource
budgets and domain admission/retry decisions; exchange timeouts and recovery
never supply a recording-age cutoff. The current serial client does not impose
a platform-wide count of models, workers, accelerators or inputs.

The client requires a ready worker before accepting a request. Model reloads
never happen on a clip request path. A whole exchange is serialized, faults
kill/reap the child, and a rolling start budget bounds restart storms. The
maintenance thread polls idle children; snapshots never wait for an exchange.
The worker watches process-parent identity and input EOF rather than using Linux
PDEATHSIG, which follows the spawning thread's lifetime.

Protocol and deadline helpers derive from the verified `gpuw-ipc-prototype-20261112`
archive (`gpuw_proto.py` / `gpuw_client.py` / `gpuw_worker.py`). Production code
omits test hooks, unbounded event histories and inline retry/reload. Test workers
are separate executables. There is no multi-model registry or scheduler.

From the repository root, use `make install-inference`, `make lint-inference`,
`make test-inference` or `make coverage-inference`. These include the PANNs worker
validation tests without installing its NVIDIA runtime. Run operator setup through
the [opt-in guide](../../docs/operator-manual/panns-gpu.md).
