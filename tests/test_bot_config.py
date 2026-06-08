import importlib
import os
import sys
import unittest
from unittest.mock import patch


def load_bot_config(env: dict[str, str]):
    sys.modules.pop("backend.bot.config", None)
    with (
        patch.dict(os.environ, env, clear=True),
        patch("pathlib.Path.exists", return_value=False),
    ):
        return importlib.import_module("backend.bot.config")


class BotConfigTests(unittest.TestCase):
    def test_ollama_base_url_matches_portfolio_env_name(self):
        cfg = load_bot_config(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "OLLAMA_BASE_URL": "http://ollama:11434/",
            }
        )

        self.assertEqual(cfg.OLLAMA_URL, "http://ollama:11434")

    def test_ollama_url_takes_precedence_over_base_url(self):
        cfg = load_bot_config(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "OLLAMA_URL": "http://bot-specific:11434/",
                "OLLAMA_BASE_URL": "http://portfolio-style:11434/",
            }
        )

        self.assertEqual(cfg.OLLAMA_URL, "http://bot-specific:11434")


if __name__ == "__main__":
    unittest.main()
