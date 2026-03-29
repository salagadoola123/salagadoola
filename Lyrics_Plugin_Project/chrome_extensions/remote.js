const fontKo    = document.getElementById('font-ko');
const fontEn    = document.getElementById('font-en');
const slider    = document.getElementById('size-slider');
const sizeLabel = document.getElementById('size-label');
const prevSlider = document.getElementById('prev-slider');
const prevLabel  = document.getElementById('prev-label');
const preKo     = document.getElementById('preview-ko');
const preEn     = document.getElementById('preview-en');
const applyBtn  = document.getElementById('apply-btn');
const offsetSlider = document.getElementById('offset-slider');
const offsetLabel  = document.getElementById('offset-label');

// 저장된 설정 불러오기
chrome.storage.local.get(['gasaji_font_ko','gasaji_font_en','gasaji_size','gasaji_prev_count','gasaji_offset'], d => {
  if (d.gasaji_font_ko)    { fontKo.value = d.gasaji_font_ko; preKo.style.fontFamily = d.gasaji_font_ko; }
  if (d.gasaji_font_en)    { fontEn.value = d.gasaji_font_en; preEn.style.fontFamily = d.gasaji_font_en; }
  if (d.gasaji_size)       { slider.value = d.gasaji_size; sizeLabel.textContent = d.gasaji_size + 'px'; updatePreviewSize(d.gasaji_size); }
  if (d.gasaji_prev_count) { prevSlider.value = d.gasaji_prev_count; prevLabel.value = d.gasaji_prev_count; }
  if (typeof d.gasaji_offset === 'number') {
    offsetSlider.value = d.gasaji_offset;
    offsetLabel.textContent = (d.gasaji_offset >= 0 ? '+' : '') + d.gasaji_offset.toFixed(1) + 's';
  }
});

// 오프셋 슬라이더 - 실시간 즉시 반영 (적용 버튼 불필요)
function sendOffset(val) {
  const offset = parseFloat(val);
  const sign = offset >= 0 ? '+' : '';
  offsetLabel.textContent = sign + offset.toFixed(1) + 's';
  offsetLabel.style.color = offset === 0 ? 'var(--green)' : '#ff9f43';
  chrome.storage.local.set({ gasaji_offset: offset });
  chrome.tabs.query({active:true, currentWindow:true}, tabs => {
    if (!tabs[0]) return;
    chrome.tabs.sendMessage(tabs[0].id, { type:'set_offset', offset });
  });
}
offsetSlider.addEventListener('input', () => sendOffset(offsetSlider.value));

document.getElementById('offset-reset').addEventListener('click', () => {
  offsetSlider.value = 0;
  sendOffset(0);
});

fontKo.addEventListener('change', () => { preKo.style.fontFamily = fontKo.value; resetBtn(); });
fontEn.addEventListener('change', () => { preEn.style.fontFamily = fontEn.value; resetBtn(); });
slider.addEventListener('input', () => {
  sizeLabel.textContent = slider.value + 'px';
  updatePreviewSize(slider.value);
  resetBtn();
});
prevSlider.addEventListener('input', () => {
  prevLabel.value = prevSlider.value;
  resetBtn();
});
prevLabel.addEventListener('input', () => {
  let v = parseInt(prevLabel.value);
  if (isNaN(v) || v < 1) v = 1;
  if (v > 10) v = 10;
  prevLabel.value = v;
  prevSlider.value = v;
  resetBtn();
});

function updatePreviewSize(px) {
  preKo.style.fontSize = Math.round(px * 0.6) + 'px';
  preEn.style.fontSize = px + 'px';
}

const stepSlider = document.getElementById('step-slider');
const stepLabel  = document.getElementById('step-label');
stepSlider.addEventListener('input', () => {
  stepLabel.textContent = stepSlider.value + 'px';
});

function moveWidget(dir) {
  const step = parseInt(stepSlider.value);
  chrome.tabs.query({active:true, currentWindow:true}, tabs => {
    if (!tabs[0]) return;
    chrome.tabs.sendMessage(tabs[0].id, { type:'move_widget', dir, step });
  });
}

document.getElementById('btn-up').addEventListener('click',    () => moveWidget('up'));
document.getElementById('btn-down').addEventListener('click',  () => moveWidget('down'));
document.getElementById('btn-left').addEventListener('click',  () => moveWidget('left'));
document.getElementById('btn-right').addEventListener('click', () => moveWidget('right'));

function resetBtn() {
  applyBtn.textContent = '✓ 적용';
  applyBtn.className = 'apply-btn';
}

applyBtn.addEventListener('click', () => {
  const ko = fontKo.value, en = fontEn.value;
  const size = parseInt(slider.value);
  const prev_count = parseInt(prevLabel.value);
  chrome.storage.local.set({ gasaji_font_ko: ko, gasaji_font_en: en, gasaji_size: size, gasaji_prev_count: prev_count });
  chrome.tabs.query({active:true, currentWindow:true}, tabs => {
    if (!tabs[0]) return;
    chrome.tabs.sendMessage(tabs[0].id, { type:'set_font', font_ko: ko, font_en: en, size, prev_count });
  });
  applyBtn.textContent = '✅ 적용됨';
  applyBtn.className = 'apply-btn applied';
});

function update() {
  chrome.tabs.query({active:true, currentWindow:true}, tabs => {
    if (!tabs[0]) return;
    chrome.tabs.sendMessage(tabs[0].id, {type:'get_status'}, res => {
      if (chrome.runtime.lastError || !res) return;
      const connected = res.connected;

      // 연결 상태
      const dot = document.getElementById('dot-ws');
      const liveBadge = document.getElementById('live-badge');
      const valWs = document.getElementById('val-ws');
      if (dot) dot.className = 'conn-dot' + (connected ? ' on' : '');
      if (liveBadge) liveBadge.className = 'live-pill' + (connected ? ' show' : '');
      if (valWs) {
        valWs.innerHTML = `<span class="conn-dot ${connected ? 'on' : ''}"></span>${connected ? '연결됨' : '끊김'}`;
        valWs.className = 'stat-value' + (connected ? ' ok' : ' err');
      }

      // 가사 줄 수
      const valLyrics = document.getElementById('val-lyrics');
      if (valLyrics) {
        valLyrics.textContent = res.lyrics ? res.lyrics + '줄' : '—';
        valLyrics.className = 'stat-value' + (res.lyrics ? ' ok' : '');
      }

      // 재생 위치
      const valPos = document.getElementById('val-pos');
      if (valPos) valPos.textContent = res.pos ? res.pos.toFixed(1) + 's' : '—';

      // webPlayer
      const valWp = document.getElementById('val-wp');
      if (valWp) {
        valWp.textContent = res.wp_available ? '✅' : '❌';
        valWp.className = 'stat-value' + (res.wp_available ? ' ok' : ' err');
      }
    });
  });
}

update();
setInterval(update, 1000);

// 슬라이더 track fill 업데이트 (CSP 대응 - inline script 대신 여기서)
function updateTrack(input) {
  const min = +input.min, max = +input.max, val = +input.value;
  const pct = ((val - min) / (max - min) * 100).toFixed(1) + '%';
  input.style.setProperty('--pct', pct);
}
document.querySelectorAll('input[type=range]').forEach(r => {
  updateTrack(r);
  r.addEventListener('input', () => updateTrack(r));
});
