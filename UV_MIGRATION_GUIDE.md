# uv 迁移指南

本项目已成功从 `pip` 迁移到 `uv` 包管理器。以下是完整的迁移总结和使用指南。

## 迁移概览

AutoE2E 项目包含两个部分，都已成功迁移到 uv：

1. **主项目** (`/home/tyrfly1001/autoe2e/`)
   - 依赖定义在 `pyproject.toml` 中
   - 锁文件：`uv.lock` (3986 行)
   - 依赖数量：193 个包（包含传递依赖）

2. **日志服务器** (`/home/tyrfly1001/autoe2e/benchmark/_log-server/`)
   - 依赖定义在 `pyproject.toml` 中
   - 依赖数量：4 个核心包（Flask、Flask-Cors、Flask-Session、redis）

## 新的工作流

### 安装 uv（一次性）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 主项目：安装依赖

```bash
cd /home/tyrfly1001/autoe2e

# 创建虚拟环境
uv venv .venv
source .venv/bin/activate

# 安装依赖（两种方式选一种）
# 方式1：使用锁文件（推荐，完全可复现）
uv pip sync requirements.txt

# 方式2：使用最新兼容版本
uv pip install -r requirements.txt
```

### 日志服务器：安装依赖

```bash
cd /home/tyrfly1001/autoe2e/benchmark/_log-server

# 安装依赖
uv pip install -r requirements.txt
```

### 运行项目

激活虚拟环境后：

```bash
# 主程序
python main.py

# 测试
pytest

# 日志服务器
cd benchmark/_log-server
flask --app extract.py --debug run
```

或使用 `uv run` 不需要手动激活虚拟环境：

```bash
uv run python main.py
uv run pytest
```

## 命令对比

| 操作 | pip | uv |
|------|-----|-----|
| 创建虚拟环境 | `python -m venv .venv` | `uv venv .venv` |
| 激活虚拟环境 | `source .venv/bin/activate` | `source .venv/bin/activate` |
| 安装依赖 | `pip install -r requirements.txt` | `uv pip install -r requirements.txt` |
| 同步锁文件 | 无直接等价 | `uv pip sync requirements.txt` |
| 添加依赖 | `pip install package==version` | `uv add package==version` |
| 冻结依赖 | `pip freeze > requirements.txt` | `uv pip freeze > requirements.txt` |
| 运行脚本 | 需手动激活 | `uv run python script.py` |

## 关键文件变更

### 主项目文件结构

```
autoe2e/
├── pyproject.toml          # 新增：定义依赖
├── uv.lock                 # 新增：锁定版本（3986 行）
├── requirements.txt        # 保留：由 uv 生成的兼容文件
├── README.md               # 更新：新增 uv 安装说明
└── ...
```

### 日志服务器文件结构

```
benchmark/_log-server/
├── pyproject.toml          # 新增：定义依赖
├── requirements.txt        # 保留：用于兼容性
└── ...
```

## pyproject.toml 结构

### 主项目 (autoe2e)

```toml
[project]
name = "autoe2e"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "abstract-singleton==1.0.1",
    "beautifulsoup4==4.12.2",
    # ... 其他依赖
]
```

### 日志服务器 (autoe2e-log-server)

```toml
[project]
name = "autoe2e-log-server"
version = "0.1.0"
description = "Coverage extraction and logging server for AutoE2E"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "Flask==3.0.3",
    "Flask-Cors==4.0.1",
    "Flask-Session==0.8.0",
    "redis==5.0.6",
]
```

## 为什么使用 uv？

1. **性能** ⚡
   - 比 pip 快 10-100 倍
   - 用 Rust 编写，编译优化

2. **可复现性** 🔒
   - `uv.lock` 确保所有环境一致
   - 支持多平台依赖分辨率

3. **现代化** 🚀
   - 统一的 `pyproject.toml` 配置
   - 支持依赖组（dev、test 等）
   - 更好的错误信息

4. **兼容性** ✅
   - 完全兼容 pip
   - `requirements.txt` 格式不变
   - 平滑迁移

## 常见操作

### 更新依赖版本

```bash
cd /home/tyrfly1001/autoe2e

# 添加新依赖
uv add package-name

# 更新特定包
uv add package-name --upgrade

# 更新所有包
uv pip install --upgrade -r requirements.txt
```

### 生成新的锁文件

```bash
cd /home/tyrfly1001/autoe2e
uv sync
```

### 检查依赖

```bash
# 显示已安装的包
uv pip list

# 显示包的详细信息
uv pip show package-name
```

### 清理虚拟环境

```bash
# 删除虚拟环境
rm -rf .venv

# 重新创建
uv venv .venv
uv pip sync requirements.txt
```

## CI/CD 集成建议

在 CI 环境中使用 `uv pip sync` 获得完全一致的环境：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv
source .venv/bin/activate
uv pip sync requirements.txt
pytest
```

## 故障排除

### 问题：`uv` 命令未找到
**解决**：确保 uv 已安装且在 PATH 中
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 问题：虚拟环境激活失败
**解决**：确保使用正确的激活脚本
```bash
# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 问题：依赖冲突
**解决**：使用 `uv pip sync` 从锁文件重新同步
```bash
uv pip sync requirements.txt
```

## 更多信息

- [uv 官方文档](https://docs.astral.sh/uv/)
- [项目 README](./README.md)
- [pyproject.toml 规范](https://packaging.python.org/en/latest/specifications/pyproject-toml/)
