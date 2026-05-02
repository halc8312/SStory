---
title: "SStory - エターナル・アルカディア世界構築プロジェクト"
version: "1.0.0"
created: "2026-05-01"
last_updated: "2026-05-02"
author: "halc8312"
category: "project"
tags: ["project", "worldbuilding", "introduction"]
status: "stable"
---

# SStory - エターナル・アルカディア世界構築プロジェクト

ファンタジー世界「エターナル・アルカディア」の完全な世界観を構築するプロジェクトです。

詳細は [`world/README.md`](world/README.md) を参照してください。

## 世界の特徴

- **五大陆**: 中心となる五大陸と無数の浮島
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
```

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