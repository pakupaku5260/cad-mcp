# cadmcp

**语言：** [English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [日本語](README.ja.md)

> 语义以 [英文 README](README.md) 为准；本页为中文译本。

CAD MCP 服务器：单进程、专用 STA 执行器、可离线测试的 Fake 后端——**优先对接 SolidWorks**。

> **与达索系统无附属关系。** SolidWorks® 为达索系统或其子公司商标。本项目为独立社区 MCP 服务器。

[![CI](https://github.com/pakupaku5260/cad-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/pakupaku5260/cad-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pycadmcp.svg)](https://pypi.org/project/pycadmcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 环境要求

| 模式 | 需要 |
|---|---|
| **Fake 后端（CI 默认）** | Python 3.11+，Windows/macOS/Linux |
| **SolidWorks 后端** | Windows + SolidWorks **2025** + `pywin32` |

完整离线测试套件跑在 **FakeBackend** 上——本地开发/验证**不需要**安装 SolidWorks。

## 安装

```bash
pip install pycadmcp
```

开发安装（可编辑 + 测试依赖）：

```bash
git clone https://github.com/pakupaku5260/cad-mcp.git
cd cad-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

命令行入口：`cadmcp`。

## 快速开始

```bash
cadmcp doctor --backend fake
```

### 接入 MCP 客户端

推荐 **stdio**：客户端拉起进程。安装后：

```bash
cadmcp install --client cursor      # 或 claude | vscode | opencode
cadmcp install --client cursor --dry-run
```

会写入名为 `solidworks` 的服务项。等价手工配置：

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

无 SolidWorks 时把 `"--backend", "solidworks"` 换成 `"fake"`。HTTP 仅用于本机调试；MCP 客户端请用 stdio。

连上后即可在客户端里调工具（可将 `examples/box_recipe.json` 放入工作区后调用 `replay_recipe`）。

```bash
cadmcp serve --transport stdio --backend fake --profile part
```

真机请在 Windows 上使用 `--backend solidworks`，并先启动 SolidWorks。

## 能力矩阵

**134** 个工具、**9** 个 toolset，详见 [docs/TOOL_INVENTORY.md](docs/TOOL_INVENTORY.md)。

| Toolset | 数量 | 范围 |
|---|---|---|
| core | 45 | 文档、草图、基础特征、查询 |
| features_adv | 25 | 螺纹、螺旋、扫掠、曲面等 |
| assembly | 20 | 插入、配合、零部件 |
| drawing | 16 | 视图、标注、DrawingSpec |
| sketch_adv | 12 | 样条、偏移/修剪、约束、尺寸 |
| sheetmetal | 7 | 钣金 |
| selection | 6 | 面/边选择 |
| view | 2 | 视角 / 截图 |
| export | 1 | STEP/STL/PDF/DXF |

Skills：`cadmcp://skill/...`。

## 架构摘要

- Fake 与 SolidWorks 共享 protocol 层。
- SolidWorks COM **仅**在专用 **STA** 线程执行。
- 结果为 OpResult 信封（`ok` / `error.code` / `delta` / `state_version`）。

详见 [ARCHITECTURE.md](ARCHITECTURE.md)；命名变更见 [docs/naming.md](docs/naming.md)。

## 测试

```bash
ruff check .
pytest -q
python scripts/tool_inventory.py --check
```

真机（会**不保存**关闭所有已打开文档）：

```bash
set CADMCP_REAL_SW=1
pytest -q -m sw
```

## 已知限制

| 限制 | 说明 |
|---|---|
| 模具型芯/型腔 | 阻塞（分型面 / 许可上下文）— [#1](https://github.com/pakupaku5260/cad-mcp/issues/1) |
| 原生 InsertThread | 使用螺旋+扫掠切除路径 — [#2](https://github.com/pakupaku5260/cad-mcp/issues/2) |
| Toolbox | 未集成 — [#3](https://github.com/pakupaku5260/cad-mcp/issues/3) |
| 零件在位编辑 (`EditPart2`) | 不支持；子装配在位编辑可用 — [#4](https://github.com/pakupaku5260/cad-mcp/issues/4) |
| 轴向拧入运动 | 不支持 |

## 许可证

[MIT](LICENSE) — Copyright (c) 2026 pakupaku5260。

与达索系统无附属关系。SolidWorks® 为达索系统或其子公司商标。
