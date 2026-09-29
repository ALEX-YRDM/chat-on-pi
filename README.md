# LocalChat Voice Assistant

运行于 Raspberry Pi 5 的单用户、本地中文半双工语音助手。Mac 用于开发和不依赖硬件的测试；Linux 树莓派负责 ALSA 录音/播放和真实模型推理。

```text
树莓派麦克风 → arecord → 16kHz mono PCM WAV
                         ↓
                    WhisperService (whisper-cli)
                         ↓
SQLite 历史 + Prompt → OllamaService (HTTP /api/chat)
                         ↓
                    PiperService (常驻 Python API)
                         ↓
                 WAV → AudioPlayer (aplay)
                    └→ 浏览器 HTTP 音频播放器
```

项目不会移动、修改、编译 whisper.cpp，不会自动下载模型，不会自动安装 systemd 服务。没有 Node/npm、Docker、前端框架、云 API、登录系统或后台任务队列。

## 1. 环境与目录

需要 **Python 3.11+**（建议 Raspberry Pi OS 64-bit / Python 3.11 或更新版本）、ALSA、已经可用的 whisper.cpp、Ollama、Piper 中文模型。保留树莓派已有的 `/home/zbq/localchat/.venv` 和模型文件。

```text
localchat/
├── app/
│   ├── main.py                # 应用工厂、生命周期、异常处理
│   ├── config.py              # YAML 校验与原子保存
│   ├── logging_setup.py       # console + 轮转文件日志
│   ├── database.py / models.py
│   ├── repository.py          # 对话读取、历史裁剪、标题生成
│   ├── schemas.py / dependencies.py
│   ├── runtime.py             # 服务实例，一个进程一份
│   ├── pipeline.py            # 半双工状态、互斥、耗时、结果保存
│   ├── audio_store.py         # 音频命名、WAV 校验、安全路径
│   ├── status.py / security.py / errors.py
│   ├── routes/                # chat/audio/conversations/settings/debug/health/pages/websocket
│   └── services/              # recorder/whisper/ollama/piper/audio_player/health/process
├── templates/                 # Jinja2 页面
├── static/css/ + static/js/    # 原生 CSS 和 JavaScript
├── data/localchat.db           # 首次启动创建；SQLite WAL
├── data/audio/                # 全部运行时 WAV
├── logs/app.log               # 2 MB × 4 个轮转文件
├── tests/                     # pytest，无硬件要求
├── scripts/smoke_http.py       # 真实 Uvicorn + 模拟 Ollama HTTP 的隔离验收
├── config.yaml
├── requirements.txt / requirements-dev.txt
├── run.py
└── localchat.service
```

路径基于项目文件的位置解析，不依赖 shell 当前目录。默认部署目录 `/home/zbq/localchat`，外部 Whisper 路径始终是配置中的绝对路径。

## 2. 从 Mac 传到树莓派

首次部署前，先在树莓派检查已有内容：

```bash
ssh zbq@raspberrypi.local 'ls -la /home/zbq/localchat'
```

在 Mac 的本项目目录执行以下**首次合并**命令：保留远端已有文件，不传 Mac 的 virtualenv、数据库、日志、模型，也不删除远端文件。

```bash
rsync -av --ignore-existing \
  --exclude '.venv/' --exclude '.git/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude 'data/' --exclude 'logs/' \
  --exclude '*.onnx' --exclude '*.onnx.json' \
  ./ zbq@raspberrypi.local:/home/zbq/localchat/
```

如果远端原有同名代码或 config.yaml，`--ignore-existing` 会保留它；请先备份和比较，再合并需要的内容。后续更新代码可以去掉 `--ignore-existing`，但增加 `--exclude 'config.yaml'`，继续排除 `.venv/`、`data/`、`logs/` 和模型；不要使用 `--delete`。

## 3. 安装依赖

树莓派已有 `.venv` 时直接激活，**不要重新创建或删除它**：

```bash
cd /home/zbq/localchat
source .venv/bin/activate
python --version
python -m pip install -r requirements.txt
python -m pip check
```

如果是全新目录且还没有虚拟环境，才执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

仅当 ALSA 工具缺失时：

```bash
sudo apt install alsa-utils
```

`requirements.txt` 在 Linux 安装 `piper-tts>=1.3,<2`；Mac 自动跳过 Piper，可运行界面、数据库、文字聊天和模拟测试。安装器不会强制升级已经满足版本范围的包。Piper Python API 使用 `PiperVoice.load` / `synthesize_wav`；若已验证的旧环境无法使用 API，可显式选择 `piper.backend: cli` 保留命令调用方式。

## 4. 先单独验证四条链路

### 麦克风 / 扬声器

```bash
command -v arecord
command -v aplay
arecord -l
arecord -L
aplay -l
mkdir -p /home/zbq/localchat/data/audio
arecord -D plughw:0,0 -f S16_LE -r 16000 -c 1 -d 5 \
  /home/zbq/localchat/data/audio/manual_mic.wav
aplay /home/zbq/localchat/data/audio/manual_mic.wav
```

输入默认 `plughw:0,0`，输出默认 `default`。页面上的麦克风按钮控制**树莓派连接的麦克风**，不是 Mac/手机浏览器的麦克风；因此不需要浏览器麦克风权限或 HTTPS。设备编号可能在插拔 USB 后改变，请用 `arecord -l` 核对。

### Whisper.cpp

```bash
test -x /home/zbq/whisper.cpp/build/bin/whisper-cli
test -f /home/zbq/whisper.cpp/models/ggml-tiny.bin
/home/zbq/whisper.cpp/build/bin/whisper-cli \
  -m /home/zbq/whisper.cpp/models/ggml-tiny.bin \
  -f /home/zbq/localchat/data/audio/manual_mic.wav -l zh -t 4
```

项目使用同一个 CLI，并增加 `-otxt -of <唯一临时前缀>`，从纯文本文件取结果并删除该文件；兼容回退解析仅接受带时间戳的转录行。模型信息、日志、时间戳和性能统计不会进入对话。路径不依赖 `cd whisper.cpp`。

### Ollama

```bash
command -v ollama
ollama list
curl --max-time 5 http://127.0.0.1:11434/api/tags
curl --max-time 180 http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"你好"}],"stream":false}'
```

如果 API 未启动，检查已有 Ollama 服务；需要手动启动时执行 `ollama serve`。只有模型不存在时才按需执行 `ollama pull qwen2.5:0.5b`。项目从不通过 subprocess 调用 `ollama run`。

### Piper

```bash
cd /home/zbq/localchat
source .venv/bin/activate
python -c 'from piper import PiperVoice; print("Piper import OK")'
python -m piper -m zh_CN-huayan-medium \
  -f /home/zbq/localchat/data/audio/manual_piper.wav \
  -- '你好，我是运行在树莓派五上的本地语音助手。'
aplay /home/zbq/localchat/data/audio/manual_piper.wav
```

CLI 支持 voice 名称，不代表 Python API 可以直接用名称加载。默认 API 查找：

```text
/home/zbq/localchat/zh_CN-huayan-medium.onnx
/home/zbq/localchat/zh_CN-huayan-medium.onnx.json
```

如果你现有模型在其他位置，请将 **已有 .onnx 的绝对路径** 填入 `piper.model_path`，不移动/删除模型；配套 JSON 应为同路径加 `.json`。可用 `find /home/zbq -name 'zh_CN-huayan-medium.onnx' 2>/dev/null` 查找。如果确认尚未下载，可自行在项目目录运行 `python -m piper.download_voices zh_CN-huayan-medium`；应用本身不执行下载。

模型在启动时加载一次，后续请求复用。若 API 初始化失败，服务仍启动，Health 提示原因，取消主页“生成语音”即可单独测试文字聊天。临时 `backend: cli` 使用当前 virtualenv 的 Python、固定项目 cwd 和你已验证的命令；它会每次加载模型，性能较低。CLI 模式 Health 只确认 package 可导入，真实可用性以 Piper Test 为准。

## 5. 配置

配置来源只有 `config.yaml`，不叠加数据库 settings 表。`LOCALCHAT_CONFIG=/absolute/path/config.yaml` 可以选择另一个配置文件（不改变 data/logs 的位置）。

| 配置 | 默认 / 含义 |
|---|---|
| `app.host / port` | `0.0.0.0:8000` |
| `audio.input_device` | `plughw:0,0` |
| `audio.sample_rate / channels / format` | 默认 `16000 / 1 / S16_LE`；录音参数可改为 8000–48000Hz、1–2 声道，格式固定 S16_LE |
| `audio.max_record_seconds` | 30，范围 1–120；达到上限自动停止并回收进程 |
| `audio.playback_device` | `default` |
| `whisper.executable / model` | 你提供的 `/home/zbq/whisper.cpp/...` 绝对路径 |
| `whisper.language / threads` | `zh / 4`，线程范围 1–8 |
| `whisper.timeout_seconds` | 120 |
| `ollama.base_url / model` | `http://127.0.0.1:11434 / qwen2.5:0.5b` |
| `ollama.temperature` | 0.7，范围 0–2 |
| `ollama.context_message_limit` | 最近 10 条 user/assistant 消息，范围 0–100 |
| `ollama.timeout_seconds` | 180；连接超时 5 秒 |
| `piper.voice` | `zh_CN-huayan-medium` |
| `piper.model_path` | 留空则使用项目下 `<voice>.onnx`，否则使用绝对路径 |
| `piper.backend` | `api`，可选 `cli` |
| `piper.timeout_seconds` | CLI 超时 120 秒；不对进程内 Python API 设置伪超时 |
| `conversation.auto_play_tts` | true，控制树莓派本机播放；浏览器仍手动播放 |
| `conversation.keep_user_audio` | true，保留语音消息的 WAV |
| `conversation.keep_assistant_audio` | true，保留助手 WAV 供浏览器回放 |

语音 Pipeline 的输入仍严格要求 16000Hz、单声道、16-bit PCM。本版不自动转码；修改采样率/声道可用于单独的录音调试，识别前需恢复默认参数并重新录音。

Web Settings 保存会校验类型、范围、路径、设备字符串和 URL，原子替换 YAML。**所有 YAML 修改重启后统一生效**，页面同时提示待重启状态，避免录音/推理中切换配置造成状态不一致。保存会重新序列化 YAML，不保留注释。路径允许暂时不存在以便在 Mac 配置；实际可用性由 Health 和各服务检查。

Prompt Profile 存 SQLite、立即生效。新对话绑定当时的默认 Prompt；更改默认不会改变已有对话。主页 Prompt 下拉框可以修改当前对话绑定。编辑一个 Profile 会影响所有引用它的对话；默认或被引用的 Profile 不允许删除。

## 6. 启动和页面

```bash
cd /home/zbq/localchat
source .venv/bin/activate
python run.py
```

也可以：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

必须使用 **一个 worker**，保证只有一份 Piper 模型、录音进程和 Pipeline 互斥状态。不要在硬件运行时开启 `--reload`；调试 Python 代码后手动重启即可。使用 Uvicorn 命令时监听地址/端口由该命令指定，`run.py` 则读取 YAML。

启动日志包含项目名、Database initialized、Piper initialized（或具体失败原因）、Ollama reachable（或 unavailable）以及监听地址。没有硬件时不虚报初始化成功。

- 主页：`http://raspberrypi.local:8000/`
- 调试：`http://raspberrypi.local:8000/debug`
- 设置：`http://raspberrypi.local:8000/settings`
- API 文档：`http://raspberrypi.local:8000/docs`
- 健康检查：`http://raspberrypi.local:8000/api/health`

mDNS 不可用时，将 `raspberrypi.local` 换成树莓派 IP。Mac 本机预览使用 `http://127.0.0.1:8000`；缺少 ALSA/Whisper/Piper 时 Health 为 `degraded`，依然可以浏览 UI。Mac 的真实文字聊天需要可达的 Ollama API。

## 7. 首次验收顺序

1. 打开 `/debug`，检查 Database、Whisper 路径、Ollama 模型和 Piper 初始化状态。
2. Ollama Test 输入“你好”，确认真实模型回答。
3. Piper Test 合成中文，浏览器播放，再点击 Play on Raspberry Pi。
4. Microphone Test 录音 5 秒，浏览器回听；Whisper Test 选择该 WAV，确认中文识别。
5. 主页新建对话，先取消“生成语音”测试文字，再勾选测试合成和自动播放。
6. 点击开始录音，说“给我介绍一下树莓派五”，点击停止；检查转录、回答、两段音频和各阶段耗时。
7. 刷新页面确认历史仍在。测试删除一个测试对话，以及修改 Prompt、设置模型。
8. Full Pipeline Test 会新建“全流程测试”对话，录音 5 秒并**显式播放**，不受 auto_play_tts=false 限制。

录音是开始/停止式，`arecord -d` 只作为上限保护。正常停止发送 SIGINT 以写完 WAV 头，5 秒未结束则 kill 并 wait 回收。自动到时由后台检查器收尾；主页仍打开时自动进入语音处理。关闭浏览器不会无限录音，达到上限仍会停止，但不会自动发起新对话推理。

## 8. API 摘要

| 方法 | 地址 | 用途 |
|---|---|---|
| GET / POST | `/api/conversations` | 列表 / 新建 |
| GET / PUT / DELETE | `/api/conversations/{id}` | 详情 / 绑定 Prompt / 删除 |
| GET | `/api/conversations/{id}/messages` | 完整消息历史（推理历史另行裁剪） |
| GET / POST | `/api/prompts` | 列表 / 新建 |
| PUT / DELETE | `/api/prompts/{id}` | 修改（含 is_default）/ 删除 |
| GET / PUT | `/api/settings` | 查看 saved/active / 保存完整配置对象 |
| POST | `/api/chat` | `conversation_id, message, synthesize, play?` |
| POST | `/api/record/start` | 开始树莓派录音，返回 recording_id |
| POST | `/api/record/stop?recording_id=...` | 停止录音，返回 WAV；带 ID 可查询已自动完成的录音 |
| POST | `/api/voice/process` | `conversation_id, recording_id 或 audio_path, play?` |
| GET | `/api/audio` | 最近 100 个 WAV 文件 |
| GET | `/api/audio/{filename}` | WAV 文件响应，支持浏览器播放器 |
| POST | `/api/audio/play` | `audio_path`，本机播放 |
| GET | `/api/health`、`/api/status` | 服务健康 / Pipeline 当前状态与最近结果 |
| WebSocket | `/ws/status` | 状态变化实时推送，断线自动重连，HTTP 轮询兜底 |
| POST | `/api/debug/record` | 录音 5 秒 |
| POST | `/api/debug/whisper` | `audio_path` |
| POST | `/api/debug/ollama`、`/api/debug/piper` | `text` |
| POST | `/api/debug/pipeline?conversation_id=1` | 全流程录音测试 |
| GET | `/api/debug/runs` | 最近 20 次 Pipeline 结果 |

最小文字 API 验证（先查看创建响应里的 id）：

```bash
curl -X POST http://127.0.0.1:8000/api/conversations \
  -H 'Content-Type: application/json' -d '{}'
curl --max-time 200 http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id":1,"message":"你好","synthesize":false}'
```

`play` 未提供时读取 `auto_play_tts`；`synthesize=false` 会跳过 TTS 和播放。音频返回 URL，绝不 Base64 塞进 JSON。输入文件名或绝对路径均被限制在本项目 `data/audio`；不能读取其他目录，不允许路径穿越和符号链接。

## 9. 状态、失败和持久化

状态：`idle → recording → transcribing → thinking → synthesizing → playing → idle`。文字请求跳过录音/STT，不合成时也跳过 TTS/播放。失败进入 `error`，释放互斥锁后可以继续下一次请求，无需重启。

单用户半双工：录音、推理、合成、播放、Debug 操作共享一把互斥锁。忙时返回 409，数据库删除/Prompt 修改也不会与推理交错。外部模型调用在工作线程进行，不阻塞 WebSocket；没有为每个模型额外启动常驻线程池。

- 用户消息在 LLM 前提交，助手文本在 TTS 前提交。TTS/播放失败不会丢失已得到的文本。
- 失败 API 返回 `detail`，Pipeline 已开始时还返回 `result`（含部分文本和耗时），前端刷新已保存的消息。不要为了重试播放而重复发送整条消息，可用已有音频播放器或播放 API。
- 每次 Pipeline 的成功/失败结果保存 `pipeline_runs` 表。`recording_ms/stt_ms/llm_ms/tts_ms/playback_ms/total_ms` 使用单调时钟。Total 包括本次录音和实际处理时间；手工提供已有 WAV 时 recording_ms=0，不包括用户停顿后才点击处理的等待时间。
- 消息 `latency_ms`：用户为 STT 耗时，助手为 LLM 耗时；完整分阶段数据在 PipelineRun。
- `keep_*_audio=false` 时处理结束后删除相应临时音频，消息不保存音频 URL。助手音频可以先本机播放再删除；无法同时要求不保留 WAV 又在刷新后回放。其他历史消息已引用的输入 WAV 不会被误删。
- Debug 生成、未处理录音、识别失败且开启保留的 WAV 留在 data/audio，方便排查；没有后台磁盘清理任务。定期检查磁盘并只手工清理不再需要的诊断音频。
- 删除对话级联删除消息和 PipelineRun，并删除不再被其他消息引用的音频。数据库提交成功但文件删除失败时日志记录错误，文件可能残留；重新启动服务不影响其他对话。
- 录音 ID 最近 100 条保存在内存中，重启后可从 Debug 选择已有 WAV，历史消息和音频路径不受影响。
- SQLite 初始化建表，不引入迁移框架。升级表结构前停服务并备份 data（含 WAL 文件）；建议关闭服务后备份整个 data 目录。

## 10. 日志与安全范围

```bash
tail -f /home/zbq/localchat/logs/app.log
```

日志记录阶段、耗时、文件名和异常堆栈；正常日志不写用户语音文本、Prompt 或模型回答。Whisper 只记录字符数；SQLAlchemy 隐藏 SQL 参数；Piper CLI 超时不会把包含文本的命令参数写入日志。请仍将日志和数据库作为本地私有文件保存。

所有外部命令使用参数数组，无 `shell=True`。Whisper 可执行路径必须为绝对路径且文件名为 `whisper-cli`；配置不会把网页输入当作 shell 语句。API 写请求要求 JSON（空请求体除外），限制 128 KB，拒绝浏览器跨站修改和跨站 WebSocket。页面文本用 `textContent` 展示，防止模型输出被执行为 HTML。

这是可信 LAN 内的单用户工具，**没有登录和权限系统**；不要端口转发到公网。能访问服务的 LAN 客户端可以读取对话、改变配置和控制麦克风。浏览器同源检查并不等于身份认证。Health 只做轻量枚举/文件/API/数据库检查，不保证真实推理或音频硬件一定可用。

## 11. 测试

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m compileall -q app run.py
python -m pytest -q
python scripts/smoke_http.py
```

pytest 覆盖配置校验和原子保存、数据库默认 Prompt 与持久化、上下文裁剪、Whisper 解析、Ollama HTTP 请求/错误、API、Prompt 管理、音频路径与符号链接、保留策略、半双工并发、失败后恢复、WebSocket 断线，以及使用临时可执行程序测试 SIGINT 停止与自然到时回收。它不使用真实麦克风或模型，也不修改你的正式数据库。

`smoke_http.py` 使用临时目录启动真实 Uvicorn 和本地模拟 Ollama HTTP 服务，再通过 TCP 检查 Health、页面、静态资源、新建对话、两轮文字聊天与数据库重开持久化、WebSocket，最后停止进程并清理临时目录。它证明 HTTP 链路可运行，**不能证明真实模型质量或树莓派音频硬件可用**。

本次 Mac 开发环境验证记录见 `VALIDATION.md`。

## 12. systemd 开机启动（手动选择安装）

先确保在终端已完成硬件验收，再安装示例：

```bash
sudo cp /home/zbq/localchat/localchat.service /etc/systemd/system/localchat.service
sudo systemctl daemon-reload
sudo systemctl enable localchat
sudo systemctl start localchat
sudo systemctl status localchat
journalctl -u localchat -f
```

保存 YAML 后：`sudo systemctl restart localchat`。

停止/取消自启：

```bash
sudo systemctl stop localchat
sudo systemctl disable localchat
```

服务使用 zbq 用户、现有 virtualenv、audio 附加组、固定工作目录和一个 Uvicorn worker。`After=ollama.service` 只控制已有服务的启动顺序，不会安装 Ollama。如果你的系统并非使用这个 Ollama service 名称，可调整示例。

## 13. 常见问题

| 现象 | 检查与处理 |
|---|---|
| arecord / aplay 不存在 | 在树莓派安装 alsa-utils；Mac 无 ALSA，属于预期 |
| 设备不存在 / Device or resource busy | `arecord -l` 检查卡号，关闭其他占用麦克风的程序；查看 logs/app.log 的 arecord diagnostics |
| Permission denied | 检查 `id zbq`、`/dev/snd` 权限；需要时 `sudo usermod -aG audio zbq`，重新登录再测试 |
| stop 返回 409 | 尚未录音；自动结束后请带 start 返回的 recording_id 获取结果 |
| Whisper executable / model 不存在 | 使用配置中的绝对路径直接执行；检查执行权限和模型文件，不要改源码 |
| Whisper 空识别 / 超时 | 回听录音，检查声音大小；确认 16kHz 单声道 PCM；先用 tiny、4 线程，再按需增加超时 |
| Ollama 连接失败 | 检查 `curl .../api/tags` 与后台服务；模型应出现在 `ollama list` |
| Ollama HTTP 404 | 确认 model 精确名称，例如 `qwen2.5:0.5b` |
| Piper 初始化失败 | 确认当前 virtualenv 包版本、`.onnx` 和 `.onnx.json`，填写 model_path；必要时显式 backend: cli |
| Piper Python API 卡住 | 原生 API 没有安全线程取消；查看日志、单独复现并重启服务；需进程级超时可临时使用 CLI backend |
| 播放失败但有回答 | 文本已保存；检查 `aplay -l`、playback_device 和音量。用浏览器播放区分 TTS 与扬声器问题 |
| 数据库锁定 / 写入失败 | 只运行一个服务实例，检查目录权限和磁盘空间，不要对着同一数据库开多个 workers |
| 配置保存后没变化 | YAML 修改需要重启；Prompt 无需重启 |
| 浏览器无声音 | 浏览器不会自动播放；点消息里的播放器。本机自动播放指树莓派扬声器 |
| 503 / degraded | 先查看 /debug 的具体服务状态，再分别测试。单个组件不可用不代表 Web 服务无法使用 |
| 端口 8000 已占用 | 停止旧实例或更改 app.port；不要同时用手动启动和 systemd 启动同一项目 |

## 14. 后续方向

本版不实现 VAD、唤醒词、全双工、AEC、播放打断、流式推理、RAG 或多用户。建议先在树莓派记录真实 STT/LLM/TTS 延迟并稳定设备配置，再考虑 VAD 自动停止录音。独立 RecorderService、WhisperService、OllamaService、PiperService 和 AudioPlayer 可分别替换，Pipeline 保持编排职责，无需提前引入复杂框架。

实现接口参考：[Piper Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md)、[whisper.cpp CLI](https://github.com/ggml-org/whisper.cpp/blob/master/examples/cli/cli.cpp)、[Ollama Chat API](https://docs.ollama.com/api/chat)。
