"""Agent 插件宿主（v2.0 §3.3）：统一 AgentAdapter 接口 + entry_points 动态发现。

Hub 核心零 import 具体 Agent 平台；内置三个适配器（script / ollama / openai-compat），
第三方以 entry_points 组 `uniagent_hub.agent_adapters` 接入（类需提供 NAME 属性）。
"""
