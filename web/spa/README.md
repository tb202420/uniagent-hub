# UniAgent Hub 管理控制台（React SPA 初版）

React 19 + React Flow 12（Vite 构建）。四个页面：

- **工具注册中心**：全部已注册 MCP 工具（名称/说明/只读写），支持筛选
- **工作流编排**：蓝图 DAG 可视化（依赖分层布局）+ 最近执行列表
- **安全中心**：Guard 拦截统计（总数/成功率/平均延迟 + 按错误码 1001–1007/1999 分布）
- **审计日志**：trace_id / 工具 / caller / 错误码 / schema_hash / 延迟，支持筛选

数据来自 Dashboard 的 JSON API（`/api/*`，见 `web/audit_dashboard/app.py`）。

## 构建与运行

```bash
# 1) 构建（需要 Node 18+）
npm install
npm run build          # 产物在 dist/

# 2) 启动 Hub 与 Dashboard（项目根目录）
python main.py --port 8020                        # 终端 1：Hub
python -m web.audit_dashboard --hub http://127.0.0.1:8020 --port 18080   # 终端 2

# 3) 访问 http://127.0.0.1:18080/spa/（Dashboard 自动挂载 dist/）
```

开发模式（热更新）：`npm run dev` 后访问 http://localhost:5173（`/api` 已代理到 18080）。

> dist/ 不入库；未构建时 Dashboard 不挂载 /spa，旧版纯 HTML 页面始终可用（任何机器直接跑的保底路径）。

## 演示遥测流（配合第 6 类适配器）

```bash
python -m scripts.dev_ws_stream --port 8765        # 终端 A：演示流服务端
set HUB_WS_CONFIGS=adapters/websocket_adapter/configs/websocket_streams.yaml
python main.py --port 8020                          # 终端 B：Hub（含 websocket 适配器）
```

## 下一步（Roadmap）

- ELK.js 自动布局替代当前"依赖深度分层"手工布局
- 工作流执行实时状态（WebSocket 推送）
- 适配器管理页（启停 / 健康状态 / 配置编辑）
- Tauri 2 桌面封装（需 Rust 工具链）
