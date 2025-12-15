JAVTransl
========

JAVTransl 可以自动从日语视频（你懂的）中生成中文字幕

准备工作
--------

1. 前往 [whisper-standalone-win 项目发布页](https://github.com/Purfview/whisper-standalone-win/releases)，下载最新的 Windows 版本。
2. 将压缩包中的 `Faster-Whisper-XXL` 目录解压后直接放入本程序所在的文件夹，保持目录结构完整。
3. 安装并配置 [LM Studio](https://lmstudio.ai/)，下载 `sakura-galtransl-7b-v3.7` 模型。
4. 在 LM Studio 中加载该模型并启用 HTTP Server（API 调用）。(默认设置即可：http://127.0.0.1:1234，无需API)

使用方法
--------

1. 将需要处理的视频文件拖入程序文件列表中
2. 点击“开始处理”：
   - 使用 Faster-Whisper-XXL 识别音频并生成 SRT 字幕；
   - 调用 LM Studio 提供的 `sakura-galtransl-7b-v3.7` 模型通过 HTTP 接口把字幕翻译成中文。
3. 在视频原目录中获取最终的中文字幕文件。
4. 翻译字幕功能可以直接将日文字幕翻译成中文


Release里面有打包好的，开箱即用版本，点击“运行.bat”启动


代码由AI生成