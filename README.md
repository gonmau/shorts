# 세계 문화 상식 쇼츠 - 클라우드 자동화 (@gonmauY)

GitHub Actions(`culture-shorts-pipeline`)를 수동 실행(Run workflow)해서 소재 → 대본 → 영상 → 유튜브 비공개 업로드까지 만드는 파이프라인입니다.
필수 Secret: `GROQ_API_KEY` / 선택: `PIXABAY_API_KEY`, `YT_*`, `DISCORD_WEBHOOK_URL`, `GOOGLE_TTS_API_KEY`

## 한눈에 보는 흐름

```
소재 생성(unverified) → 승인(verified) → 대본(scripted)
  → review.txt 검수(직접 수정) → 음성 → 이미지 → 영상(video_done) → 유튜브 비공개 업로드
```

- `stage=prepare`: 대본/제목/핵심 문구까지 만들고 `review.txt`를 내보낸 뒤 멈춤 (영상 안 만듦)
- `stage=render`: `review.txt`의 수정을 반영해 영상 제작과 업로드
- `stage=all`: 검수 없이 한 번에

## 실행 입력값

| 입력 | 의미 |
|---|---|
| `redo` | **영상만** 다시 제작할 DB 번호 (예: `98,99`). 대본은 그대로, 음성/영상만 다시 만듦. 유튜브에 올린 기록은 유지됨 |
| `redo_script` | **대본부터** 다시 만들 번호 (예: `101`). 소재 단계부터 새 대본을 만듦 |
| `redo_script` + `!` | `101!` = 대본은 **그대로 두고** 폐기(rejected) 상태만 풀어 검수 대기열로 되살림 |
| `stage` | prepare / render / all |
| `count` | 이번에 처리할 개수 (하루 1~2개 권장) |
| `start_index` | 이 번호 **이후**부터 처리 (선택이 아님. 이 번호 이상 중 조건에 맞는 첫 `count`개) |
| `auto_verify` | 새 소재(unverified)를 사람 확인 없이 verified로 자동 승인. review.txt 검수와 무관 |
| `cta_check` | 대본의 구독/좋아요 문구 점검 (`off`/`scan`/`fix`). 평소 `off` |

`redo`, `redo_script`는 실행 때마다 적용되므로 **작업이 끝나면 다음 실행 전에 비우세요.**

## 소재 만드는 방식 (위키백과 기반)

- 소재는 **위키백과 발췌문**을 근거로 만듭니다. 분야(관습/예절, 법/제도, 음식문화, 언어/이름, 축제/의례, 생활문화)와 나라를 골라 위키백과를 검색하고, 그 발췌문에 있는 사실만으로 Groq이 한국어 소재를 씁니다(`wiki_source.py`).
- 같은 나라가 여러 번 나와도 됩니다. 다만 같은 위키 문서(`wiki_title`)이거나 같은 나라에서 주제/훅이 비슷하면 코드가 중복으로 걸러냅니다. 덜 쓴 나라와 분야가 더 자주 뽑힙니다.
- 한국어가 아닌 소재(영어로 나온 것)는 자동으로 버립니다.
- 소재에 `wiki_title`, `source_url`(위키 링크), `theme`이 저장되므로 Perplexity 검수 때 출처 링크로 바로 확인할 수 있습니다. `verify_note`는 영어 위키 제목입니다.
- 위키백과에 접속하지 못하거나 후보가 부족하면 예전 방식(모델 기억 기반)으로 자동 대체합니다. `python generate_culture_facts.py --source llm`으로 직접 고를 수도 있습니다.

## 사실검수

자동 AI 사실검수는 없습니다. 소재/대본 생성 프롬프트에 과장 금지 규칙만 들어 있고, 사실 확인은 `review.txt`나 `facts_db.json`에서 사람이 직접 합니다(Perplexity 등). 이전 버전이 만든 `rejected` 소재는 `redo_script=번호!`로 되살릴 수 있습니다.

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
- `redo_script=101` (`!` 없이) + `stage=prepare` → 새 대본

**4. 만들어진 영상만 다시 (음성/이미지 문제 등)**
- `redo=98,99` + `stage=render` (또는 all)

**5. 직접 검수한 소재를 JSON에 넣고 영상만 만들기 (수동 경로)**
- `facts_db.json`의 소재에 `narration`(대본)만 넣어도 됩니다. 상태가 `unverified`/`verified`여도 되고, `render` 실행 때 제작 대상으로 자동 인식됩니다(넣은 그대로 사용).
- 선택 항목: `title_line1`, `title_line2`, `highlights`(`[{"s":1,"text":"*핵심* 문구"}]`), `image_queries`(영어 6개). **비워 두면 render 때 대본 기준으로 자동 생성**됩니다.
- 순서: JSON 수정 후 Commit → `stage=render`, `count`, `start_index`(그 소재 번호 이하) 실행.
- 대본을 고쳤는데 `image_queries`를 안 고치면, `review.txt` 경로에서는 새 대본 기준으로 자동 재생성됩니다. JSON을 직접 고칠 때는 `image_queries`를 같이 고치거나 지워 주세요(지우면 자동 생성).

**이미지는 어떻게 대본과 맞나:** 이미지 검색어(`image_queries`, 장면 6개)는 대본을 읽고 만들며, `review.txt`의 `이미지[N]` 줄로 직접 고칠 수 있습니다. 검색어가 바뀌면 예전 이미지를 지우고 새로 받습니다.

## review.txt 편집 규칙

- `대본[N]`: 영상에서 읽는 문장. 고치면 그대로 반영되어 음성이 다시 만들어짐. 문장을 지우면 빠지고 번호는 다시 매겨짐
- `후크/본문/반전`: 유튜브 설명과 Discord에 들어가는 문구
- `제목1/제목2`: 영상 상단 제목
- `제외:`: 영상으로 만들지 않을 소재는 뒤에 사유(또는 `예`)를 적음. 폐기(rejected)로 바뀌어 render에서 건너뜀(비워 두면 제작)
- `이미지[N]`: 장면 이미지 6장의 영어 검색어. 고치면 그 검색어로 이미지를 다시 받음
- `핵심[N]`: (현재 기본 자막 방식에서는 화면에 쓰이지 않음. `CAPTION_MODE=highlight`일 때만 사용) 화면 하단 큰 문구. `*단어*`는 노란 강조. 줄을 지우면 빠짐. N은 `대본[N]`의 문장 번호
- `(`로 시작하는 줄: 참고용(위험도, 검수 메모, 검색어 등), 무시됨
- `=== [번호] ===` 줄은 바꾸지 말 것

## 화면 자막 (대본 자막)

- 화면 하단에는 **대본이 음성 속도에 맞춰** 나옵니다(`subtitles.py`). 문장을 쉼표/단어 단위로 **2줄 이내 조각**으로 나눠 차례로 보여주므로 글이 잘리지 않고, 긴 문장은 여러 장으로 나뉩니다.
- 나오는 시각은 TTS가 만든 문장 시간 안에서 글자 수 비율로 정합니다. 너무 짧게 스치는 조각(0.85초 미만)은 다음 조각과 합칩니다.
- 글자 크기는 고정(58px), 흰 글자 + 검은 테두리 + 반투명 패널입니다. **배경 사진의 밝기와 복잡도**를 재서 밝거나 복잡할수록 패널이 진해집니다.
- 예전 핵심 문구 방식으로 돌리려면 환경변수 `CAPTION_MODE=highlight`. 자막 글자 크기/패널 여백은 `subtitles.py` 위쪽 상수(`FONT_SIZE`, `PAD_X`, `PAD_Y`)에서 바꿉니다.

## 롱폼 (쇼츠 묶음, 가로 16:9)

별도 액션 `culture-longform` 입니다. 쇼츠 파이프라인(소재/대본/영상)과 분리되어 있고, 기록도 `facts_db.json`이 아니라 **`longform_db.json`** 에만 남습니다(`facts_db.json`은 커밋하지 않음).

| 입력 | 의미 |
|---|---|
| `mode` | `auto`: 영상이 끝나고 아직 롱폼에 안 쓴 소재를 번호순으로 / `manual`: `indexes`의 번호들을 묶음 |
| `indexes` | manual일 때 번호 (예: `109,110,115-118`) |
| `theme` | auto일 때 분야/나라/주제 키워드(소재의 theme, topic, country에 그 글자가 들어 있으면 후보). 비우면 번호순 |
| `count` | auto일 때 개수 (3~10) |
| `start_index` | auto일 때 이 번호 이상만 후보 |
| `title` | 제목 직접 지정 (비우면 자동) |
| `dry_run` | 체크하면 묶일 목록만 보고 끝 (영상 안 만듦) |

- 개수는 **3~10개**, 전체 예상 길이 **15분 이하**입니다(넘으면 auto는 앞에서 잘라 쓰고 manual은 오류). 같은 소재가 다른 롱폼에 중복으로 들어가지 않게 auto는 이미 쓴 소재를 제외합니다(manual은 직접 고르므로 허용).
- 소재마다 **음성과 이미지를 다시 만든 뒤** 가로 화면(왼쪽 사진 + 자막, 오른쪽 번호/제목/채널)으로 합성하고 오프닝 카드를 붙여 ffmpeg로 이어 붙입니다. 쇼츠 mp4를 그대로 붙이는 방식이 아닙니다.
- 결과는 아티팩트 `longform`에 `longform_NNN.mp4`, `.png`(썸네일), `.txt`(제목 + 챕터가 들어간 설명 + 사진 출처 + 해시태그)로 들어가고, 디스코드로 제목/설명/썸네일이 따로 전송됩니다. **유튜브 업로드는 직접** 합니다(설명란의 챕터와 사진 출처는 지우지 마세요).
- 예상 소요: 소재 1개당 음성+이미지+합성에 몇 분(GitHub Actions 기준). 6~8개면 30분 안팎을 예상하며 타임아웃은 120분입니다. 실제 소요 시간은 첫 실행 때 확인하세요.
- PC에서는 `local_ui.py`의 "🎞 롱폼 묶기" 탭을 쓰거나 `python build_longform.py --mode auto --count 6 --start 106` 로 실행합니다.

## 음성(TTS) 엔진

순서: **Supertonic → Edge → Google(키가 있을 때) → gTTS**. 앞 엔진이 실패하면 다음으로 넘어가며, 한 번 실패한 엔진은 그 실행에서 다시 시도하지 않습니다. 환경변수 `TTS_ORDER`로 순서를 바꿀 수 있습니다(예: `edge,supertonic,gtts`). Edge는 2026-10 Microsoft 측 변경으로 막혀 있습니다(edge-tts 이슈 #490).
## 이미지 출처와 저작권

- 장면 이미지는 **Pixabay 우선**입니다. 검색어와 Pixabay 태그가 충분히 겹치지 않으면(주제와 안 맞는 사진이면) **Wikimedia Commons**에서 찾고, 거기도 없으면 Pixabay에서 가장 비슷한 사진을 씁니다.
- Commons 사진은 **CC0, 퍼블릭 도메인, CC BY만** 허용합니다(CC BY-SA, NC, ND는 제외). 별도 제한(초상권/상표 표시)이 있는 파일, 로고/지도/깃발, 작성자 없는 CC BY 파일도 제외합니다.
- 쓴 사진의 작성자/라이선스/링크는 `image_credits`에 저장되고 **유튜브 설명란에 자동으로 추가**됩니다("cropped/zoomed" 표시 포함). 화면 이미지 아래 출처 문구도 "Photos: Pixabay · Wikimedia Commons"로 바뀝니다.
- 설명란 크레딧은 지우지 마세요. 라이선스 오류나 사람이 크게 나온 사진은 영상을 확인할 때 직접 걸러 주세요(`이미지[N]` 검색어를 고치면 그 장면을 다시 받습니다).


## DB 상태값 (facts_db.json)

`unverified` → `verified` → `scripted` → `video_done`, 그리고 `rejected`(폐기).
`fact_risk`: low / medium / high / user-reviewed(직접 수정) / user-pending(`!`로 살림, 검수 대기) / unchecked.

## 파일 관리 주의

- `facts_db.json`, `review.txt`는 Actions가 자동 커밋합니다. 코드 zip을 덮어쓸 때 이 파일들과 `avatar.png`는 건드리지 마세요.
- 워크플로 입력값 `"off"`는 반드시 따옴표로 감쌉니다(YAML에서 `off`는 false로 해석됨).
