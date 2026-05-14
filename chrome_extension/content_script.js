let lastHash = null;

function pushState() {
  const hash = window.location.hash;
  if (hash === lastHash || !hash.startsWith('#!')) return;
  lastHash = hash;
  try {
    const state = JSON.parse(decodeURIComponent(hash.substring(2)));
    chrome.runtime.sendMessage({ type: 'ng_state', state });
  } catch (e) {}
}

// Neuroglancer updates the hash on every camera move but doesn't always
// fire a hashchange event, so we poll as well.
setInterval(pushState, 500);
window.addEventListener('hashchange', pushState);
pushState();

// Allow the panel to request a fresh push (e.g. after "Check Again" resets state)
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== 'request_state') return;
  const hash = window.location.hash;
  if (!hash.startsWith('#!')) return;
  try {
    const state = JSON.parse(decodeURIComponent(hash.substring(2)));
    chrome.runtime.sendMessage({ type: 'ng_state', state });
    lastHash = hash;
  } catch (e) {}
});

