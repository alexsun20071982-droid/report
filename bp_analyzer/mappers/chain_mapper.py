#!/usr/bin/env python3
"""
产业链图谱加载 + BP 匹配
============================
输入：BP 关键字段 + 产业链图谱 JSON（用户提供的 50+ 图谱）
输出：BP 产品在产业链中的位置（节点 + 上下游 + 同级）
"""
import os
import json
import re
from typing import Dict, List, Tuple, Optional


def load_chain_map(json_path: str) -> Dict:
    """
    加载产业链图谱 JSON
    预期格式：
    {
      "name": "生物降解塑料产业链",
      "version": "v1.0",
      "nodes": [
        {"id": "n1", "name": "玉米淀粉", "tier": "upstream", "layer": 1},
        {"id": "n2", "name": "PLA", "tier": "midstream", "layer": 2},
        ...
      ],
      "edges": [
        {"from": "n1", "to": "n2", "relation": "上游→中游"},
        ...
      ]
    }
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def match_products_to_chain(
    bp_products: List[str],
    bp_keywords: List[str],
    chain_map: Dict
) -> Dict:
    """
    匹配 BP 产品到产业链节点
    匹配策略：
    1. 关键词精确匹配
    2. 子串匹配
    3. 同义词扩展（预留）
    """
    nodes = chain_map.get('nodes', [])
    matched = []
    all_terms = [p.lower() for p in bp_products] + [k.lower() for k in bp_keywords]

    for node in nodes:
        node_name = node.get('name', '').lower()
        node_aliases = [a.lower() for a in node.get('aliases', [])]

        for term in all_terms:
            # 精确匹配
            if term == node_name or term in node_aliases:
                matched.append({
                    'node_id': node.get('id'),
                    'node_name': node.get('name'),
                    'tier': node.get('tier'),
                    'layer': node.get('layer'),
                    'match_type': 'exact',
                    'matched_term': term,
                })
                break
            # 子串匹配（要求至少 3 字以上）
            elif len(term) >= 3 and len(node_name) >= 3 and (term in node_name or node_name in term):
                matched.append({
                    'node_id': node.get('id'),
                    'node_name': node.get('name'),
                    'tier': node.get('tier'),
                    'layer': node.get('layer'),
                    'match_type': 'substring',
                    'matched_term': term,
                })
                break

    # 去重
    seen = set()
    unique = []
    for m in matched:
        key = (m['node_id'], m['match_type'])
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return {
        'chain_name': chain_map.get('name', ''),
        'chain_version': chain_map.get('version', ''),
        'matched_count': len(unique),
        'matches': unique,
    }


def get_upstream_downstream(
    chain_map: Dict,
    node_id: str
) -> Dict:
    """
    拿上下游节点
    """
    edges = chain_map.get('edges', [])
    nodes = {n['id']: n for n in chain_map.get('nodes', [])}

    upstream = []
    downstream = []

    for edge in edges:
        if edge.get('to') == node_id:
            from_node = nodes.get(edge.get('from'), {})
            upstream.append({
                'node_id': edge['from'],
                'name': from_node.get('name'),
                'relation': edge.get('relation', ''),
            })
        elif edge.get('from') == node_id:
            to_node = nodes.get(edge.get('to'), {})
            downstream.append({
                'node_id': edge['to'],
                'name': to_node.get('name'),
                'relation': edge.get('relation', ''),
            })

    return {
        'upstream': upstream,
        'downstream': downstream,
    }


def find_benchmark_companies(
    chain_map: Dict,
    node_id: str,
    bp_company_name: str = ''
) -> List[str]:
    """
    找同节点/同 tier 的对标公司
    需要图谱里有 'companies' 字段（如 {node_id: [公司名列表]}）
    """
    companies_by_node = chain_map.get('companies', {})
    candidates = companies_by_node.get(node_id, [])
    # 排除 BP 自己
    return [c for c in candidates if c != bp_company_name]


# ============== 多图谱匹配 ==============

def match_against_multiple_chains(
    bp_products: List[str],
    bp_keywords: List[str],
    chains_dir: str
) -> List[Dict]:
    """
    对多个产业链图谱做匹配
    返回按匹配度排序的结果列表
    """
    results = []

    if not os.path.isdir(chains_dir):
        return results

    for fname in os.listdir(chains_dir):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(chains_dir, fname)
        try:
            chain = load_chain_map(fpath)
            match_result = match_products_to_chain(bp_products, bp_keywords, chain)
            if match_result['matched_count'] > 0:
                match_result['chain_file'] = fname
                results.append(match_result)
        except Exception as e:
            print(f"  ⚠️ {fname} 解析失败: {e}")

    # 按匹配数降序
    results.sort(key=lambda x: x['matched_count'], reverse=True)
    return results


# ============== Demo 用：一个示例产业链 ==============

DEMO_CHAIN = {
    "name": "生物降解塑料产业链",
    "version": "v1.0",
    "nodes": [
        {"id": "u1", "name": "玉米", "tier": "upstream", "layer": 1},
        {"id": "u2", "name": "淀粉", "tier": "upstream", "layer": 1},
        {"id": "m1", "name": "PLA 聚乳酸", "tier": "midstream", "layer": 2, "aliases": ["聚乳酸", "PLA"]},
        {"id": "m2", "name": "PBS", "tier": "midstream", "layer": 2},
        {"id": "m3", "name": "PHA", "tier": "midstream", "layer": 2},
        {"id": "d1", "name": "包装薄膜", "tier": "downstream", "layer": 3},
        {"id": "d2", "name": "一次性餐具", "tier": "downstream", "layer": 3},
        {"id": "d3", "name": "农用地膜", "tier": "downstream", "layer": 3},
    ],
    "edges": [
        {"from": "u1", "to": "u2", "relation": "原料→加工"},
        {"from": "u2", "to": "m1", "relation": "原料→聚合"},
        {"from": "u2", "to": "m2", "relation": "原料→聚合"},
        {"from": "u2", "to": "m3", "relation": "原料→发酵"},
        {"from": "m1", "to": "d1", "relation": "树脂→制品"},
        {"from": "m1", "to": "d2", "relation": "树脂→制品"},
        {"from": "m2", "to": "d1", "relation": "树脂→制品"},
        {"from": "m2", "to": "d3", "relation": "树脂→制品"},
    ],
    "companies": {
        "m1": ["NatureWorks", "海正生材", "中粮生物"],
        "m2": ["安庆和兴", "BASF"],
        "m3": ["蓝晶科技", "微构工坊"],
        "d1": ["金发科技", "彤程新材"],
    }
}


# ============== CLI ==============

def main():
    import sys
    # 当只传 --demo 时（sys.argv == ['chain_mapper.py', '--demo']）允许
    if len(sys.argv) < 2:
        print("用法: chain_mapper.py <BP.fields.json> <chains_dir>")
        print("或者 chain_mapper.py --demo")
        sys.exit(1)

    if sys.argv[1] == '--demo':
        print("=== Demo: 生物降解塑料产业链 ===")
        bp_products = ['PLA 改性料', '生物基薄膜']
        bp_keywords = ['聚乳酸', 'PLA', '降解']
        result = match_products_to_chain(bp_products, bp_keywords, DEMO_CHAIN)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        # 拿上下游
        if result['matches']:
            node_id = result['matches'][0]['node_id']
            print(f"\n上下游 (节点 {node_id}):")
            print(json.dumps(get_upstream_downstream(DEMO_CHAIN, node_id), ensure_ascii=False, indent=2))

            # 对标
            bench = find_benchmark_companies(DEMO_CHAIN, node_id, '中粮生物')
            print(f"\n对标公司: {bench}")
        return

    bp_json = sys.argv[1]
    chains_dir = sys.argv[2]

    if not os.path.exists(bp_json):
        print(f"❌ 不存在: {bp_json}")
        sys.exit(1)

    with open(bp_json, 'r', encoding='utf-8') as f:
        fields = json.load(f)

    bp_products = fields.get('products', [])
    bp_keywords = fields.get('technologies', [])

    print(f"=== BP 匹配 ===")
    print(f"产品: {len(bp_products)}, 关键词: {len(bp_keywords)}")

    results = match_against_multiple_chains(bp_products, bp_keywords, chains_dir)
    print(f"\n=== 匹配结果（{len(results)} 条产业链有命中）===")
    for r in results[:5]:
        print(f"\n📊 {r['chain_name']} ({r['chain_file']})")
        print(f"   命中 {r['matched_count']} 个节点:")
        for m in r['matches'][:5]:
            print(f"     - [{m['tier']}] {m['node_name']} (匹配: {m['matched_term']}, {m['match_type']})")

    out = bp_json + '.chain_matches.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {out}")


if __name__ == '__main__':
    main()