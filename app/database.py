import logging
from pathlib import Path
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from .models import Base, PromptProfile

DEFAULT_PROMPT = """你是运行在 Raspberry Pi 上的本地中文语音助手。

请使用自然、简洁、适合口语播放的中文回答用户。

除非用户明确要求详细说明，否则优先将回答控制在 2～4 句话。

因为你的回答会通过语音合成播放，请避免不必要的 Markdown 表格、复杂代码块、长列表以及不适合朗读的格式。"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", hide_parameters=True, connect_args={"check_same_thread": False, "timeout": 10})
        event.listen(self.engine, "connect", self._configure)
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _configure(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.session.begin() as session:
            if session.scalar(select(PromptProfile.id).where(PromptProfile.is_default.is_(True))) is None:
                session.add(PromptProfile(name="默认中文助手", content=DEFAULT_PROMPT, is_default=True))
        logging.getLogger("localchat.database").info("Database initialized")
