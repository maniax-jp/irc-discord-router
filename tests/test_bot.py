# -*- coding: utf-8 -*-
"""
IRC-Discord Bot テスト
"""

import asyncio
import threading
import time
import subprocess
import pytest
import irc.client
import irc.bot
import discord
from unittest.mock import MagicMock, patch, AsyncMock
from bot import Bot, IRCClient, DEFAULT_NICK, IRC_SERVER as ORIGINAL_SERVER, IRC_PORT as ORIGINAL_PORT, parse_channel_pairs

# テスト用の設定
TEST_IRC_SERVER = "localhost"
TEST_IRC_PORT = 6667
TEST_CHANNEL = "#test"

class MockMessageable(discord.abc.Messageable):
    """
    Messageable インターフェースを模倣するモッククラス。
    isinstance(obj, discord.abc.Messageable) を True にしつつ、
    send メソッドを AsyncMock にすることで検証を可能にする。
    """
    def __init__(self):
        self.send = AsyncMock()



class IRCServerManager:
    """ngircd コンテナを管理するクラス"""
    def __init__(self):
        self.container_name = "irc-test-server"

    def start(self):
        # 既存のコンテナを削除して新しく起動
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
        subprocess.run(
            ["docker", "run", "-d", "--name", self.container_name, "-p", f"{TEST_IRC_PORT}:{TEST_IRC_PORT}", "lscr.io/linuxserver/ngircd:latest"],
            capture_output=True, check=True
        )
        # 起動まで少し待機
        time.sleep(2)

    def stop(self):
        subprocess.run(["docker", "stop", self.container_name], capture_output=True)

    def restart(self):
        subprocess.run(["docker", "restart", self.container_name], capture_output=True)

@pytest.fixture(scope="module")
def irc_server():
    manager = IRCServerManager()
    manager.start()
    yield manager
    manager.stop()

class TestBot:
    """
    Bot クラスの機能テスト。
    """
    @pytest.fixture
    def bot(self):
        """Bot インスタンスのフィクスチャ"""
        b = Bot()
        b.loop = asyncio.get_event_loop()
        return b

    @pytest.fixture
    def mock_bot(self, bot):
        """Discord 側をモック化した Bot インスタンス"""
        bot.discord_client = MagicMock()
        bot.discord_client.loop = asyncio.get_event_loop()
        bot.discord_channel_map = {}
        return bot

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
        assert mock_discord_client is not None
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            mock_channel = MockMessageable()
            bot.discord_channel_map["111"] = mock_channel

            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["Hello Discord!"]
            event.source.nick = "Alice"

            # ボット自身のメッセージにならないように設定
            bot.irc_client.current_nick = "BotNick"

            bot.irc_client.on_pubmsg(mock_irc_connection, event)
            mock_channel.send.assert_called_with("Alice: Hello Discord!")

    def test_discord_to_irc_forward(self, bot, mock_irc_connection):
        """Discord から IRC へのメッセージ転送テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            message = MagicMock()
            message.content = "Hello IRC!"
            message.author.display_name = "Bob"
            message.author.id = 987654321
            message.channel.id = "111"

            bot.discord_client = MagicMock()
            bot.discord_client.user.id = 123456789

            loop = asyncio.get_event_loop()
            loop.run_until_complete(bot.on_message(message))

            mock_irc_connection.privmsg.assert_called_with("#test-irc", "Bob: Hello IRC!")

    def test_irc_bot_message_exclusion(self, bot, mock_irc_connection):
        """IRC ボット自身のメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            mock_channel = MockMessageable()
            bot.discord_channel_map["111"] = mock_channel

            bot.irc_client.current_nick = "BotNick"

            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["I am a bot"]
            event.source.nick = "BotNick"

            bot.irc_client.on_pubmsg(mock_irc_connection, event)
            mock_channel.send.assert_not_called()

    def test_discord_bot_message_exclusion(self, bot, mock_irc_connection, mock_discord_client):
        """Discord ボット自身のメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            message = MagicMock()
            message.content = "I am a bot"
            message.author.id = mock_discord_client.user.id
            message.channel.id = "111"

            loop = asyncio.get_event_loop()
            loop.run_until_complete(bot.on_message(message))

            mock_irc_connection.privmsg.assert_not_called()

    def test_irc_unmanaged_channel_exclusion(self, bot, mock_irc_connection):
        """管理外の IRC チャンネルからのメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#managed-irc", "111")]):
            event = MagicMock()
            event.target = "#unmanaged-irc"
            event.arguments = ["Hello"]
            event.source.nick = "Alice"

            bot.irc_client.on_pubmsg(mock_irc_connection, event)
            assert len(bot.discord_channel_map) == 0

    def test_discord_unmanaged_channel_exclusion(self, bot, mock_irc_connection):
        """管理外の Discord チャンネルからのメッセージ除外テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#managed-irc", "111")]):
            message = MagicMock()
            message.content = "Hello"
            message.author.display_name = "Bob"
            message.channel.id = "999"

            bot.discord_client = MagicMock()
            bot.discord_client.user.id = 123456789

            loop = asyncio.get_event_loop()
            loop.run_until_complete(bot.on_message(message))

            mock_irc_connection.privmsg.assert_not_called()

    def test_discord_channel_not_found(self, bot, mock_discord_client, mock_irc_connection):
        """Discord チャンネルが見つからない場合の処理テスト"""
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            mock_discord_client.get_channel.return_value = None
            bot.discord_channel_map = {}

            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["Hello"]
            event.source.nick = "Alice"

            bot.irc_client.current_nick = "BotNick"
            bot.irc_client.on_pubmsg(mock_irc_connection, event)
            assert "111" not in bot.discord_channel_map

    def test_nickname_fallback_logic(self, mock_bot):
        """
        ニックネーム衝突時のフォールバック動作を検証する
        期待される挙動: 前方一致 (1文字目から) -> 末尾に数字付与
        """
        # Bot の IRCClient を作成
        irc_client = IRCClient(mock_bot, TEST_IRC_SERVER, TEST_IRC_PORT, DEFAULT_NICK, "TestRealName")

        # 1. 前方一致の検証
        # 最初のニックネームは既に設定済みなので、2番目から検証する
        expected_prefixes = [DEFAULT_NICK[:i] for i in range(2, len(DEFAULT_NICK) + 1)]
        for expected in expected_prefixes:
            mock_conn = MagicMock()
            irc_client.on_nicknameinuse(mock_conn, None)
            assert irc_client.current_nick == expected
            mock_conn.nick.assert_called_with(expected)

        # 2. 数字付与の検証
        for i in range(1, 5):
            mock_conn = MagicMock()
            irc_client.on_nicknameinuse(mock_conn, None)
            assert irc_client.current_nick == f"{DEFAULT_NICK}{i}"
            mock_conn.nick.assert_called_with(f"{DEFAULT_NICK}{i}")

    def test_reconnection_channel_rejoin(self, mock_bot):
        """
        サーバー復帰時のチャンネル再参加を検証する
        """
        # Bot の IRC client を作成
        irc_client = IRCClient(mock_bot, TEST_IRC_SERVER, TEST_IRC_PORT, DEFAULT_NICK, "TestRealName")

        # チャンネルペアをモック化
        with patch("bot.CHANNEL_PAIRS", [(TEST_CHANNEL, "123"), ("#other", "456")]):
            mock_conn = MagicMock()
            irc_client.on_welcome(mock_conn, None)

            # 全ての管理対象チャンネルに join が呼ばれたか確認
            mock_conn.join.assert_any_call(TEST_CHANNEL)
            mock_conn.join.assert_any_call("#other")
            assert mock_conn.join.call_count == 2

    def test_parse_channel_pairs_malformed(self):
        """
        不正な形式のチャンネルペア文字列が正しく処理され、有効なものだけが抽出されることを検証する
        """
        malformed_str = "#chan1:111,invalid_pair,#chan2:222,:333,444:"
        result = parse_channel_pairs(malformed_str)
        assert result == [("#chan1", "111"), ("#chan2", "222")]

    def test_discord_invalid_id_handling(self, bot, mock_discord_client, mock_irc_connection):
        """
        Discord チャンネル ID が数値でない場合に、エラーログを出力して適切に無視されることを検証する
        """
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "invalid_id")]):
            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["Hello"]
            event.source.nick = "Alice"
            bot.irc_client.current_nick = "BotNick"

            # 実行しても例外が発生せず、正常に終了することを確認
            bot.irc_client.on_pubmsg(mock_irc_connection, event)
            assert "invalid_id" not in bot.discord_channel_map

    def test_channel_pair_independence(self, bot, mock_discord_client, mock_irc_connection):
        """
        複数のチャンネルペアが互いに干渉せず、正しく転送されることを検証する
        """
        with patch("bot.CHANNEL_PAIRS", [("#irc1", "111"), ("#irc2", "222")]):
            mock_channel_111 = MockMessageable()
            mock_channel_222 = MockMessageable()
            bot.discord_channel_map["111"] = mock_channel_111
            bot.discord_channel_map["222"] = mock_channel_222

            # #irc1 へのメッセージをシミュレート
            event1 = MagicMock()
            event1.target = "#irc1"
            event1.arguments = ["Msg 1"]
            event1.source.nick = "Alice"
            bot.irc_client.current_nick = "BotNick"
            bot.irc_client.on_pubmsg(mock_irc_connection, event1)

            mock_channel_111.send.assert_called()
            mock_channel_222.send.assert_not_called()

            # #irc2 へのメッセージをシミュレート
            event2 = MagicMock()
            event2.target = "#irc2"
            event2.arguments = ["Msg 2"]
            event2.source.nick = "Bob"
            bot.irc_client.on_pubmsg(mock_irc_connection, event2)

            mock_channel_222.send.assert_called()

    def test_discord_send_failure_logging(self, bot, mock_discord_client, mock_irc_connection):
        """
        Discord 送信に失敗した際に、_handle_discord_send_result が正しくエラーをログ出力することを検証する
        """
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "111")]):
            mock_channel = MockMessageable()
            # send が例外を投げるように設定
            mock_channel.send.side_effect = Exception("API Error")
            bot.discord_channel_map["111"] = mock_channel

            event = MagicMock()
            event.target = "#test-irc"
            event.arguments = ["Hello"]
            event.source.nick = "Alice"
            bot.irc_client.current_nick = "BotNick"

            with patch("bot.logger.error") as mock_log:
                bot.irc_client.on_pubmsg(mock_irc_connection, event)
                # asyncio.run_coroutine_threadsafe は即座に Future を返すため、
                # 実際にコールバックが呼ばれるまで待つか、手動でコールバックを呼ぶ必要がある。
                # ここではBot._handle_discord_send_result を直接テストする。

                future = MagicMock()
                future.result.side_effect = Exception("API Error")
                bot._handle_discord_send_result(future)

                mock_log.assert_called()
                # ログメッセージに "予期せぬエラーが発生しました" が含まれているか確認
                args, _ = mock_log.call_args
                assert "予期せぬエラーが発生しました" in args[0]

    def test_discord_send_specific_errors(self, bot):
        """
        Discord 送信時の具体的なエラー (Forbidden, HTTPException) が正しくログ出力されることを検証する
        """
        with patch("bot.logger.error") as mock_log:
            # 1. discord.Forbidden のケース
            future_forbidden = MagicMock()
            future_forbidden.result.side_effect = discord.Forbidden(MagicMock(), "No permission")
            bot._handle_discord_send_result(future_forbidden)

            args_forbidden, _ = mock_log.call_args
            assert "Discord チャンネルへの送信権限がありません" in args_forbidden[0]

            # 2. discord.HTTPException のケース
            future_http = MagicMock()
            future_http.result.side_effect = discord.HTTPException(MagicMock(), "HTTP Error")
            bot._handle_discord_send_result(future_http)

            args_http, _ = mock_log.call_args
            assert "Discord API エラーが発生しました" in args_http[0]

            # 3. その他の予期せぬエラーのケース
            future_generic = MagicMock()
            future_generic.result.side_effect = RuntimeError("Unexpected error")
            bot._handle_discord_send_result(future_generic)

            args_generic, _ = mock_log.call_args
            assert "予期せぬエラーが発生しました" in args_generic[0]

    def test_on_ready_invalid_id_handling(self, bot, mock_discord_client):
        """
        on_ready 時に Discord チャンネル ID が数値でない場合に、適切に無視されることを検証する
        """
        with patch("bot.CHANNEL_PAIRS", [("#test-irc", "invalid_id")]):
            # mock_discord_client は既にセットアップ済み
            loop = asyncio.get_event_loop()
            loop.run_until_complete(bot.on_ready())

            assert "invalid_id" not in bot.discord_channel_map


if __name__ == "__main__":
    pytest.main()
