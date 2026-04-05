"""
Test MQTT callback signatures for paho-mqtt 2.1.0 compatibility.

This test verifies that the callback signatures in MQTTClient match
paho-mqtt 2.1.0 expectations to prevent TypeError issues.
"""

import inspect
import unittest
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt

from orpheus_common.mqtt import MQTTClient


class TestMQTTCallbackSignatures(unittest.TestCase):
    """Test that callback signatures match paho-mqtt 2.1.0."""

    def setUp(self):
        """Set up test client."""
        self.client = MQTTClient(
            broker_host="localhost",
            broker_port=1883,
            client_id="test-callback-client",
        )

    def test_on_connect_signature(self):
        """Test _on_connect has correct signature for paho-mqtt 2.1.0."""
        # Expected signature: (client, userdata, flags, rc, properties=None)
        sig = inspect.signature(self.client._on_connect)
        params = list(sig.parameters.keys())

        # Should have: self, client, userdata, flags, rc, properties
        self.assertGreaterEqual(
            len(params), 4, "on_connect should have at least 4 parameters (plus self)"
        )
        self.assertIn("client", params)
        self.assertIn("userdata", params)
        self.assertIn("flags", params)
        self.assertIn("rc", params)

    def test_on_disconnect_signature(self):
        """Test _on_disconnect has correct signature for paho-mqtt 2.1.0."""
        # Expected signature: (client, userdata, flags, rc, properties=None)
        sig = inspect.signature(self.client._on_disconnect)
        params = list(sig.parameters.keys())

        # Should have: self, client, userdata, flags, rc, properties
        self.assertGreaterEqual(
            len(params), 4, "on_disconnect should have at least 4 parameters (plus self)"
        )
        self.assertIn("client", params)
        self.assertIn("userdata", params)
        self.assertIn("flags", params)
        self.assertIn("rc", params)

    def test_on_message_signature(self):
        """Test _on_message has correct signature for paho-mqtt 2.1.0."""
        # Expected signature: (client, userdata, msg)
        sig = inspect.signature(self.client._on_message)
        params = list(sig.parameters.keys())

        # Should have: self, client, userdata, msg
        self.assertEqual(len(params), 3, "on_message should have 3 parameters (plus self)")
        self.assertIn("client", params)
        self.assertIn("userdata", params)
        self.assertIn("msg", params)

    def test_on_connect_callback_execution(self):
        """Test that _on_connect can be called with paho-mqtt 2.1.0 arguments."""
        mock_client = Mock(spec=mqtt.Client)
        userdata = None
        flags = {"session present": 0}
        rc = 0
        properties = None

        # This should not raise TypeError
        try:
            self.client._on_connect(mock_client, userdata, flags, rc, properties)
        except TypeError as e:
            self.fail(f"on_connect raised TypeError with v2.1.0 signature: {e}")

        # Verify connection state was updated
        self.assertTrue(self.client._connected)

    def test_on_disconnect_callback_execution(self):
        """Test that _on_disconnect can be called with paho-mqtt 2.1.0 arguments."""
        mock_client = Mock(spec=mqtt.Client)
        userdata = None
        flags = {}
        rc = 0
        properties = None

        # Set connected first
        self.client._connected = True

        # This should not raise TypeError
        try:
            self.client._on_disconnect(mock_client, userdata, flags, rc, properties)
        except TypeError as e:
            self.fail(f"on_disconnect raised TypeError with v2.1.0 signature: {e}")

        # Verify connection state was updated
        self.assertFalse(self.client._connected)

    def test_on_message_callback_execution(self):
        """Test that _on_message can be called with paho-mqtt 2.1.0 arguments."""
        mock_client = Mock(spec=mqtt.Client)
        userdata = None
        mock_msg = Mock(spec=mqtt.MQTTMessage)
        mock_msg.topic = "orpheus/test"
        mock_msg.payload = b'{"test": "data"}'

        # This should not raise TypeError
        try:
            self.client._on_message(mock_client, userdata, mock_msg)
        except TypeError as e:
            self.fail(f"on_message raised TypeError with v2.1.0 signature: {e}")

    @patch("paho.mqtt.client.Client")
    def test_paho_mqtt_version_check(self, mock_mqtt_client):
        """Verify paho-mqtt version is 2.1.0."""
        import paho.mqtt
        import pytest

        version = getattr(paho.mqtt, "__version__", None)
        if version:
            # Check if correct version is installed
            if not version.startswith("2."):
                pytest.skip(
                    f"paho-mqtt {version} is installed, but 2.1.0 is required. "
                    f"Run: pip install --upgrade -r requirements.txt"
                )

            # Verify it's 2.x
            self.assertTrue(version.startswith("2."))

            # Should HAVE CallbackAPIVersion (v2 feature)
            self.assertTrue(
                hasattr(mqtt, "CallbackAPIVersion"),
                "CallbackAPIVersion not found - paho-mqtt 2.x should have this. "
                "Ensure paho-mqtt==2.1.0 is installed.",
            )


class TestMQTTSubscribeMethod(unittest.TestCase):
    """Test the subscribe() method functionality."""

    def setUp(self):
        """Set up test client."""
        self.client = MQTTClient(
            broker_host="localhost",
            broker_port=1883,
            client_id="test-subscribe-client",
        )

    def test_subscribe_method_exists(self):
        """Test that subscribe() method exists."""
        self.assertTrue(hasattr(self.client, "subscribe"))
        self.assertTrue(callable(getattr(self.client, "subscribe")))

    def test_subscribe_registers_callback(self):
        """Test that subscribe() registers callback correctly."""
        callback_invoked = []

        def test_callback(topic, payload):
            callback_invoked.append((topic, payload))

        # Subscribe to topic
        self.client.subscribe("orpheus/test/#", test_callback)

        # Verify callback is registered
        self.assertIn("orpheus/test/#", self.client._callbacks)
        self.assertIn(test_callback, self.client._callbacks["orpheus/test/#"])

    def test_subscribe_multiple_callbacks_same_topic(self):
        """Test multiple callbacks can be registered to same topic."""

        def callback1(topic, payload):
            pass

        def callback2(topic, payload):
            pass

        # Subscribe both to same topic
        self.client.subscribe("orpheus/test", callback1)
        self.client.subscribe("orpheus/test", callback2)

        # Both should be registered
        self.assertEqual(len(self.client._callbacks["orpheus/test"]), 2)
        self.assertIn(callback1, self.client._callbacks["orpheus/test"])
        self.assertIn(callback2, self.client._callbacks["orpheus/test"])


if __name__ == "__main__":
    unittest.main()
