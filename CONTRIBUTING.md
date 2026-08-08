# 贡献指南

感谢你愿意为 doubaochat 贡献代码！以下是参与流程。

## 开发环境准备

```bash
git clone https://github.com/Pheobus610/doubaochat.git
cd doubaochat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # 包含运行时 + 测试/ lint 依赖
cp .env.example .env                  # 按需填写你自己的方舟凭证
pre-commit install                    # 可选：安装提交前钩子
```

启动开发服务：

```bash
./start.sh          # 或 uvicorn app.main:app --reload
```

## 开发工作流

1. **Fork 并拉取分支**：从 `main` 拉出特性分支，命名建议 `feat/xxx`、`fix/xxx`、`docs/xxx`。
2. **编码**：保持与现有代码风格一致；如新增接口，请同步更新 `README.md` 的接口表。
3. **本地校验**（提交前必须通过）：

   ```bash
   ruff check .
   ruff format --check .
   pytest
   ```

4. **提交**：使用清晰的提交信息，推荐 [Conventional Commits](https://www.conventionalcommits.org/) 风格，
   例如 `feat: 新增错题导出接口`、`fix: 修复 TTS 长文本分块越界`。
5. **Pull Request**：向 `main` 发起 PR，按 PR 模板填写说明与测试情况，等待 Review。

## 测试规范

- 单元测试位于 `tests/`，使用 `pytest`。
- **禁止**在测试中真实调用方舟/语音等外部 API，请使用模拟数据或桩函数。
- 纯函数、数据校验、接口行为均应有覆盖；新增功能请补齐对应测试。

## 代码风格

- Python ≥ 3.10（项目使用 `X | None` 语法）。
- 由 `ruff` 负责检查与格式化，配置见 `ruff.toml`。
- 前端 JS 保持与现有文件一致的缩进（2 空格）与命名风格。

## 行为准则

请保持友善与尊重，聚焦技术讨论。对所有人欢迎。
