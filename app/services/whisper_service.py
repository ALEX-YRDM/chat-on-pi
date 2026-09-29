import logging
import os
from pathlib import Path
import re
import time
from uuid import uuid4
from ..config import WhisperConfig
from ..errors import ServiceError
from .process import run_command

logger = logging.getLogger("localchat.whisper")
SEGMENT = re.compile(r"^\s*\[\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}\]\s*(.*?)\s*$")


def parse_whisper_output(output: str) -> str:
    """Fallback accepts only timestamped transcript segments, never diagnostic lines."""
    segments = []
    for line in output.splitlines():
        match = SEGMENT.match(line)
        if match and match.group(1).strip():
            segments.append(match.group(1).strip())
    return " ".join(segments).strip()


class WhisperService:
    def __init__(self, config: WhisperConfig):
        self.config = config

    def transcribe(self, audio_path: str) -> str:
        config = self.config
        if not Path(config.executable).is_file() or not os.access(config.executable, os.X_OK):
            raise ServiceError("Whisper executable 不存在或不可执行")
        if not Path(config.model).is_file():
            raise ServiceError("Whisper model 不存在，请检查配置")
        path = Path(audio_path).resolve()
        output_base = path.parent / f"transcript_{uuid4().hex}"
        output_file = Path(str(output_base) + ".txt")
        started = time.monotonic()
        try:
            result = run_command([config.executable, "-m", config.model, "-f", str(path),
                                  "-l", config.language, "-t", str(config.threads),
                                  "-otxt", "-of", str(output_base)], config.timeout_seconds, "Whisper")
            text = (output_file.read_text(encoding="utf-8").strip() if output_file.exists()
                    else parse_whisper_output(result.stdout))
            if not text:
                raise ServiceError("Whisper 未识别到文字，请靠近麦克风重新录音", 422)
            logger.info("Transcription finished latency=%sms chars=%s", round((time.monotonic() - started) * 1000), len(text))
            return text
        finally:
            output_file.unlink(missing_ok=True)
