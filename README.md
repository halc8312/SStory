---
title: "SStory - エターナル・アルカディア世界構築プロジェクト"
version: "1.1.0"
created: "2026-05-01"
last_updated: "2026-07-18"
author: "halc8312"
category: "project"
tags: ["project", "worldbuilding", "introduction"]
status: "stable"
---

# SStory - エターナル・アルカディア世界構築プロジェクト

ファンタジー世界「エターナル・アルカディア」の完全な世界観を構築するプロジェクトです。

詳細は [`world/README.md`](world/README.md) を参照してください。

## 世界の特徴

- **五大陸**: 中心となる五大陸と無数の浮島
- **精霊契約システム**: すべての生命が精霊と魔法契約
- **十種族**: 人間、エルフ、ドワーフ、オーク、ハーフリングなど
- **四柱神**: 世界を創った原初の神々
- **10,000年の歴史**: 三つの大文明の興亡

## クイックスタート

```bash
# 世界設定を読む
cat world/index.md

# 歴史を知る
cat world/lore/creation-myth.md

# 地理を学ぶ
cat world/geography/continents.md

# 世界設定ポータル（GitHub Pages）をローカルで起動
node scripts/run-python.js -m http.server 8000 --directory docs
# http://localhost:8000/ を開く
```

---

## 🌐 世界設定ポータル (GitHub Pages)

このリポジトリには、**エターナル・アルカディア設定資料館**（世界設定ポータル）が含まれています。

### 目的

- 世界設定資料を体系的に閲覧できるWebサイトを提供
- GitHub Pages 上で公開、誰でも無料でアクセス可能
- 初めて訪れる読者にも世界観を理解しやすい構成

### サイトURL

**公開URL**: `https://halc8312.github.io/SStory/`

### GitHub Pages 設定方法

このリポジトリでは、`main` ブランチの `/docs` フォルダを公開元にしています。

**設定手順**:

1. GitHub のリポジトリページを開く
2. **Settings** → **Pages** を開く
3. **Build and deployment** を `Deploy from a branch` に変更
4. **Branch** を `main` に選択
5. **Folder** を `/docs` に選択
6. **Save** をクリック
7. 数分待つと `https://halc8312.github.io/SStory/` でサイトが公開されます

### 現在の実装方式

**v0.1 静的HTMLポータル**（本リリース）:

- ビルド不要の静的HTML/CSS/JS
- `docs/` フォルダを GitHub Pages の公開元として直接配置
- MkDocs / GitHub Actions は使用せず
- Pages デプロイ用 GitHub Actions ワークフローは削除済み (`pages.yml`, `jekyll-gh-pages.yml`)

**注意**: 本リポジトリは **Project Pages** として `https://halc8312.github.io/SStory/` に公開されます。
ユーザーサイトURL (`https://halc8312.github.io/`) ではなく、プロジェクトサイトURLを使用してください。
`docs/` 静的公開方式では、Pages用 GitHub Actions は不要です。

### サイト構成（v0.1）

```
docs/
├── .nojekyll                       # Jekyll 処理を無効化
├── index.html                      # ホームページ
├── 404.html                        # エラーページ
├── assets/                         # 静的リソース
│   ├── css/
│   │   └── style.css               # 羊皮紙風デザイン
│   └── js/
│       └── main.js                 # 軽量スクリプト
├── pages/                          # 各ページ
│   ├── world.html                  # 世界概要
│   ├── geography.html              # 地理
│   ├── transportation.html         # 交通
│   ├── maps.html                   # 地図ギャラリー
│   ├── map-data.html               # Map Data 仕様
│   └── roadmap.html                # 開発ロードマップ
└── data/
    └── map/
        └── README.md               # Map Data 説明
```

### ローカルでの確認

```bash
node scripts/run-python.js -m http.server 8000 --directory docs
# ブラウザで http://localhost:8000/ を開く
```

### 採用技術（v0.1）

- 静的HTML / CSS / JavaScript（Vanilla）
- モバイル対応・レスポンシブデザイン
- 相対パスによるProject Pages対応

### 現在のステータス

- ✅ **ポータル基盤**: 静的HTMLポータル、地図ギャラリー、Map Data公開コピー
- ✅ **インタラクティブマップ v1**: 現行安定版（Leaflet、POI、Web版ルート検索）
- 🧪 **インタラクティブマップ v2**: 試験版・次世代候補（v1は引き続き現行）
- ⏳ **今後**: Markdown閲覧導線の強化、タイルマップ、世界設定データベース化

詳細な開発ロードマップ: [docs/pages/roadmap.html](./docs/pages/roadmap.html)

### 正史資料との関係

- **本ポータル**は `world/` 配下の世界設定Markdownへのナビゲーションです。カノンは `CANON_POLICY.md` の条件を満たす文書に限ります
- 詳細な設定は `world/` 以下のファイルを直接参照してください
- Map Data は `world/map-data/data/` の編集上の正本JSONを参照します。JSON自体が独立したカノンという意味ではありません

---

## ディレクトリ構造

```
world/
├── index.md                    # 世界構築の目次・案内 (type: overview)
├── README.md                   # プロジェクト概要 (type: overview)
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
│   │   ├── zephyr-president.md
│   │   ├── moon-elf-queen.md
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
```

## ライセンス

CC BY-SA 4.0 - 商用利用可能、クレジット表示必須、継承義務あり。詳細は [LICENSE](LICENSE) ファイルを参照してください。

## 利用ポリシー

コンテンツの利用ガイドラインについては [USAGE_POLICY.md](USAGE_POLICY.md) を、公式設定（カノン）の定義については [CANON_POLICY.md](CANON_POLICY.md) を参照してください。

## コントリビューション

ご参加いただける方は、[CONTRIBUTING.md](CONTRIBUTING.md) のガイドラインを参照してください。
Pull Request大歓迎です！世界観の拡張、修正、追加をぜひお願いします。
