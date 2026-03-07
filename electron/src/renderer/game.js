/* ===== AI 政治討論シミュレーター フロントエンド ===== */

const API_BASE = 'http://127.0.0.1:8765';

const scenarioScreen = document.getElementById('scenarioScreen');
const gameScreen = document.getElementById('gameScreen');
const scenarioList = document.getElementById('scenarioList');
const modelList = document.getElementById('modelList');
const loadingMsg = document.getElementById('loadingMsg');
const scenarioTitle = document.getElementById('scenarioTitle');
const contextUsage = document.getElementById('contextUsage');
const speakerHeader = document.getElementById('speakerHeader');
const closeSpeakerHeaderBtn = document.getElementById('closeSpeakerHeaderBtn');
const suspectList = document.getElementById('suspectList');
const currentSuspectName = document.getElementById('currentSuspectName');
const currentSuspectOccupation = document.getElementById('currentSuspectOccupation');
const suspectProfile = document.getElementById('suspectProfile');
const profileBackground = document.getElementById('profileBackground');
const profileAlibi = document.getElementById('profileAlibi');
const suspectImage = document.getElementById('suspectImage');
const suspectImagePlaceholder = document.getElementById('suspectImagePlaceholder');
const chatLog = document.getElementById('chatLog');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const restartBtn = document.getElementById('restartBtn');

let gameState = null;
let currentSuspectId = null;
let isStreaming = false;
let imageCache = {};
let activeModelKey = '';
let debateHistory = [];

async function init() {
  loadingMsg.textContent = 'サーバーに接続中...';
  await waitForServer();
  await Promise.all([loadScenarios(), loadModels()]);
}

async function waitForServer(timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) return;
    } catch (_) {}
    await sleep(500);
  }
  loadingMsg.textContent = 'サーバーへの接続に失敗しました。アプリを再起動してください。';
}

async function loadScenarios() {
  try {
    const res = await fetch(`${API_BASE}/api/game/scenarios`);
    const data = await res.json();
    renderScenarioList(data.scenarios);
    loadingMsg.classList.add('hidden');
  } catch (err) {
    loadingMsg.textContent = 'テーマの読み込みに失敗しました。';
    console.error(err);
  }
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById(`tab${btn.dataset.tab.charAt(0).toUpperCase() + btn.dataset.tab.slice(1)}`).classList.remove('hidden');
  });
});

async function loadModels() {
  try {
    const res = await fetch(`${API_BASE}/api/models`);
    const data = await res.json();
    renderModelList(data.models);
  } catch (err) {
    console.error('モデル一覧の取得に失敗:', err);
  }
}

function renderModelList(models) {
  modelList.innerHTML = '';
  for (const m of models) {
    if (m.active) activeModelKey = m.key;
    const card = document.createElement('div');
    card.className = 'model-card' +
      (m.active ? ' is-active' : '') +
      (m.downloaded && !m.active ? ' is-switchable' : '');
    card.dataset.key = m.key;

    let badgeClass;
    let badgeText;
    if (m.active) {
      badgeClass = 'active';
      badgeText = '使用中';
    } else if (m.downloaded) {
      badgeClass = 'available';
      badgeText = '切り替え';
    } else {
      badgeClass = 'unavailable';
      badgeText = '未ダウンロード';
    }

    card.innerHTML = `
      <div class="model-info">
        <div class="model-name">${escHtml(m.key)}</div>
        <div class="model-desc">${escHtml(m.description || '')}</div>
        <div class="model-meta">${m.size_gb ? `${m.size_gb}GB` : ''} ${m.vram_gb ? `/ VRAM ~${m.vram_gb}GB` : ''}</div>
      </div>
      <div class="model-badge ${badgeClass}">${badgeText}</div>
    `;

    if (m.downloaded && !m.active) {
      card.addEventListener('click', () => switchModel(m.key, card));
    }
    modelList.appendChild(card);
  }
}

async function switchModel(modelKey, card) {
  const badge = card.querySelector('.model-badge');
  badge.textContent = '切り替え中...';
  badge.className = 'model-badge switching';
  card.classList.remove('is-switchable');
  card.style.cursor = 'default';

  try {
    const res = await fetch(`${API_BASE}/api/models/switch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_key: modelKey }),
    });
    const data = await res.json();
    if (data.ok) {
      await loadModels();
    } else {
      badge.textContent = 'エラー';
      badge.className = 'model-badge unavailable';
    }
  } catch (err) {
    badge.textContent = 'エラー';
    badge.className = 'model-badge unavailable';
    console.error(err);
  }
}

function renderScenarioList(scenarios) {
  scenarioList.innerHTML = '';
  for (const s of scenarios) {
    const card = document.createElement('div');
    card.className = 'scenario-card';
    card.innerHTML = `<h3>${escHtml(s.title)}</h3><p>${escHtml(s.description)}</p>`;
    card.addEventListener('click', () => startGame(s.id));
    scenarioList.appendChild(card);
  }
}

async function startGame(topicId) {
  loadingMsg.classList.remove('hidden');
  loadingMsg.textContent = '討論を準備中...';

  try {
    const res = await fetch(`${API_BASE}/api/game/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic_id: topicId }),
    });
    const data = await res.json();
    gameState = data.state;
    loadingMsg.classList.add('hidden');
    showGameScreen();
  } catch (err) {
    loadingMsg.textContent = '討論の開始に失敗しました。';
    console.error(err);
  }
}

function showGameScreen() {
  scenarioScreen.classList.add('hidden');
  gameScreen.classList.remove('hidden');

  scenarioTitle.textContent = gameState.topic_title;
  contextUsage.textContent = 'context: 待機中';
  suspectList.innerHTML = '';
  for (const s of gameState.speakers) {
    const item = document.createElement('div');
    item.className = 'suspect-item';
    item.dataset.id = s.id;
    item.innerHTML = `
      <div class="s-name">${escHtml(s.name)}</div>
      <div class="s-occ">${escHtml(s.party_name)} / ${escHtml(s.role_title)}</div>
      <div class="s-badge">待機中</div>
    `;
    item.addEventListener('click', () => selectSuspect(s.id));
    suspectList.appendChild(item);
  }

  currentSuspectId = null;
  debateHistory = [];
  chatLog.innerHTML = '';
  imageCache = {};
  speakerHeader.classList.add('hidden');
  currentSuspectName.textContent = '議員を選択してください';
  currentSuspectOccupation.textContent = '';
  suspectProfile.classList.add('hidden');
  messageInput.disabled = false;
  sendBtn.disabled = false;
  messageInput.value = '';
}

async function loadSuspectImage(suspectId) {
  if (imageCache[suspectId]) {
    if (imageCache[suspectId] === 'error') {
      suspectImage.classList.add('hidden');
      suspectImagePlaceholder.querySelector('span').textContent = '画像なし';
      suspectImagePlaceholder.classList.remove('hidden');
    } else {
      suspectImage.src = imageCache[suspectId];
      suspectImage.classList.remove('hidden');
      suspectImagePlaceholder.classList.add('hidden');
    }
    return;
  }

  suspectImage.classList.add('hidden');
  suspectImagePlaceholder.querySelector('span').textContent = '画像生成中...';
  suspectImagePlaceholder.classList.remove('hidden');

  try {
    const res = await fetch(`${API_BASE}/api/game/character_image/${suspectId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    imageCache[suspectId] = url;
    if (currentSuspectId === suspectId) {
      suspectImage.src = url;
      suspectImage.classList.remove('hidden');
      suspectImagePlaceholder.classList.add('hidden');
    }
  } catch (err) {
    imageCache[suspectId] = 'error';
    if (currentSuspectId === suspectId) {
      const spinner = suspectImagePlaceholder.querySelector('.image-loading-spinner');
      if (spinner) spinner.style.display = 'none';
      suspectImagePlaceholder.querySelector('span').textContent = '画像なし';
    }
    console.warn('キャラクター画像の取得に失敗:', err);
  }
}

function selectSuspect(suspectId) {
  if (!gameState) return;
  currentSuspectId = suspectId;
  const suspect = gameState.speakers.find(s => s.id === suspectId);
  if (!suspect) return;

  document.querySelectorAll('.suspect-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === suspectId);
  });

  currentSuspectName.textContent = suspect.name;
  currentSuspectOccupation.textContent = `${suspect.party_name} / ${suspect.role_title}`;
  profileBackground.textContent = suspect.public_profile;
  profileAlibi.textContent = suspect.party_position;
  speakerHeader.classList.remove('hidden');
  suspectProfile.classList.remove('hidden');
  loadSuspectImage(suspectId);
}

function closeSpeakerHeader() {
  currentSuspectId = null;
  speakerHeader.classList.add('hidden');
  suspectProfile.classList.add('hidden');
  currentSuspectName.textContent = '議員を選択してください';
  currentSuspectOccupation.textContent = '';
  document.querySelectorAll('.suspect-item').forEach(el => {
    el.classList.remove('active');
  });
}

async function hydrateMessageAvatar(avatarEl, speakerId) {
  if (!speakerId) return;
  await loadSuspectImage(speakerId);
  const cached = imageCache[speakerId];
  if (!cached || cached === 'error') return;

  avatarEl.innerHTML = '';
  const img = document.createElement('img');
  img.src = cached;
  img.alt = '';
  img.className = 'msg-avatar-image';
  avatarEl.appendChild(img);
}

function appendMessage(role, label, content, streaming = false, speakerId = null) {
  const msgEl = document.createElement('div');
  msgEl.className = `msg ${role === 'user' ? 'user' : 'suspect'}`;

  const body = document.createElement('div');
  body.className = 'msg-body';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = role === 'user' ? '司' : '議';

  const meta = document.createElement('div');
  meta.className = 'msg-meta';

  const bubble = document.createElement('div');
  bubble.className = `msg-bubble${streaming ? ' streaming' : ''}`;
  bubble.textContent = content;

  const labelEl = document.createElement('div');
  if (role === 'user') {
    labelEl.className = 'msg-label';
    labelEl.textContent = label;
  } else {
    const match = label.match(/^(.*)\s\((.*)\)$/);
    const name = match ? match[1] : label;
    const party = match ? match[2] : '';

    labelEl.className = 'msg-label msg-speaker-name';
    labelEl.textContent = name;

    if (party) {
      const partyEl = document.createElement('div');
      partyEl.className = 'msg-party';
      partyEl.textContent = party;
      meta.appendChild(labelEl);
      meta.appendChild(partyEl);
    } else {
      meta.appendChild(labelEl);
    }
  }

  if (role === 'user') {
    body.appendChild(avatar);
    body.appendChild(bubble);
    msgEl.appendChild(labelEl);
  } else {
    meta.appendChild(bubble);
    body.appendChild(avatar);
    body.appendChild(meta);
  }
  msgEl.appendChild(body);
  chatLog.appendChild(msgEl);
  scrollToBottom();
  if (role !== 'user' && speakerId) {
    hydrateMessageAvatar(avatar, speakerId);
  }
  return bubble;
}

function appendSystemNote(text) {
  const note = document.createElement('div');
  note.className = 'msg';
  note.innerHTML = `<div class="msg-label">進行</div><div class="msg-bubble">${escHtml(text)}</div>`;
  chatLog.appendChild(note);
  scrollToBottom();
}

function scrollToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function updateSpeakerBadge(speakerId, text) {
  const item = document.querySelector(`.suspect-item[data-id="${speakerId}"]`);
  if (item) item.querySelector('.s-badge').textContent = text;
}

function getSpeaker(speakerId) {
  return gameState?.speakers.find(s => s.id === speakerId) || null;
}

async function sendMessage() {
  if (isStreaming) return;
  const text = messageInput.value.trim();
  if (!text) return;

  messageInput.value = '';
  messageInput.disabled = true;
  sendBtn.disabled = true;
  isStreaming = true;

  debateHistory.push({ role: 'user', label: '司会者（あなた）', content: text });
  appendMessage('user', '司会者（あなた）', text, false);

  const bubbles = {};

  try {
    const res = await fetch(`${API_BASE}/api/game/interrogate/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });

    if (!res.ok) {
      const err = await res.json();
      appendSystemNote(`[エラー] ${err.detail || '不明なエラー'}`);
    } else {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const json = line.slice(6);
          let event;
          try { event = JSON.parse(json); } catch (_) { continue; }

          if (event.event === 'round_start') {
            scenarioTitle.textContent = gameState.topic_title;
            contextUsage.textContent = `context: ${event.context_usage || '計算失敗'}`;
            document.querySelectorAll('.suspect-item .s-badge').forEach(el => {
              el.textContent = '静観';
            });
            for (const candidate of event.order) {
              updateSpeakerBadge(candidate.speaker_id, '発言候補');
            }
          } else if (event.event === 'speaker_start') {
            const label = `${event.speaker_name} (${event.party_name})`;
            bubbles[event.speaker_id] = appendMessage('assistant', label, '', true, event.speaker_id);
            updateSpeakerBadge(event.speaker_id, '発言中');
          } else if (event.event === 'answer') {
            const bubble = bubbles[event.speaker_id];
            if (bubble) {
              bubble.textContent += event.text;
              scrollToBottom();
            }
          } else if (event.event === 'speaker_done') {
            const bubble = bubbles[event.speaker_id];
            const speaker = getSpeaker(event.speaker_id);
            if (bubble && speaker) {
              bubble.classList.remove('streaming');
              debateHistory.push({
                role: 'assistant',
                label: `${speaker.name} (${speaker.party_name})`,
                content: bubble.textContent,
              });
            }
            updateSpeakerBadge(event.speaker_id, '発言済み');
          } else if (event.event === 'error') {
            const bubble = bubbles[event.speaker_id];
            if (bubble) {
              bubble.textContent = `[エラー: ${event.text}]`;
              bubble.classList.remove('streaming');
            } else {
              appendSystemNote(`[エラー] ${event.text}`);
            }
          }
        }
      }
    }
  } catch (err) {
    appendSystemNote('[接続エラーが発生しました]');
    console.error(err);
  } finally {
    isStreaming = false;
    messageInput.disabled = false;
    sendBtn.disabled = false;
    messageInput.focus();
  }
}

function restart() {
  gameScreen.classList.add('hidden');
  scenarioScreen.classList.remove('hidden');
  gameState = null;
  currentSuspectId = null;
  isStreaming = false;
  debateHistory = [];
  contextUsage.textContent = 'context: -';
  speakerHeader.classList.add('hidden');
}

function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

sendBtn.addEventListener('click', sendMessage);

messageInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

restartBtn.addEventListener('click', restart);
closeSpeakerHeaderBtn.addEventListener('click', closeSpeakerHeader);

init();
