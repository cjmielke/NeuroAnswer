// --- STATE MANAGEMENT ---
async function checkNeuroglancer() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;

  const isNeuroglancer = tab.title.toLowerCase().includes('neuroglancer') || tab.url.includes('#!');

  if (isNeuroglancer) {
    document.getElementById('error-state').style.display = 'none';
    document.getElementById('app-state').style.display = 'flex'; // Use flex for the chat layout
  } else {
    document.getElementById('error-state').style.display = 'flex';
    document.getElementById('app-state').style.display = 'none';
  }
}

document.getElementById('refresh-btn')?.addEventListener('click', checkNeuroglancer);
checkNeuroglancer();

// --- COORDINATE EXTRACTION ---
async function getCurrentCoordinates() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url.includes('#!')) return null;

    const url = new URL(tab.url);

    // Fix 1: Use decodeURIComponent to catch the %2C commas
    const decodedHash = decodeURIComponent(url.hash.substring(2));
    const ngState = JSON.parse(decodedHash);
    console.log("ngState is :");
    console.log(ngState);

    // Fix 2: Handle both known Neuroglancer state schemas
    if (ngState.position) {
      // Modern schema (as seen in your log)
      return ngState.position;
    } else if (ngState.navigation && ngState.navigation.pose && ngState.navigation.pose.position) {
      // Legacy schema fallback
      return ngState.navigation.pose.position.voxelCoordinates;
    }
  } catch (e) {
    console.log("Coordinate extraction failed", e);
  }
  return null;
}

// --- CHAT LOGIC ---
const chatHistory = document.getElementById('chat-history');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

function appendMessage(sender, text, coords = null, isTemp = false) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `msg ${sender === 'You' ? 'msg-user' : 'msg-bot'}`;

  //let html = `<strong>${sender}:</strong> ${text}`;
  let html = `<strong>${sender}:</strong> ${marked.parse(text)}`;   // markdown support!
  if (coords) {
    html += `<br><span class="coord-badge">Target: [${coords.map(c => Math.round(c)).join(', ')}]</span>`;
  }

  msgDiv.innerHTML = html;
  if (isTemp) msgDiv.id = 'temp-msg';

  chatHistory.appendChild(msgDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight; // Auto-scroll
}

async function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;

  // 1. Clear input and update UI
  chatInput.value = '';
  const coords = await getCurrentCoordinates();
  appendMessage('You', text, coords);
  appendMessage('Copilot', 'Processing...', null, true); // Loading state

  // 2. Send to FastAPI Orchestrator
  try {
    const response = await fetch('http://127.0.0.1:8080/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: text, bbox: coords })
    });

    const data = await response.json();

    // Remove loading state and show result
    document.getElementById('temp-msg').remove();
    appendMessage('Copilot', data.reply || "Error: No reply found in response.");

  } catch (error) {
    document.getElementById('temp-msg').remove();
    appendMessage('Copilot', `Network Error: Could not reach FastAPI on port 8080. Is it running?`);
    console.error(error);
  }
}

// Bind enter key and click
sendBtn.addEventListener('click', handleSend);
chatInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') handleSend();
});