let generatedFile=null;
async function health() {
  const report=await api('/api/health'); $('health').replaceChildren();
  for(const [name,ok] of Object.entries(report.services)){const item=document.createElement('div');item.className='health-item';item.textContent=name;const value=document.createElement('strong');value.className=ok?'ok':'bad';value.textContent=ok?'OK':'Unavailable';item.append(value);$('health').append(item);}
  $('health-details').textContent=JSON.stringify(report.details,null,2);
}
async function audioList(selected) {
  const list=await api('/api/audio'); $('wav-select').replaceChildren();
  list.forEach(file=>{const option=document.createElement('option');option.value=file.filename;option.textContent=file.filename;$('wav-select').append(option);});
  if(selected)$('wav-select').value=selected;
}
async function runs() {$('runs-output').textContent=JSON.stringify(await api('/api/debug/runs'),null,2);}
window.addEventListener('DOMContentLoaded',()=>{
  bindAction('refresh-health',health);bindAction('refresh-audio',()=>audioList());bindAction('refresh-runs',runs);
  bindAction('test-mic',async()=>{const result=await api('/api/debug/record','POST');$('mic-output').replaceChildren(audioElement(result.audio_url));await audioList(result.filename);});
  bindAction('test-whisper',async()=>{const result=await api('/api/debug/whisper','POST',{audio_path:$('wav-select').value});$('whisper-output').textContent=`${result.output}\n\nSTT: ${result.latency_ms} ms`;});
  bindAction('test-ollama',async()=>{const result=await api('/api/debug/ollama','POST',{text:$('ollama-text').value});$('ollama-output').textContent=`${result.output}\n\nLLM: ${result.latency_ms} ms`;});
  bindAction('test-piper',async()=>{const result=await api('/api/debug/piper','POST',{text:$('piper-text').value});generatedFile=result.filename;$('test-speaker').disabled=false;$('piper-output').replaceChildren(audioElement(result.audio_url));const timing=document.createElement('p');timing.textContent=`TTS: ${result.latency_ms} ms`;$('piper-output').append(timing);await audioList();});
  bindAction('test-speaker',async()=>{await api('/api/audio/play','POST',{audio_path:generatedFile});});
  bindAction('test-pipeline',async()=>{
    const conversation=await api('/api/conversations','POST',{title:'全流程测试'});
    try {const result=await api(`/api/debug/pipeline?conversation_id=${conversation.id}`,'POST');$('pipeline-output').textContent=timingText(result.timing)+'\n\n'+JSON.stringify(result,null,2);}
    catch(e){$('pipeline-output').textContent=JSON.stringify(e.result || {error:e.message},null,2);throw e;} finally{await runs();await audioList();}
  });
  Promise.all([health(),audioList(),runs()]).catch(e=>notice(e.message));
});
