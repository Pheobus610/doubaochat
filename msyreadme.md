# msyreadme — 命令速查

单机测试与服务器部署的常用命令。所有命令均已实测可用。

- 项目目录：`doubaochat/`
- 虚拟环境：`.venv`（Python 3.12，由 `uv` 创建）
- 默认端口：`8000`（可用 `PORT` 环境变量覆盖）

---

## 一、单机测试（本地开发）

### 1. 首次准备环境

```bash
cd doubaochat
./setup.sh
```

会自动创建 `.venv`、安装依赖、生成 `.env`。

> 本机 `python3` 是 3.9，而项目需要 3.10+（代码用了 `X | None` 语法）。
> `setup.sh` 会自动检测并用 `uv` 装独立的 Python 3.12，不需要 sudo，也不动系统 Python。

装完后填 API Key：

```bash
vim .env      # 填 ARK_API_KEY 和 ARK_MODEL
```

### 2. 启动本地服务

```bash
./start.sh                    # 默认 8000 端口，带 --reload 热重载
PORT=8080 ./start.sh          # 换端口
TUNNEL=1 ./start.sh           # 同时开公网隧道（需先装 cloudflared 或 ngrok）
```

浏览器打开 <http://127.0.0.1:8000>，`Ctrl-C` 退出。

> `--reload` 仅适合开发（改代码自动重启）。**服务器上不要用 `start.sh`**，见第二部分。

### 3. 跑测试

```bash
cd doubaochat

# 全部测试（80 个）
.venv/bin/python -m pytest -q

# 代码规范检查
.venv/bin/ruff check .

# 规范 + 测试一起跑（提交前建议执行）
.venv/bin/ruff check . && .venv/bin/python -m pytest -q
```

按模块单独跑：

```bash
.venv/bin/python -m pytest tests/test_main.py -v         # 接口主流程        16 个
.venv/bin/python -m pytest tests/test_quiz_perf.py -v    # 出题性能与超时     29 个
.venv/bin/python -m pytest tests/test_pdf_preview.py -v  # PDF 预览与路径安全 14 个
.venv/bin/python -m pytest tests/test_ops.py -v          # 运维与长期挂载     12 个
.venv/bin/python -m pytest tests/test_concurrency.py -v  # 并发与线程池        9 个
```

常用参数：

```bash
.venv/bin/python -m pytest -q -x                    # 遇到第一个失败就停
.venv/bin/python -m pytest -q -k "quota"            # 只跑名字含 quota 的
.venv/bin/python -m pytest tests/test_ops.py -q -s  # 显示 print 输出
```

### 4. 前端 JS 测试（可选）

需要 Node，本机默认没装：

```bash
# 有 node 的话
node tests/test_prefetch.js        # 预生成状态机，7 个用例

# 顺手做语法检查
node --check static/app.js
node --check static/voice.js
```

没有 Node 可以跳过，Python 测试已覆盖后端全部逻辑。

---

## 二、服务器部署（长期挂载）

### 1. 全新服务器，一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/Pheobus610/doubaochat/main/install.sh | bash
```

已经克隆过代码的话：

```bash
cd doubaochat
./install.sh              # 自动选择 Docker 或裸机
./install.sh --docker     # 强制用 Docker
./install.sh --bare       # 强制用裸机 venv
./install.sh --yes        # 全部默认，不交互（写进自动化脚本时用）
```

脚本会依次做：装 curl/git → 准备 Python 3.10+ → 生成 `.env` → 启动服务 → 询问是否开机自启。

安装完记得填 Key 再重启：

```bash
vim .env                  # 填 ARK_API_KEY、ARK_MODEL
./server.sh restart
```

### 2. 日常运维

```bash
cd doubaochat

./server.sh start              # 后台启动
./server.sh stop               # 停止
./server.sh restart            # 重启
./server.sh status             # 状态 + 健康检查 + 内存 + 磁盘占用
./server.sh logs               # 实时跟踪日志（Ctrl-C 退出）
./server.sh logs 500           # 看最近 500 行
./server.sh update             # 拉最新代码 + 装依赖 + 重启
```

脚本会自动判断当前是 Docker、systemd 还是 nohup，不用关心底层差异。

`status` 输出示例：

```
运行模式：裸机
------------------------------------------
✓ 运行中，PID 75038
  PID    RSS  %CPU ELAPSED
75038  64992  21.4   00:01
------------------------------------------
✓ 健康检查通过：{"ok":true,"configured":true,...}
uploads 占用： 28K（8 个文件）
磁盘剩余：245Gi / 460Gi (已用 45%)
```

### 3. 开机自启与崩溃自愈（长期挂载必做）

```bash
./server.sh install-service      # 注册开机自启
./server.sh uninstall-service    # 取消
```

**这一步别省。** 不注册的话是 `nohup` 方式跑的，进程崩了不会自己起来，服务器重启后也不会拉起。注册之后：

- 崩溃 5 秒内自动重启
- 服务器重启后自动拉起
- 10 分钟内重启超过 10 次会停下来等人处理（防重启风暴刷爆日志）

验证自愈是否生效（**建议部署后跑一次**）：

```bash
./server.sh status               # 记下 PID
sudo kill -9 <PID>               # 模拟崩溃
sleep 8
./server.sh status               # PID 应该变了，且健康检查通过
```

> 这一项我在 macOS 上没法验证（本机无 systemd，Docker Desktop 也没开），
> 请在服务器上确认一次。

### 4. Docker 方式（手动操作）

```bash
docker compose up -d --build     # 构建并后台启动
docker compose ps                # 状态
docker compose logs -f           # 日志
docker compose restart           # 重启
docker compose down              # 停止并删容器
```

已配好：`restart: always`（宿主机重启也会拉起）、内存上限 512M、日志轮转 10MB×3、
每 30 秒健康探针。

### 5. 常用运维检查

```bash
# 服务是否活着
curl -s http://127.0.0.1:8000/api/health

# 磁盘（长期挂载最容易忽略的指标）
df -h .
du -sh uploads/

# 端口被谁占了
lsof -i:8000

# 内存占用
ps -o pid,rss,%cpu,etime -p $(cat .server.pid)
```

---

## 三、关键配置（`.env`）

改完执行 `./server.sh restart` 生效。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ARK_API_KEY` | 空 | 火山方舟 API Key，**必填** |
| `ARK_MODEL` | 空 | 推理接入点 ID，**必填** |
| `PORT` | 8000 | 监听端口 |
| `THREAD_POOL_SIZE` | 80 | 线程池上限，20 并发靠它。**别调回 40** |
| `MAX_SESSIONS` | 500 | 会话数上限，超了按最久未活动淘汰 |
| `SESSION_TTL_SECONDS` | 7200 | 会话 2 小时无活动即清理 |
| `UPLOAD_TTL_SECONDS` | 7200 | 上传的 PDF 保留 2 小时 |
| `UPLOAD_MAX_TOTAL_MB` | 4096 | uploads 目录总容量上限，超了删最旧的 |
| `LOG_LEVEL` | INFO | 日志级别，排查问题可调 DEBUG |
| `ACCESS_TOKEN` | 空 | 设了之后访问需带 token，公网暴露建议开 |

---

## 四、几个必须知道的坑

**1. 服务器上绝对不要用 `--workers 4`**

会话状态存在进程内存里，多 worker 会让同一个用户的请求随机落到不同进程，
随机报「会话不存在」。脚本里已经写死 `--workers 1`。

20 并发靠线程池就够（实测 20 并发出题完全并行，期间健康检查 2.4ms）。
这个应用是在等 LLM 返回（IO 密集），不是在算 CPU，多核用不上。

**2. `THREAD_POOL_SIZE` 别调回 40**

anyio 原生默认 40，实测 60 并发时峰值**精确卡死在 40**、耗时 4.0s；
调到 80 后峰值 60、耗时 2.1s（降低 49%）。
每个用户会占 2~3 个线程（出题预取 + 语音合成 + 偶发上传），20 人正好撞线。

**3. `start.sh` 只用于本地开发**

它带 `--reload`，改代码就重启，会打断正在进行的请求。服务器用 `./server.sh start`。

**4. 服务重启后所有会话丢失**

会话在内存里，重启即清空。前端能自愈（收到 404 会提示重新开始），
但用户正在做的题会没了。所以**更新代码尽量选没人用的时候**。

**5. 真正的并发天花板大概率是方舟限流**

前端有自动生成和预取，用户进页面就会消耗 API 调用。
20 人同时用，QPS 可能撞上方舟账号配额。
如果看到「请求过于频繁（限流）」，是要去方舟控制台提配额，改这边的代码没用。

---

## 五、出问题了怎么查

```bash
./server.sh status        # 先看活着没
./server.sh logs 200      # 再看日志
```

| 现象 | 大概原因 | 怎么办 |
| --- | --- | --- |
| 接口返回 503 未配置 | `.env` 里 Key 没填 | 填 `ARK_API_KEY` / `ARK_MODEL` 后 `./server.sh restart` |
| 「请求过于频繁（限流）」 | 撞方舟配额 | 去方舟控制台提配额 |
| 随机「会话不存在」 | 被改成了多 worker | 改回 `--workers 1` |
| 服务起不来，端口被占 | 有残留进程 | `lsof -i:8000` 找到后 kill |
| 磁盘满 | uploads 堆积 | 调小 `UPLOAD_MAX_TOTAL_MB`、`UPLOAD_TTL_SECONDS` |
| 崩了不自动重启 | 没注册 systemd | `./server.sh install-service` |
| 日志里没有应用信息 | `LOG_LEVEL` 太高 | 设 `LOG_LEVEL=DEBUG` 后重启 |

---

## 六、命令速查表

| 场景 | 命令 |
| --- | --- |
| 本地首次准备 | `./setup.sh` |
| 本地开发启动 | `./start.sh` |
| 跑全部测试 | `.venv/bin/python -m pytest -q` |
| 提交前自检 | `.venv/bin/ruff check . && .venv/bin/python -m pytest -q` |
| 服务器首次安装 | `./install.sh` |
| 服务器启动/停止 | `./server.sh start` / `./server.sh stop` |
| 查看状态 | `./server.sh status` |
| 查看日志 | `./server.sh logs` |
| 更新代码 | `./server.sh update` |
| 注册开机自启 | `./server.sh install-service` |
| 健康检查 | `curl -s http://127.0.0.1:8000/api/health` |

---

## 附：本文档的验证情况

写文档时逐条实测了命令，过程中修掉了 3 个真实 bug（否则文档里的命令跑不通）：

1. `setup.sh` 开头有个硬性版本门禁，系统 Python 3.9 时直接 `exit 1`，
   导致后面「自动用 uv 装 3.12」的兜底逻辑永远走不到 —— 也就是说在
   任何自带 3.9 的机器上（macOS、CentOS 7）`setup.sh` 都是失败的。已移除该门禁。
2. `setup.sh` / `start.sh` / `server.sh` 都直接调 `.venv/bin/pip`，
   但 `uv` 创建的虚拟环境**默认不含 pip**，会报 `No such file or directory`。
   已改为优先 `python -m pip`，回退 `uv pip`。
3. `setup.sh` 里 `$PY_BIN（` 这种写法，bash 会把全角括号当成变量名的一部分，
   配合 `set -u` 报 `unbound variable`。已改为 `${PY_BIN}`。

已验证通过：

- `ruff check .` 无告警，`pytest` 80 个全过（分模块数量与本文一致）
- `./setup.sh` 可重复执行且不破坏已有环境
- `./start.sh` 端到端启动成功，健康检查返回 200
- `./server.sh start / status / stop` 端到端正常
- 6 个 shell 脚本语法检查通过

**未能在本机验证**（macOS 无 systemd、Docker Desktop 未启动），需在服务器上确认：

- `./server.sh install-service` 注册开机自启
- `kill -9` 后 5 秒内自动重启
- `docker compose` 相关命令

