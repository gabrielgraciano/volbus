---
title: "Gold — desenho"
subtitle: "Como medir o efeito da chuva na velocidade dos ônibus, trecho a trecho"
author: "Projeto Ônibus SP × Chuva · Gabriel Graciano Dias"
date: "25/10/2026"
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

**A velocidade volta ao normal ~1h30–2h depois do fim da chuva**, inclusive depois de chuva forte. Linha de base com 3 h ou com 6 h sem chuva dá o mesmo resultado (0,971 vs 0,970 aos 20 min): **3 h sem chuva é uma linha de base segura.**

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
- **Tempo de recuperação** = primeiro instante depois do fim em que a razão volta para dentro da banda da linha de base (±1%, ou ±1 desvio-padrão das janelas secas do trecho) **e fica lá por ≥ 3 janelas (30 min)**; busca até 3 h depois do fim.
- **Perda acumulada** (área do "triângulo de resiliência") = Σ(1 − razão) × tempo, em minutos-ônibus perdidos.
- **Por trecho ou corredor:** análise de sobrevivência (Kaplan–Meier, Cox com atributos de infraestrutura), com **censura** quando volta a chover antes da recuperação ou acaba a operação do dia — alguns trechos alagáveis podem não se recuperar dentro do evento.
- Primeiro resultado da cidade: **~100–120 min** (seção 1.5).

## 2.7 KR3 — ranking dos trechos mais afetados

1. **Estágio 1 — efeito bruto por trecho:** anomalia nas janelas com chuva ≥ moderada, com erro-padrão por bootstrap/agrupamento por dia. **Regra de dado mínimo ([N] dos KRs):** chuva ≥ moderada em **≥ 8 dias** e ≥ 30 janelas, e linha de base com ≥ 30 janelas secas por hora usada; posto a até 5 km.
2. **Estágio 2 — encolhimento por Bayes empírico com covariáveis:** efeito do trecho ~ Normal(Xγ, τ²) (estilo Fay–Herriot, ou *adaptive shrinkage*, pacote `ashr`). Trechos com pouco dado são puxados para o esperado pelas covariáveis; os bem medidos mantêm o próprio efeito. **O mesmo modelo responde ao KR4**: γ são os efeitos de infraestrutura.
3. **Ranking pela posterior**, não pela estimativa bruta: para cada trecho, P(estar no top-10) e o intervalo do rank.
4. **Estabilidade:** bootstrap por blocos de dia (estratificado), refazendo os dois estágios; frequência no top-10/top-20 e índice de Jaccard entre os top-10 das réplicas. Se os efeitos do topo forem muito próximos, usar bootstrap m-de-n.
5. **Multiplicidade:** ~29 mil trechos → controlar a taxa de falsas descobertas (Benjamini–Hochberg) ou *local false sign rate* do `ashr` ao dizer quais trechos têm efeito.
6. **Critério de "estável" definido antes de olhar** (a confirmar com o Rafael): o top-10 reportado aparece no top-20 em ≥ 80% das réplicas; Jaccard mediano ≥ 0,5.
7. Alternativa de unidade, se o ranking por trecho for instável: **corredores** (sequências de trechos consecutivos de 0,5–1 km).

## 2.8 KR4 — infraestrutura

Fontes levantadas e testadas a partir deste PC (detalhes, URLs e comandos em `docs/gold_fontes_infra.md`). Quase tudo está no **GeoSampa**, aberto (CC BY-SA 4.0), por WFS público ou arquivo pronto, em SIRGAS 2000 / UTM 23S (EPSG:31983). O Databricks não alcança esses servidores: baixar no PC e subir para o volume (`bronze/raw/infra/`).

| Atributo (hipótese da literatura) | Fonte | Variável por trecho |
|---|---|---|
| **Tipo de via** (vias rápidas/arteriais perdem mais em %) | Classificação Viária CET (GeoSampa; 210.754 trechos de logradouro; revisão 02/2026) | fração do trecho por classe (VTR, arterial, coletora, local) e classe dominante |
| **Faixa exclusiva** (atenua) | `faixa_onibus` (7.378 feições, ~779 km; data de implantação; horário) | fração do trecho com faixa; só pico ou integral |
| **Corredor** (atenua) | `corredor_onibus` (45 linhas, ~265 km; 40 em operação) | fração do trecho em corredor |
| **Histórico de alagamento** (perdas de 20–40%, recuperação lenta) | Ocorrências da Defesa Civil 2013–2026 (pontos com data; ALAGAMENTO/INUNDAÇÃO) | ocorrências por km por ano num raio de 50–100 m |
| Alagamento por evento (opcional) | CGE, histórico diário desde ~2008 com hora e transitável/intransitável (HTML, exige scraping e geocodificação) | casar com os eventos de chuva hora a hora |
| Suscetibilidade (complemento) | manchas de inundação TR 5/25/100 (modeladas), córregos canalizados, declividade | fração do trecho em mancha; proximidade de córrego canalizado |
| Contexto (opcional) | Censo 2022, entorno por setor (bueiro, pavimentação) | média ponderada no entorno |

**Como juntar:** geometria de cada trecho físico = pedaço do traçado GTFS entre as duas paradas, reprojetado para EPSG:31983; para camadas lineares, recorte por buffer (12–15 m vias, 15–20 m faixas, 20–25 m corredores) com filtro de rumo (< 30°) para não pegar ruas transversais; pontos contados num raio; polígonos por fração do comprimento.

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
- **Calendário:** feriados (07/09 e 12/10, segundas), eleição (04/10, domingo), suspensão do rodízio em dias de chuva forte (ex.: 14/10, 17h–20h), greves e jogos — marcar e testar a exclusão.
- **Métrica:** % (log) é a principal; para somar ao longo de uma rota, usar *pace* (s/km), que é aditivo.
- **Mecanismos misturados:** o efeito é na velocidade comercial (tráfego + embarque), não "do trânsito".

# 3. Tabelas propostas

| Tabela | Grão | Conteúdo |
|---|---|---|
| `gold.trecho` | trecho físico | coordenadas, comprimento, linhas, postos atribuídos (pesos e distâncias); depois, atributos de infraestrutura (KR4) |
| `gold.chuva_posto_10min` | posto × slot | intensidades em 30/60 min, acumulado 3 h, minutos desde o fim, `evento_id` |
| `gold.evento_chuva` | evento | posto, início, fim, duração, total, pico |
| `gold.obs_trecho_10min` | trecho × janela | Σd, Σt, velocidade, n_pares, chuva atribuída, linha de base, razão |
| `gold.efeito_cidade` | classe × período | KR1 e KR2 da cidade, com IC |
| `gold.efeito_trecho` | trecho | efeito bruto, efeito com encolhimento, IC, frequência no top-10/20, dados usados |

# 4. Riscos e cuidados

- **Ruído por janela** (2 passagens na mediana): sempre agregar; nunca concluir de janelas isoladas.
- **Dependência dentro do dia:** erros-padrão e ranking por bootstrap de dias, não de janelas.
- **Linha de base variando** com dia da semana e semana: ajustar (seção 2.4).
- **Rede CEMADEN:** fora das variáveis de tempo.
- **Ônibus presos em alagamento:** a regra `parado_longo` (≥ 20 min) pode remover justamente os piores casos; rodar o KR1/KR3 com e sem eles.
- **Validade externa:** setembro de 2026 foi o mais chuvoso da série, com chuva frontal persistente; o efeito de temporais convectivos de verão pode ser diferente.
- **Trechos com razão absurda** (0 ou > 10): dado insuficiente ou trecho mal formado; a regra de dado mínimo resolve a maioria.
