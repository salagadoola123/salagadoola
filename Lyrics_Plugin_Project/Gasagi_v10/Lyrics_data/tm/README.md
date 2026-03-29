# LyricsTM — Build v1

영어 가사 한국어 번역 파이프라인을 위한 TM/TD 데이터셋.  
Google Translate 번역 결과를 보정하고, 문맥 기반 묶음 번역을 가능하게 하는 구조적 데이터.

---

## 데이터셋 현황

| 항목 | 수치 |
|---|---|
| 총 곡 수 | 17곡 |
| 번역 라인 | ~736줄 |
| TM 엔트리 | ~548개 |
| TD 엔트리 | ~274개 |
| relation 적용 | ~417줄 |

### 유효 데이터셋 (17곡)

| 파일 | 곡 | 장르 |
|---|---|---|
| `amber_mark_sweet_serotonin.json` | Amber Mark - Sweet Serotonin | R&B / Neo-Soul |
| `cil_something_like_this.json` | Cil - something like this | Indie Pop |
| `cody_jon_stagefright.json` | CODY JON - STAGEFRIGHT | Indie Pop |
| `doja_cat_need_to_know.json` | Doja Cat - Need to Know | R&B / Pop |
| `emily_burns_vanilla_sundae.json` | Emily Burns - Vanilla Sundae | Indie Pop |
| `harry_styles_watermelon_sugar.json` | Harry Styles - Watermelon Sugar | Pop |
| `henry_moodie_comedown.json` | Henry Moodie - comedown | Pop |
| `hozier_take_me_to_church.json` | Hozier - Take Me to Church | Alt-Rock / Folk |
| `hybs_dancing_with_my_phone.json` | HYBS - Dancing With My Phone | Lo-fi / Pop |
| `johnny_stimson_aa_battery.json` | Johnny Stimson - AA Battery | Pop |
| `kendrick_n95_sample.json` | Kendrick Lamar - N95 | Hip-Hop / Conscious Rap |
| `lizzo_boys.json` | Lizzo - Boys | Funk / Pop |
| `matilda_mann_there_will_never_be_another_you.json` | Matilda Mann - There Will Never Be Another You | Folk Pop |
| `olivia_rodrigo_drivers_license.json` | Olivia Rodrigo - drivers license | Indie Pop |
| `raye_hard_out_here_sample.json` | RAYE - Hard Out Here. | Alt-Pop / R&B |
| `sza_good_days.json` | SZA - Good Days | R&B / Neo-Soul |
| `virginia_to_vegas_palm_springs.json` | Virginia To Vegas - Palm Springs | Country Pop |

### 제외 곡 (1곡)

| 파일 | 이유 |
|---|---|
| 

---

## JSON 파일 구조

```json
{
  "meta": { ... },
  "structure": [ { "section", "label", "span" } ],
  "lyrics": [ { "id", "section", "type", "text", "translation", "translation_notes", "relation?" } ],
  "td": { "표현": { "ko", "context" } },
  "tm": [ { "id", "source", "target", "score", "notes" } ]
}
```

---

## 필드 상세

### `structure.span`
각 섹션의 lyrics id 범위. 파이프라인이 섹션 경계를 넘는 잘못된 묶음을 차단하는 **1차 필터**.

```json
{ "section": "verse1", "label": "벌스1", "span": [1, 7] }
```

---

### `lyrics.relation`
이전 맥락과 이후 맥락의 관계를 정의. 번역 시 묶음 단위와 컨텍스트 구성 순서를 결정하는 **2차 판단**.

```json
"relation": {
  "type": "setup_chain",
  "group": "v1a",
  "role": "background",
  "ref": [1, 2, 3, 4],
  "auto_hints": ["starts_with_relative"]
}
```

#### `type` 패턴 9종

| 패턴 | 의미 | 예시 |
|---|---|---|
| `setup_chain` | 선언 → 배경 연속 | "면허 땄어" → "우리가 얘기하던 것처럼" |
| `cause_effect` | 원인 → 결과 | "오늘 혼자 달렸어" → "울면서" |
| `expectation_contrast` | 기대 → 현실 반전 | 과거 기대 블록 vs 현재 현실 블록 |
| `setup_payoff` | 복선 → 회수 | "조건 제시" → "반전 결론" |
| `parallel` | 같은 구조 반복 나열 | "I still see / I still hear" / "Take off X, take off Y" |
| `concession_claim` | 인정 → 반박/주장 | "걔랑 있는 거 알아" → "그래도 머릿속에서 안 사라져" |
| `continuation` | 문법적 연속 | 주어→목적어 분리, 접속사 시작 |
| `contrast` | 외부시선 → 내부반박 | "친구들은 잘 살 거래" → "걔네는 내 마음 몰라" |
| `payoff` | 앞 블록 전체 결정타 | 단독 라인으로 앞 서사 마무리 |

#### `role` 종류 및 설명

| role | 설명 |
|---|---|
| `anchor` | 묶음의 시작점. 이후 줄들이 이 줄을 기준으로 해석됨 |
| `background` | anchor의 배경·맥락 제공. 왜 그런지 설명하는 줄 |
| `continuation` | 앞 줄과 문법적·의미적으로 이어지는 줄 |
| `purpose` | anchor의 목적·의도를 설명하는 줄 |
| `cause` | 결과보다 앞서는 원인 줄 |
| `effect` | cause로부터 발생한 결과 줄 |
| `setup` | payoff를 위한 복선·조건 제시 줄 |
| `payoff` | setup 또는 앞 블록 전체를 회수하는 결정타 줄 |
| `tension` | setup과 payoff 사이의 갈등·긴장 고조 줄 |
| `reversal` | 예측을 뒤엎는 반전 줄 |
| `prediction` | 조건에 따른 예측·전망을 제시하는 줄 |
| `resolution` | 갈등·긴장이 해소되거나 결론이 나는 줄 |
| `claim` | 주장·선언을 담은 줄 |
| `rebuttal` | 앞 줄의 주장을 반박하는 줄 |
| `concession` | 상대방 입장이나 현실을 인정하는 줄 |
| `obstacle` | claim이나 목표를 가로막는 장애 요소를 나타내는 줄 |
| `pivot` | 흐름의 방향이 전환되는 줄 |
| `detail` | 앞 줄의 내용을 구체화·보완하는 줄 |
| `image` | 감각적 장면·비유를 제시하는 줄 (parallel 패턴에서 주로 사용) |
| `emotion` | image 줄에 대응하는 감정 반응 줄 |
| `echo` | 앞서 나온 줄을 반향·반복하며 여운을 남기는 줄 (주로 outro) |

#### `auto_hints` 자동 감지 단서

| 힌트 | 감지 조건 |
|---|---|
| `starts_with_conjunction` | And / But / Or / So / Yet / 'Cause 로 시작 |
| `starts_with_relative` | Just like / Like / That / When / Where / If 로 시작 |
| `no_subject` | 동명사 / to부정사 / Crying 등으로 시작 (주어 없음) |
| `fragment` | 6단어 이하 단편 |

---

### `td` (Translation Dictionary)
Google이 직역해버리는 슬랭/관용표현 교정용.  
번역 파이프라인에서 원문 감지 → 번역 결과 교정 순으로 적용.

```json
"sugar high": { "ko": "달콤함에 취한 흥분 상태", "context": "당분 과잉 상태 → 감정적 황홀감 비유" }
```

---

### `tm` (Translation Memory)
완전일치 시 Google 번역 없이 바로 사용.  
`score 0.85` = 수동 검수 완료.

```json
{ "id": 1, "source": "We used to talk every night", "target": "우리 매일 밤 통화했었잖아", "score": 0.85, "notes": "코러스 반복" }
```

---

## 번역 파이프라인 설계 (예정)

```
입력 가사 한 줄
  ↓
1. TM 완전일치 확인 → 히트 시 바로 사용
  ↓ (미스)
2. span으로 섹션 바운더리 확인 (1차 필터)
3. relation.group으로 묶음 단위 구성 (2차 판단)
4. ref 순서대로 컨텍스트 빌드 (anchor → continuation → payoff)
  ↓
5. Google Translate (묶음 단위로 전송)
  ↓
6. 원문에서 TD 키 감지 → 번역 결과 교정
  ↓
7. _to_colloquial() 구어체 변환
  ↓
출력
```
bridge_server.py 연계
① TM 로드:  14개 / TD 10개 (drivers license 1곡 기준)
② TM 완전일치: "We used to talk every night" → "우리 매일 밤 통화했었잖아" ✅
④ RelationGrouper: 17그룹
   [anchor,background,background,purpose] TM 2히트 → v1a 그룹 (4줄 묶음)
   [cause,effect] TM 1히트 → v1b 그룹
   [image,emotion,image,emotion] TM 2히트 → 코러스 parallel
   [setup,tension,payoff] TM 3히트 → ch1b 그룹

---

## 포맷 규칙

- 인코딩: UTF-8
- 들여쓰기: 2칸
- lyrics / tm: **한 줄 인라인** (VS Code 가독성 최적화)
- td: **key 컬럼 28자 정렬**
- 코러스 반복 라인: `translation_notes` 비워도 됨 (TM에서 처리)

---

*Build v1 — 2026-03-11*
