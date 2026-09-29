from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConversationCreate(InputModel):
    title: str = Field("新对话", min_length=1, max_length=200)
    system_prompt_id: int | None = Field(None, gt=0)


class ConversationUpdate(InputModel):
    system_prompt_id: int = Field(gt=0)


class PromptInput(InputModel):
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=12000)
    is_default: bool = False


class ChatInput(InputModel):
    conversation_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=8000)
    synthesize: bool = True
    play: bool | None = None


class VoiceInput(InputModel):
    conversation_id: int = Field(gt=0)
    recording_id: str | None = Field(None, min_length=1, max_length=200)
    audio_path: str | None = Field(None, min_length=1, max_length=1000)
    play: bool | None = None

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.recording_id) == bool(self.audio_path):
            raise ValueError("请提供 recording_id 或 audio_path，两者选一")
        return self


class AudioInput(InputModel):
    audio_path: str = Field(min_length=1, max_length=1000)


class TextInput(InputModel):
    text: str = Field(min_length=1, max_length=8000)
