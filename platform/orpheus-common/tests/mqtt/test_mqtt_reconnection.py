"""
Test MQTT client reconnection behavior.

This test validates that the MQTTClient handles disconnections properly
and uses paho-mqtt's automatic reconnection features.
"""

import unittest
from unittest.mock import Mock, patch

from orpheus_common.mqtt import MQTTClient


class TestMQTTReconnection(unittest.TestCase):
    """Test reconnection handling in MQTTClient."""

    @patch("paho.mqtt.client.Client")
    def test_connect_enables_automatic_reconnection(self, mock_mqtt_client_class):
        """Test that connect() enables paho-mqtt automatic reconnection."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Simulate successful connection
        def simulate_connect(*args, **kwargs):
            client._on_connect(mock_client_instance, None, {}, 0, None)

        mock_client_instance.connect.side_effect = simulate_connect

        # Connect
        client.connect()

        # Verify reconnect_delay_set was called with correct parameters
        mock_client_instance.reconnect_delay_set.assert_called_once_with(min_delay=1, max_delay=60)

    @patch("paho.mqtt.client.Client")
    def test_disconnect_callback_does_not_block(self, mock_mqtt_client_class):
        """Test that _on_disconnect doesn't block with sleep or reconnect calls."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Set as connected first
        client._connected = True

        # Simulate unexpected disconnect (rc != 0)
        client._on_disconnect(mock_client_instance, None, {}, 1, None)

        # Verify client is marked as disconnected
        self.assertFalse(client._connected)

        # Verify reconnect() was NOT called (paho-mqtt handles this automatically)
        mock_client_instance.reconnect.assert_not_called()

    @patch("paho.mqtt.client.Client")
    def test_disconnect_callback_handles_reason_code_object(self, mock_mqtt_client_class):
        """Test that _on_disconnect handles paho-mqtt v2 reason_code objects."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Set as connected first
        client._connected = True

        # Create mock reason_code object with value attribute (paho-mqtt v2)
        mock_reason_code = Mock()
        mock_reason_code.value = 1  # Non-zero = unexpected disconnect

        # Simulate disconnect with reason_code object
        client._on_disconnect(mock_client_instance, None, {}, mock_reason_code, None)

        # Verify client is marked as disconnected
        self.assertFalse(client._connected)

    @patch("paho.mqtt.client.Client")
    def test_clean_disconnect_does_not_log_warning(self, mock_mqtt_client_class):
        """Test that clean disconnect (rc=0) doesn't log as unexpected."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Set as connected first
        client._connected = True

        # Simulate clean disconnect (rc = 0)
        with patch("orpheus_common.mqtt.logger") as mock_logger:
            client._on_disconnect(mock_client_instance, None, {}, 0, None)

            # Should log info, not warning
            mock_logger.warning.assert_not_called()
            mock_logger.info.assert_called()

        # Verify client is marked as disconnected
        self.assertFalse(client._connected)

    @patch("paho.mqtt.client.Client")
    def test_publish_handles_disconnection_gracefully(self, mock_mqtt_client_class):
        """Test that publish() handles disconnection without raising exceptions."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Set as disconnected
        client._connected = False

        # Try to publish while disconnected - should not raise exception
        with patch("orpheus_common.mqtt.logger") as mock_logger:
            client.publish("test/topic", {"message": "test"})

            # Should log warning message about not being connected
            mock_logger.warning.assert_called()

        # Verify publish was not attempted on the underlying client
        mock_client_instance.publish.assert_not_called()

    @patch("paho.mqtt.client.Client")
    def test_publish_handles_exceptions(self, mock_mqtt_client_class):
        """Test that publish() catches and logs exceptions."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Set as connected
        client._connected = True

        # Make publish raise an exception
        mock_client_instance.publish.side_effect = Exception("Network error")

        # Try to publish - should not raise exception
        with patch("orpheus_common.mqtt.logger") as mock_logger:
            client.publish("test/topic", {"message": "test"})

            # Should log exception (using logger.exception instead of logger.error with exc_info)
            mock_logger.exception.assert_called()

    @patch("paho.mqtt.client.Client")
    def test_exponential_backoff_tracking(self, mock_mqtt_client_class):
        """Test that reconnection delay increases exponentially."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Set as connected first
        client._connected = True
        initial_delay = client._reconnect_delay

        # Simulate first disconnect
        client._on_disconnect(mock_client_instance, None, {}, 1, None)
        delay_after_first = client._reconnect_delay

        # Delay should have doubled
        self.assertGreater(delay_after_first, initial_delay)

        # Set as connected again
        client._connected = True

        # Simulate second disconnect
        client._on_disconnect(mock_client_instance, None, {}, 1, None)
        delay_after_second = client._reconnect_delay

        # Delay should have doubled again
        self.assertGreater(delay_after_second, delay_after_first)

    @patch("paho.mqtt.client.Client")
    def test_reconnection_delay_capped_at_max(self, mock_mqtt_client_class):
        """Test that reconnection delay doesn't exceed maximum."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Set delay to near maximum
        client._reconnect_delay = 50.0
        client._max_reconnect_delay = 60.0
        client._connected = True

        # Simulate multiple disconnects
        for _ in range(5):
            client._on_disconnect(mock_client_instance, None, {}, 1, None)
            client._connected = True

        # Delay should not exceed max
        self.assertLessEqual(client._reconnect_delay, client._max_reconnect_delay)

    @patch("paho.mqtt.client.Client")
    def test_successful_connect_resets_backoff(self, mock_mqtt_client_class):
        """Test that successful connection resets exponential backoff."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="localhost", broker_port=1883, client_id="test-client")

        # Increase delay through failed connections
        client._reconnect_delay = 30.0
        client._connected = False

        # Simulate successful reconnection
        client._on_connect(mock_client_instance, None, {}, 0, None)

        # Delay should be reset to initial value
        self.assertEqual(client._reconnect_delay, 1.0)
        self.assertTrue(client._connected)


if __name__ == "__main__":
    unittest.main()
