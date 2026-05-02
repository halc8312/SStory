# SStory Repository - ファイル構造詳細

## ディレクトリツリー (2026-05-01 更新)

```
SStory/                                    # プロジェクトルート
├── .git/                                   # Gitメタデータ (自動生成)
├── .github/
│   ├── workflows/
│   │   ├── opencode.yml                    # GitHub Action 設定
│   │   └── lint.yml                        # Lint CI (新規)
│   └── ISSUE_TEMPLATE/                     # Issueテンプレート (新規)
│       ├── bug-report.md
│       ├── feature-request.md
│       └── worldbuilding-suggestion.md
├── world/                                  # 世界観コンテンツ
│   ├── index.md                            # 世界目次 (55行) ✅ frontmatter
│   ├── README.md                           # プロジェクト概要 (275行) ✅ frontmatter
│   │
│   ├── lore/                               # 歴史・神話
│   │   ├── creation-myth.md                # 創世神話 (53行) ✅ frontmatter
│   │   ├── ancient-civilizations.md        # 古代文明 ✅ frontmatter
│   │   └── timelines/
│   │       ├── main-timeline.md            # 歴史年表 ✅ frontmatter
│   │       └── visual-timeline.md          # 可視化年表 (Mermaid) 新規 ✅
│   │
│   ├── geography/                          # 地理・環境
│   │   ├── continents.md                   # 大陸概要 (122行) ✅ frontmatter
│   │   ├── climate.md                      # 気候と生態系 ✅ frontmatter
│   │   └── regions/
│   │       └── central-region.md           # 中央地域詳細 ✅ frontmatter
│   │
│   ├── races/                              # 種族・文化
│   │   └── races-overview.md               # 五大種族詳細 (233行) ✅ frontmatter, 修正済
│   │
│   ├── magic/                              # 魔法・技術
│   │   ├── system.md                       # 魔法系統 (292行) ✅ frontmatter
│   │   ├── schools.md                      # 魔法学校 ✅ frontmatter
│   │   └── artifacts.md                    # 魔導器 ✅ frontmatter
│   │
│   ├── politics/                           # 政治・社会
│   │   ├── kingdoms.md                     # 国家一覧 (459行) ✅ frontmatter, 修正済
│   │   └── alliances.md                    # 同盟と戦争 ✅ frontmatter
│   │
│   ├── creatures/                          # 生物・モンスター
│   │   ├── bestiary.md                     # モンスター図鑑 ✅ frontmatter
│   │   └── legendary.md                    # 伝説の生物 ✅ frontmatter
│   │
│   ├── culture/                            # 文化・社会
│   │   ├── languages.md                    # 言語 ✅ frontmatter
│   │   └── calendar.md                     # 暦 (269行) ✅ frontmatter
│   │
│   ├── economy/                            # 経済
│   │   ├── trade.md                        # 通貨と交易 (370行) ✅ frontmatter, link修正
│   │   └── resources.md                    # 資源 ✅ frontmatter
│   │
│   ├── religion/                           # 信仰
│   │   ├── pantheon.md                     # 神々の pantheon (438行) ✅ frontmatter
│   │   └── beliefs.md                      # 信仰体系 ✅ frontmatter
│   │
│   ├── maps/                               # 地図
│   │   ├── world-map.md                    # 世界地図参照 ✅ frontmatter
│   │   ├── world-map.svg                   # 世界地図 (SVG) 新規 ✅
│   │   └── continents/
│   │       ├── elysion.svg                   # エリュシオン 新規 ✅
│   │       ├── lumiera.svg                 # リュミエラ 新規 ✅
│   │       ├── chaosrea.svg                # カオス・リア 新規 ✅
│   │       ├── atlantis.svg                # アトランティス 新規 ✅
│   │       └── grimoire.svg                # グリモワール 新規 ✅
│   │
│   ├── npcs/                               # NPC (新規)
│   │   ├── leaders/                        # 指導者 (12ファイル) ✅
│   │   │   ├── zephyr-president.md
│   │   │   ├── moon-elf-queen.md
│   │   │   ├── dwarf-king.md
│   │   │   ├── orc-warlord.md
│   │   │   ├── jade-queen.md
│   │   │   ├── silver-chairman.md
│   │   │   ├── atlantis-queen.md
│   │   │   ├── halfling-elder.md
│   │   │   ├── stormhold-wind-guide.md
│   │   │   ├── chrono-guardian.md
│   │   │   ├── elemental-council-speaker.md
│   │   │   └── freecity-representative.md
│   │   └── historical/                     # 歴史的人物 (7ファイル) ✅
│   │       ├── astrael.md
│   │       ├── selenia-moonfell.md
│   │       ├── gurum-mechanica.md
│   │       ├── cain-union.md
│   │       ├── rayel.md
│   │       ├── brock-ironheart.md
│   │       └── gron-smasher.md
│   │
│   ├── rules/                              # TRPGルール (新規)
│   │   ├── core-mechanics.md               # 基本メカニクス ✅
│   │   ├── combat.md                       # 戦闘ルール ✅
│   │   ├── magic-casting.md                # 魔法発動 ✅
│   │   ├── bestiary-stats.md               # モンスター統計 ✅
│   │   └── character-creation.md           # キャラクター作成 ✅
│   │
│   ├── images/                             # 画像資産 (計画中)
│   │   └── README.md
│   │
│   └── glossary.md                         # 用語集 (新規) ✅ frontmatter
│
├── CONTRIBUTING.md                         # コントリビューションガイド 新規 ✅
├── ROADMAP.md                              # 開発ロードマップ 新規 ✅
├── STYLE_GUIDE.md                          # スタイルガイド 新規 ✅
├── README.md                               # ルートドキュメント (52行) ✅ frontmatter
├── opencode.json                           # opencode AI設定 (30行)
├── opencode_stepfun_github_manual.md       # 手動設定ガイド
├── package.json                            # npm scripts (新規) ✅
├── .markdownlint.json                      # markdownlint設定 (新規) ✅
└── .github/
    └── workflows/
        └── lint.yml                        # CI lint (新規) ✅
```

---

## ファイル統計

### 行数ランキング (読取済みファイル)

| ファイル | 行数 | カテゴリ |
|----------|------|----------|
| `world/politics/kingdoms.md` | 459 | 政治 |
| `world/religion/pantheon.md` | 438 | 宗教 |
| `world/economy/trade.md` | 370 | 経済 |
| `world/magic/system.md` | 292 | 魔法 |
| `world/races/races-overview.md` | 233 | 種族 |
| `world/README.md` | 275 | 総合 |
| `world/geography/continents.md` | 122 | 地理 |
| `world/lore/creation-myth.md` | 53 | 歴史 |
| `world/index.md` | 55 | 目次 |
| `README.md` (root) | 52 | 概要 |

**読取済み総行数**: 2,749行
**未読ファイル**: 12ファイル (推定1,500-2,000行)
**プロジェクト総行数 (推定)**: 4,500-5,000行

---

## コンテンツカバレッジ分析 (2026-05-01 更新)

### ✅ 完成度高 (80-100%) - 32ファイル
- [x] 創世神話
- [x] 古代文明
- [x] 歴史年表 + 可視化年表 (Mermaid)
- [x] 五大陸の概要 + 各大陸詳細地図 (SVG)
- [x] 五大種族の詳細 + frontmatter
- [x] 魔法システム全体 + 学校 + 魔導器
- [x] 十二国家の詳細プロフィール
- [x] 同盟と戦争
- [x] モンスター図鑑 + 伝説の生物
- [x] 言語 + 暦 (暦は年号体系定義済)
- [x] 経済システム（通貨・GDP・貿易）+ 資源
- [x] 神々と宗教体系 (pantheon + beliefs)
- [x] プロジェクト全体README + 目次
- [x] **TRPGコアルール** (5ファイル: core-mechanics, combat, magic-casting, bestiary-stats, character-creation) ★新規
- [x] **主要NPC** (12国の指導者 12ファイル) ★新規
- [x] **歴史的人物** (7ファイル) ★新規
- [x] **用語集** (glossary.md) ★新規
- [x] **ワールドマップ** (world-map.svg + 5大陸SVG) ★新規

### ⚠️ 部分完了 (30-80%) - 0ファイル
- [ ] 画像資産 (まだ空, コンセプトアート未導入)

### ❌ 未着手 (0-30%) - 0ファイル
- [ ] 英語翻訳 (未着手)
- [ ] シナリオ例 (未着手)
- [ ] その他拡張コンテンツ

---

**総ファイル数**: world/ 配下 約55ファイル (Markdown 44 + SVG 6 + 他)
**総行数 (推定)**: 12,000+ 行 (評価時5,000行 → +7,000行追加)
**カバレッジ**: **世界観コア 80%+ 完了**, TRPGルール 100% 完了, NPC 100% 完了, 地図 100% 完了.

---

## クロスリファレンス状況

### 内部リンクの完全性

```
[世界概要](index.md)                    ✅ 存在
├─ [大陸概要](geography/continents.md)  ✅ 存在
├─ [種族・文化](races/)                 ✅ 存在
│  └─ races-overview.md                 ✅ 存在
├─ [魔法・技術](magic/)                 ✅ 存在
│  ├─ system.md                         ✅ 存在
│  ├─ schools.md                        ✅ 存在 (未読)
│  └─ artifacts.md                      ✅ 存在 (未読)
├─ [政治・社会](politics/)              ✅ 存在
│  ├─ kingdoms.md                       ✅ 存在
│  └─ alliances.md                      ✅ 存在 (未読)
├─ [生物・モンスター](creatures/)       ✅ 存在
│  ├─ bestiary.md                       ✅ 存在 (未読)
│  └─ legendary.md                      ✅ 存在 (未読)
├─ [文化・社会](culture/)               ✅ 存在
│  ├─ languages.md                      ✅ 存在 (未読)
│  └─ calendar.md                       ✅ 存在 (未読)
├─ [経済](economy/)                     ✅ 存在
│  ├─ trade.md                          ✅ 存在
│  └─ resources.md                      ✅ 存在 (未読)
└─ [信仰・宗教](religion/)              ✅ 存在
   ├─ pantheon.md                       ✅ 存在
   └─ beliefs.md                        ✅ 存在 (未読)
```

**リンク切れ**: 0 (目次から全てのファイルが存在する)

---

## メタデータ分析

### メタデータ標準の欠如

**問題**: 全ファイルに作成者・作成日・更新日・バージョン情報が記述されていない

**現状例**:
- `world/index.md` のみに「最終更新: 2026-05-01」「バージョン: 1.0.0」「作成者: halc8312」
- 他の28ファイルはすべてメタデータなし

**推奨**: YAML frontmatter の標準化

```yaml
---
title: "Creation Myth"
version: "1.0.2"
created: "2026-01-15"
last_updated: "2026-05-01"
author: "halc8312"
contributors: []
category: "lore"
tags: ["creation", "gods", "mythology"]
status: "stable"  # or "draft", "review"
---
```

---

## データ重複と単一ソース真理

### 重複情報

| 情報 | 出現ファイル | 問題 |
|------|--------------|------|
| 五大陸一覧 | index.md, geography/continents.md | 完全一致ならOK |
| 五元素精霊 | magic/system.md, races-overview.md | 名称・特性が一致（要確認） |
| 四柱神 | lore/creation-myth.md, religion/pantheon.md | 完全一致ならOK |
| 十二国家 | politics/kingdoms.md, index.md | 一部のみ重複 |
| 精霊契約システム | 複数ファイル | 概念が分散 |

**課題**: 単一ソース真理（Single Source of Truth）が確立されていない
**推奨**: マスターデータファイルを作成（例: `world/data/` ディレクトリ）

---

## 品質チェックリスト

### ✅ 満たされている項目
- [x] 日本語として自然な表現
- [x] 見出し階層の適切さ
- [x] コードブロックの適切な使用
- [x] 表の整列
- [x] 内部リンクの存在
- [x] 読点の適切な使用
- [x] 段落の分離

### ⚠️ 改善が必要な項目
- [ ] メタデータの標準化
- [ ] ファイルごとの最終更新日記載
- [ ] 用語集の作成
- [ ] 索引の作成
- [ ] 相互参照の完全化
- [ ] 図表の挿入（画像）
- [ ] 出典の明記（インスパイア元）

### ❌ 欠如している項目
- [ ] 自動テスト
- [ ] スペルチェック
- [ ] リンク切れチェック
- [ ] ユニットテスト（データ）
- [ ] ビルド検証
- [ ] アクセシビリティチェック

---

## ツール推奨セット

### ドキュメント品質向上
1. **markdownlint** - Markdown構文チェック
2. **markdown-link-check** - リンク切れ検出
3. **cspell** - スペルチェック（日本語辞書対応）
4. **write-good** - 文章の改善提案

### 一貫性維持
1. **vale** - スタイルガイドチェッカー
2. **proselint** - ライティングチェック
3. **textlint** - 自然言語処理チェック（日本語対応）

### データ管理
1. **json-schema** - データ構造検証
2. **ajv** - JSONスキーマバリデータ
3. **yaml-lint** - YAML構文チェック（メタデータ用）

---

## アクションアイテム（技術的負債）

### Phase 1: 即時修正（1週間）
- [ ] 地の精霊名称統一（ドリト→グラン）
- [ ] 単位誤記修正（kmkm²→km²）
- [ ] 年号体系の明確化
- [ ] CONTRIBUTING.md作成
- [ ] メタデータ標準化ガイド作成

### Phase 2: 短期改善（1ヶ月）
- [ ] GitHub Actions に lint ステップ追加
- [ ] 全ファイルに YAML frontmatter 追加
- [ ] 用語集（glossary.md）作成
- [ ] ファイルテンプレート作成
- [ ] クロスリファレンス完全化

### Phase 3: 中期改善（3ヶ月）
- [ ] データ検証スクリプト作成
- [ ] 自動ビルドパイプライン構築
- [ ] ドキュメントサイト構築（GitHub Pages）
- [ ] 国際化対応基盤（i18n）
- [ ] API/JSONエクスポート機能

---

## 付録: ファイルごとの状態

| ファイル | 状態 | 行数 | 優先度 | 備考 |
|----------|------|------|--------|------|
| world/index.md | ✅ 完成 | 55 | 高 | メタデータ不足 |
| world/README.md | ✅ 完成 | 275 | 高 | メタデータ不足 |
| world/lore/creation-myth.md | ✅ 完成 | 53 | 中 | クロス参照OK |
| world/geography/continents.md | ✅ 完成 | 122 | 中 | データ豊富 |
| world/races/races-overview.md | ⚠️ 不整合あり | 233 | 高 | 地精霊名不一致 |
| world/magic/system.md | ✅ 完成 | 292 | 高 | 詳細なシステム |
| world/politics/kingdoms.md | ✅ 完成 | 459 | 高 | 単位誤記あり |
| world/economy/trade.md | ✅ 完成 | 370 | 中 | 年号体系不明 |
| world/religion/pantheon.md | ✅ 完成 | 438 | 中 | 良質 |
| README.md | ✅ 完成 | 52 | 中 | 簡潔 |
| opencode.json | ✅ 完成 | 30 | 低 | 設定適切 |

**残り12ファイル**: 読取・評価が必要（優先度低）

---

**作成日**: 2026-05-01
**更新日**: 2026-05-01
**バージョン**: 1.0.0
**ステータス**: 草案
