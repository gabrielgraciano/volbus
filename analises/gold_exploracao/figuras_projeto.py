"""Gera as figuras de docs/projeto_completo.md a partir das tabelas gold.

Uso: python figuras_projeto.py PASTA_DE_SAIDA
Precisa de dbsql.py, com a CLI do Databricks autenticada.
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from dbsql import q

SAIDA = sys.argv[1]
AZUL, LARANJA, AQUA, AMARELO = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
TINTA, SECUNDARIA, GRADE = "#0b0b0b", "#52514e", "#e6e4dd"

plt.rcParams.update({"font.family": "Segoe UI", "font.size": 10, "axes.edgecolor": GRADE, "axes.labelcolor": SECUNDARIA,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRADE, "grid.linewidth": 0.7,
                     "xtick.color": SECUNDARIA, "ytick.color": SECUNDARIA, "xtick.major.size": 0, "ytick.major.size": 0,
                     "axes.titlesize": 11, "axes.titlecolor": TINTA, "axes.titleweight": "semibold", "axes.titlelocation": "left",
                     "legend.frameon": False, "legend.fontsize": 9, "lines.linewidth": 2, "savefig.dpi": 200, "savefig.bbox": "tight"})


def virgula(x, casas=2):
    return f"{x:.{casas}f}".replace(".", ",")


def eixo_virgula(ax, casas=2, eixo="y"):
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: virgula(v, casas))
    (ax.yaxis if eixo == "y" else ax.xaxis).set_major_formatter(fmt)


# 1. velocidade por hora
v = q("""SELECT hour(janela_sp) h, sum(dist_m) / sum(tempo_s) * 3.6 v FROM onibus.silver.velocidade_trecho
         WHERE tipo_dia = 'util' GROUP BY 1 ORDER BY 1""", timeout_s=600).astype(float)
fig, ax = plt.subplots(figsize=(7.2, 2.9))
ax.plot(v.h, v.v, color=AZUL)
ax.scatter([18], [v.v[18]], s=36, color=AZUL, zorder=3, edgecolor="white", linewidth=1.2)
ax.annotate(f"18h: {virgula(v.v[18], 1)} km/h", (18, v.v[18]), xytext=(0, -16), textcoords="offset points", ha="center", color=TINTA, fontsize=9)
ax.annotate(f"7h: {virgula(v.v[7], 1)} km/h", (7, v.v[7]), xytext=(0, -16), textcoords="offset points", ha="center", color=TINTA, fontsize=9)
ax.scatter([7], [v.v[7]], s=36, color=AZUL, zorder=3, edgecolor="white", linewidth=1.2)
ax.set_title("Velocidade comercial média em dia útil")
ax.set_xlabel("hora do dia")
ax.set_ylabel("km/h")
ax.set_xticks(range(0, 24, 3))
ax.set_ylim(8, 25)
ax.set_yticks([10, 15, 20, 25])
fig.savefig(f"{SAIDA}/fig_velocidade_hora.png")
plt.close(fig)

# 2. efeito por classe
e = q("""SELECT periodo, classe_chuva, razao, ic_inf, ic_sup, n_dias, fragil FROM onibus.gold.efeito_cidade
         WHERE recorte = 'tudo' AND periodo IN ('todos', 'tarde') AND classe_chuva IN ('traco', 'fraca', 'moderada', 'forte', 'muito_forte')""", timeout_s=300)
for c in ("razao", "ic_inf", "ic_sup", "n_dias"):
    e[c] = pd.to_numeric(e[c])
e["fragil"] = e.fragil.astype(str).str.lower() == "true"
classes = ["traco", "fraca", "moderada", "forte", "muito_forte"]
nomes = ["traço (< 0,4 mm/h)", "fraca (< 2,5)", "moderada (< 10)", "forte (< 25)", "muito forte (≥ 25)"]
fig, ax = plt.subplots(figsize=(7.2, 3.1))
for periodo, cor, rotulo, dy in [("todos", AZUL, "dia todo", 0.14), ("tarde", LARANJA, "pico da tarde (16–19h)", -0.14)]:
    x = e[e.periodo == periodo].set_index("classe_chuva").reindex(classes)
    y = np.arange(len(classes))[::-1] + dy
    ok = ~x.fragil
    ax.hlines(y[ok], x.ic_inf[ok], x.ic_sup[ok], color=cor, lw=1.6)
    ax.scatter(x.razao[ok], y[ok], s=42, color=cor, zorder=3, edgecolor="white", linewidth=1, label=rotulo)
    ax.scatter(x.razao[~ok], y[~ok], s=42, facecolor="white", edgecolor=cor, linewidth=1.6, zorder=3)
ax.scatter([], [], s=42, facecolor="white", edgecolor=SECUNDARIA, linewidth=1.6, label="menos de 8 dias (sem intervalo)")
ax.axvline(1, color=SECUNDARIA, lw=1)
ax.set_yticks(range(len(classes)))
ax.set_yticklabels(nomes[::-1])
ax.grid(axis="y", visible=False)
eixo_virgula(ax, 2, "x")
ax.set_xlim(0.78, 1.01)
ax.set_title("Velocidade na chuva, relativa ao normal, com intervalo de 95%")
ax.set_xlabel("razão (1 = normal)")
ax.legend(loc="lower left", bbox_to_anchor=(1.0, 0.25))
fig.savefig(f"{SAIDA}/fig_efeito_classe.png")
plt.close(fig)

# 3. recuperacao da cidade
c = q("""SELECT periodo_fim, classe_evento, tau_min, razao, ic_inf, ic_sup, fragil FROM onibus.gold.recuperacao_cidade
         WHERE periodo_fim IN ('manha', 'meio', 'tarde', 'noite')""", timeout_s=300)
for k in ("tau_min", "razao", "ic_inf", "ic_sup"):
    c[k] = pd.to_numeric(c[k])
c["fragil"] = c.fragil.astype(str).str.lower() == "true"
fig, eixos = plt.subplots(1, 4, figsize=(7.4, 2.7), sharey=True, sharex=True)
for ax, periodo, titulo in zip(eixos, ("manha", "meio", "tarde", "noite"), ("manhã", "meio do dia", "tarde", "noite")):
    for classe, cor in (("fraca", AZUL), ("moderada", LARANJA), ("forte", AQUA)):
        x = c[(c.periodo_fim == periodo) & (c.classe_evento == classe)].sort_values("tau_min")
        fragil = x.fragil.iloc[0]
        ax.plot(x.tau_min, x.razao, color=cor, lw=1.6, ls=(0, (4, 2)) if fragil else "-", label=classe)
        if not fragil:
            ax.fill_between(x.tau_min, x.ic_inf, x.ic_sup, color=cor, alpha=0.12, lw=0)
    ax.axhline(0.99, color=SECUNDARIA, lw=0.9, ls=":")
    ax.set_title(titulo)
    ax.set_xticks([0, 60, 120, 170])
    ax.set_xlabel("min depois do fim", fontsize=8)
    ax.tick_params(labelsize=8)
eixos[0].set_ylim(0.84, 1.10)
eixos[0].set_yticks([0.85, 0.90, 0.95, 1.00, 1.05, 1.10])
eixo_virgula(eixos[0], 2)
eixos[0].set_ylabel("razão")
eixos[0].legend(loc="lower right", fontsize=7.5, handlelength=1.4)
fig.subplots_adjust(wspace=0.08)
fig.savefig(f"{SAIDA}/fig_recuperacao_cidade.png")
plt.close(fig)

# 4. infraestrutura por grupo
g = pd.read_parquet(f"{sys.argv[2]}/t12_grupos.parquet")
fig, eixos = plt.subplots(1, 2, figsize=(7.4, 3.0), sharey=True)
ordem_chuva = ["fraca", "moderada", "forte+"]
for ax, dim, grupos, titulo in [(eixos[0], "via", ["coletora", "arterial", "expressa"], "Tipo de via"),
                                (eixos[1], "alagamento", ["0 dias", "1-4 dias", "5-19 dias", "20+ dias"], "Dias de alagamento a 100 m")]:
    for grupo, cor in zip(grupos, (AZUL, LARANJA, AQUA, AMARELO)):
        x = g[(g.dimensao == dim) & (g.grupo == grupo)].set_index("chuva").reindex(ordem_chuva)
        ax.plot(ordem_chuva, x.razao, color=cor, marker="o", markersize=5.5, markeredgecolor="white", markeredgewidth=1, label=grupo.replace("-", "–"))
    ax.set_title(titulo)
    ax.legend(loc="lower left", fontsize=8)
    ax.set_xlabel("intensidade da chuva")
eixo_virgula(eixos[0], 2)
eixos[0].set_ylabel("razão (1 = normal)")
eixos[0].set_ylim(0.82, 0.98)
eixos[0].set_yticks([0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98])
fig.savefig(f"{SAIDA}/fig_infra.png")
plt.close(fig)

# 5. piores fora da amostra
vv = pd.read_parquet(f"{sys.argv[2]}/t13_validacao.parquet").set_index("metrica").valor
fx = [0, 30, 60, 90, 120, 150]
fig, ax = plt.subplots(figsize=(7.2, 2.8))
for rot, cor, nome in [("piores", LARANJA, "1% piores na chuva, escolhidos em outros dias"), ("resto", AZUL, "resto dos trechos")]:
    ax.plot(np.array(fx) + 15, [vv[f"{rot}_fora_da_amostra_{f}min"] for f in fx], color=cor, marker="o", markersize=5.5,
            markeredgecolor="white", markeredgewidth=1, label=nome)
ax.axhline(0.99, color=SECUNDARIA, lw=0.9, ls=":")
ax.text(168, 0.982, "0,99", color=SECUNDARIA, fontsize=8, ha="right", va="top")
eixo_virgula(ax, 2)
ax.set_xticks([0, 30, 60, 90, 120, 150, 180])
ax.set_ylim(0.8, 1.03)
ax.set_title("Recuperação medida em dias que não entraram na escolha")
ax.set_xlabel("minutos depois do fim da chuva")
ax.set_ylabel("razão")
ax.legend(loc="lower right")
fig.savefig(f"{SAIDA}/fig_piores.png")
plt.close(fig)

# 6. mapa do grupo critico
s = pd.read_parquet(f"{sys.argv[2]}/t12_trecho.parquet")
fig, ax = plt.subplots(figsize=(5.2, 6.4))
ax.scatter(s.lon, s.lat, s=0.35, color="#cfcdc5", linewidths=0, rasterized=True)
k = s[s.grupo_critico]
ax.scatter(k.lon, k.lat, s=20, color=LARANJA, edgecolor="white", linewidth=0.5, zorder=3, label=f"grupo crítico: {len(k)} trechos em {k.local_critico.nunique()} locais")
ax.scatter([], [], s=12, color="#cfcdc5", label="demais trechos da regra [N]")
ax.set_aspect(1 / np.cos(np.radians(23.55)))
ax.set_xticks([])
ax.set_yticks([])
ax.grid(False)
for lado in ("left", "bottom"):
    ax.spines[lado].set_visible(False)
ax.set_title("Onde estão os trechos críticos")
ax.legend(loc="lower right", markerscale=1)
fig.savefig(f"{SAIDA}/fig_mapa_critico.png")
plt.close(fig)
print("ok")
