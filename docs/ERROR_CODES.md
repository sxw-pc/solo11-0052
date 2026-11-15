# 错误码与警告码

所有码均为字符串常量，定义于 `sample_attest/codes.py`。测试断言代码而非文案。错误阻止执行并返回非零退出码；警告记录在报告与台账中，严格模式可将警告升级为失败。

## 方案加载与校验

| 代码 | 级别 | 触发条件 | 定位 |
|---|---|---|---|
| `PLAN_FILE_NOT_FOUND` | error | 方案文件不存在 | `plan.path` |
| `PLAN_PARSE_ERROR` | error | YAML 无法读取/解析 | `plan.path`/`plan` |
| `PLAN_NOT_MAPPING` | error | 根节点不是映射 | `plan` |
| `PLAN_MISSING_FIELD` | error | 必填字段缺失 | 具体字段路径 |
| `PLAN_TYPE_ERROR` | error | 字段类型错误 | 具体字段路径 |
| `PLAN_BAD_RANGE` | error | 数值超出允许范围 | 具体字段路径 |
| `PLAN_UNKNOWN_FIELD` | error | 未知顶层/嵌套字段 | 具体字段路径 |
| `PLAN_UNKNOWN_MODE` | error | mode 不是四种支持值之一 | `plan.mode` |
| `PLAN_CONFLICT` | error | size 与 rate 同时声明 | `plan.size` |
| `PLAN_FIELD_NOT_APPLICABLE` | error | 字段不适用于当前 mode | 具体字段路径 |
| `PLAN_BAD_CHECK` | error | 核验项类型/参数组合非法 | `plan.checks[i]...` |
| `PLAN_DUPLICATE_CHECK_ID` | error | 核验项 id 重复 | `plan.checks[i].id` |
| `PLAN_QUOTA_SUM_MISMATCH` | warning | 配额合计与 size 不一致 | `plan.expected_distribution` |
| `PLAN_INVALID` | error | CLI 对方案校验错误集合的聚合码 | stderr JSON |

## 数据集加载

| 代码 | 级别 | 触发条件 | 定位 |
|---|---|---|---|
| `DATASET_FILE_NOT_FOUND` | error | 数据集路径不存在 | `plan.dataset.path` |
| `DATASET_INVALID_FORMAT` | error | 格式不是 csv/jsonl | `plan.dataset.format` |
| `DATASET_ENCODING_ERROR` | error | 文件不是 UTF-8/UTF-8-SIG | `dataset.path` |
| `DATASET_PARSE_ERROR` | error | JSON 行非法、CSV 行长/表头异常 | `dataset.line`，含行号 |
| `DATASET_EMPTY` | error | 文件或数据行为空 | `dataset` |
| `DATASET_MISSING_KEY_FIELD` | error | CSV 表头/JSONL 行缺少主键字段 | `dataset.<key_field>` |
| `DATASET_MISSING_KEY` | error | 主键为空或不是标量 | `dataset.<key_field>`，含行号 |
| `DATASET_DUPLICATE_KEY` | error | 主键重复 | `dataset.<key_field>`，含当前/前次行号 |
| `DATASET_MISSING_SUBJECT_FIELD` | error | 声明了 `subject_field` 但 CSV 表头无该列 | `dataset.<subject_field>` |
| `DATASET_MISSING_SUBJECT` | error | 主体字段取值为空（JSONL 无表头时也用于缺列行） | `dataset.<subject_field>`，含行号 |
| `DATASET_BLANK_LINE` | warning | 空行被跳过 | `dataset.line`，含行号 |

## 抽样

| 代码 | 级别 | 触发条件 |
|---|---|---|
| `SAMPLE_EMPTY_POPULATION` | warning | 总体为空，样本为空 |
| `SAMPLE_TARGET_ZERO` | warning | 库级目标量为 0 |
| `SAMPLE_SIZE_EXCEEDS_POPULATION` | warning | 目标量超过总体，已截断 |
| `SAMPLE_DUPLICATE_POSITION` | warning | 系统抽样位置重复，已剔除 |
| `SAMPLE_SYSTEMATIC_WRAP` | warning | 系统抽样发生一次越界回绕 |
| `SAMPLE_EMPTY_STRATUM` | warning | 空分层边界 |
| `SAMPLE_MISSING_STRATUM_VALUE` | warning | 分层字段为空，归入空分层 |
| `STRATUM_QUOTA_SHORT` | warning | 分层可用记录少于配额，缺口被报告 |
| `STRATUM_GROUP_MISSING` | warning | 声明分层在总体中不存在 |
| `STRATUM_UNPLANNED_GROUP` | warning | 总体分层未在配额中声明 |
| `SAMPLE_EMPTY_CLUSTER` | warning | 空整群边界 |
| `SAMPLE_MISSING_CLUSTER_VALUE` | warning | 群字段为空，归入空群 |
| `CLUSTER_OVERSHOOT` | warning | 整群纳入导致样本量超目标 |

## 分布核验 / 可复现签验

| 代码 | 级别 | 触发条件 | 定位 |
|---|---|---|---|
| `CHECK_QUOTA_SHORT` | fail | 分层实际数少于声明配额 | `stratum:<name>` |
| `CHECK_QUOTA_OVER` | warn | 分层实际数大于声明配额 | `stratum:<name>` |
| `CHECK_RATE_OUT_OF_RANGE` | fail | 抽样率不在声明区间 | `verification.rate` |
| `CHECK_RATE_AT_BOUNDARY` | warn | 抽样率恰在区间端点 | `verification.rate` |
| `CHECK_COVERAGE_MISSING` | fail | 声明分组未被抽中 | `<field>:<group>` |
| `CHECK_COVERAGE_MINIMUM_ONLY` | warn | 声明分组仅抽中 1 条 | `<field>:<group>` |
| `CHECK_DUPLICATE_KEY` | fail | 样本主键重复 | `sample.keys` |
| `CHECK_KEY_OUTSIDE_POPULATION` | fail | 样本键不属于总体 | `sample.keys` |
| `CHECK_EMPTY_SAMPLE` | warn | 空样本无法完成该检查 | `sample.keys` |
| `CHECK_FIELD_NOT_FOUND` | fail | 覆盖字段不存在于数据集 | `field:<name>` |
| `VERIFY_NO_BASELINE` | error | 台账无同 plan_id 历史记录 | `verify` |
| `VERIFY_NOT_REPRODUCIBLE` | status/error | 当前指纹与基线不一致 | `verify` |

## 台账、归档与服务

| 代码 | 级别 | 触发条件 |
|---|---|---|
| `LEDGER_ERROR` | error | 保留的台账错误聚合码 |
| `LEDGER_TASK_NOT_FOUND` | error | 台账/HTTP 查询的任务不存在 |
| `ARCHIVE_TASK_NOT_FOUND` | error | 导出指定任务不存在 |
| `ARCHIVE_MANIFEST_INVALID` | error | 清单缺失、不可读或结构非法 |
| `ARCHIVE_MISSING_FILE` | error | 清单声明的文件不存在 |
| `ARCHIVE_HASH_MISMATCH` | error | 文件 SHA-256 与清单不符，定位文件名 |
| `SERVER_METHOD_NOT_ALLOWED` | error | 对只读接口执行写方法，HTTP 405 |
| `IO_ERROR` | error | CLI 文件系统 I/O 失败 |

## CLI 退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 运行成功；strict 无警告；verify 可复现；归档有效 |
| 1 | 核验结果失败（非 strict 升级） |
| 2 | 用法、方案、数据集、基线缺失或 I/O 错误 |
| 3 | strict 模式下存在警告 |
| 4 | verify 指纹不可复现 |
| 5 | 归档校验失败 |
