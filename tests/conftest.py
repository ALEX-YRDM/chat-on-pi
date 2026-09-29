from pathlib import Path
import wave
import httpx
import pytest
from fastapi.testclient import TestClient
from app.config import ROOT
from app.main import create_app
from app.services.piper_service import PiperService


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text((ROOT / "config.yaml").read_text())
    monkeypatch.setattr(PiperService, "initialize", lambda self: None)
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("not running")
    monkeypatch.setattr(httpx, "get", unavailable)
    app = create_app(config, tmp_path)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def rt(client):
    return client.app.state.runtime


def write_wav(path: Path, rate=16000, channels=1) -> str:
    with wave.open(str(path), "wb") as wav:
        wav.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 1600 * channels)
    return str(path)


@pytest.fixture
def fake_services(rt, monkeypatch):
    calls = []
    def answer(messages, *args):
        calls.append(messages)
        return "树莓派五是一台单板计算机。"
    monkeypatch.setattr(rt.ollama, "chat", answer)
    monkeypatch.setattr(rt.whisper, "transcribe", lambda path: "给我介绍一下树莓派五")
    monkeypatch.setattr(rt.piper, "synthesize", lambda text: write_wav(rt.audio.new_path("assistant")))
    monkeypatch.setattr(rt.player, "play", lambda path: None)
    return calls


@pytest.fixture
def conversation(client):
    response = client.post("/api/conversations", json={})
    assert response.status_code == 201
    return response.json()["id"]
