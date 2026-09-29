"""All public audio references are confined to one flat WAV directory."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import wave
from .errors import ServiceError


class AudioStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def new_path(self, prefix: str) -> Path:
        return self.directory / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex}.wav"

    def resolve(self, reference: str, must_exist: bool = True) -> Path:
        supplied = Path(reference)
        if ".." in supplied.parts or "\\" in reference or "\x00" in reference:
            raise ServiceError("音频路径无效", 400)
        if not supplied.is_absolute() and supplied.name != reference:
            raise ServiceError("请使用音频文件名或受管理目录内的绝对路径", 400)
        candidate = supplied if supplied.is_absolute() else self.directory / supplied
        resolved = candidate.resolve()
        if candidate.is_symlink() or resolved.parent != self.directory or resolved.suffix.lower() != ".wav":
            raise ServiceError("只允许访问 data/audio 中的 WAV 文件", 400)
        if must_exist and not resolved.is_file():
            raise ServiceError("音频不存在或已被清理", 404)
        return resolved

    def validate_wav(self, reference: str, require_stt: bool = False) -> Path:
        path = self.resolve(reference)
        if path.stat().st_size > 50 * 1024 * 1024:
            raise ServiceError("WAV 文件超过 50 MB", 400)
        try:
            with wave.open(str(path), "rb") as audio:
                if audio.getnframes() == 0:
                    raise ValueError("empty")
                if require_stt and (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                    raise ServiceError("Whisper 输入需要 16kHz、单声道、16-bit PCM WAV", 400)
        except (wave.Error, EOFError, ValueError) as exc:
            raise ServiceError("WAV 文件为空或格式无效", 400) from exc
        return path

    def url(self, path: str | Path | None) -> str | None:
        return f"/api/audio/{Path(path).name}" if path else None

    def delete(self, reference: str) -> None:
        self.resolve(reference, must_exist=False).unlink(missing_ok=True)
