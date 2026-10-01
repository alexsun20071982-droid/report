#!/usr/bin/env python3
"""
发布云端养料到飞书「养料分发中心」表（任务发布器）
==================================================
扫描云端所有"适合入本地 Vault"的资料，批量写入飞书表，标记
local_claim_status=unclaimed，等待本地 agent 领取入库。

可作为独立脚本跑，也可被 cron 调用。

用法：
  # 默认：发过去 10 天的 feynman + 4 周周报 + 30 天 dual-carbon
  python3 publish_dist_tasks.py

  # 只发 feynman（日报 + 周报）
  python3 publish_dist_tasks.py --types feynman-daily feynman-weekly

  # dry-run（不发，看哪些会发）
  python3 publish_dist_tasks.py --dry-run
"""
import os
import sys
import re
import json
import argparse
import uuid
import time
from datetime import datetime
import urllib.request

sys.path.insert(0, '/home/ubuntu/.hermes/scripts')
from feishu_cred import APP_TOKEN, APP_ID, APP_SECRET

DIST_TABLE_ID = 'tblBdLY8kX8gOqBJ'
OUTPUT_DIR = '/home/ubuntu/.hermes/cron/output'


def get_token():
    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        data=json.dumps({'app_id': APP_ID, 'app_secret': APP_SECRET}).encode(),
        headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))['tenant_access_token']


def api(method, path, data=None):
    token = get_token()
    url = f'https://open.feishu.cn/open-apis{path}'
    req = urllib.request.Request(url,
        data=json.dumps(data, ensure_ascii=False).encode() if data else None,
        method=method,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        return json.load(urllib.request.urlopen(req, timeout=15))
    except Exception as e:
        return {'code': -1, 'msg': str(e)}


# 价值评估 + 默认配置
FILE_CONFIGS = {
    'feynman-daily': {
        'pattern': r'feynman_daily_distill_(\d{8})\.md$',
        'source_type': 'feynman-daily',
        'kg_source_file': 'feynman-daily-distill',
        'value': '⭐⭐⭐⭐⭐ 高价值',
        'default_vault_path': '2-养料精选/{YYYY-MM}/{title}.md',
        'confidence': 0.85,
    },
    'feynman-weekly': {
        'pattern': r'feynman_weekly_(\d{8})\.md$',
        'source_type': 'feynman-weekly',
        'kg_source_file': 'feynman-weekly-report',
        'value': '⭐⭐⭐⭐⭐ 高价值',
        'default_vault_path': '2-养料精选/{YYYY-MM周}/{title}.md',
        'confidence': 0.90,
    },
    'dual-carbon': {
        'pattern': r'dual_carbon_daily_(\d{8})\.md$',
        'source_type': 'dual-carbon',
        'kg_source_file': 'dual_carbon',
        'value': '⭐⭐⭐ 中价值',
        'default_vault_path': '2-养料精选/dual-carbon/{YYYY-MM}/{title}.md',
        'confidence': 0.70,
    },
}


def extract_summary(md_text: str) -> str:
    """从 .md 抽主话题摘要（前 3 个 🎯 话题）"""
    topics = re.findall(r'\*\*🎯\s*([^*]+)\*\*', md_text)
    if not topics:
        topics = re.findall(r'###\s*\*\*([^*]+)\*\*', md_text)
    if not topics:
        # fallback: 找首段
        return md_text.split('\n\n')[0][:500]
    summary = '、'.join([t.strip() for t in topics[:3]])
    if len(topics) > 3:
        summary += f'等 {len(topics)} 话题'
    return summary[:500] + ('...' if len(summary) > 500 else '')


def auto_category(md_text: str) -> list:
    """从 .md 自动识别 category"""
    keywords = {
        '跨境电商': ['跨境', '电商', '出海', '外贸'],
        '园区': ['园区', '招商', '产业图谱'],
        '投资': ['投资', 'ETF', '股票', '基金', '资本', '赛道', '渗透率'],
        '科技AI': ['AI', '大模型', 'agent', '智能体', 'OpenClaw', 'Hermes'],
        '供应链': ['供应链', '物流', '仓储', '运输'],
        '畜牧': ['畜牧', '养殖'],
        '能源': ['能源', '氢能', '光伏', '风电', '碳', '绿氢'],
    }
    matched = []
    for cat, words in keywords.items():
        for w in words:
            if w in md_text:
                matched.append(cat)
                break
    return matched if matched else ['其他']


def get_existing_dist_ids() -> set:
    """拉所有现有 dist_id，避免重复发"""
    result = api('GET', f'/bitable/v1/apps/{APP_TOKEN}/tables/{DIST_TABLE_ID}/records?page_size=100')
    if result.get('code') != 0:
        print(f"  ⚠️ 拉表失败: {result.get('msg')}")
        return set()

    existing = set()
    for r in result.get('data', {}).get('items', []):
        did = r['fields'].get('dist_id')
        if did:
            existing.add(did)
    return existing


def publish_one_md(md_path: str, file_type: str, cfg: dict, dry_run: bool = False) -> dict:
    """发单个任务到飞书表"""
    basename = os.path.basename(md_path)
    m = re.match(cfg['pattern'], basename)
    if not m:
        return {'skipped': True, 'reason': 'pattern_mismatch'}

    date_compact = m.group(1)  # YYYYMMDD
    date_obj = datetime.strptime(date_compact, '%Y%m%d')
    date_iso = date_obj.strftime('%Y-%m-%d')
    year_month = date_obj.strftime('%Y-%m')

    # 读 .md
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    summary = extract_summary(md_text)
    category = auto_category(md_text)

    # 默认 vault path
    is_weekly_path = '周' in cfg.get('default_vault_path', '')
    if is_weekly_path:
        # 周报：放周目录
        week_num = date_obj.isocalendar()[1]
        week_label = f'{year_month}-W{week_num:02d}'
        default_vault_path = cfg['default_vault_path'].replace('{YYYY-MM周}', week_label)
    else:
        default_vault_path = cfg['default_vault_path'].replace('{YYYY-MM}', year_month)

    is_weekly = 'weekly' in file_type
    if is_weekly:
        title_prefix = cfg["source_type"].split("-")[0].title() + ' 周报'
        title = f'{title_prefix} {date_iso}'
    else:
        title_prefix = cfg["source_type"].split("-")[0].title() + ' 日报'
        title = f'{title_prefix} {date_iso}'
    default_vault_path_full = default_vault_path.replace('{title}', re.sub(r'[\\/:*?"<>|]', '_', title))

    dist_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'{cfg["source_type"]}-{date_compact}'))

    fields = {
        'dist_id': dist_id,
        'created_at': str(int(time.time() * 1000)),
        'source_type': cfg['source_type'],
        'title': title,
        'summary': summary,
        'feishu_doc_url': '',  # 没生成 docs，留空（让本地 agent 直接拉 md_local_path）
        'docx_url': '',
        'md_local_path': md_path,
        'category': category,
        'tags': '',
        'kg_source_file': cfg['kg_source_file'],
        'vault_path': default_vault_path_full,  # 默认建议路径
        'status': 'pending',
        'confidence': str(cfg['confidence']),
        'local_claim_status': 'unclaimed',
        'local_claim_agent': '',
        'local_claim_at': '',
        'local_claim_vault_path': '',
        'notes': f'云端 Hermes 批量发布任务 ({cfg["value"]})',
    }

    if dry_run:
        return {'dry_run': True, 'dist_id': dist_id, 'title': title, 'path': md_path}

    result = api('POST', f'/bitable/v1/apps/{APP_TOKEN}/tables/{DIST_TABLE_ID}/records',
                 {'fields': fields})
    if result.get('code') == 0:
        return {'success': True, 'dist_id': dist_id, 'record_id': result['data']['record']['record_id']}
    else:
        return {'success': False, 'reason': result.get('msg')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--types', nargs='+',
                        choices=list(FILE_CONFIGS.keys()),
                        default=['feynman-daily', 'feynman-weekly', 'dual-carbon'],
                        help='要发的资料类型')
    parser.add_argument('--limit', type=int, default=50, help='每个类型最多发多少')
    parser.add_argument('--days', type=int, default=60, help='只看过去多少天')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"=== 任务发布器 ===")
    print(f"  types: {args.types}")
    print(f"  limit per type: {args.limit}")
    print(f"  days: {args.days}")

    # 拉现有 dist_id 避免重复
    if not args.dry_run:
        existing = get_existing_dist_ids()
        print(f"  现有 dist_ids: {len(existing)} 个")
    else:
        existing = set()

    total_success = 0
    total_skipped = 0
    total_failed = 0

    for file_type in args.types:
        cfg = FILE_CONFIGS[file_type]
        print(f"\n--- {file_type} ({cfg['value']}) ---")

        # 找符合的 .md
        matches = []
        for fname in os.listdir(OUTPUT_DIR):
            if re.match(cfg['pattern'], fname):
                full_path = os.path.join(OUTPUT_DIR, fname)
                if os.path.isfile(full_path):
                    matches.append(full_path)

        # 按日期排序
        matches.sort(reverse=True)

        # 限 days / limit
        count = 0
        for md_path in matches:
            if count >= args.limit:
                break

            # 检查日期范围（粗略）
            m = re.match(cfg['pattern'], os.path.basename(md_path))
            if m:
                date_obj = datetime.strptime(m.group(1), '%Y%m%d')
                days_old = (datetime.now() - date_obj).days
                if days_old > args.days:
                    continue

            # 检查 dist_id 是否已存在
            m = re.match(cfg['pattern'], os.path.basename(md_path))
            if m:
                date_compact = m.group(1)
                dist_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'{cfg["source_type"]}-{date_compact}'))
                if dist_id in existing:
                    total_skipped += 1
                    continue

            result = publish_one_md(md_path, file_type, cfg, dry_run=args.dry_run)
            if result.get('success') or result.get('dry_run'):
                total_success += 1
                count += 1
                if args.dry_run:
                    print(f"  [DRY] {result['title']}")
                else:
                    print(f"  ✅ {result.get('title', '?')} record={result.get('record_id', '')[:15]}")
            else:
                total_failed += 1
                print(f"  ❌ {os.path.basename(md_path)}: {result.get('reason', '?')}")

    print(f"\n=== 汇总 ===")
    print(f"  成功/拟发: {total_success}")
    print(f"  跳过（已存在）: {total_skipped}")
    print(f"  失败: {total_failed}")


if __name__ == '__main__':
    main()