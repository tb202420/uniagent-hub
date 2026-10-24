# 桌面档（Tauri 2 外壳 + PyInstaller sidecar 脚手架）

v2.0 §3.2/§四 的桌面形态。**本目录为脚手架**：本地无 Rust 工具链时不必构建，
由 CI（`.github/workflows/desktop-build.yml`，手动触发）产出安装包；浏览器档
（Dashboard :18080 + SPA）始终是保底交付形态。

## 结构

```
desktop/
  tauri.conf.json        Tauri 2 配置（窗口加载 http://127.0.0.1:18080）
  src-tauri/             Rust 外壳（最小实现：单窗口 WebView）
    Cargo.toml
    src/main.rs
    capabilities/default.json
  hub-sidecar.spec       PyInstaller 打包 Hub 为 sidecar 可执行文件
```

## 本地构建（需 Rust 1.80+ 与 Node 18+）

```bash
# 1) Hub sidecar（Python 侧）
pip install pyinstaller
pyinstaller desktop/hub-sidecar.spec                 # 产物 dist/uniagent-hub.exe

# 2) Tauri 外壳（把 sidecar 拷入 src-tauri/binaries/ 后）
cd desktop
npm install                                           # 或复用 web/spa 的前端产物
cargo tauri build
```

## CI 构建

Actions → Desktop Build → Run workflow：windows 矩阵，`tauri-action` 出安装包
（Artifact 下载）。当前为脚手架阶段，构建脚本随首个 Rust 工具链环境校准。

## 设计说明

- 外壳只加载本地 Dashboard（127.0.0.1:18080），不在 WebView 内执行任何业务逻辑；
- sidecar 化的 Hub 与直跑 Python 行为一致（同一 main.py 入口）；
- 内存目标 50–120MB（v2.0 §四），实测数据待首个构建产出后补充。
