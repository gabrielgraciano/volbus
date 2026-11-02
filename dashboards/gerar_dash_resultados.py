"""Gera o dashboard "Ônibus × Chuva: resultados", com uma aba por KR, a partir das tabelas gold.

Uso, da pasta dashboards:
    python gerar_dash_resultados.py validar     roda cada consulta no warehouse e mostra as primeiras linhas
    python gerar_dash_resultados.py criar       cria o dashboard e guarda o id em dash_resultados_id.txt
    python gerar_dash_resultados.py atualizar   troca a definição do dashboard criado, com PATCH

Números dentro de textos e títulos são de 02/11/2026. Gráficos e contadores seguem as tabelas.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analises", "gold_exploracao"))
from dbsql import WH, _api, q as sql  # noqa: E402

NOME = "Ônibus × Chuva: resultados"
PASTA = "/Users/diasg270@gmail.com/onibus"
AQUI = os.path.dirname(os.path.abspath(__file__))
ARQ_ID = os.path.join(AQUI, "dash_resultados_id.txt")

CLASSE = """CASE classe_chuva WHEN 'traco' THEN '1 traço' WHEN 'fraca' THEN '2 fraca' WHEN 'moderada' THEN '3 moderada'
                              WHEN 'forte' THEN '4 forte' WHEN 'muito_forte' THEN '5 muito forte' END"""
PERIODO = """CASE periodo WHEN 'todos' THEN 'dia todo' WHEN 'manha' THEN 'manhã' WHEN 'meio' THEN 'meio do dia'
                          WHEN 'tarde' THEN 'pico da tarde' WHEN 'noite' THEN 'noite' END"""
GRUPO = """CASE WHEN dimensao = 'via' AND grupo = 'coletora' THEN '1 coletora' WHEN dimensao = 'via' AND grupo = 'arterial' THEN '2 arterial'
                WHEN dimensao = 'via' AND grupo = 'expressa' THEN '3 expressa' WHEN dimensao = 'alagamento' AND grupo = '0 dias' THEN '4 sem alagamento'
                WHEN dimensao = 'alagamento' AND grupo = '1-4 dias' THEN '5 alagou 1-4 dias' WHEN dimensao = 'alagamento' AND grupo = '5+ dias' THEN '6 alagou 5+ dias'
                WHEN dimensao = 'onibus' AND grupo = 'sem faixa nem corredor' THEN '7 sem faixa' WHEN dimensao = 'onibus' AND grupo = 'faixa' THEN '8 faixa'
                WHEN dimensao = 'onibus' AND grupo = 'corredor' THEN '9 corredor' END"""
TERMO = """CASE termo WHEN 'via_arterial' THEN 'via arterial (contra coletora)' WHEN 'via_expressa' THEN 'via expressa (contra coletora)'
                      WHEN 'via_local' THEN 'via local (contra coletora)' WHEN 'alag_log1p_dias' THEN 'alagamento (por log dos dias)'
                      WHEN 'frac_faixa' THEN 'faixa de ônibus' WHEN 'frac_corredor' THEN 'corredor de ônibus'
                      WHEN 'perto_terminal' THEN 'perto de terminal' WHEN 'log_comprimento' THEN 'comprimento (por log)'
                      WHEN 'log_horas_onibus' THEN 'horas de ônibus (por log)' WHEN 'dist_posto_km' THEN 'distância ao posto (por km)' END"""

DATASETS = {
    "kpis": """
SELECT (SELECT count(*) FROM onibus.gold.efeito_trecho) AS trechos,
       (SELECT count_if(p_queda >= 0.95) FROM onibus.gold.efeito_trecho) AS com_queda,
       (SELECT round(100 * (razao - 1), 1) FROM onibus.gold.efeito_cidade WHERE recorte = 'tudo' AND periodo = 'todos' AND classe_chuva = 'moderada') AS queda_moderada,
       (SELECT round(100 * (razao - 1), 1) FROM onibus.gold.efeito_cidade WHERE recorte = 'tudo' AND periodo = 'tarde' AND classe_chuva = 'moderada') AS queda_moderada_tarde,
       (SELECT count_if(grupo_critico) FROM onibus.gold.efeito_trecho) AS criticos,
       (SELECT count(DISTINCT local_critico) FROM onibus.gold.efeito_trecho WHERE grupo_critico) AS locais,
       (SELECT count_if(classe_recuperacao <> 'indefinido') FROM onibus.gold.recuperacao_trecho) AS classificados,
       (SELECT count_if(classe_recuperacao IN ('1h_a_2h', 'mais_de_1h', 'mais_de_2h')) FROM onibus.gold.recuperacao_trecho) AS demoram,
       (SELECT round(valor, 2) FROM onibus.gold.estabilidade_ranking WHERE metrica = 'jaccard_mediano') AS jaccard,
       (SELECT int(valor) FROM onibus.gold.estabilidade_ranking WHERE metrica = 'top10_no_top20_em_80pct') AS estaveis,
       (SELECT round(valor, 2) FROM onibus.gold.estabilidade_ranking WHERE metrica = 'fiabilidade') AS fiabilidade""",
    "efeito_classe": f"""
SELECT {CLASSE} AS chuva, {PERIODO} AS periodo_label, round(100 * (razao - 1), 1) AS variacao_pct
FROM onibus.gold.efeito_cidade
WHERE recorte = 'tudo' AND NOT fragil AND periodo IN ('todos', 'tarde', 'meio')
  AND classe_chuva IN ('traco', 'fraca', 'moderada', 'forte', 'muito_forte')""",
    "efeito_tabela": f"""
SELECT {CLASSE} AS chuva, {PERIODO} AS periodo_label, round(razao, 3) AS razao,
       CASE WHEN fragil THEN concat('sem intervalo (', n_dias, ' dias)')
            ELSE concat(format_number(ic_inf, 3), ' a ', format_number(ic_sup, 3)) END AS intervalo_95,
       n_dias, janelas
FROM onibus.gold.efeito_cidade
WHERE recorte = 'tudo' AND classe_chuva IN ('traco', 'fraca', 'moderada', 'forte', 'muito_forte')
ORDER BY 1, 2""",
    "recup_periodo": """
SELECT CASE periodo_fim WHEN 'manha' THEN 'manhã' WHEN 'meio' THEN 'meio do dia' WHEN 'tarde' THEN 'tarde' ELSE 'noite' END AS acabou,
       tau_min, razao
FROM onibus.gold.recuperacao_cidade WHERE classe_evento = 'moderada' AND periodo_fim IN ('manha', 'meio', 'tarde', 'noite')""",
    "recup_piores": r"""
SELECT CASE WHEN metrica LIKE 'piores%' THEN '1% piores na chuva' ELSE 'resto dos trechos' END AS grupo,
       int(regexp_extract(metrica, '(\\d+)min', 1)) + 15 AS minutos, round(valor, 3) AS razao
FROM onibus.gold.validacao_recuperacao WHERE metrica LIKE '%fora_da_amostra%'""",
    "tempo_grupo": f"""
SELECT {GRUPO} AS grupo_label, tempo_rec_min, round(perda_min, 1) AS perda_min
FROM onibus.gold.tempo_recuperacao_grupo
WHERE periodo = 'fora_do_pico' AND dimensao IN ('via', 'alagamento', 'onibus') AND {GRUPO} IS NOT NULL""",
    "perda_grupo": f"""
SELECT {GRUPO} AS grupo_label, round(perda_min, 1) AS perda_min
FROM onibus.gold.tempo_recuperacao_grupo
WHERE periodo = 'pico' AND dimensao IN ('via', 'alagamento', 'onibus') AND {GRUPO} IS NOT NULL""",
    "mapa_recuperacao": """
SELECT lat, lon, CASE WHEN classe_recuperacao = 'mais_de_2h' THEN 'mais de 2 h' ELSE 'mais de 1 h' END AS demora, nome_de, nome_ate
FROM onibus.gold.recuperacao_trecho WHERE classe_recuperacao IN ('1h_a_2h', 'mais_de_1h', 'mais_de_2h')""",
    "classes_recuperacao": """
SELECT CASE classe_recuperacao WHEN 'ate_1h' THEN '1 até 1 h' WHEN '1h_a_2h' THEN '2 de 1 a 2 h' WHEN 'mais_de_1h' THEN '3 mais de 1 h'
                               WHEN 'mais_de_2h' THEN '4 mais de 2 h' ELSE '5 indefinido' END AS classe, count(*) AS trechos
FROM onibus.gold.recuperacao_trecho GROUP BY 1""",
    "mapa_critico": """
SELECT lat, lon, round(razao_encolhida, 2) AS razao, nome_de, nome_ate FROM onibus.gold.efeito_trecho WHERE grupo_critico""",
    "locais": """
WITH l AS (SELECT local_critico, count(*) AS trechos, round(median(razao_encolhida), 2) AS razao_mediana, min(rank) AS melhor_posicao,
                  round(median(v_kmh_media), 1) AS v_kmh, max(dias_alag_100m) AS dias_alagamento, round(avg(placebo_seco), 2) AS placebo
           FROM onibus.gold.efeito_trecho WHERE grupo_critico GROUP BY 1)
SELECT l.melhor_posicao, concat(t.nome_de, ' → ', t.nome_ate) AS lugar, l.trechos, l.razao_mediana, l.v_kmh, l.dias_alagamento, l.placebo,
       t.classe_dominante AS via
FROM l JOIN onibus.gold.efeito_trecho t ON t.rank = l.melhor_posicao ORDER BY 1""",
    "infra_via": """
SELECT CASE chuva WHEN 'fraca' THEN '1 fraca' WHEN 'moderada' THEN '2 moderada' ELSE '3 forte ou mais' END AS chuva_label, CASE grupo WHEN 'coletora' THEN '1 coletora' WHEN 'arterial' THEN '2 arterial' ELSE '3 expressa' END AS grupo_label,
       round(100 * (razao - 1), 1) AS variacao_pct
FROM onibus.gold.efeito_grupo WHERE dimensao = 'via' AND grupo IN ('coletora', 'arterial', 'expressa')""",
    "infra_alag": """
SELECT CASE chuva WHEN 'fraca' THEN '1 fraca' WHEN 'moderada' THEN '2 moderada' ELSE '3 forte ou mais' END AS chuva_label, CASE grupo WHEN '0 dias' THEN '1 sem alagamento' WHEN '1-4 dias' THEN '2 de 1 a 4 dias' WHEN '5-19 dias' THEN '3 de 5 a 19 dias' ELSE '4 20 dias ou mais' END AS grupo_label,
       round(100 * (razao - 1), 1) AS variacao_pct
FROM onibus.gold.efeito_grupo WHERE dimensao = 'alagamento'""",
    "infra_dentro": """
SELECT CASE chuva WHEN 'fraca' THEN '1 fraca' WHEN 'moderada' THEN '2 moderada' ELSE '3 forte ou mais' END AS chuva_label, CASE dimensao WHEN 'alagamento_em_arterial' THEN 'em arterial' ELSE 'em coletora' END AS via, round(100 * (vs_referencia - 1), 1) AS diferenca_pct
FROM onibus.gold.efeito_grupo WHERE dimensao LIKE 'alagamento_em%' AND grupo = '5+ dias'""",
    "infra_modelo": f"""
SELECT {TERMO} AS atributo, round(100 * (exp(max_by(coef_log, modelo = 'principal')) - 1), 2) AS trecho_tipico_pct,
       concat(format_number(100 * (exp(max_by(ic_inf, modelo = 'principal')) - 1), 2), ' a ', format_number(100 * (exp(max_by(ic_sup, modelo = 'principal')) - 1), 2)) AS intervalo_tipico,
       round(100 * (exp(max_by(coef_log, modelo = 'ponderado_por_onibus')) - 1), 2) AS peso_onibus_pct,
       concat(format_number(100 * (exp(max_by(ic_inf, modelo = 'ponderado_por_onibus')) - 1), 2), ' a ', format_number(100 * (exp(max_by(ic_sup, modelo = 'ponderado_por_onibus')) - 1), 2)) AS intervalo_onibus
FROM onibus.gold.efeito_infra WHERE modelo IN ('principal', 'ponderado_por_onibus') GROUP BY termo ORDER BY 1""",
}


def linhas(texto):
    return [x + "\n" for x in texto.strip().split("\n")]


def frame(titulo, subtitulo=None):
    f = {"showTitle": True, "title": {"value": titulo, "fields": []}}
    if subtitulo:
        f.update({"showDescription": True, "description": {"value": subtitulo, "fields": []}})
    return f


def consulta(dataset, campos):
    return [{"name": "main_query", "query": {"datasetName": dataset, "disaggregated": True,
                                             "fields": [{"name": c, "expression": f"`{c}`"} for c in campos]}}]


def cor(pos):   # tema: 1 azul, 2 laranja, 3 verde, 4 vermelho
    return {"themeColorType": "visualizationColors", "position": pos}


def cores(pares):
    return {"type": "categorical", "mappings": [{"value": v, "color": cor(p)} for v, p in pares], "sort": {"by": "natural-order"}}


def widget(nome, consultas, spec, x, y, w, h):
    return {"widget": {"name": nome, "queries": consultas, "spec": spec}, "position": {"x": x, "y": y, "width": w, "height": h}}


def texto(nome, conteudo, x, y, w, h):
    return {"widget": {"name": nome, "multilineTextboxSpec": {"lines": linhas(conteudo)}}, "position": {"x": x, "y": y, "width": w, "height": h}}


def contador(campo, titulo, sub, x, y, w=3, h=2):
    return widget(f"kpi-{campo}", consulta("kpis", [campo]),
                  {"version": 2, "widgetType": "counter", "frame": frame(titulo, sub), "encodings": {"value": {"fieldName": campo, "displayName": titulo}}}, x, y, w, h)


def linha(nome, ds, xc, yc, serie, titulo, sub, x, y, w, h, nome_x, nome_y, mapa=None):
    enc = {"x": {"fieldName": xc, "displayName": nome_x, "scale": {"type": "quantitative"}},
           "y": {"fieldName": yc, "displayName": nome_y, "scale": {"type": "quantitative"}},
           "color": {"fieldName": serie, "displayName": " ", "scale": cores(mapa) if mapa else {"type": "categorical"}}}
    return widget(nome, consulta(ds, [xc, yc, serie]), {"version": 3, "widgetType": "line", "frame": frame(titulo, sub), "encodings": enc}, x, y, w, h)


def barra(nome, ds, xc, yc, titulo, sub, x, y, w, h, nome_y, serie=None, mapa=None, nome_x=" ", rotulo=True):
    enc = {"x": {"fieldName": xc, "displayName": nome_x, "scale": {"type": "categorical", "sort": {"by": "natural-order"}}},
           "y": {"fieldName": yc, "displayName": nome_y, "scale": {"type": "quantitative"}}}
    campos = [xc, yc]
    mark = {}
    if serie:
        enc["color"] = {"fieldName": serie, "displayName": " ", "scale": cores(mapa)}
        campos.append(serie)
        mark = {"layout": "group"}
    if rotulo:
        enc["label"] = {"show": True}
    spec = {"version": 3, "widgetType": "bar", "frame": frame(titulo, sub), "encodings": enc}
    if mark:
        spec["mark"] = mark
    return widget(nome, consulta(ds, campos), spec, x, y, w, h)


def tabela(nome, ds, colunas, titulo, sub, x, y, w, h):
    enc = {"columns": [{"fieldName": c, "displayName": t} for c, t in colunas]}
    return widget(nome, consulta(ds, [c for c, _ in colunas]), {"version": 2, "widgetType": "table", "frame": frame(titulo, sub), "encodings": enc}, x, y, w, h)


def mapa(nome, ds, campos, enc_cor, titulo, sub, x, y, w, h):
    enc = {"coordinates": {"latitude": {"fieldName": "lat"}, "longitude": {"fieldName": "lon"}}, "color": enc_cor}
    return widget(nome, consulta(ds, campos), {"version": 2, "widgetType": "symbol-map", "frame": frame(titulo, sub),
                                               "mark": {"opacity": 0.85, "shape": "circle"}, "encodings": enc}, x, y, w, h)


def pagina(nome, titulo, itens):
    return {"name": nome, "displayName": titulo, "pageType": "PAGE_TYPE_CANVAS", "layoutVersion": "GRID_V1", "layout": itens}


RESUMO = """### O que descobrimos
- **A chuva derruba a velocidade, e quanto mais forte, mais:** −4,7% na chuva fraca e −14,6% na muito forte, no dia todo.
- **O pico da tarde é o momento mais sensível:** na chuva moderada, a queda sobe de −6,3% para −10,3%.
- **A hora em que a chuva acaba pesa mais que a intensidade:** fora dos picos a velocidade volta em até 40 min; nos picos, leva de 1 a 2 h.
- **Os piores trechos demoram cerca do dobro:** ~2 h contra ~1 h, medidos em dias que não entraram na escolha deles.
- **Via importa:** na chuva forte, arterial perde 5,7% a mais que coletora, e via expressa 10,7%.
- **Alagamento frequente pesa 2 a 4%**, mesmo comparando dentro do mesmo tipo de via.
- **Faixa e corredor não mostraram proteção detectável.**
"""
LEITURA = """### Como ler
- **Razão ou variação:** comparam a velocidade na chuva com o normal do mesmo trecho, horário, dia da semana e semana.
- **Período:** dia útil, 6h às 23h, 25/08 a 25/10/2026, 42 dias úteis. Tudo depende do último download de chuva.
- **Soma e trecho típico:** somar os ônibus dá o que o passageiro sente, e tempo preso pesa mais. O trecho típico perde menos.
- **Associação não é causa:** trechos não foram sorteados para ter faixa ou alagar.
- Textos e títulos são de 02/11/2026. Gráficos e contadores seguem as tabelas. Detalhes em `docs/projeto_completo.pdf`.
"""
KR3_TEXTO = """### Por que não há um top-10 exato
O critério, fixado antes de olhar, pedia Jaccard de pelo menos 0,5 e os 10 primeiros estáveis. O resultado reprovou, em todas as alternativas testadas. Com ~13 dias de chuva por trecho, sabemos **quais lugares são críticos**, mas não a ordem exata entre eles.

O grupo crítico reúne trechos entre os 5% piores em ao menos 80% das 500 reamostras de dias. Nas horas secas dos mesmos dias eles ficam normais, então a queda aparece com a chuva.

**Cuidados:** a Estr. de Itapecerica mudou de regime em outubro, mesmo no seco. Trechos muito lentos são gargalos, onde a fila amplifica a chuva. Perto de terminal, parte da queda pode ser espera.
"""
KR2_TEXTO = """### Como ler
Uma janela isolada varia ±23%, então não há um tempo exato por trecho: por trecho há uma **faixa**, e o tempo em minutos fica para grupos de trechos.

As três faixas valem para a mistura de chuva da cidade. Depois de chuva no pico, o mesmo trecho demora mais.
"""
KR4_TEXTO = """### Duas leituras
**Soma por grupo** (gráficos): mostra o que o ônibus sente.

**Modelo** (tabela): compara trechos parecidos, em %. Negativo quer dizer que perde mais. Intervalo que inclui zero quer dizer que não dá para afirmar.

As diferenças ficam menores no modelo porque via, faixa, corredor e alagamento vêm juntos, e os trechos mais cheios perdem mais.
"""
VIA = [("1 coletora", 1), ("2 arterial", 2), ("3 expressa", 3)]
ALAG = [("1 sem alagamento", 1), ("2 de 1 a 4 dias", 2), ("3 de 5 a 19 dias", 3), ("4 20 dias ou mais", 4)]
DENTRO = [("em coletora", 1), ("em arterial", 2)]
PER = [("dia todo", 1), ("pico da tarde", 2), ("meio do dia", 3)]
FIM = [("manhã", 1), ("meio do dia", 2), ("tarde", 3), ("noite", 4)]
PIORES = [("resto dos trechos", 1), ("1% piores na chuva", 2)]

paginas = [
    pagina("resumo", "Resumo", [
        contador("trechos", "Trechos medidos", "KR1: regra de dado mínimo", 0, 0),
        contador("com_queda", "Com queda quase certa", "KR1: probabilidade ≥ 95%", 3, 0),
        contador("queda_moderada", "Queda na chuva moderada (%)", "cidade, dia todo", 6, 0),
        contador("queda_moderada_tarde", "No pico da tarde (%)", "mesma chuva, 16h às 19h", 9, 0),
        contador("classificados", "Trechos com faixa de recuperação", "KR2", 0, 2),
        contador("criticos", "Trechos críticos", "KR3: grupo estável", 3, 2),
        contador("locais", "Lugares críticos", "KR3: trechos a até 300 m juntos", 6, 2),
        contador("jaccard", "Jaccard do top-10", "KR3: mínimo era 0,5", 9, 2),
        texto("resumo-texto", RESUMO, 0, 4, 7, 8),
        texto("resumo-leitura", LEITURA, 7, 4, 5, 8),
    ]),
    pagina("kr1", "KR1: queda na chuva", [
        barra("kr1-barra", "efeito_classe", "chuva", "variacao_pct", "Quanto mais forte a chuva, maior a queda, e o pico da tarde perde mais",
              "Variação da velocidade contra o normal, em %. Só células com pelo menos 8 dias.", 0, 0, 12, 8, "variação (%)", "periodo_label", PER),
        tabela("kr1-tabela", "efeito_tabela", [("chuva", "Chuva"), ("periodo_label", "Período"), ("razao", "Razão (1 = normal)"), ("intervalo_95", "Intervalo de 95%"),
                                               ("n_dias", "Dias"), ("janelas", "Janelas")],
               "Todos os números, com intervalo", "Bootstrap de 2.000 reamostras de dias", 0, 8, 12, 9),
    ]),
    pagina("kr2", "KR2: recuperação", [
        linha("kr2-periodo", "recup_periodo", "tau_min", "razao", "acabou", "A hora em que a chuva acaba decide quanto a velocidade demora a voltar",
              "Chuva moderada, cidade. Razão por minutos depois do fim, pelo período em que acabou.", 0, 0, 6, 7, "minutos depois do fim", "razão (1 = normal)", FIM),
        linha("kr2-piores", "recup_piores", "minutos", "razao", "grupo", "Os piores trechos voltam em ~2 h, o resto em ~1 h",
              "Trechos escolhidos numa metade dos dias, recuperação medida na outra.", 6, 0, 6, 7, "minutos depois do fim", "razão (1 = normal)", PIORES),
        barra("kr2-tempo", "tempo_grupo", "grupo_label", "tempo_rec_min", "Fora do pico: via rápida e alagamento demoram mais a voltar",
              "Minutos até a razão ficar em pelo menos 0,99 por 30 min.", 0, 7, 6, 7, "minutos"),
        barra("kr2-perda", "perda_grupo", "grupo_label", "perda_min", "No pico: compare a perda, porque quase nada volta em 3 h",
              "Minutos de operação normal perdidos por ônibus nas 2 h depois do fim.", 6, 7, 6, 7, "minutos perdidos"),
        barra("kr2-classes", "classes_recuperacao", "classe", "trechos", "Por trecho: a grande maioria volta em até 1 h",
              "Faixa de recuperação de cada trecho com dado suficiente.", 0, 14, 4, 7, "trechos"),
        mapa("kr2-mapa", "mapa_recuperacao", ["lat", "lon", "demora"], {"fieldName": "demora", "displayName": "Demora", "scale": cores([("mais de 1 h", 2), ("mais de 2 h", 4)])},
             "Onde a velocidade demora mais a voltar", "Trechos marcados como acima de 1 h", 4, 14, 5, 7),
        texto("kr2-texto", KR2_TEXTO, 9, 14, 3, 7),
    ]),
    pagina("kr3", "KR3: trechos críticos", [
        contador("criticos", "Trechos críticos", "entre os 5% piores em ≥ 80% das reamostras", 0, 0),
        contador("locais", "Lugares", "trechos a até 300 m contam como um", 3, 0),
        contador("jaccard", "Jaccard do top-10", "critério: pelo menos 0,5", 6, 0),
        contador("estaveis", "Estáveis entre os 10 primeiros", "critério: 10 de 10", 9, 0),
        mapa("kr3-mapa", "mapa_critico", ["lat", "lon", "razao"],
             {"fieldName": "razao", "displayName": "Razão", "scale": {"type": "quantitative", "colorRamp": {"mode": "single-hue", "baseColor": cor(2)}, "reverse": True}},
             "Os trechos críticos se espalham pela cidade", "Quanto mais escuro, maior a queda", 0, 2, 7, 11),
        texto("kr3-texto", KR3_TEXTO, 7, 2, 5, 11),
        tabela("kr3-locais", "locais", [("melhor_posicao", "Posição"), ("lugar", "Lugar"), ("via", "Via"), ("trechos", "Trechos"), ("razao_mediana", "Razão"),
                                        ("v_kmh", "km/h"), ("dias_alagamento", "Dias de alagamento"), ("placebo", "Placebo no seco")],
               "Os 88 lugares críticos", "A posição é indicativa: a ordem exata não é estável", 0, 13, 12, 10),
    ]),
    pagina("kr4", "KR4: infraestrutura", [
        barra("kr4-via", "infra_via", "chuva_label", "variacao_pct", "Via mais rápida perde mais na chuva", "Variação contra o normal, em %, somando os ônibus.", 0, 0, 6, 7,
              "variação (%)", "grupo_label", VIA, "intensidade da chuva"),
        barra("kr4-alag", "infra_alag", "chuva_label", "variacao_pct", "Quem tem histórico de alagamento perde mais", "Dias de alagamento a até 100 m, de 2013 a 24/08/2026.", 6, 0, 6, 7,
              "variação (%)", "grupo_label", ALAG, "intensidade da chuva"),
        barra("kr4-dentro", "infra_dentro", "chuva_label", "diferenca_pct", "O alagamento pesa mesmo dentro do mesmo tipo de via", "Trechos com 5 dias ou mais, contra os sem histórico, em %.", 0, 7, 5, 7,
              "diferença (%)", "via", DENTRO, "intensidade da chuva"),
        texto("kr4-texto", KR4_TEXTO, 5, 7, 7, 7),
        tabela("kr4-modelo", "infra_modelo", [("atributo", "Atributo"), ("trecho_tipico_pct", "Trecho típico (%)"), ("intervalo_tipico", "Intervalo de 95%"),
                                              ("peso_onibus_pct", "Peso por ônibus (%)"), ("intervalo_onibus", "Intervalo de 95%")],
               "Comparando trechos parecidos", "Coeficientes do modelo, em %", 0, 14, 12, 8),
    ]),
]

definicao = {"datasets": [{"name": n, "displayName": n, "queryLines": linhas(s)} for n, s in DATASETS.items()], "pages": paginas}

modo = sys.argv[1] if len(sys.argv) > 1 else "validar"
if modo == "validar":
    for n, s in DATASETS.items():
        r = sql(s, timeout_s=300)
        print(f"== {n}: {len(r)} linhas")
        print(r.head(3).to_string(index=False)[:500])
else:
    json.dump(definicao, open(os.path.join(AQUI, "onibus_resultados.lvdash.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    corpo = {"display_name": NOME, "warehouse_id": WH, "serialized_dashboard": json.dumps(definicao, ensure_ascii=False)}
    if modo == "criar":
        assert not os.path.exists(ARQ_ID), "dashboard já criado: use atualizar"
        r = _api("post", "/api/2.0/lakeview/dashboards", {**corpo, "parent_path": PASTA})
        open(ARQ_ID, "w").write(r["dashboard_id"])
    else:
        ident = open(ARQ_ID).read().strip()
        r = _api("patch", f"/api/2.0/lakeview/dashboards/{ident}", corpo)
    print("ok:", r["dashboard_id"], r.get("path"), r.get("lifecycle_state"))
