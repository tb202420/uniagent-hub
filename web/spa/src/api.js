// Dashboard JSON API 客户端（同源；Basic Auth 由浏览器首次认证后复用）
export async function getJSON(path) {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`)
  return resp.json()
}
