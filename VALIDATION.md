# 本次开发验证记录

日期：2026-09-29。开发目录：`/Users/zbq/code/chat-on-pi`。

## 环境检查

- Mac，Python 3.13.0。开始时目录为空，无已有代码被覆盖。
- 未找到 arecord、aplay、树莓派的 Whisper executable/model，符合 Mac 开发环境现状。
- 存在 `/usr/local/bin/ollama` 命令，`127.0.0.1:11434` API 未运行。
- 初始 Python 环境无项目依赖和 Piper。已创建本项目 `.venv`，安装 Mac 开发和测试依赖；Piper 依赖按 Linux 平台条件安装。
- 没有修改、移动或删除任何外部 Whisper/Piper/Ollama 模型或配置，也没有连接树莓派或安装 systemd。

## 分阶段检查

| 阶段 | 检查 | 结果 |
|---|---|---|
| 1 骨架 | FastAPI lifespan、SQLite 建表、默认 Prompt、Health API | 通过；硬件缺失时 degraded |
| 2 服务 | 独立服务导入、Whisper 输出解析、Piper 缺失时降级启动 | 通过 |
| 3 文字 | 两轮聊天、结构化上下文、持久化、标题 | 通过，Ollama 模拟响应 |
| 4 语音 | STT→LLM→TTS→播放、音频下载、错误恢复 | 通过，模型/播放使用模拟服务 |
| 5 页面 | Chat / Settings / Debug、CSS、JavaScript HTTP 加载 | 通过 |
| 6 实时 | WebSocket 推送、断开/重连、跨站写请求保护 | 通过 |
| 7 交付 | Python 编译、pytest、TCP HTTP 验收、实际 run.py、pip check | 通过，详情见下文 |

## 实际执行

1. `python -m compileall -q app run.py scripts`：通过。
2. `python -m pytest -q`：**60 passed**。无需真实音频硬件或模型。
3. macOS JavaScriptCore（osascript）对四个前端 JS 文件执行 `new Function(source)` 语法检查：通过。
4. `python scripts/smoke_http.py`：启动真实 Uvicorn 进程和本地模拟 Ollama HTTP server，通过 TCP 访问 Health、三个页面和静态文件，创建对话，完成两轮文字聊天，检查 4 条历史消息与请求上下文，连接 WebSocket，停止进程后重新打开 SQLite 检查持久化：通过。
5. **实际执行 `.venv/bin/python run.py`**，监听默认 `127.0.0.1:8000` 可访问地址：Health 返回 HTTP 200、status=degraded、database=true；三个页面与静态资源 HTTP 200。创建临时对话，调用真实文字聊天 API，在 Ollama 未启动时返回预期 503，之后 Health 仍可响应。验证结束删除临时对话并停止进程。
6. `python -m pip check`：No broken requirements found。

测试还使用临时 Python 可执行程序模拟 arecord，**实际创建 Popen 子进程并发送 SIGINT**，确认正常结束、WAV 可读、进程已回收；覆盖自然达到上限、未按时结束的额外停止保护、重复录音和无录音时 stop 的情况。这不是实际 ALSA 或麦克风测试。

当前依赖组合在 pytest 中产生一条 Starlette 关于 TestClient 使用 httpx 的弃用提示，不影响测试结果；未额外引入另一套 HTTP 客户端。

## 本机验证依赖版本

```text
Python       3.13.0
FastAPI      0.141.1
Uvicorn      0.54.0
SQLAlchemy   2.1.1
Jinja2       3.1.6
PyYAML       6.0.3
httpx        0.28.1
pydantic     2.13.5
websockets   16.1.1
pytest       9.1.1
```

这些是 Mac 已测试版本，不是 Raspberry Pi 的依赖锁。树莓派部署后请执行 `pip check` 和 pytest，并保留满足 requirements 范围的现有 Piper 环境。

## 仍需树莓派人工验证

- [ ] `arecord -D plughw:0,0` 真实录音、音量、背景噪声、USB 卡号稳定性。
- [ ] 真实 `whisper-cli` / ggml-tiny 中文转录、模型参数兼容性与耗时。
- [ ] Ollama qwen2.5:0.5b 真实推理、多轮上下文、CPU/内存和耗时。
- [ ] 现有 Piper 包和中文 ONNX/JSON 模型的 Python API 初始化、发音与耗时。
- [ ] `aplay` 的输出设备、音量和本机扬声器播放。
- [ ] 浏览器里实际点击、音频播放、手机布局与录音按钮体验；已验证 HTTP 加载和 JS 语法，未做浏览器视觉/交互自动化。
- [ ] 完整真实语音链路和各阶段耗时。
- [ ] 选择安装 systemd 后，重启树莓派确认开机启动和 audio 设备权限。

真实硬件验收步骤、依赖检查和排错命令见 README。此次验证完成后没有留下后台 Uvicorn 或模拟 Ollama 进程。
