import shutil
import wave
from ..audio_store import AudioStore
from ..config import AudioConfig
from ..errors import ServiceError
from .process import run_command


class AudioPlayer:
    def __init__(self, config: AudioConfig, audio: AudioStore):
        self.config, self.audio = config, audio

    def play(self, audio_path: str) -> None:
        executable = shutil.which("aplay")
        if not executable:
            raise ServiceError("未找到 aplay，请安装 alsa-utils")
        path = self.audio.validate_wav(audio_path)
        with wave.open(str(path), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
        run_command([executable, "-D", self.config.playback_device, str(path)],
                    min(duration + 15, 600), "aplay")
