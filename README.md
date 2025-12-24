JAVTransl
========

JAVTransl 可以自动从日语视频（你懂的）中生成中文字幕

准备工作
--------

1. 获取本项目文件：
   - Release 页面下载后解压；
   - 或者直接下载源码 / 使用 `git clone https://github.com/thezeromr/JAVTransl.git`。
2. 双击 “运行.bat”，会自动安装uv和项目依赖(如果出错，可在终端执行：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`)
5. 安装并配置 [LM Studio](https://lmstudio.ai/)，下载 `sakura-galtransl-7b-v3.7` 模型。
6. 在 LM Studio 中加载该模型并启用 HTTP Server（API 调用），默认设置即可（http://127.0.0.1:1234， 无需 API Key）。

第一次运行的时候，faster-whisper需要下载模型，可能启动时间会比较久

运行程序
--------

在项目根目录打开终端并执行 `uv run python main.py`。
或双击 “运行.bat”


使用方法
--------

1. 将需要处理的视频文件拖入程序文件列表中
2. 点击“开始处理”：
   - 使用 faster-whisper 识别音频并生成 SRT 字幕；
   - 调用 LM Studio 提供的 `sakura-galtransl-7b-v3.7` 模型通过 HTTP 接口把字幕翻译成中文。
3. 在视频原目录中获取最终的中文字幕文件。
4. 翻译字幕功能可以直接将日文字幕翻译成中文


代码由AI生成
