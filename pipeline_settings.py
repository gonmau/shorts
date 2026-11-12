# -*- coding: utf-8 -*-
"""PC UI의 음성·자막 설정을 GitHub 자동 실행(Actions)에도 똑같이 적용하기 위한 공유 설정.

- UI가 설정을 바꾸면 pipeline_settings.json 을 만들어 GitHub에 자동으로 올린다 (UI 쪽 코드).
- Actions 는 실행 초기에 `python pipeline_settings.py --github-env >> "$GITHUB_ENV"` 로 이 파일을 읽어 환경변수로 넣는다.
  워크플로를 수동 실행(Run workflow)하며 입력한 목소리/속도/자막 방식이 있으면 그 값이 우선이고, 비워두면 이 파일의 값을 쓴다.
공유하는 항목: 목소리(Supertonic), 속도, Edge 음성, 음성 엔진 순서, 자막 방식, 장면 수, 목표 길이, 업로드 시 썸네일 설정.
(교차검증·이미지 자동검증 같은 PC 전용 옵션, 웹훅 주소 등 비밀 값은 올리지 않는다.)"""
import json
import os
import sys
from pathlib import Path

FILE = Path("pipeline_settings.json")
KEYS = ("voice", "rate", "edge", "caption", "engine", "scenes", "target_sec", "yt_thumb", "tv_fx", "font_sub", "font_title", "font_ovl", "info_off")
ENGINE_ORDER = {"auto": "supertonic,edge,google,gtts", "edge": "edge,supertonic,google,gtts", "supertonic": "supertonic", "edge_only": "edge"}
IS_EN = Path("generate_topics.py").exists()


def shared(cfg):
    """UI 설정(dict)에서 공유할 항목만 뽑는다."""
    return {k: cfg[k] for k in KEYS if cfg.get(k) is not None}


def env_from(s, is_en=IS_EN):
    e = {}
    if s.get("voice"):
        e["SUPERTONIC_VOICE_" + ("EN" if is_en else "KO")] = str(s["voice"])
    if s.get("rate") is not None:
        try:
            e["TTS_RATE"] = f"{int(s['rate']):+d}%"
        except (TypeError, ValueError):
            pass
    if s.get("edge"):
        e["TTS_EDGE_VOICE"] = str(s["edge"])
    if s.get("caption"):
        e["CAPTION_MODE"] = str(s["caption"])
    if s.get("engine"):
        e["TTS_ORDER"] = ENGINE_ORDER.get(s["engine"], ENGINE_ORDER["auto"])
    try:
        if int(s.get("scenes") or 0) > 0:
            e["SCENE_COUNT"] = str(int(s["scenes"]))
    except (TypeError, ValueError):
        pass
    try:
        if int(s.get("target_sec") or 0) > 0:
            e["SCRIPT_TARGET_SEC"] = str(int(s["target_sec"]))
    except (TypeError, ValueError):
        pass
    if s.get("yt_thumb"):
        e["YT_THUMBNAIL"] = "on"
    if s.get("tv_fx"):
        e["TV_FX"] = "on"
    if s.get("info_off"):
        e["INFOGRAPHIC"] = "0"
    for k, ev in (("font_sub", "FONT_SUB"), ("font_title", "FONT_TITLE"), ("font_ovl", "FONT_OVL")):
        if s.get(k):
            e[ev] = str(s[k])
    return e


def github_env():
    """Actions 용: 이미 값이 있는 환경변수(수동 실행 입력)는 두고, 비어 있는 것만 공유 설정으로 채운다."""
    try:
        s = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        print("# pipeline_settings.json 없음 → 기본값 사용", file=sys.stderr)
        return
    for k, v in env_from(s).items():
        if os.environ.get(k, "").strip():
            print(f"# {k} 는 실행 입력 값을 우선 사용", file=sys.stderr)
            continue
        print(f"{k}={v}")
        print(f"# {k}={v} (공유 설정)", file=sys.stderr)


if __name__ == "__main__":
    if "--github-env" in sys.argv:
        github_env()
    else:
        print(json.dumps(shared(json.loads(FILE.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2) if FILE.exists() else "(pipeline_settings.json 없음)")
