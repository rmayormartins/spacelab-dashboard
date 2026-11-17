#!/usr/bin/env python3
"""Coletor do spacelab-dashboard.

Le satellites.json, consulta a SatNOGS Network (e o SatNOGS DB, se houver
token), baixa os quadros demodulados e grava data/<norad>.json para o
dashboard estatico. So usa a biblioteca padrao do Python.

Variaveis de ambiente opcionais:
  SATNOGS_DB_TOKEN  token pessoal do db.satnogs.org (Settings / API Token)
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
NET = "https://network.satnogs.org/api"
DB = "https://db.satnogs.org/api"
UA = "spacelab-dashboard-collector/1.0 (+github pages dashboard)"
SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|ogg|webp)(\?|$)", re.I)
TS_RX = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})")


def note(level, msg):
    """Imprime e gera anotacao visivel no resumo da execucao do GitHub Actions."""
    print(f"::{level}::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"[{level}] {msg}", flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- **{level}**: {msg}\n")


def explain(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} {e.reason}"
    if isinstance(e, urllib.error.URLError):
        return f"sem conexao ({e.reason})"
    if isinstance(e, TimeoutError):
        return "tempo esgotado"
    return f"{type(e).__name__}: {e}"


def http(url, headers=None, binary=False, tries=3, timeout=90):
    """GET com espera educada em 429/5xx. Retorna (corpo, cabecalhos)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                return (body if binary else body.decode("utf-8")), r.headers
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                wait = int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
                print(f"  HTTP {e.code}, esperando {wait}s", flush=True)
                time.sleep(min(wait, 120))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError("sem resposta: " + url)


def next_link(headers):
    m = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("Link") or "")
    return m.group(1) if m else None


def frame_time(url, fallback):
    m = TS_RX.search(url)
    if m:
        return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}Z"
    return fallback


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def sat_id_of(norad):
    """Identificador SatNOGS (sat_id) do satelite, usado como filtro alternativo."""
    try:
        body, _ = http(f"{DB}/satellites/?format=json&norad_cat_id={norad}", tries=2)
        for s in json.loads(body):
            if s.get("norad_cat_id") == norad and s.get("sat_id"):
                return s["sat_id"]
    except Exception as e:
        print(f"  sat_id indisponivel: {explain(e)}", flush=True)
    return None


def first_page(norad, cfg):
    """Descobre qual filtro de satelite a Network API respeita.

    A API ignora em silencio parametros que nao conhece e devolve observacoes
    de qualquer satelite. Por isso cada candidato so e aceito se TODAS as
    observacoes devolvidas forem do NORAD pedido.
    """
    base = {"format": "json"}
    if cfg.get("only_good", True):
        base["status"] = "good"
    if cfg.get("station"):
        base["ground_station"] = cfg["station"]
    if cfg.get("days"):
        since = datetime.now(timezone.utc) - timedelta(days=int(cfg["days"]))
        base["start"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    candidates = [("satellite__norad_cat_id", norad), ("norad_cat_id", norad), ("norad", norad)]
    empty, ignored = None, []
    for i in range(4):
        if i == 3:
            sid = sat_id_of(norad)
            if not sid:
                break
            key, val = "sat_id", sid
        else:
            key, val = candidates[i]
        url = f"{NET}/observations/?{urllib.parse.urlencode({**base, key: val})}"
        body, headers = http(url)
        page = json.loads(body)
        page = page if isinstance(page, list) else page.get("results", [])
        got = {o.get("norad_cat_id") for o in page}
        if page and got == {norad}:
            print(f"  filtro aceito: {key} ({len(page)} observacoes na 1a pagina)", flush=True)
            return page, headers
        if not page:
            empty = (page, headers)
            print(f"  filtro {key}: pagina vazia", flush=True)
        else:
            ignored.append(key)
            print(f"  filtro {key}: ignorado pela API (veio NORAD {sorted(x for x in got if x)[:5]})", flush=True)
        time.sleep(0.5)
    if empty:
        return empty
    raise RuntimeError("a API ignorou os filtros de satelite testados: " + ", ".join(ignored))


def collect_network(norad, cfg, done_obs):
    """Lista observacoes do satelite e baixa os quadros das que ainda nao foram vistas."""
    frames, pages, seen = [], 0, []
    budget = int(cfg.get("max_frames", 400))
    page, headers = first_page(norad, cfg)
    while page and len(frames) < budget:
        pages += 1
        for obs in page:
            oid = obs.get("id")
            if obs.get("norad_cat_id") != norad or oid in done_obs:
                continue
            ok = True
            for item in obs.get("demoddata") or []:
                furl = item.get("payload_demod")
                if not furl or SKIP_EXT.search(furl):
                    continue
                if len(frames) >= budget:
                    ok = False
                    break
                try:
                    raw, _ = http(furl, binary=True)
                except Exception as e:  # um quadro ruim nao derruba a coleta
                    print(f"  quadro falhou ({explain(e)}): {furl}", flush=True)
                    ok = False
                    continue
                if raw:
                    frames.append({
                        "t": frame_time(furl, obs.get("start")),
                        "hex": raw.hex(),
                        "obs": oid,
                        "gs": obs.get("ground_station"),
                        "station": obs.get("station_name") or "",
                        "src": "net",
                    })
                time.sleep(0.05)
            if ok and obs.get("status") != "future":
                seen.append(oid)
        url = next_link(headers)
        if not url or pages >= int(cfg.get("max_pages", 6)):
            break
        time.sleep(0.5)
        body, headers = http(url)
        page = json.loads(body)
        page = page if isinstance(page, list) else page.get("results", [])
    return frames, seen


def collect_db(norad, token, budget):
    url = f"{DB}/telemetry/?format=json&satellite={norad}"
    frames = []
    while url and len(frames) < budget:
        body, _ = http(url, headers={"Authorization": "Token " + token})
        j = json.loads(body)
        rows = j.get("results", []) if isinstance(j, dict) else j
        if not rows:
            break
        for r in rows:
            if r.get("frame"):
                frames.append({
                    "t": r.get("timestamp"),
                    "hex": r["frame"].lower(),
                    "obs": r.get("observation_id"),
                    "gs": r.get("station_id"),
                    "station": r.get("observer") or "",
                    "src": "db",
                })
        url = j.get("next") if isinstance(j, dict) else None
        time.sleep(0.5)
    return frames


def main():
    cfg = load(os.path.join(ROOT, "satellites.json"), None)
    if not cfg:
        sys.exit("satellites.json ausente ou invalido")
    os.makedirs(DATA, exist_ok=True)
    token = os.environ.get("SATNOGS_DB_TOKEN", "").strip()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index, errors, reasons = [], 0, []
    for label, probe in (("Network", f"{NET}/stations/?format=json&id=1"), ("DB", f"{DB}/modes/?format=json")):
        t0 = time.time()
        try:
            http(probe, tries=1, timeout=30)
            print(f"sonda {label}: OK em {time.time() - t0:.1f}s", flush=True)
        except Exception as e:
            note("warning", f"sonda SatNOGS {label} falhou em {time.time() - t0:.0f}s: {explain(e)}")
    for sat in cfg.get("satellites", []):
        norad, name = sat.get("norad"), sat.get("name") or str(sat.get("norad"))
        if not norad:
            continue
        path = os.path.join(DATA, f"{norad}.json")
        old = load(path, {})
        if old.get("schema") != 2:  # caches antigos podiam misturar satelites
            old = {}
        frames = old.get("frames", [])
        done = set(old.get("obs_done", []))
        print(f"{name} ({norad}): {len(frames)} quadros em cache", flush=True)
        new, seen = [], []
        try:
            scfg = {**cfg, **{k: v for k, v in sat.items() if k in ("days", "station", "max_frames", "max_pages", "only_good")}}
            new, seen = collect_network(norad, scfg, done)
            print(f"  network: {len(new)} quadros novos em {len(seen)} observacoes", flush=True)
        except Exception as e:
            errors += 1
            reasons.append(f"{name}: Network {explain(e)}")
            note("warning", f"{name} ({norad}): Network API falhou: {explain(e)}")
        if token:
            try:
                dbf = collect_db(norad, token, int(cfg.get("max_frames", 400)))
                print(f"  db: {len(dbf)} quadros", flush=True)
                new += dbf
            except Exception as e:
                errors += 1
                note("warning", f"{name} ({norad}): DB falhou: {explain(e)}")
        merged = {}
        for f in frames + new:
            if f.get("hex") and f.get("t"):
                merged[(f["t"], f["hex"], f.get("gs"))] = f
        frames = sorted(merged.values(), key=lambda f: f["t"])[-int(cfg.get("max_frames", 400)):]
        changed = len(frames) != len(old.get("frames", [])) or bool(new)
        out = {
            "schema": 2,
            "norad": norad,
            "name": name,
            "updated": now if changed else old.get("updated", now),
            "frames": frames,
            "obs_done": sorted(done | set(seen))[-3000:],
        }
        if changed or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, separators=(",", ":"))
        index.append({"norad": norad, "name": name, "frames": len(frames),
                      "last": frames[-1]["t"] if frames else None, "updated": out["updated"]})
    # catalogo para a busca do dashboard quando o navegador bloqueia o SatNOGS DB
    try:
        body, _ = http(f"{DB}/satellites/?format=json")
        items = [{"n": s["norad_cat_id"], "name": s.get("name") or "", "alt": s.get("names") or "",
                  "st": s.get("status") or "",
                  "dec": [t["decoder"] for t in (s.get("telemetries") or []) if t.get("decoder")]}
                 for s in json.loads(body) if s.get("norad_cat_id")]
        try:  # transmissores ativos por satelite, para o filtro "ativos" do painel
            tbody, _ = http(f"{DB}/transmitters/?format=json&alive=true&status=active", timeout=120)
            count = {}
            for t in json.loads(tbody):
                if t.get("alive") and t.get("status", "active") == "active" and t.get("downlink_low"):
                    count[t.get("norad_cat_id")] = count.get(t.get("norad_cat_id"), 0) + 1
            if count:
                for it in items:
                    it["tx"] = count.get(it["n"], 0)
            print(f"transmissores ativos: {sum(count.values())} em {len(count)} satelites", flush=True)
        except Exception as e:
            note("warning", f"lista de transmissores falhou: {explain(e)}")
        cat_path = os.path.join(DATA, "catalog.json")
        if items and load(cat_path, {}).get("items") != items:
            with open(cat_path, "w", encoding="utf-8") as f:
                json.dump({"updated": now, "items": items}, f, separators=(",", ":"), ensure_ascii=False)
        print(f"catalogo: {len(items)} satelites", flush=True)
    except Exception as e:
        note("warning", f"catalogo do SatNOGS DB falhou: {explain(e)}")
    old_index = load(os.path.join(DATA, "index.json"), {})
    if old_index.get("satellites") != index:
        with open(os.path.join(DATA, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"updated": now, "satellites": index}, f, indent=1)
    total = sum(s["frames"] for s in index)
    note("notice", f"coleta terminou: {total} quadros em data/, {errors} erros")
    if errors and not total:
        note("error", "nenhum quadro coletado. Motivos: " + "; ".join(reasons[:4]))
        sys.exit(1)


if __name__ == "__main__":
    main()
