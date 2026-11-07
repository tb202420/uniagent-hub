// 终端接管状态机（v3.0 控制层）：Agent 控制 ↔ 人工控制 双向切换。
// 用 Zustand 让状态跨页面共享（切到监视层再回来仍保持接管态）。
import { create } from 'zustand'

export const useTakeover = create((set) => ({
  mode: 'agent',
  setMode: (mode) => set({ mode }),
  toggle: () => set((s) => ({ mode: s.mode === 'human' ? 'agent' : 'human' })),
}))
