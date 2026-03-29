# 🎵 LyricsTM — VIBE → OBS 가사 번역 브릿지 v10

영어 가사를 자연스러운 한국어 구어체로 실시간 번역해 OBS에 표시하는 시스템.

---

## 전체 아키텍처

```
VIBE 웹 재생
    │ 크롬 확장 (content.js)
    │ trackId / position / cookies
    ▼
bridge_server.py  ─── WebSocket ws://localhost:6789 ──→  obs_overlay.html
    │                                                      (OBS 브라우저 소스)
    ├─ SMTCReader          Windows 미디어 세션 감지
    ├─ LyricsProvider      LRCLIB / VIBE API 가사 로드
    │   ├─ TMIndex         data/tm/*.json → TM·TD 인덱스
    │   └─ RelationGrouper relation.group 기반 번역 묶음 구성
    └─ BridgeServer        WebSocket 허브 + 번역 파이프라인 실행
```

---

## 번역 파이프라인 (v10)

```
① TM 완전일치       tm[] source → target 직접 반환 (score ≥ 0.8)
② relation 묶음     relation.group + span 섹션 경계 필터로 묶음 구성
③ Google Translate  묶음 단위 \n 결합 전송 (컨텍스트 유지)
④ TD 교정           원문 슬랭 감지 → 직역 패턴 탐지 → ko 값으로 치환
⑤ 구어체 변환       _to_colloquial() 문어체 어미 → 해요/해체
```

TM 히트 시 ③④⑤ 스킵. 캐시 미스 줄만 ②~⑤ 실행. 최종 미번역 줄은 개별 병렬 fallback.

---

## 파일 구조

```
가사지/
  bridge_server.py       ← v10 메인 서버
  obs_overlay.html       ← OBS 브라우저 소스
  data/
    tm/
      *.json             ← 곡별 TM·TD·relation·structure 데이터 (17곡)
      README.md          ← JSON 포맷 상세 문서
```

---

## 설치 및 실행

### 1. Python 의존성

```bash
pip install websockets winsdk requests
```

### 2. 서버 실행

```bash
python bridge_server.py
```

정상 기동 시 출력:

```
[INFO] ✅ TM 인덱스 로드: 17곡 / TM 548개 / TD 274개
[INFO] ✅ SMTC (Windows Media Session) 초기화 성공
[INFO] 🚀 브릿지 서버 시작: ws://localhost:6789
[INFO] 📡 HTTP 서버: http://localhost:6790/obs_overlay.html
```

### 3. OBS 설정

1. OBS → Sources → `+` → **Browser**
2. URL: `http://localhost:6790/obs_overlay.html`
3. Width: `1920` / Height: `200`
4. **Shutdown source when not visible** 체크 해제
5. **Refresh browser when scene becomes active** 체크

### 4. 크롬 확장 설치

`manifest.json` 폴더를 크롬 확장 개발자 모드로 로드.  
VIBE 탭에서 trackId · position · cookies를 WebSocket으로 전송.

---

## JSON 데이터 포맷

기준 파일: `amber_mark_sweet_serotonin.json`

```json
{
  "meta": {
    "title": "Sweet Serotonin",
    "artist": "Amber Mark",
    "language": "en"
  },

  "structure": [
    { "section": "verse1",  "label": "벌스1",  "span": [1, 4]  },
    { "section": "chorus",  "label": "코러스", "span": [7, 14] }
  ],

  "lyrics": [
    {
      "id": 7,
      "section": "chorus",
      "type": "sung",
      "text": "Sugar, honey, serotonin",
      "translation": "달콤한 감정이 먼저 밀려와",
      "translation_notes": "삼중 은유. sugar=달콤함, honey=부드러움, serotonin=행복물질",
      "relation": {
        "type": "parallel",
        "group": "ch_a",
        "role": "image",
        "ref": [7, 8],
        "auto_hints": ["fragment"]
      }
    }
  ],

  "td": {
    "weak in the knees": {
      "ko": "무릎이 풀릴 만큼 설레다",
      "context": "고전적 로맨틱 표현"
    }
  },

  "tm": [
    {
      "id": 3,
      "source": "Sugar, honey, serotonin",
      "target": "달콤한 감정이 먼저 밀려와",
      "score": 0.85
    }
  ]
}
```

### structure.span

섹션의 lyrics id 범위. 파이프라인의 **섹션 경계 필터** 역할.  
같은 `relation.group` 키라도 span이 다르면 별개 묶음으로 분리됨.  
반복 코러스(id=7 chorus / id=21 chorus2 / id=29 outro)는 LRC 출현 순서대로 각자 올바른 span에 매핑됨.

### relation type 9종

| type | 설명 |
|------|------|
| `setup_chain` | 순차 설명 묶음 |
| `cause_effect` | 원인 → 결과 |
| `setup_payoff` | 복선 → 회수 |
| `parallel` | 병렬 이미지 |
| `continuation` | 이전 줄 연속 |
| `contrast` | 대조 |
| `concession_claim` | 인정 → 주장 |
| `expectation_contrast` | 기대 → 반전 |
| `payoff` | 독립 회수 |

### relation role 21종

`anchor` · `background` · `continuation` · `purpose` · `cause` · `effect` ·
`setup` · `payoff` · `tension` · `reversal` · `prediction` · `resolution` ·
`claim` · `rebuttal` · `concession` · `obstacle` · `pivot` · `detail` ·
`image` · `emotion` · `echo`

---

## 데이터셋 현황 (Build v1)

| 항목 | 수치 |
|------|------|
| 유효 곡 수 | 17곡 |
| TM 항목 | ~548개 |
| TD 항목 | ~274개 |
| relation 정의 | ~417줄 |
| 제외 | `joey_badass_xxx_kings_dead.json` (의역 다수로 정획도 리미트성) |

---

## 신규 곡 추가

1. `amber_mark_sweet_serotonin.json` 포맷 참고해 JSON 작성
2. `structure.span` 자동 계산 스크립트 사용 (이전 세션 코드 참조)
3. `relation` 필드는 수동 작업
4. `data/tm/` 폴더에 저장 → 서버 재시작 시 자동 로드

---

## 주요 클래스

| 클래스 | 역할 |
|--------|------|
| `TMIndex` | `data/tm/*.json` 로드 → TM·TD 인메모리 인덱스. `inject_relations()`으로 LyricLine에 relation+span 주입 |
| `RelationGrouper` | `build_groups()` — relation.group + span 경계 필터로 번역 묶음 구성 |
| `LyricsProvider` | LRCLIB / VIBE API 가사 로드 + `translate_lyrics()` 파이프라인 실행 |
| `BridgeServer` | WebSocket 허브. `_translate_and_broadcast()`로 번역 결과 전파 |
| `SMTCReader` | Windows SMTC로 현재 재생 트랙 감지 |
| `WindowTitleReader` | SMTC 불가 시 창 타이틀 폴백 |

---

## 가사 소스 우선순위

| 순위 | 소스 | 타임코드 |
|------|------|----------|
| 1 | VIBE API (trackId 기반) | ✅ syncLyric |
| 2 | LRCLIB | ✅ LRC |
| 3 | Google Translate 배치 | — |

---

## 문제 해결

| 증상 | 원인 | 조치 |
|------|------|------|
| `TM 인덱스 로드: 0곡` | `data/tm/` 폴더 없거나 JSON 없음 | 폴더 생성 후 JSON 배치 | 
| TM 히트 0줄 | LRC 텍스트와 JSON `text` 불일치 | 공백·대소문자 확인, score < 0.8 점검 | ✅
| TD 교정 미발동 | 직역 패턴 테이블 미등록 | `_direct_variants()` 테이블에 패턴 추가 | 
| relation 묶음 미적용 | `inject_relations` 곡 매칭 실패 | JSON `meta.artist` / `meta.title` 확인 | 
| SMTC 안 됨 | winsdk 미설치 | `pip install winsdk` | 
| OBS 연결 안 됨 | 포트 충돌 | `WS_PORT = 6789` 변경 |
data-vibe-time은 audio.currentTime 직접 읽는 방식으로 싱크가 정확한 싱크를 겨냥 
---

## PENDING

- **TD 직역 패턴 확충** — 실제 재생 로그에서 탐지 실패 케이스 수집 후 `_direct_variants()` 추가
- **배포 테스트** — TM 히트율 / TD 교정 발동 / 묶음 번역 품질 로그 검증
- **미번역 곡 보완** — `olivia_rodrigo_drivers_license.json` 외 신규 5곡 `translation` 필드 입력
- **`_translation_cache` key 통일** — `artist||title` → `vibe_trackid` 기반으로 변경
- **`is_korean()` 개선** — 영어 제목 + 한글 괄호 혼용 케이스 오판 수정
