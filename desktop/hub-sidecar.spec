# PyInstaller 打包 UniAgent Hub 为桌面 sidecar 可执行文件（v2.0 §3.2）。
# 用法：pip install pyinstaller && pyinstaller desktop/hub-sidecar.spec
# 产物：dist/uniagent-hub.exe（与直跑 main.py 行为一致；配合 Tauri externalBin 使用）

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    datas=[
        # 适配器配置与工作流蓝图随包携带（specs/yaml）
        ("../adapters/cli_adapter/configs", "adapters/cli_adapter/configs"),
        ("../adapters/script_adapter/configs", "adapters/script_adapter/configs"),
        ("../adapters/script_adapter/scripts", "adapters/script_adapter/scripts"),
        ("../adapters/database_adapter/configs", "adapters/database_adapter/configs"),
        ("../adapters/rest_adapter/specs", "adapters/rest_adapter/specs"),
        ("../core/workflow/workflows.yaml", "core/workflow"),
        ("../core/workflow/workflows_hardware.yaml", "core/workflow"),
    ],
    hiddenimports=[
        "adapters.cli_adapter.adapter",
        "adapters.script_adapter.adapter",
        "adapters.database_adapter.adapter",
        "adapters.rest_adapter.adapter",
        "adapters.rest_adapter.openapi",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="uniagent-hub",
          console=True, onefile=False)
