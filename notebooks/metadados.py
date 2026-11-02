# Databricks notebook source
# MAGIC %md
# MAGIC # Metadados do catalogo `onibus`
# MAGIC
# MAGIC Fonte unica das descricoes de tabelas e colunas (o que aparece no Catalog Explorer).
# MAGIC
# MAGIC **Por que reaplicar a cada gravacao:** os notebooks gravam com `overwrite` + `overwriteSchema`, que
# MAGIC troca o schema e leva junto os comentarios das colunas. Por isso cada notebook termina com:
# MAGIC
# MAGIC ```
# MAGIC %run ./metadados
# MAGIC aplicar_metadados("onibus.silver.posicao_limpa")
# MAGIC ```
# MAGIC
# MAGIC Este notebook so define coisas; nao aplica nada sozinho. Catalogo, schemas e volume (`OBJETOS`)
# MAGIC nao sao regravados por ninguem: basta aplicar uma vez com `aplicar_objetos()`.

# COMMAND ----------

OBJETOS = {
    "CATALOG onibus":
        "Projeto Ônibus SP × Chuva (IME-USP, MAE0350): onde a chuva mais degrada a velocidade dos ônibus "
        "de São Paulo. Camadas: bronze (fiel à fonte), silver (limpo e enriquecido), gold (pronto para os resultados).",
    "SCHEMA onibus.bronze":
        "Dados como vieram da fonte, sem limpeza: arquivos crus no volume raw e a tabela posicao.",
    "SCHEMA onibus.silver":
        "Dados limpos e enriquecidos: GTFS versionado (gtfs_*) e a cadeia de posições "
        "posicao_limpa → posicao_rota → deslocamento → velocidade_trecho.",
    "SCHEMA onibus.gold":
        "Tabelas prontas para os resultados: trechos físicos e seus postos de chuva, chuva por posto com variáveis "
        "derivadas e eventos de chuva, infraestrutura por trecho, velocidade relativa à linha de base e efeito da chuva. Desenho em docs/gold_desenho.md.",
    "VOLUME onibus.bronze.raw":
        "Arquivos crus. olhovivo/: posições da API Olho Vivo (bronze_posicao/ = v1, 25/08–21/09; "
        "bronze_raw/ = v2, desde 21/09) e auditoria.csv da coleta, copiados do Google Drive pelo notebook "
        "00_ingestao_drive. gtfs/versao=AAAA-MM-DD/: GTFS da SPTrans por data de download. "
        "infra/versao=AAAA-MM-DD/: camadas do GeoSampa baixadas no PC, com manifesto.csv.",
}

# --- colunas reaproveitadas entre tabelas ------------------------------------------------------

COL_DT = "Dia de São Paulo (America/Sao_Paulo) do ciclo de coleta, AAAA-MM-DD. Partição."
COL_P = "Prefixo do veículo: identifica o ônibus físico. O mesmo p ao longo de vários ta é uma trajetória."
COL_TA = "Instante (UTC) em que a SPTrans registrou a posição. É o relógio usado para tempo e velocidade."
COL_COLETADO = ("Instante (UTC) do ciclo de coleta na VM. v2: início do ciclo, tirado do nome do arquivo; "
                "v1: gravado pelo coletor. Pode ficar até ~60 s antes de ta (a requisição leva até ~46 s).")
COL_PY = "Latitude (graus). Já vem encaixada no traçado pela SPTrans: não é GPS bruto."
COL_PX = "Longitude (graus). Já vem encaixada no traçado pela SPTrans: não é GPS bruto."
COL_SL = ("Sentido informado pela API: 1 ou 2 (= direction_id do GTFS + 1). Pode atrasar: o ônibus já "
          "voltou e a API ainda manda o sentido antigo.")
COL_FORMATO = "Formato do arquivo de origem: v1 (achatado pelo coletor, até 21/09, ciclo ~2 min) ou v2 (resposta crua, desde 21/09, ciclo 1 min)."
COL_VERSAO = "Versão do GTFS = data do download. O período em que cada versão vale está em gtfs_versao."

BRONZE_COLS = {
    "dt": COL_DT,
    "coletado_em": COL_COLETADO,
    "ta": COL_TA,
    "p": COL_P,
    "c": "Letreiro da linha, ex. 507T-10. Igual ao route_id do GTFS em 99,7% das posições.",
    "cl": "Código interno da SPTrans para linha + sentido. Muda quando o ônibus troca de sentido.",
    "sl": COL_SL,
    "py": COL_PY,
    "px": COL_PX,
    "a": "Veículo acessível (true/false).",
    "lt0": "Terminal 0 da linha (letreiro). Não é o destino atual do ônibus.",
    "lt1": "Terminal 1 da linha (letreiro). Não é o destino atual do ônibus.",
    "hr": "Hora de SP (HH:MM) no topo da resposta da API.",
    "arquivo": "Caminho do arquivo de origem no volume onibus.bronze.raw.",
    "formato": COL_FORMATO,
}

LIMPA_COLS = {
    "dt": COL_DT,
    "p": COL_P,
    "ta": COL_TA,
    "ta_sp": "ta convertido para o horário de parede de São Paulo (America/Sao_Paulo).",
    "tipo_dia": "util, sabado, domingo ou feriado, pela data de ta_sp. Feriados operam com tabela de domingo.",
    "route_id": "Linha (= letreiro c da bronze), com traçado no GTFS do dia.",
    "sl": COL_SL,
    "direction_id": ("Sentido no GTFS (0/1). Linhas de sentido único: sempre o único sentido do GTFS, "
                     "qualquer que seja o sl."),
    "shape_id": "Traçado do GTFS onde a posição é projetada (gtfs_shapes).",
    "sentido_unico": ("true se a linha tem um só sentido/traçado no GTFS (circulares, ~11% das posições). "
                      "Nelas sl=1/2 só indica a metade da volta: troca de sl não é troca de viagem."),
    "versao_gtfs": "Versão do GTFS usada neste dia (gtfs_versao).",
    "py": COL_PY,
    "px": COL_PX,
    "coletado_em": COL_COLETADO,
    "idade_s": "coletado_em − ta, em segundos. Até −60 s é normal (coletado_em é o início do ciclo).",
    "formato": COL_FORMATO,
}

# --- tabelas -----------------------------------------------------------------------------------

TABELAS = {
    "onibus.bronze.posicao": {
        "comentario":
            "Posições dos ônibus como a API Olho Vivo (SPTrans) devolveu: 1 linha por ônibus por ciclo de coleta, "
            "sem limpeza (inclui duplicatas, ônibus parados, posições velhas). Fonte: volume onibus.bronze.raw/olhovivo. "
            "Notebook 01_bronze_posicao, job pipeline-onibus (diário 10h SP, overwrite completo). Partição dt. "
            "Checagem: linhas por dia = soma de veiculos_gravados da auditoria.csv.",
        "colunas": BRONZE_COLS,
    },
    "onibus.silver.gtfs_routes": {
        "comentario":
            "Linhas de ônibus do GTFS da SPTrans, uma versão por download. Chave (versao, route_id). "
            "Notebook 02_silver_gtfs. ~39 linhas estão aqui sem viagem em gtfs_trips (variantes -21/-22 e especiais): "
            "não têm traçado.",
        "colunas": {
            "versao": COL_VERSAO,
            "route_id": "Código da linha, ex. 507T-10. Igual ao letreiro c da API.",
            "agency_id": "Operador (sempre 1 = SPTrans).",
            "route_short_name": "Código curto da linha (igual ao route_id).",
            "route_long_name": "Nome da linha: terminal – terminal.",
            "route_type": "Tipo de transporte no padrão GTFS (3 = ônibus).",
            "route_color": "Cor da linha (hex), para mapas.",
            "route_text_color": "Cor do texto da linha (hex), para mapas.",
        },
    },
    "onibus.silver.gtfs_trips": {
        "comentario":
            "Viagens-modelo do GTFS: uma por linha × sentido × tipo de serviço. Ponte linha + sentido → traçado. "
            "Chave (versao, trip_id). Exatamente 1 shape por (linha, sentido) nas duas versões. "
            "Linhas de sentido único (circulares, ~380) só têm um direction_id. Notebook 02_silver_gtfs.",
        "colunas": {
            "versao": COL_VERSAO,
            "route_id": "Linha (gtfs_routes).",
            "service_id": "Tipo de serviço, isto é, dias de operação (gtfs_calendar).",
            "trip_id": "Código da viagem-modelo, ex. 1012-10-0.",
            "trip_headsign": "Letreiro de destino da viagem.",
            "direction_id": "Sentido no GTFS: 0 ou 1. Na API, sl = direction_id + 1.",
            "shape_id": "Traçado percorrido (gtfs_shapes).",
        },
    },
    "onibus.silver.gtfs_shapes": {
        "comentario":
            "Traçado de cada linha × sentido: pontos em ordem, com a distância acumulada desde o início. "
            "É a régua onde as posições são projetadas (posicao_rota). Chave (versao, shape_id, shape_pt_sequence). "
            "~10% dos pontos repetem o anterior (passo de 0 m). Notebook 02_silver_gtfs.",
        "colunas": {
            "versao": COL_VERSAO,
            "shape_id": "Código do traçado.",
            "shape_pt_lat": "Latitude do ponto (graus).",
            "shape_pt_lon": "Longitude do ponto (graus).",
            "shape_pt_sequence": "Ordem do ponto no traçado (1 = início).",
            "shape_dist_traveled": ("Distância acumulada desde o início do traçado, em metros "
                                    "(confere com a soma das distâncias entre pontos: razão mediana 0,999)."),
        },
    },
    "onibus.silver.gtfs_stops": {
        "comentario":
            "Paradas do GTFS com localização. Chave (versao, stop_id). Entre 26/08 e 12/10: 69 saíram, "
            "95 entraram, 87 mudaram de lugar mais de 1 m. Notebook 02_silver_gtfs.",
        "colunas": {
            "versao": COL_VERSAO,
            "stop_id": "Código da parada.",
            "stop_name": "Nome da parada.",
            "stop_desc": "Descrição da parada (quase sempre vazia).",
            "stop_lat": "Latitude da parada (graus).",
            "stop_lon": "Longitude da parada (graus).",
        },
    },
    "onibus.silver.gtfs_stop_times": {
        "comentario":
            "Sequência de paradas de cada viagem-modelo: dela sai o trecho (parada → parada seguinte). "
            "Chave (versao, trip_id, stop_sequence). Os horários são de uma viagem-modelo: o GTFS da SPTrans "
            "é por frequência, sem horário programado real. Notebook 02_silver_gtfs.",
        "colunas": {
            "versao": COL_VERSAO,
            "trip_id": "Viagem-modelo (gtfs_trips).",
            "arrival_time": "Chegada na viagem-modelo, HH:MM:SS (pode passar de 24:00:00). Não é horário programado real.",
            "departure_time": "Partida na viagem-modelo, HH:MM:SS (pode passar de 24:00:00). Não é horário programado real.",
            "stop_id": "Parada (gtfs_stops).",
            "stop_sequence": "Ordem da parada na viagem (1..n, sem buracos).",
        },
    },
    "onibus.silver.gtfs_frequencies": {
        "comentario":
            "Intervalo programado entre ônibus (headway) por viagem-modelo e faixa horária. Base da medida "
            "secundária (headway programado × observado). Chave (versao, trip_id, start_time). Notebook 02_silver_gtfs.",
        "colunas": {
            "versao": COL_VERSAO,
            "trip_id": "Viagem-modelo (gtfs_trips).",
            "start_time": "Início da faixa horária, HH:MM:SS.",
            "end_time": "Fim da faixa horária, HH:MM:SS.",
            "inicio_s": "Início da faixa em segundos desde 00:00.",
            "fim_s": "Fim da faixa em segundos desde 00:00.",
            "headway_secs": "Intervalo programado entre ônibus, em segundos.",
        },
    },
    "onibus.silver.gtfs_calendar": {
        "comentario":
            "Tipos de serviço do GTFS e os dias da semana em que operam. Chave (versao, service_id). "
            "Ex.: USD = todos os dias; U__ = dias úteis. Notebook 02_silver_gtfs.",
        "colunas": {
            "versao": COL_VERSAO,
            "service_id": "Tipo de serviço.",
            **{d: f"1 se o serviço opera {n}; 0 se não." for d, n in [
                ("monday", "na segunda"), ("tuesday", "na terça"), ("wednesday", "na quarta"),
                ("thursday", "na quinta"), ("friday", "na sexta"), ("saturday", "no sábado"), ("sunday", "no domingo")]},
            "start_date": "Início da validade do serviço.",
            "end_date": "Fim da validade do serviço.",
        },
    },
    "onibus.silver.gtfs_versao": {
        "comentario":
            "Qual versão do GTFS vale em cada dia. Join: dt BETWEEN usar_de AND coalesce(usar_ate, '9999-12-31'). "
            "A primeira versão também cobre os dias antes do download (desde o início da coleta, 25/08). "
            "Limitação: sabemos quando baixamos, não quando a SPTrans mudou. Notebook 02_silver_gtfs.",
        "colunas": {
            "versao": "Versão do GTFS = data do download.",
            "usar_de": "Primeiro dia em que esta versão é usada.",
            "usar_ate": "Último dia em que esta versão é usada (nulo = em uso até hoje).",
        },
    },
    "onibus.silver.posicao_limpa": {
        "comentario":
            "Posições válidas dos ônibus, já ligadas ao traçado do GTFS. Grão: 1 posição de 1 ônibus num instante; "
            "chave (p, ta). Origem: bronze.posicao menos as descartadas (quarentena_posicao); por dia, "
            "bronze = limpa + quarentena. Notebook 03_silver_posicao_limpa (overwrite completo). Partição dt.",
        "colunas": LIMPA_COLS,
    },
    "onibus.silver.quarentena_posicao": {
        "comentario":
            "Posições da bronze que não entraram na posicao_limpa, com o motivo. Mesmas colunas da bronze.posicao "
            "+ motivo. Guardada para auditoria e para reprocessar se uma regra mudar. Notebook 03_silver_posicao_limpa.",
        "colunas": {
            **BRONZE_COLS,
            "motivo": ("Por que saiu (primeira regra que se aplica, nesta ordem): duplicata (mesmo (p, ta) repetido; "
                       "fica a 1ª coleta), coordenada_invalida, ta_no_futuro (ta > coletado_em + 60 s), "
                       "posicao_velha (coletado_em − ta > 5 min), linha_sem_shape (linha sem viagem/traçado no GTFS "
                       "do dia), sentido_sem_shape."),
        },
    },
    "onibus.silver.posicao_rota": {
        "comentario":
            "Onde cada posição está na rota: metro ao longo do traçado. Grão igual ao da posicao_limpa, chave (p, ta): "
            "mesmas linhas, mais 4 colunas. Projeção ortogonal no traçado; onde ele passa duas vezes pela mesma rua "
            "(41% do traçado das circulares), a passagem é escolhida pela continuidade da trajetória do ônibus "
            "(Viterbi). Notebook 04_silver_posicao_rota. Partição dt.",
        "colunas": {
            **LIMPA_COLS,
            "d_m": "Metro ao longo do traçado (0 = início), na régua do shape_dist_traveled do GTFS.",
            "erro_lateral_m": ("Distância da posição até o traçado, em metros. ~0 no traçado certo (a SPTrans publica "
                               "a posição já sobre a rota); alto = traçado desatualizado."),
            "n_candidatos": ("Quantas passagens do traçado estavam a até (melhor erro + 10 m). > 1 = rua percorrida "
                             "duas vezes; d_m escolhido pela continuidade."),
            "comprimento_m": "Comprimento total do traçado, em metros.",
        },
    },
    "onibus.bronze.chuva_sibh": {
        "comentario":
            "Leituras de chuva do SIBH (DAEE/SP Águas), telemetria, como vieram nos CSVs exportados à mão: 141 postos do "
            "município, 01/08–25/10/2026. Uma linha por leitura. Arquivos e verificação: docs/chuva_sibh.md e "
            "manifesto.csv no volume (chuva/sibh/download=2026-10-25). Notebook 07_silver_chuva.",
        "colunas": {
            "prefixo": "Código do posto no SIBH. Texto (há E3-326, A701, 355030873A, 5).",
            "nome": "Nome como no CSV: 'Município (Nome do posto)'.",
            "instante_utc": "Instante da leitura, em UTC (o campo Data do SIBH é UTC).",
            "mm": "Chuva em mm desde a leitura anterior do mesmo posto (incremento). 15 negativos = manutenção do pluviômetro.",
            "arquivo": "CSV de origem (ver manifesto.csv).",
            "data_original": "Campo Data como veio, AAAA/MM/DD HH:MM.",
        },
    },
    "onibus.silver.chuva_10min": {
        "comentario":
            "Chuva por posto numa grade comum de 10 min, em UTC. Cada leitura é repartida igualmente entre os slots de "
            "10 min desde a leitura anterior (até 60 min; mais que isso, os slots anteriores ficam faltantes). Nada é "
            "apagado: problemas viram flags. Soma de mm por posto = soma das leituras não negativas da bronze. "
            "Notebook 07_silver_chuva. Partição dt (dia de SP).",
        "colunas": {
            "prefixo": "Código do posto (silver.postos).",
            "slot_utc": "Início do slot de 10 min, em UTC. O slot é [slot_utc, slot_utc + 10 min).",
            "slot_sp": "slot_utc no horário de São Paulo.",
            "dt": "Dia de São Paulo do slot, AAAA-MM-DD. Partição.",
            "mm": "Chuva no slot, em mm. Nulo = faltante ou negativo — nunca usar como 0.",
            "resolucao_min": ("Intervalo coberto pela leitura que gerou o valor: 10 = medido no slot; 60 = leitura horária "
                              "repartida em 6 slots (rede CEMADEN quando seca, INMET)."),
            "f_faltante": "Nenhuma leitura cobre o slot.",
            "f_negativo": "A leitura que cobre o slot era negativa (manutenção do pluviômetro); mm nulo.",
            "f_intervalo_longo": "Valor veio de uma leitura que cobre mais de 10 min (não se sabe em qual dos 10 min choveu).",
            "f_pico_implausivel": "Mais de 30 mm no slot (180 mm/h): conferir com os vizinhos antes de usar.",
        },
    },
    "onibus.silver.postos": {
        "comentario":
            "Postos de chuva do SIBH no município: coordenadas (stations.json do SIBH), rede, operador e qualidade no "
            "período com ônibus (desde 25/08). status não apaga nada: a gold escolhe quais postos usar. Notebook 07_silver_chuva.",
        "colunas": {
            "prefixo": "Código do posto no SIBH.",
            "nome": "Nome do posto (dos CSVs; o JSON tem acentos corrompidos).",
            "rede": "daee (grade de 10 min), cemaden (IDs 3550308xx: reporta por evento, 1/h quando seco) ou inmet (horária).",
            "operador": "Dono do posto segundo o SIBH: SAISP, SP ÁGUAS, SABESP, ANA, CEMADEN, INMET.",
            "lat": "Latitude (graus decimais).",
            "lon": "Longitude (graus decimais).",
            "resolucao_mediana_min": "Mediana de resolucao_min dos slots: 10 = medido a cada 10 min.",
            "completude": "Fração dos slots de 10 min com valor (não faltante, não negativo) desde 25/08.",
            "maior_lacuna_h": "Maior sequência de slots faltantes desde 25/08, em horas.",
            "mm_total": "Chuva total desde 25/08, em mm.",
            "chuva_1209_mm": "Chuva em 12/09 (SP), dia de chuva forte na cidade inteira. 0 com dado = posto quebrado.",
            "razao_vizinhos": ("mm_total / mediana do mm_total dos 5 vizinhos mais próximos confiáveis (2ª passada: completude "
                               ">= 90% e razão da 1ª passada entre 0,4 e 2,0)."),
            "duplicata_de": "Outro posto no mesmo lugar (< 50 m) com o mesmo total: mesmo pluviômetro cadastrado duas vezes. Usar só um.",
            "dist_media_vizinhos_km": "Distância média aos 5 vizinhos usados na razão, em km.",
            "n_slots_negativos": "Slots marcados f_negativo desde 25/08.",
            "n_picos": "Slots marcados f_pico_implausivel desde 25/08.",
            "status": ("Primeiro que se aplica: sem_dado (nenhuma leitura desde 25/08), quebrado (razao < 0,4 ou 0 mm em 12/09 com dado), suspeito (razao > 2,0), "
                       "lacunar (completude < 90%), ok."),
        },
    },
    "onibus.gold.recuperacao_trecho": {
        "comentario":
            "KR2 por trecho. Depois de eventos com pico >= 2,5 mm/h, em dia útil: razão na 1ª, 2ª e 3ª hora, classe de recuperação e "
            "perda nas 2 h seguintes, para quem tem pelo menos 8 dias e 30 janelas na 2ª hora. Razões na mistura de chuva da cidade, "
            "depois do encolhimento. Não é um tempo exato: uma janela isolada varia ±23%. Notebook 13_gold_recuperacao_trecho.",
        "colunas": {
            "trecho_id": "Trecho físico (gold.trecho).",
            "n_dias_h2": "Dias com janelas na 2ª hora depois do fim.",
            "janelas_h2": "Janelas na 2ª hora depois do fim.",
            "razao_h1": "Razão encolhida na 1ª hora depois do fim. 1 = normal.",
            "p_abaixo_h1": "Probabilidade de a razão verdadeira da 1ª hora estar abaixo de 0,99.",
            "razao_h2": "Razão encolhida na 2ª hora depois do fim.",
            "p_abaixo_h2": "Probabilidade de a razão verdadeira da 2ª hora estar abaixo de 0,99.",
            "razao_h3": "Razão encolhida na 3ª hora depois do fim. Nulo se o trecho não tem dado suficiente.",
            "p_abaixo_h3": "Probabilidade de a razão verdadeira da 3ª hora estar abaixo de 0,99.",
            "classe_recuperacao": "ate_1h, 1h_a_2h, mais_de_2h, mais_de_1h (3ª hora sem resposta) ou indefinido.",
            "perda_2h_min": "Minutos de operação normal perdidos por ônibus nas 2 h depois do fim. Negativo = mais rápido que o normal.",
            "perda_ic_inf": "Limite inferior do intervalo de 95% da perda.",
            "perda_ic_sup": "Limite superior do intervalo de 95% da perda.",
            "nome_de": "Parada de início.",
            "nome_ate": "Parada de fim.",
            "classe_dominante": "Classe de via com maior fração do trecho.",
            "dias_alag_100m": "Dias distintos com alagamento a até 100 m, de 2013 a 24/08/2026.",
            "lat": "Latitude do ponto médio.",
            "lon": "Longitude do ponto médio.",
            "grupo_critico": "Trecho do grupo crítico do notebook 12.",
        },
    },
    "onibus.gold.recuperacao_grupo": {
        "comentario":
            "KR2 por grupo de trechos. Curva da razão depois do fim de eventos com pico >= 2,5 mm/h, em dia útil, com intervalo por "
            "reamostragem de dias. Notebook 13_gold_recuperacao_trecho.",
        "colunas": {
            "dimensao": "via, alagamento, onibus ou critico.",
            "grupo": "Grupo de trechos.",
            "periodo": "Quando a chuva acabou: todos, pico (6-9h e 16-19h) ou fora_do_pico (10-15h e 20-23h).",
            "tau_min": "Minutos depois do fim (0 = janela logo após o fim).",
            "razao": "Soma das distâncias / soma das distâncias esperadas. 1 = normal.",
            "ic_inf": "Limite inferior do intervalo de 95%. Nulo se frágil.",
            "ic_sup": "Limite superior do intervalo de 95%. Nulo se frágil.",
            "fragil": "true se o grupo tem menos de 8 dias: indicativo, sem intervalo.",
        },
    },
    "onibus.gold.tempo_recuperacao_grupo": {
        "comentario":
            "KR2 por grupo de trechos. Tempo de recuperação (razão >= 0,99 por 3 janelas seguidas) e perda nas 2 h seguintes. O grupo "
            "crítico foi escolhido nos mesmos dias: use validacao_recuperacao para ele. Notebook 13_gold_recuperacao_trecho.",
        "colunas": {
            "dimensao": "via, alagamento, onibus ou critico.",
            "grupo": "Grupo de trechos.",
            "periodo": "Quando a chuva acabou: todos, pico ou fora_do_pico.",
            "tempo_rec_min": "Minutos depois do fim até recuperar. Nulo = não recuperou até 170 min.",
            "ic_inf": "Limite inferior do intervalo de 95%. Nulo se frágil.",
            "ic_sup": "Limite superior do intervalo de 95%. Nulo se frágil ou se mais de 2,5% das reamostras não recuperaram.",
            "frac_censurada": "Fração das reamostras que não recuperaram até 170 min.",
            "perda_min": "Minutos de operação normal perdidos por ônibus nas 2 h depois do fim.",
            "perda_ic_inf": "Limite inferior do intervalo de 95% da perda. Nulo se frágil.",
            "perda_ic_sup": "Limite superior do intervalo de 95% da perda. Nulo se frágil.",
            "perda_vs_ref": "Perda do grupo menos a do grupo de referência. Acima de 0 = perde mais.",
            "ref_ic_inf": "Limite inferior do intervalo de 95% de perda_vs_ref. Nulo se frágil.",
            "ref_ic_sup": "Limite superior do intervalo de 95% de perda_vs_ref. Nulo se frágil.",
            "n_trechos": "Trechos no grupo.",
            "n_dias": "Dias com dado no grupo.",
            "janelas": "Janelas trecho × 10 min.",
            "fragil": "true se o grupo tem menos de 8 dias: indicativo, sem intervalo.",
        },
    },
    "onibus.gold.validacao_recuperacao": {
        "comentario":
            "KR2. Validação por divisão dos dias em metades: fiabilidade das medidas por trecho, classificação medida em outros dias e "
            "recuperação dos 1% piores na chuva, medida em dias que não entraram na escolha. Notebook 13_gold_recuperacao_trecho.",
        "colunas": {
            "metrica": ("Nome da métrica. h1, h2 e h3 = 1ª, 2ª e 3ª hora; h1_h2 = 2 h seguidas. piores_ e resto_fora_da_amostra_Nmin = "
                        "razão na faixa que começa N minutos depois do fim."),
            "valor": "Valor observado.",
        },
    },
    "onibus.gold.efeito_trecho": {
        "comentario":
            "KR1 e KR3. Efeito da chuva moderada ou mais forte em cada trecho, em dia útil, 6h-23h, para quem tem pelo menos 8 dias e "
            "30 janelas de chuva, com posto DAEE. Inclui o ranking, a estabilidade por reamostragem de dias e o placebo. "
            "A ordem exata do topo não é estável: use o grupo crítico. Notebook 12_gold_efeito_trecho.",
        "colunas": {
            "trecho_id": "Trecho físico (gold.trecho).",
            "nome_de": "Parada de início.",
            "nome_ate": "Parada de fim.",
            "n_dias": "Dias com chuva moderada+ no trecho.",
            "janelas": "Janelas de 10 min com chuva moderada+.",
            "horas_chuva": "Horas de ônibus nessas janelas.",
            "razao_bruta": "Soma das distâncias / distâncias esperadas na chuva, relativa ao seco do trecho, sem padronizar.",
            "razao_padronizada": "A mesma razão, se o trecho tivesse pegado a mistura de período e intensidade da cidade.",
            "se_log": "Erro da razão padronizada em log, agrupado por dia e moderado.",
            "razao_encolhida": "Razão padronizada depois do encolhimento. É a que ordena o ranking.",
            "ic_inf": "Limite inferior do intervalo de 95% de razao_encolhida (aproximação normal em log).",
            "ic_sup": "Limite superior do intervalo de 95% de razao_encolhida (aproximação normal em log).",
            "p_queda": "Probabilidade posterior de a razão verdadeira ser menor que 1.",
            "rank": "Posição pelo efeito encolhido: 1 = perde mais.",
            "rank_ic_inf": "Percentil 2,5 da posição nas reamostras de dias.",
            "rank_ic_sup": "Percentil 97,5 da posição nas reamostras de dias.",
            "freq_top10": "Fração das reamostras em que o trecho ficou no top-10.",
            "freq_top20": "Fração das reamostras em que o trecho ficou no top-20.",
            "freq_pior1": "Fração das reamostras em que o trecho ficou entre os 1% piores.",
            "freq_pior5": "Fração das reamostras em que o trecho ficou entre os 5% piores.",
            "placebo_seco": ("Log da razão nas janelas secas dos dias com chuva moderada+ menos a dos outros dias. "
                             "Muito negativo = o trecho também fica lento no seco, e a causa pode não ser a chuva."),
            "perto_terminal": "O nome de uma das paradas cita terminal, garagem, metrô ou estação. Parte da queda pode ser espera.",
            "classe_dominante": "Classe de via com maior fração do trecho.",
            "dias_alag_100m": "Dias distintos com alagamento a até 100 m, de 2013 a 24/08/2026.",
            "v_kmh_media": "Velocidade média do trecho, em km/h.",
            "comprimento_m": "Comprimento do trecho, em metros.",
            "lat": "Latitude do ponto médio.",
            "lon": "Longitude do ponto médio.",
            "grupo_critico": "true se freq_pior5 >= 0,8: entre os 5% piores em pelo menos 80% das reamostras.",
            "local_critico": "Código do lugar: trechos críticos a até 300 m têm o mesmo código. -1 = fora do grupo crítico.",
        },
    },
    "onibus.gold.estabilidade_ranking": {
        "comentario":
            "KR3. Métricas de estabilidade do ranking por trecho, por reamostragem de dias e por divisão dos dias em metades. "
            "Só jaccard_mediano e top10_no_top20_em_80pct têm limiar, fixado antes de ver o resultado. Notebook 12_gold_efeito_trecho.",
        "colunas": {
            "metrica": "Nome da métrica.",
            "valor": "Valor observado.",
            "limiar": "Limiar do critério de estabilidade. Nulo = métrica informativa.",
            "passou": "sim ou nao, nas métricas com limiar.",
        },
    },
    "onibus.gold.efeito_infra": {
        "comentario":
            "KR4. Associação entre infraestrutura e o efeito da chuva no trecho, comparando trechos parecidos. "
            "Coeficientes em relação à via coletora, sem faixa, sem corredor. Associação, não causa. Notebook 12_gold_efeito_trecho.",
        "colunas": {
            "modelo": ("principal = trecho típico (peso pela precisão); ponderado_por_onibus = peso pelas horas de ônibus; os demais "
                       "são sensibilidades do principal."),
            "termo": "Atributo do trecho.",
            "coef_log": "Coeficiente, em log da razão. Negativo = perde mais.",
            "ic_inf": "Limite inferior do intervalo de 95%, por reamostragem de dias.",
            "ic_sup": "Limite superior do intervalo de 95%, por reamostragem de dias.",
            "ic_inf_espacial": "Limite inferior do intervalo de 95%, por blocos espaciais de ~2 km. Nulo nas sensibilidades.",
            "ic_sup_espacial": "Limite superior do intervalo de 95%, por blocos espaciais de ~2 km. Nulo nas sensibilidades.",
            "n_trechos": "Trechos no modelo.",
            "pct": "Coeficiente em %: 100 × (exp(coef_log) − 1).",
        },
    },
    "onibus.gold.efeito_grupo": {
        "comentario":
            "KR4 sem modelo. Queda de cada grupo de trechos por intensidade de chuva, somando distâncias: mostra o que o ônibus sente. "
            "Intervalos por reamostragem de dias. Notebook 12_gold_efeito_trecho.",
        "colunas": {
            "dimensao": "via, alagamento, onibus, alagamento_em_arterial ou alagamento_em_coletora.",
            "grupo": "Grupo de trechos.",
            "chuva": "fraca, moderada ou forte+ (forte e muito forte).",
            "razao": "Soma das distâncias / distâncias esperadas na chuva, relativa ao seco do grupo.",
            "ic_inf": "Limite inferior do intervalo de 95%. Nulo se frágil.",
            "ic_sup": "Limite superior do intervalo de 95%. Nulo se frágil.",
            "vs_referencia": "Razão do grupo / razão do grupo de referência, na mesma chuva. Abaixo de 1 = perde mais.",
            "ref_ic_inf": "Limite inferior do intervalo de 95% de vs_referencia. Nulo se frágil.",
            "ref_ic_sup": "Limite superior do intervalo de 95% de vs_referencia. Nulo se frágil.",
            "n_trechos": "Trechos no grupo.",
            "n_dias": "Dias com essa chuva no grupo.",
            "janelas": "Janelas trecho × 10 min.",
            "fragil": "true se tem menos de 8 dias: indicativo, sem intervalo.",
        },
    },
    "onibus.gold.trecho_infra": {
        "comentario":
            "Infraestrutura de cada trecho físico: fração por classe de via, faixa e corredor de ônibus e histórico de alagamento, "
            "a partir do GeoSampa (Fonte: GeoSampa/PMSP, CC BY-SA 4.0). Frações = fração de pontos a cada ~20 m ao longo do traçado. "
            "Notebook 11_gold_trecho_infra.",
        "colunas": {
            "trecho_id": "Trecho físico (gold.trecho).",
            "frac_vtr": "Fração do trecho em via de trânsito rápido (classificação viária CET).",
            "frac_rodovia": "Fração do trecho em rodovia.",
            "frac_arterial": "Fração do trecho em via arterial.",
            "frac_coletora": "Fração do trecho em via coletora.",
            "frac_local": "Fração do trecho em via local.",
            "frac_sem_classe": "Fração do trecho sem via classificada a até 15 m com rumo parecido.",
            "classe_dominante": "Classe com a maior fração: VTR, RODOVIA, ARTERIAL, COLETORA, LOCAL ou SEM_CLASSE.",
            "frac_faixa": "Fração do trecho em via com faixa EXCLUSIVA de ônibus, em qualquer horário.",
            "frac_faixa_longa": "Fração do trecho em faixa exclusiva que vale pelo menos 10 h por dia útil.",
            "frac_faixa_via_dupla": ("Parte de frac_faixa em via de mão dupla. A geometria não indica o sentido da faixa: "
                                     "ela pode estar do outro lado da rua."),
            "frac_corredor": "Fração do trecho a até 25 m de corredor de ônibus em operação.",
            "n_pontos": "Pontos usados no trecho.",
            "dias_alag_50m": "Dias distintos com ALAGAMENTO ou INUNDACAO a até 50 m do trecho, de 01/01/2013 a 24/08/2026.",
            "dias_alag_100m": "Dias distintos com ALAGAMENTO ou INUNDACAO a até 100 m do trecho, de 01/01/2013 a 24/08/2026.",
            "alag_dias_km2_ano": "dias_alag_100m por km² da área a até 100 m do trecho, por ano: compara trechos de comprimentos diferentes.",
            "versao_infra": "Versão dos arquivos em bronze/raw/infra.",
            "versao_gtfs": "Versão do GTFS do traçado usado.",
            "shape_id": "Traçado com mais tempo de ônibus no trecho, usado como geometria.",
        },
    },
    "onibus.gold.efeito_cidade": {
        "comentario":
            "KR1. Quanto a velocidade da cidade cai por classe de chuva e período do dia, em dia útil, relativa ao seco do mesmo período, "
            "com intervalo por reamostragem de dias. Notebook 10_gold_efeito_cidade.",
        "colunas": {
            "recorte": "tudo, ate_20_09 (coleta a 2 min) ou desde_21_09 (coleta a 1 min).",
            "periodo": "manha (6-9h), meio (10-15h), tarde (16-19h), noite (20-23h) ou todos.",
            "classe_chuva": "Classe de chuva da janela (obs_trecho_10min.classe_chuva).",
            "razao": "Soma das distâncias / soma das distâncias esperadas, relativa ao seco do período. 0,90 = 10% mais lento.",
            "ic_inf": "Limite inferior do intervalo de 95% (percentil das reamostras de dias). Nulo se a célula é frágil.",
            "ic_sup": "Limite superior do intervalo de 95%. Nulo se a célula é frágil.",
            "jk_min": "Menor razão tirando um dia por vez.",
            "jk_max": "Maior razão tirando um dia por vez.",
            "n_dias": "Dias com a célula.",
            "janelas": "Janelas trecho × 10 min na célula.",
            "fragil": "true se a célula tem menos de 8 dias: indicativo, sem intervalo.",
        },
    },
    "onibus.gold.recuperacao_cidade": {
        "comentario":
            "KR2. Curva da razão depois do fim da chuva, por período em que ela acabou e intensidade do evento, em dia útil. Inclui as "
            "janelas secas antes da chuva (classe_evento = antecipacao, tau negativo). Só trechos com postos DAEE e janelas a mais de "
            "40 min da próxima chuva. Notebook 10_gold_efeito_cidade.",
        "colunas": {
            "periodo_fim": "Período em que a chuva acabou: manha, meio, tarde, noite ou todos (todos inclui madrugada).",
            "classe_evento": "fraca (pico < 2,5 mm/h), moderada (< 10), forte (>= 10) ou antecipacao.",
            "tau_min": "Minutos depois do fim (0 = janela logo após o fim). Negativo = minutos até a chuva chegar ao posto.",
            "razao": "Soma das distâncias / soma das distâncias esperadas, relativa ao seco. 1 = normal.",
            "ic_inf": "Limite inferior do intervalo de 95%. Nulo se frágil.",
            "ic_sup": "Limite superior do intervalo de 95%. Nulo se frágil.",
            "n_dias": "Dias com janelas neste ponto.",
            "janelas": "Janelas trecho × 10 min neste ponto.",
            "fragil": "true se a curva tem menos de 8 dias: indicativo, sem intervalo.",
        },
    },
    "onibus.gold.tempo_recuperacao": {
        "comentario":
            "KR2. Tempo de recuperação da velocidade e perda acumulada, por período em que a chuva acabou e intensidade do evento. "
            "Recuperado = razão >= 0,99 por 3 janelas seguidas. Notebook 10_gold_efeito_cidade.",
        "colunas": {
            "periodo_fim": "Período em que a chuva acabou: manha, meio, tarde, noite ou todos (todos inclui madrugada).",
            "classe_evento": "fraca (pico < 2,5 mm/h), moderada (< 10) ou forte (>= 10).",
            "tempo_rec_min": "Minutos depois do fim até recuperar. Nulo = não recuperou até 170 min.",
            "ic_inf": "Limite inferior do intervalo de 95%. Nulo se frágil.",
            "ic_sup": "Limite superior do intervalo de 95%. Nulo se frágil ou se mais de 2,5% das reamostras não recuperaram.",
            "frac_censurada": "Fração das reamostras que não recuperaram até 170 min.",
            "perda_min": "Minutos de operação normal perdidos por ônibus nas 2 h depois do fim. Negativo = mais rápido que o normal.",
            "perda_ic_inf": "Limite inferior do intervalo de 95% da perda. Nulo se frágil.",
            "perda_ic_sup": "Limite superior do intervalo de 95% da perda. Nulo se frágil.",
            "n_dias": "Dias com a curva.",
            "janelas": "Janelas trecho × 10 min na curva.",
            "fragil": "true se a curva tem menos de 8 dias: indicativo, sem intervalo.",
        },
    },
    "onibus.gold.obs_trecho_10min": {
        "comentario":
            "Uma linha por trecho físico × janela de 10 min com ônibus e chuva: distância e tempo dos ônibus, chuva dos postos do "
            "trecho (média com peso 1/d²) e classe de chuva. Trecho sem posto não entra. Notebook 09_gold_obs_base. Partição dt.",
        "colunas": {
            "trecho_id": "Trecho físico (gold.trecho).",
            "janela_sp": "Início da janela de 10 min, no horário de São Paulo.",
            "dt": "Dia de São Paulo da janela (não o da coleta). Partição.",
            "tipo_dia": "util, sabado, domingo ou feriado, pelo dia da janela.",
            "dist_m": "Distância percorrida pelos ônibus dentro do trecho na janela, somando as linhas, em metros.",
            "tempo_s": "Tempo gasto pelos ônibus dentro do trecho na janela, somando as linhas, em segundos.",
            "n_pares": "Pedaços de pares de posições que contribuíram.",
            "n_onibus": "Soma, entre as linhas, dos ônibus distintos que passaram.",
            "n_linhas": "Linhas com ônibus no trecho na janela.",
            "hora": "Hora de São Paulo da janela.",
            "dia_semana": "Dia da semana: 1 = domingo ... 7 = sábado.",
            "semana": "Semana do ano (ISO).",
            "grupo_dia": "util, sabado ou domingo_feriado. Usado na linha de base.",
            "mm": "Chuva no slot, média ponderada dos postos com leitura, em mm.",
            "mm_h_30": "Intensidade nos últimos 30 min, média ponderada, em mm/h.",
            "mm_h_60": "Intensidade nos últimos 60 min, média ponderada, em mm/h.",
            "mm_3h": "Acumulado nas últimas 3 h, média ponderada, em mm.",
            "peso_valido": "Soma dos pesos dos postos com mm_h_30 válido (1 = todos os postos do trecho).",
            "seco_estrito": "Todos os postos do trecho em seco estrito.",
            "seco_3h": "Todos os postos do trecho sem chuva nas últimas 3 h.",
            "em_evento": "Algum posto do trecho está dentro de um evento de chuva.",
            "min_desde_fim": "Minutos desde o fim da chuva, no posto em que ela acabou por último. Nulo se algum posto está em evento.",
            "min_ate_proximo": "Minutos até o próximo evento de chuva começar em algum posto do trecho.",
            "frac_cidade_chuva": "Fração dos postos DAEE da cidade chovendo no slot.",
            "pico_evento_mm_h": ("Maior pico de intensidade em 30 min, em mm/h, entre os eventos em andamento ou que acabaram há até "
                                 "3 h nos postos do trecho. Nulo se não houve evento nesse período."),
            "classe_chuva": ("Primeira que se aplica: sem_dado, seco, transbordamento (postos secos, >= 25% da cidade chovendo), "
                             "pos_chuva (sem chuva em 30 min, choveu em 3 h), traco (< 0,4 mm/h), fraca (< 2,5), moderada (< 10), "
                             "forte (< 25), muito_forte."),
        },
    },
    "onibus.gold.linha_base": {
        "comentario":
            "Velocidade normal de cada trecho por hora e grupo de dia: soma das distâncias / soma dos tempos nas janelas secas. "
            "Exige 30 janelas secas em dia útil e 15 nos demais. Combinar com ajuste_dia_hora e ajuste_semana. Notebook 09_gold_obs_base.",
        "colunas": {
            "trecho_id": "Trecho físico.",
            "grupo_dia": "util, sabado ou domingo_feriado.",
            "hora": "Hora de São Paulo.",
            "v_base_ms": "Velocidade normal, em m/s.",
            "n_janelas_secas": "Janelas secas usadas.",
            "n_dias_secos": "Dias com janelas secas usadas.",
            "horas_onibus_secas": "Horas de ônibus nas janelas secas usadas.",
        },
    },
    "onibus.gold.ajuste_dia_hora": {
        "comentario":
            "Fator multiplicativo da cidade por grupo de dia, dia da semana e hora, estimado nas janelas secas: quanto aquele dia e hora "
            "diferem da linha de base do trecho (segunda ~3–4% mais rápida, sexta mais lenta). Notebook 09_gold_obs_base.",
        "colunas": {
            "grupo_dia": "util, sabado ou domingo_feriado.",
            "dia_semana": "Dia da semana: 1 = domingo ... 7 = sábado.",
            "hora": "Hora de São Paulo.",
            "fator_dia_hora": "Fator: soma das distâncias / soma de (tempo × v_base), nas janelas secas.",
            "n_janelas": "Janelas secas usadas.",
        },
    },
    "onibus.gold.ajuste_semana": {
        "comentario":
            "Fator multiplicativo da cidade por semana, estimado nas janelas secas depois do fator de dia e hora. Corrige variações "
            "lentas da velocidade (calendário, demanda). Notebook 09_gold_obs_base.",
        "colunas": {
            "semana": "Semana do ano (ISO).",
            "inicio_semana": "Primeiro dia com janela seca na semana.",
            "fator_semana": "Fator: soma das distâncias / soma de (tempo × v_base × fator_dia_hora), nas janelas secas.",
            "n_janelas": "Janelas secas usadas.",
        },
    },
    "onibus.gold.trecho": {
        "comentario":
            "Trechos físicos: par de paradas consecutivas (parada_de, parada_ate), juntando as linhas que o usam. Tem sentido, "
            "porque as paradas são cadastradas por lado da rua. Inclui trechos atípicos, marcados em f_atipico. Grão da gold. "
            "Notebook 08_gold_base.",
        "colunas": {
            "trecho_id": "Identificador do trecho físico: parada_de>parada_ate.",
            "parada_de": "Parada de início (stop_id do GTFS).",
            "parada_ate": "Parada de fim (stop_id do GTFS).",
            "nome_de": "Nome da parada de início.",
            "nome_ate": "Nome da parada de fim.",
            "lat_de": "Latitude da parada de início.",
            "lon_de": "Longitude da parada de início.",
            "lat_ate": "Latitude da parada de fim.",
            "lon_ate": "Longitude da parada de fim.",
            "lat": "Latitude do ponto médio entre as paradas (usado para achar os postos de chuva).",
            "lon": "Longitude do ponto médio entre as paradas.",
            "comprimento_m": "Comprimento na rota, em metros: mediana entre as linhas que usam o trecho.",
            "dist_reta_m": "Distância em linha reta entre as duas paradas, em metros.",
            "sinuosidade": "comprimento_m / dist_reta_m. ~1 numa rua reta; muito acima ou abaixo disso indica laço ou projeção ruim.",
            "f_atipico": "Trecho suspeito: comprimento < 30 m ou > 3 km, ou sinuosidade < 0,5 ou > 3. Fica fora do ranking (KR3).",
            "n_linhas": "Quantas linhas de ônibus usam o trecho.",
            "linhas": "Linhas que usam o trecho, separadas por vírgula.",
            "horas_onibus": "Total de horas de ônibus dentro do trecho na velocidade_trecho.",
            "v_kmh_media": "Velocidade média do trecho em todo o período (soma das distâncias / soma dos tempos).",
            "fonte_chuva": "De onde vem a chuva do trecho: daee, outra_rede (sem DAEE a 5 km) ou sem_posto.",
            "n_postos": "Quantos postos de chuva o trecho usa (0 a 3).",
            "dist_posto_km": "Distância ao posto mais próximo usado, em km.",
        },
    },
    "onibus.gold.trecho_posto": {
        "comentario":
            "Postos de chuva de cada trecho: até 3 postos DAEE confiáveis a até 5 km do ponto médio, com peso 1/d² (d com piso de "
            "0,1 km); sem DAEE, o posto confiável mais próximo de outra rede a até 5 km. Pesos somam 1 por trecho. "
            "Trecho sem posto não aparece. Notebook 08_gold_base.",
        "colunas": {
            "trecho_id": "Trecho físico (gold.trecho).",
            "prefixo": "Código do posto (silver.postos).",
            "rede": "Rede do posto: daee, cemaden ou inmet.",
            "fonte_chuva": "daee ou outra_rede.",
            "ordem": "1 = posto mais próximo do trecho.",
            "dist_km": "Distância do ponto médio do trecho ao posto, em km.",
            "peso": "Peso do posto na média da chuva do trecho (1/d², normalizado).",
        },
    },
    "onibus.gold.chuva_posto_10min": {
        "comentario":
            "Chuva por posto confiável (status ok, sem duplicata) a cada 10 min, com variáveis derivadas olhando para trás. "
            "Mesmas linhas e mesma chuva da silver.chuva_10min para esses postos. Nulo = não sei, nunca 0. "
            "Notebook 08_gold_base. Partição dt.",
        "colunas": {
            "prefixo": "Código do posto.",
            "rede": "Rede do posto: daee, cemaden ou inmet.",
            "slot_utc": "Início do slot de 10 min, em UTC.",
            "slot_sp": "slot_utc no horário de São Paulo. Casa com janela_sp da velocidade_trecho.",
            "dt": "Dia de São Paulo do slot. Partição.",
            "mm": "Chuva no slot, em mm. Nulo = faltante ou negativo.",
            "resolucao_min": "Intervalo coberto pela leitura que gerou o valor (10 = medido no slot).",
            "f_faltante": "Nenhuma leitura cobre o slot.",
            "f_negativo": "Leitura negativa (manutenção do pluviômetro).",
            "f_intervalo_longo": "Valor veio de leitura que cobre mais de 10 min.",
            "f_pico_implausivel": "Mais de 30 mm no slot: conferir com os vizinhos.",
            "chove": "mm >= 0,2 (resolução do pluviômetro de báscula).",
            "mm_h_30": "Intensidade nos últimos 30 min (este slot e os 2 anteriores), em mm/h. Nulo se faltar leitura.",
            "mm_h_60": "Intensidade nos últimos 60 min, em mm/h. Nulo se faltar leitura.",
            "mm_3h": "Acumulado nas últimas 3 h, em mm. Nulo se faltar leitura.",
            "seco_3h": "Nenhum slot com chuva nas últimas 3 h, com as 18 leituras válidas.",
            "frac_cidade_chuva": "Fração dos postos DAEE confiáveis com chuva neste slot.",
            "seco_estrito": "seco_3h e menos de 25% dos postos DAEE da cidade chovendo. Define a linha de base.",
            "evento_id": "Evento de chuva mais recente que já começou neste posto (gold.evento_chuva).",
            "em_evento": "O slot está dentro desse evento.",
            "min_desde_fim": "Minutos desde o fim do evento (0 = o slot logo depois do fim). Nulo dentro do evento.",
            "min_ate_proximo": "Minutos até o próximo evento começar. Usado no teste de antecipação.",
        },
    },
    "onibus.gold.evento_chuva": {
        "comentario":
            "Eventos de chuva por posto: começa no 1º slot com >= 0,2 mm e termina no último slot com chuva antes de >= 60 min "
            "secos. Slots secos dentro do evento contam na duração. Notebook 08_gold_base.",
        "colunas": {
            "evento_id": "Identificador: prefixo-número do evento no posto.",
            "prefixo": "Código do posto.",
            "rede": "Rede do posto.",
            "tempo_confiavel": "true só para a rede DAEE. CEMADEN e INMET têm leitura horária quando seco: início impreciso.",
            "seq": "Número do evento no posto.",
            "inicio_utc": "Início do 1º slot com chuva, em UTC.",
            "fim_utc": "Fim do último slot com chuva, em UTC.",
            "inicio_sp": "inicio_utc no horário de São Paulo.",
            "fim_sp": "fim_utc no horário de São Paulo.",
            "duracao_min": "Duração, em minutos.",
            "mm_total": "Chuva total no evento, em mm.",
            "relevante": "mm_total >= 1 mm.",
            "pico_mm_h_10": "Maior intensidade em 10 min, em mm/h.",
            "pico_mm_h_30": "Maior intensidade em 30 min, em mm/h.",
            "slots_chuva": "Slots com chuva (>= 0,2 mm) no evento.",
            "slots": "Total de slots do evento.",
            "slots_validos": "Slots do evento com leitura válida.",
            "proximo_inicio_utc": "Início do próximo evento do mesmo posto.",
            "seco_antes_min": "Minutos secos entre o fim do evento anterior e este.",
            "seco_depois_min": "Minutos secos entre este evento e o próximo.",
        },
    },
    "onibus.silver.gtfs_trechos": {
        "comentario":
            "Trechos entre paradas consecutivas de cada traçado, na régua da posicao_rota (metro ao longo do shape). "
            "Paradas do stop_times projetadas no shape em ordem (cada uma adiante da anterior). Chave "
            "(versao, shape_id, trecho_seq). Trechos de ~0 m removidos. Notebook 06_silver_velocidade_trecho.",
        "colunas": {
            "versao": COL_VERSAO,
            "route_id": "Linha do traçado.",
            "direction_id": "Sentido no GTFS (0/1).",
            "shape_id": "Traçado (gtfs_shapes).",
            "trecho_seq": "Ordem do trecho no traçado (1 = da 1ª para a 2ª parada). Pode ter buracos onde um trecho de ~0 m saiu.",
            "parada_de": "Parada de início do trecho (stop_id). (parada_de, parada_ate) = trecho físico, comum a várias linhas.",
            "parada_ate": "Parada de fim do trecho (stop_id).",
            "d_ini_m": "Metro do traçado onde o trecho começa (projeção de parada_de).",
            "d_fim_m": "Metro do traçado onde o trecho termina (projeção de parada_ate).",
            "comprimento_trecho_m": "d_fim_m − d_ini_m, em metros.",
            "erro_parada_de_m": "Distância da parada de início até o traçado (paradas ficam na calçada: ~10–30 m é normal).",
            "fora_de_ordem": "true se alguma das duas paradas não pôde ser projetada adiante da anterior (projeção suspeita).",
            "comprimento_m": "Comprimento total do traçado, em metros.",
        },
    },
    "onibus.silver.velocidade_trecho": {
        "comentario":
            "Velocidade comercial dos ônibus por trecho entre paradas, em janelas de 10 min (horário de SP). Cada par "
            "ok da deslocamento rateia distância e tempo entre os trechos que atravessou (velocidade constante dentro "
            "do par); velocidade = Σ distância / Σ tempo. Par parado conta tempo e distância 0. Notebook "
            "06_silver_velocidade_trecho. Partição dt.",
        "colunas": {
            "dt": COL_DT,
            "janela_sp": "Início da janela de 10 min, no horário de São Paulo.",
            "tipo_dia": ("util, sabado, domingo ou feriado, do primeiro par de cada shape × dt. Perto da meia-noite pode ser o do dia "
                         "vizinho (0,01% das linhas); a gold usa o dia da janela."),
            "route_id": "Linha.",
            "direction_id": "Sentido no GTFS (0/1).",
            "shape_id": "Traçado.",
            "versao_gtfs": "Versão do GTFS usada neste dia (gtfs_versao).",
            "trecho_seq": "Ordem do trecho no traçado (gtfs_trechos).",
            "parada_de": "Parada de início do trecho. (parada_de, parada_ate) = trecho físico.",
            "parada_ate": "Parada de fim do trecho.",
            "comprimento_trecho_m": "Comprimento do trecho, em metros.",
            "dist_m": "Distância percorrida dentro do trecho na janela, somando todos os ônibus, em metros.",
            "tempo_s": "Tempo gasto dentro do trecho na janela, somando todos os ônibus, em segundos.",
            "v_kmh": "Velocidade comercial = dist_m / tempo_s × 3,6 (km/h). Inclui paradas em ponto e semáforo.",
            "n_pares": "Quantos pedaços de pares contribuíram (medida de quanto dado sustenta a velocidade).",
            "n_onibus": "Quantos ônibus distintos passaram pelo trecho na janela.",
        },
    },
    "onibus.silver.deslocamento": {
        "comentario":
            "Pares de posições consecutivas do mesmo ônibus no mesmo dia: de onde para onde na régua da rota e em "
            "quanto tempo. Unidade de observação da velocidade. Todo par fica, classificado em situacao; só os 'ok' "
            "seguem para a velocidade_trecho. Ecos (posição antiga reenviada pela API) saem antes de formar os pares. "
            "Por dia: posições da posicao_rota = pares + ecos + ônibus. Notebook 05_silver_deslocamento. Partição dt.",
        "colunas": {
            "dt": COL_DT,
            "p": COL_P,
            "route_id": "Linha da posição final do par.",
            "direction_id": "Sentido no GTFS (0/1) da posição final do par.",
            "shape_id": "Traçado da posição final do par. Se diferente do traçado inicial, o par é nova_viagem.",
            "sentido_unico": "true se a linha tem um só traçado no GTFS (circulares): troca de sl não é troca de viagem.",
            "versao_gtfs": "Versão do GTFS usada neste dia (gtfs_versao).",
            "tipo_dia": "util, sabado, domingo ou feriado, pela data de ta_sp da posição final.",
            "formato": COL_FORMATO,
            "ta_ini": "Instante (UTC) da posição inicial do par.",
            "ta_fim": "Instante (UTC) da posição final do par.",
            "ta_sp_ini": "ta_ini no horário de São Paulo.",
            "ta_sp_fim": "ta_fim no horário de São Paulo.",
            "d_ini_m": "Metro da rota na posição inicial (posicao_rota.d_m).",
            "d_fim_m": "Metro da rota na posição final (posicao_rota.d_m).",
            "comprimento_m": "Comprimento total do traçado, em metros.",
            "py_ini": "Latitude da posição inicial (graus).",
            "px_ini": "Longitude da posição inicial (graus).",
            "py_fim": "Latitude da posição final (graus).",
            "px_fim": "Longitude da posição final (graus).",
            "dt_s": "Tempo entre as duas posições, em segundos (ta_fim − ta_ini).",
            "dd_m": "Distância percorrida na rota, em metros (d_fim_m − d_ini_m). Negativa = recuo.",
            "v_kmh": "Velocidade comercial do par (dd_m / dt_s × 3,6), em km/h. Inclui paradas e semáforos.",
            "situacao": ("Classificação do par (primeira que se aplica): buraco (Δt > 5 min), nova_viagem (mudou de "
                         "traçado ou foi do fim para o início), terminal (as duas pontas a até 200 m do início ou "
                         "do fim e |Δd| < 50 m), recuo (Δd < −30 m; inclui sentido atrasado da API), rapido (> 80 km/h), parado_longo (par ok dentro de "
                         "sequência parada |Δd| < 10 m que soma >= 20 min: frota estacionada fora do terminal), ok."),
        },
    },
}

# COMMAND ----------

def _texto(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def aplicar_metadados(tabela):
    """Comentario da tabela e de cada coluna. Avisa (sem falhar) se faltar descricao."""
    m = TABELAS[tabela]
    spark.sql(f"COMMENT ON TABLE {tabela} IS {_texto(m['comentario'])}")
    colunas = spark.table(tabela).columns
    for col in colunas:
        if col in m["colunas"]:
            spark.sql(f"ALTER TABLE {tabela} ALTER COLUMN `{col}` COMMENT {_texto(m['colunas'][col])}")
    sem = sorted(set(colunas) - set(m["colunas"]))
    if sem:
        print(f"aviso: colunas sem descricao em {tabela}: {sem}")
    print(f"metadados aplicados: {tabela}")


def aplicar_objetos():
    for objeto, texto in OBJETOS.items():
        spark.sql(f"COMMENT ON {objeto} IS {_texto(texto)}")
