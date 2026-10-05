# UniAgent Hub 生成的 CLI 工具

由平台反向生成（MCP Tool → CLI 脚本），与 `tools/call` 等价。

Hub 地址：`http://127.0.0.1:8020`（可用环境变量 `HUB_URL` 覆盖）

## 使用
```bash
python gen_git_status.py --repo_path /path/to/your/repo
```

## 工具列表
- `gen_git_status.py`：查看指定仓库的 Git 工作区状态（只读）
- `gen_file_search.py`：在指定目录搜索匹配文件名的文件（Windows：where /r）
- `gen_get_weather.py`：获取指定经纬度的当前天气
- `gen_file_summary.py`：统计指定目录下文件数量与清单（只读）
- `gen_get_ac_state.py`：获取空调当前状态（开关/设定温度）
- `gen_ac_control.py`：控制空调开关与设定温度（write 级）
- `gen_get_temperature.py`：获取客厅当前温度（摄氏度）
- `gen_get_humidity.py`：获取客厅当前湿度（%）
- `gen_db_query.py`：只读查询演示数据库（仅允许 SELECT 单语句，会议室台账表 meeting_rooms）
- `gen_db_execute.py`：对演示数据库执行受限写操作（INSERT/UPDATE/DELETE 单语句，需 write 权限）
