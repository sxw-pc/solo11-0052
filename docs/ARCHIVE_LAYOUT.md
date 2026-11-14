# 归档包布局与校验清单

`python -m sample_attest export --task <task_id> --out <dir>` 从本地 SQLite 台账读取指定任务的最新一次运行，生成自描述归档目录。

## 目录树

```text
<dir>/
├── manifest.json
├── plan.yaml
├── sample_keys.json
├── report.json
└── report.md
```

固定文件集合为 `plan.yaml`、`report.json`、`report.md`、`sample_keys.json`。导出会覆盖同名文件；清单只覆盖这四个文件。

| 文件 | 内容 |
|---|---|
| `plan.yaml` | 规范化方案副本（字段按字典序输出，含执行所需全部声明字段） |
| `sample_keys.json` | 排序后的样本主键数组，UTF-8、两空格缩进、末尾换行 |
| `report.json` | 机器可读报告：任务、总体、样本、三类指纹、全部核验项、归因条目、告警 |
| `report.md` | 人类可读报告：合规声明、摘要、核验表、归因、告警、可复现性说明 |
| `manifest.json` | 归档清单，见下 |

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

- 同一任务、同一导出实现、固定生成时间时，归档目录内五个文件逐字节一致。
- `generated_at` 是 manifest 中唯一随导出时刻变化的字段；它不参与目录内文件哈希校验。
- `report.json` 本身包含该次抽样运行的 `generated_at`，但来自台账、导出时不会重写。
- 测试通过 `--now` / `generated_at` 注入固定时间，避免测试对系统时钟的依赖。

## 校验流程

`python -m sample_attest verify-archive --dir <dir>`：

1. 读取 `manifest.json`；缺失或结构非法返回 `ARCHIVE_MANIFEST_INVALID`。
2. 拒绝绝对路径、目录跳转或空文件名。
3. 对 `files` 中每个条目按文件名排序检查存在性；缺失返回 `ARCHIVE_MISSING_FILE` 并定位文件名。
4. 重新计算每个文件 SHA-256；不一致返回 `ARCHIVE_HASH_MISMATCH` 并定位文件名。
5. 全部通过输出 `{"status":"VALID","checked":4,...}`，退出码 0；否则退出码 5。

`manifest.json` 不对自身做哈希（自引用不可行），因此清单本身的修改由结构校验发现；受保护的是四个内容文件。

## 安全边界

归档不包含外部 URL、凭据或云端配置，只包含本地台账中的方案副本、样本键与报告。归档的完整性不能替代数据访问授权；只能用于证明本地抽样过程的可追溯性与可复现性。
