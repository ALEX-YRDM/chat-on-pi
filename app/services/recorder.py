import logging
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from ..audio_store import AudioStore
from ..config import AudioConfig
from ..errors import ServiceError

logger = logging.getLogger("localchat.recorder")


class RecorderService:
    """One arecord process. The pipeline owns the automatic-stop watchdog."""
    def __init__(self, config: AudioConfig, audio: AudioStore):
        self.config = config
        self.audio = audio
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.path: Path | None = None
        self.started = 0.0
        self.duration = config.max_record_seconds
        self.stderr = None

    def start(self, seconds: int | None = None) -> str:
        with self.lock:
            if self.process is not None:
                raise ServiceError("已有录音任务，请先停止", 409)
            executable = shutil.which("arecord")
            if not executable:
                raise ServiceError("未找到 arecord，请安装 alsa-utils 并在树莓派运行")
            self.path = self.audio.new_path("user")
            self.stderr = tempfile.TemporaryFile()
            duration = min(seconds or self.config.max_record_seconds, self.config.max_record_seconds)
            self.duration = duration
            args = [executable, "-D", self.config.input_device, "-f", self.config.format,
                    "-r", str(self.config.sample_rate), "-c", str(self.config.channels),
                    "-d", str(duration), "-t", "wav", str(self.path)]
            try:
                self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=self.stderr)
                self.started = time.monotonic()
                time.sleep(0.12)
                if self.process.poll() is not None:
                    raise ServiceError("录音启动失败，请检查麦克风设备和 ALSA 权限")
            except Exception as exc:
                self._log_diagnostics()
                self._cleanup()
                self.path.unlink(missing_ok=True)
                if isinstance(exc, OSError):
                    raise ServiceError("录音无法启动，请检查 arecord 权限及麦克风设备") from exc
                raise
            logger.info("Recording started file=%s", self.path.name)
            return self.path.name

    def finished(self) -> bool:
        with self.lock:
            return self.process is not None and (
                self.process.poll() is not None
                or time.monotonic() >= self.started + self.duration + 0.5
            )

    def stop(self) -> dict:
        with self.lock:
            if self.process is None:
                raise ServiceError("录音尚未开始", 409)
            process, path = self.process, self.path
            elapsed = round((time.monotonic() - self.started) * 1000)
            interrupted = process.poll() is None
            try:
                if interrupted:
                    try:
                        process.send_signal(signal.SIGINT)
                    except ProcessLookupError:
                        pass
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                    raise ServiceError("录音进程未正常停止，已终止并回收") from None
                # ALSA may return 1 after SIGINT even when the WAV was finalized.
                if (not interrupted and code != 0) or code not in (0, 1, -signal.SIGINT):
                    raise ServiceError("录音失败，请检查麦克风是否被占用")
                if not path.is_file():
                    raise ServiceError("没有录到音频，请至少录音一秒后再停止", 422)
                self.audio.validate_wav(str(path))
                logger.info("Recording finished latency=%sms", elapsed)
                return {"recording_id": path.stem, "filename": path.name,
                        "audio_url": self.audio.url(path), "recording_ms": elapsed}
            except Exception:
                self._log_diagnostics()
                path.unlink(missing_ok=True)
                raise
            finally:
                self._cleanup()

    def _log_diagnostics(self) -> None:
        if self.stderr is not None:
            self.stderr.seek(0)
            logger.error("arecord diagnostics: %s", self.stderr.read(4096).decode("utf-8", errors="replace").strip())

    def _cleanup(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=3)
        self.process = None
        if self.stderr is not None:
            self.stderr.close()
            self.stderr = None

    def close(self) -> None:
        with self.lock:
            self._cleanup()
