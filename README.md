# WeCom HolmesGPT Adapter

企业微信智能机器人（API 模式 / WebSocket 长连接）到 HolmesGPT `/api/chat` 的轻量适配器。独立部署，不修改 HolmesGPT，不改变现有 Vue UI。

## 1. 功能

- 企业微信 WebSocket 长连接、SDK 自动心跳和重连。
- 接收企业微信文本消息，调用 HolmesGPT SSE API。
- 展示工具调用进度，最终回复 HolmesGPT `ai_answer_end.analysis`。
- 将 HolmesGPT 返回的 `conversation_history` 按企业微信用户 + 会话保存。
- `/help`、`/status`、`/reset` 命令。
- 用户 allowlist、并发限制、超时和健康检查。
- Redis 持久化会话；未配置 Redis 时使用进程内存（仅适合开发测试）。

当前版本只处理文本消息；不执行任何 Kubernetes 写操作。若 HolmesGPT 发出 `approval_required`，Adapter 会明确提示用户转到 Web UI 处理，不会自动批准。

## 2. 目录

```text
app/
  main.py                 FastAPI 生命周期与健康检查
  config.py               环境变量
  holmes/client.py        HolmesGPT SSE 客户端
  services/chat.py        对话与事件处理
  services/session.py     Redis / 内存会话
  wecom/handler.py        企业微信消息事件
deploy/
  configmap.yaml
  deployment.yaml
  secret-command.sh
```

## 3. 企业微信机器人配置

在企业微信管理后台创建「智能机器人」，选择「API 模式 / 长连接」：
1. 记录机器人 ID（Bot ID）和 Secret。
2. 配置机器人可见范围。
3. 确认运行 Adapter 的 Kubernetes 节点可以访问 `wss://openws.work.weixin.qq.com:443`。
4. 把允许使用机器人的企业微信 userid 写入 `ALLOWED_USER_IDS`，多个用户用逗号分隔。

不要把 Bot Secret 放进 ConfigMap、镜像或 Git。企业微信侧的 API 模式机器人应由本 SDK 主动建立 WebSocket 长连接，不需要给 Adapter 配置公网回调 URL。

## 4. 本地运行

需要 Python 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填写 Bot ID / Secret、允许的 userid、Holmes 地址
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

健康检查：
```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

## 5. 构建镜像

```bash
docker build -t harbor.example.com/sre-ai/wecom-holmes-adapter:0.1.0 .
docker push harbor.example.com/sre-ai/wecom-holmes-adapter:0.1.0
```

将 `deploy/deployment.yaml` 中镜像地址改为你自己的 Harbor 地址。

## 6. Kubernetes 部署

先确认 Namespace 存在：
```bash
kubectl get ns sre-ai
```

创建 Secret（本地 Bash 环境执行，不要把真实值提交 Git）：
```bash
export WECHAT_BOT_ID='企业微信 Bot ID'
export WECHAT_BOT_SECRET='企业微信 Bot Secret'
# Holmes 未开启 API Key 时可以不设置
export HOLMES_API_KEY=''
bash deploy/secret-command.sh
```

修改 `deploy/configmap.yaml`：
- `ALLOWED_USER_IDS`：替换成企业微信 userid，建议不要开启 `ALLOW_ALL_USERS`。
- `HOLMES_API_URL`：当前默认值为 `http://172.16.119.92:30395`。
- `REDIS_URL`：填写可用 Redis 地址。若暂时不使用 Redis，设为空字符串；但 Pod 重启会丢失会话上下文。

部署：
```bash
kubectl apply -f deploy/configmap.yaml
kubectl apply -f deploy/deployment.yaml
kubectl -n sre-ai rollout status deploy/wecom-holmes-adapter
kubectl -n sre-ai logs deploy/wecom-holmes-adapter -f
```

## 7. 关键配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `WECHAT_BOT_ID` | 空 | 企业微信 Bot ID，Secret |
| `WECHAT_BOT_SECRET` | 空 | 企业微信 Bot Secret，Secret |
| `ALLOWED_USER_IDS` | 空 | 允许的 userid，逗号分隔 |
| `ALLOW_ALL_USERS` | `false` | 是否允许所有用户；生产环境保持 false |
| `HOLMES_API_URL` | `http://172.16.119.92:30395` | Holmes 服务根地址 |
| `HOLMES_API_KEY` | 空 | Holmes 开启 API 认证时填写 |
| `HOLMES_MODEL` | 空 | 留空使用 Holmes 默认模型 |
| `HOLMES_TIMEOUT_SECONDS` | `300` | Holmes 请求总超时 |
| `REDIS_URL` | 空 | Redis URL；空值使用内存 |
| `SESSION_TTL_SECONDS` | `86400` | 会话 TTL |
| `MAX_CONCURRENT_CHATS` | `8` | 全局最大并发对话数 |

## 8. 会话隔离

Redis Key 格式：
```text
holmes:wecom:{chatid-or-direct}:{userid}
```
因此同一用户在不同群聊中的上下文互相隔离，不同用户也不会共享上下文。`/reset` 只清除当前用户当前会话的历史。

## 9. 消息与流式说明

- Holmes `/api/chat` 使用 `stream: true`。
- `ai_message.content` 用于展示可见的阶段性消息；不会转发 `ai_message.reasoning`。
- `start_tool_calling` / `tool_calling_result` 用于显示工具执行进度。
- `ai_answer_end.analysis` 作为最终回答，并保存同一事件的 `conversation_history`。
- 如果实际部署版本的 HolmesGPT SSE 事件字段有差异，请以当前版本的 HTTP API 日志和事件为准。

## 10. 排障

```bash
# 企业微信长连接 / 认证日志
kubectl -n sre-ai logs deploy/wecom-holmes-adapter --tail=200

# Pod 就绪情况
kubectl -n sre-ai get pod -l app=wecom-holmes-adapter -o wide

# 从 Adapter Pod 检查 Holmes 网络连通性
kubectl -n sre-ai exec deploy/wecom-holmes-adapter -- \
  python -c "import urllib.request; print(urllib.request.urlopen('http://172.16.119.92:30395/healthz', timeout=5).status)"
```

常见问题：
- **认证失败**：检查 Bot ID / Secret 是否对应当前智能机器人。
- **连接不上**：检查集群 DNS、节点出口、防火墙是否允许访问企业微信 WebSocket 443。
- **Holmes 401**：检查 `HOLMES_API_KEY` 是否与 Holmes 服务端一致。
- **Holmes 404/连接失败**：检查 `HOLMES_API_URL`，不要把 `/api/chat` 重复拼进根地址。
- **没有上下文**：配置 Redis，并确认同一个 `userid` / `chatid` 稳定可取。
- **Ready 探针失败**：查看企业微信 SDK 是否已认证；检查机器人凭证和 WebSocket 出口。

## 11. 安全边界

- 不开放集群写操作。
- 默认拒绝未列入 `ALLOWED_USER_IDS` 的用户。
- Bot Secret、Holmes API Key 仅放 Kubernetes Secret。
- 建议企业微信机器人可见范围也限制在运维/开发人员范围。
- 若后续增加重启、扩缩容等操作，必须单独设计审批、身份授权、审计和幂等机制。

## 12. 参考

- [WeCom AI Bot Python SDK](https://github.com/WecomTeam/wecom-aibot-python-sdk)
- [HolmesGPT HTTP API](https://holmesgpt.dev/dev/reference/http-api/)
