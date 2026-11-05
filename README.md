# volbus — Ônibus de São Paulo × chuva

Onde a chuva mais degrada a malha de ônibus de São Paulo, e quais elementos da
infraestrutura estão associados a essa perda. A medida é a velocidade dos ônibus
por trecho, comparada com a linha de base em tempo seco.

Projeto de Gabriel Graciano Dias (Estatística, IME-USP, MAE0350), com mentoria de
Rafael Ribaldo.

## Como funciona

1. **Coleta (VM na DigitalOcean).** `coletor_v2.py` grava a posição de toda a frota
   a cada minuto, pela API Olho Vivo da SPTrans. `coletor_cet.py` coleta a lentidão
   da CET e `coletor_kmz.py` a velocidade nas vias publicada pela SPTrans. O
   `backup.sh` move os arquivos para o Google Drive. O agendamento está em
   `crontab.txt`, e o token da SPTrans fica no `.env`, fora do Git.
2. **Databricks.** Os notebooks em `notebooks/` montam o catálogo `onibus`:
   - **bronze** (`00`–`01`): dado cru, lido do Drive;
   - **silver** (`02`–`07`): GTFS, posições limpas e projetadas na rota,
     deslocamentos, velocidade por trecho e chuva de 10 min do SIBH/DAEE;
   - **gold** (`08`–`13`): linha de base, efeito da chuva e tempo de recuperação,
     na cidade e por trecho, e infraestrutura do GeoSampa.

   O job diário `pipeline-onibus` vai da ingestão até a velocidade por trecho. A
   chuva e a gold rodam à mão.
3. **Resultados.** Dashboard gerado por `dashboards/gerar_dash_resultados.py`.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `notebooks/` | pipeline no Databricks |
| `analises/gold_exploracao/` | consultas e testes no PC de cada etapa da gold |
| `dashboards/` | definições e gerador dos dashboards |
| `docs/` | documentação do projeto |
| `silver.py` | versão local da silver, anterior aos notebooks |
| `consolida_chuva.py` | junta e confere os CSVs de chuva do SIBH |

## Para saber mais

[`docs/projeto_completo.pdf`](docs/projeto_completo.pdf) documenta o projeto
inteiro, da coleta aos KRs, com as decisões de cada etapa.
