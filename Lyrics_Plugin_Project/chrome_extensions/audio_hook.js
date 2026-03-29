/**
 * audio_hook.js - document_start에 실행
 * VIBE의 AudioContext를 후킹해서 currentTime 노출
 */
(function() {
  const OrigAudioContext = window.AudioContext || window.webkitAudioContext;
  if (!OrigAudioContext) return;

  const hookedContexts = [];
  window.__vibeAudioContexts = hookedContexts;

  function HookedAudioContext(...args) {
    const ctx = new OrigAudioContext(...args);
    hookedContexts.push(ctx);
    console.log('[가사지] 🎵 AudioContext 후킹됨! sampleRate=' + ctx.sampleRate);
    return ctx;
  }
  HookedAudioContext.prototype = OrigAudioContext.prototype;
  Object.setPrototypeOf(HookedAudioContext, OrigAudioContext);

  window.AudioContext = HookedAudioContext;
  window.webkitAudioContext = HookedAudioContext;

  // currentTime 읽기 헬퍼
  window.__getVibeAudioTime = function() {
    for (const ctx of hookedContexts) {
      if (ctx.state === 'running') return ctx.currentTime;
    }
    return -1;
  };
})();