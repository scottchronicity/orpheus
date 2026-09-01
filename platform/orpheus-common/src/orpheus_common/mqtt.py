"""
MQTT client wrapper for Orpheus services.

Provides auto-reconnect, JSON serialization, topic pattern matching,
and integration with Orpheus logging.
"""

import json
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from orpheus_common.event_bus import EventBus
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


class MQTTClient(EventBus):
    """
    Robust MQTT client wrapper with automatic reconnection and JSON support.

    Features:
    - Auto-reconnect with exponential backoff
    - JSON serialization/deserialization
    - Topic pattern matching for callbacks
    - QoS configuration
    - Last will and testament for agent health

    Example:
        >>> client = MQTTClient(
        ...     broker_host="localhost",
        ...     client_id="my-agent",
        ...     topics=["orpheus/sensors/#"]
        ... )
        >>>
        >>> @client.on_message("orpheus/sensors/audio/#")
        ... def handle_audio(topic, payload):
        ...     print(f"Audio: {payload}")
        >>>
        >>> client.publish("orpheus/status/my-agent", {"status": "running"})
        >>> client.connect()
    """

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        client_id: Optional[str] = None,
        topics: Optional[list[str]] = None,
        qos: int = 1,
        keepalive: int = 60,
        will_topic: Optional[str] = None,
        will_payload: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize MQTT client.

        Args:
            broker_host: MQTT broker hostname
            broker_port: MQTT broker port
            client_id: Unique client identifier (auto-generated if None)
            topics: List of topics to subscribe to on connect
            qos: Quality of Service (0, 1, or 2)
            keepalive: Keepalive interval in seconds
            will_topic: Topic for last will message
            will_payload: Payload for last will message (JSON dict)
        """
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id or f"orpheus-{int(time.time())}"
        self.topics = topics or []
        self.qos = qos
        self.keepalive = keepalive

        # Callback registry: {topic_pattern: [callback_functions]}
        self._callbacks: dict[str, list[Callable]] = {}

        # Connection state
        self._connected = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

        # Create paho MQTT client
        if hasattr(mqtt, "CallbackAPIVersion"):
            self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        else:
            self._client = mqtt.Client(client_id=self.client_id)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Configure last will and testament
        if will_topic and will_payload:
            self._client.will_set(
                will_topic, payload=json.dumps(will_payload), qos=self.qos, retain=True
            )

        logger.info(
            "MQTT client initialized",
            client_id=self.client_id,
            broker_host=self.broker_host,
            broker_port=self.broker_port,
        )

    def connect(self) -> None:
        """
        Connect to MQTT broker.

        Blocks until connected or raises exception.
        Auto-reconnect is handled automatically after initial connection.
        """
        try:
            logger.info(
                "Connecting to MQTT broker",
                broker_host=self.broker_host,
                broker_port=self.broker_port,
            )

            # Enable automatic reconnection
            self._client.reconnect_delay_set(min_delay=1, max_delay=60)

            self._client.connect(self.broker_host, self.broker_port, self.keepalive)
            self._client.loop_start()

            # Wait for connection
            timeout = 10
            start = time.time()
            while not self._connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            if not self._connected:
                raise TimeoutError("Failed to connect to MQTT broker within timeout")

            logger.info("Connected to MQTT broker successfully")

        except Exception as e:
            logger.error("Failed to connect to MQTT broker", error=str(e))
            raise

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        logger.info("Disconnecting from MQTT broker", client_id=self.client_id)
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    def publish(
        self, topic: str, payload: Any, qos: Optional[int] = None, retain: bool = False
    ) -> None:
        """
        Publish message to topic.

        Automatically serializes dictionaries to JSON.

        Args:
            topic: Topic to publish to
            payload: Message payload (dict, str, bytes, etc.)
            qos: Quality of Service (uses client default if None)
            retain: Retain message on broker

        Example:
            >>> client.publish("orpheus/detection/audio", {
            ...     "type": "detection",
            ...     "species": "amecro",
            ...     "confidence": 0.95
            ... })
        """
        if not self._connected:
            logger.warning("Cannot publish: not connected", topic=topic)
            return

        # Serialize payload
        original_payload = payload
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        elif not isinstance(payload, (str, bytes)):
            payload = str(payload)

        # Publish
        qos = qos if qos is not None else self.qos
        try:
            result = self._client.publish(topic, payload, qos=qos, retain=retain)

            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(
                    "Failed to publish message",
                    topic=topic,
                    error=mqtt.error_string(result.rc),
                )
            else:
                # Create a summary of the payload for logging
                if isinstance(original_payload, dict):
                    payload_keys = list(original_payload.keys())[:3]
                    logger.info(
                        "Published message", topic=topic, payload_keys=payload_keys, qos=qos
                    )
                else:
                    logger.info("Published message", topic=topic, qos=qos)
        except Exception:
            logger.exception("Exception while publishing", topic=topic)

    def subscribe(self, topic_pattern: str, callback: Callable) -> None:
        """
        Subscribe to topic pattern with callback function.

        Args:
            topic_pattern: MQTT topic pattern (supports # and + wildcards)
            callback: Function to call when message received (topic, payload)

        Example:
            >>> def handle_audio(topic, payload):
            ...     print(f"Received on {topic}: {payload}")
            >>> client.subscribe("orpheus/sensors/audio/#", handle_audio)
        """
        if topic_pattern not in self._callbacks:
            self._callbacks[topic_pattern] = []
        self._callbacks[topic_pattern].append(callback)
        logger.debug(
            "Registered callback for topic pattern",
            topic_pattern=topic_pattern,
            callback=callback.__name__,
        )

        # If already connected, subscribe to broker immediately
        if self._connected:
            self._client.subscribe(topic_pattern, qos=self.qos)
            logger.info("Subscribed to topic pattern", topic_pattern=topic_pattern, qos=self.qos)

    def unsubscribe(self, topic_pattern: str) -> None:
        """
        Drop all callbacks for a topic pattern and unsubscribe at the broker.

        Idempotent — unsubscribing a pattern with no registered callbacks is a
        no-op. Part of the EventBus contract.

        Args:
            topic_pattern: The same pattern that was given to ``subscribe``.
        """
        had = self._callbacks.pop(topic_pattern, None) is not None
        if self._connected:
            self._client.unsubscribe(topic_pattern)
        if had:
            logger.info("Unsubscribed from topic pattern", topic_pattern=topic_pattern)

    def on_message(self, topic_pattern: str) -> Callable:
        """
        Decorator to register message callback for topic pattern.

        Args:
            topic_pattern: MQTT topic pattern (supports # and + wildcards)

        Returns:
            Decorator function

        Example:
            >>> @client.on_message("orpheus/sensors/audio/#")
            ... def handle_audio(topic, payload):
            ...     print(f"Received on {topic}: {payload}")
        """

        def decorator(func: Callable) -> Callable:
            self.subscribe(topic_pattern, func)
            return func

        return decorator

    def _on_connect(
        self, client: mqtt.Client, userdata: Any, flags: dict, rc: int, properties: Any = None
    ) -> None:
        """Callback when connected to broker."""
        # Handle paho-mqtt v2 reason_code object which might be passed as rc
        if hasattr(rc, "value"):
            rc = rc.value

        if rc == 0:
            self._connected = True
            self._reconnect_delay = 1.0  # Reset backoff
            logger.info("MQTT connection established", client_id=self.client_id)

            # Subscribe to configured topics
            for topic in self.topics:
                client.subscribe(topic, qos=self.qos)
                logger.info("Subscribed to topic", topic=topic, qos=self.qos)

            # Subscribe to callback patterns
            for pattern in self._callbacks.keys():
                if pattern not in self.topics:
                    client.subscribe(pattern, qos=self.qos)
                    logger.info("Subscribed to pattern", pattern=pattern, qos=self.qos)
        else:
            logger.error("MQTT connection failed", code=rc, reason=mqtt.connack_string(rc))

    def _on_disconnect(
        self, client: mqtt.Client, userdata: Any, flags: Any, rc: int, properties: Any = None
    ) -> None:
        """Callback when disconnected from broker."""
        self._connected = False

        # Handle paho-mqtt v2 reason_code object
        if hasattr(rc, "value"):
            rc = rc.value

        if rc != 0:
            logger.warning("Unexpected MQTT disconnect", code=rc, reason=mqtt.error_string(rc))
            # Don't block the network thread - let paho-mqtt handle reconnection automatically
            # The loop_start() handles reconnection internally
            logger.info("Attempting automatic MQTT reconnection")

            # Exponential backoff for logging purposes
            self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
        else:
            logger.info("Clean disconnect from MQTT broker")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Callback when message received."""
        topic = msg.topic

        # Try to parse as JSON
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload

        # Log with summary
        if isinstance(payload, dict):
            payload_keys = list(payload.keys())[:3]
            logger.debug("Received message", topic=topic, payload_keys=payload_keys)
        else:
            preview = str(payload)[:50]
            logger.debug("Received message", topic=topic, preview=preview)

        # Match against registered callbacks
        for pattern, callbacks in self._callbacks.items():
            if self._topic_matches(topic, pattern):
                for callback in callbacks:
                    try:
                        callback(topic, payload)
                    except Exception as e:
                        logger.exception(
                            "Error in callback",
                            callback=callback.__name__,
                            topic=topic,
                            error=str(e),
                        )

    def _topic_matches(self, topic: str, pattern: str) -> bool:
        """
        Check if topic matches MQTT pattern.

        Supports:
        - Single-level wildcard: +
        - Multi-level wildcard: #

        Example:
            >>> self._topic_matches("orpheus/sensors/audio/1", "orpheus/sensors/#")
            True
            >>> self._topic_matches("orpheus/sensors/audio/1", "orpheus/sensors/+/1")
            True
        """
        topic_parts = topic.split("/")
        pattern_parts = pattern.split("/")

        # Multi-level wildcard at end
        if pattern_parts[-1] == "#":
            return topic_parts[: len(pattern_parts) - 1] == pattern_parts[:-1]

        # Must have same number of parts
        if len(topic_parts) != len(pattern_parts):
            return False

        # Check each part
        for t_part, p_part in zip(topic_parts, pattern_parts):
            if p_part != "+" and p_part != t_part:
                return False

        return True

    @property
    def is_connected(self) -> bool:
        """Check if client is connected to broker."""
        return self._connected


# ``MQTTBus`` is the EventBus-vocabulary name for the MQTT transport. It is the
# same class as ``MQTTClient`` (kept as the canonical name for back-compat with
# every existing import); new code can use either. See event_bus.create_event_bus.
MQTTBus = MQTTClient
