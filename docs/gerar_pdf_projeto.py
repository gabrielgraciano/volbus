"""Gera docs/projeto_completo.pdf a partir de docs/projeto_completo.md.

Precisa de Quarto (traz o pandoc), Chrome e pypdf. Duas passadas: a primeira descobre em que página cada título caiu, e a
segunda escreve esses números no sumário. No fim, acrescenta os marcadores. O rodapé vem do CSS.

Uso: python gerar_pdf_projeto.py PASTA_TEMPORARIA
"""
import os
import re
import subprocess
import sys
from html import unescape

from pypdf import PdfReader, PdfWriter

DOCS = os.path.dirname(os.path.abspath(__file__))
TMP = sys.argv[1]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
QUARTO = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Quarto\bin\quarto.exe")

EXTRA = """<style>
@page {
  @bottom-left { content: "Ônibus SP × Chuva"; font-family: "Segoe UI", Arial, sans-serif; font-size: 8pt; color: #56607a; }
  @bottom-right { content: counter(page) " de " counter(pages); font-family: "Segoe UI", Arial, sans-serif; font-size: 8pt; color: #56607a; }
}
@page :first { @bottom-left { content: none; } @bottom-right { content: none; } }
nav#TOC { page-break-after: always; font-size: 10pt; }
nav#TOC h2 { font-size: 15pt; margin-top: 8px; }
nav#TOC ul { list-style: none; padding-left: 0; margin: 0; }
nav#TOC ul ul { padding-left: 14px; font-size: 9pt; color: #56607a; }
nav#TOC > ul > li { margin-top: 5px; font-weight: 600; }
nav#TOC > ul > li li { font-weight: 400; }
nav#TOC a { color: #1d2433; display: flex; align-items: baseline; }
nav#TOC a .pg { margin-left: auto; padding-left: 8px; font-variant-numeric: tabular-nums; }
nav#TOC a .pontos { flex: 1; border-bottom: 1px dotted #c8c4b8; margin: 0 6px; transform: translateY(-3px); }
figure { margin: 12px 0 14px; page-break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 118mm; }
figcaption { font-size: 9pt; color: #56607a; margin-top: 4px; text-align: left; }
p, li { orphans: 3; widows: 3; }
table.longa { page-break-inside: auto; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
p:has(+ table), p:has(+ pre), p:has(+ figure), p:has(+ ul) { break-after: avoid; }
ul { margin-top: 4px; }
</style>
"""


def html(saida):
    entrada = os.path.join(DOCS, "projeto_completo.md")
    extra = os.path.join(TMP, "extra.html")
    open(extra, "w", encoding="utf-8").write(EXTRA)
    subprocess.run([QUARTO, "pandoc", entrada, "-f", "markdown", "-t", "html5", "-s", "--toc", "--toc-depth=2", "--metadata", "toc-title=Sumário",
                    "--css", os.path.join(DOCS, "estilo_pdf.css"), "--embed-resources", "--resource-path", DOCS, "-H", extra, "-o", saida], check=True)


def imprimir(entrada, saida):
    url = "file:///" + os.path.abspath(entrada).replace("\\", "/")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={saida}", url], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def titulos(texto):
    """Pares (id, título, nível) do sumário do pandoc."""
    nav = texto[texto.index('<nav id="TOC"'):texto.index("</nav>")]
    achados = []
    for m in re.finditer(r'<a href="#([^"]+)"[^>]*>(.*?)</a>', nav, re.S):
        achados.append((m.group(1), re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()))
    return achados


def normaliza(s):
    return re.sub(r"\s+", "", s)


def achar_paginas(pdf, tit):
    leitor = PdfReader(pdf)
    paginas = [normaliza(p.extract_text() or "") for p in leitor.pages]
    # o corpo começa na página do primeiro capítulo, depois do sumário
    atual = next(i for i, t in enumerate(paginas) if "Estedocumentoacompanhaosdados" in t)
    primeiro = atual
    achados = {}
    for ident, titulo in tit:
        alvo = normaliza(titulo)
        for i in range(atual, len(paginas)):
            if alvo in paginas[i]:
                achados[ident] = i + 1
                atual = i
                break
        else:
            raise RuntimeError(f"título não encontrado: {titulo}")
    return achados, len(paginas), primeiro


def com_paginas(texto, pag):
    ini, fim = texto.index('<nav id="TOC"'), texto.index("</nav>")
    nav = texto[ini:fim]

    def troca(m):
        ident = m.group(1)
        return f'<a href="#{ident}"{m.group(2)}><span>{m.group(3)}</span><span class="pontos"></span><span class="pg">{pag[ident]}</span></a>'

    return tabelas_longas(texto[:ini] + re.sub(r'<a href="#([^"]+)"([^>]*)>(.*?)</a>', troca, nav, flags=re.S) + texto[fim:])


def tabelas_longas(texto):
    """Tabela com mais de 9 linhas pode quebrar entre páginas; as curtas ficam inteiras."""
    def marca(m):
        return m.group(0).replace("<table", '<table class="longa"', 1) if m.group(0).count("<tr") > 9 else m.group(0)

    return re.sub(r"<table.*?</table>", marca, texto, flags=re.S)


def finalizar(pdf, saida, tit, pag):
    escritor = PdfWriter(clone_from=pdf)
    total = len(escritor.pages)
    pai = None
    for ident, titulo in tit:
        secao = bool(re.match(r"\d+\.\d+ ", titulo))
        item = escritor.add_outline_item(titulo, pag[ident] - 1, parent=pai if secao else None)
        if not secao:
            pai = item
    escritor.add_metadata({"/Title": "Ônibus SP × Chuva: o projeto do começo ao fim", "/Author": "Gabriel Graciano Dias"})
    escritor.write(saida)
    return total


os.makedirs(TMP, exist_ok=True)
h1 = os.path.join(TMP, "p1.html")
html(h1)
texto = open(h1, encoding="utf-8").read()
tit = titulos(texto)
# primeira passada com números provisórios: reserva o espaço do sumário
h2 = os.path.join(TMP, "p2.html")
open(h2, "w", encoding="utf-8").write(com_paginas(texto, {i: 999 for i, _ in tit}))
pdf1 = os.path.join(TMP, "p1.pdf")
imprimir(h2, pdf1)
pag, _, _ = achar_paginas(pdf1, tit)
# segunda passada com os números certos
open(h2, "w", encoding="utf-8").write(com_paginas(texto, pag))
pdf2 = os.path.join(TMP, "p2.pdf")
imprimir(h2, pdf2)
pag2, _, _ = achar_paginas(pdf2, tit)
assert pag == pag2, "o sumário mudou de tamanho entre as passadas"
total = finalizar(pdf2, os.path.join(DOCS, "projeto_completo.pdf"), tit, pag2)
print(f"ok: {total} páginas, {len(tit)} títulos no sumário")
