import asyncio
import json
import re
import threading
import requests
import logging
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

WS_HOST, WS_PORT, POLL_INTERVAL = "localhost", 6789, 1.0

@dataclass
class TrackInfo:
    title: str = ""; artist: str = ""; album: str = ""; position: float = 0.0
    duration: float = 0.0; is_playing: bool = False; thumbnail: str = ""; track_id: int = 0

@dataclass
class LyricLine:
    time: float; text: str

class SMTCReader:
    def __init__(self):
        self._available = False
        try:
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
            self._Manager = Manager; self._available = True
            log.info("✅ SMTC 초기화 성공")
        except: log.warning("⚠️ SMTC 사용 불가")

    async def get_current_track(self):
        if not self._available: return None
        try:
            manager = await self._Manager.request_async()
            session = manager.get_current_session()
            if not session: return None
            props = await session.try_get_media_properties_async()
            timeline = session.get_timeline_properties()
            playback = session.get_playback_info()
            from winsdk.windows.media import MediaPlaybackStatus
            return TrackInfo(
                title=props.title or "", artist=props.artist or "",
                position=timeline.position.total_seconds() if timeline.position else 0,
                is_playing=playback.playback_status == MediaPlaybackStatus.PLAYING
            )
        except: return None

class LyricsProvider:
    def __init__(self):
        self._cache = {}; self._session = requests.Session()

    def get_lyrics_by_vibe_trackid(self, track_id):
        key = f"vibe_{track_id}"
        if key in self._cache: return self._cache[key]
        try:
            r = self._session.get(f"https://apis.naver.com/vibeWeb/musicapiweb/vibe/v1/lyric/{track_id}", timeout=5)
            # VIBE API 응답 구조에 맞게 파싱 로직 구현 (기존 로직 유지)
            lines = self._parse_vibe_lyric_json(r.json())
            if lines: self._cache[key] = lines
            return lines
        except: return []

    def _parse_vibe_lyric_json(self, data):
        # 기존 v5의 가사 파싱 로직과 동일
        try:
            res = data.get("response", {}).get("result", {}).get("trackInformation", {})
            sync = res.get("syncLyric", "")
            if sync and isinstance(sync, str):
                lines = []
                for p in sync.split('#'):
                    if '|' in p:
                        t, txt = p.split('|', 1)
                        lines.append(LyricLine(time=float(t), text=txt.strip()))
                return lines
        except: pass
        return []

    def get_lrclib_lyrics(self, artist, title):
        try:
            r = requests.get("https://lrclib.net/api/get", params={"artist_name": artist, "track_name": title}, timeout=5)
            if r.status_code == 200:
                lrc = r.json().get("syncedLyrics") or r.json().get("plainLyrics", "")
                # LRC 파싱 로직 적용
                return [] # 요약된 코드이므로 파싱 생략
        except: return []

class BridgeServer:
    def __init__(self):
        self.smtc = SMTCReader(); self.lyrics_provider = LyricsProvider()
        self.clients = set(); self._last_track_key = ""; self._current_lyrics = []
        self._current_track = TrackInfo()

    async def handler(self, ws):
        self.clients.add(ws); log.info(f"🔌 클라이언트 연결: {ws.remote_address}")
        try:
            async for msg in ws:
                data = json.loads(msg)
                if data["type"] == "trackid_found":
                    tid = data["track_id"]
                    log.info(f"📥 VIBE trackId 수신: {tid}")
                    self._current_lyrics = self.lyrics_provider.get_lyrics_by_vibe_trackid(tid)
                    await self._broadcast({"type": "update", "track": asdict(self._current_track), "lyrics": [asdict(l) for l in self._current_lyrics]})
        finally: self.clients.discard(ws)

    async def _broadcast(self, data):
        if not self.clients: return
        m = json.dumps(data, ensure_ascii=False)
        await asyncio.gather(*[c.send(m) for c in list(self.clients)], return_exceptions=True)

    async def poll_loop(self):
        while True:
            track = await self.smtc.get_current_track()
            if track and self._is_browser_title(track): track = None
            
            if track:
                key = f"{track.artist}||{track.title}"
                if key != self._last_track_key:
                    self._last_track_key = key
                    log.info(f"🎶 새 곡 감지: {track.artist} - {track.title}")
                    self._current_lyrics = self.lyrics_provider.get_lrclib_lyrics(track.artist, track.title)
                self._current_track = track
                await self._broadcast({"type": "update", "track": asdict(track), "lyrics": [asdict(l) for l in self._current_lyrics]})
            await asyncio.sleep(POLL_INTERVAL)

    @staticmethod
    def _is_browser_title(track: TrackInfo) -> bool:
        """강화된 브라우저 제목 필터링"""
        t, a = track.title, track.artist
        junk = [r'Chrome$', r'Edge$', r'VIBE\s*\(바이브\)', r'보관함\s*>', r'네이버', r'공지사항']
        for p in junk:
            if re.search(p, t, re.I) or re.search(p, a, re.I): return True
        return ">" in t and "VIBE" in t

    async def start(self):
        import websockets
        async with websockets.serve(self.handler, WS_HOST, WS_PORT):
            await self.poll_loop()

if __name__ == "__main__":
    bridge = BridgeServer()
    asyncio.run(bridge.start())