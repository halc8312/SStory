# アクション可能な推奨事項

## 優先度別タスクリスト

### 🔴 CRITICAL (今すぐ対応 - 1週間以内)

#### タスク #1: データ不整合の修正
**Priority**: Critical
**Estimated Time**: 2-4 hours
**Impact**: High (全ドキュメントの信頼性に影響)

**Sub-tasks**:
- [ ] `world/races/races-overview.md` line 154: 「土の精霊ドリト」→「土の精霊グラン（Granus）」に修正
- [ ] `world/politics/kingdoms.md` line 167: 「約70万kmkm²」→「約70万km²」に修正
- [ ] `world/economy/trade.md`: 「アールディー1026年」のepochを定義または明確化
- [ ] 他に不整合がないか一括検索
  - 検索パターン: 「ドリト」「Granus」「グラン」を一貫性チェック
  - 検索パターン: 「kmkm²」「キロメートル」の単位一貫性

**Implementation**:
```bash
# 不整合検索
grep -r "ドリト" world/
grep -r "kmkm²" world/
grep -r "アールディー" world/
```

**Deliverable**: 修正を含むPR #2

---

#### タスク #2: CONTRIBUTING.md 作成
**Priority**: Critical
**Estimated Time**: 3-5 hours
**Impact**: High (今後のコントリビューション効率化)

**File**: `CONTRIBUTING.md` (ルート)

**Content**:
```markdown
# SStory への Contributing ガイド

## はじめに
世界観プロジェクトへの参加を歓迎します！

## 開発プロセス
1. Issueで提案（新規設定・修正）
2. Forkして作業
3. Pull Request作成
4. Review後マージ

## ファイル規則
### 命名規則
- 小文字、ハイフン区切り (kebab-case)
- 例: `creation-myth.md`, `central-region.md`

### ディレクトリ構造
world/
  ├── lore/
  ├── geography/
  ├── races/
  ├── magic/
  ├── politics/
  ├── creatures/
  ├── culture/
  ├── economy/
  ├── religion/
  └── maps/

### メタデータ (必須)
各ファイル先頭に YAML frontmatter:

---
title: "ファイルタイトル"
version: "1.0.0"
created: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
author: "GitHub username"
category: "lore|geography|magic|..."
tags: ["tag1", "tag2"]
status: "draft|review|stable"
---

### マークダウン規約
- 見出し: # 〜 ##### まで
- 表: | で整列
- リンク: [テキスト](相対パス)
- 強調: **太字**、*斜体*
- コード: ``` で囲む

### 相互参照
関連ファイルがある場合は必ず末尾に:
**関連項目**: [関連ページ名](../path/to/file.md)

### 表記統一
- 種族名: 人間、エルフ、ドワーフ、オーク、ハーフリング（カタカナ統一）
- 精霊名: 風の精霊ゼフ、地の精霊グラン、火の精霊ピュロス、水の精霊ハイドロ、月の精霊ルナ
- 大陸名: エリュシオン、リュミエラ、カオス・リア、アトランティス、グリモワール
- 国名: 日本語表記優先、英語併記可

## レビュープロセス
- 少なくとも1人のレビューが必要
- 既存設定との矛盾がないか確認
- マークダウン構文チェック
- クロスリファレンス確認

## 質問がある場合
GitHub Issue または Discussions へ

## ライセンス
CC BY-SA 4.0 - 商用利用可、クレジット必須、継承義務あり
```

---

#### タスク #3: 自動CIパイプライン強化
**Priority**: Critical
**Estimated Time**: 2-3 hours
**Impact**: High (今後の品質保証)

**File**: `.github/workflows/lint.yml` (新規作成)

**Content**:
```yaml
name: Lint and Validate

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  markdown-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install markdownlint
        run: npm install -g markdownlint-cli
      - name: Run markdownlint
        run: markdownlint '**/*.md' --ignore node_modules

  link-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install markdown-link-check
        run: npm install -g markdown-link-check
      - name: Check links
        run: markdown-link-check -q -c .markdown-link-check.json '**/*.md'

  spell-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run cspell
        uses: streetsidesoftware/cspell-action@v1
        with:
          files: '**/*.md'
          language: 'ja'
```

**Additional config files**:
- `.markdownlint.json` - ルール設定
- `.cspell.json` - 辞書設定
- `package.json` - devDependencies追加

---

### 🟡 HIGH (1ヶ月以内)

#### タスク #4: YAML Frontmatter 標準化
**Priority**: High
**Estimated Time**: 8-12 hours
**Impact**: Medium (メタデータ管理)

**Implementation**:
1. 全31ファイルに frontmatter 追加
2. 項目:
   - `title`
   - `version` (初期値 1.0.0)
   - `created` (不明な場合は 2026-05-01)
   - `last_updated`
   - `author` (halc8312)
   - `category` (lore/geography/races/magic/politics/creatures/culture/economy/religion)
   - `tags` (5-10個のキーワード)
   - `status` (stable/draft)

**Example**:
```yaml
---
title: "創世神話 - エターナル・アルカディア"
version: "1.0.0"
created: "2026-01-15"
last_updated: "2026-05-01"
author: "halc8312"
category: "lore"
tags: ["creation", "gods", "four-primordials", "spirit-contracts"]
status: "stable"
---
```

**Script** (optional):
```bash
#!/bin/bash
# add-frontmatter.sh
for file in world/**/*.md; do
  # 既に frontmatter があるかチェック
  if ! head -1 "$file" | grep -q "^---"; then
    # frontmatter を追加
    cat > /tmp/fm.yaml <<EOF
---
title: "$(basename "$file" .md | tr '-' ' ' | sed 's/.*/\u&/')"
version: "1.0.0"
created: "2026-05-01"
last_updated: "2026-05-01"
author: "halc8312"
category: "$(dirname "$file" | cut -d/ -f2)"
tags: []
status: "stable"
---
EOF
    cat /tmp/fm.yaml "$file" > /tmp/newfile && mv /tmp/newfile "$file"
  fi
done
```

---

#### タスク #5: コアTRPGルール作成
**Priority**: High
**Estimated Time**: 100-200 hours (大規模)
**Impact**: Critical (プロジェクトの本質的価値)

**New Files to Create**:

##### 1. `world/rules/core-mechanics.md`
**目的**: 基本ルールブックの第1章
**内容**:
- 能力値定義 (STR, DEX, CON, INT, WIS, CHA)
- 種族修正 (racial modifiers)
- 年齢による能力変化
- 命中判定 (d20 + 修正 vs AC)
- ダメージ計算
- 経験値とレベルアップ

##### 2. `world/rules/combat.md`
**内容**:
- 戦闘ターン制 (initiative)
- 行動 types: 移動、攻撃、呪文、特殊能力
- 位置と範囲効果
- 状態異常 (麻痹、魅了、 etc.)
- 防御選択 (AC)

##### 3. `world/rules/magic-casting.md`
**内容**:
- 詠唱時間 (1秒～3日)
- MPコスト
- 成分 (V/S/M) 要件
- 成功判定 (spellcasting check)
- 失敗時の暴走ルール
- 一日あたりの使用制限

##### 4. `world/rules/bestiary-stats.md`
**内容**:
- モンスターのステータスブロック形式
- CR (Challenge Rating) 計算式
- 例: ゴブリン、オーク、ドラゴン

##### 5. `world/rules/character-creation.md`
**内容**:
- ステップバイステップ作成ガイド
- クラス定義 (戦士、魔法使い、盗賊、牧师、 etc.)
- スキル一覧
- 装備ルール
- 初期所持金

**ワークフロー**:
1. 基本ルール定義 (Week 1-2)
2. テストプレイ (Week 3-4)
3. バランス調整 (Week 5-6)
4. ドキュメント化 (Week 7-8)

---

#### タスク #6: ワールドマップ作成
**Priority**: High
**Estimated Time**: 40-80 hours
**Impact**: High (世界観の可視化)

**Option A: 手描きスキャン (早い)**
- ラフスケッチ → スキャン → 簡易着色
- 時間: 20-40時間
- 品質: 中

**Option B: デジタル描画 (高品質)**
- ツール: Inkarnate, Wonderdraft, Photoshop
- 時間: 40-80時間
- 品質: 高

**Option C: プロ発注 (最高品質)**
- 予算: $500-2,000
- 時間: コミュニケーション含め2-4週間
- 品質: 最高

**推奨**: Option A+B ハイブリッド
- 自分でラフ作成 → デジタル仕上げ
- またはコミュニティからアーティスト募集

**Files to Create**:
```
world/maps/
├── world-map.png              # 全体図 (2000x2000px)
├── world-map-source.psd       # 編集用ソース
├── continents/
│   ├── elysion.png              # エリュシオン
│   ├── lumiera.png            # リュミエラ
│   ├── chaosrea.png           # カオス・リア
│   ├── atlantis.png           # アトランティス
│   └── grimoire.png           # グリモワール
└── political/
    └── political-map.png      # 国境線表示
```

---

### 🟢 MEDIUM (3ヶ月以内)

#### タスク #7: 主要NPC作成
**Priority**: Medium
**Estimated Time**: 60-100 hours
**Impact**: Medium (物語の中心だが、なくても世界観は成立)

**Files to Create**:
```
world/npcs/
├── leaders/                    # 現職指導者
│   ├── zephyr-president.md
│   ├── moon-elf-queen.md
│   ├── dwarf-king.md
│   ├── orc-warlord.md
│   └── jade-queen.md
├── historical/                 # 歴史的人物
│   ├── founder-of-zephyr.md
│   ├── last-lunarian-empress.md
│   └── gran-dwarf-king.md
└── adventurers/               # 冒険者NPC
    ├── famous-adventurer-1.md
    └── guild-master.md
```

**Each NPC file template**:
```markdown
---
title: "NPC名"
category: "npcs"
type: "leader|historical|adventurer"
race: "human|elf|dwarf|orc|halfling"
age: 数値
alignment: "lawful-good|neutral|etc."
class: "職業"
---

# 名前
**肩書き**: 役職
**所属**: 国家・組織

## 外見
- 身長: XX cm
- 体重: XX kg
- 髪: XX
- 瞳: XX
- 特徴: XX

## 性格
- 主要特性3つ
- 価値観
- 目標

## 能力値 (TRPG用)
- STR: 10 (+0)
- DEX: 14 (+2)
- CON: 12 (+1)
- INT: 16 (+3)
- WIS: 13 (+1)
- CHA: 15 (+2)

## 経歴
- 生誕: 年、場所
- 重要な出来事
- 現在の立場に至る経緯

## 関係者
- 友好: NPC名
- 敵対: NPC名
- 中立: NPC名

## 所有アイテム
- 伝説の剣「名前」 (+2 攻撃)
- 魔法の指輪「名前」 (効果)
-  etc.

## 現在の状況
- 現在の活動
- 抱える問題
- プレイヤーへの関わり方
```

---

#### タスク #8: 用語集 (Glossary) 作成
**Priority**: Medium
**Estimated Time**: 8-12 hours
**Impact**: Medium (読者の理解向上)

**File**: `world/glossary.md`

**Content**:
```markdown
# 用語集

## あ行
- **アストラリス** (Astralis): ゼフィア連合共和国の首都、世界最大都市
- **アストラエル** (Astrael): 原初の四柱神の一柱、星と魔法の創造神
...

## か行
...

## さ行
...

## た行
...

## な行
...

## は行
...

## ま行
...

## や行
...

## ら行
...

## わ行
...
```

**Implementation**:
1. 全ファイルから専門用語を抽出 (スクリプト)
2. 五十音順にソート
3. 各項目に簡単な説明 (1-2行) と詳細へのリンク

---

#### タスク #9: タイムライン可視化
**Priority**: Medium
**Estimated Time**: 16-24 hours
**Impact**: Medium (歴史の理解容易化)

**Options**:
1. **Mermaid.js 図** (GitHubで表示可能)
   ```mermaid
   timeline
       title エターナル・アルカディア歴史
       section 混沌期 (-10000〜-5000)
         四柱神の創造 :  -10000 : 始まり
         精霊誕生 :  -8000 : 元素精霊
       section 精霊契約期 (-5000〜-1000)
         ルナリア帝国 :  -5000 : エルフの文明
         グランドリア王国 :  -3000 : ドワーフの文明
         ゼフィア連合成立 :  -1000 : 人間の台頭
       section 現代契約期 (-1000〜0)
         十二国同盟成立 : 0 : 現在の秩序
   ```

2. **SVG 画像** (静的だが美しい)
3. **Web インタラクティブ** (将来拡張可能)

**推奨**: Mermaid.js で簡易版を `world/lore/timelines/visual-timeline.md` に作成

---

#### タスク #10: ドキュメントサイト構築
**Priority**: Medium
**Estimated Time**: 24-40 hours
**Impact**: High (アクセシビリティ向上)

**Tool Selection**:
- **Docusaurus** (Facebook製、Reactベース) - 推奨
- **MkDocs** (Pythonベース、シンプル) - 軽量
- **Hugo** (Goベース、高速) - 大規模向け
- **GitBook** (SaaS) - 手軽

**推奨: Docusaurus** (日本語対応、検索あり、モダン)

**Implementation**:
```bash
# セットアップ
npx create-docusaurus@latest docs classic

# 構成
docs/
├── sidebars.js              # サイドバー構成
├── docusaurus.config.js     # 設定
├── src/
│   ├── components/          # カスタムコンポーネント
│   ├── pages/              # トップページ
│   └── themes/             # テーマ
├── world/                   # 既存コンテンツを変換
│   ├── index.md
│   ├── lore/
│   └── ...
└── static/                 # 画像・資産
```

**Features**:
- 検索機能 (Algolia または local search)
- ダークモード
- 多言語対応基盤 (i18n)
- バージョン管理 (複数バージョン同時公開)
- モバイル対応

**Deployment**: GitHub Pages (自動)

---

### 🔵 LOW (6ヶ月以内)

#### タスク #11: 国際化 (i18n) 対応
**Priority**: Low
**Estimated Time**: 100-200 hours
**Impact**: Medium (海外ユーザー獲得)

**Goal**: 英語版作成

**Strategy**:
1. 全ファイルを `world/en/` に翻訳
2. 翻訳管理: Crowdin または GitHub Translations
3. 言語切り替えUI実装

**Files**:
```
world/
├── index.md                  (日本語)
├── en/
│   ├── index.md
│   ├── lore/
│   └── ...
```

**Note**: 日本語が原文、英語は翻訳版と明記

---

#### タスク #12: データエクスポート機能
**Priority**: Low
**Estimated Time**: 40-60 hours
**Impact**: Low (プログラム的利用)

**Goal**: JSON形式で全データエクスポート

**File**: `scripts/export.js`

**Output**:
```json
{
  "version": "1.0.0",
  "world": {
    "name": "Eternal Arcadia",
    "races": [
      {
        "id": "human",
        "name_ja": "人間",
        "name_en": "Human",
        "lifespan": "80年",
        "spirit_affinity": {"wind": 0.3, "earth": 0.2, ...}
      }
    ],
    "nations": [...],
    "deities": [...],
    "magic_system": {...}
  }
}
```

**Use Cases**:
- ゲーム開発者がデータをインポート
- AIトレーニングデータ
- データ分析

---

#### タスク #13: APIサーバー構築
**Priority**: Low
**Estimated Time**: 60-80 hours
**Impact**: Low

**Stack**: Node.js + Express + TypeScript

**Endpoints**:
```
GET  /api/v1/races
GET  /api/v1/nations
GET  /api/v1/magic-system
GET  /api/v1/search?q=query
GET  /api/v1/lore/timeline
```

**Authentication**: Public API (rate limiting)

---

## プロジェクト管理タスク

### プロジェクトマネジメント

#### PM-1: ロードマップ作成
**Priority**: High
**File**: `ROADMAP.md` (ルート)

**Content**:
```markdown
# SStory 開発ロードマップ

## v1.0.0 (Current)
- 基本世界観完成
- 十二国家詳細
- 魔法システム完成

## v1.1.0 (2026-Q3)
- TRPGコアルール実装
- ワールドマップ公開
- 主要NPC 10体追加

## v1.2.0 (2026-Q4)
- ドキュメントサイト公開
- ベストiary統計データ
- 6つの国家を詳細化

## v2.0.0 (2027)
- 完全なTRPGサプリメント
- 高品質マップ完成
- 英語版公開
- コミュニティ100人突破

## v3.0.0 (2028)
- 複数の拡張セット
- ゲーム統合 (Foundry VTT)
- 出版 (PDF/Print)
```

---

#### PM-2: Issueテンプレート作成
**Priority**: Medium

**Files**:
- `.github/ISSUE_TEMPLATE/bug-report.md`
- `.github/ISSUE_TEMPLATE/feature-request.md`
- `.github/ISSUE_TEMPLATE/worldbuilding-suggestion.md`

---

#### PM-3: Pull Requestテンプレート作成
**Priority**: Medium

**File**: `.github/PULL_REQUEST_TEMPLATE.md`

**Content**:
```markdown
## 変更概要
- 簡潔な説明

## 変更内容
- 詳細な変更点
- 関連ファイル

## 影響範囲
- 既存設定との整合性
- 修正が必要なファイル

## テスト
- 手動で確認した内容

## Screenshots (該当する場合)
-  before/after

## チェックリスト
- [ ] 既存設定との矛盾なし
- [ ] Markdown構文チェック済み
- [ ] クロスリファレンス確認済み
- [ ] メタデータ更新済み
```

---

#### PM-4: スタイルガイド作成
**Priority**: Medium
**File**: `STYLE_GUIDE.md`

**Content**:
- 表記規則（全角/半角、漢字の使用）
- 用語統一リスト
- 表のデザインガイド
- 見出し構造ルール
- ファイル名命名規則
- ディレクトリ構造ルール

---

## 技術的改善

### Tech-1: パッケージマネジメント導入
**Priority**: Low

`package.json` 作成:
```json
{
  "name": "sstory-worldbuilding",
  "version": "1.0.0",
  "scripts": {
    "lint": "markdownlint '**/*.md'",
    "links": "markdown-link-check '**/*.md'",
    "spell": "cspell '**/*.md'",
    "build": "npm run lint && npm run links",
    "test": "npm run build"
  },
  "devDependencies": {
    "markdownlint-cli": "^0.40.0",
    "markdown-link-check": "^3.10.0",
    "cspell": "^8.0.0"
  }
}
```

---

### Tech-2: 検証スクリプト作成
**Priority**: Medium

`scripts/validate-consistency.js`:
- 全ファイルから用語を抽出
- 表記ゆれを検出
- 数値の矛盾チェック (例: 人口の合計 vs 各国家人口)
- リンク切れ検出

---

### Tech-3: データベース化
**Priority**: Low (長期的)

**Option**: SQLite + 管理ツール
- 世界観データを構造化
- クエリで関連情報取得
- バージョン管理可能

---

## コミュニティ構築

### Comm-1: GitHub Discussions 有効化
**Priority**: High
**Estimated Time**: 1 hour

**Categories**:
- General (一般讨论)
- Q&A (質問)
- Ideas (提案)
- Worldbuilding (世界構築)
- Showcase (成果発表)

---

### Comm-2: Discord サーバー作成
**Priority**: Medium
**Estimated Time**: 4 hours

**Channels**:
- #general - 雑談
- #worldbuilding - 世界構築議論
- #rules-development - ルール開発
- #art-assets - アート共有
- #showcase - 利用作品発表
- #help - 質問

---

### Comm-3: 初回コントリビュートイベント
**Priority**: Medium
**Estimated Time**: 8 hours (準備)

**Event**: "SStory Worldbuilding Sprint Week"

**Goal**: 10人から初PR獲得

**Tracks**:
1. **Geography Track**: 地域詳細5ファイル作成
2. **Bestiary Track**: モンスター10体統計データ作成
3. **NPC Track**: 主要NPC 3体作成
4. **Map Track**: 簡易マップ作成

**Rewards**:
- コントリビューター一覧に記載
- 限定ロール (Discord)
- クレジット表示

---

## コンテンツ拡張計画

### 優先順位別コンテンツ作成

#### Tier 1 (Must Have)
1. ✪ TRPG コアルール (100-200h)
2. ✪ ワールドマップ (40-80h)
3. ✪ 主要NPC (60-100h)
4. ✪ 用語集 (8-12h)
5. ✪ タイムライン図 (16-24h)

**Total Tier 1**: 224-416時間 (2-4ヶ月フルタイム)

---

#### Tier 2 (Should Have)
6. ベストiary統計データ (40-60h)
7. 全12国家の詳細化 (各20-40h = 240-480h)
8. 種族ごとの文化詳細 (各15-25h = 75-100h)
9. 魔法学校のカリキュラム (20-30h)
10. アイテムカタログ (100+アイテム, 40-60h)

**Total Tier 2**: 415-730時間 (4-7ヶ月)

---

#### Tier 3 (Nice to Have)
11. シナリオ/クエスト例 (10-20シナリオ, 80-120h)
12. エラの町（詳細都市） (30-50h/都市)
13. Organization詳細 (ギルド、教会 etc.) (50-80h)
14. 伝説のアイテム (20-30h)
15. 異世界転生ルール (20-40h)

**Total Tier 3**: 200-320時間 (2-3ヶ月)

---

## リソース配分提案

### 人的リソース

**現在**: 1人 (halc8312)

**推奨体制** (6ヶ月後目標):
- コアメンテナー: 2-3人
- コンテンツチーム: 5-10人
  - 歴史チーム (2人)
  - 地理チーム (2人)
  - 政治経済チーム (2人)
  - 魔法システムチーム (2人)
  - 文化種族チーム (2人)
- アートチーム: 2-3人
- ゲームデザインチーム: 2-3人
- コミュニティマネージャー: 1人

**Total Target**: 15-25人の共同作業者

---

### 財務リソース

**現在**: $0 (無料)

**推奨資金調達** (オプション):
1. **GitHub Sponsors**: 維持費用
2. **Patreon**: 拡張資金
3. **クリエイター支援**: アート発注費
4. **クラウドファンディング**: 書籍出版費

**推定必要額**:
- アート発注: $2,000-5,000
- サイト維持: $0-100/年 (GitHub Pages無料)
- ツール購入: $200-500
- 総額: $2,500-6,000

---

## 成功指標 (KPI)

### 3ヶ月後 (短期)
- [ ] コントリビューター数: 3人以上
- [ ] PR数: 10件以上
- [ ] ドキュメントサイト公開
- [ ] データ不整合修正完了
- [ ] CONTRIBUTING.md 公開

### 6ヶ月後 (中期)
- [ ] コントリビューター数: 10人以上
- [ ] TRPGコアルール完成
- [ ] ワールドマップ公開
- [ ] Discord サーバー 50人以上
- [ ] 初の派生作品誕生

### 12ヶ月後 (長期)
- [ ] コントリビューター数: 30人以上
- [ ] 全主要国家の詳細化完了 (6/12)
- [ ] GitHub Stars: 100以上
- [ ] 利用作品: 5作品以上
- [ ] 英語版公開
- [ ] 初のPDFリリース

---

## リスクと軽減策

### リスク1: 単一維持者ボトルネック
**リスク**: halc8312が時間を取れない
**軽減策**:
- 早期にコアメンテナーを育成
- 決定権の分散
- ドキュメントによる知識共有

### リスク2: 品質低下
**リスク**: 開放後の低品質コントリビューション
**軽減策**:
- 厳格なレビュープロセス
- 自動チェック (CI/CD)
- 明確なガイドライン
-  rejects ではなく改善提案

### リスク3: 争いごと
**リスク**: 世界観をめぐる議論の対立
**軽減策**:
- 民主的決定プロセス
- 最終決定権をコアチームに
- 透明性のある議論 (GitHub Issues)

### リスク4: モチベーション低下
**リスク**: 進捗が見えず継続困難
**軽減策**:
- 小さなマイルストーン設定
- 定期的な進捗報告
- コミュニティからの称賛
- コントリビューターの表彰

---

## ツールチェイン完成形

```
┌─────────────────────────────────────────────────────────┐
│                   開発ワークフロー                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [Local Dev]                                            │
│       │                                                 │
│       ▼                                                 │
│  ┌────────────────┐                                    │
│  │  markdownlint  │ ← 構文チェック                      │
│  └────────┬───────┘                                    │
│           │                                             │
│  ┌────────▼───────┐                                    │
│  │ spell-check    │ ← スペルチェック                    │
│  └────────┬───────┘                                    │
│           │                                             │
│  ┌────────▼───────┐                                    │
│  │ link-check     │ ← リンク切れチェック                │
│  └────────┬───────┘                                    │
│           │                                             │
│  ┌────────▼───────┐                                    │
│  │ validate-cons  │ ← 一貫性チェック (独自)              │
│  └────────┬───────┘                                    │
│           │                                             │
│           ▼                                             │
│  [Git Push]                                             │
│           │                                             │
│           ▼                                             │
│  ┌────────────────────────────────────────────┐        │
│  │         GitHub Actions (CI/CD)              │        │
│  ├────────────────────────────────────────────┤        │
│  │ 1. Checkout                                │        │
│  │ 2. Lint & Validate                          │        │
│  │ 3. Build (optional)                         │        │
│  │ 4. Deploy to GitHub Pages (on main)         │        │
│  └────────────────────────────────────────────┘        │
│           │                                             │
│           ▼                                             │
│  [GitHub Pages] ← 自動公開                               │
│                                                         │
│  ┌────────────────────────────────────────────┐        │
│  │          Additional Tools                    │        │
│  ├────────────────────────────────────────────┤        │
│  │ • Docusaurus (静的サイト)                     │        │
│  │ • Search (Algolia / local)                  │        │
│  │ • i18n (将来)                                │        │
│  │ • API (将来)                                 │        │
│  └────────────────────────────────────────────┘        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 初月の具体的なスケジュール

### Week 1 (今週)
- [x] 評価レポート作成 (済)
- [ ] データ不整合修正 PR #2 作成
- [ ] CONTRIBUTING.md 追加 PR #3
- [ ] 自動CI (.github/workflows/lint.yml) PR #4
- [ ] メタデータ標準化ガイド追加 PR #5

**Goal**: 基本体制整備

---

### Week 2-3
- [ ] 全ファイルへの YAML frontmatter 追加
- [ ] markdownlint 設定 (.markdownlint.json)
- [ ] 用語集 (glossary.md) 草案作成
- [ ] GitHub Discussions 有効化

**Goal**: 品質基盤構築

---

### Week 4
- [ ] 第一回レビューミーティング (GitHub Discussions)
- [ ] 次月ロードマップ公開
- [ ] Discord サーバー作成・告知
- [ ] 初コントリビュート歓迎イベント発表

**Goal**: コミュニティ開始

---

### Month 2 以降
- TRPGルール作成開始 (コアチーム結成)
- ワールドマップ制作開始 (アーティスト募集)
- 6国家の詳細化 (チーム分け)
- 英語翻訳開始 (ボランティア募集)

---

## 結論

SStoryは**優れた基盤を持つ傑プロジェクト**です。

ただ、今のままだと:
1. データ不整合が読者の信頼を損なう
2. コントリビューターが参加しにくい
3. ゲームとして使えない (TRPG目的なら)

**すぐにできる3つのこと**:
1. ✍️ 不整合を修正する (2-4h)
2. 📝 CONTRIBUTING.md を作る (3-5h)
3. 🤖 自動CIを追加する (2-3h)

**これだけで**:
- 品質が大幅向上
- 新規コントリビューターが安心して参加できる
- プロジェクトのプロフェッショナル印象が上がる

**次はTRPGルールとマップ** - これが完成すれば、本当に「完成した世界観」になります。

---

**推奨アクション**: 今週中に 🔴 CRITICAL タスク #1-3 を実行し、PRを作成してください。

**弊社（opencode）は、そのPR作成を自動的に行います** (このIssueに /oc コマンドで)。

---

**Document Version**: 1.0.0
**Last Updated**: 2026-05-01
**Status**: Actionable Recommendations
