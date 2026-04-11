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

# .env ファイルから環境変数をロード
load_dotenv()

# 設定値を環境変数から取得
IRC_SERVER = os.getenv("IRC_SERVER")
IRC_PORT = int(os.getenv("IRC_PORT", 6667))
IRC_CHANNEL = os.getenv("IRC_CHANNEL")
IRC_NICK = os.getenv("IRC_NICK")
IRC_USER = os.getenv("IRC_USER")
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

    def on_pubmsg(self, connection, event):
        """チャンネルメッセージ受信時の処理"""
        # メッセージ内容を抽出
        message_content = event.arguments[0]
        sender_nick = event.source.nick

        print(f"[受信] IRC チャンネル {event.target} からメッセージ：{message_content} (送信者：{sender_nick})")

        # ボット自身のメッセージは無視
        if sender_nick == IRC_NICK:
            print(f"[送信] 自分からのメッセージを無視")
            return

        # Discord 側に転送
        print(f"Discord への転送：{message_content}")
        if self.bot.discord_channel:
            # Discord は非同期なので、別のタスクとしてスケジュールする
            asyncio.run_coroutine_threadsafe(
                self.bot.discord_channel.send(f"{sender_nick}: {message.content}"),
                self.bot.discord_client.loop
            )
            print(f"IRC → Discord: {message.content}")

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
        self.irc_nick = IRC_NICK

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
        print(f"[受信] Discord からメッセージ：{message.content}")

        # 自分のメッセージは処理しない
        if message.author == self.discord_client.user:
            print(f"[送信] 自分からのメッセージを無視")
            return

        # 指定されたチャンネルのメッセージのみ処理
        if message.channel.id != int(DISCORD_CHANNEL_ID):
            print(f"チャンネル ID が一致しない：{message.channel.id} != {DISCORD_CHANNEL_ID}")
            return

        # IRC 側に転送
        print(f"Discord → IRC への転送：{message.content}")
        if self.irc_client.connection:
            self.irc_client.connection.privmsg(IRC_CHANNEL, f"{message.author.name}: {message.content}")
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
        self.irc_client.connect(IRC_SERVER, IRC_PORT, IRC_NICK)
        # チャンネルに参加
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
