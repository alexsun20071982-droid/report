#!/usr/bin/env python3
"""
云端 → GitHub: 同步 cron/output/*.md 到 repo 的 dist/ 目录
未来加 cron 自动跑（如每天 03:00）
"""
import os
import sys
import glob
import re
import subprocess

REPO_DIR = os.environ.get('HERMES_REPO_DIR', '/home/ubuntu/hermes-report')
SRC_DIR = '/home/ubuntu/.hermes/cron/output'

def git(*args):
    return subprocess.run(['git', '-C', REPO_DIR] + list(args),
                          capture_output=True, text=True)

def main():
    if not os.path.isdir(REPO_DIR):
        print(f"❌ repo dir 不存在: {REPO_DIR}")
        sys.exit(1)

    dist = os.path.join(REPO_DIR, 'dist')
    os.makedirs(dist, exist_ok=True)

    count = 0
    # feynman-daily
    for f in sorted(glob.glob(f'{SRC_DIR}/feynman_daily_distill_*.md')):
        bn = os.path.basename(f)
        m = re.search(r'(\d{8})', bn)
        if m:
            dc = m.group(1)
            iso = f"{dc[:4]}-{dc[4:6]}-{dc[6:]}"
            target = os.path.join(dist, f'{iso}_feynman-daily.md')
            import shutil
            shutil.copy2(f, target)
            count += 1
    # feynman-weekly
    for f in sorted(glob.glob(f'{SRC_DIR}/feynman_weekly_*.md')):
        bn = os.path.basename(f)
        m = re.search(r'(\d{8})', bn)
        if m:
            dc = m.group(1)
            iso = f"{dc[:4]}-{dc[4:6]}-{dc[6:]}"
            target = os.path.join(dist, f'{iso}_feynman-weekly.md')
            import shutil
            shutil.copy2(f, target)
            count += 1
    # dual-carbon
    for f in sorted(glob.glob(f'{SRC_DIR}/dual_carbon_daily_*.md')):
        bn = os.path.basename(f)
        m = re.search(r'(\d{8})', bn)
        if m:
            dc = m.group(1)
            iso = f"{dc[:4]}-{dc[4:6]}-{dc[6:]}"
            target = os.path.join(dist, f'{iso}_dual-carbon.md')
            import shutil
            shutil.copy2(f, target)
            count += 1

    print(f"复制 {count} 个 .md")
    git('add', 'dist/')
    git('commit', '-m', f'sync: {count} cron output files')
    push = git('push', 'origin', 'main')
    print(push.stdout, push.stderr)

if __name__ == '__main__':
    main()
