from pathlib import Path
import json
import subprocess
import sys
import time
import httpx
import pytest
from app.errors import ServiceError
from app.services.whisper_service import parse_whisper_output, WhisperService
from app.services.ollama_service import OllamaService
from app.services.process import run_command
from app.services.recorder import RecorderService
from app.services.piper_service import PiperService
from app.services.health_service import microphone_check
from app.config import AudioConfig, OllamaConfig
from app.audio_store import AudioStore
from conftest import write_wav


def test_whisper_parser_excludes_diagnostics():
    output = '''whisper_init_from_file: loading model
system_info: NEON=1
[00:00:00.000 --> 00:00:02.100]  你好，世界。
[00:00:02.100 --> 00:00:04.200]  请介绍树莓派。
whisper_print_timings: total = 500 ms
random stdout text'''
    assert parse_whisper_output(output) == "你好，世界。 请介绍树莓派。"
    assert parse_whisper_output("whisper_init: model info\nperformance: 9") == ""


def test_whisper_prefers_clean_output_file(rt, monkeypatch, tmp_path):
    executable = tmp_path / "whisper-cli"
    executable.write_text("placeholder")
    executable.chmod(0o755)
    model = tmp_path / "model.bin"
    model.touch()
    config = rt.config.active.whisper.model_copy(update={"executable": str(executable), "model": str(model)})
    def run(args, timeout, label):
        assert Path(args[args.index("-f") + 1]).is_absolute()
        Path(args[args.index("-of") + 1] + ".txt").write_text("你好", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="model diagnostics", stderr="timings")
    monkeypatch.setattr("app.services.whisper_service.run_command", run)
    assert WhisperService(config).transcribe(write_wav(rt.audio.new_path("user"))) == "你好"
    assert list(rt.audio.directory.glob("transcript*")) == []


@pytest.mark.parametrize("kind,status", [("empty",502),("invalid",502),("http",502),("timeout",504),("connect",503)])
def test_ollama_errors(kind, status):
    def handler(request):
        if kind == "timeout": raise httpx.ReadTimeout("timeout")
        if kind == "connect": raise httpx.ConnectError("unreachable")
        if kind == "http": return httpx.Response(404, json={"error":"model missing"})
        if kind == "invalid": return httpx.Response(200, json={"wrong": "value"})
        return httpx.Response(200, json={"message":{"content":" "}})
    service = OllamaService(OllamaConfig())
    service.client.close()
    service.client = httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(handler))
    with pytest.raises(ServiceError) as exc:
        service.chat([{"role":"user", "content":"test"}])
    assert exc.value.status_code == status
    service.close()


def test_ollama_structured_http_payload():
    messages=[{"role":"system","content":"中文"},{"role":"user","content":"你好"}]
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert body == {"messages":messages,"model":"qwen2.5:0.5b","stream":False,"options":{"temperature":0.7}}
        return httpx.Response(200,json={"message":{"content":"  你好。 "}})
    service=OllamaService(OllamaConfig())
    service.client.close()
    service.client=httpx.Client(base_url="http://localhost",transport=httpx.MockTransport(handler))
    assert service.chat(messages) == "你好。"
    service.close()


def test_process_timeout_and_missing_executable():
    with pytest.raises(ServiceError, match="超时"):
        run_command([sys.executable, "-c", "import time; time.sleep(3)"], .05, "test")
    with pytest.raises(ServiceError, match="不存在"):
        run_command(["/nonexistent/localchat-program"], 1, "test")


@pytest.fixture
def fake_arecord(tmp_path, monkeypatch):
    script = tmp_path / "arecord"
    script.write_text(f'''#!{sys.executable}
import signal, sys, time, wave
stop = False
def interrupt(*args):
    global stop
    stop = True
signal.signal(signal.SIGINT, interrupt)
open(sys.argv[0] + '.ready', 'w').close()
end = time.monotonic() + int(sys.argv[sys.argv.index('-d') + 1])
while not stop and time.monotonic() < end:
    time.sleep(.01)
with wave.open(sys.argv[-1], 'wb') as w:
    w.setparams((1,2,16000,0,'NONE','not compressed'))
    w.writeframes(b'\\0\\0' * 1600)
''')
    script.chmod(0o755)
    monkeypatch.setattr("app.services.recorder.shutil.which", lambda name: str(script) if name == "arecord" else None)
    return script


def test_recorder_real_subprocess_sigint_reaped(tmp_path, fake_arecord):
    recorder=RecorderService(AudioConfig(), AudioStore(tmp_path / "audio"))
    name=recorder.start()
    process=recorder.process
    with pytest.raises(ServiceError, match="已有录音"):
        recorder.start()
    deadline=time.monotonic()+3
    while not Path(str(fake_arecord)+'.ready').exists() and time.monotonic()<deadline:
        time.sleep(.01)
    assert Path(str(fake_arecord)+'.ready').exists()
    result=recorder.stop()
    assert result["filename"] == name
    assert process.poll() == 0
    assert recorder.process is None
    with pytest.raises(ServiceError, match="尚未开始"):
        recorder.stop()


def test_recorder_natural_deadline(rt, fake_arecord):
    result=rt.pipeline.start_recording(1)
    deadline=time.monotonic()+4
    while rt.pipeline.recording_active and time.monotonic()<deadline:
        rt.pipeline.check_recording()
        time.sleep(.05)
    assert not rt.pipeline.recording_active
    assert rt.pipeline.snapshot()["state"] == "idle"
    assert rt.pipeline.stop_recording(result["recording_id"])["recording_id"] == result["recording_id"]
    with rt.pipeline.exclusive():
        pass


def test_piper_loads_once_and_synthesis_separate(rt, monkeypatch):
    import types
    model=rt.root / "voice.onnx"
    model.touch(); Path(str(model)+".json").touch()
    calls=[]
    class FakeVoice:
        @classmethod
        def load(cls, path, use_cuda=False):
            calls.append(path)
            return cls()
        def synthesize_wav(self, text, wav):
            wav.setparams((1,2,22050,0,'NONE','not compressed'))
            wav.writeframes(b'\0\0'*100)
    monkeypatch.setitem(sys.modules,"piper",types.SimpleNamespace(PiperVoice=FakeVoice))
    service=PiperService(rt.config.active.piper.model_copy(update={"model_path":str(model)}), rt.audio, rt.root)
    # Fixture suppresses automatic startup; invoke the real initializer here via saved reference below.
    REAL_PIPER_INITIALIZE(service)
    first=service.synthesize("你好")
    second=service.synthesize("再见")
    assert first != second and len(calls)==1
    assert service.ready


REAL_PIPER_INITIALIZE = PiperService.initialize


def test_watchdog_stops_even_if_arecord_does_not_exit(rt, fake_arecord):
    result = rt.pipeline.start_recording(30)
    deadline = time.monotonic() + 3
    while not Path(str(fake_arecord) + '.ready').exists() and time.monotonic() < deadline:
        time.sleep(.01)
    process = rt.recorder.process
    rt.recorder.started = time.monotonic() - 31
    rt.pipeline.check_recording()
    assert process.poll() == 0
    assert not rt.pipeline.recording_active
    assert rt.pipeline.stop_recording(result['recording_id'])['filename']


def test_microphone_device_enumeration(monkeypatch):
    monkeypatch.setattr('app.services.health_service.shutil.which', lambda name: '/usr/bin/arecord')
    monkeypatch.setattr('app.services.health_service.subprocess.run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, stdout='card 0: Device [USB], device 0: USB Audio [USB Audio]\n'))
    assert microphone_check('plughw:0,0')[0]
    assert not microphone_check('plughw:9,0')[0]


def test_recorder_start_permission_error(tmp_path, monkeypatch):
    monkeypatch.setattr('app.services.recorder.shutil.which', lambda name: '/bin/arecord')
    def denied(*args, **kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr('app.services.recorder.subprocess.Popen', denied)
    recorder = RecorderService(AudioConfig(), AudioStore(tmp_path / 'audio'))
    with pytest.raises(ServiceError, match='录音无法启动'):
        recorder.start()
    assert recorder.process is None
    assert recorder.stderr is None
