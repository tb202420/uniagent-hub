// Dashboard JSON API 客户端（同源；Basic Auth 由浏览器首次认证后复用）
export async function getJSON(path) {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`)
  return resp.json()
}

export async function postJSON(path, body) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(data.error || `${path} -> HTTP ${resp.status}`)
  return data
}
