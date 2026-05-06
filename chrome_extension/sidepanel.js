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

    if (ngState.position) {           // Modern neuroglancer schema
      return ngState.position;
    } else if (ngState.navigation && ngState.navigation.pose && ngState.navigation.pose.position) {
      return ngState.navigation.pose.position.voxelCoordinates;         // Legacy schema fallback
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


async function updateNeuroglancerTab(newUrl) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) { // updates #! hash in url - tab doesn't reload, just changes scene
    chrome.tabs.update(tab.id, { url: newUrl });
  }
}

async function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  const coords = await getCurrentCoordinates();
  appendMessage('You', text, coords);
  appendMessage('Copilot', 'Processing...', null, true); // Loading state

  try {
    const response = await fetch('http://127.0.0.1:8080/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: text, bbox: coords })
    });

    const data = await response.json();

    // Remove loading state and show result
    document.getElementById('temp-msg').remove();

    // 2. Append Claude's text reply
    appendMessage('Copilot', data.reply || "Done.");

    // 3. Inject Action Buttons for the Scenes
    if (data.scene_urls && data.scene_urls.length > 0) {
      const chatHistory = document.getElementById('chat-history');

      data.scene_urls.forEach((url, index) => {
        const btn = document.createElement('button');
        btn.innerText = `🎯 Apply Scene ${index + 1}`;
        btn.className = 'goto_scene_btn'
        //btn.style.marginTop = '8px';
        //btn.style.display = 'block';
        //btn.style.width = '100%';
        //btn.style.backgroundColor = '#4caf50'; // Make it pop a bit

        // Bind the click to our tab-updater function
        btn.onclick = () => updateNeuroglancerTab(url);

        chatHistory.appendChild(btn);
      });
      chatHistory.scrollTop = chatHistory.scrollHeight;
    }

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