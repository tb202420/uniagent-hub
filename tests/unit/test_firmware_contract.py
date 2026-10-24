"""ESP32 固件 ↔ 模拟器契约回归测试。

风险应对（开发规划风险1）：固件与 UniSpec 契约不一致是最大集成风险。
本测试静态提取固件 main.cpp 中的 UniSpec 原始字符串模板（占位替换后），
与模拟器 sim_esp32_greenhouse.UNISPEC 逐字段比对——固件任何破坏契约的
改动都会在此处失败，无需真机/编译器。
"""

import json
import re
from pathlib import Path

from adapters.mqtt_adapter.sim_esp32_greenhouse import (
    COMMAND_TOPIC, REGISTER_TOPIC, PUMP_MAX_DURATION_S, STATE_TOPIC, UNISPEC,
)

FW = (Path(__file__).resolve().parents[2]
      / "docs/hardware/firmware/esp32/src/main.cpp").read_text(encoding="utf-8")


def _firmware_unispec() -> dict:
    """提取 R\"JSONSPEC(...)JSONSPEC\" 模板并做与固件一致的占位替换（默认模式）。"""
    m = re.search(r'R"JSONSPEC\((.*?)\)JSONSPEC"', FW, re.S)
    assert m, "main.cpp 中未找到 UniSpec 原始字符串模板"
    tpl = m.group(1)
    tpl = tpl.replace("__TH_CAPS__", "")            # 默认 3 能力模式
    tpl = tpl.replace("__PREFIX__", "uniagent-hub-rxyc")
    tpl = tpl.replace("__PREFIX_TOOL__", "")
    tpl = tpl.replace("MQTT_BROKER", "mqtt://broker.example:1883")
    return json.loads(tpl)


def test_unispec_matches_simulator():
    fw = _firmware_unispec()
    # spec 级字段（name 允许不同：模拟器带"（模拟）"后缀）
    assert fw["id"] == UNISPEC["id"]
    assert fw["type"] == UNISPEC["type"]
    assert fw["protocol"] == UNISPEC["protocol"]
    assert fw["constraints"] == UNISPEC["constraints"]
    assert fw["endpoint"]["topic"] == UNISPEC["endpoint"]["topic"] == STATE_TOPIC
    assert fw["endpoint"]["command_topic"] == COMMAND_TOPIC
    # 能力逐字段（名称/description/inputSchema/readOnly/stateField）
    assert len(fw["capabilities"]) == 3
    for fw_cap, sim_cap in zip(fw["capabilities"], UNISPEC["capabilities"]):
        assert fw_cap["name"] == sim_cap["name"]
        assert fw_cap["description"] == sim_cap["description"]
        assert fw_cap["inputSchema"] == sim_cap["inputSchema"]
        assert fw_cap["outputSchema"] == sim_cap["outputSchema"]
        assert fw_cap["readOnly"] == sim_cap["readOnly"]
        assert fw_cap.get("stateField") == sim_cap.get("stateField")


def test_topic_constants_match_hub_convention():
    """固件内的 topic 字符串与 topics.py 计算结果一致（前缀默认值下）。"""
    assert 'TOPIC_PREFIX     "uniagent-hub-rxyc"' in FW
    assert REGISTER_TOPIC.endswith("register/irrigation_01")
    assert STATE_TOPIC.endswith("devices/irrigation_01/state")
    assert COMMAND_TOPIC.endswith("devices/irrigation_01/command")
    # 固件内三段 topic 拼接片段（宏展开后的后缀部分）
    assert '"/register/irrigation_01"' in FW
    assert '"/devices/irrigation_01/state"' in FW
    assert '"/devices/irrigation_01/command"' in FW


def test_pump_duration_contract():
    """600s 上限与 duration 钳位逻辑存在（clamp 契约对齐模拟器）。"""
    assert PUMP_MAX_DURATION_S == 600
    assert "PUMP_MAX_DURATION_S 600" in FW
    assert "clampDuration" in FW                    # 钳位函数
    assert "d > PUMP_MAX_DURATION_S) d = PUMP_MAX_DURATION_S" in FW
    assert "d < 1) d = 1" in FW


def test_command_ack_and_auto_stop():
    """命令回执（request_id）与到点自动停泵的实现存在。"""
    assert 'doc["request_id"] = g_lastRequestId' in FW
    assert "g_lastRequestId = String(cmd[\"request_id\"]" in FW
    assert "水泵自动停止" in FW and "g_pumpOffAtMs" in FW


def test_platformio_deps():
    """platformio.ini 声明 ArduinoJson 7 与 PubSubClient（构建可复现）。"""
    ini = (Path(__file__).resolve().parents[2]
           / "docs/hardware/firmware/esp32/platformio.ini").read_text(encoding="utf-8")
    assert "ArduinoJson@^7" in ini
    assert "PubSubClient" in ini
    assert "esp32-s3-devkitc-1" in ini


def test_full_mode_capability_names_unique():
    """FULL_CAPABILITIES=1 追加能力名合法（camelCase）且默认 3 能力名不冲突。"""
    th = re.search(r'static const char kThCapsJson\[\] =(.*?);', FW, re.S).group(1)
    names = re.findall(r'__PREFIX_TOOL__(\w+)', th)   # C++ 源内为 \" 转义，不能锚定尾引号
    assert set(names) == {"get_temperature", "get_humidity"}
    core = {c["name"] for c in _firmware_unispec()["capabilities"]}
    assert core == {"get_soil_moisture", "get_light_intensity", "control_pump"}
    assert not core & set(names)                     # 无重名
