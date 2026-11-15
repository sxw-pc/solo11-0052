# 归档包布局与校验清单

`python -m sample_attest export --task <task_id> --out <dir>` 从本地 SQLite 台账读取指定任务的最新一次运行，生成自描述归档目录。追加 `--with-history` 时，额外导出该 `task_id` 下全部运行历史（见下文“运行历史”）。

## 目录树

默认布局（与 1.0 版归档逐字节兼容）：

```text
<dir>/
├── manifest.json
├── plan.yaml
├── sample_keys.json
├── report.json
└── report.md
```

带 `--with-history` 的布局：

```text
<dir>/
├── manifest.json
├── history.json
├── plan.yaml
├── sample_keys.json
├── report.json
└── report.md
```

固定文件集合为 `plan.yaml`、`report.json`、`report.md`、`sample_keys.json`；开启历史导出时追加 `history.json`。导出会覆盖同名文件；清单只覆盖声明的内容文件。

| 文件 | 内容 |
|---|---|
| `plan.yaml` | 规范化方案副本（字段按字典序输出，含执行所需全部声明字段） |
| `sample_keys.json` | 排序后的样本主键数组，UTF-8、两空格缩进、末尾换行 |
| `report.json` | 机器可读报告：任务、总体、样本、三类指纹、全部核验项、归因条目、告警 |
| `report.md` | 人类可读报告：合规声明、摘要、核验表、归因、告警、可复现性说明 |
| `history.json` | 可选。同一 `task_id` 全部运行的历史轨迹与相邻运行样本键差异 |
| `manifest.json` | 归档清单，见下 |

## 运行历史（`history.json`）

仅在 `export --with-history` 时生成，顶层字段固定为 `task_id` 与 `runs`。`runs` 按 `run_id` 升序（即台账中的执行先后顺序）排列，每条运行的字段名与顺序口径固定：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | integer | 台账自增运行号 |
| `created_at` | string | 该次运行写入台账的 UTC ISO-8601 时间 |
| `status` | string | 该次运行的总体核验状态（`pass`/`warn`/`fail`） |
| `sample_fingerprint` | string | 该次运行的规范样本指纹（排序后 SHA-256） |
| `check_counts` | object | 核验计数 `{pass, warn, fail}` |
| `diff` | object | 相对上一次运行的样本键差异 `{added, missing}`，均按 UTF-8 字节序排序；首条运行没有前驱，两个列表均为空 |

`diff` 不做截断：归档面向审计，保留完整的新增（`added`，本次有、上次无）与缺失（`missing`，上次有、本次无）样本键。整个文件以 `json.dumps(ensure_ascii=False, indent=2, sort_keys=True)` 加末尾换行写入，因此同一台账、同一 `--now` 反复导出逐字节一致。

## `manifest.json` 字段

字段顺序固定为字典序（`json.dumps(sort_keys=True)`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `archive_version` | string | 当前为 `1.0` |
| `files` | object | 文件名 -> `{sha256, size}`；条目按文件名排序 |
| `generated_at` | string | 归档生成时间，UTC ISO-8601；唯一时间字段 |
| `plan_id` | string | 方案 ID |
| `population_fingerprint` | string | 总体名单 SHA-256 |
| `task_id` | string | 稳定任务号 |

示例：

```json
{
  "archive_version": "1.0",
  "files": {
    "plan.yaml": {"sha256": "<64 hex>", "size": 529},
    "report.json": {"sha256": "<64 hex>", "size": 5547},
    "report.md": {"sha256": "<64 hex>", "size": 2123},
    "sample_keys.json": {"sha256": "<64 hex>", "size": 327}
  },
  "generated_at": "2026-01-02T00:00:00Z",
  "plan_id": "stratified-basic",
  "population_fingerprint": "<64 hex>",
  "task_id": "<16 hex>"
}
```

## 确定性与时间戳

- 同一任务、同一导出实现、固定生成时间时，归档目录内全部文件逐字节一致（默认五个；带历史时六个）。
- `generated_at` 是 manifest 中唯一随导出时刻变化的字段；它不参与目录内文件哈希校验。
- `report.json` 本身包含该次抽样运行的 `generated_at`，但来自台账、导出时不会重写。
- `history.json` 的内容完全来自台账，时间字段取自各运行的 `created_at`，导出时刻不写入该文件。
- 测试通过 `--now` / `generated_at` 注入固定时间，避免测试对系统时钟的依赖。

## 校验流程

`python -m sample_attest verify-archive --dir <dir>`：

1. 读取 `manifest.json`；缺失或结构非法返回 `ARCHIVE_MANIFEST_INVALID`。
2. 拒绝绝对路径、目录跳转或空文件名。
3. 对 `files` 中每个条目按文件名排序检查存在性；缺失返回 `ARCHIVE_MISSING_FILE` 并定位文件名。
4. 重新计算每个文件 SHA-256；不一致返回 `ARCHIVE_HASH_MISMATCH` 并定位文件名。
5. 仅当哈希全部通过且清单声明了 `history.json` 时，才解析历史并做可复现性分析：
   - 文件结构非法或 `task_id` 与清单不一致，返回 `ARCHIVE_HISTORY_INVALID`。
   - 按 `run_id` 升序比较相邻运行的 `sample_fingerprint`；出现不同值即判定可复现性分叉（`reproducibility: "FORKED"`），并在 `forks` 中定位相邻 `run_id` 对（`previous_run_id`/`run_id`）与两侧指纹，代码为 `ARCHIVE_REPRODUCIBILITY_FORK`。
   - 分叉是审计发现而非归档损坏：归档整体仍为 `status: "VALID"`、退出码 0，结论放在输出的 `history` 字段中。
   - `history.json` 自身被篡改时第 4 步先行失败，结论为 `ARCHIVE_HASH_MISMATCH`，不会进入分叉分析。
6. 没有 `history.json` 的旧归档按原四文件格式校验：`{"status":"VALID","checked":4,...}`，退出码 0；否则退出码 5。

`manifest.json` 不对自身做哈希（自引用不可行），因此清单本身的修改由结构校验发现；受保护的是清单声明的内容文件。

## 安全边界

归档不包含外部 URL、凭据或云端配置，只包含本地台账中的方案副本、样本键与报告。归档的完整性不能替代数据访问授权；只能用于证明本地抽样过程的可追溯性与可复现性。
