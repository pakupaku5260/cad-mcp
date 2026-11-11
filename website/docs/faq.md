# FAQ

## What is cadmcp?

An MCP server that bridges AI clients and CAD design tools. Agents call
modeling tools over MCP; a dedicated executor runs the CAD side. SolidWorks
2025 on Windows is supported today; the protocol is built so additional CAD
backends can follow the same surface.

## Do I need SolidWorks to try it?

No. Use `--backend fake` for install, client wiring, and offline checks on any
OS. Real geometry in SolidWorks requires Windows, SolidWorks 2025 running, and
`--backend solidworks`.

## Which AI clients work?

Any MCP host that can spawn a stdio server or connect over Streamable HTTP —
including Cursor, Claude Desktop, VS Code, and OpenCode. Use
`cadmcp install --client …` for common editors.

## What are the known limits?

Current product limits include (details tracked as GitHub issues):

- Mold core/cavity workflows blocked pending license / parting context
- Native InsertThread path uses helix + sweep-cut
- Toolbox not integrated
- Part in-context edit (`EditPart2`) not supported; subassembly in-context edit is
- Axial screw-in motion not supported

See the project README **Known limitations** table for links.

## Is this affiliated with Dassault Systèmes?

**No.** This is an independent community project under the MIT License.
SolidWorks® is a trademark of Dassault Systèmes or its subsidiaries. cadmcp is
not affiliated with, endorsed by, or sponsored by Dassault Systèmes.

## Where is the source / license?

- Repository: [pakupaku5260/cad-mcp](https://github.com/pakupaku5260/cad-mcp)
- Package: [pycadmcp on PyPI](https://pypi.org/project/pycadmcp/)
- License: MIT
