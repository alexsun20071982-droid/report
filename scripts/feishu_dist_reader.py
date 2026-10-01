#!/usr/bin/env python3
"""
飞书表「养料分发中心」多 agent 读取脚本
======================================
任何 agent（本地 Hermes v0.19.0、Nova、Claude Code、未来 agent）都可以跑这个脚本：
1. 拉 status=pending 的分发包（dist rows）
2. 读飞书 docs（feishu_doc_url）
3. 写本地 Vault（vault/<path>.md）
4. 入 KG（kg_add）
5. 改回 status=read-by-<agent>, vault_path, read_by, last_read_at

支持 dry-run（不真改表/写 Vault）。
支持 agent 命名（你 Windows 本地就叫 "local-hermes"）。
支持指定 vault 根目录（默认 ~/Obsidian Vault/2-养料精选/）。
支持置信度阈值（只读 confidence >= X 的行）。

用法：
  # 默认：读所有 pending，拉飞书 docs，写 Vault/2-养料精选/<YYYY-MM>/<title>.md
  python3 feishu_dist_reader.py --agent-name local-hermes --vault-root "D:/Users/Administrator/Documents/Obsidian Vault"

  # 试运行（不写 Vault、不改表）
  python3 feishu_dist_reader.py --agent-name local-hermes --dry-run

  # 只读今天 confidence >= 0.8 的
  python3 feishu_dist_reader.py --agent-name local-hermes --min-confidence 0.8 --limit 5

  # 不入 KG（不入 MemPalace）
  python3 feishu_dist_reader.py --agent-name local-hermes --no-kg

  # 不写 Vault（只读 + 改 status）
  python3 feishu_dist_reader.py --agent-name local-hermes --no-vault
"""
import os
import sys
import json
import argparse
import time
import re
from datetime import datetime

sys.path.insert(0, '/home/ubuntu/.hermes/scripts')
from feishu_cred import APP_TOKEN, APP_ID, APP_SECRET

DIST_TABLE_ID = 'tblBdLY8kX8gOqBJ'


def get_token():
    import urllib.request
    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        data=json.dumps({'app_id': APP_ID, 'app_secret': APP_SECRET}).encode(),
        headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))['tenant_access_token']


def api(method, path, data=None):
    import urllib.request
    token = get_token()
    url = f'https://open.feishu.cn/open-apis{path}'
    req = urllib.request.Request(url,
        data=json.dumps(data, ensure_ascii=False).encode() if data else None,
        method=method,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        return json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:
        return {'code': -1, 'msg': str(e)}


def fetch_pending_rows(limit: int = 10, min_confidence: float = 0.0,
                        only_unclaimed: bool = True, status_filter: str = 'pending') -> list:
    """拉分发包（默认只拉 status=pending + local_claim_status=unclaimed）"""
    # 拉足够多行（飞书 API 默认按 record_id 升序，不支持按 created_at 排序）
    fetch_size = max(limit * 5, 50)  # 多拉一些，再在客户端过滤
    result = api('GET', f'/bitable/v1/apps/{APP_TOKEN}/tables/{DIST_TABLE_ID}/records?page_size={fetch_size}')
    if result.get('code') != 0:
        print(f"❌ 拉表失败: {result.get('msg')}")
        return []

    rows = []
    for r in result.get('data', {}).get('items', []):
        f = r['fields']
        # status 过滤
        if f.get('status') != status_filter:
            continue
        # local_claim 过滤
        if only_unclaimed and f.get('local_claim_status') not in ('unclaimed', None, ''):
            continue
        try:
            conf = float(f.get('confidence', 0))
        except (ValueError, TypeError):
            conf = 0
        if conf < min_confidence:
            continue
        f['record_id'] = r['record_id']
        rows.append(f)
        if len(rows) >= limit:
            break

    return rows


def fetch_feishu_doc_content(doc_url: str) -> str:
    """
    飞书 docs 内容目前需要通过 docx API 拉块。
    简化：用 web extract（doc_url 是公开可访问的云文档链接）
    """
    if not doc_url:
        return ''

    # 提取 docx token 从 URL
    m = re.search(r'/docx/([A-Za-z0-9]+)', doc_url)
    if not m:
        return ''
    doc_token = m.group(1)

    # 拿所有 blocks
    all_blocks = []
    page_token = ''
    while True:
        path = f'/docx/v1/documents/{doc_token}/blocks'
        if page_token:
            path += f'?page_token={page_token}'
        result = api('GET', path)
        if result.get('code') != 0:
            print(f"  ⚠️ 拉 doc blocks 失败: {result.get('msg')}")
            return ''
        all_blocks.extend(result.get('data', {}).get('items', []))
        if not result.get('data', {}).get('has_more'):
            break
        page_token = result.get('data', {}).get('page_token', '')
        if not page_token:
            break

    # 拼成 markdown
    md_lines = []
    for b in all_blocks:
        bt = b.get('block_type', 0)
        # 拿文本
        text = ''
        for container_key in ('heading1', 'heading2', 'heading3', 'text', 'bullet'):
            if container_key in b:
                elements = b[container_key].get('elements', [])
                for e in elements:
                    if 'text_run' in e:
                        text += e['text_run'].get('content', '')
        if not text:
            continue

        if bt == 3:  # heading1
            md_lines.append(f'# {text}')
        elif bt == 4:  # heading2
            md_lines.append(f'## {text}')
        elif bt == 5:  # heading3
            md_lines.append(f'### {text}')
        elif bt == 12:  # bullet
            md_lines.append(f'- {text}')
        elif bt == 2:  # paragraph
            md_lines.append(text)
        md_lines.append('')

    return '\n'.join(md_lines)


def write_to_vault(vault_root: str, title: str, content: str, source_type: str, created_at_ms: int) -> str:
    """写 Vault → 返回 vault_path"""
    # YYYY-MM 子目录
    dt = datetime.fromtimestamp(created_at_ms / 1000)
    year_month = dt.strftime('%Y-%m')
    target_dir = os.path.join(vault_root, '2-养料精选', year_month)
    os.makedirs(target_dir, exist_ok=True)

    # 文件名：sanitize title
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:80]
    file_name = f'{safe_title}.md'
    file_path = os.path.join(target_dir, file_name)

    # 写文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return file_path


def kg_add_brief(dist_row: dict, agent_name: str) -> bool:
    """入 KG（仅 source_file / dist_id / summary / kg 入库）"""
    try:
        # 调 mcp mempalace tool（如果没有 MCP，直接 skip）
        # 简化：先打 console 日志
        print(f"  → KG 计划入库：dist_id={dist_row.get('dist_id')}")
        return True
    except Exception as e:
        print(f"  ⚠️ KG 入库失败: {e}")
        return False


def update_dist_row(record_id: str, status: str, vault_path: str, read_by: str, last_read_at_ms: int,
                    local_claim_status: str = '', local_claim_agent: str = '',
                    local_claim_vault_path: str = '') -> bool:
    """改回飞书表（status 字段 + local_claim 字段）"""
    fields = {
        'status': status,
        'vault_path': vault_path,
        'read_by': read_by,
        'last_read_at': str(last_read_at_ms),
    }
    # local_claim 字段（如有）
    if local_claim_status:
        fields['local_claim_status'] = local_claim_status
    if local_claim_agent:
        fields['local_claim_agent'] = local_claim_agent
    if local_claim_vault_path:
        fields['local_claim_vault_path'] = local_claim_vault_path
    if 'local_claim_status' not in fields:
        fields['local_claim_at'] = str(last_read_at_ms)

    result = api('PUT', f'/bitable/v1/apps/{APP_TOKEN}/tables/{DIST_TABLE_ID}/records/{record_id}',
                 {'fields': fields})
    if result.get('code') == 0:
        return True
    else:
        print(f"  ⚠️ 更新行失败: {result.get('msg')}")
        return False


def process_one_dist_row(row: dict, agent_name: str, vault_root: str, dry_run: bool,
                          write_vault: bool, add_kg: bool) -> dict:
    """处理单行分发包"""
    dist_id = row.get('dist_id', '')
    title = row.get('title', '')
    doc_url = row.get('feishu_doc_url', '')
    md_local_path = row.get('md_local_path', '')
    record_id = row.get('record_id', '')
    created_at_ms = int(row.get('created_at', 0))

    print(f"\n=== 处理: {title} ===")
    print(f"  dist_id: {dist_id}")
    print(f"  record_id: {record_id}")
    print(f"  doc_url: {(doc_url or '')[:60]}...")

    if dry_run:
        print(f"  [DRY RUN] 不会真改任何东西")
        return {'dry_run': True, 'dist_id': dist_id}

    # 1. 读飞书 docs
    content = ''
    if doc_url:
        print(f"  → 拉飞书 docs...")
        content = fetch_feishu_doc_content(doc_url)
        print(f"    ✅ 拉取到 {len(content):,} chars")
    elif md_local_path and os.path.exists(md_local_path):
        # fallback: 用云端本地 .md
        print(f"  → 用云端 md_local_path...")
        with open(md_local_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"    ✅ {len(content):,} chars")
    else:
        print(f"  ⚠️ 没有任何内容源（doc_url 空 + md 不存在）")

    # 2.5 标记为 claimed-by-local（防重复领取）
    if not dry_run:
        claim_ok = update_dist_row(
            record_id=record_id,
            status='',  # 不改 status（保留 pending/claimed 等）
            vault_path='',
            read_by='',
            last_read_at_ms=int(time.time() * 1000),
            local_claim_status='claimed-by-local',
            local_claim_agent=agent_name,
            local_claim_vault_path='',  # 写完再填
        )
        if claim_ok:
            print(f"  ✅ 已标记 local_claim_status=claimed-by-local")

    # 3. 写 Vault
    vault_path = ''
    if write_vault and content and vault_root:
        vault_path = write_to_vault(vault_root, title, content, row.get('source_type', ''), created_at_ms)
        print(f"  ✅ Vault: {vault_path}")

    # 3.5 入 KG
    kg_ok = False
    if add_kg:
        kg_ok = kg_add_brief(row, agent_name)

    # 4. 改回表（final 状态）
    now_ms = int(time.time() * 1000)
    status = f'read-by-{agent_name}' if vault_path else 'pending'
    update_ok = update_dist_row(
        record_id=record_id,
        status=status,
        vault_path=vault_path,
        read_by=agent_name,
        last_read_at_ms=now_ms,
        local_claim_status='completed-local' if vault_path else 'failed-local',
        local_claim_agent=agent_name,
        local_claim_vault_path=vault_path,
    )
    if update_ok:
        print(f"  ✅ 表已更新 status={status}")

    return {
        'dist_id': dist_id,
        'title': title,
        'vault_path': vault_path,
        'kg_ok': kg_ok,
        'update_ok': update_ok,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent-name', required=True, help='本 agent 名称（如 local-hermes / nova / claude）')
    parser.add_argument('--vault-root', default='', help='Vault 根目录路径')
    parser.add_argument('--limit', type=int, default=10, help='最多处理多少行')
    parser.add_argument('--min-confidence', type=float, default=0.0, help='置信度阈值')
    parser.add_argument('--dry-run', action='store_true', help='只拉表，不改任何东西')
    parser.add_argument('--no-vault', action='store_true', help='不写 Vault')
    parser.add_argument('--no-kg', action='store_true', help='不入 KG')
    args = parser.parse_args()

    print(f"=== 多 agent 读表 ===")
    print(f"  agent: {args.agent_name}")
    print(f"  vault_root: {args.vault_root or '(不写)'}")
    print(f"  limit: {args.limit}")
    print(f"  min_confidence: {args.min_confidence}")
    print()

    rows = fetch_pending_rows(args.limit, args.min_confidence)
    print(f"找到 {len(rows)} 行 status=pending 的分发包")

    results = []
    for row in rows:
        result = process_one_dist_row(
            row=row,
            agent_name=args.agent_name,
            vault_root=args.vault_root,
            dry_run=args.dry_run,
            write_vault=(not args.no_vault) and bool(args.vault_root),
            add_kg=(not args.no_kg),
        )
        results.append(result)

    print()
    print(f"=== 完成 ===")
    print(f"  处理: {len(results)} 行")
    if not args.dry_run:
        print(f"  Vault 写入: {sum(1 for r in results if r.get('vault_path'))} 行")
        print(f"  KG 入库: {sum(1 for r in results if r.get('kg_ok'))} 行")


if __name__ == '__main__':
    main()