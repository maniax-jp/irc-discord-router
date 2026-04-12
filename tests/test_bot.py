# -*- coding: utf-8 -*-
"""
IRC-Discord Bot テスト
"""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from bot import Bot

class TestBot:
    """
    Bot クラスの機能テスト。
    """
    @pytest.fixture
    def bot(self):
        """Bot インスタンスのフィクスチャ"""
        # Bot の初期化時に IRCClient が作成されるが、
        # テストのために mock 化したい場合はここで行う
        return Bot()

    @pytest.fixture
    def mock_discord_client(self, bot):
        """Discord クライアントのモック"""
        client = MagicMock()
        client.loop = asyncio.get_event_loop()
        client.user.id = 123456789
        bot.discord_client = client
        return client

    @pytest.fixture
    def mock_irc_connection(self, bot):
        """IRC 接続のモック"""
        connection = MagicMock()
        bot.irc_client.connection = connection
        return connection

    def test_irc_to_discord_forward(self, bot, mock_discord_client, mock_irc_connection):
        """IRC から Discord へのメッセージ転送テスト"""
        # フィクスチャが正しく注入されていることを確認
        assert mock_discord_client is not None
        # 設定のモック化
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            # Discord チャンネルのモック
            mock_channel = AsyncMock()
            bot.discord_channel_map["111"] = mock_channel

            # IRC イベントのモック
            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["Hello Discord!"]
            event.source.nick = "Alice"

            # IRCClient の Nick を設定してボット自身のメッセージにならないようにする
            bot.irc_client.nick_candidates = ["BotNick"]
            bot.irc_client.current_nick_index = 0

            # IRCClient の on_pubmsg を呼び出し
            # 実際には connection, event が渡される
            bot.irc_client.on_pubmsg(mock_irc_connection, event)

            # asyncio.run_coroutine_threadsafe が呼ばれたか確認したいが、
            # channel.send が呼ばれたかを確認するのがより直接的
            # run_coroutine_threadsafe は非同期関数をスケジュールするので、
            # ここではそのスケジュールされた関数が実行されたかを検証する必要がある
            # しかし、テスト環境では単に mock_channel.send が呼ばれたかを確認したい
            # 実際には asyncio.run_coroutine_threadsafe(channel.send(...), loop)
            # なので、mock_channel.send が呼ばれたはず
            mock_channel.send.assert_called_with("Alice: Hello Discord!")

    def test_discord_to_irc_forward(self, bot, mock_irc_connection):
        """Discord から IRC へのメッセージ転送テスト"""
        # 設定のモック化
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            # Discord メッセージのモック
            message = MagicMock()
            message.content = "Hello IRC!"
            message.author.display_name = "Bob"
            message.author.id = 987654321
            message.channel.id = "111"

            # Bot の discord_client を設定して、自分のメッセージではないことを確認させる
            bot.discord_client = MagicMock()
            bot.discord_client.user.id = 123456789

            # Bot の on_message を呼び出し (async 関数なので await するか loop で回す)
            loop = asyncio.get_event_loop()
            loop.run_until_complete(bot.on_message(message))

            # IRC 側に送信されたことを確認
            mock_irc_connection.privmsg.assert_called_with("#test-irc", "Bob: Hello IRC!")

    def test_irc_bot_message_exclusion(self, bot, mock_irc_connection):
        """IRC ボット自身のメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            mock_channel = AsyncMock()
            bot.discord_channel_map["111"] = mock_channel

            # ボット自身のメッセージをシミュレート
            bot.irc_client.nick_candidates = ["BotNick"]
            bot.irc_client.current_nick_index = 0

            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["I am a bot"]
            event.source.nick = "BotNick"

            bot.irc_client.on_pubmsg(mock_irc_connection, event)

            # 送信されないことを確認
            mock_channel.send.assert_not_called()

    def test_discord_bot_message_exclusion(self, bot, mock_irc_connection, mock_discord_client):
        """Discord ボット自身のメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            # ボット自身のメッセージをシミュレート
            message = MagicMock()
            message.content = "I am a bot"
            message.author.id = mock_discord_client.user.id
            message.channel.id = "111"

            loop = asyncio.get_event_loop()
            loop.run_until_complete(bot.on_message(message))

            # 送信されないことを確認
            mock_irc_connection.privmsg.assert_not_called()

    def test_irc_unmanaged_channel_exclusion(self, bot, mock_irc_connection):
        """管理外の IRC チャンネルからのメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#managed-irc", "111")]):
            # 管理外のチャンネルからのメッセージ
            event = MagicMock()
            event.target = "#unmanaged-irc"
            event.arguments = ["Hello"]
            event.source.nick = "Alice"

            bot.irc_client.on_pubmsg(mock_irc_connection, event)

            # Discord 側に転送されないことを確認
            # discord_channel_map は空なので、何も呼ばれないはず
            assert len(bot.discord_channel_map) == 0

    def test_discord_unmanaged_channel_exclusion(self, bot, mock_irc_connection):
        """管理外の Discord チャンネルからのメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#managed-irc", "111")]):
            # 管理外のチャンネルからのメッセージ
            message = MagicMock()
            message.content = "Hello"
            message.author.display_name = "Bob"
            message.channel.id = "999" # 管理外

            bot.discord_client = MagicMock()
            bot.discord_client.user.id = 123456789

            loop = asyncio.get_event_loop()
            loop.run_until_complete(bot.on_message(message))

            # IRC 側に転送されないことを確認
            mock_irc_connection.privmsg.assert_not_called()

    def test_discord_channel_not_found(self, bot, mock_discord_client, mock_irc_connection):
        """Discord チャンネルが見つからない場合の処理テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            # Discord チャンネルが取得できない設定にする
            mock_discord_client.get_channel.return_value = None
            bot.discord_channel_map = {} # キャッシュを空に

            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["Hello"]
            event.source.nick = "Alice"

            # IRCClient の Nick を設定
            bot.irc_client.nick_candidates = ["BotNick"]
            bot.irc_client.current_nick_index = 0

            bot.irc_client.on_pubmsg(mock_irc_connection, event)

            # Discord チャンネルが見つからないため、送信は行われない
            # (AsyncMock を使っていないので、単純に何も呼ばれていないことを確認)
            # ここでは discord_channel_map に追加されなかったことを確認
            assert "111" not in bot.discord_channel_map

if __name__ == "__main__":
    pytest.main()
