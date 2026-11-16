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
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
NET = "https://network.satnogs.org/api"
DB = "https://db.satnogs.org/api"
UA = "spacelab-dashboard-collector/1.0 (+github pages dashboard)"
SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|ogg|webp)(\?|$)", re.I)
TS_RX = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})")


def http(url, headers=None, binary=False, tries=4):
    """GET com espera educada em 429/5xx. Retorna (corpo, cabecalhos)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
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


def collect_network(norad, cfg, done_obs):
    """Lista observacoes e baixa os quadros das que ainda nao foram vistas."""
    q = {"format": "json", "satellite__norad_cat_id": norad}
    if cfg.get("only_good", True):
        q["status"] = "good"
    if cfg.get("station"):
        q["ground_station"] = cfg["station"]
    url = f"{NET}/observations/?{urllib.parse.urlencode(q)}"
    frames, pages, seen = [], 0, []
    budget = int(cfg.get("max_frames", 400))
    while url and pages < int(cfg.get("max_pages", 6)) and len(frames) < budget:
        body, headers = http(url)
        page = json.loads(body)
        page = page if isinstance(page, list) else page.get("results", [])
        pages += 1
        if not page:
            break
        for obs in page:
            oid = obs.get("id")
            demod = obs.get("demoddata") or []
            if oid in done_obs:
                continue
            ok = True
            for item in demod:
                furl = item.get("payload_demod")
                if not furl or SKIP_EXT.search(furl):
                    continue
                if len(frames) >= budget:
                    ok = False
                    break
                try:
                    raw, _ = http(furl, binary=True)
                except Exception as e:  # um quadro ruim nao derruba a coleta
                    print(f"  quadro falhou ({e}): {furl}", flush=True)
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
        time.sleep(0.5)
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
    index, errors = [], 0
    for sat in cfg.get("satellites", []):
        norad, name = sat.get("norad"), sat.get("name") or str(sat.get("norad"))
        if not norad:
            continue
        path = os.path.join(DATA, f"{norad}.json")
        old = load(path, {})
        frames = old.get("frames", [])
        done = set(old.get("obs_done", []))
        print(f"{name} ({norad}): {len(frames)} quadros em cache", flush=True)
        new, seen = [], []
        try:
            new, seen = collect_network(norad, cfg, done)
            print(f"  network: {len(new)} quadros novos em {len(seen)} observacoes", flush=True)
        except Exception as e:
            errors += 1
            print(f"  network falhou: {e}", flush=True)
        if token:
            try:
                dbf = collect_db(norad, token, int(cfg.get("max_frames", 400)))
                print(f"  db: {len(dbf)} quadros", flush=True)
                new += dbf
            except Exception as e:
                errors += 1
                print(f"  db falhou: {e}", flush=True)
        merged = {}
        for f in frames + new:
            if f.get("hex") and f.get("t"):
                merged[(f["t"], f["hex"], f.get("gs"))] = f
        frames = sorted(merged.values(), key=lambda f: f["t"])[-int(cfg.get("max_frames", 400)):]
        changed = len(frames) != len(old.get("frames", [])) or bool(new)
        out = {
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
    old_index = load(os.path.join(DATA, "index.json"), {})
    if old_index.get("satellites") != index:
        with open(os.path.join(DATA, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"updated": now, "satellites": index}, f, indent=1)
    if errors and not any(s["frames"] for s in index):
        sys.exit("todas as coletas falharam")


if __name__ == "__main__":
    main()
