/* ===== AI 尋問ゲーム フロントエンド ===== */

const API_BASE = 'http://127.0.0.1:8765';

// ===== DOM参照 =====
const scenarioScreen = document.getElementById('scenarioScreen');
const gameScreen = document.getElementById('gameScreen');
const scenarioList = document.getElementById('scenarioList');
const modelList = document.getElementById('modelList');
const loadingMsg = document.getElementById('loadingMsg');
const scenarioTitle = document.getElementById('scenarioTitle');
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
const accuseBtn = document.getElementById('accuseBtn');
const restartBtn = document.getElementById('restartBtn');
const accuseModal = document.getElementById('accuseModal');
const accuseList = document.getElementById('accuseList');
const cancelAccuseBtn = document.getElementById('cancelAccuseBtn');
const resultModal = document.getElementById('resultModal');
const resultIcon = document.getElementById('resultIcon');
const resultTitle = document.getElementById('resultTitle');
const resultMessage = document.getElementById('resultMessage');
const playAgainBtn = document.getElementById('playAgainBtn');

// ===== 状態 =====
let gameState = null;         // サーバーから取得したゲーム状態
let currentSuspectId = null;  // 現在選択中の容疑者ID
let isStreaming = false;       // SSEストリーミング中フラグ
let imageCache = {};           // suspectId -> objectURL | 'error'

// ===== 初期化 =====
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
    loadingMsg.textContent = 'シナリオの読み込みに失敗しました。';
    console.error(err);
  }
}

// ===== タブ =====
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById(`tab${btn.dataset.tab.charAt(0).toUpperCase() + btn.dataset.tab.slice(1)}`).classList.remove('hidden');
  });
});

// ===== モデル一覧 =====
let activeModelKey = '';

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

    let badgeClass, badgeText;
    if (m.active) {
      badgeClass = 'active'; badgeText = '使用中';
    } else if (m.downloaded) {
      badgeClass = 'available'; badgeText = '切り替え';
    } else {
      badgeClass = 'unavailable'; badgeText = '未ダウンロード';
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

// ===== ゲーム開始 =====
async function startGame(scenarioId) {
  loadingMsg.classList.remove('hidden');
  loadingMsg.textContent = 'ゲームを準備中...';

  try {
    const res = await fetch(`${API_BASE}/api/game/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario_id: scenarioId }),
    });
    const data = await res.json();
    gameState = data.state;
    loadingMsg.classList.add('hidden');
    showGameScreen();
  } catch (err) {
    loadingMsg.textContent = 'ゲームの開始に失敗しました。';
    console.error(err);
  }
}

function showGameScreen() {
  scenarioScreen.classList.add('hidden');
  gameScreen.classList.remove('hidden');
  resultModal.classList.add('hidden');
  accuseModal.classList.add('hidden');

  scenarioTitle.textContent = gameState.scenario_title;

  // 容疑者リスト描画
  suspectList.innerHTML = '';
  for (const s of gameState.suspects) {
    const item = document.createElement('div');
    item.className = 'suspect-item';
    item.dataset.id = s.id;
    item.innerHTML = `
      <div class="s-name">${escHtml(s.name)}</div>
      <div class="s-occ">${escHtml(s.occupation)}</div>
      <div class="s-badge">未尋問</div>
    `;
    item.addEventListener('click', () => selectSuspect(s.id));
    suspectList.appendChild(item);
  }

  // 状態リセット
  currentSuspectId = null;
  chatLog.innerHTML = '';
  currentSuspectName.textContent = '容疑者を選択してください';
  currentSuspectOccupation.textContent = '';
  suspectProfile.classList.add('hidden');
  messageInput.disabled = true;
  sendBtn.disabled = true;
  messageInput.value = '';
  imageCache = {};
}

// ===== キャラクター画像 =====
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

  // ローディング表示
  suspectImage.classList.add('hidden');
  suspectImagePlaceholder.querySelector('span').textContent = '画像生成中...';
  suspectImagePlaceholder.classList.remove('hidden');

  try {
    const res = await fetch(`${API_BASE}/api/game/character_image/${suspectId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    imageCache[suspectId] = url;
    // 現在も同じ容疑者が選択されているか確認してから表示
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

// ===== 容疑者選択 =====
function selectSuspect(suspectId) {
  if (isStreaming) return;

  currentSuspectId = suspectId;
  const suspect = gameState.suspects.find(s => s.id === suspectId);

  // サイドバーのアクティブ状態更新
  document.querySelectorAll('.suspect-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === suspectId);
  });

  // ヘッダー更新
  currentSuspectName.textContent = suspect.name;
  currentSuspectOccupation.textContent = `${suspect.age}歳・${suspect.occupation}`;
  profileBackground.textContent = suspect.background;
  profileAlibi.textContent = suspect.alibi;
  suspectProfile.classList.remove('hidden');

  // キャラクター画像を非同期で取得
  loadSuspectImage(suspectId);

  // チャットログをこの容疑者の履歴に切り替え
  renderChatLog(suspectId);

  messageInput.disabled = false;
  sendBtn.disabled = false;
  messageInput.focus();
}

// ===== チャットログ描画 =====
const chatHistories = {};  // suspectId -> [{role, content}]

function renderChatLog(suspectId) {
  chatLog.innerHTML = '';
  const history = chatHistories[suspectId] || [];
  for (const msg of history) {
    appendMessage(msg.role, msg.content, false);
  }
  scrollToBottom();
}

function appendMessage(role, content, streaming = false) {
  const isUser = role === 'user';
  const suspect = currentSuspectId ? gameState.suspects.find(s => s.id === currentSuspectId) : null;

  const msgEl = document.createElement('div');
  msgEl.className = `msg ${isUser ? 'user' : 'suspect'}`;

  const label = isUser ? '刑事（あなた）' : (suspect ? suspect.name : '容疑者');
  const bubble = document.createElement('div');
  bubble.className = `msg-bubble${streaming ? ' streaming' : ''}`;
  bubble.textContent = content;

  const labelEl = document.createElement('div');
  labelEl.className = 'msg-label';
  labelEl.textContent = label;

  msgEl.appendChild(labelEl);
  msgEl.appendChild(bubble);
  chatLog.appendChild(msgEl);
  scrollToBottom();
  return bubble;
}

function scrollToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

// ===== メッセージ送信 =====
async function sendMessage() {
  if (!currentSuspectId || isStreaming) return;
  const text = messageInput.value.trim();
  if (!text) return;

  messageInput.value = '';
  messageInput.disabled = true;
  sendBtn.disabled = true;
  isStreaming = true;

  // ユーザーメッセージ追加
  if (!chatHistories[currentSuspectId]) chatHistories[currentSuspectId] = [];
  chatHistories[currentSuspectId].push({ role: 'user', content: text });
  appendMessage('user', text, false);

  // ストリーミング返答バブル
  const bubble = appendMessage('suspect', '', true);
  let answerText = '';

  try {
    const res = await fetch(`${API_BASE}/api/game/interrogate/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suspect_id: currentSuspectId, message: text }),
    });

    if (!res.ok) {
      const err = await res.json();
      bubble.textContent = `[エラー: ${err.detail || '不明なエラー'}]`;
      bubble.classList.remove('streaming');
    } else {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop();  // 未完成の行をバッファに残す

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const json = line.slice(6);
          let event;
          try { event = JSON.parse(json); } catch (_) { continue; }

          if (event.event === 'answer') {
            answerText += event.text;
            bubble.textContent = answerText;
            scrollToBottom();
          } else if (event.event === 'done') {
            bubble.classList.remove('streaming');
            chatHistories[currentSuspectId].push({ role: 'assistant', content: answerText });
            // サイドバーのバッジ更新
            updateSuspectBadge(currentSuspectId);
          } else if (event.event === 'error') {
            bubble.textContent = `[エラー: ${event.text}]`;
            bubble.classList.remove('streaming');
          }
        }
      }
    }
  } catch (err) {
    bubble.textContent = '[接続エラーが発生しました]';
    bubble.classList.remove('streaming');
    console.error(err);
  } finally {
    isStreaming = false;
    if (currentSuspectId) {
      messageInput.disabled = false;
      sendBtn.disabled = false;
      messageInput.focus();
    }
  }
}

function updateSuspectBadge(suspectId) {
  const item = document.querySelector(`.suspect-item[data-id="${suspectId}"]`);
  if (item) {
    item.classList.add('has-chat');
    item.querySelector('.s-badge').textContent = '尋問済み';
  }
}

// ===== 指名モーダル =====
function openAccuseModal() {
  accuseList.innerHTML = '';
  for (const s of gameState.suspects) {
    const btn = document.createElement('button');
    btn.className = 'accuse-option';
    btn.innerHTML = `<div class="opt-name">${escHtml(s.name)}</div><div class="opt-occ">${escHtml(s.occupation)}</div>`;
    btn.addEventListener('click', () => accuseSuspect(s.id));
    accuseList.appendChild(btn);
  }
  accuseModal.classList.remove('hidden');
}

async function accuseSuspect(suspectId) {
  accuseModal.classList.add('hidden');
  try {
    const res = await fetch(`${API_BASE}/api/game/accuse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suspect_id: suspectId }),
    });
    const result = await res.json();
    showResult(result);
  } catch (err) {
    console.error(err);
  }
}

function showResult(result) {
  if (result.player_won) {
    resultIcon.textContent = '🎉';
    resultTitle.textContent = '捜査成功！';
    resultMessage.textContent = `正解です！\n「${result.boss_name}」がグループのボスでした。\nあなたの鋭い尋問で真相を暴きました。`;
    resultTitle.style.color = '#27ae60';
  } else {
    resultIcon.textContent = '❌';
    resultTitle.textContent = '捜査失敗';
    resultMessage.textContent = `残念…「${result.accused_name}」はボスではありませんでした。\n本当のボスは「${result.boss_name}」でした。\nもう一度挑戦してみましょう。`;
    resultTitle.style.color = '#c0392b';
  }
  resultModal.classList.remove('hidden');
}

// ===== やり直し =====
function restart() {
  gameScreen.classList.add('hidden');
  scenarioScreen.classList.remove('hidden');
  Object.keys(chatHistories).forEach(k => delete chatHistories[k]);
  gameState = null;
  currentSuspectId = null;
  isStreaming = false;
}

// ===== ユーティリティ =====
function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ===== イベントリスナー =====
sendBtn.addEventListener('click', sendMessage);

messageInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

accuseBtn.addEventListener('click', openAccuseModal);
cancelAccuseBtn.addEventListener('click', () => accuseModal.classList.add('hidden'));
restartBtn.addEventListener('click', restart);
playAgainBtn.addEventListener('click', () => {
  resultModal.classList.add('hidden');
  restart();
});

// ===== 起動 =====
init();
