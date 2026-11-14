import { useEffect, useRef, useState } from 'react'
import { getEventStream } from '../eventStream.js'

export function useEventStream(handler) {
  const ref = useRef(handler)
  ref.current = handler
  const [status, setStatus] = useState('idle')

  useEffect(() => {
    const stream = getEventStream()
    const unsubscribe = stream.subscribe((event) => {
      if (event.kind === '__status') setStatus(event.status)
      else ref.current(event)
    })
    return unsubscribe
  }, [])

  return status
}
