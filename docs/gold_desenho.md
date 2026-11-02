---
title: "Gold — desenho"
subtitle: "Como medir o efeito da chuva na velocidade dos ônibus, trecho a trecho"
author: "Projeto Ônibus SP × Chuva · Gabriel Graciano Dias"
date: "25/10/2026, atualizado em 02/11/2026"
lang: pt-BR
---

# Para que serve a gold

A silver tem as duas metades do problema, separadas: **velocidade por trecho entre paradas a cada 10 min** (`silver.velocidade_trecho`) e **chuva por posto a cada 10 min** (`silver.chuva_10min`). A gold junta as duas e responde aos KRs:

| KR | Pergunta | Saída da gold |
|---|---|---|
| KR1 | Quanto a velocidade cai durante a chuva, por trecho? | efeito por intensidade de chuva (cidade, período do dia, trecho) |
| KR2 | Quanto tempo leva para a velocidade voltar ao normal? | curva de recuperação depois do fim da chuva |
| KR3 | Quais os 10 trechos mais afetados, com ranking estável? | efeito por trecho com incerteza, ajustado por quantidade de dado, e frequência no top-10 |
| KR4 | A queda está associada a tipo de via e histórico de alagamento? | efeito por trecho × atributos de infraestrutura |
| KR5 (aspiracional) | Dá para prever a queda na próxima hora? | modelo preditivo com validação temporal |

Este documento registra **o que os dados mostraram numa primeira exploração** (25/10) e **as decisões de desenho que saem disso**. As consultas estão em `analises/gold_exploracao/`.

# 1. O que os dados mostraram

Todas as contas desta seção: **dia útil, 6h–22h, 25/08 a 24/10**; chuva do **posto DAEE confiável mais próximo** do trecho (70 postos).

## 1.1 Quanto dado cada trecho tem

- **28.970 trechos físicos** (par de paradas consecutivas, juntando todas as linhas que passam ali) têm velocidade em dia útil. Metade é servida por uma linha só; 10% por 7 ou mais.
- Na mediana, um trecho tem velocidade em **75% das janelas de 10 min**; 21.883 têm em pelo menos metade.
- **Mas cada janela tem, na mediana, só 2 passagens de ônibus.** Uma velocidade de 10 min sozinha é ruidosa: o efeito precisa ser estimado agregando muitas janelas.

## 1.2 Distância até um posto confiável

| | Mediana | 90% dos trechos | 98% dos trechos |
|---|---|---|---|
| posto confiável mais próximo (qualquer rede) | **1,6 km** | até 3,4 km | até 5 km |

85% dos trechos têm um posto confiável a até 3 km.

## 1.3 A chuva é parecida a que distância?

Correlação entre pares de postos DAEE:

| Distância | a 10 min | a 1 h |
|---|---|---|
| até 2 km | **0,89** | 0,94 |
| 3–5 km | 0,72 | 0,88 |
| 5–8 km | 0,61 | 0,83 |
| 8–12 km | 0,52 | 0,77 |
| 20–30 km | 0,32 | 0,64 |

O posto mais próximo (1,6 km na mediana) representa bem a chuva do trecho; acima de ~5 km a representação piora rápido. Ressalva: set/out de 2026 tiveram chuva **frontal** (espalhada). No verão, chuva convectiva é mais localizada e a correlação cai mais rápido com a distância.

**A rede CEMADEN piora a correlação a 10 min**, e por um motivo que importa: quando seca, ela manda uma leitura por hora; quando volta a chover, a primeira leitura cobre a hora inteira e o rateio da silver **espalha a chuva até 50 min antes de ela começar**. Para medir início e fim de chuva (KR2), isso é um problema.

**Falta de dado nos postos não tem relação com chuva:** a chuva média na cidade é a mesma quando o posto está com ou sem dado (0,337 vs 0,336 mm/h). Não há o viés "o posto cai durante o temporal".

## 1.4 Primeira estimativa do efeito (KR1)

Velocidade relativa à **velocidade normal do mesmo trecho e hora em período seco** (3 h sem chuva no posto), por intensidade da chuva nos últimos 30 min. Razão = Σ distância ÷ Σ(tempo × velocidade normal), ou seja, ponderada pelo tempo que os ônibus passaram no trecho.

| Chuva nos últimos 30 min | Pico manhã (6–9h) | Fora do pico | Pico tarde (16–19h) | Janelas |
|---|---|---|---|---|
| seco (3 h sem chuva) | 1,000 | 1,000 | 1,000 | 61,0 M |
| pós-chuva (choveu nas 3 h, não nos 30 min) | 0,978 | 1,000 | 0,992 | 9,6 M |
| fraca (< 2,5 mm/h) | 0,962 | 0,971 | 0,944 | 6,5 M |
| moderada (2,5–10 mm/h) | 0,939 | 0,960 | **0,900** | 1,9 M |
| forte (10–25 mm/h) | 0,918 | 0,923 | **0,885** | 288 mil |
| muito forte (≥ 25 mm/h) | — | 0,880 | **0,819** | 53 mil |

**Relação dose-resposta clara**: de −3% a −6% com chuva fraca até **−18% com chuva muito forte no pico da tarde**. O pico da tarde é o mais sensível.

## 1.5 Recuperação depois da chuva (KR2)

Mesma razão, para janelas sem chuva nos últimos 30 min, pelo tempo desde a última chuva no posto:

| Minutos desde o fim | Fraca | Moderada | Forte (pico ≥ 10 mm/h) |
|---|---|---|---|
| 20 | 0,983 | 0,972 | 0,970 |
| 40 | 0,982 | 0,974 | 0,976 |
| 60 | 0,987 | 0,984 | 0,984 |
| 80 | 0,990 | 0,992 | 0,993 |
| 100–120 | ~1,00 | ~1,00 | ~1,00 |

**A velocidade volta ao normal ~1h30–2h depois do fim da chuva**, inclusive depois de chuva forte. *(Média do dia inteiro: a seção 1.11 mostra que o tempo depende muito da hora em que a chuva acaba.)* Linha de base com 3 h ou com 6 h sem chuva dá o mesmo resultado (0,971 vs 0,970 aos 20 min): **3 h sem chuva é uma linha de base segura.**

## 1.6 Efeito por trecho (KR3)

Para chuva moderada ou mais (≥ 2,5 mm/h nos últimos 30 min):

- cada trecho tem, na mediana, **78 janelas de chuva — mas em só ~12 dias de chuva**. Janelas do mesmo dia não são independentes: **a evidência efetiva de cada trecho é de ~12 dias**;
- efeito mediano **−3,3%** (razão 0,967); os 10% mais afetados perdem 15% ou mais; 10% ficam até 4% *mais rápidos* (ruído e efeitos reais);
- a dispersão entre trechos cai com mais dado (desvio 0,115 com 20–50 janelas → 0,084 com ≥ 100) mas não some: **parte é ruído, parte é diferença real**. Separar as duas é o problema do KR3.

## 1.7 A linha de base muda com o dia da semana e com o tempo

Velocidade em período seco, relativa à linha de base trecho × hora:

| | Seg | Ter | Qua | Qui | Sex |
|---|---|---|---|---|---|
| até 20/09 (coleta a 2 min) | 1,032 | 1,006 | 0,987 | 0,984 | 0,967 |
| desde 21/09 (coleta a 1 min) | 1,039 | 1,014 | 0,998 | 1,000 | 0,997 |

- **Segunda ~3–4% mais rápida, sexta mais lenta.** Sem ajuste, uma chuva numa segunda parece menor e numa sexta, maior.
- O período desde 21/09 fica ~1% acima. Pode ser real (mudança de calendário, de demanda) ou da mudança de cadência da coleta; não dá para separar com estes dados. Por semana, a velocidade seca varia de 0,985 a 1,015.

## 1.8 Dois testes de validade

**Antecipação (leads):** antes de a chuva começar, a velocidade deveria estar normal. Janelas secas (3 h sem chuva no posto), pelo tempo até o posto registrar chuva:

| Minutos até a chuva no posto | 0–20 | 20–40 | 40–60 | ≥ 60 |
|---|---|---|---|---|
| Razão | 0,982 | 0,993 | 0,998 | ~1,000 |

- **Confirma o fuso**: com 3 h de desalinhamento, a queda apareceria horas antes, não 20–40 min.
- O resíduo (−1,8% nos 20 min anteriores) é o esperado com o posto a ~1,6 km: a chuva chega ao trecho antes do posto, ou começa como garoa abaixo da resolução do pluviômetro (0,2 mm). Consequência: a chuva do posto **mede o efeito com erro**, o que o puxa para zero — os efeitos estimados são, se tanto, **limites inferiores** (ver 2.9).
- Alinhamento dos relógios conferido: na silver, a leitura das 14:50 (que acumula 14:40–14:50) vai para o slot que **começa** às 14:40, a mesma convenção da janela de velocidade.

**Contaminação da linha de base pela chuva em outra região:** janelas com o posto do trecho seco, pela fração dos postos DAEE da cidade chovendo no mesmo slot:

| Resto da cidade | Fora do pico | Pico manhã | Pico tarde | % das janelas secas |
|---|---|---|---|---|
| tudo seco | 1,000 | 1,000 | 1,001 | 87,4% |
| até 25% dos postos chovendo | 1,003 | 0,999 | 0,997 | 11,9% |
| 25% ou mais chovendo | **0,961** | 1,031 | **0,973** | 0,7% |

Há transbordamento (o congestionamento se espalha para onde não chove), mas em 0,7% das janelas secas: quase não mexe na linha de base. Mesmo assim, a definição de "seco" passa a exigir a cidade predominantemente seca (2.4).

**Ônibus somem durante a chuva?** Fração dos trechos de cada posto com dado na janela, relativa à fração normal (seca) no mesmo horário:

| Chuva | fraca | moderada | forte | muito forte |
|---|---|---|---|---|
| trechos com dado (vs. seco) | 0,988 | 0,982 | 0,978 | **0,961** |

Há um **dado faltante informativo pequeno**: com chuva muito forte, 4% menos trechos têm dado. Os piores momentos somem um pouco da amostra, então o efeito fica levemente **subestimado** — mais uma razão para ler os efeitos como limites inferiores e para analisar o número de passagens como desfecho (2.9).

## 1.10 Robustez da primeira estimativa (26/10)

Mesmas razões da 1.4, agora com **intervalo de confiança por bootstrap de dias** (2.000 reamostras de dias inteiros), **jackknife** (tirando um dia por vez) e separando setembro × outubro e o período a 1 min (21/09–24/10). "Forte+" = ≥ 10 mm/h.

| Classe | Período | Dias com a classe | Razão | IC 95% | Jackknife (mín–máx) | Set. | Out. | Só 1 min |
|---|---|---|---|---|---|---|---|---|
| pós-chuva | fora do pico tarde | 41 | 0,991 | 0,980–1,001 | 0,988–0,993 | 0,980 | 1,008 | 1,007 |
| fraca | fora do pico tarde | 39 | 0,967 | 0,951–0,981 | 0,963–0,970 | 0,962 | 0,976 | 0,979 |
| moderada | fora do pico tarde | 19 | 0,950 | 0,932–0,971 | 0,943–0,954 | 0,949 | 0,958 | 0,947 |
| forte+ | fora do pico tarde | 14 | 0,916 | 0,901–0,955 | 0,912–0,930 | 0,911 | 0,948 | 0,928 |
| pós-chuva | pico tarde | 28 | 0,992 | 0,961–1,017 | 0,986–1,003 | 0,994 | 0,990 | 0,999 |
| fraca | pico tarde | 27 | 0,944 | 0,911–0,977 | 0,937–0,958 | 0,931 | 0,971 | 0,976 |
| moderada | pico tarde | 12 | 0,900 | 0,871–0,938 | 0,887–0,921 | 0,920 | 0,876 | 0,877 |
| forte+ | pico tarde | **6** | 0,869 | não estimável | 0,860–0,901 | **0,958** | **0,863** | 0,863 |

**Leitura:**
- **Robusto:** chuva fraca, moderada e forte reduzem a velocidade, com intervalos que excluem 1, nenhum dia sozinho mudando o resultado (jackknife estreito) e a mesma direção em setembro e outubro. A dose-resposta se mantém.
- **Frágil:** chuva forte **no pico da tarde** — só 6 dias; setembro e outubro discordam (0,958 vs 0,863); o bootstrap não estima (há reamostras sem nenhum desses dias). Os números "−12% a −18% no pico da tarde" da 1.4 são indicativos, não conclusivos.
- **Pós-chuva agregado (0–3 h depois):** pequeno e com intervalo que inclui 1; o efeito de recuperação está concentrado nos primeiros ~40 min (1.5) e precisa ser estimado por evento (2.6), não por esse agregado.
- **Magnitude da chuva fraca varia com o período** (set. −3,8% × out. −2,4%): parte pode ser composição de dias da semana ou a mudança de cadência; o modelo com ajuste por dia da semana e semana (2.4–2.5) deve resolver.

## 1.9 Comparação com a literatura

Revisão completa em `docs/gold_literatura.md`. Poucos estudos de ônibus com AVL publicam efeito em %; a maior parte é de tráfego geral.

| Fonte | Leve | Moderada | Forte | Observação |
|---|---|---|---|---|
| Tsapakis et al. 2013 (Londres, carros, ANPR) | +0,1–2,1% tempo | +1,5–3,8% | +4,0–6,0% | links longos da periferia sofrem mais |
| Zhang et al. 2018 (Pequim, floating car) | −3 a −5% | — | −12 a −15% no pico | tráfego levemente congestionado é o mais sensível |
| Lam et al. 2013 (Hong Kong) | −4,2% | −6,3% | −7,3% | via fonte secundária |
| Chaves Maia (Rio, ônibus GPS, 33 pluviômetros) | — | −1,0% (Atenção) | −7,3% (Crise) | efeito local até ~42%; BRT atenua; versões do estudo divergem |
| Geotab 2026 (SP, telemetria, não revisado) | −3,2% dias chuvosos | — | até −14,8% | mesmo segmento, hora e dia da semana |
| **Este projeto (SP, ônibus, 70 postos a 10 min)** | **−3 a −6%** | **−4 a −10%** | **−8 a −12%** (muito forte: até −18%) | pico da tarde o mais sensível |

**Nossos números estão na faixa da literatura**, um pouco acima — esperado para ônibus, que somam ao tráfego o embarque mais lento com chuva (Novales et al. 2021). Heterogeneidade esperada pela literatura, e que vira hipótese do KR4: vias de maior hierarquia/mais rápidas perdem mais em %; faixa exclusiva e BRT atenuam; trechos alagáveis podem perder 20–40% e demorar mais a recuperar (Li et al. 2021, Shenzhen).

## 1.11 Efeito e recuperação com a base final (02/11)

Agora com a chuva dos 3 postos, a linha de base ajustada por dia da semana e semana e o intervalo de 2.000 reamostras de dias (`notebooks/10_gold_efeito_cidade.py`). Dia útil, 6h–23h, 25/08 a 25/10: **42 dias úteis**, 84,7 M janelas no KR1 e 11,1 M no KR2. Rodada oficial de 02/11, em `gold.efeito_cidade`, `gold.recuperacao_cidade` e `gold.tempo_recuperacao`.

**KR1: razão por classe de chuva e período [IC 95%].** Entre parênteses, células com menos de 8 dias: indicativas, sem intervalo.

| Classe | Dia todo | Manhã (6–9h) | Meio (10–15h) | Tarde (16–19h) | Noite (20–23h) |
|---|---|---|---|---|---|
| pós-chuva | 0,993 [0,985–0,999] | 0,981 [0,973–0,990] | 1,007 [1,000–1,013] | 0,986 [0,961–1,005] | 0,991 [0,973–1,003] |
| traço | 0,974 [0,965–0,981] | 0,974 [0,966–0,983] | 0,991 [0,985–0,997] | 0,957 [0,933–0,980] | 0,969 [0,955–0,983] |
| fraca | 0,953 [0,937–0,966] | 0,959 [0,945–0,977] | 0,982 [0,972–0,991] | 0,925 [0,897–0,954] | 0,952 [0,933–0,971] |
| moderada | 0,937 [0,917–0,950] | 0,942 [0,929–0,963] | 0,963 [0,954–0,983] | 0,897 [0,883–0,921] | 0,929 [0,855–0,954] |
| forte | 0,907 [0,889–0,930] | 0,914 (7 dias) | 0,920 [0,908–0,985] | 0,878 (6 dias) | 0,914 (6 dias) |
| muito forte | 0,854 [0,813–0,916] | — | 0,882 (6 dias) | 0,817 (3 dias) | 0,887 (2 dias) |

- **Dose-resposta com intervalo:** forte perde mais que moderada (0,968 [0,959–0,985]) e muito forte mais que forte (0,942 [0,888–0,988]). Moderada × fraca fica no limite (0,983 [0,964–1,001]).
- **O pico da tarde é mesmo o mais sensível:** tarde × meio do dia dá 0,942 [0,910–0,971] na chuva fraca e 0,931 [0,902–0,961] na moderada. Na forte, 0,954 [0,886–1,017]: inconclusivo.
- **Traço também pesa** (−2,6%): menos de uma batida do pluviômetro em 30 min, mas em geral sinal de chuva por perto.
- **Coleta a 2 min × a 1 min:** mesma direção. Dia todo: fraca 0,942 × 0,965; moderada 0,942 × 0,930.

**KR2: tempo de recuperação (min) [IC 95%].** Recuperado = razão ≥ 0,99 por 3 janelas seguidas. "aberto" = mais de 2,5% das reamostras não recuperaram até 170 min.

| A chuva acabou | Fraca | Moderada | Forte |
|---|---|---|---|
| de manhã | 70 [10–aberto] | 130 [70–aberto] | 50 [20–50] |
| no meio do dia | 0 [0–0] | 40 [0–50] | 0 [0–50] |
| à tarde | 120 [40–aberto] | 100 [40–aberto] | não recuperou até 170 (6 dias) |
| à noite | 40 [20–70] | 30 [10–90] | 30 (7 dias) |
| dia todo | 50 [20–80] | 90 [50–140] | 50 [20–aberto] |

- **O tempo de recuperação depende mais da hora em que a chuva acaba do que da intensidade.** Fora dos picos a velocidade volta em até ~40 min; nos picos leva 1–2 h, e chuva forte no fim da tarde pode não se recuperar antes de o pico acabar (6 dias: frágil). Os "~100–120 min" da 1.5 são uma média dessas situações.
- **Forte no dia todo parece voltar mais rápido que moderada:** não comparar assim, porque cada classe mistura horários de fim diferentes. Comparar dentro do período.
- **Quando a chuva acaba no meio do dia, a velocidade passa do normal** (perda de −1,0 min [−1,7 a −0,2] nas 2 h após chuva fraca; razão ~1,01). Hipótese, não testada: menos demanda em dia de chuva.
- **Perda acumulada nas 2 h depois do fim** (minutos de operação normal perdidos por ônibus): moderada 4,2 [1,6–6,8] de manhã e 3,6 [−0,9–10,5] à tarde; fraca 2,8 [0,7–7,0] à tarde.
- **O tempo é um estimador instável:** é a primeira vez que uma curva ruidosa cruza um limite, então o valor pode ficar na ponta do intervalo (fraca à tarde: 120 [40–aberto]). A perda acumulada varia menos e deve acompanhar o tempo no KR2 por trecho.

**Antecipação:** 0,991 a 10 min da chuva, 0,995 a 20 min, ~0,998 entre 30 e 50 min e 1,00 de 60 min para trás. Confirma o fuso e justifica tirar da curva de recuperação as janelas a ≤ 40 min da chuva seguinte (14% das janelas).

## 1.12 Efeito por trecho, ranking e infraestrutura (02/11)

Notebook `12_gold_efeito_trecho`: chuva moderada ou mais forte, dia útil, 6h–23h, postos DAEE, sem trechos atípicos. **Rodada oficial de 02/11**, em `gold.efeito_trecho`, `gold.estabilidade_ranking`, `gold.efeito_infra` e `gold.efeito_grupo`; idêntica ao teste no PC, que usou a mesma semente.

**KR1 por trecho.** 24.576 trechos passam na regra [N] (≥ 8 dias e ≥ 30 janelas), de 26.235 com alguma chuva moderada+ (93,7%). Em **8.700 (35,4%)** a probabilidade de queda real é ≥ 95%. Razão encolhida: 0,924 / 0,968 / 1,012 nos quantis de 5, 50 e 95%. O trecho típico (0,968) perde menos que a cidade (0,931) porque a cidade soma tempo: trechos cheios e ônibus presos pesam mais.

**KR3: o critério reprova.** Definido antes de ver o resultado, reavaliado sem alteração:

| Medida | Critério | Observado |
|---|---|---|
| Jaccard mediano do top-10 | ≥ 0,5 | **0,33** |
| Dos 10 primeiros, quantos ficam no top-20 em ≥ 80% das réplicas | 10 | **3** |
| Top-10 no top-20 de cada réplica (mediana) | — | 7 de 10 |
| Trechos diferentes em algum top-10 | — | 268 |

**Por quê.** O efeito tem sinal real (ver abaixo), mas cada trecho tem só ~13 dias de chuva moderada+, e o erro vem do dia, não do número de ônibus (quase não cai com mais horas). Dividindo os dias em duas metades, a correlação de postos é 0,26: fiabilidade 0,42 com todos os dias, e cerca de 0,59 com o dobro de dias de chuva (Spearman-Brown, indicativo). Uma simulação a partir do modelo foi descartada: ela herda as caudas do próprio modelo e dava o mesmo resultado com qualquer número de dias.

**O que foi tentado para estabilizar:**

| Alternativa | Resultado | Decisão |
|---|---|---|
| Mistura de normais em vez de uma normal | Jaccard 0,18 → 0,33; para de achatar extremos (−0,53 virava −0,13) | **adotada** |
| Eixos de 1, 2 e 4 km | fiabilidade 0,46 (trecho: 0,43) | descartada |
| Comparar só dentro do mesmo dia | 0,43 | descartada |
| Estimadores robustos entre dias | 0,31–0,42, todos abaixo da soma | descartada |
| Ranking por local, grade de 200 m a 1 km | Jaccard até 0,43; 2 a 4 de 10 | descartada |
| Incluir chuva fraca | Jaccard 0,33; 2 de 10; fiabilidade 0,45 | descartada, mas confirma os lugares |

**O que é estável: o grupo crítico (proposta para o Rafael).** Trechos entre os 5% piores em ≥ 80% das réplicas: **130 trechos em 88 locais** (trechos a até 300 m contam como um lugar), 67 km, razão mediana 0,844. Evidências:

- **Fora da amostra:** os 1% piores escolhidos numa metade dos dias continuam ~11% abaixo da média na outra metade.
- **Placebo:** nas horas secas dos mesmos dias, o grupo fica normal (−0,01). Efeito e placebo quase não se relacionam (Spearman 0,055).
- **Definição alternativa:** com a chuva fraca incluída, o ranking tem correlação 0,84 com este, e 7 dos 10 primeiros são os mesmos.
- **Perfil:** 58% em arteriais (geral 35%); 23% com ≥ 5 dias de alagamento (geral 7,6%); 15% perto de terminal (geral 5%).

Os primeiros locais: Estr. de Itapecerica (0,50), Av. Sabin (0,51), R. Maria Eugênia Celso → R. Dr. Campos Moura (0,52; 5 trechos sobrepostos), R. Geraldo Fraga de Oliveira (0,57) e R. Getulina (0,58). **Cuidados:** a ordem não é estável; a Estr. de Itapecerica ficou bem mais rápida em outubro mesmo no seco (0,8 → 1,6), sinal de mudança local a investigar; vários líderes são gargalos muito lentos (5–9 km/h), onde a fila amplifica a chuva; perto de terminal, parte da queda pode ser espera.

**KR4: tipo de via** (soma por grupo, comparada à via coletora, IC 95%):

| Chuva | Coletora | Arterial | Expressa (VTR + rodovia) |
|---|---|---|---|
| fraca | 0,965 | −2,3% [−3,0 a −1,6] | −3,8% [−5,1 a −2,2] |
| moderada | 0,956 | −3,2% [−4,5 a −2,1] | −5,5% [−8,4 a −3,5] |
| forte+ | 0,933 | **−5,7%** [−7,3 a −3,1] | **−10,7%** [−18,3 a −2,5] |

Via local não difere da coletora. Comparando trechos parecidos, a diferença da arterial fica em −0,4% [−1,2 a −0,2] no trecho típico e −1,6% [−2,6 a −0,4] ponderando por ônibus. A direção é a mesma, e a distância entre as leituras vem de os trechos mais cheios perderem mais (−1,4% por unidade de log das horas de ônibus).

**KR4: histórico de alagamento** (dias distintos a até 100 m, 2013–2026):

| Chuva | 0 dias | 1–4 dias | 5–19 dias | 20+ dias |
|---|---|---|---|---|
| fraca | 0,959 | 0,947 | 0,935 | 0,933 |
| moderada | 0,946 | 0,930 | 0,918 | 0,907 |
| forte+ | 0,921 | 0,888 | 0,853 | 0,847 |

Parte disso é tipo de via: arteriais alagam mais. Dentro de cada classe (5+ dias contra 0, IC 95%):

| Chuva | Em coletora | Em arterial |
|---|---|---|
| fraca | −3,9% [−6,8 a −1,5] | −1,7% [−3,2 a −0,5] |
| moderada | −3,3% [−4,5 a −2,1] | −2,2% [−4,0 a 0,0] |
| forte+ | −4,2% [−7,4 a −1,4] | −6,6% [−12,5 a +0,8] |

**A associação existe e aparece dentro da classe de via, mas é mais clara com histórico frequente:** coletoras com 1–4 dias não diferem das sem histórico; em arteriais, 1–4 dias já mostram −1,1 a −1,7% nas chuvas fraca e moderada. No modelo com todas as covariáveis ela é pequena: −0,43% por unidade de log dos dias [−0,87 a −0,10], ou ~−0,8% indo de 0 a 5 dias. Ponderando por ônibus, −0,42% [−1,14 a +0,17], com intervalo que inclui zero. A amostra tem 13–16 dias de chuva forte+, e nenhuma enchente grande.

**KR4: faixa e corredor.** Sem proteção detectável: −0,5% [−1,2 a +0,4] e 0,0% [−1,0 a +1,2] no modelo. Somando por grupo, parecem perder mais, mas estão em arteriais. Só faixas longas em via de mão única: −2,0%. Diferente da literatura, que espera atenuação. Limite: a geometria não diz o sentido da faixa, e no meio de um corredor linhas podem usar as pistas laterais.

**Outros.** `dist_posto_km` = +0,13% por km [0,04 a 0,29]: quanto mais longe o posto, menor o efeito medido, como esperado com erro de medida da chuva; os efeitos são limites inferiores. `log_comprimento` = −1,8%: trechos curtos perdem menos. `perto_terminal` = −1,6% [−3,4 a +1,9]: inconclusivo, e muda de sinal ponderando por ônibus.

**Tudo isso é associação, não causa:** trechos não foram sorteados para ter faixa ou alagar.

# 2. Decisões de desenho

## 2.1 Grão: trecho físico × janela de 10 min

**Trecho físico** = `(parada_de, parada_ate)`, juntando as linhas. Multiplica as observações onde mais importa (trechos com muitas linhas são os corredores) e é a unidade natural para o KR4 (atributos da via). Análises por linha ficam como detalhamento.

**Dia útil é a análise principal**; sábado e domingo à parte (outro padrão de demanda, menos dado).

## 2.2 Chuva de cada trecho

- **Posto(s):** média ponderada pelo inverso do quadrado da distância (IDW) dos até **3 postos confiáveis DAEE a até 5 km**; se não houver DAEE a 5 km, o mais próximo de qualquer rede confiável a até 5 km; acima disso, sem chuva atribuída. Guardar `dist_km` e `n_postos`.
- Por quê: o mais próximo já representa bem (r ≈ 0,85), a média de 3 reduz o ruído de um posto só, e o corte de 5 km vem da curva de correlação.
- **CEMADEN fora das variáveis de tempo** (início/fim de chuva) enquanto o rateio da leitura horária não for resolvido; ela entra só como reserva onde não há DAEE.
- Se um posto está sem dado naquele slot, a média usa os outros (não há viés de falta durante temporal).

**Variáveis por trecho × janela:** chuva no próprio slot, intensidade nos últimos 30 e 60 min (mm/h), acumulado de 3 h, minutos desde o fim da última chuva, intensidade de pico do evento.

## 2.3 Eventos de chuva

Por posto (e herdado pelo trecho): **início** = slot com ≥ 0,2 mm depois de ≥ 60 min secos; **fim** = último slot com chuva antes de ≥ 60 min secos. Guardar início, fim, duração, total e pico (mm/h em 30 min). 0,2 mm é a resolução do pluviômetro de báscula.

## 2.4 Linha de base ("velocidade normal")

`v_base(trecho, hora) × ajuste(dia da semana, hora) × ajuste(semana)`:

- **parte do trecho:** Σd/Σt nas janelas **secas estritas** do trecho naquela hora;
- **seco estrito:** nenhuma chuva (≥ 0,2 mm) nos postos do trecho nas **3 h anteriores** (a recuperação leva ~2 h; 3 h e 6 h dão o mesmo resultado) **e** menos de 25% dos postos da cidade chovendo no slot (transbordamento, seção 1.8);
- **ajustes multiplicativos estimados para a cidade** (ou por região) nas janelas secas: dia da semana × hora e semana (segunda +3–4%, sexta mais lenta; semanas de 0,985 a 1,015);
- mínimo de janelas secas por trecho × hora (calibrar; partida: 30).

Separar assim evita estimar trecho × hora × dia da semana × semana direto (célula com pouquíssimo dado). Sensibilidade: só o período a 1 min (21/09–24/10).

**Classes de chuva finais (notebook 09), a primeira que se aplica:** `sem_dado` (menos de metade do peso dos postos com leitura); `seco` (seco estrito); `transbordamento` (postos secos há 3 h, mas ≥ 25% da cidade chovendo); `pos_chuva` (sem chuva em 30 min, mas choveu em 3 h); `traco` (< 0,4 mm/h, menos que uma batida do pluviômetro em 30 min); `fraca` (< 2,5); `moderada` (< 10); `forte` (< 25); `muito_forte`.

**Tipo de dia:** o `tipo_dia` da gold vem do dia da janela, pela `posicao_limpa`. O da `velocidade_trecho` é o do primeiro par de cada shape × dt e pode ser o do dia vizinho perto da meia-noite (0,009% das linhas). Um `first()` por trecho × janela chegou a criar células `util × domingo` no ajuste, com efeito desprezível, antes da correção de 02/11.

## 2.5 KR1 — efeito da chuva

1. **Descritivo** (como na 1.4): razão por classe de intensidade × período do dia, com intervalo de confiança por **bootstrap por blocos de dia** (janelas do mesmo dia são dependentes; o tamanho efetivo da amostra é o número de dias/eventos, não o de janelas).
2. **Modelo:** log da velocidade da janela ~ efeitos fixos (trecho × hora, dia da semana × hora, semana) + chuva + pós-chuva + interação com período do dia; pesos = tempo dos ônibus na janela. Em duas versões (recomendação da literatura):
   - **(A) efeito total** — sem efeito fixo de data × hora: inclui o transbordamento para a rede;
   - **(B) efeito local** — com efeito fixo de data × hora por macrozona: identifica só pela diferença de chuva entre trechos na mesma hora. A diferença A − B mostra quanto do efeito é sistêmico.
3. **Chuva no modelo:** classes (leve < 2,5; moderada 2,5–10; forte 10–25; muito forte ≥ 25 mm/h) e, em paralelo, curva contínua (spline) da intensidade e defasagens de 0 a 120 min (modelo de defasagens distribuídas, DLNM), para não depender dos cortes.
4. **Inferência:** erro-padrão agrupado por **dia** (ou em duas vias, trecho e dia); com ~60 dias, **wild cluster bootstrap**.
5. **Caudas:** regressão quantílica (τ = 0,1 / 0,5 / 0,9) da anomalia — a literatura mostra efeito maior nos piores casos do que na média.

## 2.6 KR2 — recuperação

- **Estudo de evento:** razão em relação à linha de base para τ = −60 … +180 min em torno do **início** e do **fim** de cada evento (2.3), por intensidade do evento, período do dia e grupo de trecho. Antes do início deve dar ~1 (teste de antecipação, 1.8).
- **Tempo de recuperação** = primeiro instante depois do fim em que a razão fica **≥ 0,99 por ≥ 3 janelas (30 min)**; busca até 170 min. A banda só olha para baixo porque passar de 1 também é ter recuperado. Sempre **por período em que a chuva acabou** (seção 1.11).
- **Perda acumulada** (área do "triângulo de resiliência") = Σ(1 − razão) × tempo, em minutos-ônibus perdidos.
- **Por trecho ou corredor:** análise de sobrevivência (Kaplan–Meier, Cox com atributos de infraestrutura), com **censura** quando volta a chover antes da recuperação ou acaba a operação do dia — alguns trechos alagáveis podem não se recuperar dentro do evento.
- Resultado da cidade: seção 1.11. Só trechos com postos DAEE, e sem as janelas a ≤ 40 min da chuva seguinte.

## 2.7 KR3 — ranking dos trechos mais afetados

1. **Estágio 1 — efeito bruto por trecho:** anomalia nas janelas com chuva ≥ moderada, com erro-padrão por bootstrap/agrupamento por dia. **Regra de dado mínimo ([N] dos KRs):** chuva ≥ moderada em **≥ 8 dias** e ≥ 30 janelas, e linha de base com ≥ 30 janelas secas por hora usada; posto a até 5 km.
2. **Estágio 2 — encolhimento por Bayes empírico com covariáveis:** efeito do trecho = Xγ + mistura de normais (*adaptive shrinkage*, como no `ashr`; a normal única achatava os extremos, seção 1.12). Trechos com pouco dado são puxados para o esperado pelas covariáveis; os bem medidos mantêm o próprio efeito. **O mesmo modelo responde ao KR4**: γ são os efeitos de infraestrutura.
3. **Ranking pela posterior**, não pela estimativa bruta: para cada trecho, P(estar no top-10) e o intervalo do rank.
4. **Estabilidade:** bootstrap por blocos de dia (estratificado), refazendo os dois estágios; frequência no top-10/top-20 e índice de Jaccard entre os top-10 das réplicas. Se os efeitos do topo forem muito próximos, usar bootstrap m-de-n.
5. **Multiplicidade:** ~29 mil trechos → controlar a taxa de falsas descobertas (Benjamini–Hochberg) ou *local false sign rate* do `ashr` ao dizer quais trechos têm efeito.
6. **Critério de "estável" definido antes de olhar** (a confirmar com o Rafael): o top-10 reportado aparece no top-20 em ≥ 80% das réplicas; Jaccard mediano ≥ 0,5.
7. Alternativa de unidade, se o ranking por trecho for instável: **corredores** (sequências de trechos consecutivos de 0,5–1 km). *Testada em 02/11 com eixos de 1–4 km e grade de 200 m a 1 km: não resolve (seção 1.12). Proposta: grupo crítico.*

## 2.8 KR4 — infraestrutura

Fontes levantadas e testadas a partir deste PC (detalhes, URLs e comandos em `docs/gold_fontes_infra.md`). Quase tudo está no **GeoSampa**, aberto (CC BY-SA 4.0), por WFS público ou arquivo pronto, em SIRGAS 2000 / UTM 23S (EPSG:31983). O Databricks não alcança esses servidores: baixar no PC e subir para o volume (`bronze/raw/infra/`).

| Atributo (hipótese da literatura) | Fonte | Variável por trecho |
|---|---|---|
| **Tipo de via** (vias rápidas/arteriais perdem mais em %) | Classificação Viária CET (GeoSampa; 210.754 trechos de logradouro; revisão 02/2026) | fração do trecho por classe (VTR, arterial, coletora, local) e classe dominante |
| **Faixa exclusiva** (atenua) | `faixa_onibus` (7.378 feições, ~779 km; data de implantação; horário) | fração do trecho com faixa; só pico ou integral |
| **Corredor** (atenua) | `corredor_onibus` (45 linhas, ~265 km; 40 em operação) | fração do trecho em corredor |
| **Histórico de alagamento** (perdas de 20–40%, recuperação lenta) | Ocorrências da Defesa Civil 2013–2026 (pontos com data; ALAGAMENTO/INUNDAÇÃO) | dias distintos com ocorrência a 100 m (sensibilidade: 50 m), só antes de 25/08/2026 |
| Alagamento por evento (opcional) | CGE, histórico diário desde ~2008 com hora e transitável/intransitável (HTML, exige scraping e geocodificação) | casar com os eventos de chuva hora a hora |
| Suscetibilidade (complemento) | manchas de inundação TR 5/25/100 (modeladas), córregos canalizados, declividade | fração do trecho em mancha; proximidade de córrego canalizado |
| Contexto (opcional) | Censo 2022, entorno por setor (bueiro, pavimentação) | média ponderada no entorno |

**Como juntar (notebook 11, `gold.trecho_infra`):** cada trecho vira pontos a cada ~20 m ao longo do traçado com mais tempo de ônibus. Cada ponto procura a linha mais próxima da camada dentro de um raio, com rumo parecido (até 30°, sem olhar o sentido), para não pegar a rua transversal. Fração do trecho = fração dos pontos. Raios medidos em 02/11:

| Camada | Distância mediana | Raio | Pontos casados |
|---|---|---|---|
| Classificação viária CET | 0,6 m | 15 m | 98,6% (com 60 m, só 99,3%) |
| Faixas exclusivas | 0,8 m | 15 m | 18,3% |
| Corredores em operação | 7 m | 25 m | 8,6% |

**Resultado da junção (02/11; sem trechos atípicos):**

| Classe dominante | Trechos | km | Velocidade média (km/h) |
|---|---|---|---|
| VTR | 23 | 23 | 29,5 |
| Rodovia | 123 | 100 | 27,2 |
| Arterial | 9.974 | 4.504 | 16,2 |
| Coletora | 16.718 | 5.079 | 14,5 |
| Local | 1.896 | 661 | 13,0 |

- **Validação independente:** as classes vêm da CET e a velocidade vem dos ônibus, e ela segue a hierarquia viária. Corredor: 17,5 km/h; faixa sem corredor: 15,9; nenhum dos dois: 15,1. O notebook falha se a ordem das classes quebrar.
- **VTR e rodovia têm poucos trechos** (146 juntas): o KR4 compara, na prática, expressa × arterial × coletora × local.
- **Sentido da faixa:** faixas ficam no eixo da via e o desenho não indica o sentido (53% × 47%). Em via de mão única não há dúvida; em mão dupla, o trecho pode estar do outro lado da rua. Isso vale para 20% do comprimento com faixa e fica em `frac_faixa_via_dupla`, para testar a sensibilidade.
- **Horário da faixa:** muitas só valem no pico (mediana de 6 h por dia útil). `frac_faixa_longa` conta as de ≥ 10 h.
- **Alagamento:** 12.494 ocorrências em 1.454 dias antes do período estudado. Conta dias distintos, não registros: uma coordenada aparece 482 vezes, e 3 dias de 2016 somam 3.115 das 12.625 ocorrências da série inteira. 38,8% dos trechos têm ao menos um dia a 100 m (mediana 0, p90 = 4, p99 = 20, máximo 73). Os líderes são Prestes Maia/Anhangabaú e o eixo Ribeirão Jacu/Musgo de Flor, pontos conhecidos.
- **Variável muito assimétrica:** usar `log(1 + dias)` ou faixas de dias no modelo, com o comprimento como controle.

**Análise:** os atributos entram como covariáveis no estágio 2 do KR3 (efeito do trecho ~ Xγ); γ responde ao KR4. Sensibilidade: classe dominante vs. frações; e a interação com a recuperação (KR2) por análise de sobrevivência.

**Ressalvas:** faixas exclusivas desatualizadas (metadados de 2021, última implantação 01/2024) — usar a data de implantação; pontos da Defesa Civil geocodificados pelo endereço do chamado e subnotificados; manchas de inundação são modeladas, não observadas.

## 2.8 KR5 — previsão (aspiracional)

- **Alvo:** anomalia em t+10 … t+60 min (ou "queda > x%"), por trecho ou corredor.
- **Atributos:** chuva observada com defasagens 0–60 min e acumulados 1–3 h; chuva nos postos vizinhos e fração da cidade chovendo; anomalia atual do trecho e dos vizinhos a montante/jusante; hora e tipo de dia; infraestrutura; sensibilidade do trecho **estimada só com os dias de treino**.
- **Modelos:** primeiro as referências (persistência e perfil histórico); depois ridge e *gradient boosting* (LightGBM).
- **Avaliação:** validação **por blocos de dias inteiros, em ordem temporal** (forward chaining) — validação aleatória superestima; métricas separadas em seco, chuva leve, chuva forte e pós-chuva; ganho sobre a persistência.
- Limite: só com chuva observada, o modelo não antecipa células que ainda não chegaram; nowcasting por radar seria a extensão.

## 2.9 Cuidados que viram análises

- **Erro de medida da chuva** (posto a 1,6 km; báscula subestima intensidades altas) puxa o efeito para zero: testar a interação efeito × distância ao posto e o posto mais próximo com teto de 2, 3 e 5 km. O efeito deve crescer quando o posto está mais perto.
- **Dado faltante informativo:** em alagamento os ônibus somem do trecho (desviados ou parados) exatamente no pior momento. Analisar também o **número de passagens** como desfecho, e rodar com e sem `parado_longo`.
- **Calendário:** feriados (07/09 e 12/10, segundas), eleições (04/10 e 25/10, domingos; em 04/10 houve 29% mais horas-ônibus que num domingo normal), suspensão do rodízio em dias de chuva forte (ex.: 14/10, 17h–20h), greves e jogos — marcar e testar a exclusão.
- **Métrica:** % (log) é a principal; para somar ao longo de uma rota, usar *pace* (s/km), que é aditivo.
- **Mecanismos misturados:** o efeito é na velocidade comercial (tráfego + embarque), não "do trânsito".

# 3. Tabelas propostas

| Tabela | Grão | Conteúdo |
|---|---|---|
| `gold.trecho`, `gold.trecho_posto` | trecho físico; trecho × posto | coordenadas, comprimento, linhas, `f_atipico`, `fonte_chuva`; postos atribuídos com pesos. Depois, atributos de infraestrutura (KR4) |
| `gold.chuva_posto_10min` | posto × slot | intensidades em 30/60 min, acumulado 3 h, minutos desde o fim, `evento_id` |
| `gold.evento_chuva` | evento | posto, início, fim, duração, total, pico |
| `gold.obs_trecho_10min` | trecho × janela | Σd, Σt, n_pares, chuva atribuída, pico do evento, classe de chuva |
| `gold.linha_base`, `gold.ajuste_dia_hora`, `gold.ajuste_semana` | trecho × grupo × hora; cidade | velocidade normal e fatores |
| `gold.obs_razao` (view) | trecho × janela | observações + velocidade esperada + razão |
| `gold.efeito_cidade` | recorte × período × classe | KR1 da cidade, com IC |
| `gold.recuperacao_cidade`, `gold.tempo_recuperacao` | período do fim × classe | KR2 da cidade: curva, tempo e perda |
| `gold.trecho_infra` | trecho | classe de via, faixa, corredor, dias de alagamento |
| `gold.efeito_trecho` | trecho | efeito bruto e encolhido, IC, frequência no top-10/20 e entre os piores, grupo crítico, placebo |
| `gold.estabilidade_ranking` | métrica | critério do KR3 e validações |
| `gold.efeito_infra`, `gold.efeito_grupo` | modelo × termo; grupo × chuva | KR4 |

# 4. Riscos e cuidados

- **Ruído por janela** (2 passagens na mediana): sempre agregar; nunca concluir de janelas isoladas.
- **Dependência dentro do dia:** erros-padrão e ranking por bootstrap de dias, não de janelas.
- **Linha de base variando** com dia da semana e semana: ajustar (seção 2.4).
- **Rede CEMADEN:** fora das variáveis de tempo.
- **Falha da fonte:** em 11/10 (domingo), das ~6h às ~13h, a API da SPTrans respondeu 503 no login e quase não há posições. Não afeta dia útil; nenhum dia útil tem falha parecida.
- **Ônibus presos em alagamento:** a regra `parado_longo` (≥ 20 min) pode remover justamente os piores casos; rodar o KR1/KR3 com e sem eles.
- **Validade externa:** setembro de 2026 foi o mais chuvoso da série, com chuva frontal persistente; o efeito de temporais convectivos de verão pode ser diferente.
- **Trechos com razão absurda** (0 ou > 10): dado insuficiente ou trecho mal formado; a regra de dado mínimo resolve a maioria.
