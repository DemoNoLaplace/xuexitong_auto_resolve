# xuexitong_auto_resolve

Windows 学习通（超星）PC 客户端流程工具：读取客户端已登录 Cookie，完成课程/章节发现、内嵌文档解析、章节作业作答、文档类任务点完成，并支持 OpenAI 兼容大模型辅助答题。

> **默认只预览，不写入平台。**
> 即使使用 `--save`，程序也只会调用“暂时保存”，不会提交作业。
> 本项目仅供学习与技术交流，请遵守所在学校和课程的使用规定，风险自负。

## 功能

- 复用 PC 学习通客户端已登录的 Cookie，不保存账号密码
- 列出课程、章节，支持按课程名/章节号子串查找
- 下载并解析章节内嵌 PDF/PPT/Word 文档
- 读取章节作业题目，支持单选、多选、判断、填空、简答
- 动态解码学习通 `font-cxsecret` 字体混淆（按页面内嵌字体识别字形）
- 支持本地答案库、OpenAI 兼容大模型、保守关键词启发式
- 完成章节**文档类任务点**（PDF/PPT/Word 等）
- 只调用“暂时保存”，代码中没有提交接口

## 下载

不想配置 Python 的话，可以在 [Releases](https://github.com/DemoNoLaplace/xuexitong_auto_resolve/releases) 下载 Windows 整合包：

- `chaoxing-flow-windows.zip`：包含 exe、`answer_banks`、`config.example.env` 和使用说明
- `chaoxing-flow.exe`：单独的可执行文件

解压后把 `config.example.env` 复制为 `.env`，按需填写大模型配置。

## 环境要求

- Windows 10/11
- Python 3.10+
- PC 学习通客户端 `cxstudy.exe`
- 能访问学习通域名；需要代理时可用 `--proxy auto` 或 `--proxy direct`

## 快速开始

```powershell
git clone https://github.com/DemoNoLaplace/xuexitong_auto_resolve.git
cd xuexitong_auto_resolve

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 先启动并登录 PC 学习通，至少打开一次课程
python -m chaoxing_flow doctor
```

看到 `登录校验: OK` 和课程列表即可。

## 配置大模型（可选）

复制配置示例为 `.env`：

```powershell
Copy-Item config.example.env .env
```

编辑 `.env`：

```ini
CX_LLM_API_KEY=你的 key
CX_LLM_BASE_URL=https://api.openai.com/v1
CX_LLM_MODEL=gpt-4o-mini
```

- 程序会自动读取 exe 同目录、项目根目录或当前目录的 `.env`
- 系统环境变量优先于 `.env`
- 也可以用 `CX_ENV_FILE` 指定其他 `.env` 路径
- 兼容 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`
- `.env` 已被 `.gitignore` 忽略，**不要提交到公开仓库**

运行 `doctor` 可以检查 Key、接口和模型是否读取正确。

## 常用命令

```powershell
# 课程 / 章节
python -m chaoxing_flow courses
python -m chaoxing_flow chapters --course "课程名"

# 下载并解析章节文档
python -m chaoxing_flow materials --course "课程名" --chapter "1.1"

# 查看题目
python -m chaoxing_flow questions --course "课程名" --chapter "1.1"

# 预览作答（不写入平台）
python -m chaoxing_flow solve --course "课程名" --chapter "1.1"

# 使用大模型预览
python -m chaoxing_flow solve --course "课程名" --chapter "1.1" --llm

# 确认后暂存，并完成任务点
python -m chaoxing_flow solve --course "课程名" --chapter "1.1" --llm --save --verify
```

### 任务点

`solve --save` 默认会完成本章的**文档类任务点**（PDF/PPT/Word 等，标记为已读），然后调用“暂时保存”。

| 参数 | 作用 |
| --- | --- |
| `--save` | 暂存作业，并默认完成任务点 |
| `--no-complete-jobs` | 即使使用 `--save`，也只暂存、不处理任务点 |
| `--complete-jobs` | 只完成任务点，不暂存（可以不加 `--save`） |
| `--verify` | 暂存后重新读取并核对答案 |

限制：

- 作业任务点需要提交作业并等待批阅，本工具不会自动提交
- 视频/音频任务点需要模拟播放，暂不支持
- 文档任务点完成后会直接标记为已读，建议只对已浏览或准备学习的章节使用

### 一条命令跑完整流程

```powershell
python -m chaoxing_flow run --course "课程名" --chapter "1.1" --llm --verify
```

`run` 等价于带 `--save` 的 `solve`，同样会先询问确认。

## 答案库

默认读取 `answer_banks/example.json`（通用示例，不会匹配真实题目）。  
要使用自己的答案库，复制一份并修改：

```json
{
  "answers": [
    {
      "contains": ["关键词1", "关键词2"],
      "type": "单选题",
      "answer": "A",
      "note": "依据"
    }
  ]
}
```

- `contains` 中的关键词全部命中题干才会匹配
- 单选：`A`；多选：`ABC`；判断：`true` / `false`；简答/填空：文本
- 也可以用 `"stem": "完整题干"` 做精确匹配
- 通过 `--bank path\to\bank.json` 指定

## 字体混淆解码

学习通作业页会把常用汉字替换成生僻字，再用内嵌 `font-cxsecret` 字体渲染。  
本项目会：

1. 从页面 HTML 提取内嵌字体
2. 把每个字形渲染成小图
3. 与内置的常用汉字字形库 `chaoxing_flow/font_ref.npz` 比对
4. 按字体 SHA1 缓存映射到 `data/cache/fontmaps/`

同一个乱码字在不同页面可能对应不同汉字，因此动态识别比固定映射表可靠。  
识别失败的字符会原样保留，并在终端提示。

## 打包 exe

```powershell
.\build_exe.ps1
```

生成：

```text
dist\chaoxing-flow.exe
```

脚本会把 `answer_banks`、`config.example.env`、`README.md`、`docs\使用说明.md` 复制到 `dist`。  
需要大模型时，把 `.env` 放在 exe 同目录。

发布前请确认 `dist` 中没有 `.env` 文件。

## 项目结构

```text
xuexitong_auto_resolve/
├─ chaoxing_flow/            # 源码
│  ├─ api.py                 # 课程、章节、作业、任务点接口
│  ├─ fontmap.py             # font-cxsecret 动态解码
│  ├─ font_ref.npz           # 内置常用汉字字形库
│  ├─ solver.py              # 答案库 / LLM / 启发式
│  └─ ...
├─ answer_banks/example.json # 通用答案库示例
├─ docs/使用说明.md
├─ .github/workflows/        # GitHub Actions 发布流程
├─ build_exe.ps1
├─ config.example.env
├─ launcher.py
├─ requirements.txt
├─ run.ps1 / run.bat
├─ LICENSE
└─ README.md
```

## 安全边界

- **没有提交功能**：`api.py` 只实现了 `save_work()`，请求参数固定 `tempsave=1`
- **不保存密码**：复用客户端已登录 Cookie
- **默认预览**：`solve` 默认不写平台；`run` / `--save` 也会二次确认
- **不绕过登录**：会话失效时提示在客户端手动登录
- **材料缺失不猜**：没有答案库、没有 LLM、又没有材料时，保留未作答题目

## 常见问题

### 提示“未配置大模型 API Key”

在 exe 同目录或项目根目录创建 `.env`，写入 `CX_LLM_API_KEY=...`，然后运行：

```powershell
python -m chaoxing_flow doctor
```

### 题干仍有乱码

页面字体可能不在内置字形库覆盖范围内。终端会提示未识别字符数量；可以提交 Issue 并附上章节信息。

### 任务点还剩一个

通常是作业任务点尚未提交或尚未批阅；本工具不会自动提交作业。视频/音频任务点也暂不支持。

## 第三方组件

见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。其中 PyMuPDF 使用 AGPL-3.0，分发二进制前请确认遵守其许可证。

## License

[MIT](LICENSE)
