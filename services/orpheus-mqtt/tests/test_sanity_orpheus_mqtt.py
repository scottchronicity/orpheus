import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

import pytest

pytest.importorskip("paho.mqtt.client", reason="paho-mqtt package required")
import paho.mqtt.client as mqtt  # noqa: E402


# MQTT Broker Configuration
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TEST_TOPIC = "orpheus/test"
TIMEOUT_SECONDS = 5


@dataclass
class MQTTTestState:
    """Track state of MQTT test operations"""

    connected: bool = False
    published: bool = False
    received: bool = False
    message_content: Optional[str] = None
    error: Optional[str] = None

    def reset(self):
        """Reset all state to initial values"""
        self.connected = False
        self.published = False
        self.received = False
        self.message_content = None
        self.error = None


@pytest.fixture
def mqtt_test_state():
    """Fixture providing fresh test state for each test"""
    return MQTTTestState()


@pytest.fixture
def mqtt_client(mqtt_test_state):
    """
    Fixture providing a configured MQTT client with callbacks.
    Automatically handles connection, cleanup, and state management.
    """
    state = mqtt_test_state

    def on_connect(client, userdata, flags, rc, properties=None):
        """Callback when client connects to broker"""
        if rc == 0:
            state.connected = True
            client.subscribe(TEST_TOPIC)
        else:
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorized",
            }
            state.error = error_messages.get(rc, f"Connection failed with code {rc}")
            state.connected = False

    def on_publish(client, userdata, mid, rc=None, properties=None):
        """Callback when message is published"""
        state.published = True

    def on_message(client, userdata, msg):
        """Callback when message is received"""
        state.received = True
        state.message_content = msg.payload.decode("utf-8")

    def on_disconnect(client, userdata, flags, rc, properties=None):
        """Callback when client disconnects"""
        # Handle paho-mqtt v2 reason_code object
        if hasattr(rc, "value"):
            rc = rc.value

        if rc != 0:
            state.error = f"Unexpected disconnection (code: {rc})"

    # Create and configure client
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="orpheus-pytest-client",
        clean_session=True,
    )
    client.on_connect = on_connect
    client.on_publish = on_publish
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    yield client

    # Cleanup
    try:
        client.loop_stop()
        client.disconnect()
    except Exception:
        pass  # Client may already be disconnected


def wait_for_condition(condition_func, timeout=TIMEOUT_SECONDS, interval=0.1):
    """
    Wait for a condition function to return True.

    Args:
        condition_func: Callable that returns bool
        timeout: Maximum seconds to wait
        interval: Seconds between checks

    Returns:
        bool: True if condition met, False if timeout
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if condition_func():
            return True
        time.sleep(interval)
    return False


class TestMQTTBrokerConnection:
    """Test suite for MQTT broker connectivity"""

    def test_broker_is_reachable(self, mqtt_client, mqtt_test_state):
        """Test that the MQTT broker accepts connections"""
        try:
            mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        except ConnectionRefusedError:
            pytest.fail(
                f"Connection refused to {BROKER_HOST}:{BROKER_PORT}. "
                "Is the MQTT broker running? "
                "Check: systemctl status orpheus-mqtt.service"
            )
        except Exception as e:
            pytest.fail(f"Failed to connect to broker: {e}")

        mqtt_client.loop_start()

        # Wait for connection to establish
        connected = wait_for_condition(lambda: mqtt_test_state.connected)

        assert connected, (
            f"Failed to connect within {TIMEOUT_SECONDS} seconds. "
            f"Error: {mqtt_test_state.error or 'timeout'}"
        )
        assert mqtt_test_state.error is None, (
            f"Connection error: {mqtt_test_state.error}"
        )

    def test_publish_message(self, mqtt_client, mqtt_test_state):
        """Test that messages can be published to the broker"""
        # Connect first
        mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        mqtt_client.loop_start()

        # Wait for connection
        connected = wait_for_condition(lambda: mqtt_test_state.connected)
        assert connected, "Failed to connect to broker"

        # Publish message
        test_message = f"Test message at {datetime.now().isoformat()}"
        result = mqtt_client.publish(TEST_TOPIC, test_message, qos=1)

        try:
            result.wait_for_publish(timeout=TIMEOUT_SECONDS)
        except Exception as e:
            pytest.fail(f"Failed to publish message: {e}")

        assert mqtt_test_state.published, "Publish callback was not triggered"

    def test_subscribe_and_receive_message(self, mqtt_client, mqtt_test_state):
        """Test that messages can be subscribed to and received"""
        # Connect
        mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        mqtt_client.loop_start()

        # Wait for connection and subscription
        connected = wait_for_condition(lambda: mqtt_test_state.connected)
        assert connected, "Failed to connect to broker"

        # Allow time for subscription to complete
        time.sleep(0.5)

        # Publish a test message
        test_message = f"Subscribe test at {datetime.now().isoformat()}"
        mqtt_client.publish(TEST_TOPIC, test_message, qos=1)

        # Wait for message to be received
        received = wait_for_condition(lambda: mqtt_test_state.received)

        assert received, f"Message not received within {TIMEOUT_SECONDS} seconds"
        assert mqtt_test_state.message_content == test_message, (
            f"Message content mismatch. "
            f"Expected: {test_message}, "
            f"Received: {mqtt_test_state.message_content}"
        )

    def test_full_publish_subscribe_cycle(self, mqtt_client, mqtt_test_state):
        """Test complete publish/subscribe cycle with message verification"""
        # Connect
        mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        mqtt_client.loop_start()

        # Wait for connection
        connected = wait_for_condition(lambda: mqtt_test_state.connected)
        assert connected, "Failed to connect to broker"

        # Allow subscription to establish
        time.sleep(0.5)

        # Publish test message
        test_message = f"Full cycle test at {datetime.now().isoformat()}"
        result = mqtt_client.publish(TEST_TOPIC, test_message, qos=1)
        result.wait_for_publish()

        # Verify all operations completed successfully
        assert mqtt_test_state.connected, "Not connected to broker"
        assert mqtt_test_state.published, "Message was not published"

        # Wait for message reception
        received = wait_for_condition(lambda: mqtt_test_state.received)
        assert received, "Message was not received"
        assert mqtt_test_state.message_content == test_message, (
            "Message content mismatch"
        )
        assert mqtt_test_state.error is None, (
            f"Unexpected error: {mqtt_test_state.error}"
        )


class TestMQTTBrokerConfiguration:
    """Test suite for broker configuration and behavior"""

    def test_broker_accepts_clean_session(self, mqtt_test_state):
        """Test that broker accepts clean_session flag"""
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="orpheus-clean-test",
            clean_session=True,
        )

        def on_connect(cli, userdata, flags, rc, properties=None):
            mqtt_test_state.connected = rc == 0

        client.on_connect = on_connect

        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            client.loop_start()

            connected = wait_for_condition(lambda: mqtt_test_state.connected)
            assert connected, "Failed to connect with clean_session=True"
        finally:
            client.loop_stop()
            client.disconnect()

    def test_broker_qos_levels(self, mqtt_client, mqtt_test_state):
        """Test that broker supports different QoS levels"""
        mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        mqtt_client.loop_start()

        connected = wait_for_condition(lambda: mqtt_test_state.connected)
        assert connected, "Failed to connect to broker"

        # Test QoS 0, 1, and 2
        for qos in [0, 1, 2]:
            mqtt_test_state.published = False
            test_message = f"QoS {qos} test"

            result = mqtt_client.publish(TEST_TOPIC, test_message, qos=qos)

            if qos > 0:
                result.wait_for_publish(timeout=TIMEOUT_SECONDS)

            # For QoS 0, we don't get publish confirmation, so just verify no error
            if qos > 0:
                assert mqtt_test_state.published, f"Failed to publish with QoS {qos}"
