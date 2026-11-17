# spacelab-dashboard

Dashboard estático (GitHub Pages) que busca quadros demodulados na rede SatNOGS e tenta decodificar telemetria e beacons dos satélites selecionados. Também transforma o áudio das observações em imagem: APT dos NOAA e SSTV da ISS. O manual completo está no fim da própria página (seção MANUAL).

Author Ramon Mayor Martins, Ph.D. // @rmayormartins // IFSC SJ - Área de Telecomunicações // PU4MAY

## Publicar

1. Crie o repositório `spacelab-dashboard` e envie todo o conteúdo desta pasta (incluindo `.github/`).
2. Settings > Pages > Deploy from a branch > `main` / root.
3. Settings > Actions > General > Workflow permissions > Read and write.
4. Actions > `coletar-satnogs` > Run workflow. Depois ele roda pelo agendamento do GitHub (duas vezes por hora no arquivo), mas o GitHub trata esse agendamento como melhor esforço: em horários de carga as execuções atrasam ou são puladas. O botão Run workflow força uma coleta a qualquer momento.
5. Abra `https://<usuario>.github.io/spacelab-dashboard/`.

## Arquivos

| Arquivo | Função |
|---|---|
| `index.html` | O dashboard inteiro, em um único arquivo |
| `satellites.json` | Quais satélites o coletor acompanha, estação e limites |
| `scripts/collect.py` | Coletor (Python puro) que grava `data/<norad>.json` |
| `.github/workflows/collect.yml` | Agenda o coletor e faz commit de `data/` |
| `worker/worker.js` | Proxy no Cloudflare para as APIs do SatNOGS |
| `data/<norad>.json` | Quadros (`frames`) e produtos das últimas 60 observações (`obs`: imagens da estação, waterfall, áudio) |
| `data/catalog.json`, `data/stations.json` | Catálogo com transmissores ativos e país de cada estação |

## Motores de decodificação

1. **SPACELAB**: sync word `5D E6 2A 7E`, size tag NGHam, desembaralhamento CCSDS, Reed-Solomon (até 8 ou 16 bytes corrigidos), CRC-16 e campos conforme os layouts do `spacelab-decoder` (GOLDS-UFSC, FloripaSat-1, FloripaSat-2A, Catarina-A1/A2/A3).
2. **OFICIAL**: pacote `satnogs-decoders` do PyPI rodando no navegador via Pyodide. "Forçar decodificação" testa todos os decoders em uma amostra e ordena: cadastrado no SatNOGS DB, estritos, permissivos.
3. **NATIVO**: cabeçalho AX.25, hipótese de CSP e texto ASCII.
4. **MANUAL**: campos por offset definidos por você.

Cada quadro guarda o rastro do que cada motor tentou e por que falhou (bloco "como foi decodificado", na seção QUADROS), e a seção LOG_DECODE registra cada passagem pela cascata, com placar por motor e motivos de falha. O hexdump colore cada campo do layout e o cabeçalho AX.25.

Ferramentas para quadros que nenhum motor reconhece, na seção FORCA_BRUTA:

- **Força bruta**: roda os 169 decoders oficiais numa amostra e ordena quem aceitou.
- **Canivete suíço**: receita de operações em sequência (recorte, inversões de bits e bytes, XOR, deslocamento de bits, NRZI, G3RUH, Manchester, CCSDS, HDLC com FCS, KISS, NGHam, Reed-Solomon 255,223 e outras), com análises automáticas (entropia, marcadores de sincronismo mesmo desalinhados, indicativos AX.25, CRC no fim em 12 algoritmos, textos) e um inspetor de bytes. Uma receita que funcionou pode ser aplicada a todos os quadros do satélite.
- **Laboratório de bytes**: varredura de offsets com variação suave e campos manuais (offset, tipo, escala).

## Decode especial: imagens e áudio

A seção DECODE_ESPECIAL lista as observações do satélite com imagens publicadas pela estação, waterfall e áudio, e decodifica o áudio no próprio navegador (nada é enviado a servidor):

- **APT** (NOAA-15, 18 e 19, 137 MHz): demodulação AM da subportadora de 2400 Hz, sincronismo pelo Sync A, correção do erro de relógio. Os três NOAA foram desativados em 2025: use observações anteriores (o campo de data já vem preenchido). Áudio sem sincronismo APT é recusado.
- **SSTV** (ISS nos eventos ARISS): PD90 a PD290, Robot36, Martin M1/M2 e Scottie S1/S2/DX, com detecção pelo cabeçalho VIS, várias imagens por passagem e modo forçado quando o VIS se perdeu.
- **METEOR-M (LRPT)**: sinal digital que o áudio da observação não carrega; só as imagens das estações.

Também aceita um arquivo de áudio seu (WAV, OGG, MP3 ou FLAC).

## Fontes de quadros

- `data/<norad>.json` do próprio repositório (rota garantida, não depende de CORS).
- SatNOGS Network: `/api/observations/` pelo proxy e os arquivos de `demoddata`, waterfall e áudio direto do armazenamento (que libera o navegador).
- SatNOGS DB `/api/telemetry/` com o seu token (fica só no localStorage; para o coletor, crie o secret `SATNOGS_DB_TOKEN`).
- Colar hexadecimal, enviar arquivos ou gerar quadros simulados (sempre marcados como SIM).

Parâmetros de URL: `?sats=60237,59112&station=<id>`.

## Proxy

As APIs do SatNOGS (Network e DB) não liberam chamadas de outros sites (CORS), então o painel passa por um Worker no Cloudflare: o código está em `worker/worker.js` (só aceita destinos do SatNOGS e do archive.org e só atende este site) e o endereço fica no campo `proxy` do `satellites.json`. Imagens, waterfalls, áudios e quadros vêm direto do armazenamento, sem proxy. Os LEDs do topo e o botão "testar enlaces" mostram o que passou; sem proxy, o coletor do repositório continua funcionando.

## GOLDS-UFSC

O atalho GOLDS-UFSC já usa o layout do `spacelab-decoder` (VHF 145.900 MHz 1200 bd e UHF 468.400 MHz 4800 bd, NGHam/SLP). Antes do lançamento: use quadros simulados, quadros colados do seu fluxo GNU Radio ou `data/golds-ufsc.json`. Quando o SatNOGS DB criar a entrada, preencha o NORAD no painel e acrescente o satélite em `satellites.json`.

## Créditos e licenças

- Dados: SatNOGS / Libre Space Foundation, CC BY-SA.
- Layouts de pacotes: [spacelab-decoder](https://github.com/spacelab-ufsc/spacelab-decoder), SpaceLab/UFSC, GPLv3.
- Decoders oficiais: [satnogs-decoders](https://gitlab.com/librespacefoundation/satnogs/satnogs-decoders), AGPLv3, carregados em tempo de execução.
- NGHam: protocolo de Jon Petter Skagmo (LA3JPA); implementação conferida contra o [pyngham](https://github.com/mgm8/pyngham).

Como o `index.html` embute os layouts do spacelab-decoder, distribua este projeto sob GPLv3 ou compatível.
