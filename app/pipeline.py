"""Single-user half-duplex orchestration, shared by chat and diagnostic operations."""
from contextlib import contextmanager
from enum import StrEnum
import logging
import threading
import time
from sqlalchemy import select
from .errors import ServiceError
from .models import Conversation, Message, PipelineRun, utcnow
from .repository import add_user, build_messages, get_conversation

logger = logging.getLogger("localchat.pipeline")


class State(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SYNTHESIZING = "synthesizing"
    PLAYING = "playing"
    ERROR = "error"


class Pipeline:
    def __init__(self, runtime):
        self.rt = runtime
        self.gate = threading.Lock()
        self.state_lock = threading.Lock()
        self.status = {"state": State.IDLE, "message": "Ready"}
        self.last_result = None
        self.record_lock = threading.Lock()
        self.recording_active = False
        self.active_recording_id = None
        self.recordings = {}
        self.last_recording = None

    def snapshot(self) -> dict:
        with self.state_lock:
            return {**self.status, "last_recording": self.last_recording, "last_result": self.last_result}

    def change(self, state: State, message: str = "", **extra) -> None:
        with self.state_lock:
            self.status = {"state": state, "message": message, **extra}
        logger.info("State=%s", state)
        if hasattr(self.rt, "hub"):
            self.rt.hub.publish(self.snapshot())

    @contextmanager
    def exclusive(self):
        if not self.gate.acquire(blocking=False):
            raise ServiceError("系统正忙，请等待当前录音、推理或播放完成", 409)
        try:
            yield
        finally:
            self.gate.release()

    def _stage(self, state: State, key: str, timing: dict, function, *args):
        self.change(state)
        start = time.monotonic()
        try:
            return function(*args)
        finally:
            timing[key] = round((time.monotonic() - start) * 1000)

    def chat(self, conversation_id: int, message: str, synthesize: bool, play: bool | None = None) -> dict:
        with self.exclusive():
            return self._run(conversation_id, message, synthesize, play)

    def _run(self, conversation_id: int, message: str, synthesize: bool,
             play: bool | None, audio_path: str | None = None, recording_ms: int = 0) -> dict:
        started = time.monotonic()
        timing = dict.fromkeys(["recording_ms", "stt_ms", "llm_ms", "tts_ms", "playback_ms", "total_ms"], 0)
        timing["recording_ms"] = recording_ms
        result = {"success": False, "conversation_id": conversation_id, "user": None, "assistant": None, "timing": timing}
        generated = None
        error = None
        valid_conversation = False
        try:
            with self.rt.db.session() as session:
                get_conversation(session, conversation_id)
                valid_conversation = True
            if audio_path:
                self.rt.audio.validate_wav(audio_path, require_stt=True)
                message = self._stage(State.TRANSCRIBING, "stt_ms", timing, self.rt.whisper.transcribe, audio_path)
            self.change(State.THINKING)
            with self.rt.db.session.begin() as session:
                conversation = get_conversation(session, conversation_id)
                messages = build_messages(session, conversation, message, self.rt.config.active.ollama.context_message_limit)
                user_audio = audio_path if self.rt.config.active.conversation.keep_user_audio else None
                user = add_user(session, conversation, message,
                                self.rt.audio.resolve(user_audio).name if user_audio else None, timing["stt_ms"])
                result["user"] = {"id": user.id, "text": message, "audio_url": self.rt.audio.url(user_audio)}
            answer = self._stage(State.THINKING, "llm_ms", timing, self.rt.ollama.chat, messages)
            with self.rt.db.session.begin() as session:
                assistant = Message(conversation_id=conversation_id, role="assistant", content=answer, latency_ms=timing["llm_ms"])
                session.add(assistant)
                session.get(Conversation, conversation_id).updated_at = utcnow()
                session.flush()
                assistant_id = assistant.id
            result["assistant"] = {"id": assistant_id, "text": answer, "audio_url": None}
            if synthesize:
                generated = self._stage(State.SYNTHESIZING, "tts_ms", timing, self.rt.piper.synthesize, answer)
                if self.rt.config.active.conversation.keep_assistant_audio:
                    with self.rt.db.session.begin() as session:
                        session.get(Message, assistant_id).audio_path = self.rt.audio.resolve(generated).name
                    result["assistant"]["audio_url"] = self.rt.audio.url(generated)
                should_play = self.rt.config.active.conversation.auto_play_tts if play is None else play
                if should_play:
                    self._stage(State.PLAYING, "playback_ms", timing, self.rt.player.play, generated)
            result["success"] = True
        except Exception as exc:
            logger.exception("Pipeline failed")
            error = exc if isinstance(exc, ServiceError) else ServiceError("处理失败，请查看 logs/app.log", 500)
            result["error"] = str(error)
        finally:
            for path, keep in ((audio_path, self.rt.config.active.conversation.keep_user_audio),
                               (generated, self.rt.config.active.conversation.keep_assistant_audio)):
                if path and not keep:
                    try:
                        with self.rt.db.session() as session:
                            name = self.rt.audio.resolve(path, must_exist=False).name
                            referenced = session.scalar(select(Message.id).where(Message.audio_path == name).limit(1))
                        if referenced is None:
                            self.rt.audio.delete(path)
                    except Exception:
                        logger.exception("Audio cleanup failed")
            timing["total_ms"] = round((time.monotonic() - started) * 1000) + recording_ms
            try:
                with self.rt.db.session.begin() as session:
                    run = PipelineRun(conversation_id=conversation_id if valid_conversation else None,
                                      success=result["success"], result=result)
                    session.add(run)
                    session.flush()
                    result["run_id"] = run.id
            except Exception:
                logger.exception("Cannot persist pipeline result")
                error = error or ServiceError("Pipeline 结果保存失败，请检查数据库", 503)
                result.update(success=False, error=str(error))
            self.last_result = result
        if error:
            self.change(State.ERROR, str(error), timing=timing)
            error.result = result
            raise error
        self.change(State.IDLE, "Ready", timing=timing)
        return result

    def start_recording(self, seconds: int | None = None) -> dict:
        with self.record_lock:
            if not self.gate.acquire(blocking=False):
                raise ServiceError("系统正忙，不能开始录音", 409)
            try:
                filename = self.rt.recorder.start(seconds)
                self.recording_active = True
                self.active_recording_id = filename.removesuffix(".wav")
                self.change(State.RECORDING, "正在使用树莓派麦克风录音", recording_id=self.active_recording_id)
                return {"recording_id": self.active_recording_id,
                        "max_record_seconds": seconds or self.rt.config.active.audio.max_record_seconds}
            except Exception:
                self.change(State.ERROR, "无法开始录音，请查看麦克风配置")
                self.gate.release()
                raise

    def stop_recording(self, recording_id: str | None = None) -> dict:
        with self.record_lock:
            if not self.recording_active:
                if recording_id and recording_id in self.recordings:
                    return self.recordings[recording_id]
                raise ServiceError("录音尚未开始", 409)
            if recording_id and recording_id != self.active_recording_id:
                raise ServiceError("录音 ID 与当前任务不一致", 409)
            try:
                result = self.rt.recorder.stop()
                self.recordings[result["recording_id"]] = result
                while len(self.recordings) > 100:
                    self.recordings.pop(next(iter(self.recordings)))
                self.last_recording = result
                self.change(State.IDLE, "录音完成", recording=result)
                return result
            except Exception:
                logger.exception("Recording failed")
                self.change(State.ERROR, "录音失败，请检查麦克风或重新录音")
                raise
            finally:
                self.recording_active = False
                self.active_recording_id = None
                self.gate.release()

    def check_recording(self) -> None:
        # Stop is serialized with explicit requests; a completed ID makes the race idempotent.
        with self.record_lock:
            recording_id = self.active_recording_id if self.recording_active else None
            finished = recording_id and self.rt.recorder.finished()
        if finished:
            try:
                self.stop_recording(recording_id)
            except Exception:
                logger.exception("Automatic recording stop failed")

    def voice(self, conversation_id: int, recording_id: str | None = None,
              audio_path: str | None = None, play: bool | None = None) -> dict:
        with self.exclusive():
            recording_ms = 0
            if recording_id:
                recording = self.recordings.get(recording_id)
                if recording is None:
                    raise ServiceError("录音 ID 不存在或服务已重启，请从已有 WAV 中选择", 404)
                audio_path, recording_ms = recording["filename"], recording["recording_ms"]
            path = self.rt.audio.validate_wav(audio_path, require_stt=True)
            return self._run(conversation_id, "", True, play, str(path), recording_ms)

    def diagnostic(self, state: State, function, *args) -> dict:
        with self.exclusive():
            started = time.monotonic()
            self.change(state)
            try:
                output = function(*args)
                elapsed = round((time.monotonic() - started) * 1000)
                self.change(State.IDLE, "Ready")
                return {"output": output, "latency_ms": elapsed}
            except Exception:
                logger.exception("Diagnostic failed")
                self.change(State.ERROR, "测试失败，请查看页面错误信息及日志")
                raise

    def full_test(self, conversation_id: int) -> dict:
        with self.exclusive():
            with self.rt.db.session() as session:
                get_conversation(session, conversation_id)
            self.change(State.RECORDING, "全流程测试：录音 5 秒")
            try:
                self.rt.recorder.start(5)
                time.sleep(min(5, self.rt.config.active.audio.max_record_seconds))
                recording = self.rt.recorder.stop()
            except Exception:
                self.change(State.ERROR, "全流程录音失败")
                raise
            return self._run(conversation_id, "", True, True,
                             str(self.rt.audio.resolve(recording["filename"])), recording["recording_ms"])
