"""
Test basic MQTT client functionality with mocks.

This test validates that the MQTTClient can be instantiated and
that connect/disconnect work correctly with mocked broker connections.
"""

from unittest.mock import Mock, patch

from orpheus_common.mqtt import MQTTClient


@patch("paho.mqtt.client.Client")
def test_mqttworks(mock_mqtt_client_class):
    """Test that MQTT client can connect and disconnect using mocks."""
    # Create a mock instance that will be returned by Client()
    mock_client_instance = Mock()
    mock_mqtt_client_class.return_value = mock_client_instance

    # Create our MQTTClient
    m = MQTTClient(
        broker_host="localhost", broker_port=1883, client_id="test-client", topics=["orpheus/test"]
    )

    # Call connect() which will trigger the actual connection attempt
    # We need to manually trigger the on_connect callback since we're mocking
    def simulate_connect(*args, **kwargs):
        # Simulate successful connection by calling the registered on_connect callback
        m._on_connect(mock_client_instance, None, {}, 0, None)

    # Make connect() trigger our simulation
    mock_client_instance.connect.side_effect = simulate_connect

    # Now call connect
    m.connect()

    # Verify connection was attempted
    mock_client_instance.connect.assert_called_once_with("localhost", 1883, 60)
    mock_client_instance.loop_start.assert_called_once()

    # Verify client is now connected
    assert m.is_connected, "Client should be connected after successful on_connect"

    # Verify subscribe was called for the configured topic
    mock_client_instance.subscribe.assert_called_once_with("orpheus/test", qos=1)

    # Disconnect
    m.disconnect()

    # Verify disconnect was called
    mock_client_instance.loop_stop.assert_called_once()
    mock_client_instance.disconnect.assert_called_once()
    assert not m.is_connected, "Client should not be connected after disconnect"
