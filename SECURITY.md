# 安全说明

本项目是一个面向学习/演示用途的 Demo，部署到公网前请务必阅读并遵循以下规范。

## 1. API Key 使用要求

- 本身依赖火山方舟（豆包）大模型与语音服务，**调用按官方计费**。
- 每位使用者需**自备**自己的方舟 API Key、模型接入点 ID 与语音应用凭证。
- 仓库**不提供**任何可用的密钥；如发现历史提交中存在真实密钥，请立即在方舟控制台吊销并通知维护者。

## 2. 密钥管理规范

- **禁止**将 API Key、Token、AppID 等敏感信息硬编码进源码或提交到 Git 仓库。
- 所有密钥通过 `.env` 环境变量或前端「设置」（保存在浏览器 `sessionStorage`）注入。
- `.env` 已在 `.gitignore` 中排除，请勿使用 `git add -f .env` 强制提交。
- 建议启用 pre-commit 钩子与密钥扫描，防止误提交：

  ```bash
  pip install pre-commit
  pre-commit install
  ```

  钩子包含 `scripts/check-secrets.sh` 轻量扫描；如需更强能力，可额外安装
  [gitleaks](https://github.com/gitleaks/gitleaks) 或 AWS [git-secrets](https://github.com/awslabs/git-secrets)。

## 3. 公网暴露与访问控制

将服务暴露到非局域网时，**强烈建议**在 `.env` 设置访问口令：

```bash
ACCESS_TOKEN=请使用一段足够随机的字符串
```

启用后，除首页 `/`、静态资源 `/static/*`、健康检查 `/api/health` 外，所有接口均需在请求头携带：

```
Authorization: Bearer <ACCESS_TOKEN>
# 或
X-Access-Token: <ACCESS_TOKEN>
```

前端用户在「设置 → 访问口令」中填入即可。这是防止接口被未授权调用、
避免他人消耗你的方舟配额的轻量防线，**不能**替代 HTTPS 等传输层安全措施。

## 4. 传输安全

- 公网部署请务必启用 HTTPS（可用 [Let's Encrypt](https://letsencrypt.org/) 免费证书，
  或通过 cloudflared/ngrok 自带的 TLS）。
- 浏览器仅在 HTTPS 下才允许使用麦克风（ASR）等能力，HTTP 公网地址会导致语音功能不可用。

## 5. 安全漏洞上报

如发现安全漏洞，请**不要**在公开 Issue 中提交，而通过以下渠道私密上报：

- GitHub 私有安全公告：仓库 **Security** 标签 → **Report a vulnerability**
- 或邮件至：`<请替换为你的安全联系邮箱>`

我们会在收到报告后尽快确认并修复。感谢你的帮助！
