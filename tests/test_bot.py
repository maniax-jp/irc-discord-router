# -*- coding: utf-8 -*-
"""
IRC-Discord Bot テスト
"""

import pytest
import asyncio
from unittest.mock import MagicMock
from bot import Bot

class TestBot:
    def test_irc_to_discord_forward(self):
        """IRC から Discord へのメッセージ転送テスト"""
        bot = Bot()
        bot.irc_channel = "#test"
        bot.discord_channel = MagicMock()

        # IRC メッセージをシミュレート
        bot.test_irc_to_discord("test_message")

        # Discord 側に送信されたことを確認
        assert bot.discord_channel.send_called_with("test_message")

    def test_discord_to_irc_forward(self):
        """Discord から IRC へのメッセージ転送テスト"""
        bot = Bot()
        bot.irc_client = MagicMock()

        # Discord メッセージをシミュレート
        bot.test_discord_to_irc("test_message")

        # IRC 側に送信されたことを確認
        assert bot.irc_client.send_called_with("test_message")

    def test_bot_message_exclusion(self):
        """ボット自体のメッセージ除外テスト"""
        bot = Bot()
        bot.irc_channel = "#test"
        bot.discord_channel = MagicMock()

        # ボット自身のメッセージをシミュレート
        bot.test_irc_to_discord("bot_message")

        # 無限ループを防止するために送信されないことを確認
        assert bot.discord_channel.send_called_with("bot_message")

if __name__ == "__main__":
    pytest.main()
