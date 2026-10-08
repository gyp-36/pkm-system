// Serve the actual production bundle; proxy only to the separate validation API.
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
const root = '/app/dist'
http.createServer((req, res) => {
  if (/^\/(v1|health|docs|openapi)/.test(req.url)) {
    const upstream = http.request({ host: 'api', port: 8001, path: req.url, method: req.method, headers: req.headers }, response => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res)
    })
    upstream.on('error', () => { res.writeHead(502); res.end('Validation API unavailable') })
    req.pipe(upstream); return
  }
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
  let file = path.resolve(root, '.' + pathname)
  if (!file.startsWith(root + '/') && file !== root) { res.writeHead(403); res.end(); return }
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) file = path.join(root, 'index.html')
  const type = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml' }[path.extname(file)] || 'application/octet-stream'
  res.writeHead(200, { 'Content-Type': type }); fs.createReadStream(file).pipe(res)
}).listen(5173, '0.0.0.0')
