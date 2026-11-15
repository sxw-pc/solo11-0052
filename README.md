# 抽样签验台（sample-attest）

**一句话定位：** 面向数据工程团队的纯本地、完全离线、确定性的抽样执行与抽样证据核验工具：把「这批样本怎么抽出来、是否符合方案、能否复现」变成可回查的本地审计记录。

## 是 / 不是

**是：**

- 声明式抽样方案（YAML）的解析、校验与执行引擎；
- 四种确定性抽样器：简单随机、分层、系统、整群；
- 抽样证据链：样本清单、总体名单指纹、有效种子、样本指纹、JSON/Markdown 报告；
- 分布一致性核验器：配额、抽样率区间、覆盖、主键唯一、总体包含；
- 可复现性签验器：同输入同方案同种子重跑应得到一致指纹，不同种子可定位差异样本；
- 本地 SQLite 台账与只读 HTTP 查询、归档包导出与校验。

**不是：** 不做统计推断、置信区间、加权/PPS/多阶段抽样、机器学习采样、Web 后台、用户权限、外部数据库/云服务、可视化图表或方案版本迁移。

## 合规声明

本工具仅用于对**本人所有或已获书面授权**的本地数据集进行抽样过程核验。程序运行期不发起任何网络请求，不连接外部数据库或对象存储；HTTP 服务只监听 `127.0.0.1`。仓库内所有示例、方案和 fixture 均为合成数据，不含真实密钥、真实域名、真实 IP 或真实个人信息。

## 安装与快速上手

依赖已列在 `requirements.txt`，安装后可长期离线运行：

```bash
python -m pip install -e .
```

三条核心命令：

```bash
# 1. 执行一次抽样，输出报告并写入本地台账
python -m sample_attest run --plan plans/stratified_basic.yaml --out out/

# 2. 启动只读本地 HTTP 服务（127.0.0.1:8765）
python -m sample_attest serve

# 3. 运行全部离线测试
pytest -q
# 或：make test
```

补充命令：

```bash
python -m sample_attest verify --plan plans/stratified_basic.yaml
python -m sample_attest export --task <task_id> --out out/archive
python -m sample_attest verify-archive --dir out/archive
```

默认台账位于 `.sample_attest/ledger.db`，可用 `--db` 覆盖。`dataset.path` 相对方案文件所在目录解析。

## 最小方案示例

```yaml
plan_id: stratified-basic
dataset:
  path: ../fixtures/population_stratified.csv
  format: csv
key_field: subject_id
mode: stratified
seed: 20260101
size: 18
strata_field: region
expected_distribution:
  region_A: 9
  region_B: 6
  region_C: 3
checks:
  - id: quota_region
    type: quota
  - id: rate_band
    type: rate_range
    min: 0.25
    max: 0.35
  - id: coverage_region
    type: coverage
    field: region
    groups: [region_A, region_B, region_C]
  - id: keys_unique
    type: key_unique
  - id: keys_in_population
    type: no_overlap
```

完整字段定义见 [`docs/PLAN_SPEC.md`](docs/PLAN_SPEC.md)。

## 四种抽样模式与约束

| 模式 | 约束与行为 |
|---|---|
| `random` | 对按字节序排序的主键执行显式播种 Fisher–Yates，取 `size` 或 `ceil(N * rate)`。 |
| `stratified` | 必须声明 `strata_field`；声明确切配额时按配额取，配额不足发 `STRATUM_QUOTA_SHORT` 警告且不静默补齐；未声明配额时按最大余数法分配目标量。可选声明 `subject_field`：同一主体可跨多行出现，先按最小主键行确定其唯一归属层，再按主体配额抽取并按主体去重。 |
| `systematic` | 字节序总体、间隔 `k = floor(N / n)`、起点由生效种子决定、等步长取键；越界回绕一次并剔除重复位置。 |
| `cluster` | 必须声明 `cluster_field`；先按种子打乱群顺序，再整群纳入直至达到目标行数。末群可导致超出目标，发 `CLUSTER_OVERSHOOT` 警告。 |

公共边界：`size`、`rate` 二选一且必须大于 0；`rate <= 1`；目标量超过总体时截断并警告；总体为空时稳定返回空样本与警告。不同种子会得到不同样本指纹，可通过 `verify` 定位新增/缺失键。

## 确定性指纹与可复现性

- 总体名单指纹：主键按 UTF-8 字节序排序后逐行加入 `sha256`，因此源文件行重排不改变指纹。
- 生效种子：`int(sha256(f"{seed}|{mode}|{population_hash}").hexdigest()[:16], 16)`。
- `sample_fingerprint` / `sample_fingerprint_sorted`：样本键排序后哈希，是规范指纹，顺序无关。
- `sample_fingerprint_ordered`：按抽样器输出顺序哈希，额外约束抽样顺序。
- `task_id`：由规范化方案内容、总体指纹与生效种子派生，同一输入重跑稳定。
- `verify` 以同 `plan_id` 最近一次台账记录为基线；指纹一致输出 `REPRODUCIBLE`，否则输出 `NOT_REPRODUCIBLE` 并列出最多 20 条新增/缺失样本键及总数。

## 本地台账与 HTTP 只读入口

SQLite 表 `task_runs` 记录：自增 `run_id`、`task_id`、`plan_id`、`population_fingerprint`、`sample_fingerprint`、`status`、`strict`、核验计数、方案副本、样本键、JSON/Markdown 报告和 `created_at`。同一任务可多次运行，`GET /tasks` 默认列出每个任务的最新一次。

| 端点 | 说明 |
|---|---|
| `GET /healthz` | 健康检查 |
| `GET /tasks` | 任务列表（最新运行，支持 `?limit=`） |
| `GET /tasks/<task_id>` | 单任务详情 |
| 其他写方法 | 一律 `405`，不提供触发抽样的 HTTP 接口 |

## 归档包

```text
archive/
├── manifest.json      # 文件名 -> sha256/size，含任务号、总体指纹、generated_at
├── plan.yaml          # 规范化方案副本
├── sample_keys.json   # 排序后的样本主键
├── report.json        # 机器可读报告
└── report.md          # 人类可读报告
```

`manifest.json` 字段按字典序稳定输出，文件条目也按文件名排序。`generated_at` 是唯一时间字段，不参与文件哈希校验；测试注入固定时钟，保证同输入同归档逐字节一致。`verify-archive` 复算每个文件的 SHA-256，篡改返回 `ARCHIVE_HASH_MISMATCH` 并定位文件名。详见 [`docs/ARCHIVE_LAYOUT.md`](docs/ARCHIVE_LAYOUT.md)。

## 明确不实现

- 不做分布假设检验、置信区间或统计推断。
- 不做跨库/跨文件联邦抽样。
- 不做加权抽样、PPS、多阶段抽样。
- 不做 SMOTE、训练/测试划分或任何机器学习采样管道。
- 不做 Web 方案编辑后台；HTTP 入口只读，不提供抽样触发写接口。
- 不做用户、会话、权限体系。
- 不接外部数据库、对象存储、消息队列或云服务。
- 不做结果可视化图表。
- 不做方案版本迁移与历史方案合并。

## 错误码 / 警告码索引

代码中的常量为唯一事实来源，详见 [`docs/ERROR_CODES.md`](docs/ERROR_CODES.md)。加载/方案错误退出码为 `2`。

| 类别 | 代码 |
|---|---|
| 方案加载/校验 | `PLAN_FILE_NOT_FOUND` `PLAN_PARSE_ERROR` `PLAN_NOT_MAPPING` `PLAN_MISSING_FIELD` `PLAN_TYPE_ERROR` `PLAN_BAD_RANGE` `PLAN_UNKNOWN_FIELD` `PLAN_UNKNOWN_MODE` `PLAN_CONFLICT` `PLAN_FIELD_NOT_APPLICABLE` `PLAN_BAD_CHECK` `PLAN_DUPLICATE_CHECK_ID` `PLAN_QUOTA_SUM_MISMATCH` `PLAN_INVALID` |
| 数据集 | `DATASET_FILE_NOT_FOUND` `DATASET_INVALID_FORMAT` `DATASET_ENCODING_ERROR` `DATASET_PARSE_ERROR` `DATASET_EMPTY` `DATASET_MISSING_KEY_FIELD` `DATASET_MISSING_KEY` `DATASET_DUPLICATE_KEY` `DATASET_MISSING_SUBJECT_FIELD` `DATASET_MISSING_SUBJECT` `DATASET_BLANK_LINE` |
| 抽样 | `SAMPLE_EMPTY_POPULATION` `SAMPLE_TARGET_ZERO` `SAMPLE_SIZE_EXCEEDS_POPULATION` `SAMPLE_DUPLICATE_POSITION` `SAMPLE_SYSTEMATIC_WRAP` `SAMPLE_EMPTY_STRATUM` `SAMPLE_MISSING_STRATUM_VALUE` `STRATUM_QUOTA_SHORT` `STRATUM_GROUP_MISSING` `STRATUM_UNPLANNED_GROUP` `SAMPLE_EMPTY_CLUSTER` `SAMPLE_MISSING_CLUSTER_VALUE` `CLUSTER_OVERSHOOT` |
| 核验 | `CHECK_QUOTA_SHORT` `CHECK_QUOTA_OVER` `CHECK_RATE_OUT_OF_RANGE` `CHECK_RATE_AT_BOUNDARY` `CHECK_COVERAGE_MISSING` `CHECK_COVERAGE_MINIMUM_ONLY` `CHECK_DUPLICATE_KEY` `CHECK_KEY_OUTSIDE_POPULATION` `CHECK_EMPTY_SAMPLE` `CHECK_FIELD_NOT_FOUND` `VERIFY_NO_BASELINE` `VERIFY_NOT_REPRODUCIBLE` |
| 台账/归档/服务 | `LEDGER_ERROR` `LEDGER_TASK_NOT_FOUND` `ARCHIVE_TASK_NOT_FOUND` `ARCHIVE_MANIFEST_INVALID` `ARCHIVE_MISSING_FILE` `ARCHIVE_HASH_MISMATCH` `SERVER_METHOD_NOT_ALLOWED` `IO_ERROR` |

CLI 退出码：`0` 成功/可复现；`1` 核验失败；`2` 用法或加载错误；`3` 严格模式下出现警告；`4` 指纹不可复现；`5` 归档校验失败。

## 测试与实测覆盖率

当前仓库包含 **130 个 pytest 用例**。测试 fixture 通过 autouse `monkeypatch` 将 `socket.socket` 与 `socket.create_connection` 替换为抛异常的桩，因此整个测试集运行期不会发起网络连接。为避开环境预装插件在事件循环 self-pipe 中创建本地 socket，`pyproject.toml` 的 pytest 配置显式禁用了无关的 `pytest-sanic` 插件。

实测（Python 3.13 / Windows 11）：

```text
pytest -q
130 passed

pytest -q --cov=sample_attest
TOTAL ... 88%   （branch 覆盖；目标 ≥80%）
```

## 仓库结构

```text
sample_attest/           # Python 包
  cli.py / engine.py     # 命令与编排
  plan_loader.py ...     # 方案、数据集、指纹
  samplers/              # 四种抽样器
  verifier*.py           # 核验与归因
  ledger.py / archive.py # 台账与归档
  server.py              # 只读 Flask
plans/                   # 示例方案（含主体分层 stratified_subject_*）
fixtures/                # 合成数据（含跨层多主体 population_subjects.csv）
tests/                   # 130 个离线测试
docs/                    # 方案规范、错误码、归档布局
```
