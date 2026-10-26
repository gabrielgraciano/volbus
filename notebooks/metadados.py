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
        "Tabelas prontas para os resultados (efeito da chuva por trecho). Ainda vazio.",
    "VOLUME onibus.bronze.raw":
        "Arquivos crus. olhovivo/: posições da API Olho Vivo (bronze_posicao/ = v1, 25/08–21/09; "
        "bronze_raw/ = v2, desde 21/09) e auditoria.csv da coleta, copiados do Google Drive pelo notebook "
        "00_ingestao_drive. gtfs/versao=AAAA-MM-DD/: GTFS da SPTrans por data de download.",
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
            "tipo_dia": "util, sabado, domingo ou feriado.",
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
                         "do fim e |Δd| < 50 m), recuo (Δd < −30 m; inclui sentido atrasado da API), rapido (> 80 km/h), ok."),
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
