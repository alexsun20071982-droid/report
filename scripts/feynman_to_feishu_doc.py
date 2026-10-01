#!/usr/bin/env python3
"""
feynman/briefing .md → 飞书云文档（自动解析 Markdown）
========================================================
把 feynman 决策日报 / 周报 / briefing 等产出 .md 一键上传飞书云文档 + 完整 docx 附件。

工作流：
1. parse_markdown_to_blocks()  - markdown 解析为 block 列表
2. upload_markdown_to_feishu()  - 调 feishu_docx_upload_pipeline 上传

设计：
- 只识别 # ## ### 标题 + 普通段落 + bullet + emoji + 加粗
- 不解析表格（feynman 报告里没有表格，主要是标题+段落）
- 不解析代码块（也不在 feynman 里）
- 标题层级：# → 飞书标题1 (block_type=3)；## → 标题2 (4)；### → 标题3 (5)

用法：
  python3 feynman_to_feishu_doc.py --md /path/to/file.md --title "..."
  python3 feynman_to_feishu_doc.py --md /path/to/file.md --title "..." --dry-run
"""
import os
import sys
import re
import argparse
import json

# 复用现成的 pipeline
sys.path.insert(0, '/home/ubuntu/.hermes/skills/productivity/feishu-bitable/scripts')
from feishu_docx_upload_pipeline import build_docx, upload_to_drive, create_docx_cloud_doc, get_token


def parse_markdown_to_blocks(md_text: str) -> list:
    """
    简单 Markdown → 飞书 block 列表（feynman 风格适配）
    返回: list of dict {'type': 'heading1|heading2|heading3|paragraph|bullet', 'text': '...'}
    """
    blocks = []
    lines = md_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # 空行跳过
        if not line.strip():
            i += 1
            continue

        # 标题 # / ## / ###
        m = re.match(r'^(#{1,6})\s+(.+?)(?:\s+\{[^}]*\})?\s*$', line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1:
                blocks.append({'type': 'heading1', 'text': text})
            elif level == 2:
                blocks.append({'type': 'heading2', 'text': text})
            else:
                blocks.append({'type': 'heading3', 'text': text})
            i += 1
            continue

        # bullet (- * +)
        m = re.match(r'^[\-\*\+]\s+(.+)$', line)
        if m:
            blocks.append({'type': 'bullet', 'text': m.group(1).strip()})
            i += 1
            continue

        # 分隔线 ---
        if re.match(r'^---+$', line):
            blocks.append({'type': 'paragraph', 'text': '---'})
            i += 1
            continue

        # 引用 >
        m = re.match(r'^>\s*(.+)$', line)
        if m:
            blocks.append({'type': 'paragraph', 'text': '💬 ' + m.group(1).strip()})
            i += 1
            continue

        # 普通段落（合并连续行）
        para_lines = [line]
        j = i + 1
        while j < len(lines) and lines[j].rstrip() and not re.match(r'^(#{1,6}\s|[\-\*\+]\s|---+|>\s)', lines[j]):
            para_lines.append(lines[j].rstrip())
            j += 1

        para_text = ' '.join(para_lines).strip()
        if para_text:
            blocks.append({'type': 'paragraph', 'text': para_text})
        i = j

    return blocks


def blocks_to_sections(blocks: list) -> list:
    """
    把 blocks 转成 build_docx 用的 sections 格式
    sections: list of dict {'heading': '...', 'paras': [...], 'table': {...}}
    """
    sections = []
    current = {'heading': None, 'paras': []}

    for b in blocks:
        if b['type'] in ('heading1', 'heading2', 'heading3'):
            # 收尾当前 section
            if current['heading'] or current['paras']:
                sections.append(current)
            current = {'heading': b['text'], 'paras': []}
        else:
            current['paras'].append(b['text'])

    # 收尾最后
    if current['heading'] or current['paras']:
        sections.append(current)

    return sections


def upload_markdown_to_feishu(md_path: str, title: str, dry_run: bool = False) -> dict:
    """
    主流程：md → 解析 → 上传飞书 docs + docx 附件
    """
    print(f"=== 上传 markdown 到飞书 ===")
    print(f"文件: {md_path}")
    print(f"标题: {title}")
    print()

    # 1. 读 md
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()
    print(f"1. ✅ 读取 md ({len(md_text):,} chars)")

    # 2. 解析
    blocks = parse_markdown_to_blocks(md_text)
    print(f"2. ✅ 解析为 {len(blocks)} 个 block")
    print(f"   分布: {dict((b['type'], sum(1 for x in blocks if x['type']==b['type'])) for b in blocks)}")

    if dry_run:
        print()
        print("=== DRY RUN ===")
        print("前 5 个 block:")
        for b in blocks[:5]:
            print(f"  [{b['type']}] {b['text'][:80]}")
        print(f"...")
        return {'dry_run': True, 'block_count': len(blocks)}

    # 3. 上传
    print()
    print("3. 上传到飞书...")

    # 3a. 生成 .docx
    sections_data = blocks_to_sections(blocks)
    docx_out = f'/tmp/feishu_upload_{os.path.basename(md_path)}.docx'
    size = build_docx(docx_out, title, sections_data)
    print(f"   ✅ docx: {docx_out} ({size:,} bytes)")

    # 3b. 拿 token
    token = get_token()
    print(f"   ✅ token acquired")

    # 3c. 上传 Drive
    file_token, file_url = upload_to_drive(token, docx_out)
    print(f"   ✅ Drive file: {file_url}")

    # 3d. 建飞书云文档
    feishu_blocks = [
        {'type': 'paragraph', 'text': f'本报告由 Hermes 自动沉淀生成（基于 {os.path.basename(md_path)}）。'},
        {'type': 'paragraph', 'text': '完整 .docx 已上传到云文档附件（下方链接）。'},
        {'type': 'attached_docx', 'text': '📎 完整文档附件（点击下载）', 'url': file_url},
    ] + blocks  # 全部内容追加

    doc_token, doc_url = create_docx_cloud_doc(token, title, feishu_blocks)
    print(f"   ✅ 飞书 docs: {doc_url}")

    print()
    print("=== 最终链接 ===")
    print(f"飞书云文档: {doc_url}")
    print(f"docx 附件: {file_url}")

    return {
        'doc_token': doc_token,
        'doc_url': doc_url,
        'file_token': file_token,
        'file_url': file_url,
        'docx_path': docx_out,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--md', required=True, help='Markdown 文件路径')
    parser.add_argument('--title', required=True, help='飞书云文档标题')
    parser.add_argument('--dry-run', action='store_true', help='只解析不上传')
    args = parser.parse_args()

    upload_markdown_to_feishu(args.md, args.title, dry_run=args.dry_run)