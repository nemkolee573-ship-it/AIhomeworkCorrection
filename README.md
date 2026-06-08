# AI 作业批改工作台

这是一个基于 `AI作业批改需求文档.md` 生成的本地 MVP。它不是纯演示页面，已经支持在浏览器中真实上传结构化文件、解析题目和学生作答、执行批改、生成班级分析并导出报告。

- 教师上传参考答案/评分规则文件。
- 上传学生作业文件。
- 自动批改客观题和基础计算题。
- 对作文、历史材料题、政治论述题、数学证明题等主观题做规则化辅助初评。
- 生成学生反馈和班级学情分析。
- 导出批改报告 JSON。

## 文件说明

```text
.
├── index.html                # 页面入口
├── styles.css                # 页面样式
├── app.js                    # 文件解析、批改规则、学情分析和交互逻辑
├── server.py                 # 本地 Web 服务和 OCR/PDF 解析接口
├── model_config.json         # 大模型结构化解析配置
├── .env.example              # 模型密钥配置模板
├── scripts/vision_ocr.swift  # macOS Vision OCR 脚本
├── sample_reference.json     # 示例参考答案/评分规则
├── sample_submissions.json   # 示例学生作业
├── sample_answer_card.txt    # 示例答题卡 OCR 文本
├── AI作业批改需求文档.md      # 产品需求文档
├── 技术文档.md               # 技术设计与开发逻辑说明
└── README.md                 # 运行说明
```

## 运行方式

### 方式一：直接打开

双击 `index.html` 即可在浏览器中打开。

### 方式二：启动本地服务（推荐）

在当前目录运行：

```bash
python3 server.py
```

然后访问：

```text
http://127.0.0.1:8011
```

如果 `8011` 端口被占用，可以换一个端口：

```bash
PORT=8020 python3 server.py
```

然后访问：

```text
http://127.0.0.1:8020
```

源码默认不内置访问密码，方便分享源码。需要临时公网分享时，请先在 [.env](./.env) 中配置访问密码：

```env
ACCESS_PASSWORD=请改成你的访问密码
```

如果不配置 `ACCESS_PASSWORD`，服务会正常运行，但不会出现访问密码页，不建议用于公网分享。

### 方式三：临时公网分享（Cloudflare Tunnel）

这种方式适合把本机正在运行的 MVP 临时分享给其他老师或同事试用。先启动本地服务：

```bash
python3 server.py
```

终端会显示类似：

```text
Serving AI grading MVP at http://127.0.0.1:8014
Public tunnel command: cloudflared tunnel --protocol http2 --url http://127.0.0.1:8014
```

复制第二行命令，在另一个终端运行：

```bash
cloudflared tunnel --protocol http2 --url http://127.0.0.1:8014
```

Cloudflare 会生成一个 `https://xxxx.trycloudflare.com` 公网链接。把这个链接发给别人，对方打开后输入你在 `.env` 中配置的 `ACCESS_PASSWORD` 即可使用。

如果你的电脑还没有安装 `cloudflared`，macOS 可以使用：

```bash
brew install cloudflared
```

注意：公网分享期间，上传解析会消耗你本机配置的模型额度。试用完成后，关闭运行 `cloudflared tunnel` 的终端即可停止公网访问。

## 当前可体验功能

- 上传参考答案/评分规则文件。
- 上传学生作业文件。
- 解析 JSON、CSV、TXT、MD。
- 解析 ZIP 中的多张 PNG/JPG/WEBP/PDF。
- 解析 PNG、JPG、WEBP、PDF 中的文字内容。
- 解析答题卡中的学生姓名、题号和作答内容。
- OCR 文本可编辑，修正后可以重新按“参考答案”或“学生作业”解析。
- 展示 OCR 准确性：平均置信度、低置信行数。
- 可选接入大模型，把凌乱 OCR 文本结构化为题号、题型和答案。
- 自动批改选择题、判断题、填空题、基础计算题。
- 辅助批改作文、历史材料题、政治论述题、数学证明题。
- 主观题会同时读取题目、评分点和学生答案，输出题目回应度和复核风险。
- 生成单个学生的得分、依据、反馈和教师复核点。
- 生成班级共性问题和复核队列。
- 导出 `ai-grading-report.json`。

## 快速试用

1. 打开页面。
2. 在“上传参考答案或评分规则”处选择 `sample_reference.json`。
3. 在“上传学生作业”处选择 `sample_submissions.json`。
4. 点击“运行批改”。
5. 在“批改结果”和“学情分析”中查看结果。

也可以直接点击页面右上角“载入示例文件”，再点击“运行批改”。

如果想测试答题卡场景：

1. 参考答案选择 `sample_reference.json`。
2. 学生作业选择 `sample_answer_card.txt`。
3. 点击“运行批改”。

如果多个学生的作业是图片/PDF，可以放进一个 ZIP 一次性上传。系统会按 ZIP 内每个文件拆分学生：

```text
李同学.png
王同学.png
张同学.pdf
```

如果图片里能 OCR 出 `姓名：xxx`，优先使用 OCR 姓名；否则使用文件名作为学生名。

## 上传文件格式

### 参考答案/评分规则 JSON

```json
[
  {
    "id": "q1",
    "subject": "数学",
    "type": "choice",
    "title": "下列计算正确的是？",
    "answer": "B",
    "score": 2
  },
  {
    "id": "q2",
    "subject": "语文",
    "type": "essay",
    "title": "那一刻，我长大了",
    "answer": "围绕一次具体经历，写出成长认识，体现责任、担当或自我变化。",
    "score": 50,
    "keywords": ["长大", "责任", "感受"],
    "rubric": ["中心明确", "事例具体", "结尾点题"]
  }
]
```

### 学生作业 JSON

```json
[
  {
    "student": "李同学",
    "answers": {
      "q1": "B",
      "q2": "我照顾生病的妈妈，第一次明白责任。"
    }
  }
]
```

### 答题卡文本 / OCR 格式

答题卡图片、PDF、ZIP 会先 OCR 成文本。建议答题卡版式尽量接近：

```text
姓名：李同学
1. B
2. 42
3. 我照顾生病的妈妈，第一次明白责任。

姓名：王同学
1. A
2. 42
3. 我写了一次比赛，虽然输了，但我有很多感受。
```

客观题会提取为 `q1=B`、`q2=42`；主观题会保留题号后的整段文字。

### CSV 格式

参考答案 CSV 表头建议：

```text
id,subject,type,title,answer,score,keywords,rubric
```

主观题必须尽量提供 `title`，也就是题目原文/材料/设问。系统会用它判断学生答案是否回应题目。没有题目时，主观题只做低置信评分点检查。

主观题如果有标准答案或参考答案，也可以写在 `answer` 字段。系统会按下面顺序辅助评分：

```text
先解析题目 title
    ↓
判断学生是否回应题目
    ↓
如果有 answer，结合标准答案/参考要点
    ↓
再结合 rubric / keywords 判断命中和遗漏
```

学生作业 CSV 表头建议：

```text
student,q1,q2,q3
```

### ZIP / 图片 / PDF 参考答案建议版式

为了让 OCR 更稳定，老师拍照或导出的 PDF 建议包含清晰的“参考答案”区域。参考答案可以是打印体，也可以是老师手写在试卷上的答案或评分点：

```text
参考答案
1. B
2. 42
3. 作文题：评分点：中心明确、事例具体、情感真实、结尾点题
4. 历史题：评分点：生产力提升、城市化发展、工人阶级形成、社会问题
```

如果一套试卷有多张图片，可以把它们放进一个 ZIP：

```text
paper-01.png
paper-02.png
paper-03.png
answer-page.png
```

系统会按 ZIP 内文件名排序后逐页 OCR，并合并识别结果。建议文件名按页码排序，例如 `01.png`、`02.png`、`03.png`。

学生作业 ZIP 的推荐组织：

```text
李同学.png
王同学.png
张同学.pdf
```

如果一个学生有多页作业，建议文件名包含学生姓名和页码：

```text
李同学-01.png
李同学-02.png
王同学-01.png
王同学-02.png
```

当前 MVP 会优先按 OCR 文本中的 `姓名：xxx` 合并；如果没有姓名，会按文件名分别作为学生记录。

第二步上传学生作业时，系统会使用 `target=submission` 的学生作答解析链路。单张或少量图片/PDF 会尝试视觉模型直接看图，输出学生姓名和 `answers`；如果是 50 个学生这类大 ZIP，系统会自动跳过视觉模型，改用 OCR 分段和文件夹/文件名合并，避免一次性传太多图片导致超时或接口异常。

如果第一步上传的参考答案只有答案/解析，没有题目，第二步上传学生试卷时会额外从学生试卷中补一次题目结构。因为同一批学生默认是同一套题，系统只从这次学生上传内容中抽取一次题目，不会对每个学生重复抽题；其余学生只解析题号和作答内容。

也支持“每个学生一个文件夹”的 ZIP：

```text
六年级一班作业/
├── 李同学/
│   ├── 01.png
│   └── 02.png
├── 王同学/
│   ├── 01.png
│   └── 02.png
└── 张同学/
    └── answer-card.pdf
```

这种结构下，系统会优先使用顶层学生文件夹名作为学生名，并把同一文件夹下的多页答案合并。

图片建议：

- 光线均匀，文字不要倾斜太多。
- 一页内尽量只放一张试卷或答案页。
- 中文和数字清晰可见。
- 手写参考答案尽量写在题号旁边或统一的“参考答案”区域，题号和答案之间留出空隙。
- 手写字母、数字和单位要尽量清楚，例如 `B`、`8`、`kg`、`cm²`。
- 主观题最好写“评分点/采分点/关键词”，不要只写“略”。
- 如果 OCR 后手写答案识别错误，或表格行列被打乱，可以在页面的“OCR 文本预览”中手动改成 `1. B`、`2. 42` 这种格式。简单客观题可点击“按参考答案重新解析”；复杂数学/主观题建议点击“用大模型重新解析当前文本”。
- 数学计算大题可以写成 `22(1). 2(a+1/2)^2-(2a+7/2)(a-1)`。支持直接输入或快捷插入 `1/2`、`√(x+1)`、`x^2`、`|x-3|`、`≤`、`≥`、`×`、`÷` 等表达。

## 大模型识别题号和答案

项目已经内置了大模型配置文件 [model_config.json](./model_config.json)。启动 `python3 server.py` 时会自动读取：

- `.env`
- `model_config.json`
- 系统环境变量

你只需要编辑项目里的 [.env](./.env)：

```text
OPENAI_API_KEY=你的真实模型密钥
```

把 `你的真实模型密钥` 替换成真实 key，再启动：

```bash
python3 server.py
```

### 使用兼容接口

如果你使用兼容 OpenAI Chat Completions 的其他服务，修改 `.env`：

```text
LLM_API_KEY=你的密钥 \
LLM_API_URL=https://你的服务/v1/chat/completions \
LLM_MODEL=你的模型名
CLOUD_LLM_TIMEOUT=600
```

或者直接改 [model_config.json](./model_config.json)：

```json
{
  "enabled": true,
  "api_url": "https://openrouter.ai/api/v1/chat/completions",
  "model": "你的模型名",
  "api_key_env": "LLM_API_KEY",
  "api_key": ""
}
```

不建议把真实密钥写进 `model_config.json` 的 `api_key` 字段，优先放在 `.env`。

云端模型解析 OCR 的等待时间由 `.env` 中的 `CLOUD_LLM_TIMEOUT` 控制，默认是 `600` 秒。位置在 [server.py](./server.py) 的 `get_cloud_timeout()`。

图片直传视觉模型默认复用 `LLM_API_KEY`、`LLM_API_URL`、`LLM_MODEL`。如果你的服务有单独视觉模型，可以在 `.env` 中配置 `VISION_LLM_MODEL`、`VISION_LLM_API_URL`、`VISION_LLM_API_KEY`。`VISION_MAX_IMAGES` 控制一次最多传几张图，默认 `6`。如果当前模型不支持图片输入，系统会自动回退到 OCR 文本解析。

性能优化默认不降低识别清晰度：PDF 仍按 `PDF_RENDER_SCALE=3.0` 渲染后传给视觉模型。`VISION_FIRST=true` 表示图片/PDF 在视觉模型可用时优先直接看图，避免先跑低置信 OCR；学生卷需要补题时会把“题目结构 + 学生作答”合并为一次视觉请求，减少重复等待。

阿里云百炼 Qwen 多模态可以单独作为视觉模型接入，例如：

```env
VISION_LLM_ENABLED=true
VISION_LLM_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
VISION_LLM_MODEL=qwen3.7-plus
VISION_LLM_API_KEY=你的百炼APIKey
VISION_MAX_IMAGES=4
VISION_FIRST=true
PDF_RENDER_SCALE=3.0
```

配置后可以打开下面地址验证图片输入链路是否可用：

```text
http://127.0.0.1:8011/api/vision-test
```

启用后，上传图片/PDF/ZIP 时会先提取文本并交给模型结构化。对于 `PNG/JPG/JPEG/WEBP` 图片，会优先尝试把原图直接发给视觉模型；对于 PDF，会先渲染前几页为图片；对于 ZIP，会抽取前几张图片或 PDF 页。视觉模型会结合题干、公式、图形和手写答案分析；如果视觉模型失败，再退回 OCR 文本链路。当前策略是：

```text
图片/PDF/ZIP 图片页 + 视觉模型可用
    ↓
视觉模型直接看图拆题、识别公式、图形和答案

视觉模型不可用
    ↓
OCR 文本 + 云端大模型解析

云端大模型不可用
    ↓
自动尝试本地 Ollama 模型

本地模型也不可用
    ↓
退回本地规则解析
```

### 本地模型兜底

如果希望断网或云端视觉模型不可用时仍能解析题号、答案和试卷图片，可以安装 Ollama，并拉取支持视觉输入的 Qwen 模型：

```bash
ollama pull qwen2.5vl:7b
ollama serve
```

项目默认会请求：

```text
http://127.0.0.1:11434/api/chat
```

默认本地模型配置在 [model_config.json](./model_config.json)：

```json
{
  "local_model": {
    "enabled": true,
    "provider": "ollama",
    "api_url": "http://127.0.0.1:11434/api/chat",
    "model": "qwen2.5vl:7b",
    "vision_enabled": true,
    "vision_model": "qwen2.5vl:7b"
  }
}
```

也可以通过 `.env` 覆盖：

```text
LOCAL_LLM_ENABLED=true
LOCAL_LLM_PROVIDER=ollama
LOCAL_LLM_API_URL=http://127.0.0.1:11434/api/chat
LOCAL_LLM_MODEL=qwen2.5vl:7b
LOCAL_VISION_ENABLED=true
LOCAL_VISION_MODEL=qwen2.5vl:7b
LOCAL_LLM_TIMEOUT=180
```

检查模型是否配置成功：

```text
http://127.0.0.1:8011/api/health
```

返回里的 `llm.configured` 为 `true` 就表示已配置。

验证当前实际会走云端、本地还是规则解析：

```text
http://127.0.0.1:8011/api/llm-test
```

返回里的 `effective` 会显示 `cloud`、`local` 或 `rule`。

## 当前版本边界

- 当前是本地 MVP，不包含后端数据库。
- 结构化文件在浏览器中读取；图片/PDF 会发送到本机 `server.py` 做 OCR。
- 当前批改默认为“云端大模型优先、本地 Ollama 兜底、规则解析保底”；配置 `OPENAI_API_KEY` 或 `LLM_API_KEY` 后优先调用云端模型。
- 当前 OCR 使用 macOS Vision，复杂手写、模糊图片和复杂版面可能识别不准。
- ZIP 中支持 `.png`、`.jpg`、`.jpeg`、`.webp`、`.pdf`、`.txt`、`.md`、`.csv`、`.json`，其他文件会跳过。
- 当前教师复核结果没有持久化到数据库。

## 后续开发方向

建议按以下顺序继续开发：

1. 接入后端文件存储和数据库。
2. 接入 OCR 和 PDF 解析。
3. 实现题目切分、题型识别、答案区域识别。
4. 实现教师确认答案映射。
5. 接入真实 AI 批改服务。
6. 增加教师复核结果保存。
7. 增加学生订正流程。
8. 增加班级学情分析和导出能力。

##ai作业批改/.env配置文件,复制以下需增加api##
OPENAI_API_KEY=“deepseek-v4-pro的apikey”

LLM_API_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-v4-pro

VISION_LLM_ENABLED=true
VISION_LLM_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
VISION_LLM_MODEL=qwen3.7-plus
VISION_LLM_API_KEY="qwen3.7-plus的apikey"
VISION_MAX_IMAGES=4
VISION_MAX_IMAGES_REFERENCE=8
VISION_MAX_IMAGES_SUBMISSION=4

CLOUD_LLM_TIMEOUT=600
