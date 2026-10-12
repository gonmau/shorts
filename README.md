# 세계 문화 상식 쇼츠 - 클라우드 자동화 (@gonmauY)

GitHub Actions(`culture-shorts-pipeline`)를 수동 실행(Run workflow)해서 소재 → 대본 → 영상 → 유튜브 비공개 업로드까지 만드는 파이프라인입니다.
필수 Secret: `GROQ_API_KEY` / 선택: `PIXABAY_API_KEY`, `YT_*`, `DISCORD_WEBHOOK_URL`, `GOOGLE_TTS_API_KEY`

## 한눈에 보는 흐름

```
소재 생성(unverified) → 승인(verified) → 대본+AI 사실검수(scripted 또는 rejected)
  → review.txt 검수(직접 수정) → 음성 → 이미지 → 영상(video_done) → 유튜브 비공개 업로드
```

- `stage=prepare`: 대본/제목/핵심 문구까지 만들고 `review.txt`를 내보낸 뒤 멈춤 (영상 안 만듦)
- `stage=render`: `review.txt`의 수정을 반영해 영상 제작과 업로드
- `stage=all`: 검수 없이 한 번에

## 실행 입력값

| 입력 | 의미 |
|---|---|
| `redo` | **영상만** 다시 제작할 DB 번호 (예: `98,99`). 대본은 그대로, 음성/영상만 다시 만듦. 유튜브에 올린 기록은 유지됨 |
| `redo_script` | **대본부터** 다시 만들 번호 (예: `101`). 소재 단계부터 새 대본을 만들고 사실검수도 다시 함 |
| `redo_script` + `!` | `101!` = 대본은 **그대로 두고** 폐기(rejected) 상태만 풀어 검수 대기열로 되살림. AI 사실검수는 건너뜀 |
| `stage` | prepare / render / all |
| `count` | 이번에 처리할 개수 (하루 1~2개 권장) |
| `start_index` | 이 번호 **이후**부터 처리 (선택이 아님. 이 번호 이상 중 조건에 맞는 첫 `count`개) |
| `auto_verify` | 새 소재(unverified)를 사람 확인 없이 verified로 자동 승인. review.txt 검수와 무관 |
| `cta_check` | 대본의 구독/좋아요 문구 점검 (`off`/`scan`/`fix`). 평소 `off` |

`redo`, `redo_script`는 실행 때마다 적용되므로 **작업이 끝나면 다음 실행 전에 비우세요.**

## AI 사실검수와 폐기 기준

대본을 만든 뒤 AI가 한 번 더 사실검수를 합니다. 아래 중 하나면 해당 소재는 `rejected`(폐기)되고 검수 목록에서 건너뜁니다.

- 확인도(verifiability)가 `documented`가 아님 (`unverified`/`fabricated`/`partial` 등)
- 위험도(risk)가 `medium` 또는 `high`
- AI가 만든 교정본이 길이/형식 기준에 안 맞아 적용하지 못함
- 검수 호출 자체가 실패

폐기 사유는 `facts_db.json`의 `reject_reason`에, Discord 알림에도 표시됩니다.
**AI 검수는 틀릴 수 있습니다.** 틀린 내용을 다른 추측으로 바꾸기도 하므로, 중요한 소재는 Perplexity 등으로 직접 확인하세요.

## 자주 쓰는 작업

**1. 새 영상 만들기(검수 포함)**
1. `stage=prepare`, `count=1`, `start_index=<시작 번호>` 실행
2. `review.txt` 확인/수정 후 Commit
3. `stage=render` 실행 (같은 `count`, `start_index`)

**2. 폐기된 소재를 Perplexity가 검수한 대본으로 살리기**
1. `redo_script=101!`, `redo`는 비움, `stage=prepare`, `count=1`, `start_index=101` 실행
2. `review.txt`의 `대본[N]`, `후크/본문/반전`을 검수한 내용으로 모두 고치고 Commit
3. `redo_script`를 **비우고** `stage=render` 실행

**3. 대본이 마음에 안 들어 처음부터 다시**
- `redo_script=101` (`!` 없이) + `stage=prepare` → 새 대본 + 새 사실검수

**4. 만들어진 영상만 다시 (음성/이미지 문제 등)**
- `redo=98,99` + `stage=render` (또는 all)

## review.txt 편집 규칙

- `대본[N]`: 영상에서 읽는 문장. 고치면 그대로 반영되어 음성이 다시 만들어짐. 문장을 지우면 빠지고 번호는 다시 매겨짐
- `후크/본문/반전`: 유튜브 설명과 Discord에 들어가는 문구
- `제목1/제목2`: 영상 상단 제목
- `핵심[N]`: 화면 하단 큰 문구. `*단어*`는 노란 강조. 줄을 지우면 빠짐. N은 `대본[N]`의 문장 번호
- `(`로 시작하는 줄: 참고용(위험도, 검수 메모, 검색어 등), 무시됨
- `=== [번호] ===` 줄은 바꾸지 말 것
- 직접 고친 소재는 AI 사실검수를 다시 하지 않고 그대로 사용 (`fact_risk=user-reviewed`)

## 음성(TTS) 엔진

순서: **Supertonic → Edge → Google(키가 있을 때) → gTTS**. 앞 엔진이 실패하면 다음으로 넘어가며, 한 번 실패한 엔진은 그 실행에서 다시 시도하지 않습니다. 환경변수 `TTS_ORDER`로 순서를 바꿀 수 있습니다(예: `edge,supertonic,gtts`). Edge는 2026-10 Microsoft 측 변경으로 막혀 있습니다(edge-tts 이슈 #490).

## DB 상태값 (facts_db.json)

`unverified` → `verified` → `scripted` → `video_done`, 그리고 `rejected`(폐기).
`fact_risk`: low / medium / high / user-reviewed(직접 수정) / user-pending(`!`로 살림, 검수 대기) / unchecked.

## 파일 관리 주의

- `facts_db.json`, `review.txt`는 Actions가 자동 커밋합니다. 코드 zip을 덮어쓸 때 이 파일들과 `avatar.png`는 건드리지 마세요.
- 워크플로 입력값 `"off"`는 반드시 따옴표로 감쌉니다(YAML에서 `off`는 false로 해석됨).
