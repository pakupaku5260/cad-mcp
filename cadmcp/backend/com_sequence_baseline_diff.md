# COM 调用序列差异报告

- 基线：`cadmcp/backend/com_sequence_baseline.yaml`（source_sha=bcc8c4096127a59b05ff85c1c61a345d8a2ea8d85164112631e9b3c36326b0ef）
- 当前扫描目录：`cadmcp/backend/com`
- 基线：55 个方法 / 94 个调用点
- 当前：55 个方法 / 94 个调用点
- 差异：1（未批准 0，已批准 1）
- 结果：✅ 通过

## 未批准差异

无。

## 已批准差异

- `ComBackend.extrude_surface`（changed）：S5 拆分：_SURFACE_EXTRU_TAIL 从 ComBackend 私有类属性迁移为 com/_constants.py 模块常量。FeatureExtruRefSurface3 的参数值、顺序、数量均不变 （仅 self. 前缀消失），运行时等价。 — 批准人 项目负责人（2026-11-07 会话内确认）
