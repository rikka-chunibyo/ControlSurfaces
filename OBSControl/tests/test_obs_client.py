import base64
import hashlib
import unittest

from obscontrol.obs_client import ObsClient


class ObsClientTests(unittest.TestCase):
    def test_authentication_response_matches_obs_protocol(self):
        result = ObsClient._authentication_response("password", "salt", "challenge")
        secret = base64.b64encode(hashlib.sha256(b"passwordsalt").digest())
        expected = base64.b64encode(hashlib.sha256(secret + b"challenge").digest()).decode()
        self.assertEqual(result, expected)
