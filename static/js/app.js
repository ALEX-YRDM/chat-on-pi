let currentId = Number(localStorage.getItem('conversation_id')) || null;
let recordingId = null, recordingStart = 0, recordingLimit = 30, pending = false, finishing = false, busy = false;
let conversations = [], lastSeenRun = null;
try {
  const saved = JSON.parse(sessionStorage.getItem('recording') || 'null');
  if (saved) {recordingId = saved.id; currentId = saved.conversationId; recordingStart = saved.started; recordingLimit = saved.limit;}
} catch (_) {sessionStorage.removeItem('recording');}
function controls() {
  for (const id of ['send','new-chat','chat-prompt']) $(id).disabled = pending || busy || !!recordingId;
  $('record').disabled = pending || finishing || (busy && !recordingId);
  $('record').textContent = recordingId ? '🔴 停止录音' : '🎤 开始录音';
  $('record').classList.toggle('recording', !!recordingId);
}
async function loadConversations() {
  conversations = await api('/api/conversations');
  $('conversations').replaceChildren();
  for (const conversation of conversations) {
    const row = document.createElement('div'); row.className = 'history-item' + (currentId === conversation.id ? ' active' : '');
    const select = document.createElement('button'); select.className = 'history-title'; select.textContent = conversation.title;
    select.onclick = () => {if (!pending && !busy && !recordingId) selectConversation(conversation.id).catch(e => notice(e.message));};
    const remove = document.createElement('button'); remove.className = 'delete'; remove.textContent = '×'; remove.title = '删除对话'; remove.setAttribute('aria-label', `删除 ${conversation.title}`);
    remove.onclick = async () => {
      if (pending || busy || recordingId || !confirm(`删除对话“${conversation.title}”及其音频？`)) return;
      try {await api(`/api/conversations/${conversation.id}`, 'DELETE'); if (currentId === conversation.id) currentId = null; await loadConversations(); await selectConversation(currentId || conversations[0]?.id || null);} catch (e) {notice(e.message);}
    };
    row.append(select, remove); $('conversations').append(row);
  }
}
async function selectConversation(id) {
  currentId = id; localStorage.setItem('conversation_id', id || '');
  await loadConversations();
  const conversation = conversations.find(x => x.id === id);
  $('chat-title').textContent = conversation?.title || '开始一段对话';
  if (conversation) $('chat-prompt').value = conversation.system_prompt_id;
  await loadMessages();
}
async function loadMessages() {
  const messages = currentId ? await api(`/api/conversations/${currentId}/messages`) : [];
  $('messages').replaceChildren();
  if (!messages.length) {const empty = document.createElement('div'); empty.className = 'empty'; empty.textContent = '输入文字，或使用树莓派麦克风开始对话。'; $('messages').append(empty);}
  for (const message of messages) {
    const article = document.createElement('article'); article.className = `message ${message.role}`;
    const meta = document.createElement('div'); meta.className = 'message-meta'; meta.textContent = `${message.role === 'user' ? '你' : 'LocalChat'} · ${new Date(message.created_at).toLocaleTimeString()}`;
    const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.textContent = message.content;
    article.append(meta,bubble); if (message.audio_url) article.append(audioElement(message.audio_url)); $('messages').append(article);
  }
  $('messages').scrollTop = $('messages').scrollHeight;
}
async function ensureConversation() {
  if (!currentId) {const data = await api('/api/conversations','POST',{}); await selectConversation(data.id);}
  return currentId;
}
async function refreshAfter(result) {
  if (result?.timing) $('timing').textContent = timingText(result.timing);
  await loadConversations(); await loadMessages();
  $('chat-title').textContent = conversations.find(x => x.id === currentId)?.title || '新对话';
}
async function finishRecording() {
  if (!recordingId || finishing) return;
  finishing = true; pending = true; const id = recordingId; controls(); notice();
  try {
    await api(`/api/record/stop?recording_id=${encodeURIComponent(id)}`, 'POST');
    recordingId = null; sessionStorage.removeItem('recording'); controls();
    const result = await api('/api/voice/process','POST',{conversation_id:currentId,recording_id:id});
    await refreshAfter(result);
  } catch (e) {notice(e.message); await refreshAfter(e.result);} finally {recordingId = null; sessionStorage.removeItem('recording'); finishing = false; pending = false; $('record-time').textContent = ''; controls();}
}
window.addEventListener('pipeline-status', (event) => {
  const status = event.detail;
  busy = !['idle','error'].includes(status.state);
  if (currentId && pending && ['thinking','synthesizing'].includes(status.state)) loadMessages().catch(e => notice(e.message));
  if (recordingId && !finishing && status.state === 'idle' && status.last_recording?.recording_id === recordingId) finishRecording();
  if (recordingId && status.state === 'error' && !finishing) {recordingId = null; sessionStorage.removeItem('recording'); notice(status.message || '录音失败');}
  if (!pending && ['idle','error'].includes(status.state) && status.last_result?.conversation_id === currentId && status.last_result?.run_id !== lastSeenRun) {
    lastSeenRun = status.last_result.run_id;
    refreshAfter(status.last_result).catch(e => notice(e.message));
  }
  controls();
});
window.addEventListener('DOMContentLoaded', async () => {
  $('chat-form').onsubmit = async (event) => {
    event.preventDefault(); const message = $('message').value.trim(); if (!message || pending || busy || recordingId) return;
    pending = true; controls(); notice();
    try {await ensureConversation(); const result = await api('/api/chat','POST',{conversation_id:currentId,message,synthesize:$('synthesize').checked}); $('message').value = ''; await refreshAfter(result);}
    catch (e) {notice(e.message); if (e.result?.user) $('message').value = ''; await refreshAfter(e.result);} finally {pending = false; controls();}
  };
  $('message').onkeydown = (event) => {if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault(); $('chat-form').requestSubmit();}};
  bindAction('new-chat', async () => {currentId = null; await ensureConversation();});
  $('record').onclick = async () => {
    if (recordingId) return finishRecording();
    pending = true; controls(); notice();
    try {await ensureConversation(); const result = await api('/api/record/start','POST'); recordingId = result.recording_id; recordingLimit = result.max_record_seconds; recordingStart = Date.now(); sessionStorage.setItem('recording', JSON.stringify({id:recordingId, conversationId:currentId, started:recordingStart, limit:recordingLimit}));}
    catch (e) {notice(e.message);} finally {pending = false; controls();}
  };
  $('chat-prompt').onchange = async () => {if (currentId) {try {await api(`/api/conversations/${currentId}`,'PUT',{system_prompt_id:Number($('chat-prompt').value)});} catch (e) {notice(e.message);}}};
  setInterval(() => {
    if (recordingId) {const seconds = Math.floor((Date.now()-recordingStart)/1000); $('record-time').textContent = `正在录音 ${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`; if (seconds >= recordingLimit) finishRecording();}
  }, 250);
  try {
    const prompts = await api('/api/prompts'); for (const prompt of prompts) {const option = document.createElement('option'); option.value = prompt.id; option.textContent = prompt.name; $('chat-prompt').append(option);}
    await loadConversations(); await selectConversation(conversations.some(x=>x.id === currentId) ? currentId : conversations[0]?.id || null);
  } catch (e) {notice(e.message);}
});
