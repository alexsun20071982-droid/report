#!/usr/bin/env python3
"""
BP 解析器 — 支持 PDF / PPT / Word → 结构化文本 + 关键字段抽取
============================================================
输入：任意 BP 文件路径
输出：dict 包含文本 + 抽取的关键字段（产品/技术/融资/团队/市场）
"""
import sys
import os
import re
import json
from typing import Dict, List, Optional


def parse_pdf(file_path: str) -> Dict:
    """PDF → {text, pages, has_images}"""
    try:
        import pdfplumber
    except ImportError:
        return {'text': '', 'pages': 0, 'error': 'pdfplumber not installed. pip install pdfplumber'}

    text_parts = []
    page_count = 0
    has_images = False

    with pdfplumber.open(file_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            page_text = page.extract_text() or ''
            text_parts.append(page_text)
            if page.images:
                has_images = True

    full_text = '\n\n'.join(text_parts)
    return {
        'text': full_text,
        'pages': page_count,
        'has_images': has_images,
        'error': ''
    }


def parse_pptx(file_path: str) -> Dict:
    """PPTX → {text, slides}"""
    try:
        from pptx import Presentation
    except ImportError:
        return {'text': '', 'slides': 0, 'error': 'python-pptx not installed. pip install python-pptx'}

    prs = Presentation(file_path)
    text_parts = []
    for i, slide in enumerate(prs.slides):
        slide_text = []
        for shape in slide.shapes:
            if hasattr(shape, 'text') and shape.text:
                slide_text.append(shape.text)
            if shape.has_table:
                for row in shape.table.rows:
                    row_text = ' | '.join(cell.text.strip() for cell in row.cells)
                    slide_text.append(row_text)
        text_parts.append(f'--- Slide {i+1} ---\n' + '\n'.join(slide_text))

    return {
        'text': '\n\n'.join(text_parts),
        'slides': len(prs.slides),
        'error': ''
    }


def parse_docx(file_path: str) -> Dict:
    """DOCX → {text, paragraphs}"""
    try:
        from docx import Document
    except ImportError:
        return {'text': '', 'paragraphs': 0, 'error': 'python-docx not installed. pip install python-docx'}

    doc = Document(file_path)
    text_parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            row_text = ' | '.join(cell.text.strip() for cell in row.cells)
            text_parts.append(row_text)

    return {
        'text': '\n\n'.join(text_parts),
        'paragraphs': len(doc.paragraphs),
        'error': ''
    }


def parse_any(file_path: str) -> Dict:
    """统一入口 — 按扩展名分发"""
    if not os.path.exists(file_path):
        return {'text': '', 'error': f'文件不存在: {file_path}'}

    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        return parse_pdf(file_path)
    elif ext in ('.pptx', '.ppt'):
        return parse_pptx(file_path)
    elif ext in ('.docx', '.doc'):
        return parse_docx(file_path)
    else:
        return {'text': '', 'error': f'不支持的格式: {ext}'}


# ============== 关键字段抽取 ==============

def extract_company_name(text: str) -> str:
    """提取公司名 — 启发式：找"XX公司""XX科技""XX集团"等"""
    patterns = [
        r'([^\s，。；、]+?(?:公司|科技|集团|有限|股份|控股|实业))',
        r'([A-Z][a-zA-Z]+\s*(?:Inc|LLC|Corp|Ltd|Co\.))',
        r'([一-龥]{2,15}(?:科技|生物|医药|新能源|材料|信息|智能|半导体))',
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()
    return ''


def extract_funding(text: str) -> List[Dict]:
    """提取融资历史"""
    fundings = []
    # 匹配 "A轮融资5000万" / "融资5000万RMB" / "估值10亿"
    patterns_funding = [
        r'([A-D预]+)\s*轮[^\n。]*?([\d.]+\s*[亿万千]+)',
        r'融[资本金额]*\s*([\d.]+\s*[亿万千]+)',
        r'完成[^\n。]*?([\d.]+\s*[亿万千]+)\s*(?:融资|投资)',
    ]
    for pattern in patterns_funding:
        for m in re.finditer(pattern, text):
            fundings.append({
                'round': m.group(1) if '(' in pattern else '',
                'amount': m.group(2) if len(m.groups()) >= 2 else m.group(1),
            })
    return fundings


def extract_valuation(text: str) -> str:
    """提取估值"""
    m = re.search(r'估值[^\d]*?([\d.]+\s*[亿万])', text)
    return m.group(1) if m else ''


def extract_founders(text: str) -> List[str]:
    """提取创始人/CEO - 多 pattern + 严格过滤"""
    candidates = []

    # Pattern 1: 创始人：张三 + 副教授 模式
    # 找 "创始人" 之后的中文人名（≤4 字，2-3 字最佳）
    m = re.search(r'创始人[：:为是]?\s*([\u4e00-\u9fa5]{2,4})\s*(?:教授|博士|老师|院士|工程师|总经理|先生|女士)', text)
    if m:
        candidates.append(m.group(1))

    # Pattern 2: 创始人/CEO 后跟人名
    for m in re.finditer(r'(?:创始人|CEO|总裁|董事长)\s*[：:为是]?\s*([\u4e00-\u9fa5]{2,4})', text):
        name = m.group(1)
        if name not in candidates:
            candidates.append(name)

    # Pattern 3: 团队段找"X + 教授/博士"的人名
    team_match = re.search(r'团队[：:\s]*\n(.{20,800}?)(?:\n\n|联系)', text, re.DOTALL)
    if team_match:
        for m in re.finditer(r'[\-•·\d\.]+\s*([\u4e00-\u9fa5]{2,4})\s*[：:：\s]+[^\n]{2,40}', team_match.group(1)):
            name = m.group(1)
            if name not in candidates:
                candidates.append(name)

    # 过滤（保留合理中文人名）
    filtered = []
    bad_words = ['科技', '公司', '集团', '学院', '研究所', '工程', '有限', '大学', '清华', '北大']
    for c in candidates:
        if any(bad in c for bad in bad_words):
            continue
        if len(c) >= 2 and len(c) <= 4:
            filtered.append(c)

    return filtered[:5]


def extract_products(text: str) -> List[str]:
    """提取核心产品 - 启发式：找"核心产品"段落"""
    products = []

    # 找"核心产品"段落（限制 500 字内）
    section_match = re.search(
        r'(?:核心产品|主营业务|产品矩阵|产品体系|Our Products)[：:\s]*\n(.{20,800}?)(?:\n\n|\Z)',
        text, re.DOTALL
    )
    if section_match:
        section = section_match.group(1)
        for m in re.finditer(r'[\-•·]\s*([^\n]{2,40})', section):
            p = m.group(1).strip()
            # 过滤明显非产品的（公司名 + 货币单位）
            if any(bad in p for bad in ['公司', '%', '增长']):
                continue
            products.append(p)
        for m in re.finditer(r'\d+[\.、]\s*([^\n]{2,40})', section):
            p = m.group(1).strip()
            if any(bad in p for bad in ['公司', '%', '增长']):
                continue
            products.append(p)

    # fallback: 找"团队"段落（防止完全无产品）
    if not products:
        team_match = re.search(r'团队[：:\s]*\n(.{20,500})', text, re.DOTALL)
        if team_match:
            # 团队段不直接当产品

            pass

    return products[:8]


def extract_technology(text: str) -> List[str]:
    """提取技术关键词"""
    tech_keywords = [
        'AI', '人工智能', '机器学习', '深度学习', '大模型', 'LLM',
        '区块链', '云计算', '边缘计算', '物联网', 'IoT',
        '生物技术', '基因编辑', 'CRISPR', '合成生物学',
        '新材料', '纳米', '石墨烯', '碳纤维',
        '半导体', '芯片', '光刻', 'EDA',
        '新能源', '光伏', '锂电池', '氢能', '储能',
        '机器人', '自动驾驶', '无人机',
        'AR', 'VR', 'XR', '元宇宙',
        '5G', '6G', '卫星互联网',
    ]
    found = []
    text_lower = text.lower()
    for kw in tech_keywords:
        if kw.lower() in text_lower:
            found.append(kw)
    return found


def extract_industries(text: str) -> List[str]:
    """提取行业关键词"""
    industries = [
        '跨境电商', 'SaaS', '企业服务', '金融科技', 'FinTech',
        '医疗健康', '教育', '汽车', '出行', '物流', '供应链',
        '农业', '食品', '餐饮', '零售', '消费',
        '游戏', '社交', '内容', '媒体',
        '制造业', '工业互联网', '智能制造',
        '环保', '碳中和', 'ESG',
    ]
    found = []
    for ind in industries:
        if ind in text:
            found.append(ind)
    return found


def extract_market_size(text: str) -> List[str]:
    """提取市场规模数据"""
    results = []
    patterns = [
        r'(?:市场规模|TAM|SAM)[^\d]*?([\d.]+\s*[万亿千百]?[美]?元)',
        r'([\d.]+\s*[万亿千百]元)\s*(?:市场|行业|赛道)',
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            results.append(m.group(1))
    return list(set(results))[:5]


def extract_all_fields(parsed: Dict) -> Dict:
    """一次性抽取所有关键字段"""
    text = parsed.get('text', '')
    return {
        'company_name': extract_company_name(text),
        'fundings': extract_funding(text),
        'valuation': extract_valuation(text),
        'founders': extract_founders(text),
        'products': extract_products(text),
        'technologies': extract_technology(text),
        'industries': extract_industries(text),
        'market_size': extract_market_size(text),
        'text_length': len(text),
        'pages': parsed.get('pages', parsed.get('slides', 0)),
    }


# ============== CLI ==============

def main():
    if len(sys.argv) < 2:
        print("用法: bp_parser.py <BP文件路径>")
        print("支持: .pdf / .pptx / .docx")
        sys.exit(1)

    file_path = sys.argv[1]
    output_json = '--json' in sys.argv

    print(f"=== 解析: {file_path} ===")
    parsed = parse_any(file_path)

    if parsed.get('error'):
        print(f"❌ {parsed['error']}")
        sys.exit(1)

    print(f"✅ 解析成功: {parsed.get('pages', parsed.get('slides', 0))} 页, {len(parsed['text']):,} 字符")

    fields = extract_all_fields(parsed)

    if output_json:
        print(json.dumps(fields, ensure_ascii=False, indent=2))

    # 总是写 fields.json（无论是否 --json）
    out_json = file_path + '.fields.json'
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(fields, f, ensure_ascii=False, indent=2)
    print(f"✅ 字段已保存: {out_json}")

    if not output_json:
        print(f"\n=== 关键字段 ===")
        print(f"公司名: {fields['company_name'] or '(未识别)'}")
        print(f"创始人: {', '.join(fields['founders']) or '(未识别)'}")
        print(f"融资: {fields['fundings'][:3] if fields['fundings'] else '(未识别)'}")
        print(f"估值: {fields['valuation'] or '(未识别)'}")
        print(f"\n核心产品 ({len(fields['products'])}):")
        for p in fields['products'][:5]:
            print(f"  - {p}")
        print(f"\n技术关键词 ({len(fields['technologies'])}): {', '.join(fields['technologies'][:10])}")
        print(f"\n行业 ({len(fields['industries'])}): {', '.join(fields['industries'])}")
        print(f"\n市场规模: {fields['market_size']}")

        # 把 text 写到 .txt
        out_txt = file_path + '.extracted.txt'
        with open(out_txt, 'w', encoding='utf-8') as f:
            f.write(parsed['text'])
        print(f"\n✅ 文本已保存: {out_txt}")


if __name__ == '__main__':
    main()