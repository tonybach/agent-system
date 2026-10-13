import os
import unittest
from unittest import mock

from src.config import BASE_URL, MODEL_ID, Config


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = Config.from_env()
        self.assertEqual((cfg.base_url, cfg.model_id), (BASE_URL, MODEL_ID))

    def test_overrides(self):
        env = {"MADSLOOP_BASE_URL": "https://openrouter.ai/api/v1", "MADSLOOP_MODEL": "qwen/qwen3.6-35b-a3b",
               "MADSLOOP_MAX_ITERATIONS": "7", "MADSLOOP_QUIET": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        self.assertEqual(cfg.base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(cfg.model_id, "qwen/qwen3.6-35b-a3b")
        self.assertEqual(cfg.max_iterations, 7)
        self.assertTrue(cfg.quiet)


if __name__ == "__main__":
    unittest.main()
