#!/usr/bin/env bash
O="Origin: https://rmayormartins.github.io"
W="https://s3.eu-central-1.wasabisys.com/satnogs-network/data_obs/2026/10/26/15/15290852/waterfall_15290852_2026-10-26T15-58-27.png"
F="https://s3.eu-central-1.wasabisys.com/satnogs-network/data_obs/2026/10/27/22/15291125/data_15291125_2026-10-27T23-01-26"
A="https://network-satnogs.freetls.fastly.net/media/data_obs/2026/10/27/22/15291125/satnogs_15291125_2026-10-27T22-59-35.ogg"
q(){ python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "$1"; }
echo "=== direto (wasabi waterfall, wasabi quadro, fastly audio) com Origin"
for u in "$W" "$F" "$A"; do echo "-- $u"; curl -s -o /dev/null -D - -H "$O" "$u" | grep -iE "^HTTP|access-control|content-type|content-length"; done
echo "=== preflight OPTIONS no wasabi"
curl -s -o /dev/null -D - -X OPTIONS -H "$O" -H "Access-Control-Request-Method: GET" "$F" | grep -iE "^HTTP|access-control"
echo "=== Worker do usuario"
P="https://satnogs-proxy.rmayormartins.workers.dev/?url="
for u in "$F" "$A" "https://network.satnogs.org/api/observations/?format=json&norad_cat_id=25544"; do echo "-- via proxy: $u"; curl -s -D - -o /tmp/b -H "$O" "$P$(q "$u")" | grep -iE "^HTTP|access-control|x-proxy|content-type"; head -c 100 /tmp/b | tr -c '[:print:]' '.'; echo; done
