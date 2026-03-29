// background.js - service worker
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'loading' && tab.url?.includes('vibe.naver.com')) {
    chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: () => {
        if (window.__vibeAudioHookInstalled) return;
        window.__vibeAudioHookInstalled = true;
        console.log('[가사지] background hook 실행됨');
      }
    }).catch(() => {});
  }
});
