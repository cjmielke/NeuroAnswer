const API_BASE = 'http://127.0.0.1:8080';

const chatHistory = document.getElementById('chat-history');
const chatInput   = document.getElementById('chat-input');
const sendBtn     = document.getElementById('send-btn');


// --- CHAT ---

function appendMessage(sender, text, isTemp = false) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `msg ${sender === 'You' ? 'msg-user' : 'msg-bot'}`;
  msgDiv.innerHTML = `<strong>${sender}:</strong> ${marked.parse(text)}`;
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

const appendImg = (src) => {
  const img = document.createElement('img');
  img.src = src;
  img.style.cssText = 'max-width:100%; margin-top:8px; border-radius:4px;';
  chatHistory.appendChild(img);
  chatHistory.scrollTop = chatHistory.scrollHeight;
};

const processChunk = (data) => {
  if (data.type === 'status') {
    const tempMsg = document.getElementById('temp-msg');
    if (tempMsg) {
      tempMsg.innerHTML = `<strong>AI:</strong> <em>${data.message}</em>`;
      chatHistory.scrollTop = chatHistory.scrollHeight;
    }
  } else if (data.type === 'text') {
    appendMessage('AI', data.content);
  } else if (data.type === 'image') {
    appendImg(data.content);
  } else if (data.type === 'final') {
    document.getElementById('temp-msg')?.remove();
    for (const block of (data.blocks || [])) {
      if (block.type === 'text') appendMessage('AI', block.content);
      else if (block.type === 'image') appendImg(block.content);
    }
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }
};

async function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  appendMessage('You', text);
  appendMessage('AI', 'Processing…', true);

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: text })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let gotFinal = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const chunk = JSON.parse(line);
          if (chunk.type === 'final') gotFinal = true;
          processChunk(chunk);
        } catch (e) {
          console.error('[chat] parse error:', e, line);
        }
      }
    }
    if (buffer.trim()) {
      try {
        const chunk = JSON.parse(buffer);
        if (chunk.type === 'final') gotFinal = true;
        processChunk(chunk);
      } catch (e) {}
    }

    if (!gotFinal) {
      document.getElementById('temp-msg')?.remove();
      appendMessage('AI', '⚠️ No response received. Check the server logs.');
    }
  } catch (error) {
    document.getElementById('temp-msg')?.remove();
    appendMessage('AI', `Network Error: Could not reach backend on port 8080. Is it running?`);
    console.error(error);
  }
}

sendBtn.addEventListener('click', handleSend);
chatInput.addEventListener('keypress', e => { if (e.key === 'Enter') handleSend(); });