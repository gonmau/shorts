# -*- coding: utf-8 -*-
"""장면(이미지 6장)을 대본 문장에 맞춰 나누는 공통 규칙.

- 대본 문장을 글자 수가 비슷하도록 연속된 n개 그룹으로 나눈다 (장면 1 = 첫 그룹 ...).
- 이미지 검색어는 그룹마다(그 그룹의 문장 내용 + 그 문장의 핵심 문구) 만들고,
- 영상에서는 그 그룹의 문장을 읽는 동안 그 장면 이미지를 보여 준다.
"""
import os
import re


def _len(t):
    return len(re.sub(r"\s+", "", str(t))) or 1


def scene_groups(sentences, n=6):
    """문장 목록 -> [(첫 문장 번호, 끝 문장 번호)] (1부터, 연속, 최대 n개)."""
    m = len(sentences)
    if m == 0:
        return []
    n = min(n, m)
    lens = [_len(s) for s in sentences]
    total = sum(lens)
    groups, start, acc = [], 0, 0
    for g in range(n):
        remaining_groups = n - g
        if remaining_groups == 1:
            end = m
        else:
            target = total * (g + 1) / n
            end = start
            while end < m - (remaining_groups - 1) and acc + lens[end] / 2 < target:
                acc += lens[end]
                end += 1
            if end == start:  # 최소 한 문장
                acc += lens[end]
                end += 1
        groups.append((start + 1, end))
        start = end
    return groups


def default_scene_count():
    """새로 만드는 소재의 장면(이미지) 수. 환경변수 SCENE_COUNT, 기본 10, 6~20의 짝수로 맞춤."""
    try:
        n = int(float(os.environ.get("SCENE_COUNT", "10")))
    except ValueError:
        n = 10
    n = max(6, min(20, n))
    return n + (n % 2)


def item_scene_count(item):
    """이 소재의 장면 수. 대본/검색어를 만들 때 정해 item['scene_count']에 저장 (예전 소재는 6장)."""
    try:
        n = int((item or {}).get("scene_count") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if 1 <= n <= 30 else 6
