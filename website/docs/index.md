---
template: home.html
title: Home
hide:
  - navigation
  - toc
---

## Start here

About five minutes to a Fake health check (no CAD install required):

```bash
pip install pycadmcp
cadmcp doctor --backend fake
cadmcp install --client opencode --dry-run
```

For a live CAD session on Windows, use `--backend solidworks` with the CAD application already running.

[Full quick start →](getting-started.md)

## Two ways to work

<div class="grid cards" markdown>

-   :material-test-tube: **Fake backend**

    ---

    Develop and verify offline on Windows, macOS, or Linux. The full pytest suite runs
    against Fake — try the tools before attaching to a live CAD session.

-   :material-desktop-classic: **Live CAD backend**

    ---

    Attach to a running CAD application on Windows. COM runs only on a dedicated STA
    thread; business code never opens COM itself. SolidWorks 2025 is supported today.

</div>

## Why cadmcp

<div class="grid cards" markdown>

-   :material-creation: **AI-assisted design**

    ---

    Your MCP client calls modeling tools step by step — intent in chat, geometry in CAD.

-   :material-cpu-64-bit: **STA by design**

    ---

    One process, one dedicated STA executor. No cross-thread COM objects.

-   :material-puzzle: **134 tools · 9 toolsets**

    ---

    Sketches, features, assemblies, drawings, sheet metal, export — one MCP surface.

-   :material-connection: **Your MCP client**

    ---

    OpenCode, Cursor, and other MCP hosts. Skills ship as `cadmcp://skill/...`.

</div>

## Guides

<div class="grid cards" markdown>

-   :material-rocket-launch: [Getting started](getting-started.md)

    ---

    Install, doctor, serve, and wire an MCP client.

-   :material-toolbox: [Tools](tools.md)

    ---

    Capability matrix and the full tool inventory.

-   :material-sitemap: [Architecture](architecture.md)

    ---

    Protocol, STA, Fake vs live CAD — product constraints only.

-   :material-help-circle: [FAQ](faq.md)

    ---

    Limits, licensing notes, and common questions.

</div>
