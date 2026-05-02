# SStory への Contributing ガイド

## はじめに

SStory - エターナル・アルカディア世界構築プロジェクトへようこそ！
このプロジェクトは、誰でも自由に利用・拡張できるファンタジー世界観を提供します。

## 開発プロセス

1. **Issueで提案**: 新規設定追加や修正をIssueで議論
2. **Forkして作業**: 自分のForkにクローンして変更
3. **Pull Request作成**: 変更をPRにまとめる
4. **Review後マージ**:  maintainerによるレビュー後にマージ

## ファイル規則

### 命名規則

- 小文字、ハイフン区切り (kebab-case)
- 例: `creation-myth.md`, `central-region.md`
- 日本語ファイル名は避ける（英語推奨、ただし日本語内容可）

### ディレクトリ構造

```
world/
  ├── index.md                    # 世界目次
  ├── README.md                   # プロジェクト概要
  ├── lore/                       # 歴史・神話
  │   ├── creation-myth.md
  │   ├── ancient-civilizations.md
  │   └── timelines/
  │       └── main-timeline.md
  ├── geography/                  # 地理・環境
  │   ├── continents.md
  │   ├── climate.md
  │   └── regions/
  │       └── central-region.md
  ├── races/                      # 種族・文化
  │   └── races-overview.md
  ├── magic/                      # 魔法・技術
  │   ├── system.md
  │   ├── schools.md
  │   └── artifacts.md
  ├── politics/                   # 政治・社会
  │   ├── kingdoms.md
  │   └── alliances.md
  ├── creatures/                  # 生物・モンスター
  │   ├── bestiary.md
  │   └── legendary.md
  ├── culture/                    # 文化・社会
  │   ├── languages.md
  │   └── calendar.md
  ├── economy/                    # 経済
  │   ├── trade.md
  │   └── resources.md
  ├── religion/                   # 信仰
  │   ├── pantheon.md
  │   └── beliefs.md
  ├── maps/                       # 地図
  │   └── world-map.md
  ├── npcs/                       # NPC (将来拡張)
  │   ├── leaders/
  │   └── historical/
  ├── rules/                      # TRPGルール (将来拡張)
  │   ├── core-mechanics.md
  │   ├── combat.md
  │   ├── magic-casting.md
  │   ├── bestiary-stats.md
  │   └── character-creation.md
  └── images/                     # 画像資産
```

### メタデータ (必須)

各Markdownファイルの先頭にYAML frontmatterを記述してください：

```yaml
---
title: "ファイルタイトル"
version: "1.0.0"
created: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
author: "GitHub username"
category: "lore|geography|races|magic|politics|creatures|culture|economy|religion|maps|npcs|rules"
tags: ["tag1", "tag2", "tag3"]
status: "draft|review|stable"
---
```

**項目説明**:
- `title`: ファイルのタイトル（日本語）
- `version`: コンテンツバージョン（初期値 1.0.0）
- `created`: 作成日（不明な場合は 2026-05-01）
- `last_updated`: 最終更新日
- `author`: 主な作成者（GitHub username）
- `category`: 上記いずれかのカテゴリ
- `tags`: 関連キーワード（5〜10個程度）
- `status`: 現状（draft=草案, review=レビュー中, stable=安定）

### マークダウン規約

- 見出し: `#` 〜 `#####` まで適切に階層化
- 表: `|` で整列、ヘッダ行に `---` を含む
- リンク: `[テキスト](../相対パス/file.md)`
- 強調: `**太字**`, `*斜体*`
- コードブロック: ``` で囲み、言語指定（該当する場合）
- 水平線: `---` で区切り

### 相互参照

関連ファイルがある場合は、文末に「関連項目」セクションを追加：

```markdown
**関連項目**: [関連ページ名](../path/to/file.md) | [別の関連](../other.md)
```

### 表記統一

以下の用語は統一して使用してください：

- **種族名**: 人間、エルフ、ドワーフ、オーク、ハーフリング（カタカナ統一）
- **精霊名**:
  - 風の精霊ゼフ (Zeph)
  - 地の精霊グラン (Granus)
  - 火の精霊ピュロス (Pyros)
  - 水の精霊ハイドロ (Hydro)
  - 月の精霊ルナ (Luna)
- **大陸名**: エリュシオン、リュミエラ、カオス・リア、アトランティス、グリモワール
- **国家名**: 日本語表記優先、英語併記可（例: ゼフィア連合共和国 (Zephyr Union)）
- **年号**: アールディー (AD, Arcadia Dating) 統一。例: アールディー1026年
- **通貨**: ゼフィア金币、月銀貨、鉄貨、戦士の牙、翡翠貨、銀貨、真珠、地歩、風紋

## レビュープロセス

- すべてのPRは少なくとも1人のレビューが必要です
- 既存設定との矛盾がないか確認してください
- マークダウン構文チェック（CIが自動実行）
- クロスリファレンスの確認
- メタデータの更新（作成日・更新日）

### レビュー基準

1. **一貫性**: 既存の世界観と矛盾していないか
2. **完全性**: 必要なセクション（歴史、文化、経済など）が網羅されているか
3. **形式**: マークダウン規約に従っているか
4. **メタデータ**: frontmatterが正しく記入されているか
5. **リンク**: 内部リンク切れがないか

## 品質チェックリスト

PRを作成する前に、以下を確認してください：

- [ ] 既存設定との矛盾なし
- [ ] マークダウン構文チェック済み（`markdownlint` パス）
- [ ] リンク切れなし（`markdown-link-check` パス）
- [ ] スペルチェック済み（`cspell` パス）
- [ ] メタデータ更新済み（`created`/`last_updated`）
- [ ] カテゴリ・tags適切
- [ ] 関連項目リンク記載
- [ ] 表記統一（用語集を参照）
- [ ] 読みやすい構成（見出し、段落）

## よくある間違いと回避法

### 1. データ不整合
- **問題**: 同じ精霊・種族・国家の名称がファイル間で不一致
- **回避**: 変更前に `grep` で全ファイル検索、統一する

### 2. リンク切れ
- **問題**: 相対パスが間違っている
- **回避**: ローカルでリンクをクリックして確認、CIチェックを待つ

### 3. メタデータ漏れ
- **問題**: frontmatter未記入または項目不足
- **回避**: テンプレートをコピペしてから記入

### 4. 年号・単位の統一
- **問題**: 「アールディー」と「AD」が混在、単位「kmkm²」など
- **回避**: 用語集とスタイルガイドを参照

## 質問がある場合

- GitHub Issues: バグ報告・質問
- GitHub Discussions: 議論・提案
- プロジェクトWiki: 詳細情報

## ライセンス

CC BY-SA 4.0 - 商用利用可、クレジット表示必須、継承義務あり

詳細: https://creativecommons.org/licenses/by-sa/4.0/

## 連絡先

- リポジトリ: https://github.com/halc8312/SStory
- メンテナー: @halc8312

---

**ガイドライン最終更新**: 2026-05-01
**バージョン**: 1.0.0
