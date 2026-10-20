"""Nucleo do Altimetro: grupos, download dos curriculos e scriptLattes, leitura
dos dados, metricas, tabelas, graficos, texto e Excel. A janela fica em
altimetro.py; o download e o scriptLattes rodam num processo separado
(altimetro.py --baixar / --gerar), para a janela nao travar.

Cada grupo fica em grupos/<nome>/: membros.json, cache/ (curriculos),
saida/ (o que o scriptLattes gera) e relatorios/ (relatorios salvos).
"""
import collections
import datetime
import glob
import io
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
import math

import marca

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPTLATTES = os.path.join(AQUI, "scriptLattes")
MODELO_CONFIG = os.path.join(AQUI, "scriptLattes.config.modelo")
GRUPOS = os.path.join(AQUI, "grupos")
PREFERENCIAS = os.path.join(AQUI, "preferencias.json")

CATEGORIAS = ["Docentes", "Pesquisadores", "Pós-doutorandos", "Doutorandos", "Mestrandos",
              "Graduandos", "Egressos", "Colaboradores externos"]


# ------------------------------------------------------------------ utilidades

def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def chave_texto(s, n=150):
    return re.sub(r"[^a-z0-9]+", "", norm(s))[:n]


def ano_int(x):
    m = re.search(r"(19|20)\d{2}", str(x if x is not None else ""))
    return int(m.group()) if m else None


def doi_de(x):
    m = re.search(r"10\.\d{4,9}/\S+", str(x or ""), re.I)
    return m.group().lower().rstrip(".,;") if m else ""


def num(n):
    return f"{n:,}".replace(",", ".")


def qt(n, sing, plur):
    return f"{num(n)} {sing if n == 1 else plur}"


def lista_pt(partes):
    partes = [p for p in partes if p]
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " e " + partes[-1]


def ler_texto(caminho):
    dados = open(caminho, "rb").read()
    for cod in ("utf-8", "cp1252"):
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            pass
    return dados.decode("latin-1")


def ler_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def gravar_json(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def abrir(caminho):
    """Abre um arquivo ou pasta no programa padrao (Windows, macOS ou Linux)."""
    if platform.system() == "Windows":
        os.startfile(caminho)  # noqa: S606
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", caminho])
    else:
        subprocess.Popen(["xdg-open", caminho])


FOTO_URL = "http://servicosweb.cnpq.br/wspessoa/servletrecuperafoto?tipo=1&id="


def id_foto(html):
    m = re.search(r"servletrecuperafoto\?tipo=1&(?:amp;)?id=(K\w+)", html)
    return m.group(1) if m else ""


def salvar_foto(dados, destino):
    """Grava a foto em JPEG quadrado (centro), 320 px. False se for a imagem padrao do Lattes."""
    from PIL import Image
    im = Image.open(io.BytesIO(dados)).convert("RGB")
    if min(im.size) < 120:
        return False
    lado = min(im.size)
    x, y = (im.width - lado) // 2, max(0, (im.height - lado) // 4)  # rosto costuma ficar no alto
    im = im.crop((x, y, x + lado, y + lado)).resize((320, 320), Image.LANCZOS)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    im.save(destino, "JPEG", quality=88)
    return True


def baixar_foto(g, lid, html=None):
    """Foto do Lattes do membro para fotos/<id>.jpg. Sem foto no Lattes: grava
    fotos/<id>.sem, para nao tentar de novo a cada atualizacao."""
    if html is None:
        html = ler_texto(g.cv(lid)) if os.path.exists(g.cv(lid)) else ""
    kid = id_foto(html)
    sem = os.path.join(g.fotos, lid + ".sem")
    if not kid:
        os.makedirs(g.fotos, exist_ok=True)
        open(sem, "w").close()
        return False
    req = urllib.request.Request(FOTO_URL + kid, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - endereco fixo do CNPq
        dados = r.read()
    try:
        ok = salvar_foto(dados, g.foto_arquivo(lid))
    except Exception:  # noqa: BLE001 - imagem invalida
        ok = False
    if not ok:
        os.makedirs(g.fotos, exist_ok=True)
        open(sem, "w").close()
    elif os.path.exists(sem):
        os.remove(sem)
    return ok


ORCID_RE = r"\d{4}-\d{4}-\d{4}-\d{3}[\dXx]"


def e_orcid(lid):
    """Membro cadastrado pelo ORCID (sem Lattes: dados do OpenAlex)."""
    return bool(re.fullmatch(ORCID_RE, str(lid or "")))


def link_perfil(lid):
    return f"https://orcid.org/{lid}" if e_orcid(lid) else f"http://lattes.cnpq.br/{lid}"


OPENALEX = "https://api.openalex.org"
AGENTE = "Altimetro (https://github.com/otaviozordan/altimetro-lattes)"


def _openalex(caminho, chave=None):
    if chave:
        caminho += ("&" if "?" in caminho else "?") + "api_key=" + urllib.parse.quote(chave)
    req = urllib.request.Request(OPENALEX + caminho, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310 - endereco fixo do OpenAlex
        return json.loads(r.read().decode("utf-8"))


def baixar_openalex(g, orcid, chave=None):
    """Autor e obras do OpenAlex pelo ORCID, gravados em openalex/<orcid>.json."""
    autor = _openalex(f"/authors/orcid:{orcid}", chave)
    obras = []
    campos = "title,publication_year,type,doi,primary_location,authorships"
    # Paginacao simples (page=): o cursor do OpenAlex exige chave a partir da 2a pagina.
    for pagina in range(1, 51):  # ate 10 mil obras
        d = _openalex(f"/works?filter=author.orcid:{orcid}&per-page=200&page={pagina}&select={campos}", chave)
        res = d.get("results") or []
        for w in res:
            fonte = (w.get("primary_location") or {}).get("source") or {}
            obras.append({"titulo": w.get("title") or "", "ano": w.get("publication_year"), "tipo": w.get("type") or "",
                          "fonte_tipo": fonte.get("type") or "", "veiculo": fonte.get("display_name") or "", "doi": doi_de(w.get("doi")),
                          "autores": "; ".join((a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or [])})
        if len(res) < 200:
            break
    dados = {"orcid": orcid, "nome": autor.get("display_name") or orcid, "openalex": autor.get("id", ""),
             "instituicao": ", ".join(i.get("display_name", "") for i in autor.get("last_known_institutions") or []),
             "temas": [t.get("display_name", "") for t in (autor.get("topics") or [])[:10]],
             "baixado": datetime.date.today().isoformat(), "obras": obras}
    os.makedirs(os.path.dirname(g.cv(orcid)), exist_ok=True)
    gravar_json(g.cv(orcid), dados)
    return dados


def itens_do_openalex(d):
    out = []
    for w in d.get("obras") or []:
        tipo, ft = w.get("tipo", ""), w.get("fonte_tipo", "")
        if tipo in ("paratext", "erratum", "retraction", "peer-review", "supplementary-materials"):
            continue
        if tipo == "book":
            cat = "livros"
        elif tipo == "book-chapter" or ft == "book series":
            cat = "capitulos"
        elif tipo == "dataset":
            cat = "tecnica"
        elif tipo in ("dissertation", "preprint", "report", "standard", "grant"):
            cat = "outras_bib"
        elif ft == "conference":
            cat = "completos"
        elif ft == "journal":
            cat = "artigos"
        else:
            cat = "outras_bib"
        out.append(Item(cat, ano_int(w.get("ano")), w.get("titulo"), w.get("autores"), w.get("veiculo"), w.get("doi") or "",
                        extra="Dataset" if cat == "tecnica" else ""))
    return out


def nome_no_cv(html):
    m = re.search(r'<h2 class="nome"[^>]*>\s*([^<]+)', html)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# ---------------------------------------------------------------------- grupo

class Grupo:
    """Uma pasta em grupos/: membros.json, cache/ (CVs) e saida/ (scriptLattes)."""

    def __init__(self, pasta):
        self.pasta = pasta
        self.arquivo = os.path.join(pasta, "membros.json")
        self.cache = os.path.join(pasta, "cache")
        self.saida = os.path.join(pasta, "saida")
        d = ler_json(self.arquivo, {})
        self.nome = d.get("nome") or os.path.basename(pasta)
        self.membros = d.get("membros", [])  # [{"id","nome","categoria","incluir"}]

    @staticmethod
    def criar(nome):
        base = re.sub(r"[^\w\- ]+", "", nome).strip() or "grupo"
        pasta, n = os.path.join(GRUPOS, base), 2
        while os.path.exists(pasta):
            pasta, n = os.path.join(GRUPOS, f"{base} {n}"), n + 1
        os.makedirs(pasta)
        g = Grupo(pasta)
        g.nome = nome
        g.salvar()
        return g

    @staticmethod
    def todos():
        os.makedirs(GRUPOS, exist_ok=True)
        return [Grupo(p) for p in sorted(glob.glob(os.path.join(GRUPOS, "*"))) if os.path.isdir(p)]

    def salvar(self):
        os.makedirs(self.pasta, exist_ok=True)
        gravar_json(self.arquivo, {"nome": self.nome, "membros": self.membros})

    def membro(self, lid):
        for m in self.membros:
            if m["id"] == lid:
                return m
        return None

    def cv(self, lid):
        if e_orcid(lid):
            return os.path.join(self.pasta, "openalex", lid + ".json")
        return os.path.join(self.cache, lid)

    def cv_data(self, lid):
        c = self.cv(lid)
        return datetime.date.fromtimestamp(os.path.getmtime(c)) if os.path.exists(c) else None

    @property
    def fotos(self):
        return os.path.join(self.pasta, "fotos")

    def foto_arquivo(self, lid):
        return os.path.join(self.fotos, lid + ".jpg")

    def foto(self, lid):
        c = self.foto_arquivo(lid)
        return c if os.path.exists(c) else None

    @property
    def relatorios(self):
        return os.path.join(self.pasta, "relatorios")

    def tem_scriptlattes(self):
        return os.path.exists(os.path.join(self.saida, "index.html"))

    def tem_relatorio(self):
        """Ha dados para as estatisticas (scriptLattes ou OpenAlex)."""
        return self.tem_scriptlattes() or bool(glob.glob(os.path.join(self.pasta, "openalex", "*.json")))


# ------------------------------------- download e scriptLattes (outro processo)

def avisar(*partes):
    print("@@", *partes, flush=True)


def cv_valido(html, lid):
    return "Curr" in html and lid in html and "captcha" not in html.lower()[:2000]


def cmd_baixar(pasta, so_faltam):
    """Baixa os CVs com o baixaLattes do scriptLattes (Chrome headless)."""
    g = Grupo(pasta)
    os.makedirs(g.cache, exist_ok=True)
    todos = [m for m in g.membros if not (so_faltam and os.path.exists(g.cv(m["id"])))]
    if not todos:
        avisar("fim", "ok", "Todos os currículos já estavam baixados.")
        return
    orcids = [m for m in todos if e_orcid(m["id"])]
    lista = [m for m in todos if not e_orcid(m["id"])]
    ok_o, falhas_o = 0, []
    chave = ler_json(PREFERENCIAS, {}).get("openalex_chave") or None
    for k, m in enumerate(orcids, 1):
        nome = m.get("nome") or m["id"]
        avisar("prog", k - 1, len(orcids), f"OpenAlex: {nome}")
        print(f"[ORCID {k}/{len(orcids)}] {nome}", flush=True)
        try:
            d = baixar_openalex(g, m["id"], chave)
        except Exception as e:  # noqa: BLE001
            falhas_o.append(nome)
            print("  falhou:", "ORCID não encontrado no OpenAlex" if "404" in str(e) else str(e)[:200], flush=True)
            continue
        ok_o += 1
        print(f"  {len(d['obras'])} obras", flush=True)
        if not m.get("nome") or m["nome"] == m["id"]:
            g2 = Grupo(pasta)
            mm = g2.membro(m["id"])
            if mm is not None:
                mm["nome"] = d["nome"]
                g2.salvar()
    if not lista:
        msg = f"{ok_o} de {len(orcids)} perfis do OpenAlex baixados." + (" Falharam: " + ", ".join(falhas_o) + "." if falhas_o else "")
        avisar("prog", 1, 1, msg)
        avisar("fim", "ok" if ok_o or not falhas_o else "erro", msg)
        return
    sys.path.insert(0, SCRIPTLATTES)
    from scriptLattes.baixaLattes import baixaCVLattes
    # Uma subpasta nova por CV: o baixaCVLattes pula o que ja existe no destino,
    # e no OneDrive apagar e recriar a mesma pasta costuma falhar.
    raiz = os.path.join(pasta, "_baixando")
    os.makedirs(raiz, exist_ok=True)
    ok, falhas = 0, []
    for k, m in enumerate(lista, 1):
        nome = m.get("nome") or m["id"]
        avisar("prog", k - 1, len(lista), "Baixando " + nome)
        print(f"[{k}/{len(lista)}] {nome}", flush=True)
        tmp = tempfile.mkdtemp(dir=raiz)
        try:
            baixaCVLattes(m["id"], tmp)
            html = ler_texto(os.path.join(tmp, m["id"]))
            if not cv_valido(html, m["id"]):
                raise ValueError("a página baixada não é o currículo")
        except Exception as e:  # noqa: BLE001 - um CV com problema nao para os outros
            falhas.append(nome)
            print("  falhou:", (str(e).splitlines() or [type(e).__name__])[0], flush=True)
            continue
        with open(g.cv(m["id"]), "w", encoding="utf-8") as f:
            f.write(html)
        ok += 1
        if not os.path.exists(os.path.join(g.fotos, m["id"] + ".usuario")):  # foto escolhida a mao fica
            try:
                baixar_foto(g, m["id"], html)
            except Exception as e:  # noqa: BLE001 - sem foto, segue
                print("  foto nao baixou:", type(e).__name__, flush=True)
        if not m.get("nome") or m["nome"] == m["id"]:
            g2 = Grupo(pasta)  # relido: a janela pode ter mudado algo enquanto isso
            mm = g2.membro(m["id"])
            if mm is not None:
                mm["nome"] = nome_no_cv(html) or mm.get("nome", "")
                g2.salvar()
    shutil.rmtree(raiz, ignore_errors=True)
    msg = f"{ok} de {len(lista)} currículos baixados."
    if orcids:
        msg += f" {ok_o} de {len(orcids)} perfis do OpenAlex."
    falhas += falhas_o
    if falhas:
        msg += " Falharam: " + ", ".join(falhas) + "."
    avisar("prog", len(lista), len(lista), msg)
    avisar("fim", "ok" if ok or not falhas else "erro", msg)


def cmd_gerar(pasta):
    """Roda o scriptLattes com os CVs que estao no cache."""
    g = Grupo(pasta)
    presentes = [m for m in g.membros if os.path.exists(g.cv(m["id"])) and not e_orcid(m["id"])]
    do_openalex = [m for m in g.membros if e_orcid(m["id"]) and os.path.exists(g.cv(m["id"]))]
    if not presentes:
        if do_openalex:
            if os.path.isdir(g.saida):
                shutil.rmtree(g.saida, ignore_errors=True)
            avisar("fim", "ok", f"Estatísticas com {len(do_openalex)} perfis do OpenAlex.")
        else:
            avisar("fim", "erro", "Nenhum currículo baixado ainda.")
        return
    faltam_fotos = [m for m in presentes if not g.foto(m["id"]) and not os.path.exists(os.path.join(g.fotos, m["id"] + ".sem"))]
    for k, m in enumerate(faltam_fotos, 1):
        avisar("prog", 0, 1, f"Buscando fotos do Lattes ({k}/{len(faltam_fotos)})…")
        try:
            baixar_foto(g, m["id"])
        except Exception as e:  # noqa: BLE001
            print("  foto nao baixou:", m.get("nome") or m["id"], type(e).__name__, flush=True)
    avisar("prog", 0, 1, f"Rodando o scriptLattes com {len(presentes)} currículos…")
    lista = os.path.join(pasta, "grupo.list")
    with open(lista, "w", encoding="utf-8") as f:
        for m in presentes:
            nome = (m.get("nome") or m["id"]).replace(",", " ")
            f.write(f"{m['id']} , {nome} , , {m.get('categoria') or 'Membros'}\n")
    termos = os.path.join(pasta, "termos.txt")
    open(termos, "a").close()
    if os.path.isdir(g.saida):
        shutil.rmtree(g.saida, ignore_errors=True)
    config = os.path.join(pasta, "grupo.config")
    with open(config, "w", encoding="utf-8") as f:
        f.write(open(MODELO_CONFIG, encoding="utf-8").read()
                .replace("{NOME}", g.nome).replace("{LISTA}", lista)
                .replace("{SAIDA}", g.saida + os.sep).replace("{CACHE}", g.cache + os.sep)
                .replace("{TERMOS}", termos).replace("{ANO}", str(datetime.date.today().year)))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.join(SCRIPTLATTES, "scriptLattes.py"), config],
                       cwd=SCRIPTLATTES, env=env, stdout=sys.stdout, stderr=subprocess.STDOUT)
    if r.returncode != 0 or not g.tem_scriptlattes():
        avisar("fim", "erro", "O scriptLattes falhou; veja o registro.")
        return
    # O nome completo vem do proprio CV: completa quem foi cadastrado so pelo ID.
    g2 = Grupo(pasta)
    for arq in glob.glob(os.path.join(g.saida, "json", "*.json")):
        info = ler_json(arq, {}).get("informacoes_pessoais", {})
        mm = g2.membro(str(info.get("id_lattes", "")))
        if mm is not None and info.get("nome_completo") and (not mm.get("nome") or mm["nome"] == mm["id"]):
            mm["nome"] = info["nome_completo"]
    g2.salvar()
    avisar("prog", 1, 1, "Relatório gerado.")
    avisar("fim", "ok", f"Estatísticas geradas com {len(presentes)} currículos" + (f" e {len(do_openalex)} perfis do OpenAlex." if do_openalex else "."))


# -------------------------------------------------------- leitura dos dados

GRUPOS_CAT = ["Produção bibliográfica", "Produção técnica", "Orientações concluídas",
              "Orientações em andamento", "Projetos", "Outras atividades"]

BIB = [
    ("artigos", "Artigos em periódicos", "artigos_periodicos", ("revista",)),
    ("aceitos", "Artigos aceitos para publicação", "artigos_aceitos", ("revista",)),
    ("livros", "Livros publicados", "livros_publicados", ("editora",)),
    ("capitulos", "Capítulos de livros", "capitulos_livros", ("titulo_livro", "editora")),
    ("completos", "Trabalhos completos em eventos", "trabalhos_completos_congressos", ("evento",)),
    ("expandidos", "Resumos expandidos em eventos", "resumos_expandidos", ("evento",)),
    ("resumos", "Resumos em eventos", "resumos_congressos", ("evento",)),
    ("apresentacoes", "Apresentações de trabalho", "apresentacoes_trabalhos", ("evento",)),
    ("jornais", "Textos em jornais e revistas", "textos_jornais", ("jornal", "revista", "veiculo")),
    ("outras_bib", "Outras produções bibliográficas", "outras_producoes", ("natureza", "editora")),
]
NIVEIS = [
    ("posdoc", "Pós-doutorado", "pos_doutorado"),
    ("doutorado", "Doutorado", "doutorado"),
    ("mestrado", "Mestrado", "mestrado"),
    ("especializacao", "Especialização", "especializacao"),
    ("tcc", "Trabalho de conclusão de curso", "tcc"),
    ("ic", "Iniciação científica", "iniciacao_cientifica"),
    ("outras", "Outras orientações", "outros"),
]

CATS = collections.OrderedDict()
for _k, _r, _j, _v in BIB:
    CATS[_k] = (_r, "Produção bibliográfica")
CATS["software"] = ("Softwares", "Produção técnica")
CATS["patentes"] = ("Patentes e registros", "Produção técnica")
CATS["tecnica"] = ("Outras produções técnicas", "Produção técnica")
CATS["artistica"] = ("Produção artística", "Produção técnica")
for _k, _r, _j in NIVEIS:
    CATS["oc_" + _k] = (_r, "Orientações concluídas")
for _k, _r, _j in NIVEIS:
    CATS["oa_" + _k] = (_r, "Orientações em andamento")
CATS["pj_pesquisa"] = ("Projetos de pesquisa", "Projetos")
CATS["pj_extensao"] = ("Projetos de extensão", "Projetos")
CATS["pj_desenvolvimento"] = ("Projetos de desenvolvimento", "Projetos")
CATS["pj_outros"] = ("Outros projetos", "Projetos")
CATS["premios"] = ("Prêmios e títulos", "Outras atividades")
CATS["bancas"] = ("Participações em bancas", "Outras atividades")
CATS["ev_part"] = ("Participações em eventos", "Outras atividades")
CATS["ev_org"] = ("Organização de eventos", "Outras atividades")

PRODUCAO = [k for k, (_r, gr) in CATS.items() if gr in ("Produção bibliográfica", "Produção técnica")]
OC = ["oc_" + k for k, _r, _j in NIVEIS]
OA = ["oa_" + k for k, _r, _j in NIVEIS]
PJ = ["pj_pesquisa", "pj_extensao", "pj_desenvolvimento", "pj_outros"]


class Item:
    __slots__ = ("cat", "ano", "fim", "titulo", "pessoas", "veiculo", "doi", "extra", "coord", "membros")

    def __init__(self, cat, ano, titulo, pessoas="", veiculo="", doi="", extra="", fim=None, coord=()):
        self.cat, self.ano, self.fim = cat, ano, fim
        self.titulo = re.sub(r"\s+", " ", str(titulo or "")).strip()
        self.pessoas = re.sub(r"\s+", " ", str(pessoas or "")).strip()
        self.veiculo = re.sub(r"\s+", " ", str(veiculo or "")).strip()
        self.doi, self.extra = doi, extra
        self.coord = set(coord)
        self.membros = set()

    def chave(self, dono):
        if self.cat in ("premios",):
            return (self.cat, dono, chave_texto(self.titulo))
        if self.cat.startswith(("oc_", "oa_")):
            return (self.cat, chave_texto(self.titulo, 100), chave_texto(self.pessoas, 40))
        if self.cat in PJ:
            return ("pj", chave_texto(self.titulo))
        if self.cat == "bancas":
            return (self.cat, chave_texto(self.pessoas, 40), self.ano, self.extra, chave_texto(self.titulo, 60) if not self.pessoas else "")
        if self.doi:
            return ("doi", self.doi)
        return (self.cat, chave_texto(self.titulo), self.ano)


def _primeiro(d, campos):
    for c in campos:
        if d.get(c):
            return d[c]
    return ""


def itens_do_json(d):
    out = []
    pb = d.get("producao_bibliografica") or {}
    for cat, _r, chave, campos in BIB:
        for x in pb.get(chave) or []:
            out.append(Item(cat, ano_int(x.get("ano")), x.get("titulo"), x.get("autores"), _primeiro(x, campos), doi_de(x.get("doi"))))
    pt = d.get("producao_tecnica") or {}
    for chave, lista in pt.items():
        cat = "software" if chave.startswith("softwares") else "tecnica"
        for x in lista or []:
            out.append(Item(cat, ano_int(x.get("ano")), x.get("titulo"), x.get("autores"), x.get("tipo", ""), extra=x.get("tipo", "")))
    for chave, lista in (d.get("patentes_registros") or {}).items():
        for x in lista or []:
            out.append(Item("patentes", ano_int(x.get("ano")), x.get("titulo"), x.get("autores"), extra=chave.replace("_", " ")))
    for x in d.get("producao_artistica") or []:
        out.append(Item("artistica", ano_int(x.get("ano")), x.get("titulo"), x.get("autores")))
    ori = d.get("orientacoes") or {}
    for k, _r, chave in NIVEIS:
        for x in (ori.get("concluidas") or {}).get(chave) or []:
            out.append(Item("oc_" + k, ano_int(x.get("ano_conclusao") or x.get("ano")), x.get("titulo"),
                            x.get("orientando"), x.get("instituicao"), extra=x.get("tipo_orientacao", "")))
        for x in (ori.get("em_andamento") or {}).get(chave) or []:
            out.append(Item("oa_" + k, ano_int(x.get("ano_inicio") or x.get("ano")), x.get("titulo"),
                            x.get("orientando"), x.get("instituicao")))
    for chave, lista in d.items():
        if not chave.startswith("projetos_") or not isinstance(lista, list):
            continue
        cat = {"projetos_pesquisa": "pj_pesquisa", "projetos_extensao": "pj_extensao",
               "projetos_desenvolvimento": "pj_desenvolvimento"}.get(chave, "pj_outros")
        for x in lista:
            fim = str(x.get("ano_conclusao") or "")
            integ = x.get("integrantes") or []
            coord = [i.get("nome", "") for i in integ if "coord" in norm(i.get("papel"))]
            out.append(Item(cat, ano_int(x.get("ano_inicio")), x.get("nome"), "; ".join(i.get("nome", "") for i in integ),
                            fim=None if not ano_int(fim) else ano_int(fim), coord=coord,
                            extra="Em andamento" if not ano_int(fim) else "Concluído"))
    for x in d.get("premios_titulos") or []:
        out.append(Item("premios", ano_int(x.get("ano")), x.get("descricao")))
    for _nivel, lista in (d.get("bancas") or {}).items():
        for x in lista or []:
            out.append(Item("bancas", ano_int(x.get("ano")), x.get("descricao"), x.get("aluno"), extra=x.get("tipo", "")))
    ev = d.get("eventos") or {}
    for x in ev.get("participacoes") or []:
        out.append(Item("ev_part", ano_int(x.get("ano")), x.get("apresentacao") or x.get("evento"), veiculo=x.get("evento"),
                        extra=x.get("tipo_evento", "")))
    for x in ev.get("organizacoes") or []:
        out.append(Item("ev_org", ano_int(x.get("ano")), x.get("evento") or x.get("autores"), extra=x.get("natureza", "")))
    return out


def _titulo_formacao(desc):
    m = re.search(r"T[íi]tulo:\s*(.+?)(?:,\s*Ano de|\.\s*Orientador|\s+O Portal|\.\s*Bolsista|$)", desc or "")
    return m.group(1).strip()[:220] if m else ""


def perfil_lattes(d):
    info = d.get("informacoes_pessoais") or {}
    lid = str(info.get("id_lattes") or "")
    form = []
    for f in d.get("formacao_academica") or []:
        anos = "–".join(x for x in (str(f.get("ano_inicio") or ""), str(f.get("ano_conclusao") or "")) if x)
        form.append({"tipo": f.get("tipo", ""), "instituicao": f.get("nome_instituicao", ""), "anos": anos,
                     "titulo": _titulo_formacao(f.get("descricao", ""))})
    areas = []
    for a in d.get("areas_de_atuacao") or []:
        x = " / ".join(v for v in (a.get("area"), a.get("subarea"), a.get("especialidade")) if v) if isinstance(a, dict) else str(a)
        if x and x not in areas:
            areas.append(x)
    return {"nome": info.get("nome_completo") or lid, "atualizado": info.get("atualizacao_cv", ""), "fonte": "Lattes",
            "resumo": info.get("texto_resumo", ""), "bolsa": info.get("bolsa_produtividade", ""),
            "endereco": info.get("endereco_profissional", ""), "formacao": form,
            "linhas": [x.get("nome", "") for x in d.get("linhas_de_pesquisa") or [] if x.get("nome")],
            "areas": areas, "idiomas": [f"{x.get('nome', '')}: {x.get('proficiencia_completa', '')}" for x in d.get("idiomas") or []],
            "link": link_perfil(lid)}


def perfil_openalex(d):
    data = d.get("baixado", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
        data = f"{data[8:10]}/{data[5:7]}/{data[:4]}"
    return {"nome": d.get("nome") or d.get("orcid"), "atualizado": data, "fonte": "OpenAlex (ORCID)",
            "resumo": "", "bolsa": "", "endereco": d.get("instituicao", ""), "formacao": [], "linhas": d.get("temas") or [],
            "areas": [], "idiomas": [], "link": link_perfil(d.get("orcid")), "openalex": d.get("openalex", "")}


class Base:
    """Itens do grupo inteiro, sem repeticao: o mesmo trabalho no CV de dois
    membros conta uma vez para o grupo (e uma vez para cada um deles)."""

    def __init__(self, grupo):
        self.grupo = grupo
        self.pessoas = {}   # id -> {"nome","atualizado"}
        self.itens = []
        unidos = {}
        for arq in sorted(glob.glob(os.path.join(grupo.saida, "json", "*.json"))):
            d = ler_json(arq, None)
            if not d:
                continue
            info = d.get("informacoes_pessoais") or {}
            lid = str(info.get("id_lattes") or "")
            if not lid:
                continue
            self.pessoas[lid] = perfil_lattes(d)
            self._juntar(lid, itens_do_json(d), unidos)
        for m in grupo.membros:
            if e_orcid(m["id"]) and os.path.exists(grupo.cv(m["id"])):
                d = ler_json(grupo.cv(m["id"]), None)
                if d:
                    self.pessoas[m["id"]] = perfil_openalex(d)
                    self._juntar(m["id"], itens_do_openalex(d), unidos)
        self.itens = list(unidos.values())
        anos = [it.ano for it in self.itens if it.ano]
        self.ano_min = min(anos) if anos else datetime.date.today().year
        self.ano_max = max(max(anos) if anos else 0, datetime.date.today().year)

    @staticmethod
    def _juntar(lid, itens, unidos):
        for it in itens:
            if not it.titulo:
                continue
            k = it.chave(lid)
            if k in unidos:
                velho = unidos[k]
                velho.membros.add(lid)
                velho.coord |= it.coord
                if not velho.ano and it.ano:
                    velho.ano = it.ano
            else:
                it.membros.add(lid)
                unidos[k] = it


# ----------------------------------------------------------------- calculo

class Estat:
    def __init__(self, base, sel, a, b):
        self.a, self.b, self.sel = a, b, set(sel)
        self.grupo = base.grupo
        self.anos = list(range(a, b + 1))
        nomes_sel = {norm(base.pessoas[i]["nome"]) for i in sel if i in base.pessoas}
        self.itens = []
        for it in base.itens:
            quem = it.membros & self.sel
            if not quem or not self._no_periodo(it):
                continue
            self.itens.append((it, quem))
        self.n = collections.Counter(it.cat for it, _q in self.itens)
        self.por_ano = collections.defaultdict(collections.Counter)
        for it, _q in self.itens:
            if it.cat in PJ:
                for y in self.anos:
                    if (it.ano or a) <= y and (it.fim is None or it.fim >= y):
                        self.por_ano["pj_ativos"][y] += 1
            elif not it.cat.startswith("oa_") and it.ano:
                self.por_ano[it.cat][it.ano] += 1
        self.coordenados = sum(1 for it, _q in self.itens if it.cat in PJ and {norm(c) for c in it.coord} & nomes_sel)
        artigos = [q for it, q in self.itens if it.cat == "artigos"]
        self.artigos_parceria = sum(1 for q in artigos if len(q) >= 2)
        self.por_membro = collections.defaultdict(collections.Counter)
        for it, quem in self.itens:
            for p in quem:
                self.por_membro[p][it.cat] += 1
        self.artigos_doi = sum(1 for it, _q in self.itens if it.cat == "artigos" and it.doi)
        self.anterior = None
        # Coautoria dentro do grupo: pares de membros que dividem um trabalho.
        self.pares = collections.Counter()
        for it, quem in self.itens:
            if it.cat in PRODUCAO and len(quem) >= 2:
                q = sorted(quem)
                for i in range(len(q)):
                    for j in range(i + 1, len(q)):
                        self.pares[(q[i], q[j])] += 1

    def _no_periodo(self, it):
        if it.cat.startswith("oa_"):
            return it.ano is None or it.ano <= self.b
        if it.cat in PJ:
            return (it.ano is None or it.ano <= self.b) and (it.fim is None or it.fim >= self.a)
        return it.ano is not None and self.a <= it.ano <= self.b

    def soma(self, cats):
        return sum(self.n[c] for c in cats)

    def de(self, cats):
        cats = set(cats)
        return [(it, q) for it, q in self.itens if it.cat in cats]


def itens_filtro(est, f):
    """Os itens a que uma barra do grafico se refere. f: {"cats", "ano", "inicio",
    "ativo_em", "membro", "veiculo", "extra", "categoria_membro", "par"}."""
    cats = set(f.get("cats") or [])
    out = []
    for it, quem in est.itens:
        if cats and it.cat not in cats:
            continue
        if "ano" in f and it.ano != f["ano"]:
            continue
        if "inicio" in f and it.ano != f["inicio"]:
            continue
        if "ativo_em" in f and not ((it.ano or est.a) <= f["ativo_em"] and (it.fim is None or it.fim >= f["ativo_em"])):
            continue
        if "membro" in f and f["membro"] not in quem:
            continue
        if "par" in f and not set(f["par"]) <= quem:
            continue
        if "veiculo" in f and chave_texto(it.veiculo, 200) != f["veiculo"]:
            continue
        if "extra" in f and (it.extra or "Sem tipo") != f["extra"]:
            continue
        if "categoria_membro" in f and not any(((est.grupo.membro(p) or {}).get("categoria") or "Sem categoria") == f["categoria_membro"] for p in quem):
            continue
        out.append((it, quem))
    out.sort(key=lambda x: (-(x[0].ano or 0), list(CATS).index(x[0].cat) if x[0].cat in CATS else 99, norm(x[0].titulo)))
    return out


def tabela_de(est, base, itens):
    cab = ["Tipo", "Ano", "Título", "Autores / pessoas", "Veículo", "DOI", "Membros do grupo"]
    return cab, [[rotulo(it.cat), it.ano or "", it.titulo, it.pessoas, it.veiculo, it.doi,
                  "; ".join(sorted(base.pessoas[p]["nome"] for p in q if p in base.pessoas))] for it, q in itens]


def rotulo(cat):
    return CATS[cat][0] if cat in CATS else cat


def veiculos(est, cats, limite=None):
    cont, nomes = collections.Counter(), collections.defaultdict(collections.Counter)
    for it, _q in est.de(cats):
        if it.veiculo:
            k = chave_texto(it.veiculo, 200)
            cont[k] += 1
            nomes[k][it.veiculo] += 1
    return [(nomes[k].most_common(1)[0][0], n) for k, n in cont.most_common(limite)]


# -------------------------------------------------------------- metricas

BIB_CATS = [k for k, _r, _j, _v in BIB]
DOCENTE = ("docente", "docentes", "professor", "professores", "professora", "professoras")


def com_anterior(base, sel, a, b):
    """Estatisticas do periodo e, em .anterior, as do periodo de mesma duracao logo antes."""
    est = Estat(base, sel, a, b)
    n = b - a + 1
    if a - n >= base.ano_min - 1:
        est.anterior = Estat(base, sel, a - n, a - 1)
    return est


def docentes(est, grupo):
    return [i for i in est.sel if norm((grupo.membro(i) or {}).get("categoria")) in DOCENTE]


def variacao(atual, antes):
    if not antes:
        return None
    return round(100 * (atual - antes) / antes)


def _dec(x, casas=1):
    return f"{x:.{casas}f}".replace(".", ",")


def indicadores(est, base, grupo):
    """[(nome, valor, detalhe)] das metricas do periodo."""
    anos = est.b - est.a + 1
    doc = docentes(est, grupo)
    nd = len(doc) or len(est.sel) or 1
    quem = "docente" if doc else "membro"
    bib = est.soma(BIB_CATS)
    ativos = sum(1 for i in est.sel if any(est.por_membro.get(i, {}).get(c) for c in BIB_CATS))
    n_art = est.n["artigos"]
    out = [
        ("Produção bibliográfica", num(bib), f"{_dec(bib / anos)} por ano"),
        ("Artigos em periódicos por ano", _dec(n_art / anos), f"{num(n_art)} no período"),
        (f"Artigos por {quem} por ano", _dec(n_art / nd / anos, 2),
         qt(len(doc), "membro na categoria Docentes", "membros na categoria Docentes") if doc else "não há membros na categoria Docentes"),
        (f"Orientações concluídas por {quem}", _dec(est.soma(OC) / nd), f"{num(est.soma(OC))} no período"),
        ("Colaboração interna", f"{round(100 * est.artigos_parceria / n_art)}%" if n_art else "–", "artigos com 2 ou mais membros do grupo"),
        ("Artigos com DOI", f"{round(100 * est.artigos_doi / n_art)}%" if n_art else "–", f"{num(est.artigos_doi)} artigos"),
        ("Membros com produção", f"{ativos} de {len(est.sel)}", "ao menos um item bibliográfico no período"),
        ("Periódicos distintos", num(len(veiculos(est, ["artigos"]))), "onde saíram os artigos"),
        ("Projetos coordenados pelo grupo", num(est.coordenados), f"de {num(est.soma(PJ))} projetos ativos"),
        ("Parcerias internas", num(len(est.pares)), "pares de membros com trabalho em comum"),
    ]
    ant = est.anterior
    if ant is not None:
        for nome, x, y in (("Artigos no período anterior", n_art, ant.n["artigos"]),
                           ("Produção bibliográfica no período anterior", bib, ant.soma(BIB_CATS)),
                           ("Orientações concluídas no período anterior", est.soma(OC), ant.soma(OC))):
            v = variacao(x, y)
            out.append((nome, num(y), f"{ant.a}–{ant.b}" + ("" if v is None else f" · variação de {'+' if v >= 0 else ''}{v}%")))
    return out


def tabela_indicadores(est, base, grupo):
    return ["Indicador", "Valor", "Detalhe"], [list(x) for x in indicadores(est, base, grupo)]


# -------------------------------------------------------------- graficos

# ------------------------------------------------------------- ficha

def ficha(est, base, grupo, lid):
    """Pagina do membro: perfil, numeros do periodo, producao por ano, parcerias e listas."""
    c = est.por_membro.get(lid, collections.Counter())
    anos = est.anos
    meus = [(it, q) for it, q in est.itens if lid in q]

    def serie(cats):
        cont = collections.Counter(it.ano for it, _q in meus if it.cat in cats and it.ano)
        return [cont.get(y, 0) for y in anos]
    ev = ["completos", "expandidos", "resumos"]
    outros = [k for k in BIB_CATS if k not in ev and k != "artigos"]
    spec = {"tipo": "colunas", "titulo": "Produção bibliográfica por ano", "categorias": anos, "series": [
        ("Artigos em periódicos", serie(["artigos"])), ("Trabalhos em eventos", serie(ev)), ("Outros", serie(outros))],
        "filtros": [{"cats": ["artigos"], "membro": lid}, {"cats": ev, "membro": lid}, {"cats": outros, "membro": lid}]}
    parceiros = collections.Counter()
    for (a, b), p in est.pares.items():
        if lid in (a, b):
            parceiros[b if a == lid else a] += p
    m = grupo.membro(lid) or {}
    perfil = dict(base.pessoas.get(lid) or {"nome": m.get("nome") or lid, "atualizado": "", "fonte": "", "link": link_perfil(lid)})
    listas = [
        ("Publicações", "Artigos, livros, capítulos e outras publicações", ["artigos", "aceitos", "livros", "capitulos", "jornais", "outras_bib"]),
        ("Eventos", "Trabalhos e resumos em eventos, apresentações, participações e organização", ev + ["apresentacoes", "ev_part", "ev_org"]),
        ("Orientações", "Concluídas no período e em andamento", OC + OA),
        ("Projetos", "Ativos no período", PJ),
        ("Outros", "Produção técnica e artística, prêmios e bancas", ["software", "patentes", "tecnica", "artistica", "premios", "bancas"]),
    ]
    return {
        "id": lid, "nome": perfil.get("nome") or lid, "categoria": m.get("categoria", ""), "perfil": perfil,
        "numeros": [("Artigos", c["artigos"], "Publicações"), ("Trabalhos em eventos", c["completos"] + c["expandidos"] + c["resumos"], "Eventos"),
                    ("Livros e capítulos", c["livros"] + c["capitulos"], "Publicações"), ("Orient. concluídas", sum(c[k] for k in OC), "Orientações"),
                    ("Orient. em andamento", sum(c[k] for k in OA), "Orientações"), ("Projetos", sum(c[k] for k in PJ), "Projetos")],
        "grafico": spec,
        "parceiros": [(base.pessoas.get(i, {}).get("nome", i), p, i) for i, p in parceiros.most_common(15)],
        "listas": [(t, sub, [(it, q) for it, q in meus if it.cat in set(cats)]) for t, sub, cats in listas],
    }


def iniciais(nome):
    partes = [x for x in re.split(r"\s+", str(nome or "").strip()) if x and x.lower() not in ("de", "da", "do", "dos", "das", "e")]
    return ((partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")) if partes else "?").upper()


def veiculos_k(est, cats, limite=None):
    """Como veiculos(), com a chave usada pelo filtro do clique."""
    cont, nomes = collections.Counter(), collections.defaultdict(collections.Counter)
    for it, _q in est.de(cats):
        if it.veiculo:
            k = chave_texto(it.veiculo, 200)
            cont[k] += 1
            nomes[k][it.veiculo] += 1
    return [(nomes[k].most_common(1)[0][0], n, k) for k, n in cont.most_common(limite)]


def _curto(nome):
    p = str(nome).split()
    return " ".join(p[:1] + p[-1:]) if len(p) > 1 else str(nome)


SECOES_GRAFICOS = ["Publicações", "Orientações", "Projetos", "Produção técnica e artística", "Eventos",
                   "Prêmios e bancas", "Membros", "Colaboração"]
TEC = ["software", "patentes", "tecnica", "artistica"]


def graficos(est, base, grupo):
    """[(secao, chave, titulo, spec)] nas secoes da pagina Estatisticas do GEMEC.
    Cada barra sabe a que itens se refere: spec["filtros"] (um por serie das
    colunas; o ano entra no clique) ou spec["refs"] (um por barra), lidos por
    itens_filtro(). {"membro_ficha": id} abre a ficha e {"composicao": c}, a
    lista de pessoas da categoria."""
    anos = est.anos
    pa = est.por_ano

    def serie(cats):
        return [sum(pa.get(c, {}).get(y, 0) for c in cats) for y in anos]

    def colunas(series, filtros=None):
        return {"tipo": "colunas", "categorias": anos, "series": [(nome, serie(c)) for nome, c in series],
                "filtros": filtros or [{"cats": list(c)} for _n, c in series]}

    def barras(trios, cor=None):
        spec = {"tipo": "barras", "rotulos": [t[0] for t in trios], "valores": [t[1] for t in trios], "refs": [t[2] for t in trios]}
        if cor:
            spec["cor"] = cor
        return spec

    def nome(i):
        return base.pessoas.get(i, {}).get("nome", i)

    ev = ["completos", "expandidos", "resumos"]
    out = []

    S = "Publicações"
    out.append((S, "producao", "Produção bibliográfica por ano", colunas([
        ("Artigos em periódicos", ["artigos"]), ("Trabalhos em eventos", ev), ("Livros e capítulos", ["livros", "capitulos"]),
        ("Outros", ["aceitos", "jornais", "outras_bib", "apresentacoes"])])))
    out.append((S, "artigos", "Artigos em periódicos por ano", colunas([("Artigos", ["artigos"])])))
    por = sorted(((nome(i), est.por_membro.get(i, {}).get("artigos", 0), i) for i in est.sel if i in base.pessoas), key=lambda x: (-x[1], norm(x[0])))
    out.append((S, "membros", "Artigos por membro (15 primeiros)", barras([(n, v, {"cats": ["artigos"], "membro": i}) for n, v, i in por if v][:15])))
    out.append((S, "periodicos", "Periódicos mais frequentes", barras([(v, n, {"cats": ["artigos", "aceitos"], "veiculo": k})
                                                                      for v, n, k in veiculos_k(est, ["artigos", "aceitos"], 12)])))
    tipos = sorted([(rotulo(c), est.n[c], {"cats": [c]}) for c in BIB_CATS if est.n[c]], key=lambda x: -x[1])
    out.append((S, "tipos", "Produção bibliográfica por tipo", barras(tipos)))

    S = "Orientações"
    out.append((S, "orient_nivel", "Orientações concluídas por nível", barras(
        [(r, est.n["oc_" + k], {"cats": ["oc_" + k]}) for k, r, _j in NIVEIS if est.n["oc_" + k]])))
    out.append((S, "orientacoes", "Orientações concluídas por ano", colunas([
        ("Doutorado", ["oc_doutorado"]), ("Mestrado", ["oc_mestrado"]), ("Iniciação científica", ["oc_ic"]), ("TCC", ["oc_tcc"]),
        ("Outras", ["oc_posdoc", "oc_especializacao", "oc_outras"])])))
    out.append((S, "andamento_nivel", "Orientações em andamento por nível", barras(
        [(r, est.n["oa_" + k], {"cats": ["oa_" + k]}) for k, r, _j in NIVEIS if est.n["oa_" + k]], marca.SERIES[1])))

    S = "Projetos"
    inicio = collections.defaultdict(collections.Counter)
    for it, _q in est.de(PJ):
        if it.ano:
            inicio[it.cat][it.ano] += 1
    nat = [("Pesquisa", "pj_pesquisa"), ("Extensão", "pj_extensao"), ("Desenvolvimento", "pj_desenvolvimento"), ("Outros", "pj_outros")]
    out.append((S, "proj_inicio", "Projetos iniciados por ano", {
        "tipo": "colunas", "categorias": anos, "series": [(n, [inicio[c].get(y, 0) for y in anos]) for n, c in nat],
        "filtros": [{"cats": [c]} for _n, c in nat]}))
    out.append((S, "projetos", "Projetos ativos por ano", colunas([("Projetos ativos", ["pj_ativos"])], [{"cats": PJ, "_ano": "ativo_em"}])))

    S = "Produção técnica e artística"
    tipos = collections.Counter()
    for it, _q in est.de(TEC):
        tipos[(it.cat, it.extra or "")] += 1
    out.append((S, "tec_tipo", "Produção técnica e artística por tipo", barras(
        [(x or rotulo(c), v, {"cats": [c], "extra": x or "Sem tipo"}) for (c, x), v in tipos.most_common(15)], marca.SERIES[2])))
    out.append((S, "tecnica", "Produção técnica e artística por ano", colunas([
        ("Softwares", ["software"]), ("Patentes e registros", ["patentes"]), ("Outras técnicas", ["tecnica"]), ("Artística", ["artistica"])])))

    S = "Eventos"
    out.append((S, "eventos_ano", "Eventos por ano", colunas([
        ("Trabalhos completos", ["completos"]), ("Resumos", ["expandidos", "resumos"]), ("Participações", ["ev_part"]),
        ("Organização", ["ev_org"])])))
    tipos = collections.Counter(it.extra or "Sem tipo" for it, _q in est.de(["ev_part"]))
    out.append((S, "ev_tipo", "Participações por tipo de evento", barras(
        [(x, v, {"cats": ["ev_part"], "extra": x}) for x, v in tipos.most_common(12)], marca.SERIES[3])))
    out.append((S, "eventos", "Eventos mais frequentes (trabalhos publicados)", barras(
        [(v, n, {"cats": ev, "veiculo": k}) for v, n, k in veiculos_k(est, ev, 12)])))

    S = "Prêmios e bancas"
    out.append((S, "premios", "Prêmios e títulos por ano", colunas([("Prêmios e títulos", ["premios"])])))
    out.append((S, "bancas", "Participações em bancas por ano", colunas([("Bancas", ["bancas"])])))

    S = "Membros"
    cats = collections.Counter()
    for _it, quem in est.de(BIB_CATS):
        for c in {(grupo.membro(p) or {}).get("categoria") or "Sem categoria" for p in quem}:
            cats[c] += 1
    out.append((S, "categorias", "Produção bibliográfica por categoria de membro", barras(
        [(c, v, {"cats": BIB_CATS, "categoria_membro": c}) for c, v in cats.most_common()])))
    comp = collections.Counter((grupo.membro(i) or {}).get("categoria") or "Sem categoria" for i in est.sel)
    out.append((S, "composicao", "Composição do grupo", barras([(c, v, {"composicao": c}) for c, v in comp.most_common()], marca.SERIES[2])))

    S = "Colaboração"
    out.append((S, "rede", "Rede de colaboração entre os membros", rede(est, base, grupo)))
    out.append((S, "parcerias", "Parcerias mais frequentes", barras(
        [(f"{_curto(nome(a))} × {_curto(nome(b))}", v, {"cats": PRODUCAO, "par": [a, b]}) for (a, b), v in est.pares.most_common(12)])))
    grau = collections.Counter()
    for (a, b), v in est.pares.items():
        grau[a] += 1
        grau[b] += 1
    out.append((S, "conectados", "Membros mais conectados (nº de parceiros no grupo)", barras(
        [(nome(i), v, {"membro_ficha": i}) for i, v in grau.most_common(15)], marca.SERIES[6])))

    for _s, _k, titulo, spec in out:
        spec["titulo"] = titulo
    return out


def posicoes(pares):
    """Posicoes (0..1) dos membros na rede. Cada parte desconectada e arrumada
    a parte: a maior ocupa a area principal, as menores ficam numa coluna a
    direita (o spring_layout de tudo junto joga as partes pequenas para longe)."""
    try:
        import networkx as nx
    except ImportError:
        nos = sorted({i for p in pares for i in p})
        return {i: (0.5 + 0.5 * math.cos(2 * math.pi * k / len(nos)), 0.5 + 0.5 * math.sin(2 * math.pi * k / len(nos))) for k, i in enumerate(nos)}
    g = nx.Graph()
    for (a, b), p in pares.items():
        g.add_edge(a, b, weight=p)
    if not len(g):
        return {}
    partes = sorted(nx.connected_components(g), key=len, reverse=True)

    def arrumar(nos, x0, y0, x1, y1):
        sub = g.subgraph(nos)
        if len(nos) == 1:
            return {next(iter(nos)): ((x0 + x1) / 2, (y0 + y1) / 2)}
        if len(nos) == 2:
            a, b = sorted(nos)
            return {a: (x0 + (x1 - x0) * 0.25, (y0 + y1) / 2), b: (x0 + (x1 - x0) * 0.75, (y0 + y1) / 2)}
        try:
            bruto = nx.kamada_kawai_layout(sub, weight=None)
        except Exception:  # noqa: BLE001 - sem scipy
            bruto = nx.spring_layout(sub, seed=7, iterations=200)
        xs = [float(p[0]) for p in bruto.values()]
        ys = [float(p[1]) for p in bruto.values()]
        dx, dy = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
        return {i: (x0 + (float(p[0]) - min(xs)) / dx * (x1 - x0), y0 + (float(p[1]) - min(ys)) / dy * (y1 - y0)) for i, p in bruto.items()}

    pos = {}
    if len(partes) == 1:
        return arrumar(partes[0], 0, 0, 1, 1)
    pos.update(arrumar(partes[0], 0, 0, 0.74, 1))
    resto = partes[1:]
    alt = 1 / len(resto)
    for k, parte in enumerate(resto):
        pos.update(arrumar(parte, 0.82, k * alt + alt * 0.15, 1, (k + 1) * alt - alt * 0.15))
    return pos


def rede(est, base, grupo):
    """Coautoria no grupo: no = membro (tamanho = producao), aresta = trabalhos em comum."""
    nos_ids = {i for par in est.pares for i in par}
    prod = {i: sum(est.por_membro.get(i, {}).get(c, 0) for c in PRODUCAO) for i in est.sel}
    cats = collections.Counter((grupo.membro(i) or {}).get("categoria") or "Sem categoria" for i in nos_ids)
    grupos = [c for c, _n in cats.most_common()]
    if len(grupos) > 6:  # mais de 6 cores nao se distinguem: o resto vira "Outras"
        grupos = grupos[:5] + ["Outras"]
    pos = posicoes(est.pares)

    def grupo_de(i):
        c = (grupo.membro(i) or {}).get("categoria") or "Sem categoria"
        return c if c in grupos else "Outras"
    nos = [(i, base.pessoas.get(i, {}).get("nome", i), prod.get(i, 0), grupo_de(i)) for i in nos_ids]
    return {"tipo": "rede", "nos": nos, "arestas": [(a, b, p) for (a, b), p in est.pares.items()], "pos": pos, "grupos": grupos}


# ------------------------------------------------- tabelas (tela e Excel)

def tabela_por_ano(est):
    cab = ["Indicador"] + [str(y) for y in est.anos] + ["Total"]
    linhas = []
    for cat in [c for c in CATS if c not in OA and c not in PJ]:
        cont = est.por_ano.get(cat)
        if cont and sum(cont.values()):
            linhas.append([rotulo(cat) + (" (concluídas)" if cat in OC else "")] + [cont.get(y, 0) for y in est.anos] + [sum(cont.values())])
    pj = est.por_ano.get("pj_ativos")
    if pj:
        linhas.append(["Projetos ativos no ano"] + [pj.get(y, 0) for y in est.anos] + [est.soma(PJ)])
    return cab, linhas


def tabela_por_membro(est, base, grupo):
    cab = ["Membro", "Categoria", "Artigos", "Eventos (completos)", "Livros e capítulos", "Produção técnica",
           "Orient. concluídas", "Orient. em andamento", "Projetos", "Prêmios", "Bancas", "CV atualizado em"]
    linhas = []
    for lid in est.sel:
        if lid not in base.pessoas:
            continue
        c = est.por_membro.get(lid, collections.Counter())
        m = grupo.membro(lid) or {}
        linhas.append([base.pessoas[lid]["nome"], m.get("categoria", ""), c["artigos"], c["completos"],
                       c["livros"] + c["capitulos"], c["software"] + c["patentes"] + c["tecnica"],
                       sum(c[k] for k in OC), sum(c[k] for k in OA), sum(c[k] for k in PJ), c["premios"], c["bancas"],
                       base.pessoas[lid]["atualizado"]])
    linhas.sort(key=lambda r: (-r[2], -r[3], norm(r[0])))
    return cab, linhas


def tabela_orientacoes_resumo(est):
    cab = ["Nível", "Concluídas no período", "Em andamento"]
    linhas = [[r, est.n["oc_" + k], est.n["oa_" + k]] for k, r, _j in NIVEIS]
    linhas.append(["Total", est.soma(OC), est.soma(OA)])
    return cab, linhas


def tabela_orientacoes(est, base):
    cab = ["Situação", "Nível", "Ano", "Orientando", "Título", "Orientador(es) do grupo"]
    linhas = []
    for it, q in est.de(OC + OA):
        linhas.append(["Concluída" if it.cat in OC else "Em andamento", rotulo(it.cat), it.ano or "", it.pessoas, it.titulo,
                       "; ".join(sorted(base.pessoas[p]["nome"] for p in q))])
    linhas.sort(key=lambda r: (r[0] != "Em andamento", -(r[2] or 0), r[1]))
    return cab, linhas


def tabela_projetos(est, base):
    cab = ["Natureza", "Início", "Fim", "Projeto", "Coordenação", "Membros do grupo"]
    linhas = []
    for it, q in est.de(PJ):
        linhas.append([rotulo(it.cat).replace("Projetos de ", "").replace("Outros projetos", "outra").capitalize(), it.ano or "",
                       it.fim or "atual", it.titulo, "; ".join(sorted(it.coord)), "; ".join(sorted(base.pessoas[p]["nome"] for p in q))])
    linhas.sort(key=lambda r: (r[2] != "atual", -(r[1] or 0), norm(r[3])))
    return cab, linhas


def tabela_veiculos(est):
    cab = ["Tipo", "Periódico ou evento", "Trabalhos"]
    linhas = [["Periódico", v, n] for v, n in veiculos(est, ["artigos", "aceitos"])]
    linhas += [["Evento", v, n] for v, n in veiculos(est, ["completos", "expandidos", "resumos"])]
    return cab, linhas


def tabela_itens(est, base, cats=None, busca=""):
    cab = ["Tipo", "Ano", "Título", "Autores / pessoas", "Veículo", "DOI", "Membros do grupo"]
    termos = norm(busca).split()
    linhas = []
    for it, q in est.itens:
        if cats and it.cat not in cats:
            continue
        nomes = "; ".join(sorted(base.pessoas[p]["nome"] for p in q))
        if termos:
            alvo = norm(" ".join((it.titulo, it.pessoas, it.veiculo, it.doi, nomes)))
            if not all(t in alvo for t in termos):
                continue
        linhas.append([rotulo(it.cat), it.ano or "", it.titulo, it.pessoas, it.veiculo, it.doi, nomes])
    linhas.sort(key=lambda r: (-(r[1] or 0), list(CATS).index(next(k for k in CATS if CATS[k][0] == r[0])), norm(r[2])))
    return cab, linhas


def texto_relatorio(est, grupo, base):
    a, b = est.a, est.b
    per = f"em {a}" if a == b else f"de {a} a {b}"
    n_memb = len([i for i in est.sel if i in base.pessoas])
    cats = collections.Counter((grupo.membro(i) or {}).get("categoria") or "Sem categoria" for i in est.sel if i in base.pessoas)
    comp = lista_pt([f"{n} {c.lower()}" for c, n in cats.most_common()])
    p = []
    p.append(f"Este levantamento considera {qt(n_memb, 'membro', 'membros')} do grupo {grupo.nome}" + (f" ({comp})" if comp else "")
             + f" e o período {per}, com base nos Currículos Lattes. Trabalhos que aparecem no currículo de mais de um membro foram contados uma única vez.")

    bib = []
    for cat, sing, plur in (("artigos", "artigo em periódico", "artigos em periódicos"),
                            ("aceitos", "artigo aceito para publicação", "artigos aceitos para publicação"),
                            ("livros", "livro", "livros"), ("capitulos", "capítulo de livro", "capítulos de livros"),
                            ("completos", "trabalho completo em anais de eventos", "trabalhos completos em anais de eventos"),
                            ("expandidos", "resumo expandido", "resumos expandidos"), ("resumos", "resumo em eventos", "resumos em eventos")):
        if est.n[cat]:
            bib.append(qt(est.n[cat], sing, plur))
    if bib:
        t = f"No período, o grupo publicou {lista_pt(bib)}."
        if est.n["artigos"] >= 2:
            pct = round(100 * est.artigos_parceria / est.n["artigos"])
            t += f" Dos artigos em periódicos, {num(est.artigos_parceria)} ({pct}%) têm dois ou mais membros do grupo entre os autores."
        top = veiculos(est, ["artigos"], 3)
        if top and est.n["artigos"] >= 5:
            t += " Os periódicos mais frequentes foram " + lista_pt([f"{v} ({n})" for v, n in top]) + "."
        p.append(t)
    else:
        p.append("Não há produção bibliográfica registrada no período.")

    ant = est.anterior
    if ant is not None and ant.n["artigos"]:
        v = variacao(est.n["artigos"], ant.n["artigos"])
        rumo = "cresceu" if v > 0 else "caiu" if v < 0 else "se manteve"
        p.append(f"Em relação ao período anterior de mesma duração ({ant.a}–{ant.b}), quando foram publicados {qt(ant.n['artigos'], 'artigo', 'artigos')} "
                 f"em periódicos, o número de artigos {rumo}" + (f" {abs(v)}%." if v else "."))
    doc = docentes(est, grupo)
    if doc and est.n["artigos"]:
        media = f"{est.n['artigos'] / len(doc) / (b - a + 1):.2f}".replace(".", ",")
        p.append(f"A média foi de {media} artigos por docente por ano ({qt(len(doc), 'docente', 'docentes')} no grupo).")

    tec = []
    for cat, sing, plur in (("software", "software", "softwares"), ("patentes", "patente ou registro", "patentes e registros"),
                            ("tecnica", "outra produção técnica", "outras produções técnicas")):
        if est.n[cat]:
            tec.append(qt(est.n[cat], sing, plur))
    if tec:
        p.append(f"Na produção técnica, há registro de {lista_pt(tec)}.")

    nomes_niv = {"posdoc": ("supervisão de pós-doutorado", "supervisões de pós-doutorado"), "doutorado": ("tese de doutorado", "teses de doutorado"),
                 "mestrado": ("dissertação de mestrado", "dissertações de mestrado"), "especializacao": ("monografia de especialização", "monografias de especialização"),
                 "tcc": ("trabalho de conclusão de curso", "trabalhos de conclusão de curso"), "ic": ("iniciação científica", "iniciações científicas"),
                 "outras": ("orientação de outra natureza", "orientações de outra natureza")}
    conc = [qt(est.n["oc_" + k], *nomes_niv[k]) for k, _r, _j in NIVEIS if est.n["oc_" + k]]
    anda = [qt(est.n["oa_" + k], *nomes_niv[k]) for k, _r, _j in NIVEIS if est.n["oa_" + k]]
    if conc or anda:
        t = ""
        if conc:
            t += f"Na formação de recursos humanos, foram concluídas {num(est.soma(OC))} orientações: {lista_pt(conc)}."
        if anda:
            t += (" " if t else "") + f"Estão em andamento {num(est.soma(OA))} orientações ({lista_pt(anda)})."
        p.append(t)

    if est.soma(PJ):
        tipos = lista_pt([qt(est.n[c], *{"pj_pesquisa": ("de pesquisa", "de pesquisa"), "pj_extensao": ("de extensão", "de extensão"),
                                            "pj_desenvolvimento": ("de desenvolvimento", "de desenvolvimento"),
                                            "pj_outros": ("de outra natureza", "de outra natureza")}[c]) for c in PJ if est.n[c]])
        t = f"Os membros participaram de {qt(est.soma(PJ), 'projeto', 'projetos')} ativo{'s' if est.soma(PJ) != 1 else ''} no período ({tipos})"
        t += f", {num(est.coordenados)} deles coordenado{'s' if est.coordenados != 1 else ''} por membros do grupo." if est.coordenados else "."
        p.append(t)

    outros = []
    if est.n["premios"]:
        outros.append(qt(est.n["premios"], "prêmio ou título", "prêmios e títulos"))
    if est.n["bancas"]:
        outros.append(qt(est.n["bancas"], "participação em banca", "participações em bancas"))
    if est.n["ev_part"]:
        outros.append(qt(est.n["ev_part"], "participação em evento", "participações em eventos"))
    if est.n["ev_org"]:
        outros.append(qt(est.n["ev_org"], "evento organizado", "eventos organizados"))
    if outros:
        p.append(f"Há registro ainda de {lista_pt(outros)}.")
    return "\n\n".join(p)


def salvar_excel(caminho, abas):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    for nome, cab, linhas in abas:
        ws = wb.create_sheet(nome[:31])
        ws.append(cab)
        for r in linhas:
            ws.append(r)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F5FA8")
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "B2" if len(cab) > 3 else "A2"
        for i, titulo in enumerate(cab, 1):
            maior = max([len(str(titulo))] + [len(str(r[i - 1])) for r in linhas[:500] if i - 1 < len(r)])
            ws.column_dimensions[get_column_letter(i)].width = min(max(9, maior + 2), 70)
        if linhas:
            ws.auto_filter.ref = ws.dimensions
    wb.save(caminho)


