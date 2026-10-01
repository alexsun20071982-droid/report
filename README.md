# Hermes Scripts — Cloud ↔ Local Agent Distribution

云端 nova-hermes 推 reader / publisher / upload 工具到这个 repo。
本地 agent (chinami-i9vjrvi) clone 后使用。

## 文件清单

| 文件 | 行数 | 谁用 | 作用 |
|---|---|---|---|
| `scripts/feishu_dist_reader.py` | 352 | 本地 agent | 拉飞书表 → 写 Vault → claim 防重 |
| `scripts/publish_dist_tasks.py` | 292 | 云端 cron | 发任务到飞书表（被 cron `publish-dist-tasks` 02:30 调） |
| `scripts/feynman_distill_to_dist_table.py` | 226 | 云端 cron | feynman .md → 写飞书表（被 cron 末尾 prompt 调） |
| `scripts/feynman_to_feishu_doc.py` | 198 | 云端工具 | .md → 飞书 docs + docx 附件 |

## 飞书表配置

| 项 | 值 |
|---|---|
| APP_TOKEN | `DBJybhPVbaU5jIsyUzNcHxnPn4b` |
| 养料分发中心 table_id | `tblBdLY8kX8gOqBJ` |
| schema | 21 字段（含 `local_claim_*` 4 字段） |

## 本地 agent 使用

```bash
# 1. Clone
git clone https://github.com/alexsun20071982-droid/report.git ~/.hermes-scripts

# 2. 设置飞书应用凭证（你 Windows 本地自己的）
export FEISHU_APP_ID="<your app id>"
export FEISHU_APP_SECRET="<your app secret>"
export FEISHU_APP_TOKEN="DBJybhPVbaU5jIsyUzNcHxnPn4b"

# 3. 跑 reader（dry-run 试一次）
python3 ~/.hermes-scripts/scripts/feishu_dist_reader.py \
    --agent-name local-hermes \
    --vault-root "D:/Users/Administrator/Documents/Obsidian Vault" \
    --limit 5 \
    --dry-run

# 4. 真跑（写入 Vault）
python3 ~/.hermes-scripts/scripts/feishu_dist_reader.py \
    --agent-name local-hermes \
    --vault-root "D:/Users/Administrator/Documents/Obsidian Vault" \
    --limit 10
```

## 双轨状态机

```
云端 status:  pending → read-by-{agent} → archived
本地 local_claim_status: unclaimed → claimed-by-local → completed-local / failed-local
```

## 同步流程

| 云端我（vm-0-15-ubuntu）| 本地你（chinami-i9vjrvi）|
|---|---|
| ✅ 改 reader 脚本 → `git push` | ✅ `git pull` |
| ✅ 跑 feynman/briefing cron | ✅ 跑 reader |
| ✅ publish_dist_tasks 自动 | ✅ 写 Vault |

## 历史

- 2026-09-30：初版 4 个脚本
- 双轨状态机设计完成
- 6 域 ontology 入 KG（45 triples + 42 entities）

## dist/ 目录
云端 cron 产出的 .md 同步到此目录，文件名格式 `YYYY-MM-DD_type.md`。

本地 agent 的 reader 会从 `md_local_path` 字段（值如 `dist/2026-09-29_feynman-daily.md`）找到对应 .md。

## 自动同步
云端 cron `publish-dist-tasks` 02:30 跑后会触发 `scripts/sync_dist_to_repo.py`，把新生成的 .md 同步到 repo。
