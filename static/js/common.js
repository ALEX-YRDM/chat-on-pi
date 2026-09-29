/* No HTML interpolation: model and user text are always rendered with textContent. */
window.$ = (id) => document.getElementById(id);
window.notice = (text = '') => { $('notice').textContent = text; $('notice').hidden = !text; };
window.api = async (path, method = 'GET', body) => {
  const response = await fetch(path, {method, headers: body === undefined ? {} : {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(x => `${x.loc.join('.')}: ${x.msg}`).join('\n') : data.detail;
    const error = new Error(detail || `HTTP ${response.status}`); error.result = data.result; throw error;
  }
  return data;
};
window.audioElement = (url) => {const node = document.createElement('audio'); node.controls = true; node.preload = 'none'; node.src = url; return node;};
window.timingText = (t) => t ? `录音 ${t.recording_ms} ms · STT ${t.stt_ms} ms · LLM ${t.llm_ms} ms · TTS ${t.tts_ms} ms · 播放 ${t.playback_ms} ms · Total ${t.total_ms} ms` : '';
window.bindAction = (id, action) => $(id).addEventListener('click', async () => {
  const button = $(id); button.disabled = true; notice();
  try {await action();} catch (error) {notice(error.message);} finally {button.disabled = false;}
});
window.showStatus = (data) => {
  const labels = {idle:'Ready', recording:'Recording', transcribing:'Transcribing', thinking:'Thinking', synthesizing:'Synthesizing', playing:'Playing', error:'Error'};
  $('state').textContent = labels[data.state] || data.state;
  $('state').title = data.message || '';
  $('state-dot').className = `dot ${data.state === 'error' ? 'error' : data.state === 'idle' ? '' : 'busy'}`;
  window.dispatchEvent(new CustomEvent('pipeline-status', {detail:data}));
};
let socket;
async function pollStatus() {try {showStatus(await api('/api/status'));} catch (_) {$('connection').textContent = '连接中断';}}
function connectStatus() {
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/status`);
  socket.onopen = () => {$('connection').textContent = '实时';};
  socket.onmessage = (event) => {try {showStatus(JSON.parse(event.data));} catch (_) {}};
  socket.onclose = () => {$('connection').textContent = '重连中'; setTimeout(connectStatus, 2000);};
  socket.onerror = () => socket.close();
}
window.addEventListener('DOMContentLoaded', () => {
  pollStatus(); connectStatus();
  setInterval(() => {if (!socket || socket.readyState !== WebSocket.OPEN) pollStatus();}, 2000);
});
