#!/usr/bin/env python3
"""
feynman_daily_distill / feynman_weekly_report → 飞书表「养料分发中心」
=====================================================================
由 feynman-daily-distill / feynman-weekly-report cron 在产出 .md 后调用。
自动读 .md → 抽 summary + 分类 → 写飞书表 + 生成飞书 docs。

用法：
  # 日报模式
  python3 feynman_distill_to_dist_table.py --date 2026-09-29

  # 周报模式
  python3 feynman_distill_to_dist_table.py --date 2026-09-29 --weekly

  # 完整流程（含生成飞书 docs + docx 附件）
  python3 feynman_distill_to_dist_table.py --date 2026-09-29 --with-feishu-docs

  # Dry-run
  python3 feynman_distill_to_dist_table.py --date 2026-09-29 --dry-run
"""
import os
import sys
import re
import json
import argparse
import uuid
import time
import subprocess

# 让脚本可以独立跑
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, '/home/ubuntu/.hermes/scripts')

from feishu_cred import APP_TOKEN, APP_ID, APP_SECRET

# 养料分发中心 table_id
DIST_TABLE_ID = 'tblBdLY8kX8gOqBJ'

# feynman 输出目录
FEYNMAN_OUT_DIR = '/home/ubuntu/.hermes/cron/output'


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


def extract_summary(md_text: str, max_chars: int = 500) -> str:
    """从 .md 抽主话题摘要（前 3 个 🎯 话题）"""
    # 找所有 "**🎯 话题名**" 行
    topics = re.findall(r'\*\*🎯\s*([^*]+)\*\*', md_text)
    if not topics:
        topics = re.findall(r'###\s*\*\*([^*]+)\*\*', md_text)
    if not topics:
        return md_text.split('\n\n')[0][:max_chars]

    summary = '、'.join([t.strip() for t in topics[:3]])
    if len(topics) > 3:
        summary += f'等 {len(topics)} 话题'
    if len(summary) > max_chars:
        summary = summary[:max_chars] + '...'
    return summary


def auto_category(md_text: str) -> list:
    """从 .md 自动识别 category（多选）"""
    keywords = {
        '跨境电商': ['跨境', '电商', '出海', '外贸'],
        '园区': ['园区', '招商', '产业图谱', '产业园'],
        '投资': ['投资', 'ETF', '股票', '基金', '资本', '赛道'],
        '科技AI': ['AI', '大模型', 'OpenClaw', 'Hermes', 'agent', '智能体', '模型'],
        '供应链': ['供应链', '物流', '仓储', '运输'],
        '畜牧': ['畜牧', '养殖', '猪', '鸡'],
        '能源': ['能源', '氢能', '光伏', '风电', '碳'],
    }
    matched = []
    for cat, words in keywords.items():
        for w in words:
            if w in md_text:
                matched.append(cat)
                break
    return matched if matched else ['其他']


def upload_md_to_feishu_docs(md_path: str, title: str) -> dict:
    """
    调 feynman_to_feishu_doc.py 生成飞书 docs + docx 附件
    返回 {doc_url, file_url}
    """
    feynman_doc_script = '/home/ubuntu/.hermes/scripts/feynman_to_feishu_doc.py'
    if not os.path.exists(feynman_doc_script):
        return {'doc_url': '', 'file_url': ''}

    cmd = ['python3', feynman_doc_script, '--md', md_path, '--title', title]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # 解析最后的链接
        doc_url = ''
        file_url = ''
        for line in result.stdout.split('\n'):
            if '飞书云文档:' in line:
                doc_url = line.split('飞书云文档:')[-1].strip()
            elif 'docx 附件:' in line:
                file_url = line.split('docx 附件:')[-1].strip()
        return {'doc_url': doc_url, 'file_url': file_url}
    except Exception as e:
        print(f"  ⚠️ 上传 docs 失败: {e}")
        return {'doc_url': '', 'file_url': ''}


def write_to_dist_table(date: str, weekly: bool = False, dry_run: bool = False, with_docs: bool = False) -> dict:
    """主流程"""
    date_compact = date.replace('-', '')  # 20260929

    # 1. 找 .md
    if weekly:
        md_filename = f'feynman_weekly_{date_compact}.md'
        source_type = 'feynman-weekly'
        title = f'Feynman 周报 {date}'
        kg_source_file = 'feynman-weekly-report'
    else:
        md_filename = f'feynman_daily_distill_{date_compact}.md'
        source_type = 'feynman-daily'
        title = f'Feynman 决策日报 {date}'
        kg_source_file = 'feynman-daily-distill'

    md_path = os.path.join(FEYNMAN_OUT_DIR, md_filename)

    print(f"=== feynman → 养料分发中心 ===")
    print(f"  date: {date}, weekly: {weekly}")
    print(f"  md: {md_path}")
    print(f"  source_type: {source_type}")

    if not os.path.exists(md_path):
        print(f"  ❌ .md 不存在: {md_path}")
        return {'success': False, 'reason': 'md_not_found'}

    # 2. 读 + 抽 summary + category
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    summary = extract_summary(md_text)
    category = auto_category(md_text)
    print(f"  summary: {summary[:80]}...")
    print(f"  category: {category}")

    # 3. 上传飞书 docs（如果 with_docs）
    doc_url = ''
    file_url = ''
    if with_docs:
        print(f"  → 上传飞书 docs...")
        docs_result = upload_md_to_feishu_docs(md_path, title)
        doc_url = docs_result.get('doc_url', '')
        file_url = docs_result.get('file_url', '')
        print(f"    ✅ doc_url: {doc_url[:60]}...")
        print(f"    ✅ file_url: {file_url[:60]}...")

    # 4. 写飞书表
    fields = {
        'dist_id': str(uuid.uuid4()),
        'created_at': str(int(time.time() * 1000)),
        'source_type': source_type,
        'title': title,
        'summary': summary,
        'feishu_doc_url': doc_url,
        'docx_url': file_url,
        'md_local_path': md_path,
        'category': category,
        'tags': '',  # cron agent 可以人工补
        'kg_source_file': kg_source_file,
        'status': 'pending',
        'confidence': '0.85',
        'notes': f'云端 Hermes 自动沉淀（{source_type}）',
    }

    if dry_run:
        print()
        print('=== DRY RUN（未写入）===')
        print(json.dumps(fields, ensure_ascii=False, indent=2))
        return {'success': True, 'dry_run': True, 'fields': fields}

    print()
    print('  → 写入飞书表...')
    result = api('POST', f'/bitable/v1/apps/{APP_TOKEN}/tables/{DIST_TABLE_ID}/records',
                 {'fields': fields})
    if result.get('code') == 0:
        record_id = result['data']['record']['record_id']
        print(f"  ✅ 写入成功 record_id={record_id}")
        return {'success': True, 'record_id': record_id, 'fields': fields}
    else:
        print(f"  ❌ 写入失败: {result.get('msg')}")
        return {'success': False, 'reason': result.get('msg'), 'result': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True, help='日期 YYYY-MM-DD')
    parser.add_argument('--weekly', action='store_true', help='周报模式')
    parser.add_argument('--with-feishu-docs', action='store_true', help='同时生成飞书 docs')
    parser.add_argument('--dry-run', action='store_true', help='只解析不写表')
    args = parser.parse_args()

    write_to_dist_table(
        date=args.date,
        weekly=args.weekly,
        dry_run=args.dry_run,
        with_docs=args.with_feishu_docs,
    )