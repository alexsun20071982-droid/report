#!/usr/bin/env python3
"""
BP 决策报告生成器 — 招商 + 投资双视角
=========================================
输入：BP 字段 + 产业链匹配结果
输出：结构化 Markdown 报告（可上飞书 docx）
"""
import os
import json
from datetime import datetime
from typing import Dict, List, Optional


def gen_zhaoshang_section(fields: Dict, chain_match: Dict) -> Dict:
    """
    招商视角评估（园区操盘手 + 招商经理）
    关注：产业链补强、税收贡献、就业、用地需求、能耗
    """
    sections = []
    score = 0  # 总分 100

    # 1. 产业链补强
    chain_score = 0
    chain_note = ''
    if chain_match and chain_match.get('matched_count', 0) > 0:
        chain_score = 30
        chain_note = f"命中 {chain_match['matched_count']} 个产业链节点（{chain_match['chain_name']}），对园区产业链是补强"

        # 上下游关系
        first_match = chain_match['matches'][0]
        if first_match.get('tier') == 'midstream':
            chain_note += "\n- 项目处于产业链中游，**带动效应强**（上游原料 + 下游应用）"
            chain_score += 10
        elif first_match.get('tier') == 'downstream':
            chain_note += "\n- 项目处于产业链下游，**终端市场导向**，但带动效应较弱"
            chain_score += 5
        elif first_match.get('tier') == 'upstream':
            chain_note += "\n- 项目处于产业链上游，**基础原料供给**，需要规模化才能盈利"
            chain_score += 5
    else:
        chain_note = "⚠️ 项目未命中本地产业链图谱——需要评估是否引入新产业链"

    score += chain_score
    sections.append({
        'title': '1. 产业链补强价值',
        'score': chain_score,
        'max': 40,
        'note': chain_note,
    })

    # 2. 就业 + 税收潜力（启发式）
    headcount_note = '需要补充实地访谈'
    score += 15  # 默认给个基础分
    sections.append({
        'title': '2. 就业贡献潜力',
        'score': 15,
        'max': 25,
        'note': f"BP 提及融资: {fields.get('fundings', '未识别')}，估值: {fields.get('valuation', '未识别')}\n{headcount_note}",
    })

    # 3. 政策合规（双碳/ESG/出口管制）
    green_keywords = ['新能源', '光伏', '氢能', '储能', '降解', '碳中和', 'ESG', 'PHA', 'PLA', 'PBS', '合成生物学', '生物基', '生物制造']
    has_green = any(k in fields.get('technologies', []) or k in ' '.join(fields.get('products', [])) for k in green_keywords)
    policy_score = 25 if has_green else 15
    policy_note = ''
    if has_green:
        policy_note = "✅ 项目涉及绿色/双碳领域，**符合地方政策导向**，可申请补贴"
    else:
        policy_note = "⚠️ 项目不属于双碳/绿色领域，需评估产业准入政策"

    score += policy_score
    sections.append({
        'title': '3. 政策合规性',
        'score': policy_score,
        'max': 25,
        'note': policy_note,
    })

    # 4. 入驻成本评估
    sections.append({
        'title': '4. 入驻成本（需补充）',
        'score': 0,
        'max': 10,
        'note': '实地访谈评估：用地需求 / 厂房面积 / 能耗 / 环评',
    })

    return {
        'perspective': '招商',
        'total_score': score,
        'max_score': 100,
        'sections': sections,
        'summary': _zhaoshang_summary(score, chain_match),
    }


def gen_investment_section(fields: Dict, chain_match: Dict) -> Dict:
    """
    投资视角评估（基金投资人 + 投资经理）
    关注：团队、技术壁垒、市场规模、对标、估值合理性、退出路径
    """
    sections = []
    score = 0

    # 1. 团队
    founders = fields.get('founders', [])
    if len(founders) >= 2:
        team_score = 25
        team_note = f"✅ 创始人 {len(founders)} 人（{', '.join(founders[:3])}），团队完整度好"
    elif len(founders) == 1:
        team_score = 15
        team_note = f"⚠️ 仅识别 1 位创始人: {founders[0]}，需补充背景调研"
    else:
        team_score = 5
        team_note = "⚠️ 未识别创始人信息，必须补充尽调"

    score += team_score
    sections.append({
        'title': '1. 团队背景',
        'score': team_score,
        'max': 25,
        'note': team_note,
    })

    # 2. 技术壁垒
    techs = fields.get('technologies', [])
    has_hard_tech = any(t in techs for t in ['AI', '半导体', '生物技术', '新材料', '合成生物学', 'CRISPR', '基因编辑'])
    tech_score = 25 if has_hard_tech else (15 if techs else 5)
    tech_note = ''
    if has_hard_tech:
        tech_note = f"✅ 硬科技领域，技术关键词: {', '.join(techs[:8])}"
    elif techs:
        tech_note = f"⚠️ 技术门槛较低，需评估差异化（{', '.join(techs[:5])}）"
    else:
        tech_note = "⚠️ 未识别技术关键词，需查专利数据库"

    score += tech_score
    sections.append({
        'title': '2. 技术壁垒',
        'score': tech_score,
        'max': 25,
        'note': tech_note,
    })

    # 3. 市场规模
    market_sizes = fields.get('market_size', [])
    if len(market_sizes) >= 2:
        market_score = 20
        market_note = f"✅ 市场规模数据完整: {', '.join(market_sizes[:3])}"
    elif market_sizes:
        market_score = 15
        market_note = f"⚠️ 市场规模数据有限: {market_sizes[0]}，需第三方报告验证"
    else:
        market_score = 5
        market_note = "⚠️ BP 未提供市场规模，需灼识/沙利文报告补充"

    score += market_score
    sections.append({
        'title': '3. 市场规模',
        'score': market_score,
        'max': 20,
        'note': market_note,
    })

    # 4. 估值合理性
    valuation = fields.get('valuation', '')
    fundings = fields.get('fundings', [])
    if valuation or fundings:
        val_score = 15
        val_note = f"BP 提及估值: {valuation or '未识别'}, 融资: {fundings[:3] or '未识别'}\n需交叉验证最后一轮融资的估值倍数"
    else:
        val_score = 5
        val_note = "⚠️ BP 未提供融资/估值数据，需向创始人追问"

    score += val_score
    sections.append({
        'title': '4. 估值合理性',
        'score': val_score,
        'max': 15,
        'note': val_note,
    })

    # 5. 退出路径
    sections.append({
        'title': '5. 退出路径（需补充）',
        'score': 0,
        'max': 15,
        'note': '评估：并购退出可能性 / IPO 时间表 / 战投接盘意愿',
    })

    return {
        'perspective': '投资',
        'total_score': score,
        'max_score': 100,
        'sections': sections,
        'summary': _investment_summary(score, chain_match),
    }


def _zhaoshang_summary(score: int, chain_match: Dict) -> str:
    if score >= 80:
        return "🟢 **强推荐招引**——产业链补强好 + 政策合规，可考虑给予入驻优惠"
    elif score >= 60:
        return "🟡 **可考虑**——具备一定价值，需实地评估入驻成本"
    elif score >= 40:
        return "🟠 **谨慎评估**——价值有限，需明确入驻成本后再决策"
    else:
        return "🔴 **不建议招引**——未命中产业链 / 政策风险高"


def _investment_summary(score: int, chain_match: Dict) -> str:
    if score >= 80:
        return "🟢 **强推荐深入尽调**——团队 + 技术 + 市场均优秀"
    elif score >= 60:
        return "🟡 **继续跟踪**——基本面可，需补关键数据"
    elif score >= 40:
        return "🟠 **观望**——某维度有明显短板，需针对性补足"
    else:
        return "🔴 **不建议投入**——多维度不达标"


def render_report(
    fields: Dict,
    chain_matches: List[Dict],
    zhaoshang: Dict,
    investment: Dict,
    file_name: str = ''
) -> str:
    """
    渲染成 Markdown
    """
    today = datetime.now().strftime('%Y-%m-%d')
    md_lines = []

    md_lines.append(f"# 📊 BP 决策分析报告")
    md_lines.append(f"\n**生成日期**: {today}")
    md_lines.append(f"**文件**: {file_name or fields.get('source_file', '?')}")
    md_lines.append(f"**页数**: {fields.get('pages', '?')}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    # Section 1: 公司基本信息
    md_lines.append("## 📌 1. 公司基本信息")
    md_lines.append("")
    md_lines.append(f"| 项目 | 内容 |")
    md_lines.append(f"|---|---|")
    md_lines.append(f"| **公司名** | {fields.get('company_name') or '⚠️ 未识别'} |")
    md_lines.append(f"| **创始人** | {', '.join(fields.get('founders', [])) or '⚠️ 未识别'} |")
    md_lines.append(f"| **融资历史** | {fields.get('fundings') or '⚠️ 未识别'} |")
    md_lines.append(f"| **估值** | {fields.get('valuation') or '⚠️ 未识别'} |")
    md_lines.append(f"| **行业** | {', '.join(fields.get('industries', [])) or '⚠️ 未识别'} |")
    md_lines.append("")

    # Section 2: 核心产品
    md_lines.append("## 🎯 2. 核心产品")
    md_lines.append("")
    products = fields.get('products', [])
    if products:
        for i, p in enumerate(products, 1):
            md_lines.append(f"{i}. {p}")
    else:
        md_lines.append("⚠️ BP 未识别到明确产品列表")
    md_lines.append("")
    md_lines.append(f"**技术关键词**: {', '.join(fields.get('technologies', [])) or '⚠️ 未识别'}")
    md_lines.append("")

    # Section 3: 产业链定位
    md_lines.append("## 🏭 3. 产业链定位")
    md_lines.append("")
    if chain_matches:
        for cm in chain_matches[:3]:
            md_lines.append(f"### 📐 {cm['chain_name']} ({cm['chain_file']})")
            md_lines.append(f"- 命中节点: **{cm['matched_count']}** 个")
            for m in cm['matches'][:5]:
                md_lines.append(f"  - [{m['tier']}] {m['node_name']} (匹配: {m['matched_term']}, {m['match_type']})")
            md_lines.append("")
    else:
        md_lines.append("⚠️ 项目未匹配到本地产业链图谱")
    md_lines.append("")

    # Section 4: 招商视角
    md_lines.append("## 🤝 4. 招商视角评估")
    md_lines.append("")
    md_lines.append(f"**总分**: {zhaoshang['total_score']} / {zhaoshang['max_score']}")
    md_lines.append("")
    md_lines.append(f"**结论**: {zhaoshang['summary']}")
    md_lines.append("")
    for s in zhaoshang['sections']:
        md_lines.append(f"### {s['title']} ({s['score']}/{s['max']})")
        md_lines.append(s['note'])
        md_lines.append("")

    # Section 5: 投资视角
    md_lines.append("## 💰 5. 投资视角评估")
    md_lines.append("")
    md_lines.append(f"**总分**: {investment['total_score']} / {investment['max_score']}")
    md_lines.append("")
    md_lines.append(f"**结论**: {investment['summary']}")
    md_lines.append("")
    for s in investment['sections']:
        md_lines.append(f"### {s['title']} ({s['score']}/{s['max']})")
        md_lines.append(s['note'])
        md_lines.append("")

    # Section 6: 下一步建议
    md_lines.append("## 📋 6. 下一步建议")
    md_lines.append("")
    md_lines.append("**如评估招引**:")
    md_lines.append("- [ ] 实地访谈，评估用地/厂房/能耗")
    md_lines.append("- [ ] 查询当地产业链图谱匹配度")
    md_lines.append("- [ ] 评估税收减免政策适用性")
    md_lines.append("")
    md_lines.append("**如评估投资**:")
    md_lines.append("- [ ] 创始人背景调查 (LinkedIn/过往创业)")
    md_lines.append("- [ ] 技术专利核查")
    md_lines.append("- [ ] 行业对标公司调研 (沙利文/灼识)")
    md_lines.append("- [ ] 尽调团队组建")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append(f"\n*本报告由 nova-hermes BP Analyzer 自动生成 | {today}*")

    return '\n'.join(md_lines)


# ============== CLI ==============

def main():
    import sys
    if len(sys.argv) < 3:
        print("用法: report_generator.py <BP.fields.json> <chain_matches.json>")
        sys.exit(1)

    bp_json = sys.argv[1]
    chain_json = sys.argv[2]

    with open(bp_json, 'r', encoding='utf-8') as f:
        fields = json.load(f)
    fields['source_file'] = os.path.basename(bp_json).replace('.fields.json', '')

    chain_matches = []
    if os.path.exists(chain_json):
        with open(chain_json, 'r', encoding='utf-8') as f:
            chain_matches = json.load(f)

    chain_match = chain_matches[0] if chain_matches else {}

    zhaoshang = gen_zhaoshang_section(fields, chain_match)
    investment = gen_investment_section(fields, chain_match)

    md = render_report(fields, chain_matches, zhaoshang, investment, fields['source_file'])

    out = bp_json.replace('.fields.json', '.decision_report.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"✅ 报告已生成: {out}")
    print()
    print(md)


if __name__ == '__main__':
    main()