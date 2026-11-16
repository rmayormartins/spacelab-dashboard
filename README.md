# spacelab-dashboard

Dashboard estático (GitHub Pages) que busca quadros demodulados na rede SatNOGS e tenta decodificar telemetria e beacons dos satélites selecionados.

Author Ramon Mayor Martins, Ph.D. // @rmayormartins // IFSC SJ - Área de Telecomunicações

## Publicar

1. Crie o repositório `spacelab-dashboard` e envie todo o conteúdo desta pasta (incluindo `.github/`).
2. Settings > Pages > Deploy from a branch > `main` / root.
3. Settings > Actions > General > Workflow permissions > Read and write.
4. Actions > `coletar-satnogs` > Run workflow (depois ele roda sozinho a cada 30 min).
5. Abra `https://<usuario>.github.io/spacelab-dashboard/`.

## Arquivos

| Arquivo | Função |
|---|---|
| `index.html` | O dashboard inteiro, em um único arquivo |
| `satellites.json` | Quais satélites o coletor acompanha, estação e limites |
| `scripts/collect.py` | Coletor (Python puro) que grava `data/<norad>.json` |
| `.github/workflows/collect.yml` | Agenda o coletor e faz commit de `data/` |

## Motores de decodificação

1. **SPACELAB**: sync word `5D E6 2A 7E`, size tag NGHam, desembaralhamento CCSDS, Reed-Solomon (até 8 ou 16 bytes corrigidos), CRC-16 e campos conforme os layouts do `spacelab-decoder` (GOLDS-UFSC, FloripaSat-1, FloripaSat-2A, Catarina-A1/A2/A3).
2. **OFICIAL**: pacote `satnogs-decoders` do PyPI rodando no navegador via Pyodide. "Forçar decodificação" testa todos os decoders em uma amostra e ordena: cadastrado no SatNOGS DB, estritos, permissivos.
3. **NATIVO**: cabeçalho AX.25, hipótese de CSP e texto ASCII.
4. **Laboratório de bytes**: varredura de offsets com variação suave e campos manuais (offset, tipo, escala).

## Fontes de quadros

- `data/<norad>.json` do próprio repositório (rota garantida, não depende de CORS).
- SatNOGS Network direto do navegador: `/api/observations/` e os arquivos de `demoddata`.
- SatNOGS DB `/api/telemetry/` com o seu token (fica só no localStorage; para o coletor, crie o secret `SATNOGS_DB_TOKEN`).
- Colar hexadecimal, enviar arquivos ou gerar quadros simulados (sempre marcados como SIM).

Parâmetros de URL: `?sats=60237,59112&station=<id>`.

## Se o navegador bloquear as chamadas diretas

Os LEDs do topo e o botão "testar enlaces" mostram o que passou. Se Network ou QUADROS ficarem vermelhos, o coletor já resolve. Se quiser tempo real mesmo assim, publique este Worker no Cloudflare e cole a URL dele seguida de `/?url=` no campo de proxy:

```js
export default {
  async fetch(req) {
    const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Authorization" };
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    const u = new URL(req.url).searchParams.get("url");
    const ok = /^https:\/\/([a-z0-9-]+\.)*(satnogs\.org|fastly\.net|archive\.org)\//.test(u || "");
    if (!ok) return new Response("destino nao permitido", { status: 403, headers: cors });
    const auth = req.headers.get("Authorization");
    const r = await fetch(u, auth ? { headers: { Authorization: auth } } : {});
    const h = new Headers(r.headers);
    for (const k in cors) h.set(k, cors[k]);
    return new Response(r.body, { status: r.status, headers: h });
  }
};
```

## GOLDS-UFSC

O atalho GOLDS-UFSC já usa o layout do `spacelab-decoder` (VHF 145.900 MHz 1200 bd e UHF 468.400 MHz 4800 bd, NGHam/SLP). Antes do lançamento: use quadros simulados, quadros colados do seu fluxo GNU Radio ou `data/golds-ufsc.json`. Quando o SatNOGS DB criar a entrada, preencha o NORAD no painel e acrescente o satélite em `satellites.json`.

## Créditos e licenças

- Dados: SatNOGS / Libre Space Foundation, CC BY-SA.
- Layouts de pacotes: [spacelab-decoder](https://github.com/spacelab-ufsc/spacelab-decoder), SpaceLab/UFSC, GPLv3.
- Decoders oficiais: [satnogs-decoders](https://gitlab.com/librespacefoundation/satnogs/satnogs-decoders), AGPLv3, carregados em tempo de execução.
- NGHam: protocolo de Jon Petter Skagmo (LA3JPA); implementação conferida contra o [pyngham](https://github.com/mgm8/pyngham).

Como o `index.html` embute os layouts do spacelab-decoder, distribua este projeto sob GPLv3 ou compatível.
