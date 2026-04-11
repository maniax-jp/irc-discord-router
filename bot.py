#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IRC-Discord 双方向転送ボット
"""

import discord
import asyncio
import threading
import os
from dotenv import load_dotenv
from irc.client import SimpleIRCClient
# config import を削除し、直接 .env から読み込む形式に変更

# .env ファイルから環境変数をロード
load_dotenv()

# 設定値を環境変数から取得
IRC_SERVER = os.getenv("IRC_SERVER")
IRC_PORT = int(os.getenv("IRC_PORT", 6667))
IRC_CHANNEL = os.getenv("IRC_CHANNEL")
IRC_USER = os.getenv("IRC_USER")
# 初期 NICK は後で動的に決定するため、ここではデフォルト値として保持
DEFAULT_NICK = os.getenv("IRC_NICK", "BOT_DISCORD")
IRC_USER_REALNAME = "BOT_DISCORD"
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# グローバル変数
discord_client = None
discord_channel = None
irc_client = None

class IRCClient(SimpleIRCClient):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        # NICK 候補を生成: B, BO, BOT, BOT_, BOT_D, ...
        self.nick_candidates = [DEFAULT_NICK[:i] for i in range(1, len(DEFAULT_NICK) + 1)]
        self.current_nick_index = 0

    def _handle_numeric(self, connection, event, *args):
        """サーバーからの数値レスポンスを処理"""
        # ERR_NICKNAMEINUSE (433) の処理
        if event.numeric == 433:
            self.current_nick_index += 1
            if self.current_nick_index < len(self.nick_candidates):
                new_nick = self.nick_candidates[self.current_nick_index]
                print(f"[IRC] Nickname in use. Trying new nick: {new_nick}")
                connection.nick(new_nick)
            else:
                print("[IRC] All nickname candidates exhausted.")

        super()._handle_numeric(connection, event, *args)

    def on_pubmsg(self, connection, event):
        """チャンネルメッセージ受信時の処理"""
        # メッセージ内容を抽出
        message_content = event.arguments[0]
        sender_nick = event.source.nick

        print(f"[受信] IRC チャンネル {event.target} からメッセージ：{message_content} (送信者：{sender_nick})")

        # ボット自身の現在の Nick を無視
        current_nick = self.nick_candidates[self.current_nick_index] if self.current_nick_index < len(self.nick_candidates) else DEFAULT_NICK
        if sender_nick == current_nick:
            print(f"[無視] IRC ボット自身のメッセージを無視")
            return

        # Discord 側に転送
        print(f"Discord への転送：{message_content}")
        if self.bot.discord_channel:
            # Discord は非同期なので、別のタスクとしてスケジュールする
            asyncio.run_coroutine_threadsafe(
                self.bot.discord_channel.send(f"{sender_nick}: {message_content}"),
                self.bot.discord_client.loop
            )
            print(f"IRC → Discord: {message_content}")

    def on_join(self, connection, event):
        """チャンネル参加時の処理"""
        print(f"IRC チャンネルに参加しました：{event.target}")
        # IRC に起動メッセージを送信
        connection.privmsg(IRC_CHANNEL, "[BOT] IRC-Discord ボットが起動しました")
        print(f"IRC に起動メッセージを送信しました")

class Bot:
    def __init__(self):
        self.irc_client = IRCClient(self)
        self.discord_client = None
        self.discord_channel = None
        self.irc_channel = IRC_CHANNEL
        # 動的に決定されるため、初期値は candidate の最初
        self.irc_nick = IRCClient(self).nick_candidates[0]

    async def on_ready(self):
        """Discord 接続時の処理"""
        print(f"Discord ボットが起動しました：{self.discord_client.user}")
        # チャンネルを取得
        self.discord_channel = self.discord_client.get_channel(int(DISCORD_CHANNEL_ID))
        if self.discord_channel:
            print(f"チャンネル {DISCORD_CHANNEL_ID} を取得しました")
            # 最初のメッセージを送信
            await self.discord_channel.send(f"[BOT] IRC-Discord ボットが起動しました")
            print(f"Discord に最初のメッセージを送信しました")
        else:
            print("チャンネルの取得に失敗しました")

    async def on_message(self, message):
        """Discord メッセージ受信時の処理"""
        print(f"[受信] Discord からメッセージ：{message.content} (作者：{message.author})")

        # 自分のメッセージは処理しない (IDで厳密に比較)
        if self.discord_client.user and message.author.id == self.discord_client.user.id:
            print(f"[無視] Discord ボット自身のメッセージを無視")
            return

        # 指定されたチャンネルのメッセージのみ処理
        if message.channel.id != int(DISCORD_CHANNEL_ID):
            print(f"チャンネル ID が一致しない：{message.channel.id} != {DISCORD_CHANNEL_ID}")
            return

        # IRC 側に転送
        print(f"Discord → IRC への転送：{message.content}")
        if self.irc_client.connection:
            self.irc_client.connection.privmsg(IRC_CHANNEL, f"{message.author.display_name}: {message.content}")
            print(f"Discord → IRC: {message.content}")
        else:
            print("IRC 接続が確立されていないため、転送に失敗しました")

    def run_irc_reactor(self):
        """IRC リアクターを別スレッドで実行する"""
        print("IRC リアクターを起動します...")
        self.irc_client.reactor.process_forever()

    def run(self):
        # Discord クライアントの作成
        intents = discord.Intents.default()
        intents.message_content = True
        self.discord_client = discord.Client(intents=intents)

        # Discord イベントの登録
        self.discord_client.event(self.on_ready)
        self.discord_client.event(self.on_message)

        # IRC サーバーへの接続
        # 最初の NICK 候補を使用
        initial_nick = self.irc_client.nick_candidates[0]
        self.irc_client.connect(IRC_SERVER, IRC_PORT, initial_nick)

        # ユーザー名(REALNAME)を設定
        if self.irc_client.connection:
            # SimpleIRCClient では connect 時に自動的に USER コマンドが送られるが、
            # ここでは明示的に REALNAME を設定したい場合、send_raw や専用メソッドが必要。
            # シンプルに connection.user(user, name) を呼ぶ。
            self.irc_client.connection.user(IRC_USER or "discord_bot", IRC_USER_REALNAME)
            self.irc_client.connection.join(IRC_CHANNEL)
            print(f"IRC チャンネル {IRC_CHANNEL} に参加リクエストを送信しました")

        # IRC リアクターを別スレッドで開始
        irc_thread = threading.Thread(target=self.run_irc_reactor, daemon=True)
        irc_thread.start()

        # Discord ボットの起動
        self.discord_client.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    bot = Bot()
    bot.run()
