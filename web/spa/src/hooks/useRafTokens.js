// RAF 批处理：token 增量先进缓冲区，每个动画帧 flush 一次（v3.0 性能硬约束）。
// 目的：把「每 token 一次重渲染」降为「每帧一次」，长输出不阻塞主线程。
import { useCallback, useEffect, useRef, useState } from 'react'

export function useRafTokens() {
  const [text, setText] = useState('')
  const buf = useRef('')
  const frames = useRef(0)
  const [flushFrames, setFlushFrames] = useState(0)

  useEffect(() => {
    let raf = 0
    const loop = () => {
      if (buf.current) {
        const chunk = buf.current
        buf.current = ''
        frames.current += 1
        setText((prev) => prev + chunk)
        setFlushFrames(frames.current)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  const push = useCallback((delta) => {
    if (!delta) return
    buf.current += delta
  }, [])

  const reset = useCallback(() => {
    buf.current = ''
    frames.current = 0
    setFlushFrames(0)
    setText('')
  }, [])

  return { text, push, reset, flushFrames }
}
