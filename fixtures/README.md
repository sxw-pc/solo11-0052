# 合成 Fixture 说明

本目录所有数据均为程序生成的合成数据，仅用于离线测试与示例。
标识符使用 `subject_NNNN`、`region_A/B/C`、`cluster_NN` 等可辨识假值，
不包含任何真实个人、企业、域名或网络地址。

| 文件 | 行数（不含表头） | 用途 |
|---|---:|---|
| `population_small.csv` | 30 | 简单随机与系统抽样示例 |
| `population_stratified.csv` | 60 | 分层配额与分布核验示例 |
| `population_cluster.jsonl` | 48 | 整群抽样示例 |

字段均为字符串（JSONL 的 `sequence` 为整数，加载后规范化为字符串）。
数据集主键字段为 `subject_id`，全文件唯一。
