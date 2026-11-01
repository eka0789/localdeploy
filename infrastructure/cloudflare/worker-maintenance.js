/**
 * LocalDeploy — Cloudflare Worker: maintenance fallback
 * =====================================================
 * Saat PC/server LocalDeploy mati atau internet putus, pengunjung tetap
 * dilayani halaman maintenance yang rapi alih-alih error 502/522 jelek.
 * Origin hidup lagi → trafik otomatis kembali normal, tanpa konfigurasi ulang.
 *
 * PASANG (gratis):
 *   1. Cloudflare Dashboard → Workers & Pages → Create Worker → paste file ini → Deploy
 *   2. Worker → Settings → Variables:
 *        ORIGIN_HOST      = toko.namadomain.com          (hostname asal aplikasi)
 *        TIMEOUT_MS       = 3000                         (opsional, default 3000)
 *        MAINTENANCE_HTML = <html>…kustom…</html>        (opsional)
 *   3. Domain → Workers Routes: tambahkan route  toko.namadomain.com/*  → worker ini
 *      (atau pasang permanen — worker meneruskan trafik normal saat origin hidup)
 */

const MAINTENANCE_PAGE = `<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Segera Kembali — Maintenance</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       background:#0b1220;color:#e2e8f0;text-align:center;padding:24px}
  .card{max-width:480px}
  .dot{width:12px;height:12px;border-radius:50%;background:#f59e0b;display:inline-block;
       animation:pulse 1.2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  h1{font-size:1.6rem;margin:.6em 0}
  p{color:#94a3b8;line-height:1.6}
  code{background:#1e293b;padding:2px 8px;border-radius:6px;font-size:.85em}
</style>
</head>
<body><div class="card">
  <span class="dot"></span>
  <h1>Kami sedang melakukan pemeliharaan</h1>
  <p>Server sedang tidak dapat dijangkau untuk sesaat. Layanan akan kembali
     otomatis beberapa saat lagi — tidak ada data yang hilang.</p>
  <p>Butuh bantuan segera? Hubungi kami melalui kontak yang tersedia.</p>
  <p><code>LocalDeploy · origin offline</code></p>
</div></body></html>`;

export default {
  async fetch(request, env) {
    const originHost = env.ORIGIN_HOST || new URL(request.url).hostname;
    const timeoutMs = Number(env.TIMEOUT_MS || 3000);

    const originUrl = new URL(request.url);
    originUrl.hostname = originHost;

    try {
      const originResponse = await fetch(originUrl.toString(), {
        method: request.method,
        headers: filterHeaders(request.headers, originHost),
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        redirect: "manual",
        signal: AbortSignal.timeout(timeoutMs),
      });

      // Origin menjawab 5xx / 52x dari tunnel → tampilkan maintenance
      if (originResponse.status >= 500) {
        return maintenanceResponse(env);
      }
      const response = new Response(originResponse.body, originResponse);
      response.headers.set("x-localdeploy-fallback", "origin-ok");
      return response;
    } catch (err) {
      // timeout / connection refused / tunnel down → maintenance page
      return maintenanceResponse(env);
    }
  },
};

function maintenanceResponse(env) {
  const html = env.MAINTENANCE_HTML || MAINTENANCE_PAGE;
  return new Response(html, {
    status: 503,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Retry-After": "60",
      "x-localdeploy-fallback": "maintenance",
    },
  });
}

function filterHeaders(headers, originHost) {
  const filtered = new Headers();
  for (const [key, value] of headers.entries()) {
    if (["cf-connecting-ip", "cf-ray", "cf-visitor", "cdn-loop"].includes(key.toLowerCase())) continue;
    if (key.toLowerCase() === "host") { filtered.set("host", originHost); continue; }
    filtered.set(key, value);
  }
  return filtered;
}
