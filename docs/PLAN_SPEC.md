# 抽样方案规范（`PLAN_SPEC`）

方案是 UTF-8 YAML 映射。加载器使用 `yaml.safe_load`，先做字段白名单校验，再执行抽样。字段路径形如 `plan.dataset.format`；未知字段一律拒绝。

`dataset.path` 若为相对路径，**相对于方案文件所在目录**解析。

## 顶层字段

| 名称 | 类型 | 必填 | 取值约束 | 模式适用性 |
|---|---|---|---|---|
| `plan_id` | string | 是 | 非空 | 全部 |
| `dataset` | mapping | 是 | 仅含 `path`、`format` | 全部 |
| `dataset.path` | string | 是 | 非空；文件必须存在 | 全部 |
| `dataset.format` | string | 是 | `csv` 或 `jsonl` | 全部 |
| `key_field` | string | 是 | 非空；必须存在于数据字段且唯一 | 全部 |
| `mode` | string | 是 | `random` / `stratified` / `systematic` / `cluster` | 全部 |
| `seed` | integer | 是 | 任意整数（禁止 bool） | 全部 |
| `size` | integer | 条件 | 与 `rate` 二选一，必须 `> 0` | 全部 |
| `rate` | number | 条件 | 与 `size` 二选一，`0 < rate <= 1` | 全部 |
| `strata_field` | string | 条件 | 非空，字段应存在于数据集 | 仅 `stratified` |
| `cluster_field` | string | 条件 | 非空，字段应存在于数据集 | 仅 `cluster` |
| `cluster_substrata_field` | string | 条件 | 非空；声明 `cluster_substrata_weights` 时必填 | 仅 `cluster` |
| `cluster_substrata_weights` | mapping | 条件 | `整群名 -> {次级分层名 -> 正数权重}`，非空；声明 `cluster_substrata_field` 时必填 | 仅 `cluster` |
| `expected_distribution` | mapping | 否 | `分层名 -> 非负整数`，非空 | 仅 `stratified` |
| `checks` | list | 是 | 非空映射列表，规则 `id` 唯一 | 全部 |

未知顶层或嵌套字段返回 `PLAN_UNKNOWN_FIELD`。字段合法但模式不适用返回 `PLAN_FIELD_NOT_APPLICABLE`。同时声明 `size` 与 `rate` 返回 `PLAN_CONFLICT`；两者都缺失返回 `PLAN_MISSING_FIELD`。

## `checks` 核验项

每个核验项必须有 `type`，可选 `id`；省略时按位置生成 `check_001`。核验项之间字段白名单不同，未知字段拒绝。

| `type` | 额外字段 | 说明 |
|---|---|---|
| `quota` | 无 | `stratified` 按 `expected_distribution` 比较各分层实际/期望配额；`cluster` 且声明 `cluster_substrata_weights` 时逐群比较群内次级配额。必须声明 `expected_distribution` 或 `cluster_substrata_weights`。 |
| `rate_range` | `min`、`max`（必填，`0 <= min <= max <= 1`） | 实际抽样率 `样本数/总体数` 是否落在闭区间。 |
| `coverage` | `field`（可选）、`groups`（可选非空唯一字符串列表） | 每个声明分组至少抽中 1 条。`field` 缺省取 `strata_field` 或 `cluster_field`；`groups` 缺省取 `expected_distribution` 的键，否则取总体中该字段的去重值。 |
| `key_unique` | 无 | 样本主键不得重复。 |
| `no_overlap` | 无 | 样本主键必须全部属于总体。 |

核验状态为 `pass` / `warn` / `fail`，并输出稳定代码、观测值、期望值与定位：

- 配额不足：`fail` + `CHECK_QUOTA_SHORT`；配额超出：`warn` + `CHECK_QUOTA_OVER`。
- 抽样率越界：`fail` + `CHECK_RATE_OUT_OF_RANGE`；恰在区间端点：`warn` + `CHECK_RATE_AT_BOUNDARY`。
- 覆盖缺失：`fail` + `CHECK_COVERAGE_MISSING`；某声明分组恰好只抽中 1 条：`warn` + `CHECK_COVERAGE_MINIMUM_ONLY`。
- 重复主键：`fail` + `CHECK_DUPLICATE_KEY`；空样本无法检验唯一性或包含关系：`warn` + `CHECK_EMPTY_SAMPLE`。
- 样本键不属于总体：`fail` + `CHECK_KEY_OUTSIDE_POPULATION`。
- 覆盖字段不存在：`fail` + `CHECK_FIELD_NOT_FOUND`。

`--strict` 时，方案校验警告、抽样警告、核验警告中的任意一条都会把整体状态升为 `fail`，CLI 退出码为 `3`。

## 警告语义

- `PLAN_QUOTA_SUM_MISMATCH`：`expected_distribution` 合计与 `size` 不一致；不阻止执行，但严格模式会失败。
- `DATASET_BLANK_LINE`：空行被跳过并记录行号。
- `SAMPLE_SIZE_EXCEEDS_POPULATION`：目标量超过总体，截断为总体大小。
- `SAMPLE_TARGET_ZERO`：库级调用传入零目标时返回空样本。
- `STRATUM_QUOTA_SHORT`：分层可用记录少于声明配额；按可用量抽取，不静默补齐。
- `STRATUM_GROUP_MISSING`：声明的分层在总体中不存在。
- `STRATUM_UNPLANNED_GROUP`：总体中存在未声明的分层；其配额按 0 处理。
- `CLUSTER_OVERSHOOT`：整群纳入导致样本量超过目标，报告超出量。
- `CLUSTER_QUOTA_SHORT`：某被选整群的某次级分层配额超过该层实际行数。保留整群 take-all 结果，不补选新群或新主体；定位到 `cluster:<cluster>:<substratum>`，缺口写入警告与 `sample.metadata`。
- `CLUSTER_SUBSTRATA_MISSING`：被选整群未在 `cluster_substrata_weights` 中声明群内权重；该群按整群 take-all 保留，不静默扩样。
- `CLUSTER_SUBSTRATUM_UNPLANNED`：整群内存在未声明权重的次级分层；其配额按 0 处理，定位到 `cluster:<cluster>:<substratum>`。
- `SAMPLE_MISSING_STRATUM_VALUE` / `SAMPLE_MISSING_CLUSTER_VALUE`：字段值为空，归入空组并警告。

## 确定性与边界

- 随机性只来自 `seed`，并通过规范化的 `seed_effective` 传入各抽样器；不使用系统时间、进程 ID 或 `hash()`。
- 所有主键排序按 UTF-8 字节序。
- `rate` 的目标量为 `ceil(N * rate)`；`rate == 1` 时返回全部记录。
- 系统抽样：`k = floor(N / n)`；起点由生效种子决定；越界回绕一次；重复位置剔除并警告。
- 分层抽样未声明配额时，用最大余数法按组规模分配目标量；并列按分层名的 UTF-8 字节序决定。
- 整群抽样为一阶段整群、群内全取。声明 `cluster_substrata_field` 与 `cluster_substrata_weights` 后：
  1. 先用既有确定性规则选出整群集合，此步与未声明次级字段时完全一致，不得改变；
  2. 对每个被选群，以其行数（整群 take-all 的既定目标）为群内样本目标；
  3. 按 `权重 × 该层实际行数` 用最大余数法分摊到群内次级分层，余数并列按层次名的 UTF-8 字节序决定；
  4. 若某层配额超过该层实际行数，该群保留整群 take-all 结果，不补选新群或新主体，发出可定位到 `cluster:<cluster>:<substratum>` 的 `CLUSTER_QUOTA_SHORT`；
  5. 每群的群规模、群内分摊目标、各层实有/配额/实得写入 `sample.metadata.cluster_allocations`；
  6. 总样本数始终等于整群边界可容纳的目标量，绝不因分层配额静默扩大目标。
- 群内次级配额核验（`quota`）按方案权重与总体行数独立重算逐群结果，期望值等于该群可达的 take-all 分摊，不依赖抽样器元数据；缺口定位到 `cluster:<cluster>:<substratum>`。
- 数据集必须非空、主键必须存在且唯一；空值只统计不剔除。

## 完整示例

见仓库 `plans/` 下四个方案，以及仓库根目录 README 的最小示例。
