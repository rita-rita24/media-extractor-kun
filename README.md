# メディア抽出くん

YouTube / TikTok / Instagram / X などの動画URLから、音声（MP3）または動画（MP4）を保存するローカル実行向けWebアプリです。

このツールは、公開サーバーとして不特定多数に提供するよりも、利用者それぞれのPC上で起動して使う前提にしています。動画取得・変換は通信量やCPU負荷が大きく、外部サービスの仕様変更や利用規約の影響も受けやすいためです。

## このツールの位置づけ

- ブラウザUIは `http://localhost:3000` で開きます
- APIは同じPC上の `http://localhost:8000` で動きます
- ダウンロードと変換は利用者のPC上で実行されます
- 生成ファイルは一時ディレクトリに保存され、ダウンロード後に削除できます
- URLやジョブ情報はメモリ上で管理され、永続保存はしません

公開サーバーに置くことも技術的には可能ですが、認証・利用制限・キュー管理・永続ストレージ・ログ監視・規約面の整理が必要になります。個人利用や少人数配布では、各自ローカルで起動してもらう運用を推奨します。

## 対応サイト

- YouTube（通常動画、Shorts）
- TikTok
- Instagram（投稿、リール）
- X / Twitter
- 直接メディアURL（`.mp3`, `.mp4`, `.wav`, `.m4a`, `.webm`, `.ogg`, `.aac`, `.flac`）

## 主な機能

- 音声のみ保存（MP3）
- 動画保存（MP4）
- 非同期ジョブ処理
- リアルタイム進捗表示
- カスタムファイル名
- 同時処理数の制限
- リクエスト頻度制限
- 古い一時ファイルの自動クリーンアップ

## 動作イメージ

```text
利用者のブラウザ
  http://localhost:3000
        |
        | /api
        v
ローカルAPI（FastAPI）
  http://localhost:8000
        |
        | yt-dlp / ffmpeg / HTTP取得
        v
利用者PC上の一時ファイル
```

## 必要なもの

事前に以下をインストールしてください。

- Node.js
- Python 3
- ffmpeg

`yt-dlp` は Python の依存関係としてセットアップ時にインストールされます。ただし、OS側のコマンドとして `yt-dlp` を使える状態にしておくとトラブルシュートしやすくなります。

### macOS

```bash
brew install node python ffmpeg yt-dlp
```

### Windows

```powershell
winget install OpenJS.NodeJS Python.Python.3 FFmpeg yt-dlp
```

Windows では環境によって `python3` コマンドが使えない場合があります。その場合は WSL / Git Bash を使うか、`package.json` の `python3` を環境に合わせて調整してください。

## セットアップ

リポジトリ直下で実行します。

```bash
npm install
npm run setup
```

`npm run setup` は以下を行います。

- フロントエンド依存関係のインストール
- `backend/venv` の作成
- Python依存関係のインストール

## 起動

Web UI と API を同時に起動します。

```bash
npm run dev
```

起動後、ブラウザで以下を開きます。

```text
http://localhost:3000
```

個別に起動したい場合は以下を使います。

```bash
npm run dev:web
npm run dev:api
```

## 使い方

1. `http://localhost:3000` を開く
2. 対応サービスのURLを貼り付ける
3. 必要ならファイル名を入力する
4. 「音声のみ」または「動画」を選ぶ
5. 抽出を開始する
6. 完了後、ファイルをダウンロードする

処理時間は動画の長さ、ネットワーク速度、PC性能によって変わります。

| 動画の長さ | 処理時間の目安 |
| --- | --- |
| 10分 | 1〜3分 |
| 1時間 | 5〜15分 |
| 3時間 | 15〜45分 |

## API エンドポイント

| メソッド | パス | 説明 |
| --- | --- | --- |
| `POST` | `/api/extract` | 抽出ジョブを開始 |
| `GET` | `/api/job/{job_id}` | ジョブステータスを取得 |
| `GET` | `/api/download/{job_id}/{filename}` | 生成ファイルをダウンロード |
| `DELETE` | `/api/job/{job_id}` | ジョブと一時ファイルを削除 |
| `GET` | `/api/health` | ヘルスチェック |

## 設定

バックエンドは環境変数で一部の制限値を変更できます。

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | APIへのアクセスを許可するOrigin |
| `MAX_CONCURRENT_JOBS` | `3` | 同時に処理できるジョブ数 |
| `JOB_RATE_LIMIT_WINDOW_SECONDS` | `60` | レート制限の判定期間 |
| `JOB_RATE_LIMIT_MAX_REQUESTS` | `5` | 判定期間内に開始できるジョブ数 |
| `MAX_DIRECT_MEDIA_BYTES` | `536870912` | 直接メディアURLの最大サイズ |

例:

```bash
ALLOWED_ORIGINS=http://localhost:3000 MAX_CONCURRENT_JOBS=1 npm run dev:api
```

## ローカル配布する場合

他の人に使ってもらう場合は、以下の流れを推奨します。

1. GitHubやZIPでこのリポジトリを渡す
2. 利用者に Node.js / Python 3 / ffmpeg を入れてもらう
3. 利用者のPCで `npm install` と `npm run setup` を実行してもらう
4. `npm run dev` で起動してもらう
5. `http://localhost:3000` にアクセスして使ってもらう

この方式なら、処理負荷・通信量・生成ファイルが各利用者のPC内に閉じます。

## 公開サーバー化について

公開サーバーとして運用する場合は、最低限以下を検討してください。

- 認証
- IP単位やユーザー単位のレート制限
- ジョブキュー
- ジョブ状態の永続化
- ファイル保存先の設計
- 自動削除ポリシー
- サーバーのCPU・メモリ・ディスク・転送量
- エラーログと監視
- 対応サイトの利用規約・著作権リスク

参考として、フロントエンドは以下でビルドできます。

```bash
npm run build
```

本番配信する場合は `frontend/dist` を静的配信し、`/api` を FastAPI にリバースプロキシします。

## トラブルシュート

### `ffmpeg` が見つからない

`ffmpeg` がインストールされ、PATH に入っているか確認してください。

```bash
ffmpeg -version
```

### `yt-dlp` の実行に失敗する

対象サービス側の仕様変更、年齢制限、ログイン必須、非公開動画、地域制限などで失敗することがあります。まず `yt-dlp` を更新してください。

```bash
backend/venv/bin/python -m pip install -U yt-dlp
```

### ポートが使われている

既に `3000` または `8000` が使われている可能性があります。該当プロセスを停止するか、設定を変更してください。

### セットアップをやり直したい

依存関係を入れ直す場合は、`node_modules`、`frontend/node_modules`、`backend/venv` を削除してから再度セットアップしてください。

```bash
npm install
npm run setup
```

## 注意事項

自分が権利を持つ動画、または保存が許可されているコンテンツに対して使用してください。

- 著作権で保護されたコンテンツの無断ダウンロードは法律違反となる可能性があります
- 各サービスの利用規約を確認してください
- 対象サイトの仕様変更により、突然動作しなくなることがあります

## ライセンス

MIT License
