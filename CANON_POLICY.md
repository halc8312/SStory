# カノンポリシー (Canon Policy)

## はじめに

このドキュメントは、SStoryプロジェクト（エターナル・アルカディア世界構築プロジェクト）における「カノン（正統設定）」の定義、管理プロセス、および変更ポリシーを定めます。

## カノンの定義

### 1. カノン（Canon）とは

**カノン**（正統設定）とは、本プロジェクトにおいて公式かつ事実として認められた世界観設定のことを指します。カノンに含まれる文書は、プロジェクトの公式設定として扱われ、すべてのコントリビューターと利用者が共通の基盤として参照すべきものです。

### 2. カノンの範囲

以下の条件を**すべて満たす**文書がカノンとみなされます：

1. **ファイルタイプ**: `type: "canon-document"` の frontmatter を持つ
2. **カテゴリ**: `category` が `lore`, `geography`, `races`, `magic`, `politics`, `creatures`, `culture`, `economy`, `religion`, `maps`, `transportation` のいずれか
3. **ステータス**: `status: "stable"`（安定状態）
4. **レビュー**: maintainer によるレビュー（approve）を経ている
5. **場所**: `world/` ディレクトリ以下に配置されている

**例**:

- `world/lore/creation-myth.md` (stable, reviewed) → カノン ✅
- `world/geography/continents.md` (stable) → カノン ✅
- `world/npcs/leaders/xxx.md` → `type: "npc"` のためカノンではない（NPC設定はカノン文書ではないが公式文書）
- `world/rules/core-mechanics.md` → `type: "rule"` のためカノンではない（ルール文書は別管理）
- `world/images/README.md` → `type: "asset"` のためカノンではない

### 3. 構造化データ・作業領域との境界

#### Map Data

- `world/map-data/data/*.json` は、地図機能が参照する**機械可読データの編集上の正本**です。公開用の `docs/data/map/*.json` は同期スクリプトで生成する複製であり、直接編集しません。
- 「編集上の正本」は、JSON内の全レコードが自動的に世界観カノンになるという意味ではありません。`confidence: "canon"` は、stableなカノン文書に根拠があることを示す出典区分です。
- `confidence` が `estimated`, `inferred`, `placeholder` の値、および `status: "draft"` のPOIは、表示・経路計算・試作に利用できる補助データであり、カノンではありません。
- JSONとstableなカノン文書が矛盾する場合は、カノン文書を優先し、`world/map-data/data/` を修正してから公開用コピーを再同期します。
- `world/map-data/schemas/`, `world/map-data/docs/`, `world/map-data/examples/` は仕様・手順・例示であり、それ自体は世界観カノンではありません。

#### Language

- ルート直下の `Language/` は架空言語の**設計・実験領域**であり、カノンではありません。そこにある話者数、語彙、歴史、ロードマップは、stableなカノン文書へ採用されるまで提案として扱います。
- 言語設定をカノンへ昇格する場合は、内容を `world/culture/languages.md` などの `type: "canon-document"` へ反映し、レビュー後に `status: "stable"` とします。
- `Language/` とstableなカノン文書が矛盾する場合は、stableなカノン文書を優先します。

### 4. カノンの階層

本プロジェクトでは、カノンに以下の階層区分は設けません。すべての `stable` 状態の `canon-document` は**同等に公式**です。

- 例外: 新しく追加された文書は、一定期間のレビュー期間を経て `stable` になります
- 将来、階層区分（例: Core Canon, Extended Canon）を導入する可能性がありますが、現時点ではすべて単一のカノンとして扱います

## カノンの変更プロセス

カノン（stable 文書）を変更するには、以下のプロセスに従う必要があります。

### 1. 変更提案

- **Issue を作成**: 変更内容について議論を開始
- 変更の理由、影響、根拠を明記
- 関連する既存のカノン文書との矛盾がないか確認

### 2. PR 作成

- 変更を PR にまとめる
- frontmatter の `version` を更新（セマンティックバージョン）
- `last_updated` を更新
- `contributors` に自身の GitHub username を追加
- **optional**: `previous_version` と `changelog` を記入

### 3. レビュー

- maintainer（@halc8312）によるレビュー
- カノン整合性チェック（他のカノン文書と矛盾がないか）
- スタイル・フォーマット確認（STYLE_GUIDE.md 準拠）
- 少なくとも1人のレビューが必要（CONTRIBUTING.md 参照）

### 4. マージとカノン確定

- レビュー承認後にマージ
- マージと同時に `status: "stable"` を維持（または `review` → `stable` に遷移）
- これにより当該文書がカノンとして確定・更新されます

## カノン矛盾の解決

### 1. 矛盾が発生した場合

複数のカノン文書間に矛盾が生じた場合、以下の優先順位で解決します：

1. **最新の更新日時**（`last_updated` が新しい方が優先）
2. **より具体的な文書**（例: 地域詳細 vs 全体概要 では具体的な方が優先）
3. **maintainer の判断**（最終的に @halc8312 が裁定）

### 2. 矛盾報告

矛盾を発見した場合は、ただちに GitHub Issue を立てて報告してください。報告者はできるだけ早期に問題を明文化し、どの文書のどの部分が矛盾するかを明確にしてください。

## カノン文書の作成・削除

### 新規カノン文書の追加

1. 新規文書を作成し、`type: "canon-document"`, `category` を適切に設定
2. `status: "draft"` で初期コミット
3. レビューを通じて `status: "stable"` に昇格
4. これによりカノンとして正式採用

### カノン文書の削除・廃止

- カノン文書の削除は原則禁止です
- 代わりに `status: "deprecated"` を設定し、非推奨としてマーク
- `deprecated` 文書は履歴参照用に保持しますが、現在のカノンとしては扱いません
- 代替文書へのリンクを記載してください

## カノンと二次創作

### 二次創作のカノン利用

- 二次創作（ファンフィクション、ゲームmod、アートなど）では、カノンを自由に利用できます
- カノンを改変する場合、**「これは二次創作設定であり、本プロジェクトの公式カノンではない」** ことを明確に宣言してください
- 例: 「この作品は SStory の世界観をベースにした二次創作です。公式設定とは異なる部分があります」

### カノン誤認防止

- 二次創作作品を「公式」「 canon」「正伝」として販売・公開することは禁止（[USAGE_POLICY.md](USAGE_POLICY.md) 参照）
- タイトル・説明文に「公式」「SStory公式」など誤解を招く表現を使用しないでください

## カノンステータス一覧

| ステータス | 意味 | カノン扱い | 説明 |
|------------|------|------------|------|
| `draft` | 草案 | ❌ | 作業中、公式ではない |
| `review` | レビュー中 | ❌ | レビュー待ち、公式ではない |
| `stable` | 安定 | ✅ | 公式カノンとして確定 |
| `deprecated` | 非推奨 | ❌ | 履歴参照用に保持された旧カノン。現在の設定根拠には使用しない |

## メンテナンス

- カノンポリシー自体も、プロジェクトの成長に伴い更新される可能性があります
- このポリシーの変更には、同様のレビュープロセスが適用されます

## 関連文書

- [CONTRIBUTING.md](CONTRIBUTING.md) - コントリビューションガイドライン
- [STYLE_GUIDE.md](STYLE_GUIDE.md) - スタイルガイド（frontmatter含む）
- [USAGE_POLICY.md](USAGE_POLICY.md) - 利用ポリシー
- [LICENSE](LICENSE) - ライセンス全文
- [schemas/](schemas/README.md) - frontmatter スキーマ定義

---

**最終更新**: 2026-07-18
**バージョン**: 1.1.0
**著者**: halc8312
