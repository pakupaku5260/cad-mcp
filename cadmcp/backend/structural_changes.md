# 结构变化批准记录（S0 → S9）

依据 v1.2.2 §12.3.5 / §13.2：接口变化必须为 0；结构变化（成员定义类变化）
逐类人工批准后放行。

- 生成命令：`python scripts/compare_api.py`
- S0 基线：`cadmcp/backend/api_baseline_s0.json`
- S9 基线：`cadmcp/backend/api_baseline_s9.json`（一次性产物，不入 git）
- 比对结果：**interface_diffs = 0**，兼容 import 4/4 可用，结构变化 335 项
- 批准人：项目负责人（2026-11-07 会话内确认）
- 批准日期：2026-11-07

## 汇总

| 类 | 成员数（S0/S9） | S0 定义类 | S9 定义类数 | 结论 |
|---|---|---|---|---|
| `CADBackend` | 111 / 111 | `CADBackend` | 1（`CADBackend`） | 批准 |
| `ComBackend` | 114 / 114 | `ComBackend` | 19 个 Mixin | 批准 |
| `FakeBackend` | 114 / 114 | `FakeBackend` | 18 个 Mixin | 批准 |
| `Win32DialogProbe` | 1 / 1 | `Win32DialogProbe` | 1（`Win32DialogProbe`） | 无变化 |

三类合计 335 个成员的 `source`（定义类）发生变化；无新增、无删除公开成员，
签名/默认值/注解 0 差异。

## 逐类明细

### `CADBackend`（111 项）

- 变化：111 个公开成员的定义类从 `CADBackend` 变为 `CADBackend`。
- 原因：S2 协议拆分，`cadmcp/backend/protocol/protocol.py` 定义 `CADBackend`；
  `cadmcp/backend/base.py` 保留兼容别名 `CADBackend = CADBackend`。
- 兼容性：`cadmcp.backend.base.CADBackend` 仍可 import；签名逐项一致。

### `ComBackend`（113 项）

- 变化：S0 由单体 `ComBackend` 定义的 113 个成员，S9 分散到 19 个 Mixin；
  `MODELING_DOMAIN_READY = True` 仍由 `ComBackend` 自身定义（Source 未变）。
- S9 定义类：`ComponentMixin`、`ConfigMixin`、`DimensionMixin`、`DocumentMixin`、
  `DrawingMixin`、`ExplodeMixin`、`ExtrudeMixin`、`HelixMixin`、`MateMixin`、
  `ModifyMixin`、`PatternMixin`、`PlaneAxisMixin`、`QueryMixin`、`RevolveMixin`、
  `STAThreadMixin`、`SheetMetalMixin`、`SketchMixin`、`SurfaceMixin`、`ViewMixin`。
- 原因：S2–S6 按业务域拆分，`cadmcp/backend/com/backend.py` 用多继承组合。
- 兼容性：`com_backend.ComBackend` 与 `com.ComBackend` 指向同一类；
  `attach` 的返回注解曾丢失，已于 S10-2 恢复为 `-> ComBackend`（前向引用）。

### `FakeBackend`（111 项）

- 变化：S0 由单体 `FakeBackend` 定义的 111 个成员，S9 分散到 18 个 Mixin；
  `calls_named` / `call_names` / `revision` 仍由 `FakeBackend` 自身定义。
- S9 定义类：`FakeAssemblyComponentMixin`、`FakeAssemblyExplodeMixin`、
  `FakeAssemblyMateMixin`、`FakeAssemblyQueryMixin`、`FakeDocumentMixin`、
  `FakeExtrudeMixin`、`FakeFeatureManageMixin`、`FakeHelixMixin`、`FakeLoftMixin`、
  `FakeModifyMixin`、`FakePlaneAxisMixin`、`FakeQueryMixin`、`FakeRevolveMixin`、
  `FakeSelectionMixin`、`FakeSheetMetalMixin`、`FakeSketchMixin`、
  `FakeSurfaceMixin`、`FakeViewMixin`。
- 原因：S8a–S8i 按域拆分，`cadmcp/backend/fake/backend.py` 用多继承组合；
  `fake_backend.py` 只保留兼容 shim。
- 兼容性：`cadmcp.backend.fake.backend.FakeBackend` 仍可 import；签名逐项一致。

## 未批准项

无。
