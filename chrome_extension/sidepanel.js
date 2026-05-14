const API_BASE = 'http://127.0.0.1:8080';

// Keep in sync with KNOWN_DATASETS keys in api_server.py
const KNOWN_DATASET_KEYS = ['minnie65'];

// DOM refs used throughout — declared early so init functions can use them
const chatHistory = document.getElementById('chat-history');
const chatInput   = document.getElementById('chat-input');
const sendBtn     = document.getElementById('send-btn');

// --- NEUROGLANCER TAB BINDING ---
// The content script running inside each Neuroglancer tab pushes state here.
// We track the most recently active tab by ID so all reads and writes are unambiguous.

let boundTabId   = null;
let boundState   = null;

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.type !== 'ng_state') return;
  const wasUnbound = boundTabId === null;
  boundTabId = sender.tab.id;
  boundState = msg.state;
  // Re-run init if this is the first tab we've heard from
  if (wasUnbound) onPanelInit();
});

function checkNeuroglancer() {
  const hasNg = boundState !== null;
  document.getElementById('error-state').style.display = hasNg ? 'none' : 'flex';
  document.getElementById('app-state').style.display   = hasNg ? 'flex' : 'none';
}

function getNeuroglancerState() {
  return boundState;
}

function getPositionFromState(ngState) {
  if (!ngState) return null;
  if (ngState.position) return ngState.position;
  if (ngState.navigation?.pose?.position?.voxelCoordinates)
    return ngState.navigation.pose.position.voxelCoordinates;
  return null;
}

function updateNeuroglancerTab(newUrl) {
  if (boundTabId !== null) chrome.tabs.update(boundTabId, { url: newUrl });
}

function applyLayersToTab(newLayers) {
  if (!boundState || !newLayers.length) return;
  const merged = [...(boundState.layers || [])];
  for (const newLayer of newLayers) {
    const i = merged.findIndex(l => l.name === newLayer.name);
    i >= 0 ? (merged[i] = newLayer) : merged.push(newLayer);
  }
  const updatedState = { ...boundState, layers: merged };
  const baseUrl = `https://neuroglancer-demo.appspot.com/#!`;
  updateNeuroglancerTab(baseUrl + encodeURIComponent(JSON.stringify(updatedState)));
}

function moveToPosition(position) {
  if (!boundState) return;
  const updatedState = { ...boundState, position };
  const baseUrl = `https://neuroglancer-demo.appspot.com/#!`;
  updateNeuroglancerTab(baseUrl + encodeURIComponent(JSON.stringify(updatedState)));
}


// --- INIT ---

function detectDatasetKey(ngState) {
  if (!ngState) return null;
  for (const layer of (ngState.layers || [])) {
    const src = JSON.stringify(layer.source ?? '');
    for (const key of KNOWN_DATASET_KEYS) {
      if (src.includes(key)) return key;
    }
  }
  return null;
}

async function fetchScenes() {
  const res = await fetch(`${API_BASE}/scenes`);
  return (await res.json()).scenes;
}

async function showDatasetMenu() {
  try {
    const scenes = await fetchScenes();
    appendMessage('System', 'No supported dataset loaded. Open one to get started:');
    scenes.forEach(scene => {
      const btn = appendButton(`Open ${scene.label}`, null, scene.description);
      btn.onclick = async () => {
        btn.disabled = true;
        btn.innerText = 'Loading…';
        try {
          const sceneRes = await fetch(`${API_BASE}/new_scene/${scene.id}`);
          const sceneData = await sceneRes.json();
          if (sceneData.scene_url) {
            await updateNeuroglancerTab(sceneData.scene_url);
            setTimeout(onPanelInit, 2000);
          }
        } catch (e) {
          btn.innerText = `Open ${scene.label}`;
          btn.disabled = false;
        }
      };
    });
  } catch (e) {
    appendMessage('System', 'No supported dataset loaded. (Backend appears offline — is the server running?)');
  }
}

// Populate the error-state scene menu (no bound Neuroglancer tab yet — open a new one)
async function loadErrorStateMenu() {
  const menu = document.getElementById('scene-menu');
  if (!menu || menu.childElementCount > 0) return; // don't double-populate
  try {
    const scenes = await fetchScenes();
    scenes.forEach(scene => {
      const btn = document.createElement('button');
      btn.innerText = `Open ${scene.label}`;
      btn.title = scene.description;
      btn.style.cssText = 'display:block; width:100%; margin-top:6px;';
      btn.onclick = async () => {
        btn.disabled = true;
        btn.innerText = 'Loading…';
        try {
          const sceneRes = await fetch(`${API_BASE}/new_scene/${scene.id}`);
          const sceneData = await sceneRes.json();
          if (sceneData.scene_url) {
            // No bound tab yet — open a new one; content script will bind automatically
            chrome.tabs.create({ url: sceneData.scene_url });
          }
        } catch (e) {
          btn.innerText = `Open ${scene.label}`;
          btn.disabled = false;
        }
      };
      menu.appendChild(btn);
    });
  } catch (e) {
    const err = document.createElement('p');
    err.style.cssText = 'color:#f44336; font-size:0.85em; margin-top:6px;';
    err.innerText = 'Backend offline — is the server running on port 8080?';
    menu.appendChild(err);
  }
}

function onPanelInit() {
  chatHistory.innerHTML = '';
  checkNeuroglancer();

  const ngState = getNeuroglancerState();
  if (!ngState) {
    loadErrorStateMenu();
    return;
  }

  const datasetKey = detectDatasetKey(ngState);
  if (datasetKey) {
    appendMessage('System', 'Ready.');
  } else {
    showDatasetMenu();
  }
}

// Show error state on load; content script message will trigger onPanelInit() when a tab binds
onPanelInit();
document.getElementById('refresh-btn')?.addEventListener('click', () => {
  boundTabId = null;
  boundState = null;
  document.getElementById('scene-menu').innerHTML = '';
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    if (tab) chrome.tabs.sendMessage(tab.id, { type: 'request_state' }, () => void chrome.runtime.lastError);
  });
  onPanelInit();
});


// --- CHAT ---

function appendMessage(sender, text, coords = null, isTemp = false) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `msg ${sender === 'You' ? 'msg-user' : 'msg-bot'}`;
  let html = `<strong>${sender}:</strong> ${marked.parse(text)}`;
  if (coords) {
    html += `<br><span class="coord-badge">Position: [${coords.map(c => Math.round(c)).join(', ')}]</span>`;
  }
  msgDiv.innerHTML = html;
  if (isTemp) msgDiv.id = 'temp-msg';
  chatHistory.appendChild(msgDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendButton(label, onClick, title = '') {
  const btn = document.createElement('button');
  btn.innerText = label;
  btn.className = 'goto_scene_btn';
  if (title) btn.title = title;
  if (onClick) btn.onclick = onClick;
  chatHistory.appendChild(btn);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return btn;
}


async function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  const ngState = getNeuroglancerState();
  const coords  = getPositionFromState(ngState);
  appendMessage('You', text, coords);
  appendMessage('Copilot', 'Processing…', null, true);

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: text, ng_state: ngState })
    });

    const data = await response.json();
    document.getElementById('temp-msg').remove();

    for (const block of (data.blocks || [{type: 'text', content: 'Done.'}])) {
      if (block.type === 'text') {
        appendMessage('Copilot', block.content);
      } else if (block.type === 'image') {
        const img = document.createElement('img');
        img.src = block.content;
        img.style.cssText = 'max-width:100%; margin-top:8px; border-radius:4px;';
        chatHistory.appendChild(img);
        chatHistory.scrollTop = chatHistory.scrollHeight;
      }
    }

    // Auto-apply layers (upsert into current scene)
    if (data.layers && data.layers.length > 0) {
      applyLayersToTab(data.layers);
    }

    // Camera suggestion — explicit opt-in button
    if (data.suggested_position) {
      const pos = data.suggested_position;
      appendButton(
        `Go to results`,
        () => moveToPosition(pos),
        `Move camera to [${pos.map(c => Math.round(c)).join(', ')}]`
      );
    }

    // Whole-scene replacement (future use / direct tool output)
    if (data.new_scene) {
      appendButton(`Open Scene`, () => updateNeuroglancerTab(data.new_scene));
    }

  } catch (error) {
    document.getElementById('temp-msg')?.remove();
    appendMessage('Copilot', `Network Error: Could not reach backend on port 8080. Is it running?`);
    console.error(error);
  }
}

sendBtn.addEventListener('click', handleSend);
chatInput.addEventListener('keypress', e => { if (e.key === 'Enter') handleSend(); });
