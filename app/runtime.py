from pathlib import Path
from .audio_store import AudioStore
from .config import ConfigStore
from .database import Database
from .pipeline import Pipeline
from .services.recorder import RecorderService
from .services.whisper_service import WhisperService
from .services.ollama_service import OllamaService
from .services.piper_service import PiperService
from .services.audio_player import AudioPlayer


class Runtime:
    def __init__(self, config: ConfigStore, db: Database, root: Path):
        self.config, self.db, self.root = config, db, root
        self.audio = AudioStore(root / "data/audio")
        self.recorder = RecorderService(config.active.audio, self.audio)
        self.whisper = WhisperService(config.active.whisper)
        self.ollama = OllamaService(config.active.ollama)
        self.piper = PiperService(config.active.piper, self.audio, root)
        self.player = AudioPlayer(config.active.audio, self.audio)
        self.pipeline = Pipeline(self)

    def close(self) -> None:
        self.recorder.close()
        self.ollama.close()
        self.db.engine.dispose()
