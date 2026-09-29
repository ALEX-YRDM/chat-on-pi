let config, profiles = [], selectedPrompt = null;
const labels = {
  app:['应用','监听地址','端口','调试日志'],
  audio:['Audio','输入设备','采样率（语音识别需要 16000）','声道（语音识别需要 1）','格式（本版固定 S16_LE）','录音上限（秒）','播放设备'],
  whisper:['Whisper','whisper-cli 绝对路径','模型绝对路径','语言','线程数','超时（秒）'],
  ollama:['Ollama','Base URL','模型','Temperature','历史消息条数','超时（秒）'],
  piper:['Piper','Voice','模型绝对路径（可留空）','Backend（api / cli）','CLI 超时（秒）'],
  conversation:['Conversation','树莓派自动播放','保留用户录音','保留助手音频']
};
function showPrompt(id) {
  selectedPrompt = id; const profile = profiles.find(x=>x.id === id);
  $('prompt-name').value = profile?.name || ''; $('prompt-content').value = profile?.content || '';
  $('prompt-default').checked = profile?.is_default || false; $('delete-prompt').disabled = !profile;
  $('prompt-list').value = id || '';
}
async function loadPrompts(id) {
  profiles = await api('/api/prompts'); $('prompt-list').replaceChildren();
  profiles.forEach(p=>{const option=document.createElement('option'); option.value=p.id; option.textContent=p.name+(p.is_default?' ★ 默认':''); $('prompt-list').append(option);});
  showPrompt(id ?? profiles[0]?.id ?? null);
}
window.addEventListener('DOMContentLoaded', async () => {
  try {
    const saved = await api('/api/settings'); config = saved.config;
    $('config-status').textContent = saved.restart_required ? '有待重启生效的修改' : '配置已生效';
    for (const [section, values] of Object.entries(config)) {
      const card = document.createElement('section'); card.className = 'card'; const title = document.createElement('h2'); title.textContent=labels[section][0]; card.append(title);
      Object.entries(values).forEach(([key,value], index)=>{
        const label = document.createElement('label'); label.textContent=labels[section][index+1] || key; label.htmlFor=`cfg-${section}-${key}`;
        const input = document.createElement('input'); input.id=label.htmlFor; input.dataset.section=section; input.dataset.key=key;
        input.type=typeof value === 'boolean'?'checkbox':typeof value === 'number'?'number':'text';
        if (input.type === 'checkbox') {input.checked=value; label.className='checkbox'; label.prepend(input); card.append(label);} else {input.value=value; if(input.type==='number') input.step=key==='temperature'?'0.1':'1'; card.append(label,input);}
      });
      $('config-fields').append(card);
    }
    await loadPrompts();
  } catch (e) {notice(e.message);}
  $('config-form').onsubmit=async (event)=>{
    event.preventDefault(); const button=event.submitter; button.disabled=true; notice();
    try {
      const updated=structuredClone(config);
      document.querySelectorAll('[data-section]').forEach(input=>updated[input.dataset.section][input.dataset.key]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value);
      const result=await api('/api/settings','PUT',updated); config=updated; $('config-status').textContent=result.message;
    } catch(e){notice(e.message);} finally {button.disabled=false;}
  };
  $('prompt-list').onchange=()=>showPrompt(Number($('prompt-list').value));
  $('new-prompt').onclick=()=>showPrompt(null);
  $('prompt-form').onsubmit=async(event)=>{
    event.preventDefault(); const button=event.submitter; button.disabled=true; notice();
    try {const body={name:$('prompt-name').value,content:$('prompt-content').value,is_default:$('prompt-default').checked}; const saved=await api(selectedPrompt?`/api/prompts/${selectedPrompt}`:'/api/prompts', selectedPrompt?'PUT':'POST',body); await loadPrompts(saved.id); notice('Prompt 已保存并立即生效。');}
    catch(e){notice(e.message);} finally{button.disabled=false;}
  };
  bindAction('delete-prompt',async()=>{if(selectedPrompt && confirm('删除这个 Prompt？')){await api(`/api/prompts/${selectedPrompt}`,'DELETE');await loadPrompts();}});
});
