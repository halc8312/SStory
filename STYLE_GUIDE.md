# SStory スタイルガイド

## はじめに

このガイドは、SStoryプロジェクトにおける文書作成のためのスタイル標準を定義します。すべてのコントリビューターはこのガイドに従ってください。

## 1. 表記規則

### 1.1 全角/半角

- **全角**: 日本語文字, 句読点 (。、, ・)
- **半角**: 英数字, 記号 (・を除く), スペース
- **例**: `2026-05-01`, `1000km`, `1.5倍`

### 1.2 漢字の使用

- 常用漢字を基本に、読みやすさを優先
- 難読漢字は避ける (例: 「悠久」→「長い」)
- 固有名詞は正式表記 (例: 「エターナル・アルカディア」)

### 1.3 数字

- 単位付き: 半角数字 + 半角単位 (例: `10km`, `5kg`, `100年`)
- 千単位: `1,000` (カンマ区切り)
- 小数点: `.` (例: `3.14`)
- 範囲: `～` (全角波線) or `-` (半角ハイフン) どちらでも可 but 統一推奨 (`-` を推奨)

### 1.4 時間・日付

- 日付: `YYYY-MM-DD` (例: `2026-05-01`)
- 時間: `24時間表記` (例: `14:30`)
- 年号: `アールディー (AD)` 統一 (例: `アールディー1026年`)
-  Centuries: `第21世紀` (全角数字)

### 1.5 特殊記号

- マイナス: `-` (半角)
- ダッシュ: `—` (em-dash) または `-` ( hyphen) 可 but 統一
- 引用: `"` (半角) or `「」` (日本語 citation)

## 2. 用語統一リスト

### 2.1 種族名

| 統一表記 | 避ける表記 |
|----------|------------|
| 人間 | ヒューマン |
| エルフ | エルヴ |
| ドワーフ | ドワーフ |
| オーク | オーグ |
| ハーフリング | ホビット |

### 2.2 精霊名

| 元素 | 統一表記 | 別名 |
|------|----------|------|
| 風 | 風の精霊ゼフ | ゼフェル |
| 地 | 地の精霊グラン (Granus) | グランド, ドリト ❌ |
| 火 | 火の精霊ピュロス | パイロス |
| 水 | 水の精霊ハイドロ | ハイドロス |
| 月 | 月の精霊ルナ | ルナリア |

**注意**: `races-overview.md` の地の精霊は `グラン` に統一済み。`ドリト` は誤記。

### 2.3 大陸名

| 統一表記 | 英語 |
|----------|------|
| エリュシオン | Elysion |
| リュミエラ | Lumiera |
| カオス・リア | Chaos-Rea |
| アトランティス | Atlantis |
| グリモワール | Grimoire |

### 2.4 国家名 (日本語優先, 英語併記可)

- ゼフィア連合共和国 (Zephyr Federation)
- 月影エルフ王国 (Moon Elf Kingdom)
- 鉄山脉ドワーフ王国 (Dwarven Kingdom of Ironridge)
- 赤砂オーク連合 (Red Sand Orc Confederation)
- 翡翠王国 (Jade Kingdom)
- 銀盟共和国 (Silver Confederation)
- アトランティス (Atlantis)
- ハーフリング郷士国家連合 (Halfling Commonwealth)
- 嵐の都 (Stormhold)
- 時空の番人 (Chrono Guardians)
- 精霊協会 (Elemental Council)
- 自由都市国家群 (Free City States)

### 2.5 年号

- 統一: `アールディー` (AD: Arcadia Dating)
- 例: `アールディー1026年`
- 旧表記: `AD`, `西暦` は使用しない。

### 2.6 通貨

| 国家 | 統一表記 | 単位 |
|------|----------|------|
| ゼフィア連合 | ゼフィア金币 | 1金币 = 100銀貨 = 10,000銅貨 |
| 月影エルフ王国 | 月銀貨 | 1月銀貨 = 120銅貨 |
| ドワーフ王国 | 鉄貨 | 1鉄貨 = 150銅貨 |
| オーク連合 | 戦士の牙 | 1牙 = 80銀貨 |
| 翡翠王国 | 翡翠貨 | 1翡翠貨 = 1.2金币 |
| 銀盟共和国 | 銀貨 | 1銀貨 = 0.8金币 |
| アトランティス | 真珠 | 1真珠 = 5金币 |
| ハーフリング連合 | 地歩 | 1地歩 = 10銅貨 |
| 嵐の都 | 風紋 | 1風紋 = 2金币 |

### 2.7 魔法ランク

| ランク | 読み | 説明 |
|--------|------|------|
| Forbidden | 禁忌 | 使用禁止, 世界破壊級 |
| S+ | 特級 | 大陸規模 |
| S | 上級 | 都市規模 |
| A | 上級 | 大規模 |
| B | 中級 | 小队規模 |
| C | 初級 | 小規模 |
| D | 基礎 | 日常生活 |
| Cantrip | 特技 | 常時発動 |

## 3. 見出し構造

### 3.1 階層

```markdown
# 見出し1 (h1) - ファイル単位で1回だけ
## 見出し2 (h2) - 主要セクション
### 見出し3 (h3) - サブセクション
#### 見出し4 (h4) - 詳細
##### 見出し5 (h5) - 小項目
```

### 3.2 順序

- h1: ファイル名と一致させる
- h2: 主要カテゴリ (例: 歴史, 地理, 種族, 魔法, 政治, 経済, 宗教)
- h3: 各項目のサブカテゴリ
- h4以下: 必要に応じ

### 3.3 見出しの日本語

- 短く, 具体的に
- 例: `## 種族特性` (good), `## 種族について` (bad, 冗長)

## 4. 表のフォーマット

### 4.1 基本形

```markdown
| 列1 | 列2 | 列3 |
|------|------|------|
| データ1 | データ2 | データ3 |
| データ4 | データ5 | データ6 |
```

- ヘッダ行に `---` を含める
- 列は左揃えが基本 (特に指定なければ)
- 数字は右揃え可 ( `:---:` で中央, `---:` 右)

### 4.2 テーブル例

```markdown
| 項目 | 詳細 |
|------|------|
| **首都** | アストラリス |
| **人口** | 1,200万人 |
```

## 5. リンクの書き方

### 5.1 内部リンク

```markdown
[関連項目](../path/to/file.md)
[テキスト](../../other.md)
```

- 相対パスで記述
- リンク切れ防止のため、ファイル名は correct case

### 5.2 外部リンク

```markdown
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
```

- 完全なURL

### 5.3 anchor link

```markdown
[国家一覧](./kingdoms.md#1-ゼフィア連合共和国)
```

## 6. コードブロック

### 6.1 フェンスコード

````markdown
```yaml
key: value
```
````

- 言語指定を入れる (yaml, json, javascript, bash, mermaid, etc.)
- インデントは4 spaces

### 6.2 インラインコード

- ファイル名: `` `README.md` ``
- コマンド: `` `npm install` ``
- 値: `` `1d20` ``

## 7. 強調

- **太字**: `**太字**` (重要語句, 用語初出)
- *斜体*: `*斜体*` (強調, 外国語)
- `コード`: `` `code` `` (変数, 関数, ファイル名)

## 8. リスト

### 8.1 順序付きリスト

```markdown
1. 最初
2. 二番目
3. 三番目
```

- 数字とピリオドの後にスペース
- 連番でなくても可 (Markdownは自動数字)

### 8.2 順序なしリスト

```markdown
- アイテム1
- アイテム2
  - サブアイテム (インデント2 spaces or 4 spaces)
```

### 8.3 チェックリスト

```markdown
- [x] 完了
- [ ] 未完了
```

## 9. メタデータ (YAML Frontmatter)

すべてのMarkdownファイルに必須のfrontmatter。文書タイプに応じたスキーマは `schemas/` ディレクトリで定義されています。

### 9.1 共通必須フィールド（全タイプ共通）

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
- `category`: 内容カテゴリ（主題）。下記「カテゴリ一覧」参照
- `title`: ファイルのタイトル（日本語、プロジェクト名含まない）
- `version`: セマンティックバージョン（初期値 `1.0.0`）
- `created` / `last_updated`: `YYYY-MM-DD`（更新時は必ず `last_updated` を更新）
- `author`: 主な作成者（GitHub username）
- `tags`: 関連キーワード（5〜10個程度）
- `status`: `draft` (草案), `review` (レビュー中), `stable` (安定)

### 9.2 カテゴリ一覧

| カテゴリ | 説明 | 例 |
|----------|------|----|
| `lore` | 歴史・神話・物語 | creation-myth.md |
| `geography` | 地理・環境・気候 | continents.md |
| `races` | 種族・文化 | races-overview.md |
| `magic` | 魔法・技術・魔導器 | system.md |
| `politics` | 政治・国家・同盟 | kingdoms.md |
| `creatures` | 生物・モンスター | bestiary.md |
| `culture` | 文化・言語・暦 | languages.md |
| `economy` | 経済・交易・資源 | trade.md |
| `religion` | 信仰・神々・教義 | pantheon.md |
| `maps` | 地図・座標・航路 | world-map.md |
| `transportation` | 交通・輸送・移動 | land-transportation.md |
| `npcs` | NPCカテゴリ（文書の置く場所） | npcs/leaders/ |
| `rules` | ルールカテゴリ（文書の置く場所） | rules/ |
| `overview` | 概要・目次・案内 | index.md |
| `assets` | アセット参照 | images/README.md |
| `analysis` | 分析・評価レポート | evaluation/ |

### 9.3 タイプ別追加フィールド

各文書タイプに応じて、以下の追加フィールドが必要です。完全な定義は [`schemas/`](schemas/README.md) を参照。

**canon-document**（正統世界観文書）:
```yaml
type: "canon-document"
contributors: []  # 貢献者GitHub usernameリスト
previous_version: "1.0.0"  # (optional)
changlog: []  # (optional) 変更履歴
```

**npc**（NPCキャラクターシート）:
```yaml
type: "npc"
npc_type: "leader|historical|adventurer|commoner|deity|monster-npc"
race: "human|elf|dwarf|orc|halfling|aquatic-elf|elemental|deity|other"
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
    description: "..."
    alt_text: "..."
    status: "completed|planned"
```

**analysis**（分析レポート）:
```yaml
type: "analysis"
analysis_type: "world-analysis|repository-analysis|data-consistency|content-audit"
scope: "分析対象範囲"
base_files: ["world/lore/*.md"]
ratings:
  overall: 8.0
```

**overview**（概要・目次）:
```yaml
type: "overview"
document_kind: "index|readme|toc|navigation|landing"
summary: "短い概要（1-2文）"
```

### 9.4 命名規則

- 小文字、ハイフン区切り (kebab-case)
- 例: `creation-myth.md`, `central-region.md`
- 日本語ファイル名は避ける（英語推奨、ただし日本語内容可）

### 9.5 ファイル配置とtype/categoryの対応

| タイプ | カテゴリ | 配置先 | 例 |
|--------|----------|--------|----|
| canon-document | lore | world/lore/ | creation-myth.md |
| canon-document | geography | world/geography/ | continents.md |
| canon-document | races | world/races/ | races-overview.md |
| canon-document | magic | world/magic/ | system.md |
| canon-document | politics | world/politics/ | kingdoms.md |
| canon-document | creatures | world/creatures/ | bestiary.md |
| canon-document | culture | world/culture/ | languages.md |
| canon-document | economy | world/economy/ | trade.md |
| canon-document | religion | world/religion/ | pantheon.md |
| canon-document | maps | world/maps/ | world-map.md |
| canon-document | transportation | world/transportation/ | land-transportation.md |
| npc | npcs | world/npcs/ | leaders/xxx.md |
| rule | rules | world/rules/ | core-mechanics.md |
| asset | assets | world/images/ | README.md |
| analysis | analysis | evaluation/ | analysis_report.md |
| overview | overview | world/ | index.md, README.md |

**ルール**:
- 正統世界観文書は `type: canon-document`, `category` はそのテーマ
- NPCは `type: npc`, `category: npcs`（ファイルは world/npcs/ に配置）
- ルールは `type: rule`, `category: rules`（ファイルは world/rules/ に配置）
- アセット管理は `type: asset`, `category: assets`
- 分析レポートは `type: analysis`, `category: analysis`（world/ ではなく evaluation/ に配置）
- 概要・目次は `type: overview`, `category: overview`

## 10. 引用と出典

### 10.1 引用

```markdown
> 引用文。出典を明記。
```

### 10.2 出典明記

世界観の着想元がある場合は、`出典:` を記載:

```markdown
出典: ギリシア神話の四大元素を参考
```

## 11. 画像の取り扱い

- 現在画像なし (後日追加予定)
- 追加時は `world/images/` に格納
- 相対パスで参照: `![説明](../images/file.png)`
- 代替テキスト必須: `alt="説明"`

## 12. 共通ミスと回避策

| ミス | 修正後 |
|------|--------|
| `kmkm²` | `km²` |
| `ドリト` (地精霊) | `グラン` |
| `アールディー1026年` (epoch未定義) | `calendar.md` 参照, 明示 |
| `AD` | `アールディー` |
| `human` | `人間` |
| `elf` | `エルフ` |

## 13. 英語表記のルール

- 固有名詞は日本語優先, 英語は補足
- 例: `ゼフィア連合共和国 (Zephyr Federation)`
- 初出時のみ英語併記, 2回目以降は日本語のみ

## 14. ファイル名とパス

### 14.1 命名規則

- 小文字, ハイフン区切り (kebab-case)
- 例: `creation-myth.md`, `central-region.md`
- 接頭辞なし (年号などはファイル名に含めない)

### 14.2 ディレクトリ構造

```
world/
├── index.md
├── README.md
├── lore/
├── geography/
├── races/
├── magic/
├── politics/
├── creatures/
├── culture/
├── economy/
├── religion/
├── maps/
├── npcs/
│   ├── leaders/
│   └── historical/
├── rules/
└── images/
```

## 15. ライセンス表記

すべてのファイルは **CC BY-SA 4.0** ライセンスです。

```markdown
ライセンス: CC BY-SA 4.0
商用利用: 可 (クレジット必須)
改変: 可 (継承義務あり)
```

リポジトリルートの `LICENSE` ファイルを参照。

## 16. その他のガイドライン

- **一行の長さ**: 100文字程度を目安に折り返し
- **段落**: 1段落1主題, 空行で区切る
- **引用**: 長文引用は避け, 要約して出典リンク
- ** emoji**: 使用可 but 控えめに (✅ ❌ ⚠️ 程度)
- **コメント**: Markdown内にコメント書かない (HTMLコメント可 but 削除対象)

---

**最終更新**: 2026-05-01
**バージョン**: 1.0.0
**著者**: halc8312
