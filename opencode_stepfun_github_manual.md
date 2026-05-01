# OpenCode + StepFun GitHub連携マニュアル

**目的:** GitHubのIssueやPRコメントから `/oc` を実行し、OpenCode + StepFunでリポジトリを解析・編集・コミット・PR作成まで行う。  
**対象リポジトリ例:** `https://github.com/halc8312/ESP`  
**更新日:** 2026-05-01

---

## 1. できるようになったこと

この構成では、スマホからGitHubを開いてIssueにコメントするだけで、AIエージェントに作業を依頼できます。

```text
GitHub Issueを作る
↓
Issueコメント欄に /oc ... と書く
↓
GitHub Actions が起動
↓
OpenCode がリポジトリをcheckout
↓
StepFun APIを使って解析・編集
↓
変更をコミット
↓
PRを作成
```

最終的に成功した状態は以下です。

```text
Issueコメント起動: OK
GitHub Actions起動: OK
checkout: OK
OpenCode起動: OK
opencode.json認識: OK
StepFun API接続: OK
APIキー認証: OK
リポジトリ解析: OK
ファイル作成: OK
コミット作成: OK
PR作成: OK
```

---

## 2. 必要なもの

| 項目 | 役割 |
|---|---|
| OpenCode GitHub App | Issue/PRコメントからOpenCodeを動かす |
| GitHub Actions workflow | `/oc` コメントを検知してOpenCodeを実行する |
| `opencode.json` | StepFunをOpenCodeのproviderとして登録する |
| `STEPFUN_API_KEY` | StepFun APIへ接続するためのGitHub Secret |
| StepFun Step Plan | `step-3.5-flash-2603` などを使うための契約 |

---

## 3. OpenCode GitHub Appを入れる

GitHub AppのURL:

```text
https://github.com/apps/opencode-agent
```

対象リポジトリにインストールします。

手順:

1. 上記URLを開く
2. **Install** を押す
3. 対象リポジトリを選ぶ
4. インストールする

OpenCode GitHub Appがないと、Issueコメントへの反応やPR作成がうまく動きません。

---

## 4. GitHub Secretを設定する

リポジトリで以下を開きます。

```text
Settings
→ Secrets and variables
→ Actions
→ Repository secrets
```

追加するSecret名:

```text
STEPFUN_API_KEY
```

値にはStepFunのAPIキーを入れます。

### 注意点

正しい入れ方:

```text
sk-xxxxxxxxxxxxxxxx
```

ダメな例:

```text
Bearer sk-xxxxxxxx
"sk-xxxxxxxx"
 sk-xxxxxxxx
sk-xxxxxxxx 
```

`Bearer`、引用符、前後の空白は入れません。

APIキーが間違っていると、Actionsログに以下のようなエラーが出ます。

```text
APIError: Incorrect API key provided
statusCode: 401
```

この場合、OpenCodeやGitHub Actionsの問題ではなく、StepFun APIキーの問題です。新しいAPIキーを作って、GitHub Secretを上書きします。

---

## 5. `opencode.json` を追加する

リポジトリ直下に以下のファイルを作成します。

```text
opencode.json
```

中身:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "stepfun/step-3.5-flash-2603",
  "provider": {
    "stepfun": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "StepFun",
      "options": {
        "baseURL": "https://api.stepfun.ai/step_plan/v1",
        "apiKey": "{env:STEPFUN_API_KEY}"
      },
      "models": {
        "step-3.5-flash-2603": {
          "name": "Step 3.5 Flash 2603",
          "limit": {
            "context": 262144,
            "output": 65536
          }
        },
        "step-3.5-flash": {
          "name": "Step 3.5 Flash",
          "limit": {
            "context": 262144,
            "output": 65536
          }
        }
      }
    }
  }
}
```

このファイルがないと、以下のエラーが出ます。

```text
ProviderModelNotFoundError
```

意味:

```text
OpenCodeが stepfun/step-3.5-flash-2603 を探したが、
stepfun provider の定義が見つからない
```

---

## 6. GitHub Actions workflowを追加する

以下のファイルを作成します。

```text
.github/workflows/opencode.yml
```

中身:

```yaml
name: opencode

on:
  issue_comment:
    types: [created, edited]
  pull_request_review_comment:
    types: [created, edited]
  workflow_dispatch:

jobs:
  opencode:
    if: |
      github.event_name == 'workflow_dispatch' ||
      startsWith(github.event.comment.body, '/oc') ||
      startsWith(github.event.comment.body, '/opencode') ||
      contains(github.event.comment.body, ' /oc') ||
      contains(github.event.comment.body, ' /opencode') ||
      contains(github.event.comment.body, '\n/oc') ||
      contains(github.event.comment.body, '\n/opencode')
    runs-on: ubuntu-latest
    timeout-minutes: 20

    permissions:
      id-token: write
      contents: write
      pull-requests: write
      issues: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 1
          persist-credentials: false

      - name: Run opencode
        uses: anomalyco/opencode/github@latest
        env:
          STEPFUN_API_KEY: ${{ secrets.STEPFUN_API_KEY }}
        with:
          model: stepfun/step-3.5-flash-2603
          share: false
```

---

## 7. 使い方

### 基本

Issueを作ったあと、Issue本文ではなく、**コメント欄**に書きます。

```text
/oc このIssueの内容を実装してください。必要なファイルを編集し、テストも追加して、PRを作成してください。
```

### README修正など小さい変更

```text
/oc README.mdを更新してください。変更は最小限にして、PRを作成してください。
```

### バグ修正

```text
/oc このIssueに書かれているバグを修正してください。原因を確認し、必要ならテストを追加してください。変更内容をPR本文にまとめてください。
```

### 分析レポート作成

```text
/oc リポジトリ全体を分析して、必ず Analysis_results/REPOSITORY_ANALYSIS.md というMarkdownファイルを新規作成してください。空フォルダだけ作らないでください。

以下の内容をファイルに書いてください:
1. ディレクトリ構成
2. 主要ファイル一覧
3. アプリの起動方法
4. 主要機能
5. データベース/モデル構成
6. 外部サービス連携
7. テスト構成
8. デプロイ構成
9. 改善提案

最後に git status を確認し、Analysis_results/REPOSITORY_ANALYSIS.md が変更として残っていることを確認してからコミットし、PRを作成してください。
```

### 既存PRへの追加修正

PRのコメント欄に書きます。

```text
/oc このPRの変更を確認して、足りないテストを追加してください。
```

---

## 8. 重要な使い方のコツ

### Issue本文ではなくコメント欄に `/oc`

このworkflowは以下を見ています。

```yaml
on:
  issue_comment:
```

これはIssue作成時の本文ではなく、**Issue作成後のコメント欄**です。

動かない例:

```text
新規Issueの本文に /oc と書く
```

動く例:

```text
Issueを作る
↓
そのIssueのコメント欄に /oc ... と投稿
```

### PRを作らせたいなら「ファイル変更」を明示する

OpenCodeは「調査して」だけだとコメント返信で終わることがあります。PRを作らせたい場合は、必ず以下を明示します。

```text
必ずファイルを作成/編集してください
git statusで変更が残っていることを確認してください
コミットしてPRを作成してください
```

### 空フォルダだけではPRにならない

Gitは空フォルダを管理しません。

```text
mkdir -p Analysis_results
```

だけだと差分が残らないので、PRが作られません。必ずファイル作成まで指示します。

```text
Analysis_results/REPOSITORY_ANALYSIS.md を作成してください
```

---

## 9. トラブルシューティング

### Actionsのrun自体が作られない

確認すること:

```text
.github/workflows/opencode.yml が main ブランチにあるか
Actionsが無効化されていないか
Issue本文ではなくコメント欄に書いているか
/oc が半角で書かれているか
```

OK:

```text
/oc READMEを修正して
```

NGになりやすい例:

```text
／oc READMEを修正して
```

上は全角スラッシュです。

---

### `No url found for submodule path 'llama.cpp' in .gitmodules`

エラー:

```text
fatal: No url found for submodule path 'llama.cpp' in .gitmodules
```

意味:

```text
Git上では llama.cpp がsubmodule扱いになっている
でも .gitmodules にURL情報がない
```

対策として、リポジトリ直下に `.gitmodules` を追加しました。

```ini
[submodule "llama.cpp"]
	path = llama.cpp
	url = https://github.com/ggerganov/llama.cpp.git
```

これで `actions/checkout` が通るようになりました。

---

### `ProviderModelNotFoundError`

エラー:

```text
ProviderModelNotFoundError
```

原因:

```text
opencode.yml で stepfun/step-3.5-flash-2603 を指定している
でも opencode.json に stepfun provider が定義されていない
```

対策:

```text
リポジトリ直下に opencode.json を追加する
```

---

### `Incorrect API key provided`

エラー:

```text
APIError: Incorrect API key provided
statusCode: 401
```

原因:

```text
GitHub SecretのSTEPFUN_API_KEYが間違っている
またはStepFun側で無効なAPIキーを使っている
```

対策:

```text
StepFunでAPIキーを新規発行
GitHub Secrets の STEPFUN_API_KEY を上書き
Bearerや引用符なしで貼る
```

---

### OpenCodeは成功したのにPRが作られない

よくある原因:

```text
ファイル変更が残っていない
空フォルダだけ作っている
調査結果をコメントで返しただけ
```

対策:

```text
必ず xxx.md を作成してください
git statusで変更が残っていることを確認してください
PRを作成してください
```

---

## 10. 作業依頼テンプレート

### 汎用テンプレ

```text
/oc このIssueの内容を実装してください。
必要なファイルを編集し、必要ならテストも追加してください。
最後にgit statusを確認し、変更が残っていることを確認してからコミットし、PRを作成してください。
```

### 最小変更テンプレ

```text
/oc 指定された内容だけを最小変更で実装してください。
不要なリファクタや大規模変更は避けてください。
変更後、PRを作成してください。
```

### 調査レポートテンプレ

```text
/oc リポジトリを調査して、docs/REPOSITORY_REPORT.md を作成してください。
調査結果はコメントだけで終わらせず、必ずMarkdownファイルに保存してください。
git statusで変更が残っていることを確認し、PRを作成してください。
```

### テスト追加テンプレ

```text
/oc このPR/Issueに関連するテストを追加してください。
既存のテスト構成に合わせて、変更は最小限にしてください。
テスト追加後、PRを作成してください。
```

---

## 11. 安全運用メモ

最初から大きな実装を任せるより、以下の順番で慣らすのがおすすめです。

```text
1. README修正など小さい変更
2. 分析レポート作成
3. 小さなバグ修正
4. テスト追加
5. 機能実装
6. 大きめのリファクタ
```

依頼文に入れると安定する要素:

```text
どのファイルを編集してほしいか
何を作ってほしいか
PRを作ってほしいこと
テストを追加/実行してほしいこと
git statusを確認してほしいこと
変更を最小限にしてほしいこと
```

---

## 12. 最終チェックリスト

セットアップ後、以下を確認します。

```text
[ ] OpenCode GitHub Appをリポジトリに入れた
[ ] STEPFUN_API_KEY をGitHub Secretsに入れた
[ ] opencode.json をリポジトリ直下に置いた
[ ] .github/workflows/opencode.yml をmainに置いた
[ ] 必要なら .gitmodules を修正した
[ ] Issue本文ではなくコメント欄に /oc と書いた
[ ] Actionsが起動した
[ ] Checkout repository が成功した
[ ] Run opencode が成功した
[ ] ファイル変更が残った
[ ] PRが作成された
```

---

## 13. まとめ

今回の完成形:

```text
スマホ
↓
GitHub Issueコメントに /oc
↓
GitHub Actions
↓
OpenCode
↓
StepFun
↓
PR作成
```

一番重要な知見:

```text
OpenCodeにPRを作らせたいなら、
「ファイルを編集/作成して、変更を残して、PRを作成」と明示する。
```

これで、スマホからでもGitHubだけでAIエージェントに実装タスクを依頼できます。
