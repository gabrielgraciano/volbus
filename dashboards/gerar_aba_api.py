"""Gera a aba "Versão API" no dashboard a partir da definição exportada da aba feita à mão.

Uso: python dashboards/gerar_aba_api.py  -> escreve dashboards/onibus_silver.lvdash.json e dashboards/_patch.json
"""
import copy
import json

d = json.load(open("dashboards/dash_teste_original.lvdash.json", encoding="utf-8"))
ds = {x["displayName"]: x["name"] for x in d["datasets"]}


def lines(sql):
    return [l + "\n" for l in sql.strip().split("\n")]


d["datasets"] += [
    {"name": "kpis0001", "displayName": "kpis", "queryLines": lines("""
SELECT
  (SELECT count(DISTINCT dt) FROM onibus.silver.velocidade_trecho) AS dias,
  (SELECT round(count(*) / 1e6, 0) FROM onibus.silver.posicao_limpa) AS posicoes_milhoes,
  (SELECT count(DISTINCT parada_de, parada_ate) FROM onibus.silver.velocidade_trecho) AS trechos_fisicos,
  (SELECT count(*) FROM onibus.silver.postos WHERE status = 'ok' AND duplicata_de IS NULL) AS postos_chuva""")},
    {"name": "mapafx01", "displayName": "mapa_trechos_pico_faixas", "queryLines": lines("""
SELECT v.parada_de, s.stop_name, s.stop_lat, s.stop_lon,
       round(sum(v.dist_m) / sum(v.tempo_s) * 3.6, 1) AS v_kmh,
       CASE WHEN sum(v.dist_m) / sum(v.tempo_s) * 3.6 < 10 THEN '1. menos de 10 km/h'
            WHEN sum(v.dist_m) / sum(v.tempo_s) * 3.6 < 15 THEN '2. 10 a 15 km/h'
            WHEN sum(v.dist_m) / sum(v.tempo_s) * 3.6 < 20 THEN '3. 15 a 20 km/h'
            ELSE '4. mais de 20 km/h' END AS faixa
FROM onibus.silver.velocidade_trecho v
JOIN onibus.silver.gtfs_stops s
  ON CAST(s.stop_id AS STRING) = v.parada_de AND s.versao = v.versao_gtfs
WHERE v.tipo_dia = 'util' AND hour(v.janela_sp) BETWEEN 17 AND 18
GROUP BY 1, 2, 3, 4
HAVING sum(v.n_pares) >= 200""")},
]


def q(dataset, campos, name="main_query"):
    return {"name": name, "query": {"datasetName": dataset, "disaggregated": True,
                                    "fields": [{"name": c, "expression": f"`{c}`"} for c in campos]}}


def frame(t):
    return {"showTitle": True, "title": {"value": t, "fields": []}}


def cor(pos):  # paleta do tema: 1 azul, 2 laranja, 3 verde, 4 vermelho
    return {"themeColorType": "visualizationColors", "position": pos}


def w(name, queries, spec, x, y, wd, h):
    return {"widget": {"name": name, "queries": queries, "spec": spec},
            "position": {"x": x, "y": y, "width": wd, "height": h}}


layout = []
kpi = [("dias", "Dias com velocidade"), ("posicoes_milhoes", "Posições limpas (milhões)"),
       ("trechos_fisicos", "Trechos entre paradas"), ("postos_chuva", "Postos de chuva usados")]
for i, (c, t) in enumerate(kpi):
    layout.append(w(f"api-kpi-{c}", [q("kpis0001", [c])],
                    {"version": 2, "widgetType": "counter", "frame": frame(t),
                     "encodings": {"value": {"fieldName": c, "displayName": t}}},
                    3 * i, 0, 3, 2))

pagina1 = d["pages"][0]["layout"]
hora = copy.deepcopy(next(x for x in pagina1 if x["widget"]["name"] == "velocidade-por-hora"))
hora["widget"]["name"] = "api-velocidade-por-hora"
hora["widget"]["spec"].pop("mark", None)  # sem suavizacao: a curva suave inventa picos e vales
hora["widget"]["spec"]["frame"] = frame("Velocidade média por hora (km/h, todos os trechos)")
hora["position"] = {"x": 0, "y": 2, "width": 6, "height": 7}
layout.append(hora)

layout.append(w("api-mapa-faixas", [q("mapafx01", ["faixa", "stop_lat", "stop_lon"])],
                {"version": 2, "widgetType": "symbol-map",
                 "frame": frame("Velocidade no pico da tarde por trecho (dia útil, 17h–19h)"),
                 "mark": {"opacity": 0.7, "shape": "circle"},
                 "encodings": {
                     "coordinates": {"latitude": {"fieldName": "stop_lat"}, "longitude": {"fieldName": "stop_lon"}},
                     "color": {"fieldName": "faixa", "scale": {"type": "categorical", "mappings": [
                         {"value": "1. menos de 10 km/h", "color": cor(4)},
                         {"value": "2. 10 a 15 km/h", "color": cor(2)},
                         {"value": "3. 15 a 20 km/h", "color": cor(1)},
                         {"value": "4. mais de 20 km/h", "color": cor(3)}]}}}},
                6, 2, 6, 7))

dia = ds["dia_velocidade_chuva"]
layout.append(w("api-chuva-dia", [q(dia, ["dia", "chuva_mm"])],
                {"version": 3, "widgetType": "bar", "frame": frame("Chuva por dia (mediana dos postos ok, mm)"),
                 "encodings": {"x": {"fieldName": "dia", "scale": {"type": "temporal"}},
                               "y": {"fieldName": "chuva_mm", "scale": {"type": "quantitative"}}}},
                0, 9, 6, 4))
layout.append(w("api-velocidade-dia", [q(dia, ["dia", "v_kmh"])],
                {"version": 3, "widgetType": "line", "frame": frame("Velocidade média por dia (6h–22h, km/h)"),
                 "encodings": {"x": {"fieldName": "dia", "scale": {"type": "temporal"}},
                               "y": {"fieldName": "v_kmh", "scale": {"type": "quantitative"}}}},
                0, 13, 6, 4))
layout.append(w("api-dispersao", [q(dia, ["chuva_mm", "v_kmh", "tipo_dia"])],
                {"version": 3, "widgetType": "scatter", "frame": frame("Cada ponto é um dia: chuva × velocidade"),
                 "encodings": {"x": {"fieldName": "chuva_mm", "scale": {"type": "quantitative"}},
                               "y": {"fieldName": "v_kmh", "scale": {"type": "quantitative"}},
                               "color": {"fieldName": "tipo_dia", "scale": {"type": "categorical"}}}},
                6, 9, 6, 8))

postos = copy.deepcopy(next(x for x in pagina1 if x["widget"]["name"] == "postos-de-chuva"))
postos["widget"]["name"] = "api-postos"
postos["widget"]["spec"]["frame"] = frame("Postos de chuva (tamanho = mm desde 25/08)")
postos["widget"]["spec"]["encodings"]["color"]["scale"]["mappings"] = [
    {"value": "ok", "color": cor(3)}, {"value": "quebrado", "color": cor(4)},
    {"value": "lacunar", "color": cor(1)}, {"value": "sem_dado", "color": cor(2)}]
postos["position"] = {"x": 0, "y": 17, "width": 6, "height": 7}
layout.append(postos)

texto = """### Como ler
- **Velocidade** = comercial (inclui paradas em ponto e semáforo): soma das distâncias ÷ soma dos tempos dos ônibus em cada trecho entre paradas.
- **De madrugada (2h–3h) a velocidade cai**: poucos ônibus e muitos parados fora do terminal (garagem, ponto de regulagem). Investigar antes da gold.
- **Chuva × velocidade por dia é só uma primeira olhada**: mistura dia útil e fim de semana, e a média da cidade dilui efeitos locais. O efeito de verdade vem da gold: cada trecho comparado com o seu normal (mesma hora e tipo de dia), com a chuva do posto mais próximo.
- **Postos**: 95 ok cobrem a cidade; os quebrados são quase todos do CEMADEN (leituras zeradas).
- Período: posições de 25/08 até ontem (o job diário estende às 10h); chuva de 01/08 a 25/10 (download manual)."""
layout.append({"widget": {"name": "api-texto", "multilineTextboxSpec": {"lines": [l + "\n" for l in texto.split("\n")]}},
               "position": {"x": 6, "y": 17, "width": 6, "height": 7}})

d["pages"].append({"name": "versaoapi", "displayName": "Versão API", "pageType": "PAGE_TYPE_CANVAS",
                   "layoutVersion": "GRID_V1", "layout": layout})
json.dump(d, open("dashboards/onibus_silver.lvdash.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
body = {"display_name": "Dash Teste", "warehouse_id": "117d33ac28f3ff05",
        "serialized_dashboard": json.dumps(d, ensure_ascii=False)}
json.dump(body, open("dashboards/_patch.json", "w", encoding="utf-8"), ensure_ascii=False)
print("paginas:", [p["displayName"] for p in d["pages"]], "| widgets na nova:", len(layout))
