import ssl
import unittest
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sender.simulator import configure_connection, apply_public_profile, validate_topic_prefix
from sender.actuator import Actuator


class MqttConfigurationTests(unittest.TestCase):
    def test_public_profile_drops_private_credentials_and_enables_tls(self):
        args = SimpleNamespace(username='private-account', tls=False)
        apply_public_profile(args)
        self.assertIsNone(args.username)
        self.assertTrue(args.tls)
        self.assertEqual(args.broker_host, 'broker.emqx.io')
        self.assertEqual(args.broker_port, 8883)
        self.assertTrue(args.topic_prefix.startswith('gridsense/team3/'))

    def test_topic_prefix_rejects_wildcards(self):
        for prefix in ('', '/ev', 'ev/', 'ev/#', 'ev/+', 'ev\x00'):
            with self.assertRaises(ValueError):
                validate_topic_prefix(prefix)

    def test_actuator_uses_matching_custom_topics_and_ignores_other_runs(self):
        station = Mock(vehicles=[], chargers=[])
        station.accept.return_value = True
        client = Mock()
        actuator = Actuator(station, 'our-run', threading.Lock(), 'unique/demo')
        actuator.on_connect(client, None, None, 0, None)
        client.subscribe.assert_called_once_with('unique/demo/actuator', qos=1)
        command = {'run_id':'someone-else', 'sequence':1, 'sensor_timestamp':time.time()}
        actuator.on_message(client, None, SimpleNamespace(payload=json.dumps(command)))
        client.publish.assert_not_called()
        station.accept.assert_not_called()
        command['run_id'] = 'our-run'
        actuator.on_message(client, None, SimpleNamespace(payload=json.dumps(command)))
        self.assertEqual(client.publish.call_args.args[0], 'unique/demo/ack')
        self.assertTrue(json.loads(client.publish.call_args.args[1])['accepted'])

    def test_cloud_auth_uses_verified_tls(self):
        client = Mock()
        args = SimpleNamespace(tls=True, ca_cert=None, username='sensor')
        with patch.dict('os.environ', {'MQTT_PASSWORD': 'test-only'}):
            configure_connection(client, args)
        context = client.tls_set_context.call_args.args[0]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        client.username_pw_set.assert_called_once_with('sensor', 'test-only')

    def test_credentials_cannot_be_sent_without_tls(self):
        client = Mock()
        with self.assertRaises(ValueError):
            configure_connection(client, SimpleNamespace(tls=False, ca_cert=None, username='sensor'))
        client.username_pw_set.assert_not_called()

    def test_local_anonymous_demo_still_supported(self):
        client = Mock()
        configure_connection(client, SimpleNamespace(tls=False, ca_cert=None, username=None))
        client.username_pw_set.assert_not_called()
        client.tls_set_context.assert_not_called()
