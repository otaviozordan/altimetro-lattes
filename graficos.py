"""Graficos do Altimetro. Cada grafico e uma especificacao (dict) que vira uma
lista de primitivas (retangulo, barra, linha, texto, circulo); as primitivas
sao desenhadas no Canvas do Tk (tela) ou em SVG (relatorio e exportacao).

Tipos:
  colunas  {"titulo","sub","categorias":[...], "series":[(nome, [valores])]}
           varias series = colunas empilhadas, com legenda
  barras   {"titulo","sub","rotulos":[...], "valores":[...]}  (horizontais)
  rede     {"titulo","sub","nos":[(id, nome, peso, grupo)], "arestas":[(a, b, peso)],
            "pos":{id:(x, y)} em 0..1, "grupos":[nomes na ordem das cores]}
"""
import html
import math

import marca

TXT, MUDO, GRADE, EIXO = marca.TINTA, marca.MUDO, "#EDF0F4", "#C5CDD8"
FONTE = "Segoe UI"  # a janela troca pela fonte do sistema (macOS, Linux)


def _passo(maior, alvo=5):
    if maior <= alvo:
        return 1
    bruto = maior / alvo
    p = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 5, 10):
        if bruto <= m * p:
            return int(m * p)
    return int(10 * p)


def _num(n):
    return f"{int(round(n)):,}".replace(",", ".")


def _largura_texto(t, tam):
    return len(str(t)) * tam * 0.56


def _cortar(t, n):
    t = str(t)
    return t if len(t) <= n else t[: n - 1] + "…"


def primitivas(spec, w, h, k=1.0):
    """k: escala da tela (1 no SVG)."""
    t = spec["tipo"]
    if t == "colunas":
        return _colunas(spec, w, h, k)
    if t == "barras":
        return _barras(spec, w, h, k)
    if t == "rede":
        return _rede(spec, w, h, k)
    return []


def _legenda(nomes, cores, x, y, k, w):
    out = []
    for nome, cor in zip(nomes, cores):
        larg = 18 * k + _largura_texto(nome, 11 * k) + 16 * k
        if x + larg > w and out:
            x, y = 16 * k, y + 20 * k
        out.append(("rect", x, y - 5 * k, x + 11 * k, y + 6 * k, cor, None))
        out.append(("text", x + 17 * k, y, nome, "w", 11 * k, TXT, False))
        x += larg
    return out, y


def _colunas(spec, w, h, k):
    cats, series = spec["categorias"], spec["series"]
    cores = marca.SERIES
    out = []
    topo = 16 * k
    if len(series) > 1:
        leg, y = _legenda([s[0] for s in series], cores, 16 * k, 14 * k, k, w)
        out += leg
        topo = y + 22 * k
    totais = [sum(s[1][i] for s in series) for i in range(len(cats))]
    maior = max(totais + [1])
    passo = _passo(maior)
    teto = math.ceil(maior / passo) * passo
    esq = max(36 * k, _largura_texto(_num(teto), 10 * k) + 18 * k)
    dir_, base = 12 * k, h - 30 * k
    for v in range(0, int(teto) + 1, int(passo)):
        y = base - (base - topo - 14 * k) * v / teto
        out.append(("line", esq, y, w - dir_, y, EIXO if v == 0 else GRADE, 1))
        out.append(("text", esq - 8 * k, y, _num(v), "e", 10 * k, MUDO, False))
    n = max(len(cats), 1)
    larg = (w - esq - dir_) / n
    barra = max(3 * k, min(48 * k, larg * 0.62))
    rotular = n <= 20
    salto = 1 if n <= 20 else (2 if n <= 40 else 5)
    for i, c in enumerate(cats):
        x0 = esq + i * larg + (larg - barra) / 2
        y_atual = base
        segs = [(s[0], s[1][i], cores[j % len(cores)], j) for j, s in enumerate(series)]
        visiveis = [sg for sg in segs if sg[1]]
        for j, (nome, v, cor, js) in enumerate(visiveis):
            alt = (base - topo - 14 * k) * v / teto
            y0 = y_atual - alt
            ultimo = j == len(visiveis) - 1
            gap = 2 * k if not ultimo else 0  # 2px de fundo entre os segmentos
            dica = f"{c} · {nome}: {_num(v)}" if len(series) > 1 else f"{c}: {_num(v)}"
            ref = None
            if spec.get("filtros") and js < len(spec["filtros"]):
                ref = dict(spec["filtros"][js])
                ref[ref.pop("_ano", "ano")] = c  # o ano clicado
            out.append(("bar", x0, y0 + gap, x0 + barra, y_atual, cor, 4 * k if ultimo else 0, dica, ref))
            y_atual = y0
        if rotular and totais[i]:
            out.append(("text", x0 + barra / 2, y_atual - 9 * k, _num(totais[i]), "c", 10 * k, TXT, True))
        if i % salto == 0 or i == n - 1:
            out.append(("text", x0 + barra / 2, base + 14 * k, str(c), "c", 10 * k, MUDO, False))
    return out


def _barras(spec, w, h, k):
    rot, val = spec["rotulos"], spec["valores"]
    out = []
    n = max(len(rot), 1)
    tam = 11 * k
    maxc = 46
    esq = min(w * 0.46, max(_largura_texto(_cortar(r, maxc), tam) for r in rot) + 20 * k) if rot else 40 * k
    dir_ = max(46 * k, _largura_texto(_num(max(val + [0])), 10 * k) + 18 * k)
    topo, base = 8 * k, h - 8 * k
    linha = (base - topo) / n
    barra = max(4 * k, min(22 * k, linha * 0.66))
    maior = max(val + [1])
    refs = spec.get("refs") or [None] * len(rot)
    for i, (r, v) in enumerate(zip(rot, val)):
        y = topo + i * linha + linha / 2
        out.append(("text", esq - 10 * k, y, _cortar(r, maxc), "e", tam, TXT, False, str(r)))
        x1 = esq + (w - esq - dir_) * v / maior
        if v:
            out.append(("hbar", esq, y - barra / 2, x1, y + barra / 2, spec.get("cor", marca.SERIES[0]), 4 * k, f"{r}: {_num(v)}", refs[i]))
        out.append(("text", x1 + 8 * k, y, _num(v), "w", 10 * k, TXT, True))
    out.insert(0, ("line", esq, topo, esq, base, EIXO, 1))
    return out


def _rede(spec, w, h, k):
    nos, arestas, pos = spec["nos"], spec["arestas"], spec["pos"]
    grupos = spec.get("grupos", [])
    out = []
    leg, y = _legenda(grupos, marca.SERIES, 16 * k, 14 * k, k, w) if grupos else ([], 0)
    out += leg
    m = 34 * k
    topo = (y + 26 * k) if grupos else m
    P = {i: (m + x * (w - 2 * m), topo + yy * (h - topo - m)) for i, (x, yy) in pos.items()}
    maior_a = max([a[2] for a in arestas] + [1])
    for a, b, p in sorted(arestas, key=lambda x: x[2]):
        if a in P and b in P:
            out.append(("line", *P[a], *P[b], "#AFC0D3" if p < maior_a * 0.5 else "#7F98B6", max(1, 1 + 5 * p / maior_a) * k))
    maior_n = max([n[2] for n in nos] + [1])
    grau = {}
    for a, b, p in arestas:
        grau[a] = grau.get(a, 0) + p
        grau[b] = grau.get(b, 0) + p
    rotulados = {n[0] for n in sorted(nos, key=lambda n: -grau.get(n[0], 0))[:16]}
    for i, nome, peso, g in sorted(nos, key=lambda n: n[2]):
        if i not in P:
            continue
        x, yy = P[i]
        r = (5 + 15 * math.sqrt(peso / maior_n)) * k
        cor = marca.SERIES[grupos.index(g) % len(marca.SERIES)] if g in grupos else marca.SERIES[0]
        out.append(("circle", x, yy, r, cor, f"{nome}: {_num(peso)} trabalhos, {_num(grau.get(i, 0))} em parceria no grupo", {"membro_ficha": i}))
        if i in rotulados:
            curto = " ".join(nome.split()[:1] + nome.split()[-1:]) if len(nome.split()) > 1 else nome
            out.append(("text", x, yy + r + 9 * k, curto, "c", 10 * k, TXT, False))
    return out


# --------------------------------------------------------------- Tk Canvas

def desenhar(canvas, spec, k=1.0):
    """Desenha no Canvas e devolve as areas de dica [(x0,y0,x1,y1,texto,ref)];
    ref diz a que itens a barra se refere (None: nao clicavel)."""
    canvas.delete("all")
    w, h = canvas.winfo_width(), canvas.winfo_height()
    if w < 80 or h < 80 or not spec:
        return []
    dicas = []
    anc = {"w": "w", "e": "e", "c": "center"}
    for p in primitivas(spec, w, h, k):
        t = p[0]
        if t == "line":
            canvas.create_line(p[1], p[2], p[3], p[4], fill=p[5], width=p[6])
        elif t == "rect":
            canvas.create_rectangle(p[1], p[2], p[3], p[4], fill=p[5], outline="")
        elif t in ("bar", "hbar"):
            x0, y0, x1, y1, cor, r, dica = p[1:8]
            _ret_arredondado(canvas, x0, y0, x1, y1, cor, r, "topo" if t == "bar" else "dir")
            dicas.append((min(x0, x1) - 2, min(y0, y1) - 4, max(x0, x1) + 2, max(y0, y1), dica, p[8] if len(p) > 8 else None))
        elif t == "circle":
            x, y, r, cor, dica = p[1:6]
            canvas.create_oval(x - r, y - r, x + r, y + r, fill=cor, outline="white", width=2)
            dicas.append((x - r, y - r, x + r, y + r, dica, p[6] if len(p) > 6 else None))
        elif t == "text":
            canvas.create_text(p[1], p[2], text=p[3], anchor=anc[p[4]], font=(FONTE, -int(p[5] * 1.0), "bold" if p[7] else "normal"), fill=p[6])
            if len(p) > 8 and p[8] != p[3]:
                dicas.append((p[1] - 300 if p[4] == "e" else p[1], p[2] - 8, p[1], p[2] + 8, p[8], None))
    return dicas


def _ret_arredondado(c, x0, y0, x1, y1, cor, r, lado):
    r = min(r, abs(x1 - x0) / 2, abs(y1 - y0))
    if r < 1:
        c.create_rectangle(x0, y0, x1, y1, fill=cor, outline="")
        return
    if lado == "topo":
        c.create_rectangle(x0, y0 + r, x1, y1, fill=cor, outline="")
        c.create_rectangle(x0 + r, y0, x1 - r, y0 + r, fill=cor, outline="")
        c.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=cor, outline="")
        c.create_oval(x1 - 2 * r, y0, x1, y0 + 2 * r, fill=cor, outline="")
    else:
        c.create_rectangle(x0, y0, x1 - r, y1, fill=cor, outline="")
        c.create_rectangle(x1 - r, y0 + r, x1, y1 - r, fill=cor, outline="")
        c.create_oval(x1 - 2 * r, y0, x1, y0 + 2 * r, fill=cor, outline="")
        c.create_oval(x1 - 2 * r, y1 - 2 * r, x1, y1, fill=cor, outline="")


# --------------------------------------------------------------------- SVG

def svg(spec, w=760, h=340):
    e = html.escape
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{e(spec.get("titulo", ""))}" '
         f'font-family="Segoe UI, Helvetica Neue, Arial, Noto Sans, DejaVu Sans, sans-serif">']
    anc = {"w": "start", "e": "end", "c": "middle"}
    for q in primitivas(spec, w, h, 1.0):
        t = q[0]
        if t == "line":
            p.append(f'<line x1="{q[1]:.1f}" y1="{q[2]:.1f}" x2="{q[3]:.1f}" y2="{q[4]:.1f}" stroke="{q[5]}" stroke-width="{q[6]:.1f}" stroke-linecap="round"/>')
        elif t == "rect":
            p.append(f'<rect x="{q[1]:.1f}" y="{q[2]:.1f}" width="{q[3] - q[1]:.1f}" height="{q[4] - q[2]:.1f}" rx="2" fill="{q[5]}"/>')
        elif t in ("bar", "hbar"):
            x0, y0, x1, y1, cor, r, dica = q[1:8]
            p.append(f'<path d="{_caminho(x0, y0, x1, y1, r, t)}" fill="{cor}"><title>{e(dica)}</title></path>')
        elif t == "circle":
            p.append(f'<circle cx="{q[1]:.1f}" cy="{q[2]:.1f}" r="{q[3]:.1f}" fill="{q[4]}" stroke="#fff" stroke-width="2"><title>{e(q[5])}</title></circle>')
        elif t == "text":
            peso = ' font-weight="600"' if q[7] else ""
            dica = f"<title>{e(q[8])}</title>" if len(q) > 8 and q[8] != q[3] else ""
            p.append(f'<text x="{q[1]:.1f}" y="{q[2]:.1f}" text-anchor="{anc[q[4]]}" dominant-baseline="central" font-size="{q[5]:.1f}" fill="{q[6]}"{peso}>{dica}{e(str(q[3]))}</text>')
    p.append("</svg>")
    return "".join(p)


def _caminho(x0, y0, x1, y1, r, t):
    r = min(r, abs(x1 - x0) / 2, abs(y1 - y0))
    if t == "bar":
        return (f"M{x0:.1f},{y1:.1f}L{x0:.1f},{y0 + r:.1f}Q{x0:.1f},{y0:.1f} {x0 + r:.1f},{y0:.1f}L{x1 - r:.1f},{y0:.1f}"
                f"Q{x1:.1f},{y0:.1f} {x1:.1f},{y0 + r:.1f}L{x1:.1f},{y1:.1f}Z")
    return (f"M{x0:.1f},{y0:.1f}L{x1 - r:.1f},{y0:.1f}Q{x1:.1f},{y0:.1f} {x1:.1f},{y0 + r:.1f}L{x1:.1f},{y1 - r:.1f}"
            f"Q{x1:.1f},{y1:.1f} {x1 - r:.1f},{y1:.1f}L{x0:.1f},{y1:.1f}Z")


def altura_sugerida(spec):
    if spec["tipo"] == "barras":
        return max(160, 34 * len(spec["rotulos"]) + 20)
    if spec["tipo"] == "rede":
        return 520
    return 340 if len(spec.get("series", [])) > 1 else 300


# --------------------------------------------------------------------- PNG

_FONTES_PNG = {
    False: [r"%WINDIR%\Fonts\segoeui.ttf", r"%WINDIR%\Fonts\arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "DejaVuSans.ttf"],
    True: [r"%WINDIR%\Fonts\segoeuib.ttf", r"%WINDIR%\Fonts\arialbd.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
}


def _fonte(tam, negrito=False):
    """Uma fonte TrueType do sistema (Windows, macOS ou Linux) para o PNG."""
    import os
    from PIL import ImageFont
    for c in _FONTES_PNG[negrito]:
        try:
            return ImageFont.truetype(os.path.expandvars(c.replace("%WINDIR%", os.environ.get("WINDIR", r"C:\Windows"))), int(tam))
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=int(tam))
    except TypeError:
        return ImageFont.load_default()


def png(spec, caminho, w=1000, h=None, k=2.0):
    """Grava o grafico em PNG (k = densidade: 2 fica nitido em documentos)."""
    from PIL import Image, ImageDraw
    h = h or altura_sugerida(spec)
    W, H = int(w * k), int(h * k)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    anc = {"w": "lm", "e": "rm", "c": "mm"}
    fontes = {}
    for q in primitivas(spec, W, H, k):
        t = q[0]
        if t == "line":
            d.line((q[1], q[2], q[3], q[4]), fill=q[5], width=max(1, int(round(q[6] * (1 if q[6] > 1.5 else k)))))
        elif t == "rect":
            d.rectangle((q[1], q[2], q[3], q[4]), fill=q[5])
        elif t in ("bar", "hbar"):
            x0, y0, x1, y1, cor, r = q[1:7]
            r = int(min(r, abs(x1 - x0) / 2, abs(y1 - y0)))
            if r >= 1:
                d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=cor)
                if t == "bar":
                    d.rectangle((x0, y1 - r, x1, y1), fill=cor)  # base reta
                else:
                    d.rectangle((x0, y0, x0 + r, y1), fill=cor)
            else:
                d.rectangle((x0, y0, x1, y1), fill=cor)
        elif t == "circle":
            x, y, r, cor = q[1:5]
            d.ellipse((x - r - 2 * k, y - r - 2 * k, x + r + 2 * k, y + r + 2 * k), fill="white")
            d.ellipse((x - r, y - r, x + r, y + r), fill=cor)
        elif t == "text":
            chave = (round(q[5]), bool(q[7]))
            if chave not in fontes:
                fontes[chave] = _fonte(q[5] * 1.05, q[7])
            d.text((q[1], q[2]), str(q[3]), fill=q[6], font=fontes[chave], anchor=anc[q[4]])
    img.save(caminho)
