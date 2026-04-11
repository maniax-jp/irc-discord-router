# IRC-Discord Router Bot

IRCチャンネルとDiscordテキストチャンネルを双方向に接続し、メッセージを相互に転送するボットです。

## 特徴

- **双方向転送**: IRCで発言した内容はDiscordへ、Discordで発言した内容はIRCへリアルタイムに転送されます。
- **複数チャンネルペアのサポート**: 複数のIRCチャンネルとDiscordチャンネルをペアとして設定し、個別に転送ルートを管理できます。
- **動的なニックネーム決定**: IRCサーバー接続時にニックネームが重複している場合、設定された基本ニックネームを1文字ずつ延長して、最短の利用可能なニックネームを自動的に試行します。
- **ループ防止**: ボット自身のメッセージを無視することで、IRCとDiscordの間でメッセージが無限に往復するループを防止しています。
- **Docker対応**: Docker Compose を使用して簡単にデプロイ・管理が可能です。

## 準備

### 必要要件
- Docker / Docker Compose
- Discord Bot Token (Discord Developer Portalで作成し、`MESSAGE CONTENT INTENT` を有効にしてください)
- 接続先のIRCサーバー情報

## セットアップと起動

### 1. 環境設定
`.env.example` をコピーして `.env` ファイルを作成し、環境に合わせて編集してください。

```bash
cp .env.example .env
```

#### .env 設定項目
- `IRC_SERVER`: 接続先IRCサーバーのホスト名
- `IRC_PORT`: IRCポート番号 (デフォルト: 6667)
- `IRC_NICK`: ボットの基本ニックネーム (例: `BOT_DISCORD`)
- `IRC_USER`: IRCユーザー名
- `DISCORD_BOT_TOKEN`: Discordボットのトークン
- `CHANNEL_PAIRS`: 転送ペアの設定。形式は `"irc_channel:discord_channel_id"` で、カンマ区切りで複数指定可能です。
  - 例: `#test:123456789012345678,#general:987654321098765432`

### 2. 起動
Docker Compose を使用してボットを起動します。イメージは Docker Hub (`maniaxjp/irc-discord-router`) から自動的にプルされます。

```bash
docker compose up -d
```

#### (オプション) ソースからビルドして起動する場合
最新のソースコードからビルドして起動したい場合は、以下の手順でイメージをビルドしてから起動してください。

```bash
docker build -t maniaxjp/irc-discord-router .
docker compose up -d
```

### 3. ログの確認
ボットの動作状況を確認するには、以下のコマンドでログを表示してください。

```bash
docker compose logs -f
```

## ディレクトリ構成

- `bot.py`: メインロジック (IRC/Discord クライアントの実装)
- `Dockerfile`: コンテナ定義
- `docker-compose.yml`: コンテナオーケストレーション設定
- `.env`: 環境設定ファイル
- `requirements.txt`: 依存ライブラリ一覧
