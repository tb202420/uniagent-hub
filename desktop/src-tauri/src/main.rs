// UniAgent Hub 桌面外壳（最小实现）：单窗口加载本地 Dashboard。
// 业务逻辑全部在 Python Hub / Dashboard 中，外壳不做任何决策 ——
// 与"浏览器档同一事实源"的架构约束一致（v2.0 §四：桌面档 = 外壳 + 同一后端）。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("UniAgent Hub 桌面外壳启动失败");
}
