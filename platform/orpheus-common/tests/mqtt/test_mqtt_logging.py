"""Tests for MQTT logging behavior."""

from unittest.mock import Mock, patch

from orpheus_common.mqtt import MQTTClient


class TestMQTTLogging:
    """Test that MQTT operations log correctly."""

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_init_logs_client_info(self, mock_mqtt_client_class, mock_logger):
        """Test that client initialization logs client info."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        MQTTClient(
            broker_host="test-host",
            broker_port=1234,
            client_id="test-client",
        )

        # Verify initialization was logged
        mock_logger.info.assert_called_with(
            "MQTT client initialized",
            client_id="test-client",
            broker_host="test-host",
            broker_port=1234,
        )

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_connect_logs_connection_attempt(self, mock_mqtt_client_class, mock_logger):
        """Test that connect logs the connection attempt."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="test-host", broker_port=1234)

        def simulate_connect(*args, **kwargs):
            client._on_connect(mock_client_instance, None, {}, 0, None)

        mock_client_instance.connect.side_effect = simulate_connect
        client.connect()

        # Check that connecting was logged
        # Verify at least one call has "Connecting to MQTT broker" message
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("Connecting to MQTT broker" in call for call in info_calls)

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_disconnect_logs_disconnection(self, mock_mqtt_client_class, mock_logger):
        """Test that disconnect logs the disconnection."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="test-host", client_id="test-client")
        client._connected = True
        client.disconnect()

        # Verify disconnect was logged
        mock_logger.info.assert_called_with(
            "Disconnecting from MQTT broker", client_id="test-client"
        )

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_publish_when_disconnected_logs_warning(self, mock_mqtt_client_class, mock_logger):
        """Test that publishing when disconnected logs a warning."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="test-host")
        client._connected = False

        client.publish("test/topic", {"key": "value"})

        # Verify warning was logged
        mock_logger.warning.assert_called_with("Cannot publish: not connected", topic="test/topic")

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_publish_success_logs_message(self, mock_mqtt_client_class, mock_logger):
        """Test that successful publish logs the message."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        # Create a mock result object
        mock_result = Mock()
        mock_result.rc = 0  # Success
        mock_client_instance.publish.return_value = mock_result

        client = MQTTClient(broker_host="test-host")
        client._connected = True

        client.publish("test/topic", {"key1": "value1", "key2": "value2"}, qos=1)

        # Verify publish was logged
        # Check that at least one info call mentions publishing
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("Published message" in call and "test/topic" in call for call in info_calls)

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_publish_exception_logs_error(self, mock_mqtt_client_class, mock_logger):
        """Test that publish exception logs error."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        # Make publish raise an exception
        mock_client_instance.publish.side_effect = Exception("Network error")

        client = MQTTClient(broker_host="test-host")
        client._connected = True

        client.publish("test/topic", {"key": "value"})

        # Verify exception was logged
        mock_logger.exception.assert_called()

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_subscribe_logs_subscription(self, mock_mqtt_client_class, mock_logger):
        """Test that subscribe logs the subscription."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="test-host")
        client._connected = True

        def dummy_callback(topic, payload):
            pass

        client.subscribe("test/topic/#", dummy_callback)

        # Verify subscription was logged
        mock_logger.debug.assert_called()
        mock_logger.info.assert_called_with(
            "Subscribed to topic pattern", topic_pattern="test/topic/#", qos=1
        )

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_on_message_logs_received_message(self, mock_mqtt_client_class, mock_logger):
        """Test that receiving a message logs it."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="test-host")

        # Create a mock MQTT message
        mock_msg = Mock()
        mock_msg.topic = "test/topic"
        mock_msg.payload = b'{"key": "value"}'

        # Call the internal message handler
        client._on_message(mock_client_instance, None, mock_msg)

        # Verify message receipt was logged
        debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
        assert any("Received message" in call for call in debug_calls)

    @patch("orpheus_common.mqtt.logger")
    @patch("paho.mqtt.client.Client")
    def test_callback_error_logs_exception(self, mock_mqtt_client_class, mock_logger):
        """Test that callback errors are logged."""
        mock_client_instance = Mock()
        mock_mqtt_client_class.return_value = mock_client_instance

        client = MQTTClient(broker_host="test-host")

        # Create a callback that raises an exception
        def failing_callback(topic, payload):
            raise ValueError("Callback error")

        client.subscribe("test/topic", failing_callback)

        # Create a mock MQTT message
        mock_msg = Mock()
        mock_msg.topic = "test/topic"
        mock_msg.payload = b'{"key": "value"}'

        # Call the internal message handler - should not raise
        client._on_message(mock_client_instance, None, mock_msg)

        # Verify error was logged
        exception_calls = [str(call) for call in mock_logger.exception.call_args_list]
        assert any("Error in callback" in call for call in exception_calls)
