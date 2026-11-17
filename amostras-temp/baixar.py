#!/usr/bin/env python3
"""Ramo temporario: baixa observacoes reais (audio + imagem da estacao) para
testar os decodificadores APT e SSTV do painel. Este ramo sera apagado."""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

NET = "https://network.satnogs.org/api"
UA = "spacelab-dashboard-amostras/1.0 (+https://rmayormartins.github.io/spacelab-dashboard/)"
OUT = "amostras"
MAXB = 16 * 1024 * 1024
os.makedirs(OUT, exist_ok=True)
resumo = {"probe": None, "arquivos": [], "notas": []}


def req(url, timeout=120):
    return urllib.request.Request(url, headers={"User-Agent": UA})


def get_json(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(req(url), timeout=120) as r:
                return json.loads(r.read().decode()), r.headers.get("Link") or ""
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < 2:
                time.sleep(6 * (i + 1)); continue
            raise


def get_bin(url):
    with urllib.request.urlopen(req(url), timeout=300) as r:
        b = r.read(MAXB + 1)
    if len(b) > MAXB:
        raise RuntimeError("arquivo grande demais")
    return b


def pages(params, n=6):
    url = f"{NET}/observations/?" + urllib.parse.urlencode({"format": "json", **params})
    k = 0
    while url and k < n:
        data, link = get_json(url)
        k += 1
        for o in (data if isinstance(data, list) else data.get("results", [])):
            yield o
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
        time.sleep(0.6)


def imgs(o):
    return [d.get("payload_demod") for d in (o.get("demoddata") or [])
            if re.search(r"\.(png|jpe?g)$", d.get("payload_demod") or "", re.I)]


def salvar(tag, o, want_img=True):
    oid = o["id"]
    audio = o.get("payload") or ""
    meta = {k: o.get(k) for k in ("id", "start", "end", "ground_station", "station_name", "norad_cat_id",
                                  "transmitter_mode", "transmitter_description", "transmitter_downlink_low",
                                  "observation_frequency", "payload", "waterfall", "archived", "archive_url",
                                  "status", "vetted_status", "demoddata")}
    try:
        if not audio:
            raise RuntimeError("sem audio (payload vazio)")
        b = get_bin(audio)
        fn = f"{OUT}/{tag}_{oid}.ogg"
        open(fn, "wb").write(b)
        meta["audio_file"] = fn
        print(f"  audio {fn}: {len(b)} bytes", flush=True)
    except Exception as e:
        meta["audio_erro"] = f"{type(e).__name__}: {e}"
        print(f"  audio falhou {oid}: {e}", flush=True)
    if want_img:
        for i, u in enumerate(imgs(o)[:3]):
            try:
                b = get_bin(u)
                ext = u.rsplit(".", 1)[-1].lower()
                fn = f"{OUT}/{tag}_{oid}_img{i}.{ext}"
                open(fn, "wb").write(b)
                meta.setdefault("img_files", []).append(fn)
            except Exception as e:
                meta.setdefault("img_erro", []).append(str(e))
    resumo["arquivos"].append({"tag": tag, **meta})
    return "audio_file" in meta


# 1) estrutura de uma observacao
for o in pages({"norad_cat_id": 25544, "status": "good"}, 1):
    resumo["probe"] = {"keys": sorted(o.keys()), "exemplo": {k: o[k] for k in list(o.keys())}}
    print("chaves da observacao:", sorted(o.keys()), flush=True)
    break

# 2) ISS SSTV: janelas de eventos ARISS (PD120 em 145.800, Robot36 em 437.550)
janelas = [("2026-10-19T00:00:00Z", "2026-10-28T00:00:00Z"),
           ("2026-05-08T00:00:00Z", "2026-05-13T00:00:00Z"),
           ("2026-04-10T00:00:00Z", "2026-04-15T00:00:00Z"),
           ("2025-11-12T00:00:00Z", "2025-11-21T00:00:00Z")]
com_img, so_audio = [], []
for a, b in janelas:
    try:
        n = 0
        for o in pages({"norad_cat_id": 25544, "status": "good", "start": a, "end": b}, 8):
            n += 1
            s = o.get("start") or ""
            if not (a <= s <= b):
                continue
            if not o.get("payload"):
                continue
            (com_img if imgs(o) else so_audio).append(o)
        print(f"janela {a[:10]}..{b[:10]}: {n} observacoes lidas, {len(com_img)} com imagem, {len(so_audio)} so audio", flush=True)
    except Exception as e:
        resumo["notas"].append(f"janela {a}: {e}")
        print("janela falhou", a, e, flush=True)
    if len(com_img) >= 2:
        break
feitos = 0
for o in com_img[:2]:
    feitos += salvar("iss_sstv", o)
for o in so_audio:
    if feitos >= 3:
        break
    f = str(o.get("observation_frequency") or o.get("transmitter_downlink_low") or "")
    feitos += salvar("iss_audio", o, want_img=False)

# 3) NOAA APT (historico, satelites desativados em 2025)
for norad, tag in ((33591, "noaa19"), (25338, "noaa15")):
    try:
        ok = False
        for o in pages({"norad_cat_id": norad, "status": "good"}, 6):
            if imgs(o) and o.get("payload"):
                ok = salvar(tag, o)
                if ok:
                    break
        if ok:
            break
        resumo["notas"].append(f"{tag}: nenhuma observacao com audio e imagem nas paginas lidas")
    except Exception as e:
        resumo["notas"].append(f"{tag}: {e}")

json.dump(resumo, open(f"{OUT}/resumo.json", "w"), indent=1, default=str)
print(json.dumps({"arquivos": [(x["tag"], x["id"], x.get("audio_file"), x.get("img_files"), x.get("audio_erro")) for x in resumo["arquivos"]], "notas": resumo["notas"]}, indent=1), flush=True)
