# Chuva — inventário das estações SIBH e plano de tratamento

> Projeto Ônibus SP × Chuva (IME-USP / MAE0350). Gerado em 25/10/2026.
> Contexto geral do projeto: ver `CLAUDE.md`. Este documento cobre só a camada de chuva.

## Objetivo desta etapa

Transformar os CSVs exportados do SIBH numa série de chuva confiável, em UTC,
georreferenciada, pronta para ser cruzada com a velocidade dos ônibus por trecho.
O desfecho do projeto é **redução de velocidade durante a chuva e tempo de
recuperação depois dela**, por trecho — então o que importa da chuva é
**intensidade em janela curta, no lugar certo, no horário certo**.

---

## 1. Fonte

- **SIBH – DAEE / SP Águas:** `https://sibh.daee.sp.gov.br/chuva`
- Consulta: Tipo de transmissão **TELEMETRIA**, Agrupar por **Coleta** (resolução nativa), até 10 postos por consulta, exportação em CSV.
- Período baixado: **01/08/2026 a 25/10/2026** (86 dias).
- **Não confundir** com `hidrologia.spaguas.sp.gov.br` (rede convencional, chuva diária 7h–7h, só até 2023).
- O site bloqueia automação (robots.txt). Toda a extração foi manual.

### Formato

```
Prefixo,Nome,TipoPosto,Data,Valor,Valor2
249,São Paulo (G7 - Rio Embu-Mirim),2,2026/08/01 03:00,0,null
```

| Coluna | Significado |
|---|---|
| `Prefixo` | ID do posto. **Ler como string** (há `E3-326`, `A701`, `355030873A`, e IDs numéricos curtos como `5`) |
| `Nome` | `"Município (Nome do posto)"` |
| `TipoPosto` | sempre `2` = pluviométrico |
| `Data` | `YYYY/MM/DD HH:MM` **em UTC** |
| `Valor` | mm de chuva **no intervalo desde a leitura anterior** (incremento, não acumulado) |
| `Valor2` | sempre nulo — descartar |

**Prova de que `Data` é UTC:** toda consulta iniciada em 01/08 00:00 (horário de SP) começa às `03:00`; um download feito às 17:23 locais terminava em `20:10`. Converter para `America/Sao_Paulo` só na hora de exibir ou de cruzar com calendário.

**Prova de que `Valor` é incremento:** zero valores negativos em toda a base, nenhum reset visível, somas de dias chuvosos plausíveis (ex.: ~78 mm num posto em 12/09).

---

## 2. Arquivos

| Arquivo | Conteúdo |
|---|---|
| `sibh_data_xots22fj.csv` | bloco 01 — 9 postos |
| `sibh_data_qtasrln.csv` | bloco 02 — 10 postos |
| `sibh_data_gg5ff2c.csv` | bloco 03 — 10 postos |
| `sibh_data_y3rz0kl.csv` | bloco 04 — 8 postos |
| `sibh_data_5nz0wvq.csv` | bloco 05 — 10 postos |
| `sibh_data_2r7hut6i.csv` | bloco 06 — 9 postos |
| `sibh_data_mjhbzfsk.csv` | bloco 07 — 8 postos |
| `sibh_data_ytikeo5.csv` | bloco 08 — 10 postos |
| `sibh_data_seupq7c.csv` | bloco 09 — 10 postos |
| `sibh_data_lbxyif2.csv` | bloco 10 — 7 postos |
| `sibh_data_mjxxxwc.csv` | bloco 11 — 8 postos |
| `sibh_data_jn0rnqq.csv` | bloco 12 — 7 postos |
| `sibh_data_m44fvugf.csv` | bloco 13 — 7 postos |
| `sibh_data_xglrc7e.csv` | bloco 14 — 7 postos |
| `sibh_data_7yj90f6.csv` | bloco 15 — 9 postos |
| `sibh_data_x9aszsa.csv` | bloco 16 — 9 postos |
| `sibh_data_jp9bz64.csv` | bloco 17 — 1 postos |
| `sibh_data_ckht0gjj.csv` | repescagem — `1000868`, `527` |
| `sibh_data_5tsihqb.csv` | **descartar** — repetição parcial do bloco 07 (só 25/10) |

Os blocos seguem a ordem da lista de 161 postos do município (seção 7).

---

## 3. Resumo da cobertura

| | Postos |
|---|---|
| Lista do município de São Paulo | **161** |
| Com dado baixado | **141** |
| Faltando (o site não devolveu, nem na repescagem) | **20** |

Três postos que aparecem na busca por "São Paulo" **não são do município** e foram excluídos da lista: `353060702A` (Mogi das Cruzes), `354890601A` (São Carlos), `2249113` (Águas de Santa Bárbara). Casaram só porque o nome do posto contém "São Paulo".

### Por rede

| Rede | Como reconhecer | Postos baixados | Cadência |
|---|---|---|---|
| DAEE / estadual | IDs numéricos e `E3-xxx` | 83 | quase todos 10 min regulares (um posto a 5 min: `1000790`, CTH-USP) |
| Municipal (CGE / Defesa Civil) | `3550308xxA/B` | 56 | **irregular** — ver seção 5.2 |
| INMET | `A701`, `A771` | 2 | horária |

### QC preliminar

Critérios aplicados só para triagem (não definitivos — ver seção 5.4):
- mediana de referência = 525,8 mm (postos com ≥95% dos dias e nenhuma lacuna > 24 h)
- **quebrado:** total < 40% da referência (< 210 mm)
- **suspeito:** total > 200% da referência
- **lacuna (dias):** dado em < 90% dos 86 dias
- **lacuna longa:** algum intervalo sem leitura > 24 h

| Rede | ok | quebrado | lacuna longa | lacuna (dias) |
|---|---|---|---|---|
| DAEE / estadual | 65 | 6 | 10 | 2 |
| Municipal | 24 | 26 | 4 | 2 |
| INMET | 2 | 0 | 0 | 0 |
| **Total** | **91** | **32** | **14** | **4** |

A rede municipal falha muito mais. Mas **atenção:** parte do "quebrado" e da "lacuna longa" da rede municipal pode ser artefato do critério, porque essa rede não reporta em intervalo fixo (seção 5.2). Reavaliar antes de descartar.

---

## 4. Estações

### 4.1 Faltando (20)

O site não devolveu dados para estes postos em nenhuma tentativa. `1000650`, `296` e `E3-283` falharam em duas rodadas separadas (setembro e outubro). Hipóteses: posto só fluviométrico (mede nível de rio, não chuva), telemetria desativada, ou fora do ar no período. Muitos têm nome de rio/barragem, o que reforça a primeira.

| Bloco | Prefixo | Estação |
|---|---|---|
| 01 | `1000650` | Pirajussara - Campo Limpo |
| 04 | `296` | Rio Tietê - Ponte do Piqueri |
| 04 | `E3-283` | Nucleo Itaim Biacica |
| 06 | `2346217` | ETT - Terminal Leste |
| 07 | `355030849A` | Vila Carrão |
| 07 | `355030871A` | Ipiranga |
| 10 | `853` | Reservatório Capivari - Jusante |
| 10 | `847` | Córrego Cupecê |
| 10 | `554` | Estação UHE Henry Borden Barramento Billings |
| 11 | `1000800` | Rio Tietê - Barragem Móvel Jusante - Cebolão |
| 11 | `104` | Córrego Tijuco Preto Av. Marechal Tito |
| 12 | `623` | Rio Verde - Rua Cunha Porã |
| 12 | `2346117` | MIRANTE SANTANA |
| 13 | `232` | Rio Tietê- Ponte Dutra |
| 13 | `137` | Córrego Água Espraiada - Rua Rib. do Vale PMSP/SA-03 |
| 14 | `355030854A` | Vila Maria |
| 14 | `2346201` | EL Traição Sul |
| 14 | `355030853A` | Pinheiros |
| 15 | `1000814` | Córrego Pirajuçara - Sharp |
| 16 | `355030848A` | São Miguel Paulista |

Não é preciso insistir neles. A rede restante (141 postos, ~91 íntegros) já cobre a cidade com folga.

### 4.2 Presentes (141)

`Cadência típica` = mediana do intervalo entre leituras. `mm` = soma de `Valor` no período inteiro. QC preliminar conforme seção 3.

| Bloco | Prefixo | Estação | Rede | Cadência típica (min) | Dias c/ dado | Maior lacuna (h) | mm 01/08–25/10 | QC preliminar |
|---|---|---|---|---|---|---|---|---|
| 01 | `1001635` | Córrego Coruja | DAEE/estadual | 10 | 86 | 0.2 | 531.6 | ok |
| 01 | `355030808A` | Vila Clementino | municipal | 60 | 86 | 10.0 | 587.2 | ok |
| 01 | `355030811A` | AC Santana | municipal | 60 | 86 | 9.0 | 118.4 | quebrado (mm baixo) |
| 01 | `355030814A` | Vila das Belezas | municipal | 60 | 80 | 45.2 | 15.8 | quebrado (mm baixo) |
| 01 | `355030844A` | Barro Branco | municipal | 60 | 86 | 10.0 | 85.1 | quebrado (mm baixo) |
| 01 | `355030869A` | Vila Prudente | municipal | 60 | 86 | 35.0 | 534.5 | lacuna longa |
| 01 | `355030873A` | Perus | municipal | 60 | 86 | 9.0 | 0.0 | quebrado (mm baixo) |
| 01 | `386` | Córrego Dois Irmãos | DAEE/estadual | 10 | 86 | 0.2 | 625.4 | ok |
| 01 | `844` | Água Vermelha | DAEE/estadual | 10 | 86 | 0.2 | 584.2 | ok |
| 02 | `1000360` | Córrego Pirajussara - Extra Taboão | DAEE/estadual | 10 | 86 | 15.8 | 574.0 | ok |
| 02 | `1000790` | CTH - USP | DAEE/estadual | 5 | 86 | 0.1 | 538.6 | ok |
| 02 | `1000858` | Rio Aricanduva - Alt. Avenida Principal | DAEE/estadual | 10 | 86 | 0.2 | 422.6 | ok |
| 02 | `1001300` | EEAB- Estação Elevatória de Água Bruta - Capivarí | DAEE/estadual | 10 | 86 | 0.2 | 677.6 | ok |
| 02 | `2346467` | UHE Henry Borden Barramento Billings | DAEE/estadual | 30 | 79 | 188.5 | 189.4 | quebrado (mm baixo) |
| 02 | `249` | G7 - Rio Embu-Mirim | DAEE/estadual | 10 | 86 | 19.5 | 559.0 | ok |
| 02 | `355030813A` | Jardim Guapira | municipal | 30 | 80 | 126.8 | 250.6 | lacuna longa |
| 02 | `355030822A` | Vila Leopoldina | municipal | 60 | 86 | 9.0 | 58.7 | quebrado (mm baixo) |
| 02 | `355030865A` | Vila Constância | municipal | 20 | 86 | 9.0 | 501.5 | ok |
| 02 | `580` | Córrego Itaim - Rua Joaquim L. Veiga (PMSP/BT-03) | DAEE/estadual | 10 | 86 | 0.2 | 559.2 | ok |
| 03 | `1000863` | Córrego Jacú - Av. Itaquera | DAEE/estadual | 10 | 86 | 0.2 | 526.4 | ok |
| 03 | `1000958` | Rio Tamanduateí - Jusante AT -09 Guamiranga | DAEE/estadual | 10 | 84 | 71.3 | 446.0 | lacuna longa |
| 03 | `1001855` | Córrego Itupu | DAEE/estadual | 10 | 86 | 0.2 | 595.2 | ok |
| 03 | `103` | Córrego Itaim - Av Marechal Tito | DAEE/estadual | 10 | 86 | 0.2 | 648.4 | ok |
| 03 | `355030810A` | Chacara Dona Olivia | municipal | 50 | 86 | 9.0 | 215.2 | ok |
| 03 | `355030822B` | Avenida Oratório | municipal | 50 | 59 | 286.7 | 260.6 | lacuna (dias) |
| 03 | `355030896A` | Jardim João XXIII | municipal | 60 | 86 | 9.0 | 100.7 | quebrado (mm baixo) |
| 03 | `516` | Dreno do Brooklin | DAEE/estadual | 10 | 86 | 0.2 | 620.8 | ok |
| 03 | `620` | Córrego Ponte Baixa - Rua Guilerme Valente | DAEE/estadual | 10 | 86 | 0.2 | 368.6 | ok |
| 03 | `E3-326` | Rio Tietê - São Miguel | DAEE/estadual | 10 | 8 | 41.3 | 70.8 | quebrado (mm baixo) |
| 04 | `1000838` | Perus | DAEE/estadual | 10 | 86 | 0.2 | 529.6 | ok |
| 04 | `1000849` | Barragem Guarapiranga | DAEE/estadual | 10 | 86 | 0.2 | 608.0 | ok |
| 04 | `1000883` | Córrego Itaquera - Rua Santa Divina | DAEE/estadual | 10 | 86 | 0.2 | 458.6 | ok |
| 04 | `355030858A` | Jardim Vera Cruz | municipal | 30 | 86 | 9.0 | 586.6 | ok |
| 04 | `355030886A` | Cangaíba | municipal | 60 | 86 | 9.0 | 0.0 | quebrado (mm baixo) |
| 04 | `413` | Rio Tamanduateí - Mercado Municipal | DAEE/estadual | 10 | 86 | 0.2 | 663.8 | ok |
| 04 | `563` | Córrego Ipiranga - Pç. Leonor Kaupa | DAEE/estadual | 10 | 86 | 0.2 | 574.4 | ok |
| 04 | `E3-304` | Tiquatira 3 | DAEE/estadual | 10 | 86 | 1.0 | 645.2 | ok |
| 05 | `1000837` | CGE - R. Bela Cintra | DAEE/estadual | 10 | 86 | 0.2 | 610.2 | ok |
| 05 | `1002855` | GU219 - Córrego Itupu | DAEE/estadual | 10 | 74 | 309.8 | 575.4 | lacuna (dias) |
| 05 | `157` | Rio Aricanduva- Foz | DAEE/estadual | 10 | 86 | 0.7 | 485.0 | ok |
| 05 | `355030808B` | Pirituba | municipal | 30 | 86 | 10.0 | 453.7 | ok |
| 05 | `355030828A` | Jabaquara | municipal | 60 | 86 | 9.0 | 574.4 | ok |
| 05 | `355030851A` | Jaraguá | municipal | 60 | 86 | 21.3 | 0.0 | quebrado (mm baixo) |
| 05 | `355030870A` | Jabaquara | municipal | 60 | 86 | 10.0 | 404.1 | ok |
| 05 | `355030884A` | Lajeado | municipal | 60 | 39 | 154.0 | 68.5 | quebrado (mm baixo) |
| 05 | `355030897A` | CEU Jaguaré | municipal | 60 | 86 | 9.0 | 58.2 | quebrado (mm baixo) |
| 05 | `856` | Córrego Carandirú | DAEE/estadual | 10 | 86 | 16.5 | 592.4 | ok |
| 06 | `1000839` | Ribeirão dos Meninos - Clube São José | DAEE/estadual | 10 | 86 | 0.2 | 574.5 | ok |
| 06 | `2346204` | Limão | DAEE/estadual | 30 | 1 | 0.5 | 0.0 | quebrado (mm baixo) |
| 06 | `355030806A` | Cidade Tiradentes 2 | municipal | 60 | 82 | 84.7 | 2.6 | quebrado (mm baixo) |
| 06 | `355030867A` | C.E.U Parelheiros | municipal | 60 | 86 | 9.0 | 575.0 | ok |
| 06 | `355030881A` | Itaim Paulista | municipal | 60 | 86 | 9.0 | 595.3 | ok |
| 06 | `355030889A` | Capão Redondo | municipal | 60 | 86 | 10.0 | 202.8 | quebrado (mm baixo) |
| 06 | `397` | Rio Pinheiros - Ponte João Dias | DAEE/estadual | 10 | 86 | 0.2 | 579.0 | ok |
| 06 | `5` | Rio Tietê - Belenzinho | DAEE/estadual | 10 | 86 | 0.3 | 178.6 | quebrado (mm baixo) |
| 06 | `728` | RM-19 Piscinão Jaboticabal | DAEE/estadual | 10 | 86 | 0.2 | 592.4 | ok |
| 07 | `1000035` | Núcleo Itam Biacica | DAEE/estadual | 10 | 86 | 0.2 | 506.0 | ok |
| 07 | `1000846` | Santana/Tucuruvi - COMDEC | DAEE/estadual | 10 | 86 | 0.2 | 582.2 | ok |
| 07 | `355030879A` | Avenida Tucuruvi | municipal | 60 | 86 | 9.0 | 139.6 | quebrado (mm baixo) |
| 07 | `591` | Córrego Franquinho - Dom Hélder Câmara | DAEE/estadual | 10 | 78 | 140.2 | 476.0 | lacuna longa |
| 07 | `858` | Córrego Tanquinho | DAEE/estadual | 10 | 86 | 0.2 | 661.2 | ok |
| 07 | `E3-299` | Rio Aricanduva 3- Alt. Rua Gaia | DAEE/estadual | 10 | 86 | 0.2 | 586.2 | ok |
| 07 | `E3-316` | RO-1 - Jd. Sônia Maria (Piscinão) | DAEE/estadual | 10 | 86 | 0.2 | 514.8 | ok |
| 07 | `E3-325` | Jardim Romano | DAEE/estadual | 10 | 86 | 0.7 | 615.8 | ok |
| 08 | `1000945` | Pinheiros | DAEE/estadual | 10 | 86 | 0.2 | 531.6 | ok |
| 08 | `283` | Rio Tamanduateí - Vd. Pacheco Chaves | DAEE/estadual | 10 | 85 | 38.5 | 507.8 | lacuna longa |
| 08 | `284` | Córrego Jaguaré - Rua Jorge Ward | DAEE/estadual | 10 | 86 | 0.2 | 550.8 | ok |
| 08 | `355030820A` | Cidade Tiradentes | municipal | 60 | 83 | 60.0 | 395.7 | lacuna longa |
| 08 | `355030833A` | AC Central de SP | municipal | 20 | 86 | 9.0 | 539.5 | ok |
| 08 | `355030852A` | Cidade Dutra | municipal | 60 | 86 | 23.5 | 3.2 | quebrado (mm baixo) |
| 08 | `355030860A` | Limão | municipal | 20 | 86 | 22.3 | 472.8 | ok |
| 08 | `355030863A` | Capão Redondo 2 | municipal | 60 | 86 | 9.0 | 69.1 | quebrado (mm baixo) |
| 08 | `826` | Córrego Itaquera Soleira | DAEE/estadual | 10 | 86 | 0.2 | 507.4 | ok |
| 08 | `E3-281` | Rio Tietê - Barragem da Penha Jusante | DAEE/estadual | 10 | 86 | 0.2 | 557.2 | ok |
| 09 | `1000480` | Córrego Pirajuçara - Jd. Maria Sampaio | DAEE/estadual | 10 | 86 | 0.2 | 504.2 | ok |
| 09 | `110` | Córrego Itaquera Mirim Montante | DAEE/estadual | 10 | 86 | 0.2 | 506.8 | ok |
| 09 | `275` | Córrego Ipiranga- Rua Coronel Diogo | DAEE/estadual | 10 | 86 | 24.3 | 440.2 | lacuna longa |
| 09 | `277` | Rio Pinheiros - Ponte Cid. Universitária | DAEE/estadual | 10 | 86 | 2.0 | 600.0 | ok |
| 09 | `347` | Córrego Morro do S - Rua Joaquim Nunes Teixeira | DAEE/estadual | 10 | 82 | 100.3 | 494.0 | lacuna longa |
| 09 | `355030801A` | Jardim Paulistano | municipal | 60 | 86 | 9.0 | 548.2 | ok |
| 09 | `355030812A` | Luz | municipal | 20 | 86 | 9.0 | 525.2 | ok |
| 09 | `355030820B` | Vila Babilônia | municipal | 60 | 86 | 9.0 | 382.0 | ok |
| 09 | `355030880A` | Iguatemi | municipal | 60 | 86 | 10.0 | 441.4 | ok |
| 09 | `804` | Córrego Itaquera Mirim 1 | DAEE/estadual | 10 | 86 | 22.2 | 385.0 | ok |
| 10 | `1000390` | Ribeirão dos Meninos - Volks Demarch | DAEE/estadual | 10 | 86 | 0.2 | 499.0 | ok |
| 10 | `1000843` | Rio Aricanduva - Av. Ragueb Chohfi | DAEE/estadual | 10 | 86 | 0.2 | 578.6 | ok |
| 10 | `1000943` | Córrego Tremembé - R. Garabed Gananian | DAEE/estadual | 10 | 86 | 0.2 | 653.4 | ok |
| 10 | `318` | G9 - Rio Cipó | DAEE/estadual | 10 | 85 | 54.7 | 698.4 | lacuna longa |
| 10 | `355030802A` | COHAB Inácio Monteiro | municipal | 60 | 80 | 46.2 | 248.6 | lacuna longa |
| 10 | `355030807A` | Jardim dos Alamos | municipal | 60 | 86 | 10.0 | 110.5 | quebrado (mm baixo) |
| 10 | `636` | Córrego do Lajeado - Rua Manuel B. de Lima | DAEE/estadual | 10 | 85 | 49.0 | 717.8 | lacuna longa |
| 11 | `1000845` | Freguesia do Ó | DAEE/estadual | 10 | 81 | 91.0 | 585.8 | lacuna longa |
| 11 | `1000938` | Jabaquara - Pç. Serafina Gioncoli Vicenti | DAEE/estadual | 10 | 86 | 0.2 | 595.5 | ok |
| 11 | `108` | Córrego Guaratiba Ponto 1- R. Andreas Raselius | DAEE/estadual | 10 | 86 | 0.2 | 218.2 | ok |
| 11 | `355030818A` | Itaquera 2 | municipal | 60 | 73 | 95.0 | 27.3 | quebrado (mm baixo) |
| 11 | `355030845A` | Interlargos | municipal | 50 | 86 | 9.0 | 323.3 | ok |
| 11 | `355030868A` | Jardim Novo Parelheiros | municipal | 60 | 86 | 9.0 | 512.7 | ok |
| 11 | `405` | Córrego Mandaqui - Rua Zilda | DAEE/estadual | 10 | 86 | 0.2 | 577.4 | ok |
| 11 | `E3-279` | Rio Tietê Barragem Móvel Montante | DAEE/estadual | 10 | 86 | 0.2 | 509.8 | ok |
| 12 | `266` | Taquacetuba/Billings | DAEE/estadual | 10 | 86 | 0.2 | 701.2 | ok |
| 12 | `351570703A` | Jardim Renata | municipal | 60 | 86 | 9.0 | 661.6 | ok |
| 12 | `355030803A` | São João Clímaco | municipal | 60 | 86 | 9.0 | 560.9 | ok |
| 12 | `527` | Córrego Água Espraiada - Montante Piscinão | DAEE/estadual | 10 | 86 | 0.2 | 625.4 | ok |
| 12 | `633` | Córrego Perus - Pç Inácio Dias (PMSP/PR-02) | DAEE/estadual | 10 | 86 | 0.2 | 514.4 | ok |
| 12 | `A701` | Mirante de Santana | INMET | 60 | 86 | 17.0 | 554.2 | ok |
| 12 | `E3-282` | Núcleo Jardim Helena | DAEE/estadual | 10 | 86 | 0.2 | 459.4 | ok |
| 12 | `E3-298` | Pinheiros 4/ Rua Nae Minie | DAEE/estadual | 10 | 86 | 0.2 | 653.8 | ok |
| 13 | `1000868` | Vila Mariana - R. Vergueiro | DAEE/estadual | 10 | 82 | 129.7 | 468.0 | lacuna longa |
| 13 | `11` | Jd. Brasilia - Rio Aricanduva | DAEE/estadual | 10 | 86 | 0.2 | 547.4 | ok |
| 13 | `355030801B` | José Bonifácio | municipal | 50 | 86 | 9.0 | 538.8 | ok |
| 13 | `355030817A` | Jaridm Paraná | municipal | 60 | 86 | 10.0 | 3.2 | quebrado (mm baixo) |
| 13 | `355030857A` | Centro | municipal | 60 | 86 | 21.0 | 56.8 | quebrado (mm baixo) |
| 13 | `355030872A` | Freguesia do Ó | municipal | 60 | 86 | 9.0 | 302.8 | ok |
| 13 | `387` | Córrego Mongaguá | DAEE/estadual | 10 | 86 | 0.2 | 593.6 | ok |
| 13 | `783` | Córrego Sapateiro Parque Ibirapuera | DAEE/estadual | 10 | 57 | 719.2 | 293.4 | lacuna (dias) |
| 14 | `1000879` | Rio Pinheiros - Superior - Usina Elevatória Traição | DAEE/estadual | 10 | 86 | 0.2 | 558.2 | ok |
| 14 | `355030824A` | Jardim Ângela | municipal | 60 | 86 | 9.0 | 76.9 | quebrado (mm baixo) |
| 14 | `355030838A` | Residencial Cocaia | municipal | 60 | 86 | 9.0 | 177.6 | quebrado (mm baixo) |
| 14 | `355030846A` | Butantã | municipal | 60 | 86 | 8.3 | 572.5 | ok |
| 14 | `355030859A` | Vila Aricanduva | municipal | 60 | 86 | 20.7 | 428.3 | ok |
| 14 | `631` | Córrego Zavuvus - Pç Tuney Arantes | DAEE/estadual | 10 | 86 | 0.2 | 592.2 | ok |
| 14 | `845` | Córrego Lajeado | DAEE/estadual | 10 | 78 | 221.0 | 148.2 | quebrado (mm baixo) |
| 15 | `1000262` | G16a - Rio Parelheiros | DAEE/estadual | 10 | 86 | 0.2 | 299.0 | ok |
| 15 | `1000861` | Córrego Jacú - Jd. Pantanal | DAEE/estadual | 10 | 86 | 0.2 | 189.2 | quebrado (mm baixo) |
| 15 | `355030809A` | Jardim São Luíz | municipal | 60 | 41 | 2.0 | 255.2 | lacuna (dias) |
| 15 | `355030834A` | Santo Amaro Paulista | municipal | 60 | 79 | 69.0 | 106.9 | quebrado (mm baixo) |
| 15 | `355030856A` | Jardim Imperador | municipal | 60 | 86 | 9.0 | 34.3 | quebrado (mm baixo) |
| 15 | `355030876A` | Ermelino Matarazzo | municipal | 60 | 71 | 175.0 | 65.4 | quebrado (mm baixo) |
| 15 | `389` | Córrego Cocaia | DAEE/estadual | 10 | 86 | 0.2 | 519.6 | ok |
| 15 | `528` | Córrego Água Espraiada - Cabeceira | DAEE/estadual | 10 | 86 | 0.2 | 595.2 | ok |
| 15 | `A771` | Interlargos | INMET | 60 | 86 | 6.0 | 631.4 | ok |
| 16 | `1000780` | Parque da Aclimação | DAEE/estadual | 10 | 86 | 0.2 | 490.2 | ok |
| 16 | `1000853` | Córrego Morro do S | DAEE/estadual | 10 | 78 | 222.7 | 533.2 | lacuna longa |
| 16 | `1000886` | Córrego do Rincão- Montante Piscinão | DAEE/estadual | 10 | 86 | 0.2 | 485.2 | ok |
| 16 | `280` | Córrego Oratório - Vila Prudente | DAEE/estadual | 10 | 86 | 0.2 | 492.0 | ok |
| 16 | `355030832A` | Jardim Previdência | municipal | 30 | 86 | 9.0 | 423.4 | ok |
| 16 | `355030855A` | Jardim Nossa Sr. Aparecida | municipal | 60 | 9 | 62.3 | 0.2 | quebrado (mm baixo) |
| 16 | `355030894A` | Parque Morumbi | municipal | 60 | 86 | 9.0 | 64.9 | quebrado (mm baixo) |
| 16 | `629` | Córrego Moinho Velho - R. Dois de Julho | DAEE/estadual | 10 | 86 | 0.2 | 469.4 | ok |
| 16 | `731` | Córrego Anhangabaú - Av. 23 de Maio | DAEE/estadual | 10 | 86 | 0.2 | 604.6 | ok |
| 17 | `1000817` | Ribeirão Vermelho - Anhanguera | DAEE/estadual | 10 | 86 | 0.2 | 437.8 | ok |

---

## 5. Tratamento — como estruturar

Princípio: **bronze imutável, silver com flags (não com deleção), gold com as variáveis que o modelo usa.** Nenhuma decisão de QC deve apagar dado do silver; ela só marca. Isso permite testar a sensibilidade dos resultados ao critério.

### 5.1 Bronze — os CSVs como chegaram

- Guardar os 18 CSVs originais sem alteração (exceto `sibh_data_5tsihqb.csv`, que pode ser descartado).
- Registrar num manifesto: arquivo, bloco, data do download, postos contidos.

### 5.2 Silver — série limpa por posto

1. **Ler e unir** todos os CSVs, `Prefixo` como string, descartar `Valor2` e `TipoPosto`.
2. **Timestamp:** `Data` → `instante_utc` (tz-aware UTC). Derivar `instante_sp` só como coluna auxiliar.
3. **Deduplicar** por `(prefixo, instante_utc)`. Se duplicatas tiverem `Valor` diferente, registrar — não deveria acontecer.
4. **Excluir** postos fora do município (lista na seção 3).
5. **Entender a cadência antes de regularizar.** Achado importante:
   - **DAEE/estadual:** grade regular de 10 min com **zeros explícitos** (~91–95% das leituras são 0). Ausência de linha = dado faltante.
   - **Municipal (`3550308xx`):** cadência **variável** — mistura de leituras a 10, 20, 30 e 60 min, com só ~40–50% de zeros. Padrão compatível com **registro por evento**: reporta com mais frequência quando chove e espaça quando está seco. Nesse caso, **ausência de linha não é necessariamente dado faltante**, e o `Valor` de uma leitura após 60 min provavelmente cobre os 60 min anteriores.
   - **Verificar essa hipótese** antes de seguir: em postos municipais, os intervalos curtos coincidem com `Valor > 0`? O `Valor` de leituras espaçadas é compatível com o acumulado dos vizinhos DAEE no mesmo intervalo?
6. **Regularizar para uma grade comum de 10 min:**
   - DAEE: já está na grade; linhas ausentes viram `NaN` (faltante), nunca 0.
   - Postos a 5 min (`1000790`): somar pares para 10 min.
   - Municipal: se a hipótese do item 5 se confirmar, a chuva de uma leitura espaçada cobre o intervalo inteiro desde a anterior. Não dá para distribuí-la com honestidade em blocos de 10 min — **manter a resolução nativa e marcar `resolucao_min`** para cada valor, ou agregar esses postos só em janelas de 60 min.
7. **Flags por leitura** (colunas booleanas, sem apagar nada):
   - `f_faltante` — slot da grade sem leitura (só para redes de cadência fixa)
   - `f_intervalo_longo` — valor que cobre mais de 10 min
   - `f_pico_implausivel` — intensidade acima de um limite físico (ex.: > 30 mm em 10 min); conferir contra vizinhos
8. **Flags por posto** (tabela `qc_postos`): cadência típica, completude, maior lacuna, total, razão do total contra a mediana dos 5 vizinhos mais próximos, status.

Saída silver: `chuva_silver` com `prefixo, instante_utc, mm, resolucao_min, f_*`.

### 5.3 Coordenadas

- **Ainda não estão neste conjunto.** Foram obtidas pelo DevTools do SIBH, no endpoint XHR `stations?serializer=complete&station_type_id=2` (JSON de todo o estado, ~2 MB). Pedir esse arquivo ao Gabriel.
- Ao carregar: converter para graus decimais se vier em DMS, **sinal negativo em lat e lon**, e validar que caem dentro da caixa do município (lat −24,01 a −23,35; lon −46,83 a −46,36).
- `351570703A` (Jardim Renata) tem código IBGE de outro município embutido — conferir a coordenada antes de usar.
- Postos duplicados no mesmo bairro em redes diferentes (Perus, Jabaquara, Limão, Pinheiros, Interlagos, Freguesia do Ó, Mirante de Santana) servem de validação cruzada: a série de um deve acompanhar a do outro.

### 5.4 QC definitivo — sugestões

O QC preliminar da seção 3 usa só o total do período. Melhor:
- **Comparação espacial:** para cada posto, razão entre o total dele e a mediana dos k vizinhos mais próximos (k = 5). Posto com razão < 0,4 ou > 2,0 é suspeito. Isso é mais justo que uma mediana da cidade inteira, porque a chuva variou ~2× entre regiões.
- **Comparação temporal por evento:** num dia de chuva forte em toda a cidade (ex.: 12/09), posto que marca zero é quebrado naquele dia, mesmo que o total do período pareça razoável.
- **Completude por janela:** em vez de "dias com dado", fração de slots de 10 min preenchidos na janela de interesse (horário de operação dos ônibus).
- Reportar quantos postos sobram em cada critério — é um parágrafo de metodologia.

### 5.5 Gold — variáveis para o modelo

Unidade de cruzamento: **trecho × instante** (trecho = par de paradas consecutivas do GTFS, decisão a confirmar).

Para cada observação de velocidade no trecho:
1. **Posto associado:** o mais próximo do ponto médio do trecho com dado válido naquele instante. Alternativa mais robusta: IDW (média ponderada pelo inverso da distância) dos 3 mais próximos dentro de um raio máximo (ex.: 5 km). Registrar a distância ao posto usado.
2. **Intensidade:** mm nos 10, 30 e 60 min anteriores ao instante.
3. **Acumulado:** mm nas 3 h e 24 h anteriores (proxy de solo saturado e alagamento persistente).
4. **Indicador de chuva:** `chovendo` se mm nos últimos 30 min ≥ limiar. O limiar da OMM para chuva moderada é 2,5 mm/h — **por hora**, não por dia (erro do artigo de Niterói).
5. **Eventos de chuva por posto** (base do KR2, tempo de recuperação): início = primeiro slot com mm > 0 após ≥ 1 h seca; fim = último slot com mm > 0 antes de ≥ 1 h seca. Guardar `evento_id`, início, fim, total, pico. Cada observação de velocidade recebe `min_desde_fim_do_evento` — é com isso que se mede a recuperação.
6. **Horas pós-chuva não são horas secas.** Na comparação chuva × sem chuva, a categoria "sem chuva" deve excluir as horas logo após um evento (ou o modelo deve incluir `min_desde_fim_do_evento`).

### 5.6 Checagens obrigatórias

- **Fuso:** o pico diário de chuva convectiva em SP é no fim da tarde. Plotar a chuva média por hora em `instante_sp`: o pico tem que cair entre ~15h e 20h locais. Se cair às 12h–17h ou 18h–23h, algum fuso está errado.
- **Consistência espacial:** mapa do total por posto no período — deve ser espacialmente suave, com poucos outliers isolados (esses são os quebrados).
- **Dia de controle:** em 12/09 (um dos dias de maior chuva do recorde), praticamente todos os postos íntegros devem marcar chuva.
- **Dado faltante × chuva:** a lacuna de um posto não pode se concentrar nos horários chuvosos (falha de energia/comunicação durante temporal). Se se concentrar, é viés.

---

## 6. Contexto que importa para a análise

- **Setembro/2026 foi o mês mais chuvoso da série histórica de SP (desde 1943):** 253,8 mm nos primeiros 14 dias no Mirante de Santana, contra média de 83,3 mm para o mês inteiro. Regime anômalo (chuva persistente, solo saturado) — declarar como limitação de validade externa.
- **A chuva variou ~2× dentro da cidade** no mesmo período. Por isso uma estação única para a cidade (como no artigo de Niterói) não serve: confundiria "choveu mais ali" com "a infraestrutura ali é pior".
- A coleta de posição dos ônibus vai de **25/08/2026** em diante (2 min até 21/09 02:55 UTC, 1 min depois). Os dias 01/08–24/08 de chuva não têm ônibus correspondente — servem só para caracterizar a rede.

---

## 7. Lista completa dos 161 postos do município (ordem dos blocos)

```
01  355030873A;355030814A;355030869A;355030808A;1001635;355030811A;355030844A;844;1000650;386
02  355030813A;1000790;355030822A;1001300;355030865A;1000858;1000360;249;2346467;580
03  355030896A;516;355030810A;620;355030822B;1000863;1001855;103;1000958;E3-326
04  355030886A;296;1000883;E3-304;413;563;E3-283;355030858A;1000849;1000838
05  355030851A;1002855;157;355030828A;355030808B;355030870A;355030897A;355030884A;856;1000837
06  2346204;355030867A;1000839;5;728;355030881A;355030889A;397;355030806A;2346217
07  E3-316;1000846;591;1000035;355030849A;858;E3-325;E3-299;355030879A;355030871A
08  355030860A;355030833A;1000945;284;283;826;355030852A;355030820A;355030863A;E3-281
09  355030801A;110;355030820B;355030812A;275;277;347;1000480;804;355030880A
10  1000943;1000843;355030807A;1000390;853;636;847;554;318;355030802A
11  355030818A;355030845A;1000845;E3-279;1000800;1000938;405;355030868A;108;104
12  E3-298;351570703A;355030803A;623;633;A701;266;2346117;E3-282;527
13  783;355030801B;11;232;355030872A;355030817A;355030857A;137;387;1000868
14  1000879;355030846A;845;631;355030838A;355030854A;2346201;355030824A;355030859A;355030853A
15  355030876A;1000262;1000861;389;355030856A;355030834A;A771;355030809A;528;1000814
16  629;1000780;280;355030894A;1000853;355030855A;1000886;355030832A;731;355030848A
17  1000817
```

---

## 8. Próximos passos sugeridos (para a sessão de análise)

1. Montar o silver (5.2) e **validar a hipótese da rede municipal** (item 5).
2. Carregar e validar coordenadas (5.3) — pedir o JSON ao Gabriel.
3. Rodar o QC espacial (5.4) e fechar a lista de postos válidos.
4. Rodar as checagens de 5.6, principalmente a de fuso.
5. Construir a tabela de eventos de chuva (5.5, item 5).
6. Só então fazer o join com os trechos de ônibus.

---

## 9. Verificação independente (25/10/2026, Claude, lendo os CSVs)

Feita sobre os arquivos em `Downloads/dados_chuva/` antes do upload. Manifesto com linhas, postos, período e sha256 de cada arquivo: `manifesto.csv` (vai junto para o volume).

### O que confere

| Afirmação deste documento | Resultado |
|---|---|
| Formato `Prefixo,Nome,TipoPosto,Data,Valor,Valor2`; `TipoPosto` sempre 2; `Valor2` sempre nulo | ✅ |
| Período 01/08 03:00 → 25/10 ~21:00 (UTC) | ✅ todos os blocos começam em `2026/08/01 03:00` |
| Sem duplicatas `(prefixo, instante)` | ✅ 0 (nem com valor diferente) |
| `5tsihqb` é repetição do bloco 07 | ✅ 8 postos, todos presentes em outros arquivos; só 25/10 |
| Totais por posto (seção 4.2) | ✅ amostra de 6 postos bate exatamente (ex.: `1001635` 531,6 mm; `A701` 554,2 mm; `355030873A` 0,0 mm) |
| Redes | ✅ 81 DAEE/estadual, 56 municipal, 2 INMET |
| Dia de controle 12/09 | ✅ 124 de 131 postos DAEE+INMET com dado registraram chuva; mediana 55,8 mm no dia |
| **Rede municipal reporta por evento** (hipótese da seção 5.2) | ✅ **confirmada**: leituras a ≤ 10 min da anterior têm chuva em 90% dos casos; a 30–60 min, em 6%. Seco → 1 leitura/h; chovendo → a cada ~10 min. DAEE: 97% das leituras a 10 min, 94% zeros |

### O que NÃO confere (corrigir antes da silver)

1. ~~Falta o arquivo da repescagem~~ — `sibh_data_ckht0gjj.csv` acrescentado em 25/10 (23.820 linhas, `1000868` e `527`, período completo). **141 postos.**
2. **Há 15 valores negativos** (a seção 1 diz "zero negativos"). Em 6 postos DAEE: `856` (−31,6; −13,6; −0,6), `804` (8 leituras, até −19,4), `275` (−7,4), `283` (−6,0), `5` (−1,1; −2,1), `1000845` (−0,25). Quase todos entre 10h e 13h UTC (7h–10h SP), dias depois de chuva forte — padrão de **correção/manutenção do pluviômetro** (esvaziamento), não de chuva. Tratamento: flag `f_negativo`, mm = nulo; não descontar dos acumulados.
3. **Pico de 35,0 mm numa leitura de 10 min** (`E3-325`, 01/09 14:50 UTC) = 210 mm/h. Acima do limite físico sugerido na 5.2 (30 mm/10 min). Flag `f_pico_implausivel` e conferir com os vizinhos quando houver coordenadas.
4. **Prova de UTC pelos horários dos arquivos** (a mais direta): o Windows grava o horário de salvamento em horário de Brasília. `sibh_data_jp9bz64.csv` foi salvo às **18:04** e termina em `21:00`; `sibh_data_ckht0gjj.csv`, salvo às **18:55**, termina em `21:40`. Se `Data` fosse horário de Brasília, os arquivos teriam medições de 3 h no futuro. Em UTC, 21:00 = 18:00 e 21:40 = 18:40 — a última leitura antes de cada download.
5. **Checagem de fuso pelo pico do fim da tarde: inconclusiva.** No período, a chuva total por hora concentra-se de madrugada (pico 4h–6h no relógio do arquivo = 1h–3h SP se UTC), porque set/2026 foi dominado por chuva frontal persistente, não convectiva. A evidência de UTC continua sendo a da seção 1 (consulta de 00:00 SP começa às 03:00; downloads às ~17h SP terminam às ~20–21h). Conferir de novo na gold, cruzando com a queda de velocidade dos ônibus. **`CLAUDE.md` §5 dizia "horário local" — está errado; corrigido para UTC.**

### Faltando para a silver

- **Coordenadas dos postos** (JSON `stations?serializer=complete&station_type_id=2` do DevTools do SIBH). O `coordenadas_postos.csv` do repositório está com lat/lon vazios.

---

## 10. Silver da chuva no Databricks (25/10/2026)

Notebook `07_silver_chuva`. Dados crus no volume: `/Volumes/onibus/bronze/raw/chuva/sibh/download=2026-10-25/` (18 CSVs + `stations.json` + `manifesto.csv`).

| Tabela | O que é |
|---|---|
| `onibus.bronze.chuva_sibh` | leituras como vieram (1.124.746 linhas = manifesto, sem duplicata) |
| `onibus.silver.chuva_10min` | grade de 10 min em UTC por posto; cada leitura repartida nos slots desde a anterior (até 60 min); faltante = nulo, nunca 0; flags `f_faltante`, `f_negativo`, `f_intervalo_longo`, `f_pico_implausivel` |
| `onibus.silver.postos` | 141 postos: coordenadas (`stations.json`, todas na caixa de SP), rede, operador, qualidade desde 25/08, `duplicata_de`, `status` |

**Redes e operadores** (do `stations.json`): DAEE = SAISP 56, SP Águas 17, Sabesp 8, ANA 2; **os `3550308xx` são do CEMADEN** (não da prefeitura/CGE, como estava escrito antes); INMET 2. Coordenadas: DAEE com 4+ casas decimais; CEMADEN com 3 (~100 m; zeros à direita cortados no JSON).

**Conservação:** soma de mm por posto na grade = soma das leituras não negativas da bronze, em 139 postos exato; em `5` (−1,1 mm) e `804` (−0,2 mm) uma leitura negativa caiu no mesmo slot de uma positiva e o slot inteiro ficou nulo.

**Status** (primeiro que se aplica; desde 25/08): `quebrado` = razão contra os 5 vizinhos confiáveis < 0,4, ou 0 mm em 12/09 tendo dado; `suspeito` = razão > 2,0; `lacunar` = completude < 90%; `ok`.

| Rede | ok | lacunar | quebrado | suspeito |
|---|---|---|---|---|
| DAEE | 71 | 5 | 6 | 0 |
| CEMADEN | 23 | 5 | 27 | 0 |
| INMET | 1 | 1 | 0 | 0 |
| **Total** | **95** | **11** | **33** | **0** |

Os 95 `ok` cobrem a cidade sem buracos grandes (mapa no notebook). Mediana do total dos `ok`: 528 mm desde 25/08.

**Duas lições do QC:**
1. **Vizinhos quebrados contaminam a comparação espacial.** Na 1ª versão (uma passada), 5 postos DAEE normais (485–624 mm) saíram `suspeito` porque os vizinhos de referência eram postos CEMADEN quebrados — completude alta, mas leituras zeradas. Corrigido com duas passadas: a 2ª só usa vizinhos que ficaram dentro de [0,4; 2,0] na 1ª. Efeito: 4 viraram `ok`, 1 virou `lacunar` (`1000853`, completude 85%), e o `108` (196 mm), que os vizinhos quebrados "salvavam", virou `quebrado`.
2. **Mesmo pluviômetro cadastrado duas vezes:** `1002855` ("GU219 - Córrego Itupu") e `1001855` ("Córrego Itupu") estão a 0 m um do outro com o mesmo total (574,2 mm). `duplicata_de` marca o `1002855`; a gold deve usar só um.

**Para a gold:** usar `status = 'ok'` e `duplicata_de IS NULL` (94 postos) como padrão; testar sensibilidade incluindo os `lacunar`. A chuva **não** está no job diário: só muda quando houver novo download manual do SIBH.
