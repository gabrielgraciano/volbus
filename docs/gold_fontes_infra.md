---
title: "Gold — fontes de infraestrutura (KR4)"
subtitle: "Onde baixar tipo de via, faixas, corredores e alagamentos de São Paulo"
author: "Projeto Ônibus SP × Chuva"
date: "25/10/2026, atualizado em 02/11/2026"
lang: pt-BR
---

# Resumo

- **GeoSampa cobre quase tudo, aberto (CC BY-SA 4.0).** WFS público sem autenticação (`https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs`, GeoServer, 485 camadas, EPSG:31983; exporta GeoJSON, GPKG, SHAPE-ZIP, CSV) e servidor de arquivos prontos (`download.geosampa.prefeitura.sp.gov.br`). Ambos testados com curl deste PC em 25/10: respondem 200, sem anti-bot (só o portal `geosampa.prefeitura...` tem proteção F5).
- **WFS devolve no máximo 30.000 feições por requisição:** paginar com `count`, `startIndex` e `sortBy`.
- **Alagamento:** a camada WFS "Alagamento" tem só o ano corrente; a série 2013–2026 (Defesa Civil/SIGRC) está no servidor de arquivos; o CGE tem histórico diário desde ~2008 com hora e transitável/intransitável, só em HTML.
- **O Databricks não alcança esses servidores** (rede restrita a PyPI e googleapis): baixar no PC e subir para `/Volumes/onibus/bronze/raw/infra/`.
- Atribuição exigida: "Fonte: GeoSampa/PMSP".

# Versão baixada (02/11/2026)

Em `/Volumes/onibus/bronze/raw/infra/versao=2026-11-02/`, com `manifesto.csv` (arquivo, feições, bytes, sha256, data e URL). O notebook 11 confere os hashes antes de ler.

| Arquivo | Conteúdo | Feições | Tamanho |
|---|---|---|---|
| `SIRGAS_GPKG_classeviariacet.zip` | 1 GPKG | 210.754 (LOCAL 133.098; COLETORA 50.641; ARTERIAL 21.707; VIA DE PEDESTRES 4.232; RODOVIA 648; VTR 428) | 59,2 MB |
| `faixa_onibus.gpkg` | faixas | 7.378 (EXCLUSIVA 7.003; PREFERENCIAL 231; REVERSÍVEL 103; TEMPORÁRIA 41) | 3,0 MB |
| `corredor_onibus.gpkg` | corredores | 45 (40 em operação, 2 em implantação, 3 futuros; 33 SPTrans e 12 EMTU) | 0,2 MB |
| `SIRGAS_GPKG_riscoocorrencia.zip` | **14 GPKG, um por ano**, 2013 a 09/2026 | 68.946 (ALAGAMENTO + INUNDAÇÃO: 12.625) | 11,3 MB |

**Armadilhas dos arquivos:**
- `qt_metro_faixa` está vazia nas 7.378 faixas: o comprimento sai da geometria (779 km). `dt_implantacao_faixa` tem 289 nulos.
- Faixas no eixo da via, sem indicar o sentido pela geometria (ver `gold_desenho`, seção 2.8).
- Os GPKG de ocorrências mudam de um ano para outro: 2026 tem `primaryindex`, `subpreit` e ponto com M. `data`, `ocorrencia` e a geometria existem em todos.
- Ocorrências em bloco: 2016 tem 4.210 alagamentos, com 3.115 em 3 dias (09/01, 24/02 e 25/02) e 3.361 registros de toda natureza em São Miguel Paulista. Contar dias distintos, não registros.
- O ambiente Python do PC não tem biblioteca geográfica: o teste roda num venv, com `analises/gold_exploracao/testa_11.py`.

# Tabela priorizada

| Prior. | Item | Acesso | Formato / CRS | Período | Tamanho | Junção ao trecho |
|---|---|---|---|---|---|---|
| 1 | **Classificação Viária CET** (VTR, arterial, coletora, local, rodovia) | WFS `geoportal:classificacao_viaria_cet`; arquivo `SIRGAS_GPKG_classeviariacet.zip` | GPKG/SHP/WFS, EPSG:31983 | Portaria DSV.G 018/19; revisão 19/02/2026; 1:10.000 | 210.754 trechos; GPKG zip 59 MB | buffer 12–15 m + filtro de rumo < 30° → fração por classe e classe dominante |
| 1 | **Faixas exclusivas** | WFS `geoportal:faixa_onibus` (uma requisição) | EPSG:31983 | metadados 08/2021; implantação 1970–01/2024 | 7.378 feições, ~779 km; 3 MB | buffer 15–20 m; usar `dt_implantacao` e `tx_horario_funcionamento` |
| 1 | **Corredores de ônibus** | WFS `geoportal:corredor_onibus` | EPSG:31983 | atualização 02/10/2025 | 45 linhas, ~265 km | buffer 20–25 m; filtrar "Em Operação" |
| 1 | **Ocorrências Defesa Civil 2013–2026** (alagamento, inundação, ...) | arquivo `SIRGAS_GPKG_riscoocorrencia.zip`; KMZ por ano | GPKG EPSG:31983; KMZ WGS84 | diário (só data) | GPKG zip 11 MB | contagem de ALAGAMENTO/INUNDAÇÃO num raio de 50–100 m, por km e por ano |
| 2 | **CGE pontos de alagamento** (transitável/intransitável) | `https://www.cgesp.org/v3/alagamentos.jsp?dataBusca=DD/MM/AAAA&enviaBusca=Buscar` | HTML, só endereço | ~2008 → hoje, com hora início/fim | ~12 KB/dia (~6.500 páginas) | scraping (~1 req/s; robots.txt permite /v3/) + geocodificação pela camada CET |
| 2 | Manchas de inundação TR 5/25/100 (modeladas) | `SIRGAS_GPKG_mancha_inundacao_{5,25,100}.zip` | GPKG | 10/08/2026 | 20–39 MB | fração do trecho dentro; profundidade máxima |
| 2 | Área inundável PDMAT3 | `SIRGAS_GPKG_areainundavel.zip` | GPKG | 05/2026 | 100 KB | interseção |
| 2 | OSM highway (lanes, maxspeed, tunnel) | Overpass, área 3600298285 | JSON, WGS84 | contínuo | ~25 MB (vias principais) | mesmo método; `tunnel=yes` ajuda a prever alagamento; fraco para faixas |
| 3 | Córregos canalizados | WFS `geoportal:drenagem`; `SIRGAS_GPKG_hidrodrenagem.ZIP` | GPKG | 08/2026 | 14 MB | distância/fração a < 30 m de córrego canalizado |
| 3 | Declividade | `declividade.zip` | SHP | 2015 | 5 MB | fração por classe |
| 3 | Semáforos | WFS `geoportal:semaforo` | — | 2018 | 6.432 pontos | por km (dado velho) |
| 3 | Censo 2022 entorno (bueiro, pavimentação) | FTP IBGE `Agregados_por_setores_entorno_faces_BR.zip` + setores (WFS `setor_censitario_2022`) | CSV + malha | 2025 | 10 MB + malha | média ponderada no entorno |

Não confundir: `classificacao_viaria_quadro_9` e `zoneamento_classificacao_viaria` são classificações urbanísticas da lei de zoneamento, não a de tráfego da CET.

# Comandos de download (Windows, curl.exe)

Copiar as URLs como estão (codificação Latin-1 %E7, %E1 etc.).

**Classificação viária CET**
```
curl.exe -L -o SIRGAS_GPKG_classeviariacet.zip "https://download.geosampa.prefeitura.sp.gov.br/PaginasPublicas/downloadArquivo.aspx?orig=DownloadTemas&arq=05_Sistema%20Vi%E1rio%5CClassifica%E7%E3o%20Vi%E1ria%20CET%5CGPKG_ZIP%5C%5CSIRGAS_GPKG_classeviariacet.zip&arqTipo=zip"
```

**Faixas e corredores**
```
curl.exe -o faixa_onibus.gpkg "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=geoportal:faixa_onibus&outputFormat=application/geopackage%2Bsqlite3"
curl.exe -o corredor_onibus.gpkg "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=geoportal:corredor_onibus&outputFormat=application/geopackage%2Bsqlite3"
```

**Ocorrências da Defesa Civil (consolidado 2013–2026)**
```
curl.exe -L -o SIRGAS_GPKG_riscoocorrencia.zip "https://download.geosampa.prefeitura.sp.gov.br/PaginasPublicas/downloadArquivo.aspx?orig=DownloadTemas&arq=07_Prote%E7%E3o%20e%20Defesa%20Civil%5COcorrencias%5CGPKG_ZIP%5C%5CSIRGAS_GPKG_riscoocorrencia.zip&arqTipo=zip"
```
Por ano (AAAA de 2013 a 2026): `...arq=07_Prote%E7%E3o%20e%20Defesa%20Civil%5COcorrencias%5CKMZ%5C%5CLL_WGS84_KMZ_riscoocorrencia_AAAA.kmz&arqTipo=kmz`. Campos `data`, `ocorrencia`, `subprefeit`; formato da data muda por ano (`2013/01/01`, `2019-01-01`, `20250101`); 2013 e 2019 são KML puro apesar da extensão. Ex.: 2013 = 716 ALAGAMENTO + 43 INUNDAÇÃO; 2019 = 391 + 365; 2025 = 281 + 382 (o resto é sobretudo queda de árvore).

**Mancha de inundação (troque 100 por 25 ou 5)**
```
curl.exe -L -o mancha100.zip "https://download.geosampa.prefeitura.sp.gov.br/PaginasPublicas/downloadArquivo.aspx?orig=DownloadTemas&arq=29_Drenagem%5CMancha%20de%20Inunda%E7%E3o%20100%20anos%5CGPKG_ZIP%5C%5CSIRGAS_GPKG_mancha_inundacao_100.zip&arqTipo=zip"
```

**WFS paginado (classificação viária viva), em Python no PC**
```python
import requests, io, pandas as pd, geopandas as gpd
B = "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs"
def wfs(layer, sort="cd_identificador", page=30000, cql=None):
    parts, start = [], 0
    while True:
        p = dict(service="WFS", version="2.0.0", request="GetFeature", typeNames=f"geoportal:{layer}",
                 outputFormat="application/json", count=page, startIndex=start, sortBy=sort)
        if cql: p["CQL_FILTER"] = cql
        r = requests.get(B, params=p, timeout=900); r.raise_for_status()
        g = gpd.read_file(io.BytesIO(r.content)); parts.append(g)
        if len(g) < page: break
        start += page
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True)).set_crs(31983, allow_override=True)
```

**Overpass (OSM)** — exige User-Agent:
```
[out:json][timeout:900][maxsize:1073741824];
area(id:3600298285)->.sp;
way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|busway|bus_guideway|road)$"](area.sp);
out tags geom qt;
```
`curl.exe -A "volbus-research/1.0" --data-urlencode "data@query.overpassql" -o osm_sp_highways.json https://overpass-api.de/api/interpreter`

# Ressalvas

- Faixas exclusivas: metadados de 08/2021, última implantação registrada 01/2024 — faixas recentes podem faltar; muitas valem só no pico.
- Defesa Civil: geocodificada pelo endereço do chamado (não necessariamente sobre a via), subnotificada, só data (sem hora), 300–700 alagamentos por ano.
- CGE: sem licença declarada; só endereço; cobertura favorece vias monitoradas (arteriais).
- Manchas de inundação são modeladas; declividade de 2015; semáforos de 2018.
- Licenças: GeoSampa CC BY-SA 4.0 (atribuição; derivados redistribuídos com share-alike); OSM ODbL; IBGE uso livre com citação.
