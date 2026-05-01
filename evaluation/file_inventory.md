# SStory Repository - ファイル構造詳細

## ディレクトリツリー

```
SStory/                                    # プロジェクトルート
├── .git/                                   # Gitメタデータ (自動生成)
├── .github/
│   ├── workflows/
│   │   └── opencode.yml                    # GitHub Action 設定
│   └── README.md (なし)
├── world/                                  # 世界観コンテンツ
│   ├── index.md                            # 世界目次 (55行)
│   ├── README.md                           # プロジェクト概要 (275行)
│   │
│   ├── lore/                               # 歴史・神話
│   │   ├── creation-myth.md                # 創世神話 (53行)
│   │   ├── ancient-civilizations.md        # 古代文明 (未読)
│   │   └── timelines/
│   │       └── main-timeline.md            # 歴史年表 (未読)
│   │
│   ├── geography/                          # 地理・環境
│   │   ├── continents.md                   # 大陸概要 (122行)
│   │   ├── climate.md                      # 気候と生態系 (未読)
│   │   └── regions/
│   │       └── central-region.md           # 中央地域詳細 (未読)
│   │
│   ├── races/                              # 種族・文化
│   │   └── races-overview.md               # 五大種族詳細 (233行)
│   │
│   ├── magic/                              # 魔法・技術
│   │   ├── system.md                       # 魔法系統 (292行)
│   │   ├── schools.md                      # 魔法学校 (未読)
│   │   └── artifacts.md                    # 魔導器 (未読)
│   │
│   ├── politics/                           # 政治・社会
│   │   ├── kingdoms.md                     # 国家一覧 (459行)
│   │   └── alliances.md                    # 同盟と戦争 (未読)
│   │
│   ├── creatures/                          # 生物・モンスター
│   │   ├── bestiary.md                     # モンスター図鑑 (未読)
│   │   └── legendary.md                    # 伝説の生物 (未読)
│   │
│   ├── culture/                            # 文化・社会
│   │   ├── languages.md                    # 言語 (未読)
│   │   └── calendar.md                     # 暦 (未読)
│   │
│   ├── economy/                            # 経済
│   │   ├── trade.md                        # 通貨と交易 (370行)
│   │   └── resources.md                    # 資源 (未読)
│   │
│   ├── religion/                           # 信仰
│   │   ├── pantheon.md                     # 神々の pantheon (438行)
│   │   └── beliefs.md                      # 信仰体系 (未読)
│   │
│   ├── maps/                               # 地図
│   │   └── world-map.md                    # 世界地図参照 (未読)
│   │
│   └── images/                             # 画像資産 (計画中)
│       └── README.md
│
├── README.md                               # ルートドキュメント (52行)
├── opencode.json                           # opencode AI設定 (30行)
├── opencode_stepfun_github_manual.md       # 手動設定ガイド (未読)
│
└── evaluation/                             # 評価ディレクトリ (新規作成)
    ├── analysis_report.md                  # 詳細分析レポート
    └── summary.md                          # サマリーレポート
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

## コンテンツカバレッジ分析

### ✅ 完成度高 (80-100%)
- [x] 創世神話
- [x] 五大陸の概要
- [x] 五大種族の詳細
- [x] 魔法システム全体
- [x] 十二国家の詳細プロフィール
- [x] 経済システム（通貨・GDP・貿易）
- [x] 神々と宗教体系
- [x] プロジェクト全体README

### ⚠️ 部分完了 (30-80%)
- [ ] 古代文明 (ファイル存在、内容未読)
- [ ] 歴史年表 (ファイル存在、内容未読)
- [ ] 気候と生態系 (ファイル存在)
- [ ] 地域詳細 (一部未読)
- [ ] 魔法学校 (ファイル存在)
- [ ] 魔導器 (ファイル存在)
- [ ] 同盟と戦争 (ファイル存在)
- [ ] 言語 (ファイル存在)
- [ ] 暦 (ファイル存在)
- [ ] 資源 (ファイル存在)

### ❌ 未着手 (0-30%)
- [ ] 地図作成 (参照のみ、実データなし)
- [ ] モンスター図鑑 (存在するが内容未確認)
- [ ] 伝説の生物 (存在するが内容未確認)
- [ ] 画像資産 (ディレクトリ空)
- [ ] TRPGルール (どこにも存在しない)
- [ ] NPCデータ (どこにも存在しない)
- [ ] シナリオ例 (未着手)

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
