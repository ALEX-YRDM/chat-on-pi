from pathlib import Path
import pytest
from sqlalchemy import select
from app.errors import ServiceError
from app.models import Message, PipelineRun
from conftest import write_wav


@pytest.mark.parametrize("url", ["/", "/settings", "/debug", "/api/health", "/api/status", "/static/css/style.css", "/static/js/app.js", "/static/js/common.js", "/static/js/settings.js", "/static/js/debug.js"])
def test_pages_and_assets(client,url):
    assert client.get(url).status_code==200


def test_chat_persisted_with_context(client, rt, conversation, fake_services):
    for text in ("你好", "你是谁"):
        response=client.post('/api/chat',json={"conversation_id":conversation,"message":text,"synthesize":False})
        assert response.status_code==200, response.text
    assert [x['role'] for x in fake_services[1]]==['system','user','assistant','user']
    messages=client.get(f'/api/conversations/{conversation}/messages').json()
    assert len(messages)==4
    assert client.get(f'/api/conversations/{conversation}').json()['title']=='你好'
    assert len(client.get('/api/debug/runs').json())==2


def test_voice_complete(client,rt,conversation,fake_services):
    path=write_wav(rt.audio.new_path('user'))
    response=client.post('/api/voice/process',json={"conversation_id":conversation,"audio_path":path})
    assert response.status_code==200,response.text
    data=response.json()
    assert data['success']
    assert set(data['timing'])=={'recording_ms','stt_ms','llm_ms','tts_ms','playback_ms','total_ms'}
    for role in ('user','assistant'):
        audio=client.get(data[role]['audio_url'])
        assert audio.status_code==200
        assert audio.content[:4]==b'RIFF'
    assert rt.pipeline.snapshot()['state']=='idle'


def test_tts_failure_preserves_text_and_next_request_recovers(client,rt,conversation,fake_services,monkeypatch):
    def failed(text): raise ServiceError('Piper TTS 失败')
    monkeypatch.setattr(rt.piper,'synthesize',failed)
    response=client.post('/api/chat',json={'conversation_id':conversation,'message':'你好','synthesize':True})
    assert response.status_code==503
    assert response.json()['result']['assistant']['text']
    assert len(client.get(f'/api/conversations/{conversation}/messages').json())==2
    assert rt.pipeline.snapshot()['state']=='error'
    assert client.post('/api/chat',json={'conversation_id':conversation,'message':'继续','synthesize':False}).status_code==200
    assert rt.pipeline.snapshot()['state']=='idle'


def test_llm_failure_saves_user_and_failure_run(client,rt,conversation,monkeypatch):
    def failed(messages): raise ServiceError('Ollama 超时',504)
    monkeypatch.setattr(rt.ollama,'chat',failed)
    response=client.post('/api/chat',json={'conversation_id':conversation,'message':'hello','synthesize':False})
    assert response.status_code==504
    assert response.json()['result']['user']['text']=='hello'
    assert not client.get('/api/debug/runs').json()[0]['success']


def test_concurrent_jobs_and_deletes_rejected(client,rt,conversation):
    with rt.pipeline.exclusive():
        assert client.post('/api/chat',json={'conversation_id':conversation,'message':'test'}).status_code==409
        assert client.post('/api/record/start').status_code==409
        assert client.delete(f'/api/conversations/{conversation}').status_code==409


def test_retention_deletes_wav_after_play(client,rt,conversation,fake_services):
    rt.config.active.conversation.keep_user_audio=False
    rt.config.active.conversation.keep_assistant_audio=False
    path=write_wav(rt.audio.new_path('user'))
    result=client.post('/api/voice/process',json={'conversation_id':conversation,'audio_path':path}).json()
    assert result['success']
    assert result['user']['audio_url'] is None
    assert result['assistant']['audio_url'] is None
    assert not list(rt.audio.directory.glob('*.wav'))


def test_delete_cascades_and_removes_audio(client,rt,conversation,fake_services):
    client.post('/api/chat',json={'conversation_id':conversation,'message':'你好'})
    assert client.delete(f'/api/conversations/{conversation}').status_code==200
    assert client.get(f'/api/conversations/{conversation}').status_code==404
    with rt.db.session() as session:
        assert session.scalar(select(Message.id)) is None
        assert session.scalar(select(PipelineRun.id)) is None
    assert not list(rt.audio.directory.glob('*.wav'))


def test_prompt_default_binding_edit_and_delete(client,conversation):
    original=client.get('/api/prompts').json()[0]
    assert client.delete(f"/api/prompts/{original['id']}").status_code==409
    body={'name':'简洁','content':'简短回答','is_default':True}
    second=client.post('/api/prompts',json=body).json()
    assert client.post('/api/conversations',json={}).json()['system_prompt_id']==second['id']
    assert client.get(f'/api/conversations/{conversation}').json()['system_prompt_id']==original['id']
    assert client.put(f'/api/conversations/{conversation}',json={'system_prompt_id':second['id']}).status_code==200
    assert client.delete(f"/api/prompts/{original['id']}").status_code==200
    body['content']='新的提示'
    assert client.put(f"/api/prompts/{second['id']}",json=body).json()['content']=='新的提示'
    assert sum(x['is_default'] for x in client.get('/api/prompts').json())==1


def test_settings_requires_restart(client):
    values=client.get('/api/settings').json()['config']
    values['ollama']['model']='new:model'
    assert client.put('/api/settings',json=values).json()['restart_required']
    result=client.get('/api/settings').json()
    assert result['config']['ollama']['model']=='new:model'
    assert result['active']['ollama']['model']=='qwen2.5:0.5b'


@pytest.mark.parametrize('path',['../config.yaml','/etc/passwd','x/../../test.wav','a\\b.wav'])
def test_audio_traversal(client,conversation,path):
    response=client.post('/api/voice/process',json={'conversation_id':conversation,'audio_path':path})
    assert response.status_code==400


def test_audio_symlink_and_bad_wav(rt,client,conversation,tmp_path):
    outside=tmp_path/'outside.wav';write_wav(outside)
    (rt.audio.directory/'link.wav').symlink_to(outside)
    with pytest.raises(ServiceError):rt.audio.resolve('link.wav')
    assert client.get('/api/audio/link.wav').status_code==400
    bad=rt.audio.directory/'bad.wav';bad.write_bytes(b'bad')
    assert client.post('/api/voice/process',json={'conversation_id':conversation,'audio_path':'bad.wav'}).status_code==400
    write_wav(rt.audio.directory/'wrong.wav',rate=22050)
    assert client.post('/api/voice/process',json={'conversation_id':conversation,'audio_path':'wrong.wav'}).status_code==400


def test_api_validation_and_origin(client):
    assert client.post('/api/chat',json={'conversation_id':1,'message':'   '}).status_code==422
    assert client.post('/api/conversations',json={},headers={'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/conversations',content='a=b',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==415
    assert client.post('/api/chat',content='x'*140000,headers={'Content-Type':'application/json'}).status_code==413


def test_websocket_states_disconnect_and_reconnect(client,rt):
    from app.pipeline import State
    with client.websocket_connect('/ws/status') as ws:
        assert ws.receive_json()['state']=='idle'
        rt.pipeline.change(State.THINKING)
        assert ws.receive_json()['state']=='thinking'
        rt.pipeline.change(State.IDLE)
        assert ws.receive_json()['state']=='idle'
    with client.websocket_connect('/ws/status') as ws:
        assert ws.receive_json()['state']=='idle'
    assert client.get('/api/status').status_code==200


def test_reused_input_survives_other_conversation_deletion(client,rt,conversation,fake_services):
    path=write_wav(rt.audio.new_path('user'))
    other=client.post('/api/conversations',json={}).json()['id']
    for cid in (conversation,other):
        assert client.post('/api/voice/process',json={'conversation_id':cid,'audio_path':path}).status_code==200
    assert client.delete(f'/api/conversations/{conversation}').status_code==200
    assert Path(path).exists()
    assert client.delete(f'/api/conversations/{other}').status_code==200
    assert not Path(path).exists()


def test_missing_hardware_and_empty_transcription(client,rt,conversation,monkeypatch):
    monkeypatch.setattr('app.services.recorder.shutil.which',lambda name:None)
    assert client.post('/api/record/start').status_code==503
    assert client.post('/api/record/stop').status_code==409
    def empty(path): raise ServiceError('Whisper 未识别到文字',422)
    monkeypatch.setattr(rt.whisper,'transcribe',empty)
    path=write_wav(rt.audio.new_path('user'))
    response=client.post('/api/voice/process',json={'conversation_id':conversation,'audio_path':path})
    assert response.status_code==422
    assert client.get(f'/api/conversations/{conversation}/messages').json()==[]
    assert client.get('/api/health').status_code==200


def test_speaker_failure_keeps_wav_and_text(client,rt,conversation,fake_services,monkeypatch):
    def fail(path):raise ServiceError('aplay 执行失败')
    monkeypatch.setattr(rt.player,'play',fail)
    response=client.post('/api/chat',json={'conversation_id':conversation,'message':'你好'})
    assert response.status_code==503
    result=response.json()['result']
    assert result['assistant']['text']
    assert client.get(result['assistant']['audio_url']).status_code==200


def test_database_error_is_reported_without_killing_app(client,rt,monkeypatch):
    from sqlalchemy.exc import OperationalError
    real=rt.db.session
    def fail(*args,**kwargs):raise OperationalError('test',{},Exception('unavailable'))
    monkeypatch.setattr(rt.db,'session',fail)
    assert client.get('/api/conversations').status_code==503
    monkeypatch.setattr(rt.db,'session',real)
    assert client.get('/api/conversations').status_code==200
