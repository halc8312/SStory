# メタデータスキーマ定義

このディレクトリには、SStoryプロジェクトのすべてのMarkdownファイルに適用されるメタデータスキーマ（frontmatter）の定義が含まれています。

## 概要

SStoryの文書は6つの主要タイプに分類され、それぞれに必須・推奨フィールドが定義されています：

| タイプ | 説明 | 使用例 |
|--------|------|--------|
| `canon-document` | 世界観の正統な設定文書（公式設定） | lore, geography, races, magic, politics, creatures, culture, economy, religion, maps, transportation |
| `npc` | 非プレイヤーキャラクターのキャラクターシート | leaders/, historical/ |
| `rule` | TRPGルールブックのルール文書 | rules/ |
| `asset` | アセット（画像・音声・動画）の参照・管理文書 | images/ |
| `analysis` | 世界観やリポジトリの分析・評価レポート | evaluation/, analysis/ |
| `overview` | 概要・目次・案内文書 | index.md, README.md, 関係索引 |

## スキーマ構造

各スキーマファイルはYAML形式のJSON Schemaで、主に以下の要素を定義します：

- `type`: frontmatter全体のデータ型
- `allOf` / `$ref`: 共通スキーマの継承
- `required`: 必須フィールド一覧
- `properties`: 各フィールドの型、列挙値、説明
- `description`: タイプの説明と使用例

## 共通フィールド（全タイプ共通）

すべての文書に共通するフィールド：

| フィールド | 必須 | 説明 |
|------------|------|------|
| `type` | ○ | 文書タイプ（`canon-document`, `npc`, `rule`, `asset`, `analysis`, `overview`のいずれか） |
| `category` | ○ | 文書の内容カテゴリ（下記「カテゴリ一覧」参照） |
| `title` | ○ | 文書タイトル（日本語） |
| `status` | ○ | ステータス（`draft`, `review`, `stable`, `deprecated`） |
| `version` | ○ | セマンティックバージョン（例: `1.0.0`） |
| `created` | ○ | 作成日（`YYYY-MM-DD`） |
| `last_updated` | ○ | 最終更新日（`YYYY-MM-DD`） |
| `author` | ○ | 主な作成者（GitHub username） |
| `contributors` | 条件付き | 貢献者リスト（`canon-document`, `npc`, `rule` では必須） |
| `tags` | ○ | タグリスト（5〜10個程度） |

## カテゴリ一覧

`category`フィールドに使用できる値：

| カテゴリ | 説明 | 例 |
|-----------|------|------|
| `lore` | 歴史・神話・物語 | creation-myth.md, ancient-civilizations.md |
| `geography` | 地理・環境・気候 | continents.md, climate.md, regions/ |
| `races` | 種族・文化 | races-overview.md |
| `magic` | 魔法・技術・魔導器 | system.md, schools.md, artifacts.md |
| `politics` | 政治・国家・同盟 | kingdoms.md, alliances.md |
| `creatures` | 生物・モンスター | bestiary.md, legendary.md |
| `culture` | 文化・言語・暦 | languages.md, calendar.md |
| `economy` | 経済・交易・資源 | trade.md, resources.md |
| `religion` | 信仰・神々・教義 | pantheon.md, beliefs.md |
| `maps` | 地図・座標・航路 | world-map.md, coordinates.md |
| `transportation` | 交通・輸送・移動 | land-transportation.md, sea-transportation.md |
| `npcs` | キャラクター関連（カテゴリ） | npcs/leaders/, npcs/historical/ |
| `rules` | ルールブック関連（カテゴリ） | rules/core-mechanics.md, rules/combat.md |
| `overview` | 概要・目次・案内 | index.md, README.md |
| `assets` | 画像・音声・動画アセット | images/README.md |
| `analysis` | 分析・評価・調査レポート | evaluation/analysis_report.md |

**注意**:

- `category` は「内容の主題」を表します
- `type` は「文書の形式・構造」を表します
- 例: `world/npcs/leaders/halfling-trade-leader.md` は `category: "npcs"`, `type: "npc"`
- 例: `world/geography/geographical-analysis-report.md` は本来 `category: "analysis"`, `type: "analysis"` であるべき

## 使用法

### 1. 新規文書作成時

適切なスキーマファイルを参照し、必須フィールドをすべて含めてfrontmatterを作成してください。

```yaml
---
type: "canon-document"  # 文書タイプ
category: "lore"        # カテゴリ
title: "タイトル"
version: "1.0.0"
created: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
author: "GitHub username"
contributors: []
tags: ["tag1", "tag2", "tag3"]
status: "draft|review|stable"
---
```

### 2. 既存文書の修正時

対応するスキーマファイルを参照し、不足フィールドを追加、古いフィールドを更新してください。

### 3. スキーマの拡張

新たな文書タイプが必要な場合、`schemas/` ディレクトリに新しいYAMLファイルを追加し、このREADMEを更新してください。

## スキーマ一覧

- [`common.yaml`](common.yaml) - 全タイプ共通フィールド定義
- [`canon-document.yaml`](canon-document.yaml) - 正統世界観文書用
- [`npc.yaml`](npc.yaml) - NPCキャラクターシート用
- [`rule.yaml`](rule.yaml) - ルール文書用
- [`asset.yaml`](asset.yaml) - アセット参照文書用
- [`analysis.yaml`](analysis.yaml) - 分析レポート用
- [`overview.yaml`](overview.yaml) - 概要・目次・案内文書用

## バリデーション

CI/CDパイプラインでスキーマバリデーションを実施することを推奨します。自前のスクリプトや、`markdownlint`、`yamllint` などのツールを使用できます。

## 関連ファイル

- `CONTRIBUTING.md` - 貢獻ガイドライン（スキーマ使用法を記載）
- `STYLE_GUIDE.md` - スタイルガイド（メタデータ要件を記載）

---

**最終更新**: 2026-07-18
**バージョン**: 1.1.0
**著者**: opencode AI Assistant
