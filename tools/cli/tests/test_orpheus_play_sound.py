"""Tests for orpheus_play_sound CLI tool."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add tools/cli to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orpheus_play_sound import main, parse_args, play_sound


class TestParseArgs:
    """Tests for argument parsing."""

    def test_parse_args_minimal(self):
        """Test parsing with just sound_name."""
        args = parse_args(["test_tone_1"])

        assert args.sound_name == "test_tone_1"
        assert args.repeat == 1
        assert args.pause == 0.0
        assert args.broker is None
        assert args.port is None
        assert args.timeout == 5.0
        assert not args.wait
        assert args.log_level == "INFO"

    def test_parse_args_full(self):
        """Test parsing with all options."""
        args = parse_args([
            "test_beep",
            "--repeat", "3",
            "--pause", "1.5",
            "--broker", "mqtt.local",
            "--port", "1884",
            "--timeout", "10.0",
            "--wait",
            "--log-level", "DEBUG",
        ])

        assert args.sound_name == "test_beep"
        assert args.repeat == 3
        assert args.pause == 1.5
        assert args.broker == "mqtt.local"
        assert args.port == 1884
        assert args.timeout == 10.0
        assert args.wait
        assert args.log_level == "DEBUG"


class TestPlaySound:
    """Tests for play_sound function."""

    @patch('orpheus_play_sound.OrpheusConfig')
    @patch('orpheus_play_sound.MQTTClient')
    def test_play_sound_success(self, mock_mqtt_class, mock_config_class):
        """Test successful sound playback."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config_class.get_instance.return_value = mock_config

        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client

        # Simulate success response
        def mock_subscribe(topic, callback):
            # Immediately call the callback with success response
            callback(topic, {"status": "success"})

        mock_client.subscribe.side_effect = mock_subscribe

        # Call function
        result = play_sound("test_tone_1")

        # Verify
        assert result is True
        mock_client.connect.assert_called_once()
        mock_client.publish.assert_called_once()
        mock_client.disconnect.assert_called_once()

    @patch('orpheus_play_sound.OrpheusConfig')
    @patch('orpheus_play_sound.MQTTClient')
    def test_play_sound_error_response(self, mock_mqtt_class, mock_config_class):
        """Test handling of error response."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config_class.get_instance.return_value = mock_config

        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client

        # Simulate error response
        def mock_subscribe(topic, callback):
            callback(topic, {"status": "error", "error": "Sound not found"})

        mock_client.subscribe.side_effect = mock_subscribe

        # Call function
        result = play_sound("unknown_sound")

        # Verify
        assert result is False

    @patch('orpheus_play_sound.OrpheusConfig')
    @patch('orpheus_play_sound.MQTTClient')
    def test_play_sound_connection_error(self, mock_mqtt_class, mock_config_class):
        """Test handling of connection errors."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config_class.get_instance.return_value = mock_config

        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection failed")
        mock_mqtt_class.return_value = mock_client

        # Call function
        result = play_sound("test_tone_1")

        # Verify
        assert result is False

    @patch('orpheus_play_sound.OrpheusConfig')
    @patch('orpheus_play_sound.MQTTClient')
    @patch('orpheus_play_sound.time.sleep')
    def test_play_sound_timeout(self, mock_sleep, mock_mqtt_class, mock_config_class):
        """Test timeout when no response received."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config_class.get_instance.return_value = mock_config

        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client

        # Simulate no response
        mock_client.subscribe.return_value = None

        # Mock time.sleep to avoid actually waiting
        mock_sleep.return_value = None

        # Call function with short timeout
        with patch('orpheus_play_sound.time.time') as mock_time:
            # Simulate timeout - need more values for logging too
            mock_time.side_effect = [0.0, 0.0, 6.0, 7.0, 8.0, 9.0, 10.0]  # Start, loop, timeout, logging
            result = play_sound("test_tone_1", timeout=5.0)

        # Verify
        assert result is False

    @patch('orpheus_play_sound.OrpheusConfig')
    @patch('orpheus_play_sound.MQTTClient')
    @patch('orpheus_play_sound.time.sleep')
    def test_play_sound_with_wait(self, mock_sleep, mock_mqtt_class, mock_config_class):
        """Test waiting for playback completion."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config_class.get_instance.return_value = mock_config

        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client

        # Simulate success response
        def mock_subscribe(topic, callback):
            callback(topic, {"status": "success"})

        mock_client.subscribe.side_effect = mock_subscribe

        # Call function with wait
        result = play_sound(
            "test_tone_1",
            repeat_count=3,
            pause_between=1.0,
            wait_for_completion=True,
        )

        # Verify
        assert result is True
        # Should have slept for estimated duration
        assert any(call_args[0][0] >= 3.0 for call_args in mock_sleep.call_args_list)


class TestMain:
    """Tests for main function."""

    @patch('orpheus_play_sound.play_sound')
    @patch('orpheus_play_sound.setup_logging')
    def test_main_success(self, mock_setup_logging, mock_play_sound):
        """Test successful execution."""
        mock_play_sound.return_value = True

        exit_code = main(["test_tone_1"])

        assert exit_code == 0
        mock_play_sound.assert_called_once()

    @patch('orpheus_play_sound.play_sound')
    @patch('orpheus_play_sound.setup_logging')
    def test_main_failure(self, mock_setup_logging, mock_play_sound):
        """Test failure execution."""
        mock_play_sound.return_value = False

        exit_code = main(["test_tone_1"])

        assert exit_code == 1

    @patch('orpheus_play_sound.play_sound')
    @patch('orpheus_play_sound.setup_logging')
    def test_main_invalid_repeat(self, mock_setup_logging, mock_play_sound):
        """Test invalid repeat argument."""
        exit_code = main(["test_tone_1", "--repeat", "0"])

        assert exit_code == 1
        mock_play_sound.assert_not_called()

    @patch('orpheus_play_sound.play_sound')
    @patch('orpheus_play_sound.setup_logging')
    def test_main_invalid_pause(self, mock_setup_logging, mock_play_sound):
        """Test invalid pause argument."""
        exit_code = main(["test_tone_1", "--pause", "-1.0"])

        assert exit_code == 1
        mock_play_sound.assert_not_called()

    @patch('orpheus_play_sound.play_sound')
    @patch('orpheus_play_sound.setup_logging')
    def test_main_keyboard_interrupt(self, mock_setup_logging, mock_play_sound):
        """Test handling of KeyboardInterrupt."""
        mock_play_sound.side_effect = KeyboardInterrupt()

        exit_code = main(["test_tone_1"])

        assert exit_code == 130

    @patch('orpheus_play_sound.play_sound')
    @patch('orpheus_play_sound.setup_logging')
    def test_main_exception(self, mock_setup_logging, mock_play_sound):
        """Test handling of exceptions."""
        mock_play_sound.side_effect = Exception("Test error")

        exit_code = main(["test_tone_1"])

        assert exit_code == 1
