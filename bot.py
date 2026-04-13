#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
IRC-Discord 双方向転送ボット
"""

import asyncio
import logging
import threading
import os
from typing import List, Tuple, Dict, Optional, Any
from concurrent.futures import Future
import discord
import irc.bot
from dotenv import load_dotenv

# ログ設定を discord.utils.setup_logging で行う
discord.utils.setup_logging(level=logging.INFO, root=True)
logger = logging.getLogger("irc_discord_router")

# .env ファイルから環境変数をロード
load_dotenv()

# 設定値を環境変数から取得
IRC_SERVER = os.getenv("IRC_SERVER", "localhost")
IRC_PORT = int(os.getenv("IRC_PORT", "6667"))
IRC_USER = os.getenv("IRC_USER", "discord_bot")
# チャンネルペアの設定 (形式: "#chan1:id1,#chan2:id2")
CHANNEL_PAIRS_STR = os.getenv("CHANNEL_PAIRS", "")
DEFAULT_NICK = os.getenv("IRC_NICK", "BOT_DISCORD")
IRC_USER_REALNAME = "irc_discord_router"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# チャンネルペアをパースしてリストに格納 [(irc_channel, discord_channel_id), ...]
def parse_channel_pairs(pairs_str: str) -> List[Tuple[str, str]]:
    """チャンネルペア文字列をパースしてリストに変換する"""
    pairs = []
    if pairs_str:
        for pair in pairs_str.split(","):
            if ":" in pair:
                irc_channel, disc_id = pair.split(":", 1)
                if irc_channel and disc_id:
                    pairs.append((irc_channel, disc_id))
                else:
                    logger.warning("[設定] チャンネル名またはIDが欠落しているため、不正な形式のペアを無視しました: %s", pair)
            else:
                logger.warning("[設定] 不正な形式のチャンネルペアを無視しました: %s", pair)
    return pairs

CHANNEL_PAIRS = parse_channel_pairs(CHANNEL_PAIRS_STR)
if CHANNEL_PAIRS_STR and not CHANNEL_PAIRS:
    logger.error("[設定] 有効なチャンネルペアが一つも見つかりませんでした。設定を確認してください。")

class IRCClient(irc.bot.SingleServerIRCBot):
    """
    IRC サーバーへの接続とメッセージの送受信を管理するクラス。
    """
    def __init__(self, bot: Bot, server: str, port: int, nickname: str, realname: str) -> None:
        # NICK 候補を生成: B, BO, BOT, BOT_, BOT_D, ...
        self.nick_candidates = [nickname[:i] for i in range(1, len(nickname) + 1)]
        self.current_nick_index = 0
        self.current_nick = self.nick_candidates[self.current_nick_index]
        super().__init__([(server, port)], self.current_nick, realname)
        self.bot = bot

    def on_nicknameinuse(self, c: Any, e: Any) -> None:
        """ERR_NICKNAMEINUSE (433) の処理"""
        self.current_nick_index += 1
        if self.current_nick_index < len(self.nick_candidates):
            # 第1段階: 前方一致
            new_nick = self.nick_candidates[self.current_nick_index]
            logger.info("[IRC] Nickname in use. Trying new nick: %s", new_nick)
            self.current_nick = new_nick
            c.nick(new_nick)
        elif self.current_nick_index < len(self.nick_candidates) + 99:
            # 第2段階: 数字付与
            suffix = self.current_nick_index - len(self.nick_candidates) + 1
            new_nick = f"{self.nick_candidates[-1]}{suffix}"
            logger.info("[IRC] Nickname in use. Trying new nick: %s", new_nick)
            self.current_nick = new_nick
            c.nick(new_nick)
        else:
            logger.error("[IRC] All nickname candidates exhausted.")

    def on_welcome(self, c: Any, e: Any) -> None:
        """サーバー接続成功時の処理"""
        # ユーザー名(REALNAME)を設定
        c.user(IRC_USER or "discord_bot", IRC_USER_REALNAME)
        # 全てのペアの IRC チャンネルに参加
        for irc_chan, _ in CHANNEL_PAIRS:
            c.join(irc_chan)
            logger.info("IRC チャンネル %s に参加リクエストを送信しました", irc_chan)

    def on_pubmsg(self, connection: Any, event: Any) -> None:
        """チャンネルメッセージ受信時の処理"""
        # メッセージ内容を抽出
        message_content = event.arguments[0]
        sender_nick = event.source.nick

        logger.info(
            "[受信] IRC チャンネル %s からメッセージ：%s (送信者：%s)",
            event.target, message_content, sender_nick
        )

        # ボット自身の現在の Nick を無視
        if sender_nick == self.current_nick:
            logger.info("[無視] IRC ボット自身のメッセージを無視")
            return

        # この IRC チャンネルに対応する Discord チャンネルを探す
        discord_id = None
        for irc_chan, d_id in CHANNEL_PAIRS:
            if irc_chan == event.target:
                discord_id = d_id
                break

        if discord_id:
            # Discord チャンネルオブジェクトを取得
            channel = self.bot.discord_channel_map.get(discord_id)
            if not channel:
                # キャッシュになければ取得を試みる
                try:
                    if self.bot.discord_client:
                        channel = self.bot.discord_client.get_channel(int(discord_id))
                    else:
                        channel = None
                except ValueError:
                    logger.error("Discord チャンネル ID %s が数値ではありません", discord_id)
                    channel = None

                if channel:
                    if isinstance(channel, discord.abc.Messageable):
                        self.bot.discord_channel_map[discord_id] = channel

            if isinstance(channel, discord.abc.Messageable):
                # Discord 側に転送
                logger.info("[転送] IRC → Discord：%s", message_content)
                if self.bot.loop:
                    future = asyncio.run_coroutine_threadsafe(
                        channel.send(f"{sender_nick}: {message_content}"),
                        self.bot.loop
                    )
                    future.add_done_callback(self.bot._handle_discord_send_result)
                else:
                    logger.error("Discord イベントループが準備できていないため、転送に失敗しました")
            elif channel:
                logger.error("Discord チャンネル %s はメッセージ送信に対応していません", discord_id)
            else:
                logger.error("Discord チャンネル %s が見つかりません", discord_id)
        else:
            logger.info("[無視] 管理外の IRC チャンネル %s からのメッセージです", event.target)

    def on_join(self, connection: Any, event: Any) -> None:
        """チャンネル参加時の処理"""
        # ボット自身の参加のみを処理
        if event.source.nick != self.current_nick:
            return

        logger.info("IRC チャンネルに参加しました：%s", event.target)
        # 参加したチャンネルが管理対象なら、起動メッセージを送信
        for irc_chan, _ in CHANNEL_PAIRS:
            if irc_chan == event.target:
                connection.privmsg(irc_chan, "[BOT] IRC-Discord ボットが起動しました")
                logger.info("IRC チャンネル %s に起動メッセージを送信しました", irc_chan)
                break

class Bot:
    """
    IRC と Discord 間でメッセージを双方向に転送するボット。
    """
    def __init__(self) -> None:
        self.irc_client = IRCClient(self, IRC_SERVER, IRC_PORT, DEFAULT_NICK, IRC_USER_REALNAME)
        self.discord_client: Optional[discord.Client] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.discord_channel_map: Dict[str, discord.abc.Messageable] = {} # discord_id -> discord_channel_object

    async def on_ready(self) -> None:
        """Discord 接続時の処理"""
        self.loop = asyncio.get_running_loop()
        if self.discord_client:
            logger.info("Discord ボットが起動しました：%s", self.discord_client.user)

        # 全てのペアについて Discord チャンネルをキャッシュ
        for _, discord_id in CHANNEL_PAIRS:
            try:
                channel = (
                    self.discord_client.get_channel(int(discord_id))
                    if self.discord_client else None
                )
            except ValueError:
                logger.error("Discord チャンネル ID %s が数値ではありません", discord_id)
                continue

            if (
                channel and isinstance(channel, discord.abc.Messageable)
            ):
                self.discord_channel_map[discord_id] = channel
                logger.info("チャンネル %s を取得しました", discord_id)
                # 最初のメッセージを送信
                await channel.send("[BOT] IRC-Discord ボットが起動しました")
                logger.info("Discord チャンネル %s に起動メッセージを送信しました", discord_id)
            else:
                logger.error("チャンネル %s の取得に失敗しました、またはメッセージ送信に対応していません", discord_id)

    async def on_message(self, message: discord.Message) -> None:
        """Discord メッセージ受信時の処理"""
        logger.info("[受信] Discord からメッセージ：%s (作者：%s)", message.content, message.author)

        # 自分のメッセージは処理しない (IDで厳密に比較)
        if (
            self.discord_client and self.discord_client.user
            and message.author.id == self.discord_client.user.id
        ):
            logger.info("[無視] Discord ボット自身のメッセージを無視")
            return

        # 送信元の Discord チャンネルが管理対象ペアに含まれているか確認
        irc_chan = None
        for c_irc, c_disc in CHANNEL_PAIRS:
            if str(message.channel.id) == c_disc:
                irc_chan = c_irc
                break

        if not irc_chan:
            logger.info("[無視] 管理外の Discord チャンネル %s からのメッセージです", message.channel.id)
            return

        # IRC 側に転送
        logger.info("[転送] Discord → IRC：%s", message.content)
        if self.irc_client.connection:
            self.irc_client.connection.privmsg(
                irc_chan, f"{message.author.display_name}: {message.content}"
            )
        else:
            logger.error("IRC 接続が確立されていないため、転送に失敗しました")

    def _handle_discord_send_result(self, future: Future) -> None:
        """Discord 送信結果を処理し、失敗した場合はログに出力する"""
        try:
            future.result()
        except discord.Forbidden:
            logger.error("[エラー] Discord チャンネルへの送信権限がありません。")
        except discord.HTTPException as e:
            logger.error("[エラー] Discord API エラーが発生しました: %s", e)
        except Exception as e:
            logger.error("[エラー] Discord へのメッセージ送信中に予期せぬエラーが発生しました: %s", e, exc_info=True)

    def run_irc_reactor(self) -> None:
        """IRC リアクターを別スレッドで実行する"""
        logger.info("IRC リアクターを起動します...")
        self.irc_client.start()

    def run(self) -> None:
        """
        DiscordボットとIRCリアクターを起動します。
        """
        # Discord トークンの検証
        if not DISCORD_BOT_TOKEN:
            logger.error("DISCORD_BOT_TOKEN が設定されていません")
            return

        # Discord クライアントの作成
        intents = discord.Intents.default()
        intents.message_content = True
        self.discord_client = discord.Client(intents=intents)

        # Discord イベントの登録
        self.discord_client.event(self.on_ready)
        self.discord_client.event(self.on_message)

        # IRC リアクターを別スレッドで開始
        irc_thread = threading.Thread(target=self.run_irc_reactor, daemon=True)
        irc_thread.start()

        # Discord ボットの起動
        self.discord_client.run(DISCORD_BOT_TOKEN, log_handler=None)

if __name__ == "__main__":
    mybot = Bot()
    mybot.run()
