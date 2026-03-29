"""
🎵 VIBE → OBS 가사 브릿지 서버 v10
- TM/TD/relation 기반 번역 파이프라인 적용
- trackid_found 시 항상 VIBE API 호출 (캐시 무효화)
- SMTC + LRCLIB fallback
"""

import asyncio
import json
import re
import threading
import requests
import logging
import subprocess
import base64
import os
from dataclasses import dataclass, asdict
from typing import Optional, List

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

WS_HOST = "localhost"
WS_PORT = 6789
POLL_INTERVAL = 1.0

@dataclass
class TrackInfo:
    title:      str   = ""
    artist:     str   = ""
    album:      str   = ""
    position:   float = 0.0
    duration:   float = 0.0
    is_playing: bool  = False
    thumbnail:  str   = ""
    track_id:   int   = 0

@dataclass
class LyricLine:
    time:     float
    text:     str
    relation: dict = None   # relation 필드 (TMIndex에서 주입)

# ════════════════════════════════════════════════
# 1. SMTC
# ════════════════════════════════════════════════

class SMTCReader:
    def __init__(self):
        self._available = False
        self._try_init()

    def _try_init(self):
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
            self._Manager = Manager
            self._available = True
            log.info("✅ SMTC (Windows Media Session) 초기화 성공")
        except ImportError:
            log.warning("⚠️  winsdk 없음 → 창 타이틀 폴백 모드 사용")
        except Exception as e:
            log.warning(f"⚠️  SMTC 초기화 오류: {e}")

    async def get_current_track(self) -> Optional[TrackInfo]:
        if not self._available:
            return None
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
            from winsdk.windows.media import MediaPlaybackStatus
            manager  = await Manager.request_async()
            session  = manager.get_current_session()
            if not session:
                return None
            media_props = await session.try_get_media_properties_async()
            timeline    = session.get_timeline_properties()
            playback    = session.get_playback_info()
            position = timeline.position.total_seconds() if timeline.position else 0
            duration = timeline.end_time.total_seconds() if timeline.end_time else 0
            thumb_url = ""
            if media_props.thumbnail:
                try:
                    stream = await media_props.thumbnail.open_read_async()
                    data   = await stream.read_bytes_async(stream.size)
                    thumb_url = "data:image/jpeg;base64," + base64.b64encode(bytes(data)).decode()
                except Exception:
                    pass
            is_playing = playback.playback_status == MediaPlaybackStatus.PLAYING
            return TrackInfo(
                title=media_props.title or "",
                artist=media_props.artist or "",
                album=media_props.album_title or "",
                position=position,
                duration=duration,
                is_playing=is_playing,
                thumbnail=thumb_url,
                track_id=0
            )
        except Exception as e:
            log.debug(f"SMTC read error: {e}")
            return None

# ════════════════════════════════════════════════
# 2. 창 타이틀 폴백
# ════════════════════════════════════════════════

class WindowTitleReader:
    PATTERNS = [
        r'^(.+?)\s*-\s*(.+?)\s*[-|]\s*VIBE',
        r'^(.+?)\s*[-–]\s*(.+?)\s*[-|]\s*Spotify',
        r'^(.+?)\s*[-–]\s*(.+?)\s*[-|]\s*YouTube',
        r'^(.+?)\s*[-–]\s*(.+)$',
    ]

    def get_current_track(self) -> Optional[TrackInfo]:
        try:
            cmd = (
                "Get-Process | Where-Object {"
                "$_.MainWindowTitle -ne '' -and "
                "$_.ProcessName -notin @('chrome','msedge','brave','firefox') -and "
                "$_.ProcessName -in @('VIBE','Spotify','YouTubeMusic','flo','genie')"
                "} | Select-Object ProcessName,MainWindowTitle | ConvertTo-Json"
            )
            result = subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            windows = json.loads(result.stdout or "[]")
            if isinstance(windows, dict):
                windows = [windows]
            if not windows:
                return None
            windows.sort(key=lambda w: w.get('ProcessName','') == 'VIBE', reverse=True)
            for win in windows:
                title = win.get('MainWindowTitle','')
                for pattern in self.PATTERNS:
                    m = re.match(pattern, title, re.IGNORECASE)
                    if m:
                        return TrackInfo(
                            artist=m.group(1).strip(),
                            title=m.group(2).strip(),
                            is_playing=True,
                            track_id=0
                        )
        except Exception as e:
            log.debug(f"Window title read error: {e}")
        return None

# ════════════════════════════════════════════════
# 3. 가사 API
# ════════════════════════════════════════════════

# ════════════════════════════════════════════════
# 3-A. TM 인덱스
# ════════════════════════════════════════════════

class TMIndex:
    """서버 시작 시 data/tm/*.json 전체 로드 → 인메모리 인덱스"""

    def __init__(self):
        self._tm: dict[str, str] = {}       # source.lower() → target
        self._td: dict[str, dict] = {}      # en_expr.lower() → {"ko":..., "context":...}
        self._loaded = False

    def load(self, tm_dir: str):
        if not os.path.isdir(tm_dir):
            log.warning(f"⚠️  TM 디렉토리 없음: {tm_dir}")
            return
        count_files = count_tm = count_td = 0
        for fname in os.listdir(tm_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(tm_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    d = json.load(f)
                # TM 로드
                for entry in d.get("tm", []):
                    src = entry.get("source", "").strip()
                    tgt = entry.get("target", "").strip()
                    score = entry.get("score", 0.0)
                    if src and tgt and score >= 0.8:
                        self._tm[src.lower()] = tgt
                        count_tm += 1
                # TD 로드 (곡별 병합)
                for expr, val in d.get("td", {}).items():
                    key = expr.lower()
                    if key not in self._td:
                        self._td[key] = val
                        count_td += 1
                count_files += 1
            except Exception as e:
                log.warning(f"TM 파일 로드 실패 ({fname}): {e}")
        self._loaded = True
        log.info(f"✅ TM 인덱스 로드: {count_files}곡 / TM {count_tm}개 / TD {count_td}개")

    def lookup_tm(self, text: str) -> Optional[str]:
        """완전일치 TM 검색"""
        return self._tm.get(text.strip().lower())

    def get_td_corrections(self, source: str) -> dict:
        """원문에서 TD 키 감지 → {en_expr: ko_target} 반환"""
        src_lower = source.lower()
        result = {}
        for expr_lower, val in self._td.items():
            if expr_lower in src_lower:
                result[expr_lower] = val.get("ko", "")
        return result

    def apply_td(self, source: str, translated: str) -> str:
        """TD 기반 번역 결과 교정
        전략: 원문에 TD 키가 있으면, Google이 직역했을 법한 패턴을
        번역 결과에서 탐지해 ko 값으로 치환한다.
        """
        corrections = self.get_td_corrections(source)
        if not corrections:
            return translated
        result = translated
        for expr_lower, ko_target in corrections.items():
            if not ko_target:
                continue
            # Google 직역 후보 패턴 목록
            direct_variants = self._direct_variants(expr_lower)
            replaced = False
            for variant in direct_variants:
                if variant and variant in result:
                    result = result.replace(variant, ko_target, 1)
                    log.info(f"  [TD교정] '{variant}' → '{ko_target}'")
                    replaced = True
                    break
            if not replaced:
                log.debug(f"  [TD감지] '{expr_lower}' (직역패턴 미탐지, 원문유지)")
        return result

    @staticmethod
    def _direct_variants(expr: str) -> list:
        """TD 영문 키에 대해 Google이 직역할 법한 한국어 패턴 목록"""
        table = {
            "weak in the knees":    ["무릎이 약해", "무릎이 약하게", "무릎이 약한"],
            "sugar high":           ["설탕 하이", "슈거 하이", "설탕 고조", "당 수치"],
            "rollin'":              ["롤링", "구르는", "구르며"],
            "rolling":              ["롤링", "구르는"],
            "in a hold":            ["잡고 있는", "잡혀 있는", "붙잡혀"],
            "right on time":        ["정시에", "제때", "딱 제 시간에"],
            "get on top of it":     ["그것을 극복", "위에 올라"],
            "whole life":           ["전체 인생", "온 생애", "전 생애"],
            "on fleek":             ["정확하게", "완벽하게"],
            "lowkey":               ["낮은 키", "로우키", "조용히"],
            "ghosted":              ["귀신", "유령처럼", "유령이"],
            "lit":                  ["불켜진", "불이 켜진", "켜진"],
            "no cap":               ["모자 없이", "캡 없이", "거짓말 없이"],
            "snatched":             ["낚아챈", "빼앗긴", "잡아챈"],
            "slay":                 ["죽이다", "죽여라", "죽여"],
            "periodt":              ["기간", "피리어드"],
            "vibes":                ["바이브", "분위기들"],
            "down bad":             ["나쁜 상태", "최악의 상태"],
            "rizz":                 ["리즈", "매력"],
            "bussin":               ["버싱", "대박"],
            "goated":               ["염소", "고티드"],
            "main character":       ["주인공 에너지", "주 캐릭터"],
            "caught in my feelings":["감정에 빠져", "감정에 사로잡혀"],
            "all the feels":        ["모든 감정", "많은 감정들"],
            "in my head":           ["내 머릿속에서", "머릿속에"],
            "feels like":           ["같이 느껴", "처럼 느껴져"],
            "running through":      ["달리는", "통해 달리는"],
            "whole damn":           ["빌어먹을 전체", "망할"],
            "right here":           ["바로 여기에", "여기 바로"],
        }
        return table.get(expr.lower(), [])

    def inject_relations(self, lines: list, artist: str, title: str) -> list:
        """TM JSON에서 해당 곡의 relation + span 정보를 LyricLine에 주입"""
        # artist/title 기반으로 매칭되는 JSON 찾기
        tm_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tm")
        if not os.path.isdir(tm_dir):
            return lines
        best_file = None
        best_score = 0
        for fname in os.listdir(tm_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(tm_dir, fname), encoding="utf-8") as f:
                    d = json.load(f)
                meta = d.get("meta", {})
                fa = meta.get("artist", "").lower()
                ft = meta.get("title",  "").lower()
                score = 0
                if artist.lower() in fa or fa in artist.lower():
                    score += 1
                if title.lower()  in ft or ft in title.lower():
                    score += 2
                if score > best_score:
                    best_score = score
                    best_file  = d
            except Exception:
                continue
        if not best_file or best_score < 2:
            return lines

        # text → [{ id, relation, span }] 리스트로 구성
        # 같은 text가 여러 섹션에 반복될 수 있으므로 리스트로 누적
        # structure에서 id → span 역매핑 먼저 구성
        id_to_span: dict = {}
        id_to_order: dict = {}   # id → lyrics 배열 내 순서(0-based)
        for sec in best_file.get("structure", []):
            span = sec.get("span", [])
            if len(span) == 2:
                for lid in range(span[0], span[1] + 1):
                    id_to_span[lid] = tuple(span)

        rel_map: dict = {}  # text_lower → [ {id, relation, span} ]
        for order_idx, entry in enumerate(best_file.get("lyrics", [])):
            key = entry["text"].strip().lower()
            lid = entry.get("id")
            id_to_order[lid] = order_idx
            info = {
                "id":       lid,
                "order":    order_idx,
                "relation": entry.get("relation"),
                "span":     id_to_span.get(lid),
            }
            rel_map.setdefault(key, []).append(info)

        # LyricLine에 주입
        # 같은 text가 여러 id에 있으면, LRC lines 배열 내 위치(index) 기반으로
        # 가장 가까운 순서의 id를 선택 (반복 코러스 매핑 정확도 향상)
        text_counters: dict = {}   # text_lower → 몇 번째 매칭인지
        injected = 0
        for line in lines:
            key = line.text.strip().lower()
            candidates = rel_map.get(key)
            if not candidates:
                continue
            # 이 text의 n번째 출현 → candidates의 n번째 항목 선택 (순환)
            n = text_counters.get(key, 0)
            info = candidates[n % len(candidates)]
            text_counters[key] = n + 1

            if info["relation"]:
                line.relation = info["relation"]
            if info["span"]:
                line.span = info["span"]
            injected += 1
        if injected:
            log.info(f"  🔗 relation+span 주입: {injected}/{len(lines)}줄 "
                     f"({best_file['meta'].get('title','')})")
        return lines


# ════════════════════════════════════════════════
# 3-B. Relation 묶음 그루퍼
# ════════════════════════════════════════════════

class TranslationGroup:
    """번역 단위 하나 (relation.group 기준)"""
    def __init__(self):
        self.line_indices: list = []   # 원본 lines 배열 인덱스
        self.texts:        list = []   # 원문 텍스트 (anchor 순서)
        self.roles:        list = []   # 각 줄 role
        self.tm_hits:      list = []   # TM 히트된 인덱스 (번역 스킵)

    @property
    def context(self) -> str:
        """Google에 보낼 조합 문자열 (묶음 전체)"""
        return "\n".join(self.texts)

    @property
    def needs_translation(self) -> bool:
        return len(self.line_indices) > len(self.tm_hits)


class RelationGrouper:
    """relation 필드 기반 묶음 단위 구성"""

    @staticmethod
    def _span_of(line) -> Optional[tuple]:
        """LyricLine의 span 속성 반환 (없으면 None)"""
        return getattr(line, "span", None)

    def build_groups(self, lines: list, tm_index: TMIndex) -> list:
        """
        lines: LyricLine 리스트 (text 속성 보유)
        반환: TranslationGroup 리스트 (순서 보장)

        span 경계 필터:
          같은 group 키라도 span(섹션)이 다른 줄은 같은 묶음으로 합치지 않는다.
          → group 키 + span 조합을 실제 묶음 키로 사용.
        """
        # group_key → { span_tuple → TranslationGroup }
        group_map: dict[str, dict] = {}
        solo_groups: list = []
        order: list = []   # (kind, lookup_key) 순서 보존

        for i, line in enumerate(lines):
            text = line.text.strip()
            if not text:
                continue

            rel  = getattr(line, "relation", None)
            span = self._span_of(line)  # (start, end) or None

            if rel and rel.get("group"):
                gkey     = rel["group"]
                span_key = span if span else ("nospan",)
                combo    = (gkey, span_key)   # 섹션 경계 필터 핵심

                if gkey not in group_map:
                    group_map[gkey] = {}
                if span_key not in group_map[gkey]:
                    group_map[gkey][span_key] = TranslationGroup()
                    order.append(("group", combo))

                g = group_map[gkey][span_key]
                g.line_indices.append(i)
                g.texts.append(text)
                g.roles.append(rel.get("role", ""))
                tm_hit = tm_index.lookup_tm(text)
                if tm_hit:
                    g.tm_hits.append(i)
            else:
                # relation 없는 줄 → 단독 그룹
                g = TranslationGroup()
                g.line_indices = [i]
                g.texts        = [text]
                g.roles        = ["anchor"]
                tm_hit = tm_index.lookup_tm(text)
                if tm_hit:
                    g.tm_hits = [i]
                solo_groups.append(g)
                order.append(("solo", len(solo_groups) - 1))

        # 순서대로 반환
        result = []
        for kind, key in order:
            if kind == "group":
                gkey, span_key = key
                result.append(group_map[gkey][span_key])
            else:
                result.append(solo_groups[key])
        return result


# ════════════════════════════════════════════════
# 3. 가사 API
# ════════════════════════════════════════════════

class LyricsProvider:
    def __init__(self):
        self._cache = {}
        self._translation_cache = {}  # 번역 캐시: track_key → [번역 텍스트 리스트]
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer":    "https://vibe.naver.com/",
            "Origin":     "https://vibe.naver.com",
            "Accept":     "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        # TM/TD 인덱스 로드
        self._tm_index = TMIndex()
        self._grouper  = RelationGrouper()
        _tm_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tm")
        self._tm_index.load(_tm_dir)

    def get_lyrics(self, artist: str, title: str) -> list:
        key = (artist.lower(), title.lower())
        if key in self._cache:
            return self._cache[key]
        lines = self._fetch_lrclib(artist, title) or []
        if lines:
            lines = self._tm_index.inject_relations(lines, artist, title)
        self._cache[key] = lines
        return lines

    def get_lyrics_by_vibe_trackid(self, track_id: int, cookies: str = "",
                                    artist: str = "", title: str = "") -> list:
        try:
            url = f"https://apis.naver.com/vibeWeb/musicapiweb/track/{track_id}/info"
            headers = dict(self._session.headers)
            if cookies:
                headers["Cookie"] = cookies
            r = requests.get(url, headers=headers, timeout=6)
            log.info(f"  VIBE API 응답: {r.status_code}, {len(r.content)}bytes (trackId: {track_id})")
            if r.status_code != 200 or not r.content:
                return []
            try:
                data = r.json()
            except json.JSONDecodeError:
                log.warning(f"VIBE API JSON 파싱 실패 (trackId: {track_id})")
                return []
            lines = self._parse_vibe_lyric_json(data)
            if lines:
                # LRCLIB 경로와 동일하게 relation+span 주입
                lines = self._tm_index.inject_relations(lines, artist, title)
                cache_key = f"vibe_{track_id}"
                self._cache[cache_key] = lines
                log.info(f"✅ VIBE 가사 로드 성공: {len(lines)}줄 (trackId: {track_id})")
            else:
                log.warning(f"VIBE 가사 파싱 실패 (trackId: {track_id})")
            return lines
        except Exception as e:
            log.error(f"Vibe lyric API 오류: {e} (trackId: {track_id})")
            return []

    def _parse_vibe_lyric_json(self, data: dict) -> list:
        try:
            lyric_obj = (
                data.get("response",{}).get("result",{}).get("trackInformation",{}) or
                data.get("response",{}).get("result",{}).get("lyric",{})
            )
            if not lyric_obj:
                return []
            # 형식 1: syncLyric 문자열
            sync_str = lyric_obj.get("syncLyric")
            if sync_str and isinstance(sync_str, str) and '|' in sync_str:
                lines = []
                for block in sync_str.split('#'):
                    if '|' in block:
                        time_str, text = block.split('|', 1)
                        try:
                            lines.append(LyricLine(time=float(time_str.strip()), text=text.strip()))
                        except ValueError:
                            continue
                if lines:
                    return lines
            # 형식 2: syncLyric dict
            sync_dict = lyric_obj.get("syncLyric")
            if sync_dict and isinstance(sync_dict, dict) and sync_dict.get("contents"):
                starts = sync_dict.get("startTimeIndex", [])
                texts  = sync_dict["contents"][0].get("text", [])
                lines  = []
                for i, text in enumerate(texts):
                    if i < len(starts):
                        lines.append(LyricLine(time=float(starts[i]), text=text.strip()))
                if lines:
                    return lines
            # 형식 3: 일반 가사
            plain = lyric_obj.get("lyric") or lyric_obj.get("normalLyric",{}).get("text","")
            if plain:
                raw = [l.strip() for l in plain.split('\n') if l.strip()]
                if raw:
                    return [LyricLine(time=i*4.0, text=line) for i, line in enumerate(raw)]
        except Exception as e:
            log.debug(f"VIBE JSON 파싱 오류: {e}")
        return []

    def is_korean(self, text: str) -> bool:
        """가사가 한국어인지 판별"""
        korean_chars = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3')
        total_alpha   = sum(1 for c in text if c.isalpha())
        if total_alpha == 0:
            return True
        return (korean_chars / total_alpha) > 0.3

    @staticmethod
    def _to_colloquial(text: str) -> str:
        """문어체 어미 → 구어체 변환"""
        if not text:
            return text
        # 순서 중요: 긴 패턴 먼저
        rules = [
            # 합니다체 → 해요체
            (r'입니다$',   '이야'),
            (r'입니다\.$', '이야.'),
            (r'합니다$',   '해'),
            (r'합니다\.$', '해.'),
            (r'했습니다$', '했어'),
            (r'됩니다$',   '돼'),
            (r'됩니다\.$', '돼.'),
            (r'십니다$',   '셔'),
            # 습니다/ㅂ니다
            (r'습니다$',   '어'),
            (r'ㅂ니다$',   '아'),
            # 었/았습니다
            (r'었습니다$', '었어'),
            (r'았습니다$', '았어'),
            # 겠습니다
            (r'겠습니다$', '겠어'),
            # 이다/였다
            (r'이었다$',   '이었어'),
            (r'였다$',     '였어'),
            (r'이다$',     '이야'),
            # ~다 → ~해/~어
            (r'한다$',     '해'),
            (r'한다\.$',   '해.'),
            (r'된다$',     '돼'),
            (r'간다$',     '가'),
            (r'온다$',     '와'),
            (r'준다$',     '줘'),
            (r'싶다$',     '싶어'),
            (r'없다$',     '없어'),
            (r'있다$',     '있어'),
            (r'같다$',     '같아'),
            (r'좋다$',     '좋아'),
            (r'크다$',     '커'),
            (r'하다$',     '해'),
        ]
        import re as _re
        for pattern, replacement in rules:
            text = _re.sub(pattern, replacement, text)
        return text

    def translate_lyrics(self, track_key: str, lines: list,
                         artist: str = "", title: str = "") -> list:
        """TM/TD/relation 기반 번역 파이프라인 v10"""
        if track_key in self._translation_cache:
            log.info(f"🌐 번역 캐시 hit: {track_key}")
            return self._translation_cache[track_key]

        try:
            translations = [""] * len(lines)

            # ① 한국어 줄은 스킵
            need_indices = {i for i, line in enumerate(lines)
                            if line.text.strip() and not self.is_korean(line.text.strip())}
            if not need_indices:
                self._translation_cache[track_key] = translations
                return translations

            # ② TM 완전일치 먼저 처리
            tm_hits = 0
            for i in list(need_indices):
                text = lines[i].text.strip()
                hit = self._tm_index.lookup_tm(text)
                if hit:
                    translations[i] = self._to_colloquial(hit)
                    need_indices.discard(i)
                    tm_hits += 1
            if tm_hits:
                log.info(f"  ✅ TM 히트: {tm_hits}줄")

            if not need_indices:
                self._translation_cache[track_key] = translations
                return translations

            # ③ relation.group 기반 묶음 구성
            groups = self._grouper.build_groups(lines, self._tm_index)

            log.info(f"🌐 번역 시작: {len(need_indices)}줄 / {len(groups)}그룹")

            for group in groups:
                # 이 그룹에서 번역 필요한 줄이 없으면 스킵
                active = [
                    (li, group.texts[j])
                    for j, li in enumerate(group.line_indices)
                    if li in need_indices
                ]
                if not active:
                    continue

                # ④ Google Translate (묶음 단위로 전송)
                context_texts = [group.texts[j]
                                 for j, li in enumerate(group.line_indices)
                                 if li in need_indices]
                joined = "\n".join(context_texts)

                try:
                    r = self._session.get(
                        "https://translate.googleapis.com/translate_a/single",
                        params={"client":"gtx","sl":"auto","tl":"ko","dt":"t","q": joined},
                        timeout=8
                    )
                    if r.status_code != 200:
                        log.warning(f"번역 HTTP {r.status_code}")
                        continue

                    data = r.json()
                    raw  = "".join(part[0] for part in data[0] if part[0])
                    results = [s.strip() for s in raw.split("\n")]
                    while len(results) < len(active):
                        results.append("")

                    for j, (orig_i, src_text) in enumerate(active):
                        t = results[j] if j < len(results) else ""

                        # ⑤ TD 교정
                        t = self._tm_index.apply_td(src_text, t)

                        # ⑥ 구어체 변환
                        t = self._to_colloquial(t)
                        translations[orig_i] = t

                except Exception as e:
                    log.warning(f"그룹 번역 실패 ({group.roles}): {e}")

            self._translation_cache[track_key] = translations
            log.info(f"✅ 번역 완료: {sum(1 for t in translations if t)}/{len(translations)}줄")
            return translations

        except Exception as e:
            log.error(f"번역 오류: {e}")
            return [""] * len(lines)  # 길이 보존 (빈 배열 반환 시 content.js 무시 방지)

    def _clean_search_text(self, text: str) -> str:
        """LRCLIB 검색용 텍스트 정규화"""
        # 전각 특수문자 → 반각
        text = text.replace('＆', '&').replace('！', '!').replace('？', '?')
        text = text.replace('（', '(').replace('）', ')').replace('　', ' ')
        # 괄호 안 부가정보 제거: (feat. xxx), [원곡: xxx], (Vocal Version) 등
        text = re.sub(r'\s*[\(\[\{][^\)\]\}]{0,30}[\)\]\}]', '', text)
        # 이모지 제거
        text = re.sub(r'[^\w\s\&\'\-]', ' ', text, flags=re.UNICODE)
        return text.strip()

    def _fetch_lrclib(self, artist: str, title: str) -> Optional[list]:
        attempts = []
        # 1차: 원본 그대로
        attempts.append((artist, title))
        # 2차: 클리닝
        ca, ct = self._clean_search_text(artist), self._clean_search_text(title)
        if (ca, ct) != (artist, title):
            attempts.append((ca, ct))
        # 3차: 타이틀만 첫 단어/구 (긴 제목 대비)
        short_title = ct.split('|')[0].split('-')[0].strip()
        if short_title and short_title != ct:
            attempts.append((ca, short_title))

        for a, t in attempts:
            try:
                log.info(f"   🔍 LRCLIB 검색: {a} - {t}")
                r = requests.get(
                    "https://lrclib.net/api/get",
                    params={"artist_name": a, "track_name": t},
                    timeout=5
                )
                if r.status_code == 200:
                    data = r.json()
                    lrc_text = data.get("syncedLyrics") or data.get("plainLyrics","")
                    if lrc_text:
                        lines = self._parse_lrc(lrc_text)
                        if lines:
                            log.info(f"✅ LRCLIB 가사 {len(lines)}줄: {a} - {t}")
                            return lines
                # 404면 다음 시도
                elif r.status_code not in (400, 404):
                    log.debug(f"LRCLIB HTTP {r.status_code}")
            except Exception as e:
                log.debug(f"LRCLIB error: {e}")
        return None

    def _parse_lrc(self, lrc_text: str) -> list:
        lines   = []
        pattern = re.compile(r'\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.+)')
        for line in lrc_text.split('\n'):
            m = pattern.match(line.strip())
            if m:
                t    = int(m.group(1))*60 + int(m.group(2)) + int((m.group(3) or '0').ljust(3,'0'))/1000
                text = m.group(4).strip()
                if text:
                    lines.append(LyricLine(time=t, text=text))
        return sorted(lines, key=lambda x: x.time)

# ════════════════════════════════════════════════
# 4. WebSocket 서버
# ════════════════════════════════════════════════

class BridgeServer:
    def __init__(self):
        self.smtc            = SMTCReader()
        self.wintitle        = WindowTitleReader()
        self.lyrics_provider = LyricsProvider()
        self.clients         = set()
        self._last_track_key  = ""
        self._current_lyrics  = []
        self._current_translations = []
        self._current_track   = TrackInfo()
        self._event_flag      = None
        self._current_cookies = ""  # content.js에서 받은 쿠키 저장

    async def handler(self, websocket):
        self.clients.add(websocket)
        log.info(f"🔌 클라이언트 연결됨: {websocket.remote_address}")
        try:
            await self._send_state(websocket)
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_client_message(data)
                except Exception as e:
                    log.debug(f"메시지 처리 오류: {e}")
        except Exception as e:
            log.debug(f"WS 통신 오류: {e}")
        finally:
            self.clients.discard(websocket)
            log.info("🔌 클라이언트 연결 종료")

    async def _handle_client_message(self, data: dict):
        msg_type   = data.get("type","")
        track_data = data.get("track",{})

        # ── trackid_found ──
        if msg_type == "trackid_found":
            vibe_track_id = data.get("track_id")
            if not vibe_track_id:
                return
            log.info(f"📥 content.js로부터 VIBE trackId 수신: {vibe_track_id}")

            # track_id · 쿠키는 항상 저장
            self._current_track.track_id = vibe_track_id
            cookies = data.get("cookies","")
            if cookies:
                self._current_cookies = cookies

            # LRCLIB 가사가 이미 있으면 VIBE로 교체하지 않음
            # (타임코드가 달라서 교체 순간 싱크 튐 발생 방지)
            if self._current_lyrics:
                log.info(f"  ℹ️  LRCLIB 가사 있음({len(self._current_lyrics)}줄) → VIBE 교체 스킵, trackId만 저장")
                return

            # LRCLIB 실패한 경우에만 VIBE API 호출
            log.info(f"  🎯 LRCLIB 가사 없음 → VIBE API 호출 (trackId: {vibe_track_id})")
            cache_key = f"vibe_{vibe_track_id}"
            self.lyrics_provider._cache.pop(cache_key, None)
            track_key = f"{self._current_track.artist}||{self._current_track.title}"
            self.lyrics_provider._translation_cache.pop(track_key, None)

            self._current_lyrics = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.lyrics_provider.get_lyrics_by_vibe_trackid(
                    vibe_track_id, cookies,
                    self._current_track.artist, self._current_track.title)
            )

            await self._broadcast({
                "type":         "update",
                "track":        asdict(self._current_track),
                "lyrics":       [{"time": l.time, "text": l.text} for l in self._current_lyrics],
                "translations": [],
            })
            # 번역은 백그라운드로
            asyncio.ensure_future(self._translate_and_broadcast())
            return

        # ── position_update ──
        if msg_type == "position_update":
            if track_data:
                self._current_track.position   = track_data.get("position",   self._current_track.position)
                self._current_track.is_playing = track_data.get("is_playing", self._current_track.is_playing)
                if track_data.get("track_id"):
                    self._current_track.track_id = track_data["track_id"]
            await self._broadcast({
                "type":         "update",
                "track":        asdict(self._current_track),
                "lyrics":       [{"time": l.time, "text": l.text} for l in self._current_lyrics],
                "translations": self._current_translations,
            })
            return

        # ── track_change ──
        if msg_type == "track_change":
            self._current_lyrics = []
            await self._broadcast({"type":"track_change","track":track_data,"lyrics":[]})
            return

    async def _translate_and_broadcast(self):
        """가사 번역 후 브로드캐스트 - 배치 우선, 빈 줄은 병렬 fallback"""
        if not self._current_lyrics:
            return
        track_key = f"{self._current_track.artist}||{self._current_track.title}"

        # 1차: TM 파이프라인 + 배치 번역 (executor에서 실행)
        artist = self._current_track.artist
        title  = self._current_track.title
        translations = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.lyrics_provider.translate_lyrics(
                track_key, self._current_lyrics, artist, title)
        )

        # translate_lyrics가 완전 빈 배열([])을 반환한 경우 길이 맞춤
        if not translations:
            translations = [""] * len(self._current_lyrics)

        # 2차: 배치에서 빠진 줄 병렬 fallback
        missing = [(i, self._current_lyrics[i].text.strip())
                   for i, t in enumerate(translations)
                   if not t and self._current_lyrics[i].text.strip()
                   and not self.lyrics_provider.is_korean(self._current_lyrics[i].text.strip())]

        if missing:
            log.info(f"🌐 fallback 병렬 번역: {len(missing)}줄")
            async def fetch_one(idx, text):
                try:
                    loop = asyncio.get_event_loop()
                    r = await loop.run_in_executor(None, lambda: self.lyrics_provider._session.get(
                        "https://translate.googleapis.com/translate_a/single",
                        params={"client":"gtx","sl":"auto","tl":"ko","dt":"t","q":text},
                        timeout=6
                    ))
                    if r.status_code == 200:
                        data = r.json()
                        t = "".join(p[0] for p in data[0] if p[0])
                        # TD 교정 + 구어체 변환
                        t = self.lyrics_provider._tm_index.apply_td(text, t)
                        return idx, self.lyrics_provider._to_colloquial(t)
                except Exception:
                    pass
                return idx, ""
            results = await asyncio.gather(*[fetch_one(i, t) for i, t in missing])
            for idx, t in results:
                translations[idx] = t
            # 캐시 업데이트
            self.lyrics_provider._translation_cache[track_key] = translations

        self._current_translations = translations
        await self._broadcast({
            "type":         "update",
            "track":        asdict(self._current_track),
            "lyrics":       [{"time": l.time, "text": l.text} for l in self._current_lyrics],
            "translations": self._current_translations,
        })

    async def _send_state(self, ws):
        try:
            await ws.send(json.dumps({
                "track":  asdict(self._current_track),
                "lyrics": [{"time": l.time, "text": l.text} for l in self._current_lyrics],
            }, ensure_ascii=False))
        except:
            pass

    async def _broadcast(self, data: dict):
        if not self.clients:
            return
        msg = json.dumps(data, ensure_ascii=False)
        await asyncio.gather(*[c.send(msg) for c in list(self.clients)], return_exceptions=True)

    # ── 폴링 루프 ──
    async def poll_loop(self):
        log.info(f"🎵 미디어 폴링 시작 (간격: {POLL_INTERVAL}s)")
        self._event_flag = asyncio.Event()
        loop = asyncio.get_event_loop()

        def on_smtc_event(reason):
            loop.call_soon_threadsafe(self._event_flag.set)

        await self._attach_smtc_events(on_smtc_event)

        while True:
            track = await self._read_track()

            if track and self._is_browser_title(track):
                track = None

            if track:
                if self._current_track.track_id and \
                   track.title == self._current_track.title and \
                   track.artist == self._current_track.artist:
                    track.track_id = self._current_track.track_id

                track_key = f"{track.artist}||{track.title}"

                if track_key != self._last_track_key and track.title:
                    self._last_track_key = track_key
                    log.info(f"🎶 새 곡 감지: {track.artist} - {track.title}")
                    self._current_lyrics = []
                    await self._broadcast({"type":"track_change","track":asdict(track),"lyrics":[]})

                    # 1) LRCLIB 먼저 시도
                    log.info(f"   🔍 LRCLIB 검색: {track.artist} - {track.title}")
                    self._current_lyrics = await asyncio.get_event_loop().run_in_executor(
                        None, self.lyrics_provider.get_lyrics, track.artist, track.title
                    )
                    if self._current_lyrics:
                        log.info(f"   ✅ LRCLIB {len(self._current_lyrics)}줄")
                        self._current_translations = []
                        asyncio.ensure_future(self._translate_and_broadcast())
                    else:
                        log.warning(f"   ⚠️  LRCLIB 가사 없음 - VIBE trackId 대기 중...")
                        # 2) LRCLIB 실패 시 DOM trackId 대기 후 VIBE API 시도
                        for _ in range(10):  # 최대 5초 대기
                            await asyncio.sleep(0.5)
                            tid = self._current_track.track_id
                            if tid:
                                log.info(f"   🎯 VIBE API 시도: trackId={tid}")
                                cache_key = f"vibe_{tid}"
                                self.lyrics_provider._cache.pop(cache_key, None)
                                self._current_lyrics = await asyncio.get_event_loop().run_in_executor(
                                    None, lambda: self.lyrics_provider.get_lyrics_by_vibe_trackid(
                                        tid, self._current_cookies,
                                        track.artist, track.title)
                                )
                                if self._current_lyrics:
                                    log.info(f"   ✅ VIBE {len(self._current_lyrics)}줄")
                                    await self._broadcast({
                                        "type":   "update",
                                        "track":  asdict(self._current_track),
                                        "lyrics": [{"time": l.time, "text": l.text} for l in self._current_lyrics],
                                    })
                                    asyncio.ensure_future(self._translate_and_broadcast())
                                break

                # 현재 트랙 정보 업데이트
                self._current_track.title      = track.title
                self._current_track.artist     = track.artist
                self._current_track.album      = track.album
                self._current_track.position   = track.position
                self._current_track.duration   = track.duration
                self._current_track.is_playing = track.is_playing
                self._current_track.thumbnail  = track.thumbnail

                await self._broadcast({
                    "type":         "update",
                    "track":        asdict(self._current_track),
                    "lyrics":       [{"time": l.time, "text": l.text} for l in self._current_lyrics],
                    "translations": self._current_translations,
                })
            else:
                if self._last_track_key:
                    self._last_track_key = ""
                    log.info("⏹ 재생 중지됨")
                    await self._broadcast({"type":"stopped"})

            try:
                await asyncio.wait_for(self._event_flag.wait(), timeout=POLL_INTERVAL)
                self._event_flag.clear()
            except asyncio.TimeoutError:
                pass

    async def _attach_smtc_events(self, callback):
        if not self.smtc._available:
            return
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
            manager = await Manager.request_async()
            manager.add_current_session_changed(lambda m, _: callback("session_changed"))
            session = manager.get_current_session()
            if session:
                session.add_media_properties_changed(lambda s, _: callback("media_changed"))
                session.add_playback_info_changed(lambda s, _: callback("playback_changed"))
                log.info("✅ SMTC 이벤트 리스너 등록 완료")
                log.info("   → 다음 곡 넘어가면 즉시 자동 감지됩니다")
        except Exception as e:
            log.debug(f"SMTC event attach error: {e}")
            log.info("⚠️  SMTC 이벤트 리스너 실패 → 폴링 단독 모드")

    async def _read_track(self) -> Optional[TrackInfo]:
        track = await self.smtc.get_current_track()
        if not track:
            track = self.wintitle.get_current_track()
        return track

    @staticmethod
    def _is_browser_title(track: TrackInfo) -> bool:
        combined = f"{track.title} {track.artist}"
        junk = [
            # 브라우저
            "Chrome", "Edge", "Firefox", "Safari", "Opera", "Whale",
            "Chromium", "Brave",
            # 포털·서비스
            "Google", "Naver", "네이버", "Daum", "카카오", "Kakao",
            "YouTube", "Twitch", "Instagram", "Twitter", "Facebook",
            "TikTok", "Reddit", "Discord", "Slack", "Notion",
            # AI 도구
            "Claude", "ChatGPT", "Copilot", "Gemini", "Perplexity",
            # VIBE UI 텍스트
            "VIBE(바이브)", "보관함", "플레이리스트", "공지사항",
            "실시간 방송", "차트", "새로운 발견",
            # 개발·디버그
            "localhost", "127.0.0.1", "http://", "https://",
            "VS Code", "Visual Studio", "개발자 도구", "DevTools",
            # 시스템·OS
            "새 탭", "New Tab", "설정", "파일 탐색기", "작업 관리자",
            "Windows", "Microsoft", "PowerShell", "Terminal",
        ]
        for j in junk:
            if j.lower() in combined.lower():
                return True
        # 아티스트 없고 제목이 너무 길면 브라우저 탭 제목
        if not track.artist.strip() and len(track.title) > 40:
            return True
        # 브라우저 breadcrumb 패턴 (예: "페이지 > 섹션 > 항목")
        if " > " in track.title or " - " * 2 in track.title:
            return True
        return False

    async def start(self):
        import websockets
        log.info(f"🚀 브릿지 서버 시작: ws://{WS_HOST}:{WS_PORT}")
        async with websockets.serve(self.handler, WS_HOST, WS_PORT):
            await self.poll_loop()

# ════════════════════════════════════════════════
# 5. HTTP 서버
# ════════════════════════════════════════════════

def start_http_server(port=6790):
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("localhost", port), SimpleHTTPRequestHandler)
    log.info(f"📡 HTTP 서버: http://localhost:{port}/obs_overlay.html")
    server.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()
    bridge = BridgeServer()
    try:
        asyncio.run(bridge.start())
    except KeyboardInterrupt:
        log.info("👋 서버 종료")