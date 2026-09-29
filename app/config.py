"""Validated YAML configuration. Saved edits become active after a restart."""
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import os
import tempfile
import threading

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppConfig(StrictModel):
    host: str = "0.0.0.0"
    port: int = Field(8000, ge=1, le=65535)
    debug: bool = False


class AudioConfig(StrictModel):
    input_device: str = Field("plughw:0,0", min_length=1, max_length=100, pattern=r"^[\w:,.=-]+$")
    sample_rate: int = Field(16000, ge=8000, le=48000)
    channels: int = Field(1, ge=1, le=2)
    format: Literal["S16_LE"] = "S16_LE"
    max_record_seconds: int = Field(30, ge=1, le=120)
    playback_device: str = Field("default", min_length=1, max_length=100, pattern=r"^[\w:,.=-]+$")


def absolute_path(value: str) -> str:
    if not Path(value).is_absolute() or ".." in Path(value).parts or "\x00" in value:
        raise ValueError("必须使用不含 .. 的绝对路径")
    return value


class WhisperConfig(StrictModel):
    executable: str
    model: str
    language: str = Field("zh", pattern=r"^[a-z]{2,3}$|^auto$")
    threads: int = Field(4, ge=1, le=8)
    timeout_seconds: int = Field(120, ge=1, le=600)

    @field_validator("executable", "model")
    @classmethod
    def check_path(cls, value: str) -> str:
        return absolute_path(value)

    @field_validator("executable")
    @classmethod
    def check_executable(cls, value: str) -> str:
        if Path(value).name != "whisper-cli":
            raise ValueError("可执行文件名必须是 whisper-cli")
        return value


class OllamaConfig(StrictModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = Field("qwen2.5:0.5b", min_length=1, max_length=150)
    temperature: float = Field(0.7, ge=0, le=2)
    context_message_limit: int = Field(10, ge=0, le=100)
    timeout_seconds: int = Field(180, ge=1, le=600)

    @field_validator("base_url")
    @classmethod
    def check_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("需要 http(s)://host:port，不包含凭据、路径或查询参数")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("端口无效") from exc
        return value.rstrip("/")


class PiperConfig(StrictModel):
    voice: str = Field("zh_CN-huayan-medium", pattern=r"^[A-Za-z0-9_-]+$")
    model_path: str = ""
    backend: Literal["api", "cli"] = "api"
    timeout_seconds: int = Field(120, ge=1, le=600)

    @field_validator("model_path")
    @classmethod
    def check_model(cls, value: str) -> str:
        return absolute_path(value) if value else value


class ConversationConfig(StrictModel):
    auto_play_tts: bool = True
    keep_user_audio: bool = True
    keep_assistant_audio: bool = True


class Settings(StrictModel):
    app: AppConfig = Field(default_factory=AppConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    whisper: WhisperConfig
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    piper: PiperConfig = Field(default_factory=PiperConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.lock = threading.Lock()
        self.active = self.load()

    def load(self) -> Settings:
        with self.path.open(encoding="utf-8") as handle:
            return Settings.model_validate(yaml.safe_load(handle))

    def save(self, settings: Settings) -> None:
        """Atomic replacement avoids a partially written config on power loss."""
        with self.lock:
            name = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent,
                                                 encoding="utf-8", delete=False) as handle:
                    name = handle.name
                    yaml.safe_dump(settings.model_dump(), handle, allow_unicode=True, sort_keys=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.path)
            finally:
                if name and Path(name).exists():
                    Path(name).unlink()
