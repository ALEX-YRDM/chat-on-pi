import importlib.util
import logging
from pathlib import Path
import sys
import threading
import time
import wave
from ..audio_store import AudioStore
from ..config import PiperConfig
from ..errors import ServiceError
from .process import run_command

logger = logging.getLogger("localchat.piper")


class PiperService:
    """Load one CPU voice at startup. CLI fallback must be selected explicitly."""
    def __init__(self, config: PiperConfig, audio: AudioStore, root: Path):
        self.config, self.audio, self.root = config, audio, root
        self.voice = None
        self.ready = False
        self.error = "尚未初始化"
        self.lock = threading.Lock()
        self.model_path = Path(config.model_path) if config.model_path else root / f"{config.voice}.onnx"

    def initialize(self) -> None:
        try:
            if self.config.backend == "cli":
                if importlib.util.find_spec("piper") is None:
                    raise RuntimeError("Piper package 未安装")
                self.ready = True
                self.error = "CLI 模式：仅确认 package 存在，请用 Debug 验证模型"
                logger.info("Piper CLI fallback initialized")
                return
            if not self.model_path.is_file() or not Path(str(self.model_path) + ".json").is_file():
                raise RuntimeError(f"缺少 Piper 模型或 .onnx.json：{self.model_path}")
            from piper import PiperVoice
            self.voice = PiperVoice.load(str(self.model_path), use_cuda=False)
            if not hasattr(self.voice, "synthesize_wav"):
                raise RuntimeError("当前 Piper API 不支持 synthesize_wav，请更新 piper-tts 或设置 backend: cli")
            self.ready = True
            self.error = ""
            logger.info("Piper initialized voice=%s", self.config.voice)
        except Exception as exc:
            self.error = str(exc)
            logger.exception("Piper initialization failed; text-only chat remains available")

    def synthesize(self, text: str) -> str:
        if not self.ready:
            raise ServiceError(f"Piper 未初始化：{self.error}")
        path = self.audio.new_path("assistant")
        started = time.monotonic()
        with self.lock:
            try:
                if self.config.backend == "cli":
                    model = str(self.model_path) if self.model_path.exists() else self.config.voice
                    run_command([sys.executable, "-m", "piper", "-m", model, "-f", str(path), "--", text],
                                self.config.timeout_seconds, "Piper", cwd=str(self.root))
                else:
                    with wave.open(str(path), "wb") as wav:
                        self.voice.synthesize_wav(text, wav)
                self.audio.validate_wav(str(path))
            except ServiceError:
                path.unlink(missing_ok=True)
                raise
            except Exception as exc:
                path.unlink(missing_ok=True)
                raise ServiceError("Piper 语音合成失败，请检查模型及版本") from exc
        logger.info("Synthesis finished latency=%sms", round((time.monotonic() - started) * 1000))
        return str(path)
