"""NATS EventBus backend ([REFACTOR] Event Bus Evolution — the control plane).

A faithful drop-in for the MQTT ``EventBus``: implements the same sync ABC
(publish/subscribe/unsubscribe/connect/disconnect/is_connected) over NATS, so an
agent runs on the new plane unchanged once ``event_bus.backend: nats`` is set.
This is the comms-plane-first step (see docs/designs/actor-model-and-control-plane.md);
durable streams + KV + request-reply (the event-sourcing/KV unlocks), MQTT
retained-message parity, and KV-TTL presence are layered on via JetStream (below).

Threading model (the load-bearing part):
- nats.py is asyncio-only; the EventBus ABC is sync. So this owns a private
  asyncio loop on a daemon thread and marshals each sync call onto it
  (``run_coroutine_threadsafe``).
- Inbound messages are decoded ON the loop thread but the user callback runs on a
  SEPARATE dedicated dispatch thread (an ordered queue). This is deliberate: an
  Orpheus consumer callback routinely blocks (SQLite writes, model inference), and
  running it inline on the I/O loop would stall publishes, keepalive and reconnect
  for the whole bus. The dispatch thread preserves per-bus ordering while keeping
  the loop free. (This is stricter isolation than paho, which only shields the
  publish path from a blocking on_message.)
- subscribe-before-connect is supported (like the MQTT backend): subscriptions are
  buffered and flushed on connect. publish/unsubscribe before connect (or after
  disconnect) are best-effort no-ops with a warning, matching MQTT semantics.

MQTT and NATS use different topic grammars; translation is explicit: ``/`` -> ``.``,
``+`` -> ``*`` (single token), ``#`` -> ``>`` (tail). Subjects carry JSON-encoded
dicts, identical payload shape to the MQTT backend.

``nats-py`` is a core dependency (NATS is the default backend); it's imported
lazily only to keep this module's import acyclic and off the mqtt fallback path.

MQTT-parity surfaces restored via JetStream:
- ``retain=True`` — core NATS has no retained messages, so a retained publish is
  ALSO mirrored into a JetStream KV "last value" bucket keyed by subject; a late
  subscriber is replayed the current value on subscribe (MQTT retained-message
  parity). Best-effort: a retain-store failure never fails the live publish.
  Parity is "eventually-consistent, last-writer-wins": the replay is enqueued just
  AFTER the live subscription registers (a message racing in during subscribe may
  arrive before the replayed value), it is redelivered on each (re)subscribe, an
  empty payload does NOT clear the value (use a tombstone), and a wildcard replay
  over a very large retain bucket is bounded by the op-timeout. Fine for the
  current "latest state" consumers (GPS location, weather); revisit if a consumer
  needs strict retained-first ordering.
- LWT / presence — NATS has no broker-side last-will; instead an agent refreshes a
  KV-TTL key each heartbeat (see ``orpheus_common.actor.Presence``). A kill -9'd
  agent's key ages out within the ttl, so it drops from ``kv_list`` and watchers
  see it go offline — queryable, unlike a broker-side will.

DEFERRED (honest gap on this backend today):
- ``qos`` — no NATS analogue here; ignored (one-time warning). At-least-once comes
  with JetStream durable consumers.
"""

from __future__ import annotations

import asyncio
import json
import queue
import re
import threading
from collections import namedtuple
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Awaitable, Callable, Dict, Optional

from orpheus_common.event_bus import EventBus, EventCallback
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_CONNECT_TIMEOUT = 10.0
_DEFAULT_OP_TIMEOUT = 5.0
_DEFAULT_RECONNECT_WAIT = 2.0  # nats.py default; also the cold-broker retry cadence
_DISPATCH_SHUTDOWN = object()  # sentinel that stops the dispatch worker
_UNSET = object()  # _submit timeout sentinel (distinguishes "default" from "None = wait forever")
_SUB_PENDING = object()  # a broker subscribe is in flight on the loop (not yet a handle)

# Headroom for connect()'s ready-wait over the per-attempt connect deadline, so
# the bounded attempt is what unwinds a cold-broker connect rather than the
# outer wait cutting the worker off before it can go non-fatal.
_CONNECT_UNWIND_GRACE = 5.0
# Backpressure bound on the dispatch queue (paho had TCP backpressure; an unbounded
# queue would grow without bound on the Jetson when a callback is slower than a
# high-rate topic). Full ⇒ drop-oldest with a rate-limited warning (see _dispatch_enqueue).
_DISPATCH_QUEUE_MAXSIZE = 10_000
_DISPATCH_DROP_WARN_EVERY = 1_000  # warn on the 1st drop, then every Nth

# KV bucket holding the last retained value per subject (MQTT retained-message
# parity). Keyed by the concrete NATS subject (valid KV key — no wildcards).
_RETAIN_BUCKET = "orpheus_retain"


def _subject_matches(pattern: str, subject: str) -> bool:
    """NATS subject-filter match: ``*`` matches one token, ``>`` matches one-or-more
    trailing tokens. ``subject`` is concrete (no wildcards). Used to replay only the
    retained keys a new subscription actually covers."""
    p = pattern.split(".")
    s = subject.split(".")
    for i, tok in enumerate(p):
        if tok == ">":
            return i < len(s)  # ``>`` requires at least one remaining token
        if i >= len(s) or (tok != "*" and tok != s[i]):
            return False
    return len(p) == len(s)


_JsErrors = namedtuple("_JsErrors", "not_found no_keys timeout api")


def _jserr() -> _JsErrors:
    """Lazily import the nats error types the JetStream surfaces branch on.

    Kept lazy (not a module-level import) so importing this module never requires
    nats-py — the same property the rest of the file preserves for the mqtt path.
    Re-import is a cheap ``sys.modules`` lookup. ``not_found`` is the base of
    Bucket/Key/Deleted-not-found; ``timeout`` (``nats.errors.TimeoutError``) is
    the base of ``FetchTimeoutError`` (so a drained pull-fetch is caught by it)."""
    from nats.errors import TimeoutError as NatsTimeoutError
    from nats.js.errors import APIError, NoKeysError, NotFoundError

    return _JsErrors(NotFoundError, NoKeysError, NatsTimeoutError, APIError)


def mqtt_to_nats_subject(topic: str) -> str:
    """Translate an MQTT topic/filter to a NATS subject/filter.

    ``/`` -> ``.``; single-level ``+`` -> ``*``; multi-level tail ``#`` -> ``>``.
    Assumes topic levels contain no literal ``.`` and ``#`` is only at the tail —
    true for every Orpheus topic; a level like ``v1.2`` would mis-route.
    """
    return topic.replace("/", ".").replace("+", "*").replace("#", ">")


def nats_to_mqtt_topic(subject: str) -> str:
    """Translate a delivered NATS subject back to MQTT topic form (``.`` -> ``/``).
    Delivered subjects are concrete (no wildcards), so only the separator differs.
    """
    return subject.replace(".", "/")


# A durable-stream topic level: lowercase alphanumerics + ``_``/``-`` only. NO dots
# (the subject<->topic map is lossy on dots) and NO wildcards (a concrete published
# subject). See docs/designs/event-sourcing-determinism-contract.md §4.2.
_DOTFREE_LEVEL = re.compile(r"^[a-z0-9_-]+$")


def _require_dotfree_topic(topic: str) -> None:
    """Fail loud if ``topic`` has a level that would not round-trip mqtt->nats->mqtt
    (a dot, a wildcard, or other punctuation). Guards every durable-stream publish so
    a non-bijective level can never enter the append-only log."""
    for level in topic.split("/"):
        if not _DOTFREE_LEVEL.match(level):
            raise ValueError(
                f"durable-stream topic level {level!r} in {topic!r} must match "
                "[a-z0-9_-]+ (no dots, no wildcards): the subject<->topic map is not "
                "bijective, so a dotted level would corrupt the append-only log"
            )


class NatsBus(EventBus):
    """EventBus over NATS, with the JetStream surfaces (request-reply, KV, durable
    streams) and MQTT-parity retain/presence layered on (see module docstring)."""

    def __init__(
        self,
        url: str,
        *,
        client_id: Optional[str] = None,
        will_topic: Optional[str] = None,
        will_payload: Optional[dict[str, Any]] = None,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
        op_timeout: float = _DEFAULT_OP_TIMEOUT,
        connect_required: bool = True,
        max_reconnect_attempts: int = -1,
        reconnect_time_wait: float = _DEFAULT_RECONNECT_WAIT,
        connect_coro_factory: Optional[Callable[[], Awaitable[Any]]] = None,
    ) -> None:
        self._url = url
        self._client_id = client_id or "orpheus-nats"
        # No broker-side LWT on NATS; offline-detection is the KV-TTL Presence helper
        # (orpheus_common.actor.Presence). Kept for create_event_bus signature parity.
        self._will_topic = will_topic
        self._will_payload = will_payload
        self._connect_timeout = connect_timeout
        self._op_timeout = op_timeout
        # connect_required=True (default) keeps today's behavior: a cold broker at
        # connect() raises. False = come up "disconnected" and attach in the
        # background when the broker appears (a remote broker can't be a systemd
        # dependency — ADR 0018). Reconnect kwargs harden steady-state: -1 =
        # retry forever (an edge agent should never give up on its broker).
        self._connect_required = connect_required
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_time_wait = reconnect_time_wait
        self._retry_task: Any = None  # background cold-broker reconnect (non-fatal)
        # The CURRENT connect worker's abort flag, set by _teardown_thread before
        # it stops the loop: it tells a _run still inside its initial connect that
        # connect() has disowned it, so neither the non-fatal retry branch nor the
        # success path may keep the loop alive (a zombie loop would race a later
        # connect() for self._nc and enqueue into a dispatch queue nobody drains).
        #
        # PER-WORKER, not per-bus. _teardown_thread joins with a bounded timeout
        # and tolerates the join failing, so a disowned worker can still be inside
        # its connect when a retry starts a new one. A shared flag that connect()
        # resets would un-abort it — it would read "not aborted" when its connect
        # finally resolves and attach as exactly the zombie this exists to prevent.
        self._connect_abort: Optional[threading.Event] = None
        # Injectable for tests: an async callable returning a connected nats client.
        self._connect_coro_factory = connect_coro_factory or self._default_connect
        self._nc: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        # subject-filter -> {"callbacks": [EventCallback, ...], "handle": sub | None}.
        # ONE broker subscription per subject fans out to every registered callback
        # (MQTTClient parity — a repeat subscribe() must never leak a second live,
        # unmanageable broker subscription). Survives disconnect (handles reset to
        # None) so a reconnect re-subscribes.
        self._subs: Dict[str, Dict[str, Any]] = {}
        # Ordered, off-loop callback delivery (keeps a blocking callback off the
        # I/O loop). Worker pulls (callback, topic, payload) tuples. Bounded so a
        # slow callback under a high-rate topic degrades by dropping (loudly)
        # instead of growing memory without bound.
        self._dispatch_q: queue.Queue = queue.Queue(maxsize=_DISPATCH_QUEUE_MAXSIZE)
        self._dispatch_dropped = 0
        self._dispatch_thread: Optional[threading.Thread] = None
        self._warned_qos = False
        # JetStream KV bucket handles, cached (mutated only on the loop thread).
        self._kv_buckets: Dict[str, Any] = {}
        # Background kv_watch tasks, cancelled on disconnect.
        self._watch_tasks: list = []
        # Re-applies subscriptions the broker never accepted. A registration can
        # fail (op timeout) or land while the connection is momentarily gone, and
        # nats-py cannot restore what it was never told about — so without this
        # sweep the bus reports a subscription it does not have and the consumer
        # goes quietly deaf.
        self._sub_watchdog_task: Optional[Any] = None
        # Subjects already warned about as un-registered, so a persistently
        # refused one warns once rather than on every sweep.
        self._sub_warned: set = set()

    # --- lifecycle ---------------------------------------------------------- #

    def connect(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self._will_topic is not None:
            logger.warning(
                "nats backend: no broker-side LWT; use orpheus_common.actor.Presence "
                "(KV-TTL heartbeat) for offline-detection on this backend",
                client_id=self._client_id,
            )
        self._ready.clear()
        # This worker's own abort flag. Never reset a previous worker's.
        aborted = threading.Event()
        self._connect_abort = aborted
        startup_error: Dict[str, BaseException] = {}

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            if aborted.is_set():
                loop.close()
                return
            self._loop = loop
            # Anything the factory hands over, even if our await is unwound
            # before we see it (an abort's loop.stop can land in between).
            created: list = []
            try:
                # Into a LOCAL: an aborted worker must not publish its connection
                # over one a later connect() already owns.
                nc = loop.run_until_complete(self._connect_with_deadline(created))
            except BaseException as exc:
                # Never leak a live connection nobody holds a reference to.
                for orphan in created:
                    try:
                        loop.run_until_complete(orphan.close())
                    except Exception:
                        pass
                if aborted.is_set():
                    # connect() timed out waiting and disowned this thread; the
                    # loop.stop it fired is what unwound us here. Exit without
                    # the non-fatal retry — a retry on a disowned loop would
                    # attach later as a zombie connection. Touch NO instance
                    # state (not even _ready): _teardown_thread already cleared
                    # it, and a newer worker may own it by now.
                    loop.close()
                    return
                if self._connect_required:  # surface to connect(); leave NO stale state
                    startup_error["e"] = exc
                    self._loop = None
                    self._nc = None
                    self._ready.set()
                    loop.close()
                    return
                # Non-fatal: come up disconnected and retry attaching in the
                # background (the localhost connect_required=True path is untouched).
                logger.warning(
                    "NATS broker unreachable; starting disconnected and retrying",
                    error=str(exc),
                    client_id=self._client_id,
                )
                self._nc = None
                self._retry_task = loop.create_task(self._retry_connect())
                self._ready.set()
                loop.run_forever()
                loop.close()
                return
            if aborted.is_set():
                # Connect finally succeeded, but only after connect() gave up
                # and disowned the thread: close the fresh connection instead
                # of running a loop nobody owns — and leave the instance's
                # _nc/_loop/_ready alone, since a later connect() may own them.
                if nc is not None:
                    try:
                        loop.run_until_complete(nc.close())
                    except Exception:
                        pass
                loop.close()
                return
            self._nc = nc
            self._ready.set()
            loop.run_forever()
            loop.close()

        self._thread = threading.Thread(
            target=_run, name=f"natsbus-{self._client_id}", daemon=True
        )
        self._thread.start()
        # Backstop only. The attempt itself is bounded by the same deadline inside
        # _connect_with_deadline, so a cold broker unwinds THERE — which is what
        # lets connect_required=False take its non-fatal branch instead of being
        # cut short here. The grace period keeps this from racing that unwind;
        # reaching it means the worker is wedged somewhere else entirely.
        if not self._ready.wait(timeout=self._connect_timeout + _CONNECT_UNWIND_GRACE):
            # Unstick the worker (loop.stop makes run_until_complete raise ->
            # _run's except tears down), join it, and clear ALL state so a later
            # connect() can retry cleanly instead of no-op'ing on a leaked thread.
            self._teardown_thread()
            raise ConnectionError(f"NATS connect timed out after {self._connect_timeout}s")
        if "e" in startup_error:
            self._teardown_thread()
            raise startup_error["e"]
        self._start_dispatch()
        # Sweep for subscriptions the broker never accepted. Runs in both the
        # connected and cold-broker cases: it is a no-op with nothing pending,
        # and it is the only path that retries a registration that failed while
        # connected.
        try:
            self._submit(self._start_sub_watchdog())
        except Exception as e:
            logger.debug("Suppressed NATS subscription-watchdog start error", error=str(e))
        # Flush subscriptions registered before connect (MQTT-parity) once we're
        # actually connected; in non-fatal cold-broker mode the retry loop flushes
        # them when it attaches, so guard on is_connected to avoid a no-op churn.
        if self.is_connected:
            for subject in list(self._subs):
                self._do_subscribe(subject)
            logger.info("Connected to NATS", url=self._url, client_id=self._client_id)

    def _server_list(self) -> list:
        """Comma-split the url into a NATS server list for failover, e.g.
        ``"nats://a:4222,nats://b:4222"``. nats.py tries them in order."""
        return [s.strip() for s in self._url.split(",") if s.strip()]

    async def _default_connect(self) -> Any:
        import nats  # lazy (keeps module import acyclic); nats-py is a core dep

        async def _err(e: Exception) -> None:
            logger.warning("NATS error", error=str(e), client_id=self._client_id)

        async def _disconnected() -> None:
            logger.warning("NATS disconnected", client_id=self._client_id)

        async def _reconnected() -> None:
            logger.info("NATS reconnected", client_id=self._client_id)
            # nats-py restores the subscriptions it registered; anything it never
            # accepted is invisible to it and would stay dead here.
            try:
                await self._flush_subscriptions("reconnect")
            except Exception as e:
                logger.warning(
                    "Failed to re-apply subscriptions after reconnect",
                    error=str(e),
                    client_id=self._client_id,
                )

        # creds/tls ride this seam: a caller needing auth injects its own
        # connect_coro_factory (or, later, create_event_bus passes them through).
        return await nats.connect(
            servers=self._server_list(),
            name=self._client_id,
            error_cb=_err,
            disconnected_cb=_disconnected,
            reconnected_cb=_reconnected,
            allow_reconnect=True,
            max_reconnect_attempts=self._max_reconnect_attempts,
            reconnect_time_wait=self._reconnect_time_wait,
        )

    async def _connect_with_deadline(self, created: Optional[list] = None) -> Any:
        """Attempt one connection, bounded by ``connect_timeout``.

        nats-py does NOT fail fast on a cold broker: with ``allow_reconnect`` it
        sits in its own retry loop and ``nats.connect`` simply never returns. An
        unbounded await there wedges this worker, so ``connect_required=False``
        would never reach its non-fatal branch and the background retry loop
        would block forever on its first attempt. Bounding each attempt is what
        makes both of those paths actually run against a real broker.

        ``created`` collects a connection the moment the factory hands one over,
        so a caller whose await is unwound afterwards (an abort's ``loop.stop``
        landing between the two) can still close it instead of leaking a live
        socket. Raises ConnectionError (not asyncio.TimeoutError) so every caller
        sees one exception type for "could not reach the broker".
        """

        async def _attempt() -> Any:
            nc = await self._connect_coro_factory()
            if created is not None and nc is not None:
                created.append(nc)
            return nc

        try:
            return await asyncio.wait_for(_attempt(), timeout=self._connect_timeout)
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"NATS connect timed out after {self._connect_timeout}s"
            ) from None

    async def _flush_subscriptions(self, reason: str) -> int:
        """Register every subscription the broker does not have yet, ON the loop.

        The single place subscriptions are (re)applied. ``handle is None`` means
        the entry is recorded locally but was never accepted by a broker — a
        subscribe issued before the connection existed, one whose registration
        failed, or one that raced a disconnect. Returns how many were restored,
        and says so: a silent restore is indistinguishable from never having
        been subscribed, which is what let a blind consumer run for hours.
        """
        pending = [s for s, e in self._subs.items() if e.get("handle") is None]
        if not pending:
            return 0
        for subject in pending:
            await self._subscribe_on_loop(subject)
        restored = [
            s
            for s in pending
            if self._subs.get(s, {}).get("handle") not in (None, _SUB_PENDING)
        ]
        if restored:
            self._sub_warned.difference_update(restored)
            logger.info(
                "NATS subscriptions applied",
                reason=reason,
                count=len(restored),
                subjects=sorted(restored),
                client_id=self._client_id,
            )
        still_pending = [s for s in pending if s not in restored]
        # Once per subject per outage, not once per sweep: a subject the broker
        # keeps refusing would otherwise warn every interval forever, and a
        # service logging without bound is how this box filled its disk before.
        unwarned = [s for s in still_pending if s not in self._sub_warned]
        if unwarned:
            self._sub_warned.update(unwarned)
            logger.warning(
                "NATS subscriptions still not registered; the bus is connected but "
                "will not deliver these subjects until they apply",
                reason=reason,
                subjects=sorted(unwarned),
                client_id=self._client_id,
            )
        return len(restored)

    async def _start_sub_watchdog(self) -> None:
        """Start the sweep task ON the loop (so the task is owned by this loop)."""
        if self._sub_watchdog_task is None:
            self._sub_watchdog_task = asyncio.ensure_future(self._sub_watchdog())

    async def _sub_watchdog(self) -> None:
        """Periodically re-apply subscriptions the broker never accepted.

        nats-py restores the subscriptions it knows about across its own
        reconnects; this covers the ones it was never told about, which no other
        path retries once the initial flush is done.
        """
        # Floored: reconnect_time_wait is caller-supplied and a 0 would spin.
        interval = max(self._reconnect_time_wait * 5, 0.05)
        try:
            while True:
                await asyncio.sleep(interval)
                if self._nc is None:
                    continue
                try:
                    await self._flush_subscriptions("watchdog")
                except Exception as e:  # never let the watchdog kill itself
                    logger.debug("Suppressed NATS subscription sweep error", error=str(e))
        except asyncio.CancelledError:
            return

    def subscription_status(self) -> dict[str, Any]:
        """What this bus is actually subscribed to, versus what it was asked for.

        ``pending`` being non-empty while ``connected`` is true is the shape of a
        consumer that believes it is listening and is not — surface it rather
        than serving stale data as if it were live.
        """
        subscribed = sorted(
            s for s, e in self._subs.items() if e.get("handle") not in (None, _SUB_PENDING)
        )
        pending = sorted(
            s for s, e in self._subs.items() if e.get("handle") in (None, _SUB_PENDING)
        )
        return {
            "connected": self.is_connected,
            "subscribed": subscribed,
            "pending": pending,
            "requested": len(self._subs),
        }

    async def _retry_connect(self) -> None:
        """Background initial-connect retry for connect_required=False: keep
        trying until the broker appears, then attach + flush buffered subs. Runs
        ON the loop thread, so it subscribes directly (no _submit bridge)."""
        try:
            while self._nc is None:
                await asyncio.sleep(self._reconnect_time_wait)
                try:
                    # Bounded: an unbounded attempt against a cold broker never
                    # returns, so the retry loop would wedge on iteration one.
                    nc = await self._connect_with_deadline()
                except Exception as exc:
                    # Keep waiting, but leave a (debug-level) trail so a
                    # permanently-cold broker / misconfig isn't silently invisible.
                    logger.debug(
                        "NATS still unreachable; will retry",
                        error=str(exc),
                        client_id=self._client_id,
                    )
                    continue  # broker still cold — keep waiting
                self._nc = nc
                await self._flush_subscriptions("cold-broker retry")
                logger.info(
                    "Connected to NATS (after retry)",
                    url=self._url,
                    client_id=self._client_id,
                )
                return
        except asyncio.CancelledError:
            return  # disconnect() cancelled us; nothing to clean up

    async def _teardown_on_loop(self) -> None:
        """Drain/close the connection + stop background tasks, ON the loop thread.

        Order matters: stop the cold-broker retry task and await it FIRST, so it
        can't publish ``self._nc`` after we read it — then read ``self._nc`` here
        (on the loop, after the retry is settled) rather than on the caller
        thread, which is what closes the disconnect-vs-attach leak window."""
        task = self._retry_task
        self._retry_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except BaseException:
                pass  # CancelledError (expected) or any unwind error — ignore
        watchdog = self._sub_watchdog_task
        self._sub_watchdog_task = None
        if watchdog is not None:
            watchdog.cancel()
            try:
                await watchdog
            except BaseException:
                pass
        # Stop kv_watch consumers (each owns push-consumer JSI tasks).
        if self._watch_tasks:
            watchers = self._watch_tasks
            self._watch_tasks = []
            for wtask, watcher in watchers:
                wtask.cancel()
                try:
                    await watcher.stop()
                except Exception:
                    pass
        # Now self._nc is stable: drain + close whatever connection exists.
        # close() lives in a finally so a drain failure (or cancellation) can
        # never leave the socket and its JetStream tasks alive on the loop.
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception as e:  # data may be lost on a drain failure
                logger.warning("NATS drain failed during shutdown", error=str(e))
            finally:
                try:
                    await self._nc.close()
                except Exception as e:
                    logger.debug("Suppressed NATS close error", error=str(e))

    def _teardown_thread(self) -> None:
        """Stop + join the bus loop thread and clear state. Used on a failed or
        timed-out connect so a later connect() retries clean (no leaked thread)."""
        # Flag first, then stop: whichever point _run has reached, it checks
        # the flag before keeping the loop alive, so a thread we fail to join
        # below still winds itself down instead of becoming a zombie bus. The
        # flag belongs to THIS worker and is never cleared again, so a retry
        # started before it winds down cannot un-abort it.
        if self._connect_abort is not None:
            self._connect_abort.set()
        self._connect_abort = None
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass  # loop already closed (the raise-path closed it in _run)
        if self._thread is not None:
            self._thread.join(timeout=self._op_timeout)
            if self._thread.is_alive():
                logger.warning(
                    "NATS connect worker still alive after abort; it will "
                    "self-terminate when the pending connect resolves",
                    client_id=self._client_id,
                )
        self._thread = None
        self._loop = None
        self._nc = None

    def _start_dispatch(self) -> None:
        if self._dispatch_thread is not None and self._dispatch_thread.is_alive():
            return
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, name=f"natsbus-dispatch-{self._client_id}", daemon=True
        )
        self._dispatch_thread.start()

    def _dispatch_loop(self) -> None:
        while True:
            item = self._dispatch_q.get()
            if item is _DISPATCH_SHUTDOWN:
                return
            callback, topic, payload = item
            try:
                callback(topic, payload)
            except Exception:
                logger.exception("NATS subscriber callback failed", topic=topic)

    def disconnect(self) -> None:
        # Stop the dispatch worker first so no callback fires mid-teardown.
        if self._dispatch_thread is not None:
            self._dispatch_q.put(_DISPATCH_SHUTDOWN)
            self._dispatch_thread.join(timeout=self._op_timeout)
            self._dispatch_thread = None
        # Tear down all connection state ON the loop thread in one coroutine:
        # stop the cold-broker retry task FIRST and await it (so a just-attaching
        # retry can't publish self._nc after we've decided to drain/close), then
        # stop kv_watch consumers, then drain + close. Making the drain/close
        # decision on the loop (not the caller thread) closes the
        # disconnect-vs-attach connection-leak window.
        if self._loop is not None:
            try:
                # The budget must outlive nats-py's drain (default 30s): the
                # default op timeout would cancel the teardown coroutine
                # mid-drain and the connection would never be closed.
                self._submit(self._teardown_on_loop(), timeout=max(self._op_timeout, 32.0))
            except Exception as e:
                logger.debug("Suppressed NATS teardown error", error=str(e))
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=self._op_timeout)
            if self._thread.is_alive():
                logger.warning(
                    "NATS bus thread did not exit cleanly; loop may be wedged",
                    client_id=self._client_id,
                )
        self._thread = None
        self._loop = None
        self._nc = None
        self._retry_task = None
        self._ready.clear()
        # Drop cached KV bucket handles — they're bound to the now-closed connection;
        # a later connect() re-derives them against the fresh client (else retain /
        # presence / kv_* would operate on a dead JetStream context).
        self._kv_buckets.clear()
        # Keep the callbacks, drop the (now-dead) handles so a reconnect re-subscribes.
        for entry in self._subs.values():
            entry["handle"] = None

    @property
    def is_connected(self) -> bool:
        return bool(
            self._loop is not None
            and self._nc is not None
            and getattr(self._nc, "is_connected", False)
        )

    # --- pub/sub ------------------------------------------------------------ #

    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: Optional[int] = None,
        retain: bool = False,
    ) -> None:
        if not self.is_connected:
            logger.warning("Cannot publish: NATS not connected", topic=topic)
            return
        if qos is not None and not self._warned_qos:
            logger.warning(
                "nats backend: qos ignored (at-least-once arrives with JetStream)",
                topic=topic,
            )
            self._warned_qos = True
        subject = mqtt_to_nats_subject(topic)
        data = json.dumps(payload).encode("utf-8")
        try:
            self._submit(self._nc.publish(subject, data))
        except Exception as e:  # best-effort, like MQTT — never raise out of publish
            logger.warning("NATS publish failed", topic=topic, error=str(e))
            return
        if retain:
            # Retained-message parity: mirror the value into a KV "last value"
            # bucket keyed by subject so a late subscriber gets it on subscribe.
            # Best-effort — a retain-store failure must not fail the live publish.
            try:
                self.kv_put(_RETAIN_BUCKET, subject, payload)
            except Exception as e:
                logger.warning("NATS retain store failed", topic=topic, error=str(e))

    def subscribe(self, topic_pattern: str, callback: EventCallback) -> None:
        subject = mqtt_to_nats_subject(topic_pattern)
        # Register first (buffered); flush now if connected, else at connect().
        # A repeat subscribe to the same pattern APPENDS to the callback list
        # (MQTTClient parity) — replacing the entry would orphan the old entry's
        # live broker subscription: unreachable by unsubscribe(), delivering to
        # the stale callback forever, and a second broker sub double-delivering.
        entry = self._subs.get(subject)
        if entry is not None:
            entry["callbacks"].append(callback)
            handle = entry.get("handle")
            if handle is not None and handle is not _SUB_PENDING:
                # Already live: replay retained values to just the NEW callback
                # (a pending/future subscribe replays to the whole list itself).
                try:
                    self._submit(self._retained_replay_coro(subject, [callback]))
                except Exception as e:
                    logger.debug("Suppressed NATS retained-replay error", error=str(e))
            return
        self._subs[subject] = {"callbacks": [callback], "handle": None}
        if self.is_connected:
            self._do_subscribe(subject)

    def _make_handler(self, subject: str) -> Callable[[Any], Awaitable[None]]:
        """Build the on-loop nats message handler: decode once, then fan out to the
        subject's CURRENT callback list via the dispatch thread (never run the
        maybe-blocking user callbacks on the loop). Looking the list up per message
        (not closing over it) keeps callbacks added after the broker subscription
        live without a second subscription."""

        async def _handler(msg: Any) -> None:
            try:
                topic = nats_to_mqtt_topic(msg.subject)
                payload = json.loads(msg.data.decode("utf-8"))
            except Exception:
                logger.exception("NATS message decode failed", subject=getattr(msg, "subject", "?"))
                return
            entry = self._subs.get(subject)
            if entry is None:  # unsubscribed while the message was in flight
                return
            for callback in list(entry["callbacks"]):
                self._dispatch_enqueue((callback, topic, payload))

        return _handler

    def _dispatch_enqueue(self, item: Any) -> None:
        """Enqueue for the dispatch thread with an explicit full-queue policy:
        drop-OLDEST (keep the freshest state) with a rate-limited warning, never
        block the I/O loop. The shutdown sentinel is never dropped."""
        while True:
            try:
                self._dispatch_q.put_nowait(item)
                return
            except queue.Full:
                pass
            try:
                dropped = self._dispatch_q.get_nowait()
            except queue.Empty:
                continue  # dispatch thread drained it between put and get; retry
            if dropped is _DISPATCH_SHUTDOWN:
                # Shutting down: keep the sentinel (the dispatch thread's stop
                # signal must never be lost) and drop the NEW item instead.
                self._dispatch_q.put(dropped)
                self._count_dispatch_drop()
                return
            self._count_dispatch_drop()

    def _count_dispatch_drop(self) -> None:
        self._dispatch_dropped += 1
        if (
            self._dispatch_dropped == 1
            or self._dispatch_dropped % _DISPATCH_DROP_WARN_EVERY == 0
        ):
            logger.warning(
                "dispatch queue full; dropping oldest message (callback slower than "
                "the topic rate)",
                dropped_total=self._dispatch_dropped,
                maxsize=self._dispatch_q.maxsize,
                client_id=self._client_id,
            )

    def dispatch_stats(self) -> dict[str, int]:
        """Dispatch backpressure counters (additive observability hook for
        Diagnostics): current queue depth + total messages dropped on overflow."""
        return {"queue_depth": self._dispatch_q.qsize(), "dropped": self._dispatch_dropped}

    def _do_subscribe(self, subject: str) -> None:
        """Subscribe from a sync caller (bridges onto the loop via _submit, where
        the handle-is-None check runs — atomic with the cold-broker retry flush,
        which also subscribes on the loop, so the two can't double-subscribe)."""
        try:
            self._submit(self._subscribe_on_loop(subject))
        except Exception as e:
            logger.warning("NATS subscribe failed", subject=subject, error=str(e))

    async def _subscribe_on_loop(self, subject: str) -> None:
        """Subscribe ON the loop thread (both the sync bridge and the cold-broker
        retry path land here, so the check-then-subscribe is single-threaded).
        ``_SUB_PENDING`` marks the in-flight await so a concurrent flush can't
        start a second broker subscription for the same subject."""
        entry = self._subs.get(subject)
        if entry is None or entry.get("handle") is not None or self._nc is None:
            return
        entry["handle"] = _SUB_PENDING
        try:
            handler = self._make_handler(subject)
            sub = await self._nc.subscribe(subject, cb=handler)
        except Exception as e:
            if entry.get("handle") is _SUB_PENDING:
                entry["handle"] = None  # let a later flush retry
            logger.warning("NATS subscribe failed", subject=subject, error=str(e))
            return
        if self._subs.get(subject) is not entry:
            # unsubscribed (or re-registered) while the subscribe was in flight —
            # don't leak a live broker subscription nothing can reach.
            try:
                await sub.unsubscribe()
            except Exception as e:
                logger.debug("Suppressed NATS unsubscribe error", error=str(e))
            return
        entry["handle"] = sub
        try:
            await self._retained_replay_coro(subject, list(entry["callbacks"]))
        except Exception as e:
            logger.debug("Suppressed NATS retained-replay error", error=str(e))

    async def _retained_replay_coro(
        self, subject: str, callbacks: list[EventCallback]
    ) -> None:
        """Replay the last retained value of every subject matching ``subject``
        (a concrete subject or a filter) into each of ``callbacks``, via the
        dispatch queue (same delivery path as a live message). No-op if nothing
        is retained."""
        errs = _jserr()
        try:
            handle = await self._kv_handle(_RETAIN_BUCKET, create=False)
            keys = await handle.keys()
        except (errs.not_found, errs.no_keys):
            return  # nothing retained yet
        for key in keys:
            if not _subject_matches(subject, key):
                continue
            try:
                entry = await handle.get(key)
            except (errs.not_found, errs.no_keys):
                continue
            if entry is None or entry.value is None:
                continue
            try:
                payload = json.loads(entry.value.decode("utf-8"))
            except Exception:
                logger.warning("retained value decode failed; skipping", key=key)
                continue
            for callback in callbacks:
                self._dispatch_enqueue((callback, nats_to_mqtt_topic(key), payload))

    def unsubscribe(self, topic_pattern: str) -> None:
        """Drop ALL callbacks for the pattern and the single broker subscription
        (MQTTClient parity). An in-flight (pending) subscribe cleans up after
        itself when it lands and finds its entry gone."""
        subject = mqtt_to_nats_subject(topic_pattern)
        entry = self._subs.pop(subject, None)
        if entry is None or self._loop is None:
            return
        handle = entry.get("handle")
        if handle is None or handle is _SUB_PENDING:
            return
        try:
            self._submit(handle.unsubscribe())
        except Exception as e:
            logger.debug("Suppressed NATS unsubscribe error", error=str(e))

    # --- bridge ------------------------------------------------------------- #

    def _submit(self, coro: Awaitable[Any], *, timeout: Optional[float] = _UNSET) -> Any:
        """Run an async nats op on the bus loop from a sync caller and wait.
        Cancels the coro on timeout so a hung op doesn't leak onto the loop.
        ``timeout=None`` waits indefinitely (e.g. a long stream replay)."""
        loop = self._loop
        if loop is None:
            raise ConnectionError("NatsBus is not connected")
        eff = self._op_timeout if timeout is _UNSET else timeout
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=eff)
        except FuturesTimeout:
            future.cancel()
            raise

    # --- JetStream surfaces (ADR 0017): request-reply, KV, durable streams --- #

    def _require_attached(self) -> None:
        """Raise ``ConnectionError`` when the broker is not (yet) attached.

        In non-fatal connect mode the bus comes up with ``self._nc = None``
        until the background retry attaches. Without this guard the JetStream
        surfaces would surface that state as ``AttributeError`` — which
        feature-detection (``supported()``) must read as "no such surface",
        permanently disabling presence/KV consumers over a mere boot-order
        blip. ``ConnectionError`` keeps "transport down" distinguishable
        from "backend can't do this".
        """
        if self._nc is None:
            raise ConnectionError("NatsBus is not attached to a broker yet")

    def request(self, topic: str, payload: dict[str, Any], timeout: Optional[float] = None) -> dict:
        self._require_attached()
        subject = mqtt_to_nats_subject(topic)
        data = json.dumps(payload).encode("utf-8")
        # `is None` not `or`: a caller-supplied 0 means "fail fast", not "default".
        eff = self._op_timeout if timeout is None else timeout

        async def _op() -> dict:
            # No responder -> NoRespondersError; no reply in time -> TimeoutError.
            # Both propagate as clean typed nats errors to the caller.
            msg = await self._nc.request(subject, data, timeout=eff)
            return json.loads(msg.data.decode("utf-8"))

        # Outer wall-clock outlives the inner request deadline (+1s) so NATS
        # raises its own timeout rather than _submit cancelling the coro first;
        # otherwise any request(timeout > op_timeout) would die at op_timeout.
        return self._submit(_op(), timeout=eff + 1.0)

    async def _kv_handle(
        self, bucket: str, *, create: bool = False, ttl: Optional[float] = None
    ) -> Any:
        errs = _jserr()
        handle = self._kv_buckets.get(bucket)
        if handle is not None:
            return handle
        js = self._nc.jetstream()
        try:
            handle = await js.key_value(bucket)
            # NATS KV ttl is bucket-wide and fixed at create. A ttl passed for a
            # bucket that already exists is silently a no-op on the wire, so make
            # it observable rather than a presence-expiry footgun: compare the
            # bucket's ACTUAL ttl and warn loudly only on divergence — a writer
            # refreshing slower than the real window flaps offline every beat.
            if ttl is not None:
                await self._warn_kv_ttl_divergence(handle, bucket, ttl)
        except errs.not_found:
            if not create:
                raise
            from nats.js.api import KeyValueConfig

            cfg = KeyValueConfig(bucket=bucket, ttl=ttl) if ttl else KeyValueConfig(bucket=bucket)
            handle = await js.create_key_value(config=cfg)
        self._kv_buckets[bucket] = handle
        return handle

    async def _warn_kv_ttl_divergence(self, handle: Any, bucket: str, ttl: float) -> None:
        """Warn (once per bucket per connection — callers cache the handle) when an
        existing bucket's REAL ttl differs from the one this client requested. The
        requested ttl is a wire no-op on an existing bucket, so a writer whose
        refresh cadence assumes the requested window but exceeds the actual one
        (e.g. a slow-tick agent joining a bucket a fast-tick agent created) ages
        out between its own beats and flaps offline. Best-effort: a status()
        failure falls back to the generic "ttl ignored" warning."""
        actual: Any = None
        try:
            status = await handle.status()
            actual = getattr(status, "ttl", None)
        except Exception:
            actual = None
        if isinstance(actual, (int, float)) and actual > 0:
            if abs(float(actual) - float(ttl)) < 1e-3:
                return  # bucket window matches the request — nothing to warn about
            logger.warning(
                "kv ttl ignored: bucket already exists with a DIFFERENT bucket-wide "
                "ttl; keys this client writes expire on the bucket's window, not the "
                "requested one (a writer refreshing slower than the bucket ttl will "
                "flap offline; recreate the bucket to change the window)",
                bucket=bucket,
                requested_ttl=ttl,
                bucket_ttl=float(actual),
                client_id=self._client_id,
            )
            return
        logger.warning(
            "kv ttl ignored: bucket already exists (ttl applies only when "
            "this call creates the bucket)",
            bucket=bucket,
            client_id=self._client_id,
        )

    def kv_get(self, bucket: str, key: str) -> Optional[dict]:
        self._require_attached()
        async def _op() -> Optional[dict]:
            errs = _jserr()
            try:
                handle = await self._kv_handle(bucket, create=False)
                entry = await handle.get(key)
            except (errs.not_found, errs.no_keys):
                return None  # bucket/key genuinely absent -> "not set"
            # A disconnect / decode / broker error is NOT "absent": let it raise
            # so a caller can't mistake an outage for an unset config value.
            if entry is None or entry.value is None:
                return None
            return json.loads(entry.value.decode("utf-8"))

        return self._submit(_op())

    def kv_put(self, bucket: str, key: str, value: dict, ttl: Optional[float] = None) -> int:
        self._require_attached()
        async def _op() -> int:
            handle = await self._kv_handle(bucket, create=True, ttl=ttl)
            return await handle.put(key, json.dumps(value).encode("utf-8"))

        return self._submit(_op())

    def kv_delete(self, bucket: str, key: str) -> None:
        self._require_attached()
        async def _op() -> None:
            errs = _jserr()
            try:
                handle = await self._kv_handle(bucket, create=False)
            except errs.not_found:
                return  # nothing to delete; don't create the bucket as a side effect
            await handle.delete(key)

        self._submit(_op())

    def kv_watch(
        self, bucket: str, key_pattern: str, callback: EventCallback, *, create: bool = True
    ) -> bool:
        """Returns True when a watch actually attached; False when the bucket is
        absent and ``create=False`` — a no-op return treated as success left
        consumers marked 'started' with no watch running, so the caller's
        snapshot/retry floor must see the difference and keep retrying."""
        self._require_attached()

        async def _start() -> bool:
            errs = _jserr()
            try:
                handle = await self._kv_handle(bucket, create=create)
            except errs.not_found:
                # create=False + absent bucket: a read-only consumer must NOT create
                # it (it would set the wrong bucket-wide TTL). No-op; the caller's
                # snapshot floor + re-establish loop attaches once a writer creates it.
                logger.info(
                    "kv_watch: bucket absent and create=False; watch not started",
                    bucket=bucket,
                    client_id=self._client_id,
                )
                return False
            watcher = await handle.watch(key_pattern)

            async def _loop() -> None:
                # Isolate the watch iterator: if it dies (consumer dropped, JS
                # error), log it instead of a silent "exception never retrieved"
                # — a dead presence/hot-reload watcher must not vanish quietly.
                try:
                    async for entry in watcher:
                        if entry is None:  # "all current values delivered" marker
                            continue
                        op = getattr(entry, "operation", None)
                        if op in ("DEL", "PURGE") or entry.value is None:
                            payload: Optional[dict] = None
                        else:
                            try:
                                payload = json.loads(entry.value.decode("utf-8"))
                            except Exception:
                                logger.warning(
                                    "kv_watch entry decode failed; skipping",
                                    bucket=bucket,
                                    key=entry.key,
                                    client_id=self._client_id,
                                )
                                continue
                        # Deliver off the I/O loop, like subscribe().
                        self._dispatch_enqueue((callback, entry.key, payload))
                except asyncio.CancelledError:
                    raise  # normal teardown via disconnect()
                except Exception as exc:
                    logger.warning(
                        "kv_watch loop ended on error; watch stopped",
                        bucket=bucket,
                        key_pattern=key_pattern,
                        error=str(exc),
                        client_id=self._client_id,
                    )

            # Track (consume-task, watcher) so disconnect can stop BOTH — the
            # watcher owns push-consumer JSI background tasks of its own.
            self._watch_tasks.append((asyncio.ensure_future(_loop()), watcher))
            return True

        return bool(self._submit(_start()))

    def kv_list(self, bucket: str) -> dict[str, dict]:
        self._require_attached()
        async def _op() -> dict[str, dict]:
            errs = _jserr()
            try:
                handle = await self._kv_handle(bucket, create=False)
                keys = await handle.keys()
            except (errs.not_found, errs.no_keys):
                return {}  # bucket absent or empty -> nobody present
            out: dict[str, dict] = {}
            for key in keys:
                try:
                    entry = await handle.get(key)
                except (errs.not_found, errs.no_keys):
                    continue  # key deleted/expired between keys() and get() -> skip
                if entry is None or entry.value is None:
                    continue
                try:
                    out[key] = json.loads(entry.value.decode("utf-8"))
                except Exception:
                    # One corrupt value must not sink the whole snapshot (presence
                    # offline-detection has to degrade, not fail). Skip + log.
                    logger.warning("kv_list value decode failed; skipping", bucket=bucket, key=key)
            return out

        return self._submit(_op())

    def stream_ensure(
        self,
        stream: str,
        subjects: list[str],
        *,
        max_age: Optional[float] = None,
        max_bytes: Optional[int] = None,
        discard: Optional[str] = None,
    ) -> None:
        self._require_attached()
        async def _op() -> None:
            errs = _jserr()
            js = self._nc.jetstream()
            subs = [mqtt_to_nats_subject(s) for s in subjects]
            # Bounded retention (event-sourcing determinism contract §4.4): a domain
            # shadow stream MUST cap max_age + max_bytes well under the account-level
            # max_file_store (shared with KV), with discard=old, so it never pins the
            # account and reverts cleanly by ageing out. All optional + additive.
            kwargs: dict[str, Any] = {}
            if max_age is not None:
                kwargs["max_age"] = max_age  # nats-py: seconds
            if max_bytes is not None:
                kwargs["max_bytes"] = max_bytes
            if discard is not None:
                from nats.js.api import DiscardPolicy

                kwargs["discard"] = DiscardPolicy(discard)  # "old" | "new"
            try:
                await js.add_stream(name=stream, subjects=subs, **kwargs)
            except errs.api as exc:
                # 10058 = stream name already in use. Same subjects -> nats-py
                # returns the existing stream (no error); we only land here when
                # it exists (idempotent) or the config diverges. Diverging config
                # NEVER applies (the existing stream wins), so surface it at
                # WARNING with both configs — a changed event_sourcing retention
                # that silently never takes effect must be visible. Re-raise
                # anything else (JetStream disabled, connection error) instead of
                # masking it.
                if getattr(exc, "err_code", None) == 10058:
                    await self._log_stream_divergence(js, stream, subs, kwargs)
                else:
                    logger.warning(
                        "stream_ensure failed",
                        stream=stream,
                        error=str(exc),
                        client_id=self._client_id,
                    )
                    raise

        self._submit(_op())

    async def _log_stream_divergence(
        self, js: Any, stream: str, subjects: list[str], requested: dict[str, Any]
    ) -> None:
        """After a 10058 (stream exists), fetch the live config and compare the
        fields the caller requested. Identical ⇒ debug (idempotent re-ensure);
        diverging ⇒ WARNING naming both sides, because the requested config is
        silently ignored until the stream is recreated. Best-effort: an info
        fetch failure degrades to the old debug line."""
        try:
            cfg = (await js.stream_info(stream)).config
        except Exception:
            logger.debug("stream already exists", stream=stream, client_id=self._client_id)
            return
        diverged: dict[str, Any] = {}
        if set(getattr(cfg, "subjects", None) or []) != set(subjects):
            diverged["subjects"] = {"existing": list(cfg.subjects or []), "requested": subjects}
        for field in ("max_age", "max_bytes", "discard"):
            if field in requested and getattr(cfg, field, None) != requested[field]:
                diverged[field] = {
                    "existing": getattr(cfg, field, None),
                    "requested": requested[field],
                }
        if diverged:
            logger.warning(
                "stream config diverges from the existing stream; the requested "
                "config does NOT apply (recreate the stream to change it)",
                stream=stream,
                diverged=diverged,
                client_id=self._client_id,
            )
        else:
            logger.debug(
                "stream already exists (config matches)",
                stream=stream,
                client_id=self._client_id,
            )

    def stream_publish(
        self,
        subject: str,
        payload: dict[str, Any],
        *,
        msg_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._require_attached()
        # Determinism contract §4.2: a durable-stream subject must be dot-free +
        # wildcard-free (the subject<->topic map is NOT bijective). Fail loud so a
        # dotted level can never silently enter the append-only log + corrupt rebuild.
        _require_dotfree_topic(subject)
        subj = mqtt_to_nats_subject(subject)
        data = json.dumps(payload).encode("utf-8")
        # §4.1: Nats-Msg-Id drives JetStream's dedup window, so a publish whose ack
        # is lost on an edge reconnect is idempotent on retry (matching the DB's
        # event_id UNIQUE) and stream/DB counts stay comparable for reconciliation.
        headers = {"Nats-Msg-Id": msg_id} if msg_id else None

        async def _op() -> None:
            js = self._nc.jetstream()
            await js.publish(subj, data, headers=headers)

        # ``timeout`` caps the wall-clock wait for the JetStream ack (None = the
        # bus op default). A hot-path caller (the event-sourcing shadow) passes a
        # short budget so a broker brownout can't stall it for op_timeout per call.
        if timeout is None:
            self._submit(_op())
        else:
            self._submit(_op(), timeout=timeout)

    def stream_replay(
        self, stream: str, callback: EventCallback, *, subject: Optional[str] = None
    ) -> int:
        self._require_attached()
        # One-shot drain of current history. For a clean snapshot, call before
        # the stream takes live writes (event-source rebuild at startup); a
        # concurrent publisher's messages may be included.
        #
        # The callback MAY block (SQLite writes are the expected consumer) and MAY
        # call back into this bus: it runs on an executor thread, NEVER inline on
        # the I/O loop — inline it would deadlock any nested bus call (_submit
        # waits on the very loop the callback is holding) and stall keepalive/
        # reconnect for the whole drain. Awaiting each executor call preserves
        # strict in-order delivery and the "count returned after all delivered"
        # contract.
        async def _op() -> int:
            errs = _jserr()
            loop = asyncio.get_running_loop()
            js = self._nc.jetstream()
            subj = mqtt_to_nats_subject(subject) if subject else ">"
            psub = await js.pull_subscribe(subj, stream=stream)
            count = 0
            empty_timeouts = 0
            try:
                while True:
                    try:
                        msgs = await psub.fetch(batch=128, timeout=1.0)
                    except errs.timeout:
                        # nats-py raises the SAME timeout for "stream drained"
                        # and "broker didn't answer" (brownout mid-replay), so
                        # a timeout alone must not conclude the drain: verify
                        # against the consumer's pending count and only treat
                        # persistent silence WITH pending messages as an error
                        # — a partial rebuild must NOT be reported complete.
                        info = await psub.consumer_info()
                        pending = getattr(info, "num_pending", 0) or 0
                        if pending == 0:
                            break  # drained — nothing left for this consumer
                        empty_timeouts += 1
                        if empty_timeouts >= 3:
                            raise ConnectionError(
                                f"stream_replay stalled with {pending} messages "
                                f"still pending on {stream!r} — broker silent, "
                                "refusing to report a partial replay as complete"
                            )
                        continue
                    # Any other error (connection/JS) propagates: a partial
                    # rebuild must NOT be reported as a complete one.
                    empty_timeouts = 0
                    if not msgs:
                        break
                    for m in msgs:
                        topic = nats_to_mqtt_topic(m.subject)
                        try:
                            payload: Optional[dict] = json.loads(m.data.decode("utf-8"))
                        except Exception:
                            logger.warning(
                                "stream_replay entry decode failed; delivering None",
                                subject=m.subject,
                                client_id=self._client_id,
                            )
                            payload = None
                        await loop.run_in_executor(None, callback, topic, payload)
                        await m.ack()
                    count += len(msgs)
            finally:
                # Tear down the ephemeral consumer + its JSI background tasks.
                try:
                    await psub.unsubscribe()
                except Exception:
                    pass
            return count

        # No timeout: a rebuild may legitimately take a while.
        return self._submit(_op(), timeout=None)
