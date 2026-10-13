# -*- coding: utf-8 -*-
"""장면(이미지 6장)을 대본 문장에 맞춰 나누는 공통 규칙.

- 대본 문장을 글자 수가 비슷하도록 연속된 n개 그룹으로 나눈다 (장면 1 = 첫 그룹 ...).
- 이미지 검색어는 그룹마다(그 그룹의 문장 내용 + 그 문장의 핵심 문구) 만들고,
- 영상에서는 그 그룹의 문장을 읽는 동안 그 장면 이미지를 보여 준다.
"""
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
