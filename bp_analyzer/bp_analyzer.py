#!/usr/bin/env python3
"""
BP Analyzer — 完整链路主入口
================================
一次性跑完：
1. PDF/PPT/Word 解析
2. 关键字段抽取
3. 产业链匹配
4. 决策报告生成

用法：
    python3 bp_analyzer.py /path/to/BP.pdf
    python3 bp_analyzer.py /path/to/BP.pdf --chains-dir /path/to/chains/ --feishu
"""
import os
import sys
import json
import argparse
import subprocess
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description='BP Analyzer — 一次性产出决策报告')
    parser.add_argument('bp_file', help='BP 文件路径（.pdf/.pptx/.docx）')
    parser.add_argument('--chains-dir', default='/home/ubuntu/.hermes/scripts/bp_analyzer/chains',
                        help='产业链图谱 JSON 目录')
    parser.add_argument('--feishu', action='store_true', help='生成后推飞书 docx')
    parser.add_argument('--no-demo-chain', action='store_true',
                        help='禁用 demo 产业链（用于测试）')
    parser.add_argument('--workdir', default='/tmp/bp_analyzer_out',
                        help='工作目录（存 .json / .md / .txt）')
    args = parser.parse_args()

    if not os.path.exists(args.bp_file):
        print(f"❌ 文件不存在: {args.bp_file}")
        sys.exit(1)

    # 准备
    os.makedirs(args.workdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.bp_file))[0]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    fields_json = os.path.join(args.workdir, f'{base}_{timestamp}.fields.json')
    chain_json = os.path.join(args.workdir, f'{base}_{timestamp}.chain_matches.json')
    report_md = os.path.join(args.workdir, f'{base}_{timestamp}.decision_report.md')

    # 1. 解析 BP
    print(f"\n{'='*60}")
    print(f"📄 Step 1: 解析 BP 文件")
    print(f"{'='*60}")
    parser_dir = '/home/ubuntu/.hermes/scripts/bp_analyzer/parsers'
    r = subprocess.run(
        ['python3', f'{parser_dir}/bp_parser.py', args.bp_file, '--json'],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"❌ 解析失败: {r.stderr}")
        sys.exit(1)

    # 把 fields 写到工作目录（parser 输出到原文件旁了，移过来）
    src_fields = args.bp_file + '.fields.json'
    if os.path.exists(src_fields):
        import shutil
        shutil.copy(src_fields, fields_json)
        os.remove(src_fields)
    src_txt = args.bp_file + '.extracted.txt'
    if os.path.exists(src_txt):
        os.remove(src_txt)

    with open(fields_json, 'r', encoding='utf-8') as f:
        fields = json.load(f)

    print(f"✅ 解析完成: {fields.get('pages', '?')} 页, {fields.get('text_length', 0):,} 字符")
    print(f"   公司: {fields.get('company_name') or '⚠️ 未识别'}")

    # 2. 产业链匹配
    print(f"\n{'='*60}")
    print(f"🏭 Step 2: 产业链匹配")
    print(f"{'='*60}")

    # 默认建 demo 产业链（用户后续可加自己的）
    if not args.no_demo_chain and not os.path.isdir(args.chains_dir):
        os.makedirs(args.chains_dir, exist_ok=True)
        demo_path = os.path.join(args.chains_dir, 'demo_biodegradable_plastic.json')
        if not os.path.exists(demo_path):
            from mappers.chain_mapper import DEMO_CHAIN
            with open(demo_path, 'w', encoding='utf-8') as f:
                json.dump(DEMO_CHAIN, f, ensure_ascii=False, indent=2)
            print(f"   已创建 demo 产业链: {demo_path}")

    mapper_dir = '/home/ubuntu/.hermes/scripts/bp_analyzer/mappers'
    r = subprocess.run(
        ['python3', f'{mapper_dir}/chain_mapper.py', fields_json, args.chains_dir],
        capture_output=True, text=True
    )
    print(r.stdout[:500])

    # 移动 chain_matches
    src_chain = fields_json + '.chain_matches.json'
    if os.path.exists(src_chain):
        import shutil
        shutil.copy(src_chain, chain_json)
        os.remove(src_chain)

    if os.path.exists(chain_json):
        with open(chain_json, 'r', encoding='utf-8') as f:
            chain_matches = json.load(f)
        print(f"✅ 命中 {len(chain_matches)} 条产业链")
    else:
        chain_matches = []
        print(f"⚠️ 未命中产业链")

    # 3. 生成报告
    print(f"\n{'='*60}")
    print(f"📊 Step 3: 生成决策报告")
    print(f"{'='*60}")

    output_dir = '/home/ubuntu/.hermes/scripts/bp_analyzer/outputs'
    r = subprocess.run(
        ['python3', f'{output_dir}/report_generator.py', fields_json, chain_json],
        capture_output=True, text=True
    )

    src_report = fields_json.replace('.fields.json', '.decision_report.md')
    if os.path.exists(src_report) and os.path.abspath(src_report) != os.path.abspath(report_md):
        import shutil
        shutil.copy(src_report, report_md)
        os.remove(src_report)
    elif os.path.exists(report_md):
        # report_generator 已经写到正确位置
        pass

    print(f"✅ 报告: {report_md}")
    print(f"\n📁 产出物:")
    print(f"   - {fields_json}")
    print(f"   - {chain_json}")
    print(f"   - {report_md}")

    # 4. 飞书推送
    if args.feishu and os.path.exists(report_md):
        print(f"\n{'='*60}")
        print(f"📤 Step 4: 推飞书 docx")
        print(f"{'='*60}")
        r = subprocess.run(
            ['python3', '/home/ubuntu/.hermes/scripts/feynman_to_feishu_doc.py',
             '--md', report_md,
             '--title', f"BP 决策分析报告 - {fields.get('company_name') or base} ({datetime.now().strftime('%Y-%m-%d')})"],
            capture_output=True, text=True
        )
        print(r.stdout)
        if r.stderr:
            print(f"stderr: {r.stderr[:300]}")

    print(f"\n{'='*60}")
    print(f"🎉 完成！")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()