# Trace2Test

Web/GUI Agent 轨迹回放、故障聚类与回归测试平台。

## MiniWoB smoke test

项目使用 Python 3.11、BrowserGym MiniWoB 0.14.3 和固定版本的 MiniWoB++：

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright"
.tools/uv sync --python 3.11
.tools/uv run playwright install chromium

git clone https://github.com/Farama-Foundation/miniwob-plusplus.git .benchmarks/miniwob-plusplus
git -C .benchmarks/miniwob-plusplus checkout 7fd85d71a4b60325c6585396ec4f48377d049838

cp .env.example .env
# 设置 .env 中的 MINIWOB_URL 和可选的 DASHSCOPE_API_KEY
.tools/uv run python scripts/run_miniwob_smoke.py
```

运行结果保存在 `artifacts/smoke/<run-id>/`，包括 observation、action、reward、执行前后截图和 manifest。`artifacts/` 与 `.env` 均不会被 Git 提交。

完整项目要求见 [AGENTS.md](AGENTS.md)，技术构建说明见 [docs/PROJECT_BUILD_GUIDE.md](docs/PROJECT_BUILD_GUIDE.md)。
