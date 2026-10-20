"""Relatorio do Altimetro em HTML: um arquivo so (logo, graficos em SVG,
tabelas e texto), pronto para abrir no navegador e imprimir ou salvar em PDF."""
import base64
import datetime
import html
import os

import graficos as gr
import marca
import nucleo as n

SECOES = [
    ("equipe", "Equipe", True),
    ("resumo", "Números principais", True),
    ("indicadores", "Indicadores", True),
    ("graficos", "Gráficos", True),
    ("texto", "Texto descritivo", True),
    ("por_ano", "Produção ano a ano", True),
    ("por_membro", "Produção por membro", True),
    ("orientacoes", "Orientações", True),
    ("projetos", "Projetos", True),
    ("veiculos", "Periódicos e eventos", True),
    ("membros", "Membros considerados", True),
    ("itens", "Lista completa de itens", False),
]
GRAFICOS_RELATORIO = ["producao", "artigos", "orientacoes", "projetos", "membros", "periodicos", "rede"]

e = html.escape

CSS = """
:root{color-scheme:light;--marinho:%(m)s;--azul:%(a)s;--ambar:%(am)s;--tinta:%(t)s;--mudo:%(mu)s;--borda:%(b)s;--fundo:%(f)s}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--tinta);font:15px/1.55 "Segoe UI",Arial,sans-serif}
.pagina{max-width:1080px;margin:0 auto;padding:0 28px 48px}
header{background:var(--marinho);color:#fff;padding:28px 0 26px;margin-bottom:28px}
header .pagina{display:flex;align-items:center;gap:20px;padding-bottom:0}
header .marca{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#C9D6E6;font-weight:600}
header h1{margin:2px 0 4px;font-size:28px;line-height:1.2}
header p{margin:0;color:#DCE6F2}
h2{font-size:20px;margin:40px 0 6px;padding-bottom:8px;border-bottom:2px solid var(--borda);color:var(--marinho);break-after:avoid}
h3{font-size:15px;margin:22px 0 8px}
.sub{color:var(--mudo);margin:0 0 16px;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.card{background:#fff;border:1px solid var(--borda);border-radius:12px;padding:14px 16px;break-inside:avoid}
.card .v{font-size:30px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.card .t{font-weight:600;margin-top:2px}
.card .s{color:var(--mudo);font-size:13px;margin-top:4px}
.sobe{color:#1F7A4D;font-weight:600}.desce{color:#B42318;font-weight:600}
table{width:100%%;border-collapse:collapse;background:#fff;border:1px solid var(--borda);border-radius:10px;overflow:hidden;font-size:13.5px}
th{background:#EEF2F6;color:var(--mudo);font-size:12px;text-transform:uppercase;letter-spacing:.03em;text-align:left;padding:8px 10px}
td{padding:7px 10px;border-top:1px solid #EEF1F5;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.total td{font-weight:700;background:#F7F9FB}
.figura{background:#fff;border:1px solid var(--borda);border-radius:12px;padding:16px 18px 10px;margin:0 0 16px;break-inside:avoid}
.figura h3{margin:0 0 8px}
.texto p{margin:0 0 12px;max-width:80ch}
.tabela-larga{overflow-x:auto}
.equipe-cat{margin:18px 0 8px;font-weight:700;color:var(--marinho)}
.equipe{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.pessoa{display:flex;align-items:center;gap:12px;background:#fff;border:1px solid var(--borda);border-radius:12px;padding:10px 12px;break-inside:avoid}
.pessoa img,.pessoa .ini{flex:none;width:52px;height:52px;border-radius:50%%;object-fit:cover}
.pessoa .ini{display:grid;place-items:center;color:#fff;font-weight:700;font-size:18px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.pessoa b{display:block;font-size:13.5px;line-height:1.3}
.pessoa span{color:var(--mudo);font-size:12px}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--borda);color:var(--mudo);font-size:12.5px;display:flex;gap:14px;align-items:center}
footer svg{flex:none}
.imprimir{position:fixed;right:20px;bottom:20px;background:var(--azul);color:#fff;border:0;border-radius:999px;padding:10px 18px;font:600 14px "Segoe UI",Arial;cursor:pointer;box-shadow:0 4px 14px rgba(15,45,78,.25)}
@media (max-width:760px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}header .pagina{flex-direction:column;align-items:flex-start}}
@media print{body{background:#fff;font-size:12.5px}.imprimir{display:none}header{-webkit-print-color-adjust:exact;print-color-adjust:exact}
 .pagina{max-width:none;padding:0 6mm}h2{margin-top:24px}.card,.figura,table{break-inside:avoid}@page{size:A4;margin:12mm}}
""" % {"m": marca.MARINHO, "a": marca.AZUL, "am": marca.AMBAR, "t": marca.TINTA, "mu": marca.MUDO, "b": marca.BORDA, "f": marca.FUNDO}


def _tabela(cab, linhas, total=False, numericas=None):
    if not linhas:
        return '<p class="sub">Nada no período.</p>'
    if numericas is None:
        numericas = {i for i in range(1, len(cab)) if all(isinstance(r[i], (int, float)) or r[i] == "" for r in linhas)}
    h = ['<div class="tabela-larga"><table><thead><tr>']
    h += [f'<th class="{"n" if i in numericas else ""}">{e(str(c))}</th>' for i, c in enumerate(cab)]
    h.append("</tr></thead><tbody>")
    for k, r in enumerate(linhas):
        cls = ' class="total"' if total and k == len(linhas) - 1 else ""
        h.append(f"<tr{cls}>" + "".join(f'<td class="{"n" if i in numericas else ""}">{e(n.num(v) if isinstance(v, int) and abs(v) >= 10000 else str(v))}</td>'
                                        for i, v in enumerate(r)) + "</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


def _delta(atual, antes, ant):
    v = n.variacao(atual, antes)
    if v is None or ant is None:
        return ""
    cls = "sobe" if v > 0 else "desce" if v < 0 else ""
    seta = "▲" if v > 0 else "▼" if v < 0 else "="
    return f'<div class="s"><span class="{cls}">{seta} {abs(v)}%</span> em relação a {ant.a}–{ant.b} ({n.num(antes)})</div>'


def cartoes(est):
    ant = est.anterior
    N = est.n
    a = ant.n if ant else None

    def valor(x, cats):
        return sum(x[c] for c in cats)
    itens = [
        ("Artigos em periódicos", ["artigos"]),
        ("Trabalhos completos em eventos", ["completos"]),
        ("Livros e capítulos", ["livros", "capitulos"]),
        ("Produção técnica", ["software", "patentes", "tecnica"]),
        ("Orientações concluídas", n.OC),
        ("Orientações em andamento", n.OA),
        ("Projetos ativos", n.PJ),
        ("Prêmios e títulos", ["premios"]),
    ]
    h = ['<div class="cards">']
    for titulo, cats in itens:
        v = valor(N, cats)
        d = _delta(v, valor(a, cats), ant) if a is not None and not cats[0].startswith(("oa_", "pj_")) else ""
        h.append(f'<div class="card"><div class="v">{n.num(v)}</div><div class="t">{e(titulo)}</div>{d}</div>')
    h.append("</div>")
    return "".join(h)


def equipe(est, base, grupo):
    ordem = {c: i for i, c in enumerate(n.CATEGORIAS)}
    por_cat = {}
    for lid in est.sel:
        if lid in base.pessoas:
            por_cat.setdefault((grupo.membro(lid) or {}).get("categoria") or "Sem categoria", []).append(lid)
    h = []
    for cat in sorted(por_cat, key=lambda c: (ordem.get(c, 99), c)):
        h.append(f'<div class="equipe-cat">{e(cat)} · {len(por_cat[cat])}</div><div class="equipe">')
        for lid in sorted(por_cat[cat], key=lambda i: n.norm(base.pessoas[i]["nome"])):
            nome = base.pessoas[lid]["nome"]
            arq = grupo.foto(lid)
            if arq:
                with open(arq, "rb") as f:
                    rosto = f'<img src="data:image/jpeg;base64,{base64.b64encode(f.read()).decode()}" alt="">'
            else:
                cor = marca.SERIES[(n.CATEGORIAS.index(cat) if cat in n.CATEGORIAS else len(n.CATEGORIAS)) % len(marca.SERIES)]
                rosto = f'<div class="ini" style="background:{cor}">{e(n.iniciais(nome))}</div>'
            c = est.por_membro.get(lid, {})
            partes = [n.qt(c.get("artigos", 0), "artigo", "artigos")]
            o = sum(c.get(k, 0) for k in n.OC)
            if o:
                partes.append(n.qt(o, "orientação", "orientações"))
            h.append(f'<div class="pessoa">{rosto}<div><b>{e(nome)}</b><span>{" · ".join(partes)}</span></div></div>')
        h.append("</div>")
    return "".join(h)


def gerar(est, base, grupo, secoes=None):
    secoes = set(secoes or [k for k, _t, padrao in SECOES if padrao])
    per = f"{est.a}" if est.a == est.b else f"{est.a} a {est.b}"
    hoje = datetime.date.today()
    corpo = []
    nomes = dict((k, t) for k, t, _p in SECOES)

    def secao(chave, conteudo, sub=""):
        if chave in secoes:
            corpo.append(f'<section id="{chave}"><h2>{e(nomes[chave])}</h2>' + (f'<p class="sub">{e(sub)}</p>' if sub else "") + conteudo + "</section>")

    if "equipe" in secoes:
        secao("equipe", equipe(est, base, grupo), "Quem está neste relatório; os números são do período.")
    secao("resumo", cartoes(est), f"{n.qt(len(est.sel), 'membro considerado', 'membros considerados')}. Trabalhos que estão no currículo "
          "de mais de um membro contam uma vez. Orientações em andamento e projetos contam os que estavam ativos em algum momento do período.")
    if "indicadores" in secoes:
        secao("indicadores", _tabela(*n.tabela_indicadores(est, base, grupo), numericas=set()))
    if "graficos" in secoes:
        figs = []
        for chave, titulo, spec in n.graficos(est, base, grupo):
            if chave not in GRAFICOS_RELATORIO:
                continue
            vazio = (spec["tipo"] == "barras" and not spec["valores"]) or (spec["tipo"] == "rede" and not spec["nos"]) or \
                    (spec["tipo"] == "colunas" and not any(sum(s[1]) for s in spec["series"]))
            if vazio:
                continue
            sub = "Cada ponto é um membro (tamanho: produção no período); cada linha, trabalhos em comum." if chave == "rede" else ""
            figs.append(f'<div class="figura"><h3>{e(titulo)}</h3>' + (f'<p class="sub">{e(sub)}</p>' if sub else "")
                        + gr.svg(spec, 1000, gr.altura_sugerida(spec) + (60 if chave == "rede" else 0)) + "</div>")
        secao("graficos", "".join(figs) or '<p class="sub">Sem dados para gráficos no período.</p>')
    if "texto" in secoes:
        secao("texto", '<div class="texto">' + "".join(f"<p>{e(p)}</p>" for p in n.texto_relatorio(est, grupo, base).split("\n\n")) + "</div>")
    if "por_ano" in secoes:
        secao("por_ano", _tabela(*n.tabela_por_ano(est)))
    if "por_membro" in secoes:
        secao("por_membro", _tabela(*n.tabela_por_membro(est, base, grupo)))
    if "orientacoes" in secoes:
        cab, l = n.tabela_orientacoes_resumo(est)
        secao("orientacoes", _tabela(cab, l, total=True) + "<h3>Lista</h3>" + _tabela(*n.tabela_orientacoes(est, base)))
    if "projetos" in secoes:
        secao("projetos", _tabela(*n.tabela_projetos(est, base)))
    if "veiculos" in secoes:
        secao("veiculos", _tabela(*n.tabela_veiculos(est)))
    if "membros" in secoes:
        linhas = sorted([[base.pessoas[i]["nome"], (grupo.membro(i) or {}).get("categoria", ""), i, base.pessoas[i]["atualizado"]]
                         for i in est.sel if i in base.pessoas], key=lambda r: (r[1], n.norm(r[0])))
        secao("membros", _tabela(["Membro", "Categoria", "ID Lattes", "Currículo atualizado em"], linhas, numericas=set()))
    if "itens" in secoes:
        secao("itens", _tabela(*n.tabela_itens(est, base)))

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relatório {e(grupo.nome)} {e(per)}</title>
<link rel="icon" href="data:image/svg+xml,{e(marca.logo_svg(64)).replace('#', '%23')}">
<style>{CSS}</style></head><body>
<header><div class="pagina">{marca.logo_svg(64)}<div><div class="marca">{e(marca.NOME)} · relatório do grupo</div>
<h1>{e(grupo.nome)}</h1><p>Período {e(per)} · gerado em {hoje:%d/%m/%Y} · dados do Currículo Lattes</p></div></div></header>
<main class="pagina">{''.join(corpo)}
<footer>{marca.logo_svg(28)}<div>Gerado pelo <strong>{e(marca.NOME)}</strong> {e(marca.VERSAO)}, criado por {e(marca.AUTOR)}
({e(marca.CURSO)}, {e(marca.INSTITUICAO)}). Dados dos Currículos Lattes (CNPq), processados pelo scriptLattes
(Mena-Chalco &amp; Cesar-Jr.).</div></footer></main>
<button class="imprimir" onclick="window.print()">Imprimir ou salvar em PDF</button>
</body></html>"""
