# Architecture

Product runtime constraints for `cadmcp`. This document is **not** an
internal agent playbook; it describes what any SolidWorks COM maintainer
must preserve.

## Backends

| Backend | Package | Role |
|---|---|---|
| Protocol / CAD-neutral | `cadmcp.backend.protocol` | Shared models, validators, `CADBackend` surface |
| Fake | `cadmcp.backend.fake` | Offline geometry engine for CI and local tests |
| SolidWorks | `cadmcp.backend.solidworks` | Real COM automation (Windows + SolidWorks 2025) |

`fake` and `solidworks` are peer implementations of the same protocol.
Feature packages must not depend on assembly packages across domains.
Business mixins must not import `backend.py` composition modules.

## STA (SolidWorks COM)

All SolidWorks COM work runs on a dedicated Single-Threaded Apartment (STA)
thread:

1. Every COM call goes through the STA executor.
2. Business mixins must not open their own COM connections.
3. COM objects must not be used from other threads.
4. COM objects must not be passed across threads.
5. COM init / attach / release / exception mapping stay on the STA lifecycle.
6. Thread start / stop / ready / error state remain explicit.
7. COM reference release is audited carefully.

Business mixins call COM only via `infrastructure.py`, which is the sole
business-side facade over `sta.py`. `sta.py` must not depend upward on
`infrastructure.py`.

## Layering

```text
toolsets / kernel / executor
        ↓
backend protocol models
        ↓
fake  ⊥  solidworks
              ↓
     infrastructure → sta
```

- `naming.py` owns feature-name alias state.
- Sketch lifecycle state lives in the sketch modules.
- Error codes for COM failures are mapped in `sta.py` only.

## Public API stability

Do not casually rename public tools, change default arguments, reorder COM
API sequences, or alter OpResult / error envelopes. Compatibility shims for
the pre-rename package name were removed; see [docs/naming.md](docs/naming.md).

## Skills and resources

Usage-layer skills ship as markdown under
`cadmcp/resources/content/skills/` and are exposed as `cadmcp://skill/...`
resources (same source as `help` topics under `cadmcp://help/...`).
