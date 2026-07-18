# 世界概要

**エターナル・アルカディア（Eternal Arcadia）**は、魔法と技術が融合した中世ファンタジー世界です。

## 世界の基本情報

| 項目 | 内容 |
|------|------|
| **世界名** | エターナル・アルカディア |
| **別名** | 永遠の楽園 |
| **年齢** | 10,000年以上の歴史 |
| **居住種族** | 十種族（人間、エルフ、ドワーフ、オーク、ハーフリングなど） |
| **主要要素** | 精霊契約、元素魔法、古代文明遺産 |

## 五大陸

### 1. エリュシオン（中央大陸）

- **特徴**: 政治・経済の中心
- **首都**: アストラリス（ゼフィア連合共和国）
- **主要都市**: ゼフィア、リュミエラ、カオス・リア
- **気候**: 温暖湿潤

### 2. リュミエラ（東大陸）

- **特徴**: 神秘と月魔法の大地
- **主要都市**: 月影エルフ王国
- **気候**: 亜熱帯

### 3. カオス・リア（南大陸）

- **特徴**: 砂漠と炎の大地
- **主要都市**: 赤砂オーク連合
- **気候**: 砂漠気候

### 4. アトランティス（西大陸）

- **特徴**: 氷と海の大陸
- **主要都市**: アトランティス女王領
- **気候**: 冷涼湿潤

### 5. グリモワール（北大陸）

- **特徴**: 時空と禁忌の大地
- **主要都市**: 時空番人会
- **気候**: 寒帯

## 世界の特徴

### 🌙 二重月

- **セレーネ（青月）**と**ルナ（白月）**が夜空を照らす
- 月の満ち欠けが魔法力に影響

### ⚡ 元素脈動

- 大地から元素のエネルギーが定期的に噴出
- 各地に「元素結節点」が存在

### ⏳ 時空の歪み

- グリモワールなど特定地域では時間の流れが異なる
- タイムラグ现象が発生することも

### 🤝 精霊共存

- すべての生命が**精霊と契約**によって魔法能力を発揮
- 五元素（風・地・火・水・月）の精霊が存在

## 主要設定リンク

### 地理・環境

- [大陸概要（詳細）](geography.md)
- [地域詳細](https://github.com/halc8312/SStory/tree/main/world/geography/regions)
- [気候と生態系](https://github.com/halc8312/SStory/blob/main/world/geography/climate.md)

### 歴史

- [創世神話](https://github.com/halc8312/SStory/blob/main/world/lore/creation-myth.md)
- [歴史年表](https://github.com/halc8312/SStory/blob/main/world/lore/timelines/main-timeline.md)
- [古代文明](https://github.com/halc8312/SStory/blob/main/world/lore/ancient-civilizations.md)

### 種族

- [五大種族の詳細](races.md)
- [各NPCプロフィール](https://github.com/halc8312/SStory/tree/main/world/npcs)

### 魔法

- [魔法系統と体系](magic.md)
- [魔法学校](https://github.com/halc8312/SStory/blob/main/world/magic/schools.md)
- [魔導器アイテム](https://github.com/halc8312/SStory/blob/main/world/magic/artifacts.md)

### 政治

- [国家一覧](politics.md)
- [同盟と戦争](https://github.com/halc8312/SStory/blob/main/world/politics/alliances.md)

### 経済

- [通貨と交易](economy.md)
- [資源分布](https://github.com/halc8312/SStory/blob/main/world/economy/resources.md)

### 交通

- [交通網全体](transportation.md)
- [街道・航路詳細](https://github.com/halc8312/SStory/tree/main/world/transportation)

### 地図

- [世界地図](https://github.com/halc8312/SStory/blob/main/world/maps/world-map.md)
- [各大陸地図](https://github.com/halc8312/SStory/tree/main/world/maps/continents)

## 正史資料へのアクセス

このポータルサイトは、**正史設定資料へのナビゲーション**です。

詳細な設定は、リポジトリ内の `world/` ディレクトリ以下のMarkdownファイルを直接ご覧ください。

```
world/
├── index.md                    # このサイトのトップレベル目次
├── README.md                   # プロジェクト全体概要
├── lore/                       # 歴史・神話
├── geography/                  # 地理・環境
├── races/                      # 種族・文化
├── magic/                      # 魔法・技術
├── politics/                   # 政治・社会
├── creatures/                  # 生物・モンスター
├── culture/                    # 文化・社会
├── economy/                    # 経済
├── religion/                   # 信仰
├── maps/                       # 地図
├── transportation/             # 交通
└── npcs/                       # NPCデータ
```

## Map Data について

この世界の地理情報は、**Map Data**として機械可読なJSON形式でも管理されています。

- [Map Data について詳しく](../maps/map-data.md)
- データファイル: `world/map-data/data/`
  - `nodes.json` - ノード（地点）データ
  - `routes.json` - ルート（経路）データ
  - `hazards.json` - 危険区域データ
  - `continents.json` - 大陸情報
  - `regions.json` - 地域情報

将来的には、このデータを用いて**Webインタラクティブマップ**を実装予定です。

## ライセンスと利用

この世界観は **CC BY-SA 4.0** で提供されています。

- 商用・非商用問わず利用可能
- 改変・拡張可能
- クレジット表示必須
- 継承義務あり

詳細: [USAGE_POLICY.md](https://github.com/halc8312/SStory/blob/main/USAGE_POLICY.md), [LICENSE](https://github.com/halc8312/SStory/blob/main/LICENSE)

---

**次に読む**: [地理](geography.md) | [交通](transportation.md) | [地図ギャラリー](../maps/gallery.md)
