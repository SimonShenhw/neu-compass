# WSL2 + Ubuntu 24.04 配置 (NEU-Compass)

> 实测路径(2026-04-30, RTX 5090 + Win11)。Cross-reference: ADR-0006 (WSL2 强制) /
> ADR-0014 (代码 H 盘 + 运行时数据 WSL home).

## 0. 为什么 WSL2

`pyproject.toml` 的几个依赖在 Windows 原生不靠谱:
- **faiss-cpu** — Windows wheel 偶尔报 SIMD 指令集错
- **FlagEmbedding / sentence-transformers** — torch CUDA wheel 在 Windows 慢
- **playwright** — 浏览器子进程 IPC 在 Windows 偶尔卡死
- **vLLM** (v2) — 不支持 Windows

WSL2 = "Linux 写代码的便利" + "Windows 编辑器的友好"。

## 1. 一次性安装 (10-15 分钟)

### 1.1 装 Ubuntu 24.04

**管理员 PowerShell**:
```powershell
wsl --install -d Ubuntu-24.04
```

如果已经装过 WSL2 引擎(`wsl --status` 显示有 Default version 2),
那 `-d Ubuntu-24.04` 只装 distro,无需重启。
全新机器 + 全新 WSL2 可能要重启一次。

### 1.2 第一次启动 Ubuntu

启动菜单/`wsl ~` 进入,会问:
```
Create a default Unix user account: <你的 unix 用户名>
New password: <设密码,只本机有用>
```

**注意**: 这个密码只用于本机 sudo,**不要复用其他账号的密码**,
**不要发到任何聊天/邮件/截图**。

### 1.3 验证 GPU 直通

回到 Windows Bash / PowerShell:
```bash
wsl -d Ubuntu-24.04 -e nvidia-smi
```

应该看到:
- Driver Version: 596.x (Windows 侧驱动版本,WSL 不重装)
- CUDA Version: 13.x (随 Windows 驱动)
- 你的 GPU 卡名(本项目: RTX 5090)

GPU 直通靠 Windows NVIDIA 驱动,**Linux 里不要装 NVIDIA 驱动**。
如果 nvidia-smi 报 not found,先到 Windows 装最新版 NVIDIA 驱动:
https://www.nvidia.com/Download/index.aspx

## 2. 项目环境

### 2.1 装 uv (用户级,无 sudo)

```bash
wsl -d Ubuntu-24.04 -e bash
# 进入 Ubuntu shell

curl -LsSf https://astral.sh/uv/install.sh | sh
# 装到 ~/.local/bin/uv,自动加 .bashrc PATH

source ~/.bashrc        # 或重开 shell
uv --version            # 应当 0.11+
```

### 2.2 同步项目依赖

```bash
cd /mnt/h/neu-compass    # ADR-0014: 代码在 H 盘
uv venv                  # 创建项目本地 .venv (gitignored)
uv sync --extra dev      # 装所有依赖,首次约 6 分钟
                         # PyTorch 自动挑 CUDA wheel(检测到 nvidia-smi)
```

实测产出:
- Python 3.12.3 (Ubuntu 24.04 系统 Python)
- pydantic 2.13.x / faiss 1.13.x
- **torch 2.10 + CUDA 12.8** (uv 自动检测 GPU 选 CUDA wheel)
- 总安装 ~3GB(.venv 大小)

### 2.3 验证

```bash
uv run python -c "import torch; print(torch.cuda.is_available())"
# 应当 True

uv run pytest tests/ -q
# 应当 109 passed
```

## 3. 运行时数据路径策略 (ADR-0014)

代码在 `/mnt/h/neu-compass`(NTFS via 9P,可被 Windows 编辑器编辑)。
但**运行时数据**(SQLite + FAISS index + embedding cache)建议放 WSL home:

```bash
mkdir -p ~/neu-compass-data
```

然后在 `.env` 改:
```
SQLITE_PATH=/home/<你的 unix 名>/neu-compass-data/courses.db
FAISS_INDEX_PATH=/home/<你的 unix 名>/neu-compass-data/faiss_index
```

**理由**: SQLite 高频读写 + FAISS index mmap 走 9P 跨文件系统会慢。
Week 2 末有 latency benchmark 验证(`scripts/bench_path.py`,待写)。

## 4. 常见坑 (实测)

### 4.1 VS Code Remote-WSL

Windows 里装 [WSL extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-wsl),
然后 `code .` 从 WSL 里启动 VS Code,会自动 attach 到 WSL。
比从 Windows 打开 `H:\neu-compass` 然后用 WSL terminal 友好得多。

### 4.2 Git 在 /mnt/h 下的所有权问题

新版 git 安全策略可能拒绝跨用户的 repo:
```
fatal: detected dubious ownership in repository at '/mnt/h/neu-compass'
```

修复:
```bash
git config --global --add safe.directory /mnt/h/neu-compass
```

### 4.3 行尾符 (CRLF/LF)

我们的 .gitignore 没显式管,git 默认在 Windows 上 `core.autocrlf=true`。
WSL 里 git 可能 warn `LF will be replaced by CRLF`。
可以 commit 时无视,或者:
```bash
git config --global core.autocrlf input
```
让 Linux 侧保持 LF,Windows 侧 checkout 时再转 CRLF。

### 4.4 Windows cp936 终端中文乱码

`scripts/seed_aai6600.py` 已经处理过(顶部 `sys.stdout.reconfigure(utf-8)`)。
WSL Linux 终端默认 UTF-8,无此问题。

### 4.5 第一次 uv sync 慢 / 卡

PyTorch CUDA wheel 大约 1.5GB,看你网速。
如果国内网慢,考虑加 mirror:
```bash
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
uv sync --extra dev
```

### 4.6 nvidia-smi 在 Linux 里报 "not found" 但 Windows 里有

Windows 驱动太老或 WSL2 内核太老。
- Windows 驱动: 525.x+ 才有 WSL2 GPU 支持
- WSL2 内核: `wsl --update` 升到最新

## 5. 日常工作流

```bash
# 早上开机
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
git pull

# 装新依赖(改 pyproject.toml 后)
uv sync --extra dev

# 跑测试
uv run pytest tests/

# 跑 seed
uv run python scripts/seed_aai6600.py --db-path ~/neu-compass-data/courses.db

# 启 FastAPI 后端
uv run uvicorn api.main:app --reload

# 启 Streamlit 前端
uv run streamlit run app/streamlit_app.py
```

## 6. 卸载 (如果以后要清理)

```powershell
# Windows 管理员 PowerShell
wsl --unregister Ubuntu-24.04   # 删 distro + 所有数据
```

注意: 这会删 `~/neu-compass-data/` 里的 SQLite + FAISS。
代码在 H 盘不受影响。
