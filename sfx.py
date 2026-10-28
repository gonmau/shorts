# -*- coding: utf-8 -*-
"""간단한 합성 효과음 (외부 파일 없이 numpy 로 만든다). 연령층을 고려해 적고 작게.

- 장면이 바뀌는 곳에 '휙'(whoosh), 마지막 장면(반전) 시작에 '딩'(ding).
- 효과음은 음성과 겹치지 않도록 문장 사이 쉬는 구간(장면 시작 직전)에 끝나게 놓는다. 최대 4개, 서로 3초 이상 간격, 첫 2초는 비움.
- 켜려면 환경변수 SFX=on (기본은 꺼짐). 볼륨은 SFX_VOL (기본 1.0, 0.5=절반)."""
import os

import numpy as np

SR = 44100


def _env(x, a=0.005, r=0.08):
    n = len(x)
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return x * e


def whoosh(dur=0.28):
    """필터를 지나는 잡음 + 위로 훑는 소리 (부드럽게)"""
    n = int(dur * SR)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    t = np.linspace(0, 1, n)
    # 이동 평균 길이를 줄여 가며(저역 -> 고역) 훑는 느낌
    out = np.zeros(n)
    k = (np.linspace(40, 4, n)).astype(int)
    csum = np.cumsum(np.insert(noise, 0, 0))
    for i in range(n):
        j = max(0, i - k[i])
        out[i] = (csum[i + 1] - csum[j]) / (i + 1 - j)
    out /= (np.abs(out).max() or 1)
    env = np.sin(np.pi * t) ** 2
    return _env(out * env * 0.55, 0.03, 0.12)


def ding(dur=0.7):
    """종소리 같은 두 음 (부드러운 감쇠)"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * 880 * t) + 0.45 * np.sin(2 * np.pi * 1320 * t) + 0.2 * np.sin(2 * np.pi * 1760 * t))
    x *= np.exp(-t * 6.5)
    x /= (np.abs(x).max() or 1)
    return _env(x * 0.6, 0.004, 0.2)


def plan(starts, audio_duration, max_events=4, min_gap=3.0, lead=0.05):
    """[(시각, 종류)]: starts = 장면 시작 시각 목록. 효과음은 장면 시작 직전(lead 만큼 앞)에 끝나도록 놓는다."""
    cand = []
    last = len(starts) - 1
    for i, s in enumerate(starts):
        if i == 0 or s < 2.0 or s > audio_duration - 1.0:
            continue
        cand.append((s, "ding" if i == last else "whoosh"))
    chosen = []
    for s, kind in cand:
        if chosen and s - chosen[-1][0] < min_gap:
            if kind == "ding":                      # 마지막 장면의 딩은 우선
                chosen[-1] = (s, kind)
            continue
        chosen.append((s, kind))
    if len(chosen) > max_events:                    # 너무 많으면 고르게 솎아내고, 마지막(딩)은 유지
        keep = sorted({round(i * (len(chosen) - 1) / (max_events - 1)) for i in range(max_events)})
        chosen = [chosen[i] for i in keep]
    return chosen


def build_track(events, audio_duration, vol=1.0):
    n = int(audio_duration * SR) + SR
    mono = np.zeros(n)
    for s, kind in events:
        snd = (ding() if kind == "ding" else whoosh()) * 0.16 * vol      # 음성 대비 작게
        a = max(0, int((s - len(snd) / SR + 0.05) * SR))                 # 장면 시작 직전에 끝나게
        mono[a:a + len(snd)] += snd[:max(0, n - a)]
    mono = mono[:int(audio_duration * SR)]
    return np.stack([mono, mono], axis=1)


def mix(audio, starts, audio_duration, mode=None):
    """moviepy 오디오 클립에 효과음을 얹어 돌려준다. 끄면 원래 클립 그대로."""
    mode = (mode if mode is not None else os.environ.get("SFX", "off")).strip().lower()
    if mode in ("off", "0", "false", "no", ""):
        return audio, []
    events = plan(starts, audio_duration)
    if not events:
        return audio, []
    from moviepy.audio.AudioClip import AudioArrayClip, CompositeAudioClip
    vol = float(os.environ.get("SFX_VOL", "1.0") or 1.0)
    track = AudioArrayClip(build_track(events, audio_duration, vol), fps=SR)
    mixed = CompositeAudioClip([audio, track]).set_duration(audio_duration)
    return mixed, events
