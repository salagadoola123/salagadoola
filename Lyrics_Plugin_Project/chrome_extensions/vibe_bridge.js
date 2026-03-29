// vibe_bridge.js - MAIN world
// currentAudio.currentTime + pluginPlayInfo.trackId 를 DOM에 기록
(function() {
  if (window.__vibeBridgeRunning) return;
  window.__vibeBridgeRunning = true;

  function sync() {
    try {
      const audio = window.webPlayer?.playerCore?.currentAudio;
      if (!audio) return;

      // 재생 위치
      const t = audio.currentTime;
      if (typeof t === 'number' && t >= 0) {
        document.body.setAttribute('data-vibe-time', t);
      }

      // trackId (pluginPlayInfo에서)
      const trackId = audio.pluginPlayInfo?.trackId;
      if (trackId) {
        document.body.setAttribute('data-vibe-trackid', trackId);
      }
    } catch(e) {}
  }

  function rafLoop() { sync(); requestAnimationFrame(rafLoop); }
  requestAnimationFrame(rafLoop);
  setInterval(sync, 100);
})();