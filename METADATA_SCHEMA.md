# メタデータスキーマ定義書

**バージョン**: 2.1.0
**最終更新**: 2026-07-18
**著者**: opencode AI Assistant

## 概要

この文書は、SStoryプロジェクト（エターナル・アルカディア世界構築）におけるすべてのMarkdownファイルのメタデータ（YAML frontmatter）スキーマを定義します。

## 設計哲学

### type と category の責務分離

- **`type`**: 文書の**構造・目的**（どのような形式の文書か）
  - `canon-document`: 世界観の公式設定文書
  - `npc`: キャラクターシート
  - `rule`: ゲームルール文書
  - `asset`: アセット参照管理文書
  - `analysis`: 分析・評価レポート
  - `overview`: 概要・目次・案内文書

- **`category`**: 文書の**内容主題**（何についての文書か）
  - `lore`, `geography`, `races`, `magic`, `politics`, `creatures`, `culture`, `economy`, `religion`, `maps`, `transportation`
  - `npcs`, `rules`, `overview`, `assets`, `analysis`（これらはタイプと一致しない場合もある）

**例**:

- `world/lore/creation-myth.md`: `type: canon-document`, `category: lore`
- `world/npcs/leaders/halfling-trade-leader.md`: `type: npc`, `category: npcs`
- `world/geography/geographical-analysis-report.md`（移動後）: `type: analysis`, `category: analysis`

### 正本境界（Canon Boundary）

- **正統文書（Canon）**: `world/` 配下で `type: canon-document` かつ `status: stable` の文書のみが、現在の世界観の公式設定
- **非正統文書**: `draft` / `review` の文書、および NPC、ルール、アセット、分析、概要はプロジェクト資料ではあるが「世界観の事実」としては扱われない
- **Map Data**: `world/map-data/data/*.json` は機械可読データの編集上の正本。`confidence: canon` はstableなカノン文書に根拠があることを示し、JSON自体を独立したカノンにはしない。`docs/data/map/*.json` は生成された公開用コピー
- **Language**: ルート直下の `Language/` は言語設計の実験領域で非カノン。採用する設定は `world/culture/languages.md` などへ反映し、stable化する

## 文書タイプ一覧

### 1. canon-document（正統世界観文書）

**目的**: エターナル・アルカディア世界の公式設定を記述する文書

**対象**:

- world/lore/（歴史・神話）
- world/geography/（地理・環境）
- world/races/（種族・文化）
- world/magic/（魔法・技術）
- world/politics/（政治・国家）
- world/creatures/（生物・モンスター）
- world/culture/（文化・言語・暦）
- world/economy/（経済・交易）
- world/religion/（信仰）
- world/maps/（地図）
- world/transportation/（交通）

**特徴**:

- 客観的事実を記述
- 複数人での共同編集を想定
- `contributors` フィールドで貢献者を明記
- 変更履歴（`changelog`）の記述推奨

**必須フィールド**:

```yaml
type: "canon-document"
category: "<カテゴリ>"
title: "..."

version: "1.0.0"
created: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
author: "GitHub username"
contributors: []  # 貢献者リスト
tags: ["..."]
status: "draft|review|stable"
```

**推奨フィールド**:

- `previous_version`: 前バージョン番号
- `changelog`: 変更履歴リスト
- `reviewed_by`: レビュー担当者リスト
- `based_on`: 引用元・参考資料

### 2. npc（NPCキャラクターシート）

**目的**: 非プレイヤーキャラクターの公式キャラクターシート

**対象**: world/npcs/leaders/, world/npcs/historical/, world/npcs/adventurers/, world/npcs/unique/

**特徴**:

- TRPG形式のキャラクターデータ
- 能力値、クラス、精霊契約度を構造化
- `npc_type` で種別を明記

**必須追加フィールド**:

```yaml
type: "npc"
npc_type: "leader|historical|adventurer|scholar|unique|commoner|deity|monster-npc"
race: "human|elf|dwarf|orc|halfling|aquatic-elf|triton|half-elf|half-orc|elemental|deity|other"
age: 55  # 数値または "eternal", "unknown"
alignment: "lawful-good|neutral-good|..."
class: "Fighter (Champion) 15 / Bard 3"
spirit_contract:
  wind: 40   # 0-100%
  earth: 60
  fire: 10
  water: 60
  moon: 20
```

**推奨フィールド**:

- `subrace`: 亜種（例: 月影エルフ）
- `title`: 肩書き
- `position`: 役職
- `affiliation`: 所属組織
- `location`: 現在地
- `appearance`, `personality`, `goals`, `flaws`: 描写
- `abilities`, `equipment`, `relationships`, `wealth`, `history`, `notes`

### 3. rule（ルール文書）

**目的**: TRPGゲームルールの定義

**対象**: world/rules/

**特徴**:

- システムタイプと複雑度を明記
- 関連ルールへの相互参照

**必須追加フィールド**:

```yaml
type: "rule"
rule_type: "core|combat|magic|character|bestiary|equipment|setting"
system: "custom|dnd5e|pathfinder2e|other"
complexity: "beginner|intermediate|advanced|expert"
related_rules: ["..."]
```

### 4. asset（アセット参照）

**目的**: 画像・音声・動画などのメディアアセット管理

**対象**: world/images/README.md

**特徴**:

- 各アセットのメタデータ（ライセンス、クレジット、形式）を管理
- 使用文書の追跡

**代表的な追加フィールド（任意）**:

```yaml
type: "asset"
asset_type: "image|audio|video|3d-model|font|other"
items:
  - filename: "world-map.png"
    description: "..."
    alt_text: "..."
    status: "completed|planned|in-progress"
    license: "CC BY-SA 4.0"
related_documents: ["world/maps/world-map.md"]
```

### 5. analysis（分析レポート）

**目的**: 世界観やリポジトリの調査・分析結果の記録

**対象**: evaluation/analysis/, evaluation/ 以下

**特徴**:

- 体系的調査・評価
- 発見事項の構造化
- 評価スコアと推奨アクション

**代表的な追加フィールド（任意）**:

```yaml
type: "analysis"
analysis_type: "world-analysis|repository-analysis|data-consistency|content-audit|technical-debt|feature-evaluation"
scope: "分析対象範囲"
base_files: ["..."]
methodology: "..."
findings: []  # リスト形式
metrics: {}   # 数値指標
ratings:      # 評価スコア
  overall: 8.0
  completeness: 0.85
recommendations: []  # 推奨アクション
```

### 6. overview（概要・目次）

**目的**: プロジェクト・ディレクトリの案内・目次

**対象**: world/index.md, world/README.md

**代表的な追加フィールド（任意）**:

```yaml
type: "overview"
document_kind: "index|readme|toc|navigation|landing"
summary: "短い概要（1-2文）"
```

**推奨フィールド**:

- `directory_structure`: ディレクトリ構造説明
- `getting_started`: スタートガイド手順
- `usage_examples`: 使用例
- `contact`: 連絡先情報
- `license`: ライセンス表記

## 共通フィールド詳細

| フィールド | 必須 | 型 | 説明 |
|------------|------|-----|------|
| `type` | ○ | string | 文書タイプ（6種） |
| `category` | ○ | string | 内容カテゴリ（16種） |
| `title` | ○ | string | タイトル（日本語） |
| `version` | ○ | string | セマンティックバージョン（X.Y.Z） |
| `created` | ○ | string | 作成日（YYYY-MM-DD） |
| `last_updated` | ○ | string | 最終更新日 |
| `author` | ○ | string | 主作成者（GitHub username） |
| `contributors` | 条件付き | array | 貢献者リスト（canon-document, npc, rule は必須） |
| `tags` | ○ | array[str] | タグ（5-10個推奨） |
| `status` | ○ | string | `draft`, `review`, `stable`, `deprecated` |

`deprecated` は履歴参照用に保持された文書を示し、現在のカノンには含めません。

## カテゴリ一覧

| カテゴリ | 説明 | 使用例 | 推奨type |
|----------|------|--------|----------|
| `lore` | 歴史・神話・物語 | creation-myth.md | canon-document |
| `geography` | 地理・環境・気候 | continents.md | canon-document |
| `races` | 種族・文化 | races-overview.md | canon-document |
| `magic` | 魔法・技術 | system.md | canon-document |
| `politics` | 政治・国家 | kingdoms.md | canon-document |
| `creatures` | 生物・モンスター | bestiary.md | canon-document |
| `culture` | 文化・言語・暦 | languages.md | canon-document |
| `economy` | 経済・交易 | trade.md | canon-document |
| `religion` | 信仰・神々 | pantheon.md | canon-document |
| `maps` | 地図・座標 | world-map.md | canon-document |
| `transportation` | 交通・輸送 | land-transportation.md | canon-document |
| `npcs` | NPC文書のカテゴリ | npcs/leaders/ | npc |
| `rules` | ルール文書のカテゴリ | rules/ | rule |
| `overview` | 概要・目次 | index.md | overview |
| `assets` | アセット参照 | images/README.md | asset |
| `analysis` | 分析レポート | evaluation/ | analysis |

## ファイル配置ガイドライン

```
SStory/
├── world/
│   ├── index.md                      # type: overview, category: overview
│   ├── README.md                     # type: overview, category: overview
│   ├── lore/                         # canon-document, category: lore
│   ├── geography/                    # canon-document, category: geography
│   ├── races/                        # canon-document, category: races
│   ├── magic/                        # canon-document, category: magic
│   ├── politics/                     # canon-document, category: politics
│   ├── creatures/                    # canon-document, category: creatures
│   ├── culture/                      # canon-document, category: culture
│   ├── economy/                      # canon-document, category: economy
│   ├── religion/                     # canon-document, category: religion
│   ├── maps/                         # canon-document, category: maps
│   ├── transportation/               # canon-document, category: transportation
│   ├── npcs/                         # type: npc, category: npcs
│   │   ├── leaders/
│   │   ├── historical/
│   │   └── adventurers/
│   ├── rules/                        # type: rule, category: rules
│   │   ├── core-mechanics.md
│   │   ├── combat.md
│   │   └── ...
│   └── images/                       # type: asset, category: assets
│       └── README.md
├── evaluation/
│   └── analysis/                     # type: analysis, category: analysis
│       └── geographical-analysis-report.md
├── schemas/                          # スキーマ定義ファイル（本リポジトリの定義書）
│   ├── README.md
│   ├── common.yaml
│   ├── canon-document.yaml
│   ├── npc.yaml
│   ├── rule.yaml
│   ├── asset.yaml
│   ├── analysis.yaml
│   └── overview.yaml
├── CONTRIBUTING.md                   # 貢獻ガイドライン（スキーマ使用法）
└── STYLE_GUIDE.md                   # スタイルガイド（メタデータ節）
```

## 移行ガイドライン

### 既存ファイルの更新

1. **タイプの判定**: 文書の目的から適切な `type` を選択
2. **カテゴリの判定**: 内容主題から適切な `category` を選択
3. **不足フィールドの追加**: スキーマ要件を満たすようにfrontmatterを更新
4. **値の正規化**: 既存の `category` 値が `overview` や `assets` の場合は `type` フィールドを追加

### よくある修正パターン

#### パターンA: overviewカテゴリの修正

**Before**:

```yaml
---
title: "..."
category: "overview"
---
```

**After**:

```yaml
---
type: "overview"
category: "overview"
title: "..."
document_kind: "index"  # or "readme"
summary: "..."
---
```

#### パターンB: assetsカテゴリの修正

**Before**:

```yaml
---
title: "..."
category: "assets"
---
```

**After**:

```yaml
---
type: "asset"
category: "assets"
title: "..."
asset_type: "image"
items: []
---
```

#### パターンC: analysis文書のworld/内からの移動

**Before**: `world/geography/geographical-analysis-report.md`

```yaml
---
category: "geography"
---
```

**After**: `evaluation/analysis/geographical-analysis-report.md`

```yaml
---
type: "analysis"
category: "analysis"
analysis_type: "world-analysis"
base_files: [...]
---
```

#### パターンD: NPC文書の標準化

**Before** (minimal):

```yaml
---
title: "..."
category: "npcs"
---
```

**After**:

```yaml
---
type: "npc"
category: "npcs"
title: "..."
npc_type: "leader"
race: "..."
age: 55
alignment: "..."
class: "..."
spirit_contract:
  wind: 40
  earth: 60
  ...
---
```

## バリデーション

各スキーマファイルはYAML形式で定義されており、自動バリデーションに使用できます。

推奨ツール:

- `yamllint`: YAML構文チェック
- カスタムスクリプト: スキーマ適合性チェック
- GitHub Actions: PR時の自動検証

## 変更履歴

| バージョン | 日付 | 変更内容 | 作成者 |
|------------|------|-----------|--------|
| 1.0.0 | 2026-05-01 | 初期版（CONTRIBUTING.md内定義） | halc8312 |
| 2.0.0 | 2026-05-02 | スキーマシステム導入、schemas/ ディレクトリ新設、全ファイル更新 | opencode AI Assistant |
| 2.1.0 | 2026-07-18 | statusとカノン境界を統一し、Map Data・Languageの扱いを明文化 | Codex |

## 参考

- `schemas/README.md`: スキーマディレクトリの使用法
- `CONTRIBUTING.md`: 貢獻ガイドライン
- `STYLE_GUIDE.md`: スタイルガイド

---

**この文書は CC BY-SA 4.0 ライセンスの下で公開されています。**
