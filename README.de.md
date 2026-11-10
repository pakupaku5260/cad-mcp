# cadmcp

**Sprachen:** [English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [日本語](README.ja.md)

> **English README is authoritative; translations welcome via PR.**

CAD-MCP-Server: ein Prozess, eigener STA-Executor, offline testbares Fake-Backend —
**SolidWorks-Backend zuerst**.

> **Nicht verbunden mit Dassault Systèmes.** SolidWorks® ist eine Marke von
> Dassault Systèmes oder verbundenen Unternehmen. Dies ist ein unabhängiger
> Community-MCP-Server.

[![CI](https://github.com/shiyang19822000/cad-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/shiyang19822000/cad-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pycadmcp.svg)](https://pypi.org/project/pycadmcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Anforderungen

| Modus | Benötigt |
|---|---|
| **Fake-Backend (CI-Standard)** | Python 3.11+, Windows/macOS/Linux |
| **SolidWorks-Backend** | Windows + SolidWorks **2025** + `pywin32` |

Die komplette Offline-Testsuite läuft gegen **FakeBackend** — SolidWorks ist
für lokale Entwicklung nicht erforderlich.

## Installation

```bash
pip install pycadmcp
```

Entwicklung (editierbar + Testdeps):

```bash
git clone https://github.com/shiyang19822000/cad-mcp.git
cd cad-mcp
python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

CLI: `cadmcp`.

## Schnellstart

```bash
cadmcp doctor --backend fake
```

Beispiel-Rezept: `examples/box_recipe.json` (MCP-Tool `replay_recipe`).

```bash
cadmcp install --client opencode --dry-run
cadmcp serve --transport stdio --backend fake --profile part
```

Für echte SolidWorks-Nutzung: `--backend solidworks` unter Windows.

## Fähigkeitsmatrix

**134 Tools** in **9 Toolsets** — siehe [docs/TOOL_INVENTORY.md](docs/TOOL_INVENTORY.md).

| Toolset | Anzahl | Fokus |
|---|---|---|
| core | 45 | Dokumente, Skizzen, Basis-Features, Abfragen |
| features_adv | 25 | Gewinde, Helix, Sweep, Flächen |
| assembly | 20 | Einfügen, Verknüpfungen, Komponenten |
| drawing | 16 | Ansichten, Annotationen |
| sketch_adv | 12 | Splines, Offset/Trim, Bemaßungen |
| sheetmetal | 7 | Blech |
| selection | 6 | Flächen-/Kantenwahl |
| view | 2 | Ansichten / Screenshots |
| export | 1 | STEP/STL/PDF/DXF |

Skills: `cadmcp://skill/...`.

## Architektur (Kurz)

- Gemeinsame Protocol-Schicht für Fake und SolidWorks.
- SolidWorks-COM nur auf einem **STA**-Thread.
- Ergebnisse als OpResult-Umschlag.

Details: [ARCHITECTURE.md](ARCHITECTURE.md). Umbenennung: [docs/naming.md](docs/naming.md).

## Tests

```bash
ruff check .
pytest -q
python scripts/tool_inventory.py --check
```

Echte SolidWorks-Tests (schließen Dokumente **ohne Speichern**):

```bash
set CADMCP_REAL_SW=1
pytest -q -m sw
```

## Bekannte Einschränkungen

| Einschränkung | Hinweis |
|---|---|
| Mold Core/Cavity | Blockiert — [#1](https://github.com/shiyang19822000/cad-mcp/issues/1) |
| Native InsertThread-API | Helix + Sweep-Cut-Pfad — [#2](https://github.com/shiyang19822000/cad-mcp/issues/2) |
| Toolbox | Nicht integriert — [#3](https://github.com/shiyang19822000/cad-mcp/issues/3) |
| Part in-context edit | Nicht unterstützt — [#4](https://github.com/shiyang19822000/cad-mcp/issues/4) |
| Axiale Einschraubbewegung | Nicht unterstützt |

## Lizenz

[MIT](LICENSE) — Copyright (c) 2026 shiyang19822000.

Nicht verbunden mit Dassault Systèmes.
