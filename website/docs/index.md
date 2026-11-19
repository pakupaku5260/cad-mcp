---
template: home.html
title: Home
hide:
  - navigation
  - toc
description: Connect an AI client to SolidWorks over MCP — sketch, extrude, assemble, detail and export from chat.
---

## Start here

Five minutes to a working MCP client. The first two commands need no CAD install:

```bash
pip install pycadmcp
cadmcp doctor --backend fake
cadmcp install --client cursor      # or: claude | vscode | opencode
```

For real geometry, run SolidWorks 2025 on Windows and switch the backend to
`solidworks`.

[Full quick start →](getting-started.md)

## See it build

<div class="grid cards" markdown>

-   :material-camera: **Real session, not a mockup**

    ---

    ![100×50×10 mm plate with four Ø6 through holes](assets/quickstart-demo.png)

    Prompt: *"Create a 100×50×10 mm plate with four Ø6 through holes at the
    corners."* Built through MCP in SolidWorks 2025.

-   :material-code-braces: **What the agent called**

    ---

    ```text
    new_part            {}
    start_sketch        {"plane": "Front Plane"}
    sketch_rectangle    {"x1": 0, "y1": 0, "x2": 100, "y2": 50}
    end_sketch          {}
    extrude             {"depth": 10}
    hole_wizard         {"face": 4, "diameter": 6, "end": "through_all", "x": 10, "y": 10}
    hole_wizard         {"face": 4, "diameter": 6, "end": "through_all", "x": 90, "y": 10}
    hole_wizard         {"face": 4, "diameter": 6, "end": "through_all", "x": 10, "y": 40}
    hole_wizard         {"face": 4, "diameter": 6, "end": "through_all", "x": 90, "y": 40}
    get_mass_properties {}
    ```

    `get_mass_properties` reports 48,869 mm³ — 50,000 minus four Ø6 holes,
    exactly as requested.

</div>

## Featured case

A horizontal oil-tank assembly built end to end through MCP: 16 part models,
21 mates and seven views. Use the dots to switch views.

<div class="oil-carousel">
  <input type="radio" name="oilc" id="oilc1" checked>
  <input type="radio" name="oilc" id="oilc2">
  <input type="radio" name="oilc" id="oilc3">
  <input type="radio" name="oilc" id="oilc4">
  <input type="radio" name="oilc" id="oilc5">
  <input type="radio" name="oilc" id="oilc6">
  <input type="radio" name="oilc" id="oilc7">
  <div class="oil-carousel__viewport">
    <div class="oil-carousel__slides">
      <div class="oil-carousel__slide"><img src="assets/images/oil-tank/iso.png" alt="Isometric view"><span>Isometric</span></div>
      <div class="oil-carousel__slide"><img src="assets/images/oil-tank/front.png" alt="Front view"><span>Front</span></div>
      <div class="oil-carousel__slide"><img src="assets/images/oil-tank/back.png" alt="Back view"><span>Back</span></div>
      <div class="oil-carousel__slide"><img src="assets/images/oil-tank/left.png" alt="Left view"><span>Left</span></div>
      <div class="oil-carousel__slide"><img src="assets/images/oil-tank/right.png" alt="Right view"><span>Right</span></div>
      <div class="oil-carousel__slide"><img src="assets/images/oil-tank/top.png" alt="Top view"><span>Top</span></div>
      <div class="oil-carousel__slide"><img src="assets/images/oil-tank/bottom.png" alt="Bottom view"><span>Bottom</span></div>
    </div>
  </div>
  <div class="oil-carousel__nav">
    <label for="oilc1" title="Isometric view"></label>
    <label for="oilc2" title="Front view"></label>
    <label for="oilc3" title="Back view"></label>
    <label for="oilc4" title="Left view"></label>
    <label for="oilc5" title="Right view"></label>
    <label for="oilc6" title="Top view"></label>
    <label for="oilc7" title="Bottom view"></label>
  </div>
</div>

[Read the full case study →](showcase/oil-tank.md) — with the capability matrix
and the disclosed 0.4.0 STEP-readback environment limitation.

## Two ways to work

<div class="grid cards" markdown>

-   :material-test-tube: **Fake backend**

    ---

    Develop and verify offline on Windows, macOS, or Linux. The full test suite
    runs against Fake — try the tools before attaching to a live CAD session.

-   :material-desktop-classic: **Live CAD backend**

    ---

    Attach to a running CAD application on Windows. COM runs only on a dedicated
    STA thread; business code never opens COM itself. SolidWorks 2025 is
    supported today.

</div>

## Why cadmcp

<div class="grid cards cmdx-cards-2" markdown>

-   :material-creation: **AI-assisted design**

    ---

    Your MCP client calls modeling tools step by step — intent in chat, geometry
    in CAD.

-   :material-cpu-64-bit: **STA by design**

    ---

    One process, one dedicated STA executor. No cross-thread COM objects.

-   :material-puzzle: **Every CAD domain**

    ---

    Sketches, features, assemblies, drawings, sheet metal, export — one MCP
    surface. See [tools](tools.md) for the matrix and profiles.

-   :material-connection: **Your MCP client**

    ---

    OpenCode, Cursor, Claude Desktop, VS Code, and other MCP hosts. Skills ship
    as `cadmcp://skill/...`.

</div>
