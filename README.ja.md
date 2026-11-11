# cadmcp

**言語:** [English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [日本語](README.ja.md)

> **English README is authoritative; translations welcome via PR.**

CAD MCP サーバー：単一プロセス、専用 STA 実行器、オフライン検証可能な Fake バックエンド —
**SolidWorks バックエンドを優先**。

> **Dassault Systèmes とは無関係です。** SolidWorks® は Dassault Systèmes または
> その子会社の商標です。本プロジェクトは独立したコミュニティ向け MCP サーバーです。

[![CI](https://github.com/pakupaku5260/cad-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/pakupaku5260/cad-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pycadmcp.svg)](https://pypi.org/project/pycadmcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 必要条件

| モード | 必要環境 |
|---|---|
| **Fake バックエンド（CI 既定）** | Python 3.11+、Windows/macOS/Linux |
| **SolidWorks バックエンド** | Windows + SolidWorks **2025** + `pywin32` |

オフラインテスト一式は **FakeBackend** で実行できます。開発に SolidWorks は不要です。

## インストール

```bash
pip install pycadmcp
```

開発用（editable + テスト依存）：

```bash
git clone https://github.com/pakupaku5260/cad-mcp.git
cd cad-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

CLI: `cadmcp`。

## クイックスタート

```bash
cadmcp doctor --backend fake
```

### MCP クライアント連携

推奨は **stdio**。`pip install pycadmcp` のあと:

```bash
cadmcp install --client cursor      # または claude | vscode | opencode
cadmcp install --client cursor --dry-run
```

サーバキー `solidworks` を書き込みます。手動 JSON 例:

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "cadmcp",
      "args": ["serve", "--transport", "stdio", "--backend", "solidworks", "--profile", "part"]
    }
  }
}
```

SolidWorks が無い場合は `"fake"`。HTTP はローカル调试向け；クライアントは stdio を使ってください。

接続後、クライアントからツールを呼び出します（例: `examples/box_recipe.json` と `replay_recipe`）。

```bash
cadmcp serve --transport stdio --backend fake --profile part
```

実機は Windows で `--backend solidworks` を使用します。

## 機能マトリクス

**134 ツール / 9 toolset** — [docs/TOOL_INVENTORY.md](docs/TOOL_INVENTORY.md) を参照。

| Toolset | 数 | 内容 |
|---|---|---|
| core | 45 | ドキュメント、スケッチ、基本フィーチャー、照会 |
| features_adv | 25 | ねじ、ヘリックス、スイープ、サーフェス |
| assembly | 20 | 挿入、合致、コンポーネント |
| drawing | 16 | ビュー、注記 |
| sketch_adv | 12 | スプライン、オフセット/トリム、寸法 |
| sheetmetal | 7 | 板金 |
| selection | 6 | 面/エッジ選択 |
| view | 2 | 向き / スクリーンショット |
| export | 1 | STEP/STL/PDF/DXF |

Skills: `cadmcp://skill/...`。

## アーキテクチャ（要約）

- Fake と SolidWorks は共通の protocol 層を共有。
- SolidWorks COM は専用 **STA** スレッドのみ。
- 結果は OpResult エンベロープ。

詳細: [ARCHITECTURE.md](ARCHITECTURE.md)。名称変更: [docs/naming.md](docs/naming.md)。

## テスト

```bash
ruff check .
pytest -q
python scripts/tool_inventory.py --check
```

実機（開いている文書を**保存せず**閉じます）：

```bash
set CADMCP_REAL_SW=1
pytest -q -m sw
```

## 既知の制限

| 制限 | 内容 |
|---|---|
| 金型コア/キャビティ | ブロック中 — [#1](https://github.com/pakupaku5260/cad-mcp/issues/1) |
| ネイティブ InsertThread | ヘリックス + スイープ切除パスを使用 — [#2](https://github.com/pakupaku5260/cad-mcp/issues/2) |
| Toolbox | 未統合 — [#3](https://github.com/pakupaku5260/cad-mcp/issues/3) |
| 部品のインコンテキスト編集 | 非対応 — [#4](https://github.com/pakupaku5260/cad-mcp/issues/4) |
| 軸方向ねじ込みモーション | 非対応 |

## ライセンス

[MIT](LICENSE) — Copyright (c) 2026 pakupaku5260。

Dassault Systèmes とは無関係です。
