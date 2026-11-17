// Proxy CORS do spacelab-dashboard para as APIs e arquivos do SatNOGS.
// Publique no Cloudflare Workers e cole no painel:  https://SEU-WORKER.workers.dev/?url=
const ALLOWED_ORIGINS = ["https://rmayormartins.github.io", "http://localhost:8000"];
const ALLOWED_HOSTS = /^https:\/\/([a-z0-9-]+\.)*(satnogs\.org|fastly\.net|archive\.org)\//;

const okOrigin = (o) => ALLOWED_ORIGINS.includes(o) || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(o);

export default {
  async fetch(req) {
    const origin = req.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": okOrigin(origin) ? origin : ALLOWED_ORIGINS[0],
      "Access-Control-Allow-Headers": "Authorization",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Vary": "Origin",
    };
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (req.method !== "GET") return new Response("apenas GET", { status: 405, headers: cors });
    if (origin && !okOrigin(origin)) return new Response("proxy: origem nao permitida (" + origin + ")", { status: 403, headers: cors });
    const u = new URL(req.url);
    let target = u.searchParams.get("url") || "";
    if (!target && u.pathname.length > 1) target = decodeURIComponent(u.pathname.slice(1)) + (u.pathname.includes("%3F") ? "" : u.search);
    if (!ALLOWED_HOSTS.test(target)) return new Response("proxy: destino nao permitido (" + target.slice(0, 80) + ")", { status: 403, headers: cors });
    const h = { "User-Agent": "spacelab-dashboard-proxy/1.1 (+https://rmayormartins.github.io/spacelab-dashboard/)", "Accept": "application/json, */*" };
    const auth = req.headers.get("Authorization");
    if (auth) h.Authorization = auth;
    const upstream = await fetch(target, { headers: h, redirect: "follow" });
    const headers = new Headers(cors);
    headers.set("X-Proxy-Upstream-Status", String(upstream.status));
    headers.set("Access-Control-Expose-Headers", "X-Proxy-Upstream-Status");
    if (!upstream.ok) {
      const text = (await upstream.text()).slice(0, 300);
      return new Response("proxy ok, mas o SatNOGS respondeu HTTP " + upstream.status + ": " + text, { status: upstream.status, headers });
    }
    headers.set("Content-Type", upstream.headers.get("Content-Type") || "application/octet-stream");
    headers.set("Cache-Control", "public, max-age=60");
    return new Response(upstream.body, { status: upstream.status, headers });
  },
};
