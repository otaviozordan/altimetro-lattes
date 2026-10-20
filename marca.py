"""Identidade visual do Altimetro: nome, cores e a logo (um mostrador de
altimetro com o ponteiro ambar subindo sobre barras que crescem).

A logo e desenhada aqui mesmo: em SVG (relatorio HTML) e em PNG/ICO com o
Pillow (janela e icone). python marca.py regrava os arquivos de marca/."""
import math
import os

NOME = "Altímetro"
SLOGAN = "Métricas de grupos de pesquisa a partir do Currículo Lattes"
VERSAO = "1.0"
# Autoria (pagina Sobre, rodape dos relatorios e README)
AUTORES = [
    {"nome": "Otávio Zordan Alves", "descricao": "Engenharia Mecânica Aeronáutica · UNIFEI",
     "gemec": "https://gemec.unifei.edu.br/membro/otavio-zordan-alves/", "linkedin": "https://www.linkedin.com/in/otavio-zordan"},
    {"nome": "Guilherme Ferreira Gomes", "descricao": "Professor · Líder do GEMEC · UNIFEI",
     "gemec": "https://gemec.unifei.edu.br/membro/guilherme-ferreira-gomes/", "linkedin": "https://www.linkedin.com/in/guilhermefergom/"},
]
AUTOR = " e ".join(a["nome"] for a in AUTORES)
INSTITUICAO = "UNIFEI – Universidade Federal de Itajubá"
GEMEC = "https://gemec.unifei.edu.br"

# Cores da marca (interface e relatorio)
MARINHO = "#0F2D4E"
AZUL = "#2563B8"
AZUL_CLARO = "#E4EDF9"
AMBAR = "#F2A51A"
FUNDO = "#F4F6F9"
CARTAO = "#FFFFFF"
BORDA = "#DDE3EA"
TINTA = "#15202E"
MUDO = "#5D6B7B"
SUBIU = "#1F7A4D"
DESCEU = "#B42318"

# Series dos graficos, sempre nesta ordem (paleta categorica validada para
# daltonismo em pares vizinhos; ate 5 series empilhadas, com legenda).
SERIES = ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#6250D6", "#008300", "#E34948"]

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA = os.path.join(AQUI, "marca")


def _geometria():
    """Partes da logo num quadrado de 100 x 100."""
    marcas = []
    for i in range(11):  # 270 graus, aberto embaixo
        ang = math.radians(135 + i * 27)
        r0 = 37 if i % 5 == 0 else 39.5
        marcas.append((50 + r0 * math.cos(ang), 50 + r0 * math.sin(ang), 50 + 43 * math.cos(ang), 50 + 43 * math.sin(ang), i % 5 == 0))
    barras = [(29.5, 79, 9, 11, "#7FAEE8"), (41.5, 79, 9, 18, "#B5D0F3"), (53.5, 79, 9, 26, "#FFFFFF")]
    ang = math.radians(-52)
    ponteiro = (47, 58, 47 + 33 * math.cos(ang), 58 + 33 * math.sin(ang))
    return marcas, barras, ponteiro


def logo_svg(tam=64):
    marcas, barras, (px0, py0, px1, py1) = _geometria()
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{tam}" height="{tam}" viewBox="0 0 100 100" role="img" aria-label="{NOME}">',
         f'<circle cx="50" cy="50" r="49" fill="{MARINHO}"/>']
    for x0, y0, x1, y1, maior in marcas:
        p.append(f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="#FFFFFF" stroke-opacity="{1 if maior else .55}" '
                 f'stroke-width="{3.2 if maior else 2}" stroke-linecap="round"/>')
    for x, base, w, h, cor in barras:
        p.append(f'<rect x="{x}" y="{base - h}" width="{w}" height="{h}" rx="2" fill="{cor}"/>')
    p.append(f'<line x1="{px0}" y1="{py0}" x2="{px1:.2f}" y2="{py1:.2f}" stroke="{AMBAR}" stroke-width="5" stroke-linecap="round"/>')
    p.append(f'<circle cx="{px0}" cy="{py0}" r="6" fill="{AMBAR}" stroke="{MARINHO}" stroke-width="2"/>')
    p.append("</svg>")
    return "".join(p)


def logo_imagem(tam, disco=MARINHO):
    """Logo em PIL.Image (desenhada grande e reduzida, para ficar lisa).
    disco=AZUL: variante para fundo escuro (o cabecalho da janela)."""
    from PIL import Image, ImageDraw
    k = 8
    S = 100 * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    marcas, barras, (px0, py0, px1, py1) = _geometria()
    d.ellipse((1 * k, 1 * k, 99 * k, 99 * k), fill=disco)
    for x0, y0, x1, y1, maior in marcas:
        cor = (255, 255, 255, 255 if maior else 140)
        lw = int((3.2 if maior else 2) * k)
        d.line((x0 * k, y0 * k, x1 * k, y1 * k), fill=cor, width=lw)
        for x, y in ((x0, y0), (x1, y1)):
            d.ellipse((x * k - lw / 2, y * k - lw / 2, x * k + lw / 2, y * k + lw / 2), fill=cor)
    for x, base, w, h, cor in barras:
        d.rounded_rectangle((x * k, (base - h) * k, (x + w) * k, base * k), radius=2 * k, fill=cor)
    lw = 5 * k
    d.line((px0 * k, py0 * k, px1 * k, py1 * k), fill=AMBAR, width=lw)
    d.ellipse((px1 * k - lw / 2, py1 * k - lw / 2, px1 * k + lw / 2, py1 * k + lw / 2), fill=AMBAR)
    d.ellipse(((px0 - 7) * k, (py0 - 7) * k, (px0 + 7) * k, (py0 + 7) * k), fill=disco)
    d.ellipse(((px0 - 6) * k, (py0 - 6) * k, (px0 + 6) * k, (py0 + 6) * k), fill=AMBAR)
    return img.resize((tam, tam), Image.LANCZOS)


def icone_imagem(tam):
    """Icone para tamanhos pequenos (barra de tarefas, atalhos): quadrado
    arredondado azul, arco branco grosso do mostrador, barras e o ponteiro
    ambar largo. Le bem de 16 a 256 px, em fundo claro ou escuro."""
    from PIL import Image, ImageDraw
    k = 8
    S = 100 * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * k, 2 * k, 98 * k, 98 * k), radius=22 * k, fill=AZUL)
    d.arc((16 * k, 16 * k, 84 * k, 84 * k), start=135, end=405, fill="#FFFFFF", width=9 * k)
    for x, h, cor in ((31, 14, "#A9C8F2"), (43, 22, "#D6E5FA"), (55, 30, "#FFFFFF")):
        d.rounded_rectangle((x * k, (78 - h) * k, (x + 9) * k, 78 * k), radius=2 * k, fill=cor)
    ang = math.radians(-50)
    px0, py0 = 47, 56
    px1, py1 = px0 + 30 * math.cos(ang), py0 + 30 * math.sin(ang)
    lw = 9 * k
    d.line((px0 * k, py0 * k, px1 * k, py1 * k), fill=AMBAR, width=lw)
    d.ellipse((px1 * k - lw / 2, py1 * k - lw / 2, px1 * k + lw / 2, py1 * k + lw / 2), fill=AMBAR)
    d.ellipse(((px0 - 9) * k, (py0 - 9) * k, (px0 + 9) * k, (py0 + 9) * k), fill=AZUL)
    d.ellipse(((px0 - 7) * k, (py0 - 7) * k, (px0 + 7) * k, (py0 + 7) * k), fill=AMBAR)
    return img.resize((tam, tam), Image.LANCZOS)


def gerar_arquivos():
    """marca/logo-*.png e marca/altimetro.ico (os PNG sao usados pela janela)."""
    os.makedirs(PASTA, exist_ok=True)
    for t in (32, 48, 64, 128, 256, 512):
        logo_imagem(t).save(os.path.join(PASTA, f"logo-{t}.png"))
    for t in (32, 48, 64):
        logo_imagem(t, AZUL).save(os.path.join(PASTA, f"logo-escuro-{t}.png"))
    for t in (32, 64, 256):
        icone_imagem(t).save(os.path.join(PASTA, f"icone-{t}.png"))
    # .ico com cada tamanho desenhado a parte (fica nitido no 16 e no 24)
    tams = [16, 24, 32, 48, 64, 128, 256]
    icone_imagem(256).save(os.path.join(PASTA, "altimetro.ico"), sizes=[(t, t) for t in tams],
                           append_images=[icone_imagem(t) for t in tams[:-1]])
    with open(os.path.join(PASTA, "logo.svg"), "w", encoding="utf-8") as f:
        f.write(logo_svg(512))


def arquivo(tam, escuro=False, icone=False):
    """Caminho do PNG da logo (ou do icone) no tamanho pedido (gera se faltar)."""
    c = os.path.join(PASTA, f"icone-{tam}.png" if icone else f"logo-{'escuro-' if escuro else ''}{tam}.png")
    if not os.path.exists(c):
        try:
            gerar_arquivos()
        except Exception:  # noqa: BLE001 - sem Pillow, a janela segue sem logo
            return None
    return c if os.path.exists(c) else None


if __name__ == "__main__":
    gerar_arquivos()
    print("Arquivos da marca gravados em", PASTA)
