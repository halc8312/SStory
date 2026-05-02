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
  ├── index.md                    # 世界目次 (type: overview, category: overview)
  ├── README.md                   # プロジェクト概要 (type: overview, category: overview)
  ├── lore/                       # 歴史・神話 (canon-document)
  │   ├── creation-myth.md
  │   ├── ancient-civilizations.md
  │   └── timelines/
  │       └── main-timeline.md
  ├── geography/                  # 地理・環境 (canon-document)
  │   ├── continents.md
  │   ├── climate.md
  │   └── regions/
  │       └── central-region.md
  ├── races/                      # 種族・文化 (canon-document)
  │   └── races-overview.md
  ├── magic/                      # 魔法・技術 (canon-document)
  │   ├── system.md
  │   ├── schools.md
  │   └── artifacts.md
  ├── politics/                   # 政治・社会 (canon-document)
  │   ├── kingdoms.md
  │   └── alliances.md
  ├── creatures/                  # 生物・モンスター (canon-document)
  │   ├── bestiary.md
  │   └── legendary.md
  ├── culture/                    # 文化・社会 (canon-document)
  │   ├── languages.md
  │   └── calendar.md
  ├── economy/                    # 経済 (canon-document)
  │   ├── trade.md
  │   └── resources.md
  ├── religion/                   # 信仰 (canon-document)
  │   ├── pantheon.md
  │   └── beliefs.md
  ├── maps/                       # 地図 (canon-document)
  │   └── world-map.md
  ├── transportation/             # 交通 (canon-document)
  │   ├── index.md
  │   ├── land-transportation.md
  │   ├── sea-transportation.md
  │   ├── air-transportation.md
  │   ├── historical-transportation.md
  │   └── regional-transportation.md
  ├── npcs/                       # NPC (type: npc の文書が入る)
  │   ├── leaders/               # 現役指導者
  │   │   ├── halfling-trade-leader.md
  │   │   └── ...
  │   ├── historical/            # 歴史的人物
  │   │   ├── rayel.md
  │   │   └── ...
  │   └── adventurers/           # 冒険者
  │       └── ...
  ├── rules/                      # TRPGルール (type: rule の文書)
  │   ├── core-mechanics.md
  │   ├── combat.md
  │   ├── magic-casting.md
  │   ├── bestiary-stats.md
  │   └── character-creation.md
  └── images/                     # 画像アセット (type: asset の管理文書)
      └── README.md
evaluation/                        # 分析レポート (type: analysis)
  ├── analysis_report.md
  ├── summary.md
  └── ...
schemas/                           # メタデータスキーマ定義
  ├── README.md
  ├── common.yaml
  ├── canon-document.yaml
  ├── npc.yaml
  ├── rule.yaml
  ├── asset.yaml
  ├── analysis.yaml
  └── overview.yaml
```

**ディレクトリガイドライン**:

- **`world/`**: 世界観の正統な設定文書（`canon-document`タイプ）と、`overview`タイプの目次・READMEを含む
  - サブディレクトリはテーマ別に分かれている
  - 各ファイルは `category` をそのディレクトリのテーマに合わせる
  - NPCとルールは中身が `type: npc` / `type: rule` だが、ファイルは `world/npcs/` と `world/rules/` に置く

- **`evaluation/`**: 分析・評価レポート（`type: analysis`）を置く
  - 世界観そのものではなく、世界観やリポジトリに関する分析
  - 例: `geographical-analysis-report.md` は本来ここに移動すべき

- **`schemas/`**: メタデータスキーマ定義（本システムの定義書）
  - 各スキーマYAMLファイルを参照してfrontmatter作成
  - `schemas/README.md`に使用法を記載


### メタデータ (必須)

各Markdownファイルの先頭にYAML frontmatterを記述してください。文書タイプに応じたスキーマは `schemas/` ディレクトリで定義されています。

#### 共通必須フィールド（全タイプ共通）

```yaml
---
type: "canon-document|npc|rule|asset|analysis|overview"
category: "lore|geography|races|magic|politics|creatures|culture|economy|religion|maps|transportation|npcs|rules|overview|assets|analysis"
title: "ファイルタイトル"
version: "1.0.0"
created: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
author: "GitHub username"
tags: ["tag1", "tag2", "tag3"]
status: "draft|review|stable"
---
```

**項目説明**:
- `type`: 文書タイプ（構造・目的）。[詳細](schemas/README.md)
- `category`: 内容カテゴリ（主題）。[カテゴリ一覧](#カテゴリ一覧)参照
- `title`: ファイルのタイトル（日本語、プロジェクト名含まない）
- `version`: セマンティックバージョン（初期値 `1.0.0`）
- `created`: 作成日（不明な場合は `2026-05-01`）
- `last_updated`: 最終更新日（更新時必ず更新）
- `author`: 主な作成者（GitHub username）
- `tags`: 関連キーワード（5〜10個程度）
- `status`: 現状（`draft`=草案, `review`=レビュー中, `stable`=安定）

#### カテゴリ一覧

| カテゴリ | 説明 | 例 |
|----------|------|----|
| `lore` | 歴史・神話・物語 | creation-myth.md, ancient-civilizations.md |
| `geography` | 地理・環境・気候 | continents.md, climate.md |
| `races` | 種族・文化 | races-overview.md |
| `magic` | 魔法・技術・魔導器 | system.md, artifacts.md |
| `politics` | 政治・国家・同盟 | kingdoms.md, alliances.md |
| `creatures` | 生物・モンスター | bestiary.md, legendary.md |
| `culture` | 文化・言語・暦 | languages.md, calendar.md |
| `economy` | 経済・交易・資源 | trade.md, resources.md |
| `religion` | 信仰・神々・教義 | pantheon.md, beliefs.md |
| `maps` | 地図・座標・航路 | world-map.md, coordinates.md |
| `transportation` | 交通・輸送・移動 | land-transportation.md |
| `npcs` | NPCカテゴリ（文書の入る場所） | npcs/leaders/, npcs/historical/ |
| `rules` | ルールカテゴリ（文書の入る場所） | rules/core-mechanics.md |
| `overview` | 概要・目次・案内 | index.md, README.md |
| `assets` | アセット参照 | images/README.md |
| `analysis` | 分析・評価レポート | evaluation/analysis_report.md |

#### タイプ別追加フィールド

各文書タイプに応じて、以下の追加フィールドが必要です：

**canon-document**（正統世界観文書）:
```yaml
type: "canon-document"
contributors: []  # 貢献者GitHub usernameリスト
```

**npc**（NPCキャラクターシート）:
```yaml
type: "npc"
npc_type: "leader|historical|adventurer|commoner|deity|monster-npc"
race: "human|elf|dwarf|orc|halfling|aquatic-elf|elemental|deity|other"
age: 55  # または "eternal", "unknown"
alignment: "lawful-good|neutral-good|chaotic-good|..."
class: "Fighter (Champion) 15 / Bard 3"
spirit_contract:
  wind: 40   # 0-100%
  earth: 60
  fire: 10
  water: 60
  moon: 20
```

**rule**（ルール文書）:
```yaml
type: "rule"
rule_type: "core|combat|magic|character|bestiary|equipment|setting"
system: "custom|dnd5e|pathfinder2e|other"
complexity: "beginner|intermediate|advanced|expert"
related_rules: ["character-creation.md", "combat.md"]
```

**asset**（アセット参照）:
```yaml
type: "asset"
asset_type: "image|audio|video|3d-model|font|other"
items:
  - filename: "world-map.png"
    description: "五大陸と浮島群を表現した世界地図"
    alt_text: "エターナル・アルカディア世界地図"
    status: "completed|planned"
    license: "CC BY-SA 4.0"
```

**analysis**（分析レポート）:
```yaml
type: "analysis"
analysis_type: "world-analysis|repository-analysis|data-consistency|content-audit"
scope: "分析対象範囲"
base_files: ["world/lore/*.md", "world/geography/*.md"]
findings: []  # 発見事項リスト
ratings:      # 評価スコア
  overall: 8.0
  completeness: 0.75
```

**overview**（概要・目次）:
```yaml
type: "overview"
document_kind: "index|readme|toc|navigation|landing"
summary: "短い概要（1-2文）"
```

各タイプの完全なスキーマ定義は [`schemas/`](schemas/README.md) ディレクトリを参照してください。

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
- [ ] マークダウン構文チェック済み（`npm run lint` パス）
- [ ] リンク切れなし（`npm run links` パス）
- [ ] スペルチェック済み（`npm run spell` パス）
- [ ] Frontmatter検証済み（`npm run frontmatter` パス）
- [ ] 一貫性チェック済み（`npm run consistency` パス）
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

## CI（継続的インテグレーション）パイプライン

本项目では、すべてのプルリクエストに対して自動的に以下のCIチェックが実行されます：

### チェック一覧

1. **文法チェック（Grammar）**: `markdownlint` でマークダウン構文を検証
2. **リンクチェック（Link Integrity）**: `markdown-link-check` で内部リンク切れを検証
3. **スペルチェック（Spelling）**: `cspell` で日本語スペルを検証
4. **Frontmatter検証**: `scripts/validate-frontmatter.js` でYAML frontmatterの必須項目・形式を検証
5. **一貫性チェック**: `scripts/validate-consistency.js` で用語統一・データ整合性を検証

すべてのチェックが合格しないとマージできません。詳細は [`.github/workflows/lint.yml`](../.github/workflows/lint.yml) を参照してください。

ローカルでも同じコマンドで実行可能です：
```bash
npm run validate
```

---

### セキュリティとメンテナンス

CIパイプラインでは、外部GitHub Actionのバージョンをピン留め（`actions/checkout@v4`, `actions/setup-node@v4`, `streetsidesoftware/cspell-action@v1`, `anomalyco/opencode/github@v1.14.31`）し、最小限の権限で実行します。詳細は各ワークフローファイルを参照してください。

---

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
