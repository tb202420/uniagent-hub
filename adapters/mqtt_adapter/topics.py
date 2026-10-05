"""MQTT Topic 约定（SUP-03：项目隔离前缀）。

公共 broker（broker.emqx.io）上存在他人流量，统一加项目唯一前缀避免
topic/client_id 冲突与演示干扰。前缀可通过 HUB_TOPIC_PREFIX 环境变量覆盖。

约定：
  {prefix}/register/{device_id}          设备上线注册（UniSpec，retain）
  {prefix}/devices/{device_id}/state     设备状态上报/回执
  {prefix}/devices/{device_id}/command   设备命令（写操作）
"""

from __future__ import annotations

import os

TOPIC_PREFIX = os.environ.get("HUB_TOPIC_PREFIX", "uniagent-hub-rxyc")

REGISTER_PREFIX = f"{TOPIC_PREFIX}/register"
DEVICES_PREFIX = f"{TOPIC_PREFIX}/devices"


def register_topic(device_id: str) -> str:
    return f"{REGISTER_PREFIX}/{device_id}"


def state_topic(device_id: str) -> str:
    return f"{DEVICES_PREFIX}/{device_id}/state"


def command_topic(device_id: str) -> str:
    return f"{DEVICES_PREFIX}/{device_id}/command"
