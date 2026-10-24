# 桌面档（Tauri 2 外壳 + PyInstaller sidecar 脚手架）

v2.0 §3.2/§四 的桌面形态。**本目录为脚手架**：本地无 Rust 工具链时不必构建，
由 CI（`.github/workflows/desktop-build.yml`，手动触发）产出安装包；浏览器档
（Dashboard :18080 + SPA）始终是保底交付形态。

> **本地构建状态（2026-10-24 实测：✅ 编译通过）**：Rust 1.99.1 + VS Build Tools 2022
> （MSVC 14.44 / Win SDK 10.0.26100），`desktop/build-local.cmd` 一键构建，
> `cargo build --release` **16.6 秒**完成，产物
> `src-tauri/target/release/uniagent-hub-desktop.exe`（9.4MB，release 优化档）。
>
> 已知环境坑（已在本仓库解决）：winget 安装 Build Tools 后 vswhere 未注册实例，
> rustc 找不到 link.exe —— `build-local.cmd` 通过直接注入 MSVC/SDK 的
> PATH/LIB/INCLUDE 绕过 vswhere。图标由 `src-tauri/icons/icon.ico` 提供
>（Windows 资源必需）。**未做**：NSIS 安装包打包与窗口运行实测（CI Desktop Build
> 产出安装包）—— 三态口径维持"外壳已编译验证，不宣称桌面版完成"。

## 结构

```
desktop/
  build-local.cmd        一键本地构建（注入 MSVC 环境，绕过 vswhere 坑）
  src-tauri/
    tauri.conf.json      Tauri 2 配置（窗口加载 http://127.0.0.1:18080）
    icons/icon.ico       应用图标（Windows 资源必需）
    ...                  Rust 外壳（最小实现：单窗口 WebView）
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
