---
title: "Gold — revisão de literatura"
subtitle: "Chuva e velocidade de ônibus: efeitos, métodos e armadilhas"
author: "Projeto Ônibus SP × Chuva"
date: "25/10/2026"
lang: pt-BR
---

# Como ler

Revisão feita em 25/10/2026 para orientar o desenho da gold (`docs/gold_desenho.md`). Legenda: **[V]** número conferido no resumo ou texto; **[S]** número de fonte secundária/snippet, não conferido no original; **[Q]** só resultado qualitativo ou sem acesso aos números.

**Resumo:** poucos estudos de ônibus com AVL publicam efeitos em %; a maioria é de tráfego geral. Ordens de grandeza: chuva leve 0–4%, moderada 2–6%, forte 4–15% (maior no pico), trechos críticos/alagáveis 20–40%. A evidência mais próxima é Rio (ônibus GPS + 33 pluviômetros) e Shenzhen (recuperação). Heterogeneidade por tipo de via e faixa exclusiva é consistente. Recuperação costuma ser "voltar para dentro de uma banda da linha de base". Para ranking, o padrão é encolhimento por Bayes empírico com bootstrap por dia.

# 1. Estudos-chave

## Transporte coletivo com AVL/GPS

| Citação | Cidade | Dados / método | Efeito |
|---|---|---|---|
| Hofmann & O'Mahony (2005), *IEEE ITSC*, doi:10.1109/ITSC.2005.1520087 | Dublin | AVL, dias com/sem chuva | [Q] chuva piora tempo de viagem, headway, bunching |
| Mazloumi, Currie & Rose (2010), *J. Transp. Eng.* 136(7), doi:10.1061/(ASCE)TE.1943-5436.0000126 | Melbourne | GPS, regressão da variabilidade | [V] chuva significativa só no pico da manhã |
| Mesbah, Lin & Currie (2015), *J. Traffic Transp. Eng.* 2(3), doi:10.1016/j.jtte.2015.03.001 | Melbourne (bonde) | AVL 2006–2010, regressão | [V] ~+8 s de tempo médio por mm no pico |
| Mesbah, Luy & Currie (2014), *WIT Trans.* 191, doi:10.2495/SC140671 | Melbourne (bonde) | defasagens do clima | [V/Q] pesa a chuva durante a viagem e na última hora |
| French & O'Mahony (2021), *IEEE ITSC*, doi:10.1109/ITSC48978.2021.9564546 | Dublin | AVL, 3 tipos de rota (faixa exclusiva total/parcial/misto) | [Q] efeito depende da estação e do tipo de rota |
| Su & Yang (2022), *J. East China Jiaotong Univ.* 39(3) | China | GPS de ônibus + chuva horária | [Q] faixas exclusivas reduzem a flutuação |
| Chaves Maia (2022–2024), SSRN 4283281; slides Banco Mundial; nota FGV | Rio | GPS de ônibus a 15 min (2017–18), picos, grade 1 km², 33 pluviômetros, EF de linha e célula | [V slides] −1,03% (Atenção) a −7,30% (Crise); efeito local até 41,9%. [S] nota FGV 8,94%; [S] SSRN 13,9–34,8% no pico. **Versões divergem.** BRT atenua |
| Mohammadi (2023), dissertação U. Calgary, doi:10.11575/PRISM/40772 | Calgary | AVL/APC, 16 pluviômetros de 5 min | [Q] negativo, varia por linha |
| Chen, Saidi & Sun (2025), *Transp. Res. C* 171, doi:10.1016/j.trc.2025.105000 | Calgary | mistura gaussiana bayesiana | [Q] clima afeta sobretudo os atrasos extremos (caudas) |
| Novales et al. (2021), *J. Public Transp.* 23(1) | A Coruña | observação em parada | [Q] tempo perdido no embarque cresce com chuva forte |

## Tráfego urbano geral

| Citação | Cidade | Dados / método | Efeito |
|---|---|---|---|
| Tsapakis, Cheng & Bolbol (2013), *J. Transp. Geogr.* 28, doi:10.1016/j.jtrangeo.2012.11.003 | Londres | ANPR (carros), 380+ links | [V] tempo +0,1–2,1% (leve), +1,5–3,8% (moderada), +4,0–6,0% (forte); links longos da periferia mais afetados |
| Zhang et al. (2018), *IET ITS* 12(2), doi:10.1049/iet-its.2017.0039 | Pequim | floating car, por classe de via | [V] chuva forte no pico −15,2% (expressa), −13,4% (arterial), −12,2% (coletora); [S] leve −3 a −5% |
| Lam et al. (2013), *J. Transp. Eng.* 139(7) | Hong Kong | AVI | [S] −4,2% / −6,3% / −7,3% |
| Li, Luo & Luan (2021), *ISPRS IJGI* 10(8), doi:10.3390/ijgi10080557 | Shenzhen | GPS de táxi; 44 estações horárias por krigagem | [V] um grupo recupera (−14,7% → −9,4%); arteriais longas/alagáveis pioram depois do pico (−21,9% → −25,2%). Só 5 dias de chuva |
| Tang et al. (2024), *Remote Sens.* 16(17), doi:10.3390/rs16173311 | Shenzhen | velocidade DiDi; chuva em grade horária; triângulo de resiliência | [V] linha de base = mesma via × dia da semana × hora em dias secos; fim da recuperação = último instante com queda > 0,5 km/h numa janela de até k horas |
| Sakhare et al. (2023), *Vehicles* 5(1), doi:10.3390/vehicles5010009 | Indiana | veículos conectados, chuva de modelo | [V] −8,4% em chuva muito forte |
| Kasmalkar et al. (2020), *Sci. Adv.* 6(32), doi:10.1126/sciadv.aba2423 | — | congestionamento por alagamento | atrasos se propagam além da área afetada (transbordamento) |

## São Paulo e Brasil

| Citação | Conteúdo |
|---|---|
| Gonçalves (2018), dissertação Poli-USP | chuva relevante para a variabilidade da velocidade, maior entre 16h e 19h (já lida) |
| Tomás et al. (2022), *Trans. GIS* 26(5), arXiv:2204.05982 | mapa de suscetibilidade/exposição a alagamento com dados de mobilidade — insumo para KR4; não estima velocidade |
| Simoyama, Tomás et al. (2022), *Ind. Manag. Data Syst.* 122(10) | rede ótima de pluviômetros para impacto na mobilidade; usa base real de eventos |
| Mendes, Negri & Santos (2023), *GEOINFO* | dataset de lentidão de 2019 com chuva, alagamentos e acidentes |
| Haddad & Teixeira (2015), *Habitat Int.* 45 | custo econômico dos alagamentos em SP |
| Geotab (2026), via CNN Brasil (06/04/2026) | **não revisado**: −3,2% em dias chuvosos, até −14,8% em chuva intensa (mesmo segmento, hora e dia da semana) |

**Correção para o `CLAUDE.md`:** "Chaves Gonçalves 2026" não foi encontrado — provavelmente mistura de Pedro Henrique **Chaves** Maia (FGV, Rio) com Erick Sobreiro **Gonçalves** (Poli-USP 2018).

# 2. Recomendações de método

**Linha de base:** segmento × faixa horária × tipo de dia em janelas secas estritas (nada no pluviômetro nas 2–3 h anteriores **e** pouca chuva no resto da cidade, por causa do transbordamento — Kasmalkar 2020); efeito fixo de semana (setembro atípico).

**Modelo:** log da velocidade ponderado pelo tempo/passagens; efeitos fixos segmento × hora × tipo de dia + chuva com defasagens + semana. Duas versões: **(A) efeito total** sem efeito fixo de data × hora; **(B) efeito local** com efeito fixo de data × hora por macrozona.

**Inferência:** erro-padrão por cluster de dia (ou duas vias, segmento e dia; Cameron, Gelbach & Miller 2011, *JBES* 29(2)), Driscoll & Kraay (1998); com ~60 dias, **wild cluster bootstrap** (Cameron, Gelbach & Miller 2008, *REStat* 90(3)). Tamanho efetivo ≈ número de eventos, não de janelas.

**Caudas:** regressão quantílica (τ = 0,1/0,5/0,9) ou MMQR com efeitos fixos (Machado & Santos Silva 2019, *J. Econometrics* 213(1)).

**Defasagens:** intensidade em t, acumulados de 30 e 60 min, tempo desde o fim (spline); completo: DLNM (Gasparrini, Armstrong & Kenward 2010, *Stat. Med.* 29(21)).

**Limiares:** leve < 2,5, moderada 2,5–7,6 (ou 10), forte > 7,6 (ou 10) mm/h (AMS; Bureau of Meteorology usa 2,5/10); classe "muito forte" por analogia ao Alerta Rio (≥ 25 mm/h ou ≥ 15 mm em 15 min). Números oficiais da OMM e do CGE não confirmados. Estimar também a curva contínua.

**Pluviômetro → segmento:** decorrelação de chuva convectiva ~5 km e ~5 min; estratiforme ~17 km e 15 min (Cristiano et al. 2017, *HESS* 21, revisando Emmanuel et al. 2012). Recomendação: **IDW (potência 2) a até 5 km**; sensibilidade com o mais próximo a 2/3/5 km (o efeito deve crescer com o posto mais perto: erro de medida atenua); krigagem opcional (ganha pouco a 10 min); covariável de chuva no resto da cidade.

**Recuperação (KR2):** evento = intervalos com chuva ≥ resolução separados por período seco mínimo de 60 min (sensibilidade 30 e 120; Dunkerley 2008 mostra que isso muda muito o número de eventos). Recuperação = primeiro t após o fim em que a anomalia volta à banda da linha de base e fica ≥ 30 min; busca até 3 h. Perda = área do triângulo (Bruneau et al. 2003). Estudo de evento com erros por dia; por trecho, sobrevivência com censura (nova chuva, fim da operação). *Leads* antes do início devem ser ≈ 0.

**Ranking (KR3):** dois estágios — efeito por trecho com erro por dia; depois Bayes empírico com covariáveis (Fay–Herriot ou `ashr`, Stephens 2017, *Biostatistics* 18(2)), que também responde ao KR4. Ranquear pela posterior (P(rank ≤ 10); Lin et al. 2006, *Bayesian Anal.* 1(4)); estabilidade por bootstrap por dia com Jaccard; m-de-n se efeitos próximos (Hall & Miller 2009, *Ann. Statist.* 37(6B)); multiplicidade por Benjamini–Hochberg ou lfsr. Considerar corredores como unidade.

**Previsão (KR5):** alvo = anomalia em t+10…t+60; referências persistência e perfil histórico; ridge e LightGBM; validação por blocos de dias em ordem temporal (Roberts et al. 2017, *Ecography* 40(8)); métricas estratificadas por condição de chuva.

# 3. Armadilhas

1. Linha de base contaminada por chuva em outra região ou por poucos dias secos em setembro.
2. Confundidores de calendário: suspensão do rodízio em chuva forte (14/10, 17h–20h, segundo a imprensa), feriados de 07/09 e 12/10, eleição de 04/10, jogos, greves.
3. Dado faltante informativo: em alagamento os ônibus somem do trecho → subestima o efeito; modelar também o número de observações.
4. Atenuação por erro de medida da chuva → efeitos são limites inferiores.
5. Pseudo-replicação: janelas de 10 min como independentes dão intervalos estreitos demais.
6. Ranking sem encolhimento é dominado por trechos com pouco dado.
7. Métrica: vias rápidas perdem mais em %; para somar ao longo de rota, usar pace (s/km).
8. Mecanismos misturados: embarque e tráfego.
9. Desalinhamento de uma janela entre pluviômetro e velocidade desloca as defasagens — testar *leads*.
10. Vazamento na previsão (linha de base ou sensibilidade calculadas com dias de teste).
11. Generalização: dois meses com setembro recorde; não extrapolar para a convecção de verão.

**Incertezas:** faltam estudos de ônibus com AVL que deem efeito por intensidade em %; números de Dublin e Calgary não verificados; versões do estudo do Rio divergem; limiares OMM/CGE não confirmados numericamente.
