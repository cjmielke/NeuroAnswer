const API_BASE = 'http://127.0.0.1:8080';
const NEUROGLANCER_PORT = 8675;
const NEUROGLANCER_TOKEN = 'neuroanswer';
const NEUROGLANCER_URL = `http://127.0.0.1:${NEUROGLANCER_PORT}/v/${NEUROGLANCER_TOKEN}/`;

const chatHistory = document.getElementById('chat-history');
const chatInput   = document.getElementById('chat-input');
const sendBtn     = document.getElementById('send-btn');

document.getElementById('ng-btn').href = NEUROGLANCER_URL;

document.getElementById('reset-btn').addEventListener('click', async () => {
  await fetch(`${API_BASE}/reset`, { method: 'POST' }).catch(() => {});
  chatHistory.innerHTML = '';
  appendMessage('System', 'Conversation reset.');
});


// --- CHAT ---

function appendMessage(sender, text, isTemp = false) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `msg ${sender === 'You' ? 'msg-user' : 'msg-bot'}`;
  msgDiv.innerHTML = `<strong>${sender}:</strong> ${marked.parse(text)}`;
  if (isTemp) msgDiv.id = 'temp-msg';
  chatHistory.appendChild(msgDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

const appendDetail = (toolName, content) => {
  const details = document.createElement('details');
  details.className = 'tool-detail';
  const summary = document.createElement('summary');
  summary.textContent = `${toolName} result`;
  const pre = document.createElement('pre');
  const codeEl = document.createElement('code');
  codeEl.className = 'language-json';
  codeEl.textContent = JSON.stringify(content, null, 2);
  pre.appendChild(codeEl);
  details.appendChild(summary);
  details.appendChild(pre);
  chatHistory.appendChild(details);
  Prism.highlightElement(codeEl);
  chatHistory.scrollTop = chatHistory.scrollHeight;
};

const appendCode = (code) => {
  const pre = document.createElement('pre');
  const codeEl = document.createElement('code');
  codeEl.className = 'language-python';
  codeEl.textContent = code;
  pre.appendChild(codeEl);
  chatHistory.appendChild(pre);
  Prism.highlightElement(codeEl);
  chatHistory.scrollTop = chatHistory.scrollHeight;
};

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
  } else if (data.type === 'detail') {
    appendDetail(data.tool, data.content);
  } else if (data.type === 'code') {
    appendCode(data.content);
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