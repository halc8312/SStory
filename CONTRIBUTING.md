# SStory への Contributing ガイド

SStory - エターナル・アルカディア世界構築プロジェクトへようこそ！

このプロジェクトは、TRPG・ゲーム・小説などクリエイティブな作品に利用可能な、詳細で一貫性のあるファンタジー世界観を共同で構築するオープンソースプロジェクトです。

## 📋 目次

1. [はじめに](#はじめに)
2. [開発プロセス](#開発プロセス)
3. [ファイル規則](#ファイル規則)
4. [メタデータ標準](#メタデータ標準)
5. [マークダウン規約](#マークダウン規約)
6. [用語統一](#用語統一)
7. [レビュープロセス](#レビュープロセス)
8. [よくある質問](#よくある質問)

---

## はじめに

### プロジェクトの哲学

SStoryは以下の原則に基づいています：

- **一貫性**: すべての設定は相互に関連し、矛盾がないこと
- **深度**: 背景にある歴史・文化・経済・政治を詳細に定義
- **有用性**: すべてのクリエイティブ活動に利用可能（商用可）
- **拡張性**: 基本設定は固定だが、自由に拡張可能

### ライセンス

CC BY-SA 4.0 - 商用利用可、改変・拡張自由、クレジット表示必須、継承義務あり

詳細: [LICENSE](LICENSE) ファイルを参照

---

## 開発プロセス

### 1. Issue で提案

新しい設定や修正を追加する前に、まずIssueを作成してください：

- **Bug/不整合**: データの矛盾や誤記を報告
- **Feature/新規設定**: 新しい国・種族・魔法などを提案
- **Enhancement/改善**: 既存コンテンツの拡充
- **Question/質問**: 世界観についての質問

**Issueテンプレート**に従って記入してください。

### 2. Fork して作業

1. このリポジトリをFork
2. ローカルでクローン
3. 新しいブランチ作成: `git checkout -b feature/your-feature-name`
4. 変更を加える

### 3. ローカルでの検証

変更前に、必ず以下を確認：

```bash
# 1. マークダウン構文チェック
npm run lint

# 2. リンク切れチェック
npm run links

# 3. スペルチェック
npm run spell

# 4. すべてのテスト
npm test
```

### 4. Pull Request 作成

- `main` ブランチへのPRを作成
- PRテンプレートに従って記入
- 変更内容の詳細を説明
- 関連するIssueをクローズ（`Closes #123`）

### 5. レビュー

- 少なくとも1人のレビューが必要
- 既存設定との矛盾がないか確認
- マークダウン構文チェック
- クロスリファレンス確認
- レビュー指摘に対応

### 6. マージ

レビュー承認後、自動的にマージされます。

---

## ファイル規則

### 命名規則

- **形式**: 小文字、ハイフン区切り (kebab-case)
- **例**: `creation-myth.md`, `central-region.md`, `zephyr-republic.md`
- **禁止**: スペース、大文字、アンダースコア、特殊文字

### ディレクトリ構造

```
world/
├── index.md                    # 世界目次 (必須)
├── README.md                   # プロジェクト概要 (必須)
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
│   ├── races-overview.md
│   └── (各レースごとのファイル)
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
│   ├── world-map.md
│   └── (地域別マップ)
├── npcs/                       # NPC (将来予定)
│   ├── leaders/
│   ├── historical/
│   └── adventurers/
├── rules/                      # TRPGルール (将来予定)
│   ├── core-mechanics.md
│   ├── combat.md
│   └── magic-casting.md
└── glossary.md                 # 用語集 (推奨)
```

**新規ファイル作成時**: 適切なサブディレクトリに配置。存在しない場合は作成可。

---

## メタデータ標準

### YAML Frontmatter (必須)

すべてのMarkdownファイルの先頭に、YAML frontmatterを記述してください：

```yaml
---
title: "ファイルタイトル"
version: "1.0.0"
created: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
author: "GitHub username"
contributors: []
category: "lore|geography|races|magic|politics|creatures|culture|economy|religion|maps|rules|npcs"
tags: ["tag1", "tag2", "tag3"]
status: "draft|review|stable"
---
```

### 各フィールド説明

| フィールド | 説明 | 例 |
|-----------|------|-----|
| `title` | ファイルのタイトル（日本語） | "創世神話" |
| `version` | バージョン（semver推奨） | "1.0.0" |
| `created` | 作成日（不明な場合は2026-05-01） | "2026-01-15" |
| `last_updated` | 最終更新日 | "2026-05-01" |
| `author` | 主作成者のGitHubユーザー名 | "halc8312" |
| `contributors` | 貢献者リスト（GitHub username） | ["user1", "user2"] |
| `category` | カテゴリ（上記から1つ選択） | "lore" |
| `tags` | タグ（5-10個のキーワード） | ["creation", "gods", "mythology"] |
| `status` | ステータス | "stable" |

### カテゴリ一覧

- `lore` - 歴史・神話
- `geography` - 地理・環境
- `races` - 種族・文化
- `magic` - 魔法・技術
- `politics` - 政治・社会
- `creatures` - 生物・モンスター
- `culture` - 文化・社会
- `economy` - 経済
- `religion` - 信仰
- `maps` - 地図
- `rules` - TRPGルール
- `npcs` - NPCデータ

---

## マークダウン規約

### 基本構文

```markdown
# 見出し1 (h1)
## 見出し2 (h2)
### 見出し3 (h3)
#### 見出し4 (h4)

**太字** - 強調
*斜体* - インプリシット

- リスト項目1
- リスト項目2
  - ネストされたリスト

1. 番号付きリスト1
2. 番号付きリスト2

> 引用ブロック

[リンクテキスト](../相対パス/file.md)

`インラインコード`

```コードブロック```
```

### 表の書き方

```markdown
| 列1 | 列2 | 列3 |
|-----|-----|-----|
| 値1 | 値2 | 値3 |
| 値4 | 値5 | 値6 |
```

**重要**: パイプ(`|`)の両側にスペースを入れる。列の長さは揃えなくてもOK（markdownlintが自動修正）。

### 内部リンク

**相対パスでリンク**:

```markdown
[魔法システム](../magic/system.md)
[関連: 種族一覧](../races/races-overview.md)
```

**同じディレクトリ内**:

```markdown
[隣のファイル](./neighboring-file.md)
```

**親ディレクトリ**:

```markdown
[トップへ](../index.md)
```

### 相互参照のルール

各ファイルの末尾に「関連項目」セクションを必ず追加：

```markdown
---
（frontmatter の後）
---

# 本文内容...

## 関連項目

- [世界概要](../index.md)
- [魔法システム](../magic/system.md)
- [種族一覧](../races/races-overview.md)
```

---

## 用語統一

### 種族名 (カタカナ統一)

| 日本語 | English | 説明 |
|--------|---------|------|
| 人間 | Human | 最も多い種族 |
| エルフ | Elf | 風の精霊と契約 |
| ドワーフ | Dwarf | 地の精霊と契約 |
| オーク | Orc | 火の精霊と契約 |
| ハーフリング | Halfling | 水の精霊と契約 |

### 精霊名 (完全統一)

| 元素 | 精霊名 (日本語) | 精霊名 (拉丁) | 説明 |
|------|----------------|---------------|------|
| 風 | 風の精霊ゼフ | Zephyrus | 風と自由の精霊 |
| 地 | 地の精霊グラン | Granus | 大地と堅実の精霊 |
| 火 | 火の精霊ピュロス | Pyros | 火と情熱の精霊 |
| 水 | 水の精霊ハイドロ | Hydro | 水と調和の精霊 |
| 月 | 月の精霊ルナ | Luna | 月と神秘の精霊 |

**⚠️ 重要**: 「ドリト」という表記は**存在しません**。誤記です。常に「グラン（Granus）」を使用。

### 大陸名

| 日本語 | English | 首都 |
|--------|---------|------|
| エルディア大陸 | Elida Continent | アストラリス |
| リュミエラ大陸 | Lumiera Continent | ルミエラシティ |
| カオス・リア大陸 | Chaos-Rea Continent | カオスキャピタル |
| アトランティス大陸 | Atlantis Continent | アトランティスポリス |
| グリモワール大陸 | Grimoire Continent | グリモワールシティ |

### 国名 (日本語優先)

12国家の正式名称（日本語）：

1. ゼフィア連合共和国 (Zephyr United Republic)
2. エルディア帝国 (Elida Empire)
3. リュミエラ王国 (Lumiera Kingdom)
4. カオス・リア連合 (Chaos-Rea Union)
5. アトランティス水邦 (Atlantis Aqua-Nation)
6. グリモワール魔法国家 (Grimoire Magi-State)
7. グランドリア鉱山連邦 (Grandoria Mining Federation)
8. ドワーフ堅牢城塞国家 (Dwarf Bastion)
9. オーク戦士団盟約 (Orc Warrior Pact)
10. ハーフリング交易連合 (Halfling Trade League)
11. 月妖精月光王国 (Moon Elf Moonlight Kingdom)
12. 中立精霊評議会 (Neutral Elemental Council)

**国際的には英語表記も可ですが、日本語表記を優先してください。**

### 年号

- **創世年 (Year of Creation)**: -10000年（四柱神が世界を創造）
- **精霊契約期 (Spirit Contract Period)**: -5000年〜0年
- **現代契約期 (Modern Era)**: 0年〜現在

**年号表記例**:
- 創世100年 = -9900年
- 現代100年 = 100年

**「アールディー（AD）」は使用しない**。単に「年」または「創世紀○年」を使用。

---

## レビュープロセス

### セルフレビュー (提出前)

- [ ] データに矛盾がないか（他のファイルと照合）
- [ ] マークダウン構文が正しいか（npm run lint 実行）
- [ ] リンク切れがないか（npm run links 実行）
- [ ] スペルミスがないか（npm run spell 実行）
- [ ] YAML frontmatter が正しいか
- [ ] カテゴリとタグが適切か
- [ ] 用語統一がされているか
- [ ] 関連ファイルへのリンクがあるか

### コミュニティレビュー

- レビュアーは少なくとも1人必要
- レビュアーは既存設定との矛盾を確認
- レビュアーはマークダウン構文をチェック
- レビュアーはクロスリファレンスを確認

### レビューコメント対応

- レビューコメントには48時間以内に返信
- 同意できる変更はすぐに適用
- 同意できない場合は議論し、合意形成
- 議論が平行線の場合はコアメンテナーが最終判断

---

## よくある質問

### Q: 新しい種族を追加したいです。どうすれば？

A: Issueで提案 → 承認後、`world/races/` に新規ファイル作成。他のファイル（魔法システム、国家など）への影響も考慮してください。

### Q: データに矛盾を見つけました。どうすれば？

A: すぐにIssue作成。`bug-report`テンプレートを使用。可能ならPRも作成してください。

### Q: マップを追加したいです。ファイル形式は？

A: `world/maps/` に配置。推奨形式: PNG (2000x2000px以上)、ソースファイル（.psd, .kra等）も同梱。SVGも可。

### Q: 他の世界観プロジェクトと競合しませんか？

A: SStoryはCC BY-SA 4.0で公開されており、商用利用・改変自由です。既存作品の設定を流用する場合は、明確に「インスパイア元」としてクレジットしてください。

### Q: 日本語以外でも書けますか？

A: 将来的には英語版も予定していますが、現時点では日本語が公式言語です。翻訳作業は別プロジェクトとして管理予定。

### Q: TRPGルールを追加したいです。

A: `world/rules/` ディレクトリを作成し、`core-mechanics.md`、`combat.md`、`magic-casting.md`などを追加してください。バランス調整にはテストプレイが必要です。

### Q: 画像を追加したいです。どこに置けば？

A: `world/images/` に適切なサブディレクトリを作成（例: `races/human/`, `maps/world/`）。README.md に画像の説明を記載。

### Q: バージョン番号はどう決める？

A: プロジェクト全体のバージョンは `README.md` と `world/README.md` で管理。ファイル個別のバージョンは frontmatter の `version` に記載。major.minor.patch 形式。

### Q: テストは必要ですか？

A: データの正確性検証スクリプト（`scripts/validate-consistency.js` など）の追加は大歓迎です。現在は手動レビューが中心です。

---

## 連絡先

- **リポジトリ**: https://github.com/halc8312/SStory
- **Issues**: バグ報告・提案
- **Discussions**: 質問・議論
- **メール**: （予定）

---

**ガイドライン最終更新**: 2026-05-01
**バージョン**: 1.0.0
**維持者**: halc8312 & SStory Community

よろしくお願いします！一緒に素晴らしい世界を創りましょう！
