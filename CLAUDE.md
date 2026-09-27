# Projeto Ônibus SP × Chuva — contexto para continuidade

> Gerado em 27/09/2026 a partir das conversas de planejamento. Fonte de verdade
> para retomar o trabalho no Claude Code. Onde este documento e o código
> divergirem, **o código no droplet vale** (ele produziu a coleta).
>
> As notas do Obsidian "Ônibus SP - Resumo do que existe" e "Ônibus SP - Plano de
> ação" (13/09) são **históricas**: descrevem o plano anterior (Free Edition,
> EWT/headway como medida principal, prazo 26/10, coleta a 2 min). A auditoria
> da coleta feita nelas continua válida e foi incorporada em §2.

## Quem e para quê

- **Gabriel Graciano Dias** — Estatística IME-USP. Projeto vinculado a **MAE0350**.
- **Rafael** — mentor, reunião semanal às segundas; comunicação intermediária por WhatsApp.
- **Prazo:** ~30/out/2026, flexível até novembro.
- **Estilo de trabalho preferido:** direto, tecnicamente preciso, sem floreio; honestidade acima de concordância; saídas executáveis.

---

## 1. Pergunta de pesquisa (estado atual)

Evolução:
1. ~~Lakehouse medindo regularidade de headway por linha~~
2. ~~Quanto da variância do tempo de espera é explicada pela chuva~~
3. **Atual (proposta do Rafael, a confirmar na próxima segunda):**

> **Objetivo:** Identificar onde a chuva mais degrada a malha de ônibus de São Paulo e quais elementos da infraestrutura estão associados a essa perda.

- **Medida principal: velocidade dos ônibus por trecho.** Tempo de espera saiu (EWT assume chegada aleatória de passageiros — não medimos isso).
- Headway continua mensurável e deve ficar como **medida secundária** (separa "a via travou" de "a operação ficou irregular").
- Ganho metodológico: com velocidade como **desfecho** e chuva como **tratamento**, some a endogeneidade velocidade↔headway (chuva não é causada por ônibus). Sobra confundimento com **hora do dia** (temporal concentra no fim da tarde = pico) e **autocorrelação** (dias chuvosos em sequência).

### OKRs (versão do Rafael, formato Doerr/Google: KR = resultado pontuável 0–1)

| KR | Enunciado |
|---|---|
| 1 | Quantificar a redução da velocidade durante a chuva em pelo menos [N] trechos |
| 2 | Quantificar o tempo de recuperação da velocidade após a chuva em pelo menos [N] trechos |
| 3 | Identificar os 10 trechos mais afetados, com ranking estatisticamente estável |
| 4 | Avaliar a associação entre degradação e dois atributos de infraestrutura: tipo de via e histórico de alagamento |
| 5 (aspiracional) | Prever a degradação dos trechos na hora seguinte a partir da chuva observada |

### Ajustes sugeridos (levar ao Rafael)

- **"Trecho" não está definido — decisão bloqueante.** Recomendação: **trecho = par de paradas consecutivas do GTFS** (precedente: Monitor de Ônibus do IEMA, que calcula velocidade exatamente assim com dados do Olho Vivo). Alternativa: segmentos da malha viária (casa melhor com atributos do KR4, mas exige casamento com rede viária).
- **[N] como regra, não número:** "todos os trechos com ≥K passagens com chuva e ≥K sem chuva". **N₂ ≪ N₁** (recuperação exige eventos com início e fim identificáveis no trecho).
- **KR2 é o mais forte:** novo, e corrige viés — horas pós-chuva não são horas secas.
- **KR3 precisa de definição operacional de "estável":** bootstrap por dia → recomputar top-10 → sobreposição mediana acima de limiar, ou Kendall τ entre rankings. Alternativa/complemento: modelo hierárquico com *shrinkage*.
- **KR4 — dados existem e são retrospectivos** (ver §6).

---

## 2. Infraestrutura

### Droplet DigitalOcean
- NYC1, Ubuntu 24.04, 1 vCPU / 512 MB / 10 GB, **US$ 4/mês**, IP `167.172.149.91`, usuário `gabriel`.
- Swap 1 GB (`/swapfile`), fuso do servidor **UTC**.
- **Crédito:** ~US$ 4,13 após recarga em 21/09 → dura até ~21/10. **Recarregar ~US$ 3 por volta de 15/10.**
- Disco ~44%, estável (o `move` de 48h segura).

### Layout
```
/home/gabriel/olhovivo/
  coletor.py              # Olho Vivo v2 (payload cru)
  coletor_v1_flat.py      # backup da v1 (achatada) — não usar
  coletor_cet.py          # lentidão CET
  coletor_kmz.py          # velocidade nas vias SPTrans (/KMZ)
  backup.sh               # backup noturno
  .env                    # SPTRANS_TOKEN=... (chmod 600, fora do Git)
  .venv/                  # requests, pandas
  rclone.log  cet.log
  data/
    auditoria.csv         # 1 linha por ciclo do Olho Vivo (heartbeat)
    estado_dedupe.json    # legado da v1, não usado
    alertas.log           # disco > 80%
    bronze_posicao/dt=YYYY-MM-DD/*.ndjson.gz   # v1 achatado (até 21/09)
    bronze_raw/dt=YYYY-MM-DD/*.json.gz          # v2 cru (desde 21/09)
    cet/
      lentidao.csv  auditoria.csv
      bronze_html/dt=YYYY-MM-DD/*.html.gz
```
Partições por **data local (America/Sao_Paulo)**; timestamps em **UTC**.

### Agendamento
- **systemd** `/etc/systemd/system/olhovivo.timer` → `OnCalendar=*-*-* *:*:00`, `AccuracySec=5s`, `Persistent=true`; `olhovivo.service` é `Type=oneshot`, `User=gabriel`, `EnvironmentFile=.env`, `ExecStart=.venv/bin/python coletor.py --out /home/gabriel/olhovivo/data`.
- **crontab (gabriel):**
  ```cron
  20 * * * * df -h / | awk 'NR==2 && int($5) > 80 {print strftime("\%F \%T"), "DISCO EM", $5}' >> /home/gabriel/olhovivo/data/alertas.log
  */10 * * * * /home/gabriel/olhovivo/.venv/bin/python /home/gabriel/olhovivo/coletor_cet.py --out /home/gabriel/olhovivo/data/cet >> /home/gabriel/olhovivo/cet.log 2>&1
  0 5 * * * /home/gabriel/olhovivo/backup.sh
  * * * * * cd /home/gabriel/olhovivo && set -a && . ./.env && set +a && .venv/bin/python coletor_kmz.py --out /home/gabriel/olhovivo/data/kmz >> /home/gabriel/olhovivo/kmz.log 2>&1
  ```
  **Bug (27/09):** a linha do alerta de disco nunca funcionou — `alertas.log` não existe. No crontab, `%` sem escape vira quebra de linha e trunca o comando no `strftime("%F %T")`. Corrigir para `\%F \%T` (ou mover para script).
- **backup.sh:** `rclone move` de `bronze_posicao` e `bronze_raw` com `--min-age 48h --delete-empty-src-dirs` para `gdrive:olhovivo-bronze/<sub>`; depois `rclone copy` de `data/` inteiro (exclui `estado_dedupe.json`). Cada passo independente; falhas marcadas com `!!!` no log.

### Armazenamento
- Google Drive pessoal **2 TB** (notas da reunião citam 5 TB da USP). Pasta `olhovivo-bronze/` na raiz: `bronze_posicao/`, `bronze_raw/`, `cet/`, `auditoria.csv`.
- Em 12/09: 10.795 arquivos, 1,59 GiB.

### Marcos para a metodologia
| Quando (UTC) | Evento |
|---|---|
| 25/08/2026 22:18 | Início da coleta Olho Vivo (2 min, bronze achatado) |
| 21/09/2026 02:51 | Início do coletor CET (10 min) |
| 21/09/2026 02:55 | Cadência 2 min → **1 min** (antes: drift de ~2min10s por `OnUnitActiveSec`) |
| 21/09/2026 ~03:06 | Bronze achatado → **cru** (`bronze_raw`); dedupe sai da ingestão |
| 27/09/2026 21:46 | Deploy do coletor corrigido (retry em payload `null`, login auditado, token mascarado) |
| 27/09/2026 21:36 | Início do coletor KMZ (velocidade nas vias SPTrans; 5 min, 1 min a partir de 21:44) |

### Qualidade auditada
- Auditoria de 13/09 (dado bruto, 25/08 19h18 → 13/09 02h00 SP): **12.295 ciclos**, 12.132 ok, **163 erros (1,3%)**, 86,1 M posições.
  - **Os 163 erros são todos o mesmo:** `AttributeError: 'NoneType' object has no attribute 'get'`, com duração de 0,1–0,2 s. A API respondeu HTTP 200 com corpo `null`. **Nenhum foi absorvido pelo retry** (o retry só age em falha de requisição) → ciclo perdido. ~35% entre 3h e 7h; pior dia 04/09 (43).
  - ~~"159 erros de rede absorvidos pelo retry"~~ — afirmação de um relatório anterior gerado por IA, **errada**.
  - **14 ciclos sem nenhuma linha na auditoria** (12 na manhã de 28/08, 9h35–14h38 SP). Causa provável: `autenticar()` roda fora do trecho auditado; falha de login mata o processo sem registro.
  - Maior buraco entre ciclos **ok**: 8,5 min; nenhum > 10 min. (A checagem antiga media entre todas as linhas, inclusive erros — método frágil.)
- Após troca para 1 min: mediana 60 s, máximo 73 s.
- **Auditoria do droplet em 27/09 ~21h UTC (21/09 03:06Z → 27/09 21:19Z):** 9.697 ciclos, 9.579 ok, **118 payloads `null`** (1,2%, uniformes ao longo do dia) + **38 ciclos sem registro** (HTTP 522 no `/Login/Autenticar`, confirmado no journal; 24/09: 13, 25/09: 16, 26/09: 8, 27/09: 1). Perda total ~1,6%. Nenhuma lacuna > 5 min entre ciclos ok; duração máx. 45,9 s.
  - **Os payloads `null` foram gravados no bronze** (arquivos de 58 bytes gz com conteúdo `null`, órfãos: auditoria marca `arquivo=""`). `silver.carregar_bronze` agora os pula.
  - **Vazamento:** falha de login grava a URL com `?token=` no journald. Coletor corrigido localmente para mascarar; token deve ser rotacionado de qualquer forma.
- Disco 48% em 27/09. Backup noturno leva 1h07–1h19 (era 6 min) por causa do volume a 1 min; sem falhas `!!!`.
- **CET:** 976 ciclos, 898 ok, 49 `erro_parse` ("0 de 5 regiões", ainda ocorrendo, ~5%), 29 `erro` (timeout/503, 21–23/09). Investigar um HTML de `erro_parse`.
- Dedupe por `(p, ta)` descartava só ~0,3% (a fonte atualiza mais rápido que o poll).

---

## 3. Fonte 1 — API Olho Vivo (SPTrans)

- REST v2.1, base `https://api.olhovivo.sptrans.com.br/v2.1`. Autentica com `POST /Login/Autenticar?token=...` → `true` + cookie de sessão.
- **Pegadinha:** o POST exige `Content-Length: 0` explícito, senão **HTTP 411** (o `requests` não manda sozinho).
- Token recém-criado demora a propagar (voltou `false` por horas antes de funcionar).
- Só estado atual — **nenhum endpoint histórico**. Por isso o projeto existe.

### `/Posicao`
```json
{"hr":"19:18","l":[{"c":"574C-10","cl":34407,"sl":2,"lt0":"DIV. DE SÃO CAETANO","lt1":"SÃO MATEUS","qv":12,
  "vs":[{"p":56286,"a":true,"ta":"2026-08-25T22:18:28Z","py":-23.612088,"px":-46.483258}]}]}
```
| Campo | Significado |
|---|---|
| `p` | prefixo do veículo (ônibus físico) |
| `ta` | instante da captura **na fonte**, UTC |
| `py`/`px` | lat/lon |
| `c` | letreiro = `route_id` do GTFS |
| `cl` | código interno linha+sentido |
| `sl` | sentido (1/2) |
| `lt0`/`lt1` | **terminais da linha**, não o destino atual |
| `a` | acessível |
| `qv` | nº de veículos da linha (recuperável contando) |

### Fatos medidos
- **Fonte atualiza a cada ~45 s** (mediana e p90 de Δ`ta` ≈ 45–46 s). Com poll de 1 min capturamos ~75% das atualizações.
- Idade da posição: mediana 22 s, p99 46 s.
- **Posições já vêm com map matching da SPTrans:** 99,8% com erro lateral 0,00 m sobre a polilinha do shape, máximo 1,54 m. **Não é GPS bruto** — descrever como "posições publicadas pelo operador". Consequência: erro lateral não serve de controle de qualidade.
- Frota: ~8.900 veículos em média, ~11.200 no pico.
- Volume: ~94 MB/dia a 2 min; ~190 MB/dia a 1 min. JSON cru gz ≈ 91% do tamanho do achatado.

---

### `/KMZ` — Velocidade nas vias (coletando desde 27/09)
- `GET /KMZ` (mesma sessão do login) → zip com `TA.kml`, ~156 KB (1,4 MB descomprimido). Traz **os dois sentidos**: 27/09 = 633 `Placemark` (trechos) em 244 `Folder` (corredores/vias, 127 BC + 117 CB). Variantes `/KMZ/BC`, `/KMZ/CB`, `/KMZ/Corredor`, `/KMZ/OutrasVias` são subconjuntos.
- Por trecho: nome da via + sentido, "de X até Y", referência, **extensão (m)**, **velocidade média (km/h)**, **tempo médio de percurso**, velocidade média do corredor; geometria `LineString`. Atributo `eBC="8,4"` no `Placemark` — significado desconhecido. Os campos vêm em HTML escapado dentro de `<description>` → parse na silver.
- **Papel:** velocidade oficial por trecho, calculada pela própria SPTrans a partir dos ônibus → validação direta da nossa velocidade inferida e, nas vias principais, candidato a trecho pronto. Não cobre a malha toda.
- Bronze: `data/kmz/bronze_kmz/dt=YYYY-MM-DD/kmz_<UTC>.kmz` (cru, sem gzip). Auditoria com `sha256` (16 hex) → hashes repetidos = fonte não atualizou; usar para medir a frequência real e ajustar o cron. ~225 MB/dia a 1 min (hash mudou em 3,5 min no primeiro teste). `backup.sh` move após 48h.
- Não usados (e por quê): `/Previsao*` (previsão, não observação), `/Posicao/Garagem`, `/Empresa`. **Baixar uma vez:** `/Corredor` + `/Parada/BuscarParadasPorCorredor` (quais paradas estão em corredor → atributo do KR4).

## 4. GTFS estático (SPTrans)

- **Frequency-based:** `frequencies.txt` sem `exact_times` → não há horário programado, só `headway_secs` por faixa horária.
- `shapes.txt` traz **`shape_dist_traveled`** (distância acumulada em metros) → projeção dá direto "metro X da rota".
- 1.361 rotas, 2.271 trips/shapes. `calendar.txt` válido até mar/2027.
- **Junção:** `c` == `route_id` para 99,8% das linhas (exceções: `PAEC-10`, `TREI-10` — serviço especial/treinamento, 3 veículos; descartar).
- **Sentido (validado):** `sl=1 → direction_id=0`, `sl=2 → direction_id=1`. Teste: projetar nos dois shapes e comparar erro lateral; nos 647 grupos decisivos (erro 3× menor num sentido) a separação foi 294/294 e 353/353, sem contraexemplo.
- 379 rotas com um sentido só (circulares), ~10,8% dos veículos; 5,6% dos veículos operam num sentido sem shape → tratamento próprio.

---

## 5. Fonte 2 — Chuva (SIBH-DAEE / SP Águas)

- **Sistema certo:** `sibh.daee.sp.gov.br` → telemetria, granularidade **"Coleta" (10 min)**, exporta CSV, **10 postos por consulta**. robots.txt bloqueia automação.
- **Sistema errado (não usar):** `hidrologia.spaguas.sp.gov.br` — rede convencional, chuva diária acumulada 7h–7h, série 1937–2023.
- Formato: `Prefixo,Nome,TipoPosto,Data,Valor,Valor2`, `Data` = `YYYY/MM/DD HH:MM` (horário local), **`Valor` = incremento no intervalo** (não acumulado; sem reset a tratar).
- **Coordenadas:** obtidas pelo DevTools — endpoint XHR `stations?serializer=complete&station_type_id=2` (JSON do estado inteiro). **Ainda não validadas:** converter para decimal e checar caixa de SP (lat −24,01 a −23,35; lon −46,83 a −46,36).

### Extração
- 161 postos no município (lista em `sp_ids.txt`, 17 blocos de 10). Notas da reunião falam em ~132–140 com ~120 faltando.
- **Blocos 01–04 feitos** (36 postos). **Faltam blocos 05–17** + repescagem: `1000650;E3-326;296;E3-283;1000838`.
- Excluir `353060702A` (Mogi das Cruzes), `354890601A` (São Carlos), `2249113` (Águas de Sta. Bárbara) — casaram só pelo nome.
- Script `consolida_chuva.py`: junta CSVs, QC por posto, gera série consolidada + relatório + lista de faltantes.

### Qualidade (36 postos avaliados)
- **26 ok, 8 quebrados, 1 fora do município, 1 com lacuna.**
- Critério: total no período entre 100 e 600 mm, ≥34 dias com dado, nenhuma lacuna > 24 h.
- **Telemetria DAEE (IDs numéricos e `E3-`, 10 min): 19 de 20 ok. Rede municipal (`3550308xx`, horária): 6 de 14 ok.** Priorizar DAEE nos blocos restantes.
- `355030873A` (Perus municipal) marcou 0,0 mm → quebrado. Usar `1000838` (Perus DAEE), que registra chuva.
- Validação cruzada disponível: postos duplicados em Perus, Jabaquara, Limão, Pinheiros, Interlagos, Freguesia do Ó.

### Achados
- **Setembro/2026 é o mais chuvoso da série (desde 1943):** 253,8 mm nos primeiros 14 dias vs média climatológica de 83,3 mm no mês (INMET, Mirante de Santana). Validade externa: regime anômalo (solo saturado, chuva persistente) — declarar.
- **Chuva variou 2× dentro da cidade** no mesmo período (15/08–21/09): 176 mm (Itaquera) a 375 mm (Capivari), entre postos DAEE completos. Justifica o recorte espacial.
- Pico: 12,6 mm em 10 min (Mercado Municipal) ≈ 75 mm/h.

---

## 6. Fonte 3 — Lentidão CET + dados de infraestrutura

### CET (coletando desde 21/09)
- URL: `https://www.cetsp.com.br/transito-agora/transito-nas-principais-vias.aspx` — HTML renderizado no servidor.
- Parse: `<li class="txt(Norte|Oeste|Centro|Leste|Sul)"> ... <strong>N km(P%)</strong> ... src=".../ico/TENDENCIA.gif"`.
- **Use `km`, não `%`** — o % é a participação da região no total da cidade (soma 100), não intensidade.
- **Página atualiza a cada 30 min** (trocas em :10 e :40); com poll de 10 min cada estado aparece 3 vezes (23 estados em 69 ciclos = 23 meias-horas). Na silver: colapsar repetidos e atribuir à meia-hora de medição (provavelmente :00/:30, publicada ~10 min depois).
- Sem timestamp de medição na página.
- Lentidão por corredor ("Principais Vias") está desligada no site.
- Histórico público (apilib) só 2001–2018. **Pedido LAI pendente** (texto pronto em §9).
- Papel no projeto: **validação independente** da velocidade inferida dos ônibus (mede carros, não é endógena à operação).

### Infraestrutura para o KR4 (todos retrospectivos)
- **Alagamento:** GeoSampa, camada "Alagamento (dados de Ocorrências)" — Defesa Civil/SIGRC, série de 2013 até hoje, download. Registros CGE/CET desde 2004 classificam **transitável vs intransitável** (melhor que binário).
- **Tipo de via:** Classificação Viária da CET (`/consultas/classificacao-viaria.aspx`); corredores/faixas exclusivas.
- **Candidato adicional:** Censo 2022 IBGE — entorno do domicílio (bueiro/boca de lobo, pavimentação) por setor censitário.
- Semáforos: dados de 2018, baixa confiança (Rafael descartou).

---

## 7. Camada silver — estado e desenho

### Existe (`silver.py`, testado)
- `Shape`: projeção vetorizada de lat/lon na polilinha (equirretangular local centrada em SP) → `(dist_ao_longo_m, erro_lateral_m)`.
- `MAPA_SENTIDO = {1: "0", 2: "1"}`.
- `carregar_bronze(padrao)`: lê **v1 (`.ndjson.gz`) e v2 (`.json.gz`)**, achata o cru, deduplica por `(p, ta)`. Na v2, `coletado_em` vem do nome do arquivo.
- `descobrir_mapa_sentido`, `detectar_cruzamentos` (interpolação linear entre pings), `headway_observado`, `headway_programado`.
- Testes: projeção exata nos vértices; ruído de 40 m degrada coerentemente; headway sintético de 600 s recuperado exato.

### Falta: velocidade por trecho (núcleo do KR1)
- API **não** fornece velocidade. Derivar: `v = Δd / Δt` entre pings consecutivos do mesmo veículo, com `d` = distância ao longo do shape e `t` = `ta` da fonte.
- **Problema de desenho:** a 1 min, ônibus a 40 km/h anda ~670 m entre pings → trechos curtos ficam sem ping dentro. **Solução:** a unidade de observação é o **par de pings**; distribuir (apportionment) sua distância e tempo proporcionalmente entre os trechos que ele atravessa. Velocidade do trecho numa janela = média ponderada por distância.
- Filtros a parametrizar:
  - veículo ocioso (terminal/garagem): amplitude mínima de deslocamento na janela (500 m foi usado na amostra; testar sensibilidade);
  - movimento para trás (~0,3%): descartar;
  - reinício de viagem (salto negativo grande de `d`): cortar o par;
  - velocidade plausível 2–80 km/h; distância > 500 m (filtros do artigo de Niterói);
  - velocidade é **comercial** (inclui paradas e semáforos) — declarar.
- **Baseline:** modelar o **desvio** em relação à linha de base do trecho × hora × dia da semana, não a velocidade bruta.
- **Homogeneidade:** para a análise principal, subamostrar o trecho a 1 min para 2 min (série inteira comparável); o de 1 min fica para análises finas.

### Achados da amostra (demonstração de método, não resultado)
Linha 2290-10, sl=1, 26/08 10:49–11:54 SP, 40 veículos (15 ociosos filtrados):
- velocidade mediana 11,2 km/h (ativos), p90 18,9;
- headway mediano 8,3 min vs programado ~6,5; **CV 0,65**; min 9 s, max 21,5 min;
- EWT: espera real 5,6 min vs regular 3,2 → **+2,4 min (+74%)**; bunching 9,1%, gaps 12,1%.
- Visualizações feitas: gráfico de Marey e animação no shape.

---

## 8. Literatura

### Mais próximo — lidos em 27/09 (PDFs em `../material bibliografico/`)
- **Gonçalves, E. S. (2018)**, dissertação Poli-USP (orient. C. L. Marte), `ErickSobreiroGoncalvesCorr18.pdf`.
  - Dados: AVL SPTrans março/2014 (~35 M registros, ping ~80 s); chuva **horária de 1 estação** (INMET Mirante de Santana) aplicada num raio de 7 km.
  - Método: "microviagens" = par de pings consecutivos, distância euclidiana, **sem map matching e sem trechos**; exclui < 3 km/h, gaps > 5 min, fora de dia útil 7–21h. CHAID + krigagem; **sem teste de significância**.
  - Achados: 17,4 → 16,3 km/h com chuva (−6% agregado); até −24% com ≥ 15 mm/h no pico de sexta. Queda 16–19h. **Efeito defasado** (lentidão chega depois da chuva, propagando dos acessos às vias expressas) → apoia KR2. Sem dose-resposta clara. Vias expressas/acessos/viadutos mais afetados; centro lento mas homogêneo → hipótese para KR4.
  - Limitações: 1 mês, 1 pluviômetro, **Carnaval coincidiu com chuva**.
  - **Não fez ranking de trechos** → KR3 é contribuição nova. Nosso diferencial: trecho via shape, chuva de 10 min do posto mais próximo, vários meses.
- **Tenório et al. (NetMob26, Niterói, IME-USP)**, `relatorio_netmob.PDF` — mesma pergunta em Niterói. Contato: `lucastoshioka@usp.br`.
  - Reaproveitar: filtros de viagem (> 500 m, 2–300 min, 2–80 km/h); **densidade de pings** (observados/esperados, capada em 1) como peso/filtro de cobertura; split temporal no modelo preditivo.
  - Evidência a favor: correlação agregada −0,05, efeito só por rota/região; chuva com menor importância no XGBoost.
  - Limitação declarada = nosso diferencial: poucos eventos de chuva, 1 estação horária, ~1 mês (máx. 11,8 mm/dia).
  - **Não copiar:** uma estação para a cidade (não separa "choveu mais ali" de "infra pior ali"); chuva **diária** × viagem (e o limiar 2,5 mm da OMM é **por hora**); XGBoost prevendo duração bruta com `lineId` (R² 0,84 vem do tamanho da rota); testes por rota sem correção de múltiplas comparações; viagens tratadas como independentes (pseudo-replicação).
  - **Alerta de fuso:** picos de demanda deles às 3–5h e 13–15h = exatamente 3 h antes do típico → compatível com UTC−3 aplicado duas vezes. Testar no nosso pipeline: pico da manhã na velocidade tem que cair entre 6h e 9h locais.
  - **Alerta de dado faltante não aleatório:** a anomalia deles veio de apagão coincidindo com chuva. Cruzar os erros do `auditoria.csv` com chuva.

### Adjacentes em SP
- Azevedo et al. (2021, *Sci. Reports*): chuva **reduz** passageiros idosos/PcD (30 linhas, 2015–2017) — sinal oposto a Niterói.
- Escolha de rota de carros sob chuva em SP (2024): intensidade média e máxima reduzem utilidade das rotas.
- Geotab (set/2025–fev/2026): velocidade do trânsito −3,2% em dias chuvosos, até −14,8% com chuva intensa (não revisado).
- Tomás et al. (2022, *Transactions in GIS*): mapa de risco de alagamento com dados de mobilidade; 1.165 bloqueios por alagamento em 2019 (CGE).
- Chaves Gonçalves (2026, *J. Flood Risk Mgmt*): registros CGE+CET desde 2004 com transitabilidade.
- Rio (2026): 33 pluviômetros de 15 min × 4.868 alagamentos → limiares intensidade-duração (template de desenho).

### Método (GPS de ônibus em SP)
- **Monitor de Ônibus IEMA:** velocidade por par de paradas consecutivas (GTFS) a partir do Olho Vivo — precedente para definir trecho.
- Estudos de faixas exclusivas (GPS 2013–2015): efeito heterogêneo por zona e horário — base para KR4.
- Larsen (2020, Poli-USP): predição de tempo de viagem com Olho Vivo + tráfego + redes neurais; tinha app de coleta cíclica.
- Scipopulis: velocidade dos ônibus de SP desde 2015 (comercial), monitoramento em chuva no Rio.

---

## 9. Pendências (em ordem)

1. ~~Ler a dissertação Poli-USP 2018~~ — feito 27/09 (§8).
2. **Decidir com o Rafael (reunião 28/09):** definição de trecho, [N] como regra, estabilidade operacional do KR3.
3. **Terminar extração SIBH:** blocos 05–17 + repescagem; rodar `consolida_chuva.py`.
4. **Validar coordenadas** dos postos (decimal, sinais negativos, caixa de SP).
5. **Implementar velocidade por trecho** na silver (apportionment + filtros + baseline).
6. **Protocolar LAI** no e-SIC da prefeitura (órgão: CET):
   > Solicito, para fins de pesquisa acadêmica no IME-USP, em CSV: (1) série histórica do índice de lentidão por região (Centro, Leste, Norte, Oeste, Sul), em km e %, na maior resolução disponível (preferencialmente 10 min), com horário de cada medição, de 01/08/2026 até a data da resposta; (2) a mesma série para Lentidão CET-Waze e Monitrans, se bases distintas; (3) documentação metodológica: qual indicador alimenta "Trânsito Agora", significado do % por região, frequência de atualização. Caso alguma parte não esteja disponível no formato solicitado, peço o envio das demais no formato em que existirem.
   Prazo legal: 20 dias + 10 de prorrogação.
7. **Recarregar DigitalOcean** (~15/10).
8. **Databricks Enterprise Trial:** criado; workspace ID enviado ao Rafael (aprovação interna com Elisa). **Confirmar duração da trial** antes de queimar a janela. Docs relevantes agora: Jobs, Triggers (file arrival), Compute. DABs depois que o pipeline existir. Lakeflow Connect: não se aplica (ingestão já é externa). Free Edition tinha egress restrito — não lia o Drive.
9. **Repositório Git:** privado em https://github.com/gabrielgraciano/volbus (push em 27/09). Commit `ba380b4` = estado herdado da IA, antes de qualquer correção. Falta: README escrito pelo Gabriel. `.gitignore` bloqueia `.env`, `rclone.conf`, `data/` e arquivos de dado; `.gitattributes` força LF (CRLF quebra o cron).
9b. ~~Deploy das correções do coletor~~ — feito 27/09 21:46 UTC (commit `63be6e2` do `coletor_v2.py` → `coletor.py` no droplet; backup em `coletor.py.bak-20260927`). A partir daqui, payload `null` entra no retry e falha de login gera linha de auditoria.
9c. ~~Corrigir o `%` do alerta de disco~~ — feito 27/09 (testado com limiar 0%). Crontab versionado em `crontab.txt`; instalar com `crontab crontab.txt`.
10. **Checagens:** fuso (pico 6–9h local), erros de coleta × chuva, velocidade inferida × lentidão CET por região/hora.
11. **Segurança:** decisão do Gabriel (27/09): o token da SPTrans **não será rotacionado** (baixo risco). Ao fim do projeto, revogar o acesso do rclone na conta Google.

---

## 10. Arquivos gerados

| Arquivo | Estado |
|---|---|
| `coletor_v2.py` (local) = `coletor.py` no droplet (v2, payload cru) | **em produção** no droplet |
| `coletor_cet.py` | **em produção** |
| `coletor_kmz.py` | **em produção** desde 27/09 |
| `backup.sh` | **em produção** |
| `silver.py` | atual (lê v1+v2); falta velocidade por trecho |
| `consolida_chuva.py` | atual |
| `coordenadas_postos.csv` | template com os 161 IDs, lat/lon vazios |
| `sp_ids.txt` | 161 IDs do município, `;`-separados |
| `coletor_olhovivo_ndjson.py`, `coletor_olhovivo.py`, `README.md` | **obsoletos** (v1 / versão Parquet) |
| `infra_droplet.md` | **parcialmente obsoleto** (timer de 2 min, cron antigo) |
| `okr-onibus-clima.md` | **obsoleto** (KRs de entrega; substituídos pelos do Rafael) |

---

## 11. Armadilhas já pisadas

- Olho Vivo: POST sem `Content-Length` → 411; token novo leva horas para valer.
- Windows: `~` não existe no `scp` do PowerShell — usar caminho completo entre aspas. `curl` no PowerShell é apelido: usar `curl.exe`.
- Scripts editados no Windows: rodar `sed -i 's/\r$//' arquivo` antes de agendar (CRLF quebra no cron em silêncio).
- crontab: `%` precisa de escape (`\%`), senão vira quebra de linha e o comando é truncado em silêncio.
- Bash interativo: `"!!!"` entre aspas duplas aciona expansão de histórico — usar aspas simples.
- cron não herda ambiente: caminhos absolutos, carregar `.env` explicitamente.
- `apt upgrade` perguntando sobre `sshd_config`: **manter a versão local**.
- Partição por data de SP, timestamps em UTC, SIBH em horário local — padronizar antes de qualquer join.
- Não confundir o `%` da CET com intensidade; não confundir a rede convencional do DAEE com a telemétrica; códigos `E3-` de outras bacias não retornam dados de SP.
- `pandas` no droplet de 512 MB compete com o coletor — análise pesada fora dele.
