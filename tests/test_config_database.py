from pathlib import Path
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.config import ConfigStore, ROOT, Settings
from app.database import Database
from app.models import PromptProfile, Conversation, Message
from app.repository import add_user, build_messages


def test_config_defaults_and_atomic_save(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text((ROOT / "config.yaml").read_text())
    store = ConfigStore(path)
    saved = store.load()
    assert saved.audio.input_device == "plughw:0,0"
    assert saved.whisper.executable.startswith("/home/zbq/whisper.cpp/")
    saved.ollama.model = "test:tiny"
    store.save(saved)
    assert store.load().ollama.model == "test:tiny"
    assert store.active.ollama.model == "qwen2.5:0.5b"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("section,key,value", [
    ("whisper", "executable", "/bin/sh"), ("whisper", "model", "relative.bin"),
    ("whisper", "threads", 0), ("audio", "max_record_seconds", 9999),
    ("audio", "input_device", "default;touch /tmp/unsafe"),
    ("audio", "sample_rate", 7999), ("ollama", "temperature", 99),
    ("ollama", "base_url", "file:///etc/passwd"),
    ("ollama", "base_url", "http://user:password@localhost:11434"),
    ("piper", "voice", "--bad" + ";"),
])
def test_config_validation(section, key, value):
    values = ConfigStore(ROOT / "config.yaml").active.model_dump()
    values[section][key] = value
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_default_prompt_and_persistence(tmp_path):
    path = tmp_path / "test.db"
    first = Database(path)
    first.initialize()
    first.initialize()
    with first.session() as session:
        profiles = session.scalars(select(PromptProfile)).all()
        assert len(profiles) == 1
        assert profiles[0].is_default
        assert "Raspberry Pi" in profiles[0].content
    first.engine.dispose()
    second = Database(path)
    second.initialize()
    with second.session() as session:
        assert len(session.scalars(select(PromptProfile)).all()) == 1
    second.engine.dispose()


def test_history_is_bounded_and_current_only_once(rt, conversation):
    with rt.db.session.begin() as session:
        conv = session.get(Conversation, conversation)
        for i in range(16):
            session.add(Message(conversation_id=conversation, role="user" if i % 2 == 0 else "assistant", content=str(i)))
        session.add(Message(conversation_id=conversation, role="system", content="do not use"))
        session.flush()
        messages = build_messages(session, conv, "new", 10)
        assert len(messages) == 12
        assert messages[0]["role"] == "system"
        assert [m["content"] for m in messages[1:-1]] == [str(i) for i in range(6, 16)]
        assert messages[-1] == {"role": "user", "content": "new"}
        assert len(build_messages(session, conv, "new", 0)) == 2


def test_first_message_title_and_custom_title(rt, conversation):
    with rt.db.session.begin() as session:
        conv = session.get(Conversation, conversation)
        add_user(session, conv, "这是一条超过二十个字符的用户输入用于测试标题生成规则")
        assert len(conv.title) == 20
        old = conv.title
        add_user(session, conv, "第二条")
        assert conv.title == old


def test_audio_parameters_are_configurable_for_diagnostics():
    values = ConfigStore(ROOT / 'config.yaml').active.model_dump()
    values['audio']['sample_rate'] = 44100
    values['audio']['channels'] = 2
    settings = Settings.model_validate(values)
    assert settings.audio.sample_rate == 44100
    assert settings.audio.channels == 2
