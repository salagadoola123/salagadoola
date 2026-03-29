/**
 * VIBE 가사지 content.js v15.5
 * v15.3: LRCLIB→VIBE 가사 소스 교체 시 G_pos 리셋 방지
 * v15.4: 싱크 오프셋 조절 기능 추가
 * v15.5: vibePos 확정 재시도 (300ms~1.5s), 번역 줄 수 불일치 무시
 */

const WS_URL = 'ws://localhost:6789';
let ws = null, wsReady = false;
let currentTrackId = 0, lastSentId = 0;

let G_lyrics   = [];
let G_translations = [];  // 번역 배열
let G_trackKey = '';
let G_pos      = 0;
let G_lastIdx  = -1;
let G_timer    = null;
let G_lastWall = null;
let G_isPlaying = true;

// ── VIBE playTime ──
function getVibePos() {
  const t = parseFloat(document.body.getAttribute('data-vibe-time'));
  return (isNaN(t) || t <= 0) ? -1 : t;
}

// ── 가사 표시 ──
// 폰트 설정 전역
let G_font_ko = "'NanumOgBiCe','Noto Sans KR',sans-serif";
let G_font_en = "'NanumOgBiCe','Noto Sans KR',sans-serif";
let G_size    = 30; // 현재 가사 기준 px
let G_prevCount = 1; // 이전 가사 표시 줄 수
let G_offset  = 0;  // 가사 싱크 오프셋 (초). 양수=빠르게, 음수=늦게

function applySize(size) {
  G_size = size;
  const s = size / 100 * (100/30); // 30px 기준
  const next     = document.getElementById('gasaji-next');
  const nextTrans= document.getElementById('gasaji-next-trans');
  const cur      = document.getElementById('gasaji-cur');
  const curTrans = document.getElementById('gasaji-cur-trans');
  if (next)      next.style.fontSize      = Math.round(size * 0.6)  + 'px';
  if (nextTrans) nextTrans.style.fontSize = Math.round(size * 0.47) + 'px';
  if (cur)       cur.style.fontSize       = size + 'px';
  if (curTrans)  curTrans.style.fontSize  = Math.round(size * 0.73) + 'px';
}

function isKorean(text) {
  const korean = (text.match(/[\uAC00-\uD7A3]/g) || []).length;
  const alpha   = (text.match(/[a-zA-Z]/g) || []).length;
  return korean > 0 && korean / (korean + alpha + 1) > 0.3;
}

function applyFont(el, text) {
  if (!el) return;
  el.style.fontFamily = isKorean(text) ? G_font_ko : G_font_en;
}

function applyShimmer(el, on) {
  if (on) {
    el.classList.add('shimmer-on');
  } else {
    el.classList.remove('shimmer-on');
  }
}

function showLyric(idx) {
  const safeIdx = Math.max(0, Math.min(idx < 0 ? 0 : idx, G_lyrics.length - 1));
  G_lastIdx = safeIdx;

  const cur      = document.getElementById('gasaji-cur');
  const curTrans = document.getElementById('gasaji-cur-trans');
  const next     = document.getElementById('gasaji-next');
  const nextTrans= document.getElementById('gasaji-next-trans');
  const inner    = document.getElementById('gasaji-inner');
  if (!cur || !inner) return;

  // 현재 가사
  const ct  = G_lyrics[safeIdx]?.text?.trim()    ?? '';
  const ctt = G_translations[safeIdx]?.trim()     ?? '';
  // 다음 가사
  const nt  = G_lyrics[safeIdx+1]?.text?.trim()   ?? '';
  const ntt = G_translations[safeIdx+1]?.trim()   ?? '';

  cur.textContent = ct;
  if (curTrans)  curTrans.textContent  = ctt;
  if (next)      next.textContent      = nt;
  if (nextTrans) nextTrans.textContent = '';  // 다음 가사 번역은 표시 안 함

  applyFont(cur, ct);
  applyFont(curTrans, ctt);
  applyFont(next, nt);

  applyShimmer(cur, ct && !isKorean(ct));

  cur.style.display       = ct  ? 'block' : 'none';
  if (curTrans)  curTrans.style.display  = ctt ? 'block' : 'none';
  if (next)      next.style.display      = nt  ? 'block' : 'none';
  if (nextTrans) nextTrans.style.display = 'none';  // 항상 숨김

  // 이전 가사 N줄 동적 생성
  // 기존 prev 줄들 제거
  inner.querySelectorAll('.gasaji-prev-line, .gasaji-prev-trans-line').forEach(el => el.remove());

  for (let i = 1; i <= G_prevCount; i++) {
    const pIdx = safeIdx - i;
    const pt  = pIdx >= 0 ? (G_lyrics[pIdx]?.text?.trim()    ?? '') : '';
    const ptt = pIdx >= 0 ? (G_translations[pIdx]?.trim()    ?? '') : '';
    const opacity = 1 - (i - 1) * (0.25 / G_prevCount); // 멀수록 흐리게

    // 이전 번역 (먼저 append = column-reverse라 위에 표시)
    const ptEl = document.createElement('div');
    ptEl.className = 'gasaji-prev-trans-line';
    ptEl.textContent = ptt;
    ptEl.style.cssText = `font-size:${Math.round(G_size*0.47)}px; font-weight:400;
      color:rgba(255,255,255,${(0.4 * opacity).toFixed(2)});
      text-align:center; text-shadow:0 0 3px #000,0 0 3px #000;
      display:${ptt ? 'block' : 'none'};`;
    applyFont(ptEl, ptt);

    // 이전 가사
    const pEl = document.createElement('div');
    pEl.className = 'gasaji-prev-line';
    pEl.textContent = pt;
    pEl.style.cssText = `font-size:${Math.round(G_size*0.6)}px; font-weight:500;
      color:rgba(255,255,255,${(0.65 * opacity).toFixed(2)});
      text-align:center; text-shadow:0 0 3px #000,0 0 3px #000,0 0 3px #000;
      display:${pt ? 'block' : 'none'};`;
    applyFont(pEl, pt);

    inner.appendChild(ptEl);
    inner.appendChild(pEl);
  }
}

function findIdx(pos) {
  const adjusted = pos + G_offset;
  let idx = -1;
  for (let i = 0; i < G_lyrics.length; i++) {
    if (G_lyrics[i].time <= adjusted) idx = i; else break;
  }
  return idx;
}

// ── rAF 타이머 ──
function startTimer() {
  if (G_timer) return;
  G_lastWall = performance.now();
  function raf() {
    const now     = performance.now();
    const vibePos = getVibePos();
    if (vibePos >= 0) {
      G_pos = vibePos; // 칼싱크
    } else if (G_isPlaying) {
      G_pos += (now - G_lastWall) / 1000;
    }
    G_lastWall = now;
    if (G_lyrics.length) showLyric(findIdx(G_pos));
    G_timer = requestAnimationFrame(raf);
  }
  G_timer = requestAnimationFrame(raf);
}

function stopTimer() {
  if (G_timer) { cancelAnimationFrame(G_timer); G_timer = null; }
}

function clearAll() {
  stopTimer();
  G_lyrics = []; G_trackKey = '';
  G_pos = 0; G_lastIdx = -1;
  ['gasaji-cur','gasaji-cur-trans','gasaji-prev','gasaji-prev-trans'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.style.display = 'none'; }
  });
}

// ── 새 곡 시작: 500ms 후 playTime 읽어서 시작점 확정 ──
let _startTimer = null;
function startNewTrack(lyr, isReload) {
  // isReload=true : 같은 곡의 가사 소스 교체 (LRCLIB→VIBE)
  //   → G_pos 리셋 없이 현재 재생 위치 즉시 적용
  stopTimer();
  if (_startTimer) { clearTimeout(_startTimer); _startTimer = null; }

  G_trackKey = lyr[0].text + '|' + lyr.length;
  G_lyrics   = lyr;
  G_lastIdx  = -1;

  if (isReload) {
    // 가사 소스 교체: vibePos 즉시 반영, pos 리셋 없음
    const vibePos = getVibePos();
    if (vibePos > 0) { G_pos = vibePos; }
    console.log('[가사지] 🔄 가사 교체 (pos 유지: ' + G_pos.toFixed(1) + 's)');
    showLyric(findIdx(G_pos));
    startTimer();
  } else {
    // 진짜 새 곡: pos 리셋 후 vibePos 확정까지 재시도
    G_pos = 0;
    showLyric(0);

    let _retryCount = 0;
    const _maxRetry = 12; // 100ms 간격 × 12 = 최대 1.2초 대기
    function tryConfirmStart() {
      const vibePos = getVibePos();
      if (vibePos > 0) {
        G_pos = vibePos;
        G_lastIdx = -1;
        console.log('[가사지] 🎯 시작점 확정: ' + vibePos.toFixed(1) + 's (시도:' + (_retryCount+1) + ')');
        startTimer();
      } else if (_retryCount < _maxRetry) {
        _retryCount++;
        _startTimer = setTimeout(tryConfirmStart, 100);
      } else {
        console.log('[가사지] ⚠️ playTime 없음, 0부터 시작');
        startTimer();
      }
    }
    _startTimer = setTimeout(tryConfirmStart, 300);
  }
}

// ── 일시정지 감지 ──
let _lastPlayState = null;
setInterval(() => {
  const playing = !!document.querySelector(
    '[aria-label*="일시정지"],[aria-label*="Pause"],[aria-label*="pause"]'
  );
  if (playing === _lastPlayState) return;
  _lastPlayState = playing;
  G_isPlaying    = playing;
  if (playing && !G_timer && G_lyrics.length) startTimer();
}, 200);

// ── 위젯 주입 ──
function injectWidget() {
  if (document.getElementById('gasaji-widget')) return;
  const style = document.createElement('style');
  style.textContent = `
    @font-face { font-family:'NanumOgBiCe'; src:local('Nanum OgBiCe'),local('NanumOgBiCe'); }
    #gasaji-widget {
      position:fixed!important; bottom:80px!important; left:50%!important;
      transform:translateX(-50%)!important; z-index:2147483647!important;
      width:90%; max-width:800px;
      pointer-events:none; user-select:none;
      font-family:'NanumOgBiCe','Noto Sans KR',sans-serif;
    }
    #gasaji-inner { display:flex; flex-direction:column-reverse; align-items:center; gap:16px; }

    /* 이전 가사/번역은 JS에서 동적 생성 */
    /* 현재 가사 - 빨강 */
    #gasaji-cur {
      font-size:30px; font-weight:800;
      color: #ff4444;
      text-align:center;
      text-shadow: 0 0 4px #000, 0 0 4px #000, 0 0 4px #000;
    }
    /* 현재 번역 - 순수 흰색 */
    #gasaji-cur-trans {
      font-size:22px; font-weight:700;
      color: #ffffff;
      text-align:center;
      text-shadow: 0 0 4px #000, 0 0 4px #000, 0 0 4px #000;
    }
    /* 다음 가사 - 흰색 흐리게 */
    #gasaji-next {
      font-size:18px; font-weight:600;
      color: rgba(255,255,255,0.45);
      text-align:center;
    }
    #gasaji-next-trans {
      font-size:14px; font-weight:400;
      color: rgba(255,255,255,0.25);
      text-align:center;
    }
  `;
  document.head.appendChild(style);
  const w = document.createElement('div');
  w.id = 'gasaji-widget';
  w.innerHTML = `
    <div style="position:relative">
      <div id="gasaji-inner">
        <div id="gasaji-next-trans"></div>
        <div id="gasaji-next"></div>
        <div id="gasaji-cur-trans"></div>
        <div id="gasaji-cur"></div>
      </div>
    </div>`;
  document.body.appendChild(w);

  // 저장된 위치 복원
  chrome.storage.local.get(['gasaji_x','gasaji_y'], d => {
    if (d.gasaji_x !== undefined) {
      w.style.left      = d.gasaji_x + 'px';
      w.style.bottom    = d.gasaji_y + 'px';
      w.style.transform = 'none';
    }
  });
}

function badge(t,c){
  const b=document.getElementById('gasaji-badge');
  if(!b) return;
  b.textContent=t;
  b.style.color=c;
  if(t.includes('LIVE')){
    b.style.borderColor='rgba(255,68,68,0.4)';
    b.style.boxShadow='0 0 8px rgba(255,68,68,0.3)';
    b.classList.add('live');
  } else {
    b.style.borderColor='rgba(255,255,255,0.1)';
    b.style.boxShadow='none';
    b.classList.remove('live');
  }
}
function send(d){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify(d));}

// ── WebSocket ──
function connectWS() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    wsReady = true;
    badge('● LIVE','rgba(168,255,120,0.9)');
    if (currentTrackId>0 && currentTrackId!==lastSentId) setTimeout(sendId,300);
  };
  ws.onmessage = e => {
    let msg; try{msg=JSON.parse(e.data);}catch{return;}
    if (msg.type==='track_change'){G_trackKey='';G_translations=[];return;}
    const lyr=msg.lyrics;
    if (!Array.isArray(lyr)||lyr.length===0){clearAll();return;}
    const key=lyr[0].text+'|'+lyr.length;
    if (key!==G_trackKey) {
      // 가사가 이미 로드된 상태에서 줄 수만 달라진 경우 = 소스 교체 (LRCLIB→VIBE)
      // G_lyrics가 있고 trackKey가 설정돼 있으면 reload, 아예 새 곡이면 false
      const isReload = G_lyrics.length > 0 && G_trackKey !== '';
      startNewTrack(lyr, isReload);
      console.log('[가사지] ' + (isReload ? '🔄 가사교체 ' : '🎵 새곡 ') + lyr.length + '줄');
    } else {
      if (!G_timer) startTimer();
    }
    // 번역 업데이트 (언제든 오면 즉시 반영, 빈 배열도 처리)
    if (Array.isArray(msg.translations)) {
      if (msg.translations.length > 0) {
        // 현재 가사 줄 수와 일치할 때만 반영 (이전 곡 번역 혼입 방지)
        if (msg.translations.length === G_lyrics.length) {
          G_translations = msg.translations;
          G_lastIdx = -1; // 강제 리렌더
          console.log('[가사지] 🌐 번역 수신 '+msg.translations.length+'줄');
        } else {
          console.log('[가사지] ⚠️ 번역 줄 수 불일치 무시: ' + msg.translations.length + '줄 (현재 ' + G_lyrics.length + '줄)');
        }
      }
    }
  };
  ws.onclose = ()=>{
    wsReady=false; stopTimer();
    badge('● 재연결...','rgba(255,80,80,0.8)');
    setTimeout(connectWS,2000);
  };
  ws.onerror = ()=>{wsReady=false;};
}

// ── DOM trackId 감지 (vibe_bridge.js가 기록) ──
let _lastDomTrackId = 0;
setInterval(() => {
  const id = parseInt(document.body.getAttribute('data-vibe-trackid') || '0');
  if (id > 0 && id !== _lastDomTrackId && id !== currentTrackId) {
    _lastDomTrackId = id;
    currentTrackId = id;
    lastSentId = 0;
    if (wsReady) sendId();
    console.log('[가사지] 🔍 DOM trackId→' + id);
  }
}, 300);

// ── fetch/Network trackId 감지 ──
function extractId(url){const m=url.match(/\/track\/(\d{5,})\/info/);return m?parseInt(m[1]):0;}

function sendId(){
  if(!wsReady||!currentTrackId||currentTrackId===lastSentId)return;
  lastSentId=currentTrackId;
  send({type:'trackid_found',track_id:currentTrackId,
        track:{title:'',artist:'',track_id:currentTrackId,position:0,is_playing:true},
        cookies:document.cookie});
  console.log('[가사지] ✅ trackId→'+currentTrackId);
}

const _origFetch=window.fetch;
window.fetch=async function(...args){
  const res=await _origFetch.apply(this,args);
  const url=args[0] instanceof Request?args[0].url:String(args[0]);
  const id=extractId(url);
  if(id>0&&id!==currentTrackId){currentTrackId=id;lastSentId=0;if(wsReady)sendId();}
  return res;
};

new PerformanceObserver(list=>{
  for(const e of list.getEntries()){
    const id=extractId(e.name);
    if(id>0&&id!==currentTrackId){currentTrackId=id;lastSentId=0;if(wsReady)sendId();}
  }
}).observe({entryTypes:['resource']});

function initTrackId(){
  const entries=performance.getEntriesByType('resource');
  for(let i=entries.length-1;i>=Math.max(0,entries.length-100);i--){
    const id=extractId(entries[i].name);
    if(id>0){currentTrackId=id;sendId();return;}
  }
}
setTimeout(initTrackId,500);
setTimeout(initTrackId,2000);
setTimeout(initTrackId,5000);

setInterval(()=>{
  if(!wsReady)return;
  send({type:'position_update',track:{title:'',artist:'',track_id:currentTrackId,position:G_pos,is_playing:G_isPlaying}});
},1000);

chrome.runtime.onMessage.addListener((msg,_,res)=>{
  if(msg.type==='get_status'){res({connected:wsReady,lyrics:G_lyrics.length,pos:G_pos,wp:getVibePos()});return true;}
  if(msg.type==='set_font'){
    if(msg.font_ko)    G_font_ko = msg.font_ko;
    if(msg.font_en)    G_font_en = msg.font_en;
    if(msg.size)       applySize(msg.size);
    if(msg.prev_count) G_prevCount = msg.prev_count;
    G_lastIdx = -1;
    return true;
  }
  if(msg.type==='set_offset'){
    G_offset = typeof msg.offset === 'number' ? msg.offset : 0;
    G_lastIdx = -1;
    return true;
  }
  if(msg.type==='move_widget'){
    const w = document.getElementById('gasaji-widget');
    if(!w) return;
    const step = msg.step || 10;
    const r = w.getBoundingClientRect();
    let curLeft   = r.left + r.width/2;
    let curBottom = window.innerHeight - r.bottom;
    if(msg.dir==='up')    curBottom += step;
    if(msg.dir==='down')  curBottom -= step;
    if(msg.dir==='left')  curLeft   -= step;
    if(msg.dir==='right') curLeft   += step;
    w.style.left      = curLeft   + 'px';
    w.style.bottom    = curBottom + 'px';
    w.style.transform = 'none';
    chrome.storage.local.set({ gasaji_x: curLeft, gasaji_y: curBottom });
    return true;
  }
});

// 저장된 폰트 불러오기
chrome.storage.local.get(['gasaji_font_ko','gasaji_font_en','gasaji_size','gasaji_prev_count','gasaji_offset'], d => {
  if (d.gasaji_font_ko)    G_font_ko    = d.gasaji_font_ko;
  if (d.gasaji_font_en)    G_font_en    = d.gasaji_font_en;
  if (d.gasaji_size)       setTimeout(() => applySize(d.gasaji_size), 600);
  if (d.gasaji_prev_count) G_prevCount  = d.gasaji_prev_count;
  if (typeof d.gasaji_offset === 'number') G_offset = d.gasaji_offset;
});

injectWidget();
connectWS();
console.log('[가사지 v15.5] 로드됨');