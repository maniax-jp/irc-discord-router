import pytest
import threading
import time
import subprocess
from bot import IRCClient, DEFAULT_NICK
from unittest.mock import MagicMock

# テスト設定
TEST_IRC_SERVER = "localhost"
TEST_IRC_PORT = 6667
TEST_CHANNEL = "#test-reconnect"

class ReconnectIRCClient(IRCClient):
    """再接続イベントを記録するためのIRCClientサブクラス"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.welcome_count = 0
        self.joined_channels = []

    def on_welcome(self, c, e):
        self.welcome_count += 1
        super().on_welcome(c, e)

    def on_join(self, connection, event):
        if event.source.nick == self.current_nick:
            self.joined_channels.append(event.target)
        super().on_join(connection, event)

@pytest.fixture(scope="module")
def irc_server():
    """docker-compose.test.yml を使用して IRC サーバーを管理する"""
    # 既存のコンテナを削除して競合を避ける
    subprocess.run(["docker", "rm", "-f", "irc-test-server"], capture_output=True)
    # 起動
    subprocess.run(["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d"], check=True)
    # 起動待ち
    time.sleep(5)
    yield
    # 停止・削除
    subprocess.run(["docker", "compose", "-f", "docker-compose.test.yml", "down"], check=True)

def test_automatic_reconnection(irc_server):
    """サーバー再起動後の自動再接続とチャンネル再参加を検証する"""
    mock_bot = MagicMock()
    client = ReconnectIRCClient(
        mock_bot,
        TEST_IRC_SERVER,
        TEST_IRC_PORT,
        "ReconnectBot",
        "TestRealName"
    )

    # チャンネルペアをモックして、特定のチャンネルに参加するようにする
    import bot
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bot, "CHANNEL_PAIRS", [(TEST_CHANNEL, "123")])

        # IRC リアクターを別スレッドで開始
        irc_thread = threading.Thread(target=client.start, daemon=True)
        irc_thread.start()

        # 1回目の接続確認
        timeout = 15
        start_time = time.time()
        while (client.welcome_count < 1 or TEST_CHANNEL not in client.joined_channels) and (time.time() - start_time) < timeout:
            time.sleep(0.5)

        assert client.welcome_count >= 1, "初回接続に失敗しました"
        assert TEST_CHANNEL in client.joined_channels, "初回チャンネル参加に失敗しました"

        # サーバーを再起動
        subprocess.run(["docker", "compose", "-f", "docker-compose.test.yml", "restart"], check=True)

        # 再接続確認 (指数バックオフがあるため、少し長めに待機)
        timeout = 60
        start_time = time.time()
        while (client.welcome_count < 2 or TEST_CHANNEL not in client.joined_channels) and (time.time() - start_time) < timeout:
            time.sleep(0.5)

        assert client.welcome_count >= 2, "サーバー再起動後の再接続に失敗しました"
        # 再参加したか確認 (リストに再度追加されているか、または最新の状態か)
        assert TEST_CHANNEL in client.joined_channels, "再接続後のチャンネル再参加に失敗しました"

if __name__ == "__main__":
    pytest.main([__file__])
