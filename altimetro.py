"""Altimetro - metricas de grupos de pesquisa a partir do Curriculo Lattes.

    python iniciar.py          prepara (na primeira vez) e abre; ou o lançador do seu sistema
    python altimetro.py        abre direto, com as bibliotecas já instaladas

Serve para qualquer grupo: cadastre os membros pelo ID Lattes, e o programa
baixa os curriculos e roda o scriptLattes (pasta scriptLattes/). Depois mostra
numeros, indicadores, graficos e tabelas de um periodo, salva relatorios em
HTML (imprimiveis em PDF) e exporta para Excel.

As opcoes --baixar e --gerar sao usadas pelo proprio programa, num processo
separado, para o download e o scriptLattes nao travarem a janela.
"""
import datetime
import os
import pathlib
import platform
import queue
import re
import subprocess
import sys
import threading
import webbrowser

import graficos as gr
import marca
import nucleo as n
import relatorio

ESTE = os.path.abspath(__file__)
SISTEMA = platform.system()  # Windows, Darwin (macOS) ou Linux


def interface():
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    import tkinter.font as tkfont

    try:  # texto nitido em telas com escala (Windows)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass

    FUNDO, CARTAO, BORDA = marca.FUNDO, marca.CARTAO, marca.BORDA
    TINTA, MUDO, ACENTO, MARINHO = marca.TINTA, marca.MUDO, marca.AZUL, marca.MARINHO
    FONTE = "Segoe UI"  # trocada pela fonte do sistema assim que a janela existe (App.__init__)
    BOTAO_MENU = ("<Button-2>", "<Button-3>") if SISTEMA == "Darwin" else ("<Button-3>",)

    class Tabela(ttk.Frame):
        """Treeview com barras de rolagem, ordenacao pelo cabecalho e copia (Ctrl+C)."""

        def __init__(self, pai, altura=None, **kw):
            super().__init__(pai, **kw)
            self.tv = ttk.Treeview(self, show="headings", height=altura or 10, selectmode="extended")
            ys = ttk.Scrollbar(self, orient="vertical", command=self.tv.yview)
            xs = ttk.Scrollbar(self, orient="horizontal", command=self.tv.xview)
            self.tv.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
            self.tv.grid(row=0, column=0, sticky="nsew")
            ys.grid(row=0, column=1, sticky="ns")
            xs.grid(row=1, column=0, sticky="ew")
            self.rowconfigure(0, weight=1)
            self.columnconfigure(0, weight=1)
            self.tv.tag_configure("par", background="#F8FAFC")
            self.tv.tag_configure("total", font=(FONTE, 10, "bold"))
            self.cab, self.linhas, self.ordem = [], [], (None, False)
            self.tv.bind("<Control-c>", lambda e: self.copiar(True))
            for b in BOTAO_MENU:
                self.tv.bind(b, self._menu)

        def mostrar(self, cab, linhas, larguras=None, total=False):
            esc = self._root().esc
            self.cab, self.linhas = cab, linhas
            self.tv["columns"] = list(range(len(cab)))
            fonte = tkfont.nametofont("TkDefaultFont")
            for i, c in enumerate(cab):
                num_col = i > 0 and bool(linhas) and all(isinstance(r[i], (int, float)) or r[i] == "" for r in linhas[:200])
                if larguras and i < len(larguras) and larguras[i]:
                    w = int(larguras[i] * esc)
                else:
                    w = max([fonte.measure(str(c)) + 28] + [fonte.measure(str(r[i])[:60]) + 20 for r in linhas[:200]])
                    w = min(max(w, 60), int(420 * esc))
                self.tv.heading(i, text=c, anchor="e" if num_col else "w", command=lambda i=i: self._ordenar(i))
                self.tv.column(i, width=w, minwidth=40, anchor="e" if num_col else "w", stretch=not num_col)
            self._preencher(total)

        def _preencher(self, total=False):
            self.tv.delete(*self.tv.get_children())
            for k, r in enumerate(self.linhas):
                tags = ["par"] if k % 2 else []
                if total and k == len(self.linhas) - 1:
                    tags.append("total")
                self.tv.insert("", "end", values=[n.num(v) if isinstance(v, int) and abs(v) >= 10000 else v for v in r], tags=tags)

        def _ordenar(self, i):
            if not self.linhas:
                return
            desc = not self.ordem[1] if self.ordem[0] == i else isinstance(self.linhas[0][i], int)
            self.ordem = (i, desc)
            self.linhas.sort(key=lambda r: (0, r[i]) if isinstance(r[i], (int, float)) else (1, n.norm(r[i])), reverse=desc)
            self._preencher()

        def texto(self, so_selecao=False):
            idx = [self.tv.index(s) for s in self.tv.selection()] if so_selecao else []
            linhas = [self.linhas[i] for i in idx] if idx else self.linhas
            return "\n".join("\t".join(str(v) for v in r) for r in [self.cab] + linhas)

        def copiar(self, so_selecao=False):
            self.clipboard_clear()
            self.clipboard_append(self.texto(so_selecao))

        def _menu(self, e):
            m = tk.Menu(self, tearoff=0)
            m.add_command(label="Copiar linhas selecionadas", command=lambda: self.copiar(True))
            m.add_command(label="Copiar a tabela inteira (cola no Excel)", command=self.copiar)
            m.tk_popup(e.x_root, e.y_root)

    class Grafico(tk.Canvas):
        """Canvas que desenha uma especificacao de graficos.py, com dica ao passar o mouse."""

        def __init__(self, pai, **kw):
            super().__init__(pai, bg=CARTAO, highlightthickness=0, **kw)
            self.spec, self.dicas = None, []
            self.bind("<Configure>", lambda e: self.redesenhar())
            self.bind("<Motion>", self._mover)
            self.bind("<Leave>", lambda e: self.delete("dica"))

        def mostrar(self, spec):
            self.spec = spec
            self.redesenhar()

        def redesenhar(self):
            self.dicas = gr.desenhar(self, self.spec, self._root().esc) if self.spec else []
            if self.spec and not self.dicas and self.winfo_width() > 80:
                self.create_text(self.winfo_width() / 2, self.winfo_height() / 2, text="Sem dados para este gráfico no período.",
                                 fill=MUDO, font=(FONTE, 11))

        def _mover(self, e):
            self.delete("dica")
            for x0, y0, x1, y1, txt in self.dicas:
                if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                    t = self.create_text(e.x + 14, e.y - 16, text=txt, anchor="w", fill="white", font=(FONTE, 10, "bold"), tags="dica")
                    bx = self.bbox(t)
                    if bx[2] > self.winfo_width() - 4:
                        self.move(t, -(bx[2] - bx[0]) - 28, 0)
                        bx = self.bbox(t)
                    r = self.create_rectangle(bx[0] - 8, bx[1] - 4, bx[2] + 8, bx[3] + 4, fill=TINTA, outline="", tags="dica")
                    self.tag_raise(t, r)
                    return

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            nonlocal FONTE
            FONTE = self._fonte_do_sistema()
            gr.FONTE = FONTE
            self.title(f"{marca.NOME} · {marca.SLOGAN}")
            self.esc = max(1.0, self.winfo_fpixels("1i") / 96)  # escala do Windows (125%, 150%...)
            self.geometry(f"{int(1320 * self.esc)}x{int(840 * self.esc)}")
            self.minsize(int(1100 * self.esc), int(700 * self.esc))
            self._maximizar()
            self.configure(bg=FUNDO)
            self._icone()
            self.pref = n.ler_json(n.PREFERENCIAS, {})
            self.grupo, self.base, self.est = None, None, None
            self.tarefa, self.fila, self.etapas, self.log = None, queue.Queue(), [], []
            self._agendado = None
            self._estilo()
            self._montar()
            grupos = n.Grupo.todos()
            ultimo = self.pref.get("grupo")
            alvo = next((g for g in grupos if os.path.basename(g.pasta) == ultimo), grupos[0] if grupos else None)
            self._listar_grupos(alvo)
            if not grupos:
                self.nb.select(self.abas["sobre"])
            elif not self.base:
                self.nb.select(self.abas["membros"])
            self.after(100, self._ler_fila)
            self.protocol("WM_DELETE_WINDOW", self._fechar)

        def px(self, v):
            return int(v * self.esc)

        def _fonte_do_sistema(self):
            familias = set(tkfont.families(self))
            for f in {"Windows": ["Segoe UI"], "Darwin": ["SF Pro Text", "Helvetica Neue", "Helvetica"]}.get(SISTEMA, []) + \
                    ["Inter", "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Arial"]:
                if f in familias:
                    return f
            return tkfont.nametofont("TkDefaultFont", root=self).actual("family")

        def _maximizar(self):
            try:
                if SISTEMA == "Windows":
                    self.state("zoomed")
                elif SISTEMA == "Linux":
                    self.attributes("-zoomed", True)
                else:
                    self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight() - 80}+0+0")
            except tk.TclError:
                pass

        def _icone(self):
            try:
                ico = os.path.join(marca.PASTA, "altimetro.ico")
                if not os.path.exists(ico):
                    marca.gerar_arquivos()
                if SISTEMA == "Windows":
                    self.iconbitmap(default=ico)
                else:
                    self._icone_png = tk.PhotoImage(file=marca.arquivo(256))
                    self.iconphoto(True, self._icone_png)
            except Exception:  # noqa: BLE001
                pass
            self._fotos = {}
            self.imgs = {}
            for escuro, tams in ((False, (48, 64, 128, 256)), (True, (32, 48, 64))):
                for t in tams:
                    c = marca.arquivo(t, escuro)
                    if c:
                        try:
                            self.imgs[(escuro, t)] = tk.PhotoImage(file=c)
                        except tk.TclError:
                            pass

        def _img(self, tam, escuro=False):
            """A logo mais proxima de tam*escala."""
            alvo = tam * self.esc
            disp = sorted(t for e, t in self.imgs if e == escuro)
            return self.imgs[(escuro, min(disp, key=lambda t: abs(t - alvo)))] if disp else None

        # ------------------------------------------------------------ estilo
        def _estilo(self):
            s = ttk.Style(self)
            s.theme_use("clam")
            for f in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                tkfont.nametofont(f).configure(family=FONTE, size=10)
            s.configure(".", background=FUNDO, foreground=TINTA, font=(FONTE, 10), bordercolor=BORDA, lightcolor=BORDA, darkcolor=BORDA)
            s.configure("TFrame", background=FUNDO)
            s.configure("Cartao.TFrame", background=CARTAO)
            s.configure("Marinho.TFrame", background=MARINHO)
            s.configure("TLabel", background=FUNDO, foreground=TINTA)
            s.configure("Cartao.TLabel", background=CARTAO)
            s.configure("Mudo.TLabel", foreground=MUDO)
            s.configure("MudoCartao.TLabel", background=CARTAO, foreground=MUDO)
            s.configure("Secao.TLabel", font=(FONTE, 11, "bold"), background=CARTAO)
            s.configure("Topo.TLabel", background=MARINHO, foreground="white")
            s.configure("TopoMudo.TLabel", background=MARINHO, foreground="#B9C8DA")
            s.configure("TopoNome.TLabel", background=MARINHO, foreground="white", font=(FONTE, 17, "bold"))
            s.configure("TButton", padding=(12, 5), background="#EDF1F6", bordercolor="#D3DBE5", relief="flat")
            s.map("TButton", background=[("active", "#E0E7F0"), ("disabled", FUNDO)], foreground=[("disabled", "#9AA5B1")])
            s.configure("Acento.TButton", background=ACENTO, foreground="white", bordercolor=ACENTO)
            s.map("Acento.TButton", background=[("active", "#1D4F94"), ("disabled", "#9DB6D6")], foreground=[("disabled", "white")])
            s.configure("Topo.TButton", background="#1B406A", foreground="white", bordercolor="#2A5482")
            s.map("Topo.TButton", background=[("active", "#24507F")])
            s.configure("Link.TButton", background=CARTAO, foreground=ACENTO, padding=(0, 2), borderwidth=0)
            s.map("Link.TButton", background=[("active", CARTAO)])
            s.configure("TNotebook", background=FUNDO, borderwidth=0, tabmargins=(0, 4, 0, 0))
            s.configure("TNotebook.Tab", padding=(16, 7), background=FUNDO, foreground=MUDO, borderwidth=0)
            s.map("TNotebook.Tab", background=[("selected", CARTAO)], foreground=[("selected", ACENTO)], expand=[("selected", (0, 0, 0, 0))])
            s.configure("Sub.TNotebook", background=CARTAO)
            s.configure("Sub.TNotebook.Tab", background=CARTAO, padding=(12, 5))
            s.map("Sub.TNotebook.Tab", background=[("selected", "#EAF1FA")])
            s.configure("Treeview", rowheight=self.px(27), background=CARTAO, fieldbackground=CARTAO, borderwidth=0)
            s.configure("Treeview.Heading", font=(FONTE, 9, "bold"), background="#EEF2F6", foreground=MUDO, relief="flat", padding=(6, 5))
            s.map("Treeview", background=[("selected", "#D5E4F6")], foreground=[("selected", TINTA)])
            s.map("Treeview.Heading", background=[("active", "#E3E9F0")])
            s.configure("TCombobox", padding=4, arrowsize=14, fieldbackground=CARTAO, background=CARTAO)
            s.map("TCombobox", fieldbackground=[("readonly", CARTAO)], selectbackground=[("readonly", CARTAO)],
                  selectforeground=[("readonly", TINTA)], background=[("readonly", CARTAO)])
            s.configure("TSpinbox", padding=4, arrowsize=12, fieldbackground=CARTAO)
            for o in ("Vertical", "Horizontal"):
                s.configure(o + ".TScrollbar", background="#D3DAE3", troughcolor=CARTAO, bordercolor=CARTAO,
                            lightcolor="#D3DAE3", darkcolor="#D3DAE3", arrowcolor=MUDO, arrowsize=12)
            s.configure("Horizontal.TProgressbar", background=ACENTO, troughcolor="#E6EBF1", borderwidth=0, thickness=8)
            s.configure("TCheckbutton", background=CARTAO)
            s.map("TCheckbutton", background=[("active", CARTAO)])
            s.configure("TMenubutton", background=CARTAO, padding=(10, 4))

        # -------------------------------------------------------- estrutura
        def _montar(self):
            topo = ttk.Frame(self, style="Marinho.TFrame", padding=(20, 10, 20, 10))
            topo.pack(fill="x")
            if self._img(40, True):
                ttk.Label(topo, image=self._img(40, True), style="Topo.TLabel").pack(side="left", padx=(0, 12))
            nomes = ttk.Frame(topo, style="Marinho.TFrame")
            nomes.pack(side="left")
            ttk.Label(nomes, text=marca.NOME, style="TopoNome.TLabel").pack(anchor="w")
            ttk.Label(nomes, text=marca.SLOGAN, style="TopoMudo.TLabel").pack(anchor="w")
            dir_ = ttk.Frame(topo, style="Marinho.TFrame")
            dir_.pack(side="right")
            ttk.Label(dir_, text="Grupo", style="TopoMudo.TLabel").pack(side="left", padx=(0, 8))
            self.cb_grupo = ttk.Combobox(dir_, state="readonly", width=32)
            self.cb_grupo.pack(side="left")
            self.cb_grupo.bind("<<ComboboxSelected>>", lambda e: self._abrir_grupo(self._grupos[self.cb_grupo.current()]))
            ttk.Button(dir_, text="Novo grupo", style="Topo.TButton", command=self._novo_grupo).pack(side="left", padx=(8, 0))
            ttk.Button(dir_, text="Renomear", style="Topo.TButton", command=self._renomear).pack(side="left", padx=(6, 0))

            # barra de filtros (periodo e categorias) das abas de estatistica
            self.filtros = ttk.Frame(self, padding=(20, 10, 20, 8))
            self.filtros.pack(fill="x")
            ttk.Label(self.filtros, text="Período").pack(side="left")
            self.cb_preset = ttk.Combobox(self.filtros, state="readonly", width=27)
            self.cb_preset.pack(side="left", padx=(8, 8))
            self.cb_preset.bind("<<ComboboxSelected>>", lambda e: self._aplicar_preset())
            self.v_de, self.v_ate = tk.StringVar(), tk.StringVar()
            self.sp_de = ttk.Spinbox(self.filtros, textvariable=self.v_de, width=6, command=self._mudou_periodo)
            self.sp_de.pack(side="left")
            ttk.Label(self.filtros, text="até").pack(side="left", padx=6)
            self.sp_ate = ttk.Spinbox(self.filtros, textvariable=self.v_ate, width=6, command=self._mudou_periodo)
            self.sp_ate.pack(side="left")
            for sp in (self.sp_de, self.sp_ate):
                sp.bind("<KeyRelease>", lambda e: self._mudou_periodo())
            ttk.Label(self.filtros, text="Categorias").pack(side="left", padx=(22, 8))
            self.mb_cat = ttk.Menubutton(self.filtros, text="Todas", width=22)
            self.mb_cat.pack(side="left")
            self.menu_cat = tk.Menu(self.mb_cat, tearoff=0)
            self.mb_cat["menu"] = self.menu_cat
            self.v_cats = {}
            self.lb_sel = ttk.Label(self.filtros, style="Mudo.TLabel")
            self.lb_sel.pack(side="left", padx=12)
            self.bt_relatorio = ttk.Button(self.filtros, text="Salvar relatório", style="Acento.TButton", command=lambda: self._gerar_relatorio())
            self.bt_relatorio.pack(side="right")
            self.bt_excel = ttk.Button(self.filtros, text="Exportar Excel", command=self._exportar)
            self.bt_excel.pack(side="right", padx=8)

            self.nb = ttk.Notebook(self)
            self.nb.pack(fill="both", expand=True, padx=20, pady=(0, 6))
            self.abas = {}
            for chave, titulo in (("equipe", "Equipe"), ("resumo", "Resumo"), ("graficos", "Gráficos"), ("tabelas", "Tabelas"),
                                  ("itens", "Lista de itens"), ("texto", "Texto"), ("relatorios", "Relatórios"),
                                  ("membros", "Gerenciar membros"), ("sobre", "Sobre")):
                f = ttk.Frame(self.nb, style="Cartao.TFrame", padding=16)
                self.nb.add(f, text=titulo)
                self.abas[chave] = f
            self.nb.bind("<<NotebookTabChanged>>", lambda e: self._aba_mudou())

            self.status = ttk.Label(self, style="Mudo.TLabel", padding=(22, 0, 22, 8))
            self.status.pack(fill="x")

            self._montar_membros()
            self._montar_equipe()
            self._montar_resumo()
            self._montar_graficos()
            self._montar_tabelas()
            self._montar_itens()
            self._montar_texto()
            self._montar_relatorios()
            self._montar_sobre()

        # ----------------------------------------------------- aba Membros
        def _montar_membros(self):
            f = self.abas["membros"]
            esq = ttk.Frame(f, style="Cartao.TFrame")
            esq.pack(side="left", fill="both", expand=True)
            self.lb_membros = ttk.Label(esq, text="Membros", style="Secao.TLabel")
            self.lb_membros.pack(anchor="w")
            ttk.Label(esq, text="Clique em ✓ para incluir ou tirar alguém das estatísticas. Duplo clique muda a categoria.",
                      style="MudoCartao.TLabel").pack(anchor="w", pady=(2, 8))
            self.t_m = Tabela(esq)
            self.t_m.pack(fill="both", expand=True)
            self.t_m.tv.bind("<Button-1>", self._clique_membro, add="+")
            self.t_m.tv.bind("<Double-1>", self._duplo_membro)
            self.t_m.tv.bind("<Delete>", lambda e: self._remover())

            dir_ = ttk.Frame(f, style="Cartao.TFrame", padding=(22, 0, 0, 0), width=self.px(360))
            dir_.pack(side="right", fill="y")
            dir_.pack_propagate(False)
            wl = self.px(330)
            ttk.Label(dir_, text="Adicionar membros", style="Secao.TLabel").pack(anchor="w")
            ttk.Label(dir_, text="Cole os IDs Lattes (16 dígitos) ou os links, um por linha. O nome vem do currículo.",
                      style="MudoCartao.TLabel", wraplength=wl, justify="left").pack(anchor="w", pady=(2, 6))
            self.tx_ids = tk.Text(dir_, height=6, width=36, relief="flat", font=(FONTE, 10), bg="#F7F9FB",
                                  highlightthickness=1, highlightbackground=BORDA, highlightcolor=ACENTO, padx=8, pady=6)
            self.tx_ids.pack(fill="x")
            l = ttk.Frame(dir_, style="Cartao.TFrame")
            l.pack(fill="x", pady=(8, 0))
            ttk.Label(l, text="Categoria", style="Cartao.TLabel").pack(side="left")
            self.cb_cat_novo = ttk.Combobox(l, values=n.CATEGORIAS, width=18)
            self.cb_cat_novo.set(n.CATEGORIAS[0])
            self.cb_cat_novo.pack(side="left", padx=8)
            ttk.Button(l, text="Adicionar", style="Acento.TButton", command=self._adicionar).pack(side="right")

            ttk.Separator(dir_).pack(fill="x", pady=14)
            ttk.Label(dir_, text="Membros selecionados na tabela", style="Secao.TLabel").pack(anchor="w")
            l2 = ttk.Frame(dir_, style="Cartao.TFrame")
            l2.pack(fill="x", pady=(6, 0))
            self.cb_cat_sel = ttk.Combobox(l2, values=n.CATEGORIAS, width=18)
            self.cb_cat_sel.pack(side="left")
            ttk.Button(l2, text="Mudar categoria", command=self._mudar_categoria).pack(side="right")
            l3 = ttk.Frame(dir_, style="Cartao.TFrame")
            l3.pack(fill="x", pady=(6, 0))
            ttk.Button(l3, text="Abrir no Lattes", command=self._abrir_lattes).pack(side="left", fill="x", expand=True)
            ttk.Button(l3, text="Remover do grupo", command=self._remover).pack(side="left", fill="x", expand=True, padx=(6, 0))
            ttk.Button(dir_, text="Trocar a foto…", command=self._trocar_foto).pack(fill="x", pady=(6, 0))

            ttk.Separator(dir_).pack(fill="x", pady=14)
            ttk.Label(dir_, text="Currículos e estatísticas", style="Secao.TLabel").pack(anchor="w")
            ttk.Label(dir_, text="O download usa o Chrome e leva uns 20 segundos por currículo. A janela continua livre enquanto isso.",
                      style="MudoCartao.TLabel", wraplength=wl, justify="left").pack(anchor="w", pady=(2, 8))
            self.bt_tudo = ttk.Button(dir_, text="Atualizar tudo", style="Acento.TButton", command=lambda: self._rodar(["baixar", "gerar"]))
            self.bt_tudo.pack(fill="x")
            l4 = ttk.Frame(dir_, style="Cartao.TFrame")
            l4.pack(fill="x", pady=(6, 0))
            self.bt_faltam = ttk.Button(l4, text="Baixar só os novos", command=lambda: self._rodar(["faltam", "gerar"]))
            self.bt_faltam.pack(side="left", fill="x", expand=True)
            self.bt_gerar = ttk.Button(l4, text="Só recalcular", command=lambda: self._rodar(["gerar"]))
            self.bt_gerar.pack(side="left", fill="x", expand=True, padx=(6, 0))
            self.pb = ttk.Progressbar(dir_, mode="determinate")
            self.pb.pack(fill="x", pady=(14, 4))
            self.lb_prog = ttk.Label(dir_, text="", style="MudoCartao.TLabel", wraplength=wl, justify="left")
            self.lb_prog.pack(anchor="w")
            l5 = ttk.Frame(dir_, style="Cartao.TFrame")
            l5.pack(fill="x", pady=(4, 0))
            ttk.Button(l5, text="Ver registro", style="Link.TButton", command=self._ver_log).pack(side="left")
            ttk.Button(l5, text="Relatório do scriptLattes", style="Link.TButton", command=self._abrir_scriptlattes).pack(side="left", padx=14)

        # ------------------------------------------------------ aba Equipe
        def _montar_equipe(self):
            f = self.abas["equipe"]
            cab = ttk.Frame(f, style="Cartao.TFrame")
            cab.pack(fill="x")
            self.lb_equipe = ttk.Label(cab, text="Equipe", style="Secao.TLabel")
            self.lb_equipe.pack(side="left")
            self.v_busca_eq = tk.StringVar()
            ttk.Entry(cab, textvariable=self.v_busca_eq, width=28).pack(side="right")
            ttk.Label(cab, text="Buscar", style="Cartao.TLabel").pack(side="right", padx=8)
            self.v_busca_eq.trace_add("write", lambda *a: self._agendar(self._mostrar_equipe, 200))
            ttk.Label(f, text="Quem está nas estatísticas, com os números do período. Clique em uma pessoa para ver a ficha.",
                      style="MudoCartao.TLabel").pack(anchor="w", pady=(2, 10))
            caixa = ttk.Frame(f, style="Cartao.TFrame")
            caixa.pack(fill="both", expand=True)
            self.cv_eq = tk.Canvas(caixa, bg=CARTAO, highlightthickness=0)
            sb = ttk.Scrollbar(caixa, orient="vertical", command=self.cv_eq.yview)
            self.cv_eq.configure(yscrollcommand=sb.set)
            self.cv_eq.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.fr_eq = tk.Frame(self.cv_eq, bg=CARTAO)
            self._jan_eq = self.cv_eq.create_window(0, 0, window=self.fr_eq, anchor="nw")
            self.fr_eq.bind("<Configure>", lambda e: self.cv_eq.configure(scrollregion=self.cv_eq.bbox("all")))
            self._larg_eq = 0
            self.cv_eq.bind("<Configure>", self._eq_redimensionou)
            self._rolagem(self.cv_eq)

        def _rolagem(self, canvas):
            """Roda do mouse no Canvas (Windows/macOS: MouseWheel; Linux: botoes 4 e 5)."""
            def rolar(e):
                if e.num == 4:
                    canvas.yview_scroll(-3, "units")
                elif e.num == 5:
                    canvas.yview_scroll(3, "units")
                else:
                    canvas.yview_scroll(int(-e.delta / (1 if SISTEMA == "Darwin" else 40)), "units")

            def entrar(_e):
                for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    self.bind_all(ev, rolar)

            def sair(_e):
                for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    self.unbind_all(ev)
            canvas.bind("<Enter>", entrar)
            canvas.bind("<Leave>", sair)

        def _eq_redimensionou(self, e):
            self.cv_eq.itemconfigure(self._jan_eq, width=e.width)
            colunas = max(1, e.width // self.px(240))
            if colunas != getattr(self, "_cols_eq", None):
                self._cols_eq = colunas
                self._agendar(self._mostrar_equipe, 120)

        def _foto(self, lid, nome, tam, cor_fundo=CARTAO):
            """Foto redonda (ou as iniciais) como PhotoImage, guardada em cache."""
            px = self.px(tam)
            arq = self.grupo.foto(lid) if self.grupo else None
            chave = (lid, px, arq and os.path.getmtime(arq), cor_fundo)
            if chave in self._fotos:
                return self._fotos[chave]
            try:
                from PIL import Image, ImageDraw, ImageFont, ImageTk
            except ImportError:
                return None
            k = 4
            S = px * k
            if arq:
                im = Image.open(arq).convert("RGB").resize((S, S), Image.LANCZOS)
            else:
                cat = (self.grupo.membro(lid) or {}).get("categoria") or ""
                cats = [c for c in n.CATEGORIAS]
                cor = marca.SERIES[(cats.index(cat) if cat in cats else len(cats)) % len(marca.SERIES)]
                im = Image.new("RGB", (S, S), cor)
                d = ImageDraw.Draw(im)
                try:
                    fonte = gr._fonte(S * 0.38, True)
                except Exception:  # noqa: BLE001
                    fonte = ImageFont.load_default()
                d.text((S / 2, S / 2), n.iniciais(nome), fill="white", font=fonte, anchor="mm")
            mascara = Image.new("L", (S, S), 0)
            ImageDraw.Draw(mascara).ellipse((0, 0, S - 1, S - 1), fill=255)
            fundo = Image.new("RGB", (S, S), cor_fundo)
            fundo.paste(im, (0, 0), mascara)
            img = ImageTk.PhotoImage(fundo.resize((px, px), Image.LANCZOS))
            self._fotos[chave] = img
            return img

        def _mostrar_equipe(self):
            for w in self.fr_eq.winfo_children():
                w.destroy()
            est, base, g = self.est, self.base, self.grupo
            if not est:
                tk.Label(self.fr_eq, text="Sem dados ainda. Na aba “Gerenciar membros”, adicione os IDs Lattes e clique em “Atualizar tudo”.",
                         bg=CARTAO, fg=MUDO, font=(FONTE, 11)).pack(anchor="w", pady=20)
                self.lb_equipe.configure(text="Equipe")
                return
            termo = n.norm(self.v_busca_eq.get())
            ordem = {c: i for i, c in enumerate(n.CATEGORIAS)}
            por_cat = {}
            for lid in est.sel:
                nome = base.pessoas.get(lid, {}).get("nome", lid)
                if termo and termo not in n.norm(nome):
                    continue
                cat = (g.membro(lid) or {}).get("categoria") or "Sem categoria"
                por_cat.setdefault(cat, []).append((n.norm(nome), lid, nome))
            self.lb_equipe.configure(text=f"Equipe · {n.qt(len(est.sel), 'pessoa', 'pessoas')}")
            cols = getattr(self, "_cols_eq", 4) or 4
            for cat in sorted(por_cat, key=lambda c: (ordem.get(c, 99), c)):
                pessoas = sorted(por_cat[cat])
                tk.Label(self.fr_eq, text=f"{cat}  ·  {len(pessoas)}", font=(FONTE, 11, "bold"), bg=CARTAO, fg=MARINHO,
                         anchor="w").pack(fill="x", pady=(14, 6))
                grade = tk.Frame(self.fr_eq, bg=CARTAO)
                grade.pack(fill="x")
                for c in range(cols):
                    grade.columnconfigure(c, weight=1, uniform="eq")
                for k, (_o, lid, nome) in enumerate(pessoas):
                    self._cartao_pessoa(grade, lid, nome, est.por_membro.get(lid, {})).grid(row=k // cols, column=k % cols, sticky="nsew",
                                                                                            padx=(0, 10), pady=(0, 10))
            self.cv_eq.yview_moveto(0)

        def _cartao_pessoa(self, pai, lid, nome, c):
            card = tk.Frame(pai, bg=CARTAO, highlightthickness=1, highlightbackground=BORDA, padx=12, pady=10, cursor="hand2")
            foto = self._foto(lid, nome, 56)
            lb = tk.Label(card, image=foto, bg=CARTAO) if foto else tk.Label(card, text=n.iniciais(nome), bg=CARTAO)
            lb.pack(side="left", padx=(0, 12))
            txt = tk.Frame(card, bg=CARTAO)
            txt.pack(side="left", fill="x", expand=True)
            t1 = tk.Label(txt, text=nome, font=(FONTE, 10, "bold"), bg=CARTAO, fg=TINTA, anchor="w", justify="left", wraplength=self.px(160))
            t1.pack(anchor="w")
            partes = [n.qt(c.get("artigos", 0), "artigo", "artigos")]
            orient = sum(c.get(k, 0) for k in n.OC)
            if orient:
                partes.append(n.qt(orient, "orientação", "orientações"))
            t2 = tk.Label(txt, text=" · ".join(partes), font=(FONTE, 9), bg=CARTAO, fg=MUDO, anchor="w")
            t2.pack(anchor="w", pady=(2, 0))
            for w in (card, lb, txt, t1, t2):
                w.bind("<Button-1>", lambda e, lid=lid: self._ficha(lid))
                w.bind("<Enter>", lambda e: card.configure(highlightbackground=ACENTO))
                w.bind("<Leave>", lambda e: card.configure(highlightbackground=BORDA))
            return card

        def _ficha(self, lid):
            if not self.est:
                return
            fx = n.ficha(self.est, self.base, self.grupo, lid)
            j = tk.Toplevel(self)
            j.title(fx["nome"])
            j.configure(bg=CARTAO)
            j.geometry(f"{self.px(860)}x{self.px(620)}")
            j.transient(self)
            topo = tk.Frame(j, bg=CARTAO, padx=22, pady=18)
            topo.pack(fill="x")
            foto = self._foto(lid, fx["nome"], 96)
            if foto:
                tk.Label(topo, image=foto, bg=CARTAO).pack(side="left", padx=(0, 18))
            info = tk.Frame(topo, bg=CARTAO)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=fx["nome"], font=(FONTE, 17, "bold"), bg=CARTAO, fg=MARINHO, anchor="w").pack(anchor="w")
            per = f"{self.est.a}" if self.est.a == self.est.b else f"{self.est.a}–{self.est.b}"
            tk.Label(info, text=f"{fx['categoria'] or 'Sem categoria'} · {self.grupo.nome} · período {per}", font=(FONTE, 10), bg=CARTAO, fg=MUDO).pack(anchor="w")
            if fx["atualizado"]:
                tk.Label(info, text=f"Currículo Lattes atualizado em {fx['atualizado']}", font=(FONTE, 9), bg=CARTAO, fg=MUDO).pack(anchor="w", pady=(2, 0))
            ttk.Button(topo, text="Abrir no Lattes", command=lambda: webbrowser.open("http://lattes.cnpq.br/" + lid)).pack(side="right", anchor="n")
            nums = tk.Frame(j, bg=CARTAO, padx=22)
            nums.pack(fill="x")
            for i, (rot, v) in enumerate(fx["numeros"]):
                c = tk.Frame(nums, bg=CARTAO, highlightthickness=1, highlightbackground=BORDA, padx=10, pady=6)
                c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
                nums.columnconfigure(i, weight=1, uniform="f")
                tk.Label(c, text=n.num(v), font=(FONTE, 16, "bold"), bg=CARTAO, fg=TINTA).pack(anchor="w")
                tk.Label(c, text=rot, font=(FONTE, 9), bg=CARTAO, fg=MUDO).pack(anchor="w")
            baixo = tk.Frame(j, bg=CARTAO, padx=22, pady=14)
            baixo.pack(fill="both", expand=True)
            baixo.columnconfigure(0, weight=3)
            baixo.columnconfigure(1, weight=2)
            baixo.rowconfigure(1, weight=1)
            tk.Label(baixo, text="Produção bibliográfica por ano", font=(FONTE, 10, "bold"), bg=CARTAO).grid(row=0, column=0, sticky="w")
            gfx = Grafico(baixo)
            gfx.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
            gfx.mostrar(fx["grafico"])
            tk.Label(baixo, text="Parcerias no grupo", font=(FONTE, 10, "bold"), bg=CARTAO).grid(row=0, column=1, sticky="w", padx=(20, 0))
            t = Tabela(baixo, altura=8)
            t.grid(row=1, column=1, sticky="nsew", padx=(20, 0), pady=(4, 0))
            t.mostrar(["Membro", "Trabalhos juntos"], [list(x) for x in fx["parceiros"]], [200, 110])
            j.bind("<Escape>", lambda e: j.destroy())

        def _trocar_foto(self):
            ids = self._ids_selecionados()
            if len(ids) != 1:
                messagebox.showinfo("Trocar a foto", "Selecione uma pessoa na tabela.", parent=self)
                return
            arq = filedialog.askopenfilename(parent=self, title="Escolha a foto", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp *.bmp")])
            if not arq:
                return
            try:
                with open(arq, "rb") as f:
                    n.salvar_foto(f.read(), self.grupo.foto_arquivo(ids[0]))
                open(os.path.join(self.grupo.fotos, ids[0] + ".usuario"), "w").close()  # o download nao troca mais
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Trocar a foto", f"Não deu para usar esta imagem:\n{e}", parent=self)
                return
            self._fotos.clear()
            self._mostrar_equipe()
            self.lb_prog.configure(text="Foto trocada.")

        # ------------------------------------------------------ aba Resumo
        def _montar_resumo(self):
            f = self.abas["resumo"]
            self.lb_resumo = ttk.Label(f, text="", style="Secao.TLabel")
            self.lb_resumo.pack(anchor="w")
            self.lb_resumo_sub = ttk.Label(f, text="", style="MudoCartao.TLabel")
            self.lb_resumo_sub.pack(anchor="w", pady=(2, 12))
            grade = ttk.Frame(f, style="Cartao.TFrame")
            grade.pack(fill="x")
            self.cards = []
            for i in range(10):
                c = tk.Frame(grade, bg=CARTAO, highlightthickness=1, highlightbackground=BORDA, padx=14, pady=10)
                c.grid(row=i // 5, column=i % 5, sticky="nsew", padx=(0 if i % 5 == 0 else 10, 0), pady=(0, 10))
                v = tk.Label(c, text="–", font=(FONTE, 22, "bold"), bg=CARTAO, fg=TINTA, anchor="w")
                v.pack(anchor="w")
                t = tk.Label(c, text="", font=(FONTE, 10, "bold"), bg=CARTAO, fg=TINTA, anchor="w", justify="left")
                t.pack(anchor="w")
                d = tk.Label(c, text="", font=(FONTE, 9, "bold"), bg=CARTAO, fg=MUDO, anchor="w", justify="left")
                d.pack(anchor="w", pady=(2, 0))
                s = tk.Label(c, text="", font=(FONTE, 9), bg=CARTAO, fg=MUDO, anchor="w", justify="left")
                s.pack(anchor="w")
                c.bind("<Configure>", lambda e, ls=(t, d, s): [x.configure(wraplength=e.width - 30) for x in ls])
                self.cards.append((v, t, d, s))
            for i in range(5):
                grade.columnconfigure(i, weight=1, uniform="c")

            baixo = ttk.Frame(f, style="Cartao.TFrame")
            baixo.pack(fill="both", expand=True, pady=(8, 0))
            baixo.columnconfigure(0, weight=3)
            baixo.columnconfigure(1, weight=2)
            baixo.rowconfigure(1, weight=1)
            barra = ttk.Frame(baixo, style="Cartao.TFrame")
            barra.grid(row=0, column=0, sticky="ew")
            self.cb_graf_resumo = ttk.Combobox(barra, state="readonly", width=40)
            self.cb_graf_resumo.pack(side="left")
            self.cb_graf_resumo.bind("<<ComboboxSelected>>", lambda e: self._grafico_resumo())
            self.g_resumo = Grafico(baixo, height=self.px(240))
            self.g_resumo.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
            ttk.Label(baixo, text="Indicadores", style="Secao.TLabel").grid(row=0, column=1, sticky="w", padx=(24, 0))
            self.t_ind = Tabela(baixo, altura=8)
            self.t_ind.grid(row=1, column=1, sticky="nsew", padx=(24, 0), pady=(6, 0))

        # ---------------------------------------------------- aba Graficos
        def _montar_graficos(self):
            f = self.abas["graficos"]
            esq = ttk.Frame(f, style="Cartao.TFrame", width=self.px(300))
            esq.pack(side="left", fill="y")
            esq.pack_propagate(False)
            ttk.Label(esq, text="Gráficos", style="Secao.TLabel").pack(anchor="w")
            ttk.Label(esq, text="Passe o mouse sobre as barras para ver os números.", style="MudoCartao.TLabel",
                      wraplength=self.px(280), justify="left").pack(anchor="w", pady=(2, 8))
            self.lst_graf = tk.Listbox(esq, activestyle="none", relief="flat", highlightthickness=0, font=(FONTE, 10),
                                       selectbackground="#D5E4F6", selectforeground=TINTA, bg=CARTAO, fg=TINTA, exportselection=False)
            self.lst_graf.pack(fill="both", expand=True)
            self.lst_graf.bind("<<ListboxSelect>>", lambda e: self._mostrar_grafico())
            dir_ = ttk.Frame(f, style="Cartao.TFrame", padding=(20, 0, 0, 0))
            dir_.pack(side="left", fill="both", expand=True)
            cab = ttk.Frame(dir_, style="Cartao.TFrame")
            cab.pack(fill="x")
            self.lb_graf = ttk.Label(cab, text="", style="Secao.TLabel")
            self.lb_graf.pack(side="left")
            ttk.Button(cab, text="Copiar dados", command=self._copiar_dados_grafico).pack(side="right")
            ttk.Button(cab, text="Salvar SVG", command=lambda: self._salvar_grafico("svg")).pack(side="right", padx=6)
            ttk.Button(cab, text="Salvar PNG", style="Acento.TButton", command=lambda: self._salvar_grafico("png")).pack(side="right")
            self.lb_graf_sub = ttk.Label(dir_, text="", style="MudoCartao.TLabel")
            self.lb_graf_sub.pack(anchor="w", pady=(2, 8))
            self.g_principal = Grafico(dir_)
            self.g_principal.pack(fill="both", expand=True)
            self.catalogo = []

        # ----------------------------------------------------- aba Tabelas
        def _montar_tabelas(self):
            sub = ttk.Notebook(self.abas["tabelas"], style="Sub.TNotebook")
            sub.pack(fill="both", expand=True)
            self.tabs = {}
            for chave, titulo in (("ano", "Por ano"), ("membro", "Por membro"), ("orient", "Orientações"), ("proj", "Projetos"),
                                  ("veic", "Periódicos e eventos"), ("ind", "Indicadores")):
                fr = ttk.Frame(sub, style="Cartao.TFrame", padding=(0, 10, 0, 0))
                sub.add(fr, text=titulo)
                if chave == "orient":
                    self.t_or_res = Tabela(fr, altura=8)
                    self.t_or_res.pack(fill="x")
                    ttk.Label(fr, text="Lista de orientações", style="Secao.TLabel").pack(anchor="w", pady=(12, 6))
                t = Tabela(fr)
                t.pack(fill="both", expand=True)
                self.tabs[chave] = t
            ttk.Label(self.abas["tabelas"], text="Clique no cabeçalho para ordenar. Botão direito copia a tabela (cola direto no Excel ou no Word).",
                      style="MudoCartao.TLabel").pack(anchor="w", pady=(8, 0))

        def _montar_itens(self):
            f = self.abas["itens"]
            barra = ttk.Frame(f, style="Cartao.TFrame")
            barra.pack(fill="x", pady=(0, 8))
            ttk.Label(barra, text="Tipo", style="Cartao.TLabel").pack(side="left")
            self.tipos_itens = [("Tudo", None)] + [(g, [k for k in n.CATS if n.CATS[k][1] == g]) for g in n.GRUPOS_CAT] + \
                               [(n.CATS[k][0], [k]) for k in n.CATS]
            self.cb_tipo = ttk.Combobox(barra, state="readonly", width=34,
                                        values=[t[0] if t[1] is None or len(t[1]) == 1 else "— " + t[0] for t in self.tipos_itens])
            self.cb_tipo.current(0)
            self.cb_tipo.pack(side="left", padx=8)
            self.cb_tipo.bind("<<ComboboxSelected>>", lambda e: self._mostrar_itens())
            ttk.Label(barra, text="Buscar", style="Cartao.TLabel").pack(side="left", padx=(16, 0))
            self.v_busca = tk.StringVar()
            ttk.Entry(barra, textvariable=self.v_busca, width=40).pack(side="left", padx=8)
            self.v_busca.trace_add("write", lambda *a: self._agendar(self._mostrar_itens, 200))
            self.lb_itens = ttk.Label(barra, style="MudoCartao.TLabel")
            self.lb_itens.pack(side="left", padx=8)
            ttk.Button(barra, text="Copiar lista", command=lambda: self.t_itens.copiar()).pack(side="right")
            self.t_itens = Tabela(f)
            self.t_itens.pack(fill="both", expand=True)

        def _montar_texto(self):
            f = self.abas["texto"]
            barra = ttk.Frame(f, style="Cartao.TFrame")
            barra.pack(fill="x", pady=(0, 8))
            ttk.Label(barra, text="Texto gerado a partir dos números do período. Pode editar aqui antes de copiar.",
                      style="MudoCartao.TLabel").pack(side="left")
            ttk.Button(barra, text="Copiar texto", style="Acento.TButton", command=self._copiar_texto).pack(side="right")
            self.tx = tk.Text(f, wrap="word", relief="flat", font=(FONTE, 11), bg=CARTAO, fg=TINTA, padx=4, pady=4, spacing2=3, spacing3=8)
            self.tx.pack(fill="both", expand=True)

        # -------------------------------------------------- aba Relatorios
        def _montar_relatorios(self):
            f = self.abas["relatorios"]
            esq = ttk.Frame(f, style="Cartao.TFrame", width=self.px(340))
            esq.pack(side="left", fill="y")
            esq.pack_propagate(False)
            ttk.Label(esq, text="Novo relatório", style="Secao.TLabel").pack(anchor="w")
            ttk.Label(esq, text="Usa o período e as categorias escolhidos no alto. Sai um arquivo HTML que abre no navegador; "
                      "de lá, “Imprimir ou salvar em PDF”.", style="MudoCartao.TLabel", wraplength=self.px(320), justify="left").pack(anchor="w", pady=(2, 10))
            self.v_secoes = {}
            for chave, titulo, padrao in relatorio.SECOES:
                v = tk.BooleanVar(value=padrao)
                self.v_secoes[chave] = v
                ttk.Checkbutton(esq, text=titulo, variable=v).pack(anchor="w", pady=1)
            ttk.Button(esq, text="Salvar relatório", style="Acento.TButton", command=self._gerar_relatorio).pack(anchor="w", pady=(14, 0))

            dir_ = ttk.Frame(f, style="Cartao.TFrame", padding=(24, 0, 0, 0))
            dir_.pack(side="left", fill="both", expand=True)
            cab = ttk.Frame(dir_, style="Cartao.TFrame")
            cab.pack(fill="x")
            ttk.Label(cab, text="Relatórios salvos deste grupo", style="Secao.TLabel").pack(side="left")
            ttk.Button(cab, text="Excluir", command=self._excluir_relatorio).pack(side="right")
            ttk.Button(cab, text="Abrir pasta", command=self._abrir_pasta_relatorios).pack(side="right", padx=6)
            ttk.Button(cab, text="Abrir", style="Acento.TButton", command=self._abrir_relatorio_sel).pack(side="right")
            self.t_rel = Tabela(dir_)
            self.t_rel.pack(fill="both", expand=True, pady=(10, 0))
            self.t_rel.tv.bind("<Double-1>", lambda e: self._abrir_relatorio_sel())

        # ------------------------------------------------------- aba Sobre
        def _montar_sobre(self):
            f = self.abas["sobre"]
            meio = ttk.Frame(f, style="Cartao.TFrame")
            meio.place(relx=0.5, rely=0.46, anchor="center")
            if self._img(128):
                ttk.Label(meio, image=self._img(128), style="Cartao.TLabel").pack(pady=(0, 12))
            tk.Label(meio, text=marca.NOME, font=(FONTE, 30, "bold"), fg=MARINHO, bg=CARTAO).pack()
            tk.Label(meio, text=marca.SLOGAN, font=(FONTE, 12), fg=MUDO, bg=CARTAO).pack()
            tk.Label(meio, text=f"versão {marca.VERSAO}", font=(FONTE, 9), fg=MUDO, bg=CARTAO).pack(pady=(2, 18))
            cred = tk.Frame(meio, bg=marca.AZUL_CLARO, padx=28, pady=16)
            cred.pack()
            tk.Label(cred, text="CRIADO POR", font=(FONTE, 8, "bold"), fg=ACENTO, bg=marca.AZUL_CLARO).pack()
            tk.Label(cred, text=marca.AUTOR, font=(FONTE, 16, "bold"), fg=TINTA, bg=marca.AZUL_CLARO).pack(pady=(2, 0))
            tk.Label(cred, text=marca.CURSO, font=(FONTE, 11), fg=TINTA, bg=marca.AZUL_CLARO).pack()
            tk.Label(cred, text=marca.INSTITUICAO, font=(FONTE, 11), fg=TINTA, bg=marca.AZUL_CLARO).pack()
            texto = ("Cadastre os membros do grupo pelo ID Lattes: o Altímetro baixa os currículos, processa tudo com o "
                     "scriptLattes e mostra a produção, as orientações, os projetos e a colaboração do grupo em qualquer período, "
                     "com gráficos, indicadores, relatórios e exportação para Excel.")
            tk.Label(meio, text=texto, font=(FONTE, 10), fg=TINTA, bg=CARTAO, wraplength=self.px(620), justify="center").pack(pady=(20, 8))
            tk.Label(meio, text="Dados: Plataforma Lattes (CNPq). Processamento: scriptLattes (Mena-Chalco & Cesar-Jr., 2009).",
                     font=(FONTE, 9), fg=MUDO, bg=CARTAO).pack()
            if not n.Grupo.todos():
                ttk.Button(meio, text="Criar o primeiro grupo", style="Acento.TButton", command=self._novo_grupo).pack(pady=(18, 0))

        # ------------------------------------------------------ grupos
        def _listar_grupos(self, alvo=None):
            self._grupos = n.Grupo.todos()
            self.cb_grupo["values"] = [g.nome for g in self._grupos]
            if alvo is not None:
                for i, g in enumerate(self._grupos):
                    if g.pasta == alvo.pasta:
                        self.cb_grupo.current(i)
                        self._abrir_grupo(g)
                        return
            self.cb_grupo.set("")
            self._abrir_grupo(None)

        def _novo_grupo(self):
            nome = simpledialog.askstring("Novo grupo", "Nome do grupo de pesquisa (ex.: LSA, GEMEC):", parent=self)
            if nome and nome.strip():
                self._listar_grupos(n.Grupo.criar(nome.strip()))
                self.nb.select(self.abas["membros"])
                self.tx_ids.focus_set()

        def _renomear(self):
            if not self.grupo:
                return
            nome = simpledialog.askstring("Renomear grupo", "Nome do grupo:", initialvalue=self.grupo.nome, parent=self)
            if nome and nome.strip():
                self._reler_grupo()
                self.grupo.nome = nome.strip()
                self.grupo.salvar()
                self._listar_grupos(self.grupo)

        def _abrir_grupo(self, g):
            self.grupo = g
            if g:
                self.pref["grupo"] = os.path.basename(g.pasta)
                n.gravar_json(n.PREFERENCIAS, self.pref)
            self._carregar_base()

        def _reler_grupo(self):
            """O processo de download grava membros.json (nomes): sempre partir do disco."""
            if self.grupo:
                self.grupo = n.Grupo(self.grupo.pasta)

        def _carregar_base(self):
            self._reler_grupo()
            g = self.grupo
            self.base = n.Base(g) if g and g.tem_relatorio() else None
            # nomes que faltam vem do proprio curriculo
            if g and self.base:
                mudou = False
                for m in g.membros:
                    p = self.base.pessoas.get(m["id"])
                    if p and (not m.get("nome") or m["nome"] == m["id"]):
                        m["nome"] = p["nome"]
                        mudou = True
                if mudou:
                    g.salvar()
            self.menu_cat.delete(0, "end")
            antigas = {k: v.get() for k, v in self.v_cats.items()}
            self.v_cats = {}
            for c in sorted({(m.get("categoria") or "Sem categoria") for m in (g.membros if g else [])},
                            key=lambda c: (n.CATEGORIAS.index(c) if c in n.CATEGORIAS else 99, c)):
                v = tk.BooleanVar(value=antigas.get(c, True))
                self.v_cats[c] = v
                self.menu_cat.add_checkbutton(label=c, variable=v, command=self._recalcular)
            if self.base:
                anos = list(range(self.base.ano_min, self.base.ano_max + 1))
                for sp in (self.sp_de, self.sp_ate):
                    sp.configure(from_=anos[0], to=anos[-1])
                hoje = datetime.date.today().year
                self.presets = [("Último ano completo", hoje - 1, hoje - 1), ("Ano atual", hoje, hoje),
                                ("Últimos 3 anos", hoje - 2, hoje), ("Últimos 5 anos", hoje - 4, hoje),
                                ("Últimos 10 anos", hoje - 9, hoje),
                                ("Quadriênio CAPES 2021–2024", 2021, 2024), ("Quadriênio CAPES 2025–2028", 2025, 2028),
                                ("Todo o período", anos[0], anos[-1]), ("Personalizado", None, None)]
                self.cb_preset["values"] = [p[0] for p in self.presets]
                if not self.v_de.get():
                    de, ate = self.pref.get("de"), self.pref.get("ate")
                    if de and ate:
                        self.v_de.set(de)
                        self.v_ate.set(ate)
                        self._marcar_preset()
                    else:
                        self.cb_preset.current(3)
                        self._aplicar_preset(recalcular=False)
            self._mostrar_membros()
            self._listar_relatorios()
            self._recalcular()

        # ------------------------------------------------------ membros
        CAB_M = ["", "Nome", "Categoria", "ID Lattes", "Currículo", "Atualizado no Lattes"]

        def _mostrar_membros(self):
            g = self.grupo
            larg = [40, 330, 170, 150, 170, 150]
            if not g:
                self.t_m.mostrar(self.CAB_M, [], larg)
                self.lb_membros.configure(text="Crie um grupo para começar (botão “Novo grupo”, no alto).")
                return
            pessoas = self.base.pessoas if self.base else {}
            linhas = []
            ordem = {c: i for i, c in enumerate(n.CATEGORIAS)}
            for m in sorted(g.membros, key=lambda m: (ordem.get(m.get("categoria"), 99), m.get("categoria") or "", n.norm(m.get("nome") or m["id"]))):
                d = g.cv_data(m["id"])
                linhas.append(["✓" if m.get("incluir", True) else "–", m.get("nome") or "(o nome vem com o currículo)", m.get("categoria") or "",
                               m["id"], f"baixado em {d:%d/%m/%Y}" if d else "não baixado", pessoas.get(m["id"], {}).get("atualizado", "")])
            self.t_m.mostrar(self.CAB_M, linhas, larg)
            sem = sum(1 for m in g.membros if not g.cv_data(m["id"]))
            self.lb_membros.configure(text=f"{g.nome} · {n.qt(len(g.membros), 'membro', 'membros')}" + (f" · {sem} sem currículo baixado" if sem else ""))

        def _ids_selecionados(self):
            return [self.t_m.tv.item(s, "values")[3] for s in self.t_m.tv.selection()]

        def _clique_membro(self, e):
            if self.t_m.tv.identify_region(e.x, e.y) != "cell" or self.t_m.tv.identify_column(e.x) != "#1":
                return None
            linha = self.t_m.tv.identify_row(e.y)
            if not linha:
                return None
            self._reler_grupo()
            m = self.grupo.membro(self.t_m.tv.item(linha, "values")[3])
            if not m:
                return "break"
            m["incluir"] = not m.get("incluir", True)
            self.grupo.salvar()
            self.t_m.tv.set(linha, 0, "✓" if m["incluir"] else "–")
            self._agendar(self._recalcular, 150)
            return "break"

        def _duplo_membro(self, e):
            linha = self.t_m.tv.identify_row(e.y)
            if not linha or self.t_m.tv.identify_column(e.x) == "#1":
                return
            lid = self.t_m.tv.item(linha, "values")[3]
            self._reler_grupo()
            m = self.grupo.membro(lid)
            janela = tk.Toplevel(self)
            janela.title("Categoria")
            janela.configure(bg=CARTAO, padx=18, pady=14)
            janela.transient(self)
            janela.resizable(False, False)
            tk.Label(janela, text=m.get("nome") or lid, font=(FONTE, 10, "bold"), bg=CARTAO).pack(anchor="w")
            cb = ttk.Combobox(janela, values=n.CATEGORIAS, width=28)
            cb.set(m.get("categoria") or "")
            cb.pack(pady=10)
            cb.focus_set()

            def ok(*_):
                self._reler_grupo()
                mm = self.grupo.membro(lid)
                if mm:
                    mm["categoria"] = cb.get().strip()
                    self.grupo.salvar()
                janela.destroy()
                self._carregar_base()
            ttk.Button(janela, text="Salvar", style="Acento.TButton", command=ok).pack(anchor="e")
            janela.bind("<Return>", ok)
            janela.bind("<Escape>", lambda e: janela.destroy())
            janela.grab_set()

        def _adicionar(self):
            if not self.grupo:
                self._novo_grupo()
                if not self.grupo:
                    return
            self._reler_grupo()
            novos, repetidos = 0, 0
            cat = self.cb_cat_novo.get().strip()
            for linha in self.tx_ids.get("1.0", "end").splitlines():
                m = re.search(r"(\d{16})", linha)
                if not m:
                    continue
                lid = m.group(1)
                if self.grupo.membro(lid):
                    repetidos += 1
                    continue
                resto = re.sub(r"\S*lattes\.cnpq\.br/\d{16}\S*", "", linha).replace(lid, "")
                nome = re.sub(r"^[\s,;:\-–\t|]+|[\s,;:\-–\t|]+$", "", resto).strip()
                self.grupo.membros.append({"id": lid, "nome": nome, "categoria": cat, "incluir": True})
                novos += 1
            if not novos and not repetidos:
                messagebox.showinfo("Adicionar membros", "Nenhum ID Lattes de 16 dígitos encontrado no texto.", parent=self)
                return
            self.grupo.salvar()
            self.tx_ids.delete("1.0", "end")
            self._carregar_base()
            msg = f"{n.qt(novos, 'membro adicionado', 'membros adicionados')}."
            if repetidos:
                msg += f" {n.qt(repetidos, 'já estava', 'já estavam')} no grupo."
            self.lb_prog.configure(text=msg + " Clique em “Baixar só os novos” para buscar os currículos.")

        def _mudar_categoria(self):
            ids, cat = self._ids_selecionados(), self.cb_cat_sel.get().strip()
            if not ids or not cat:
                return
            self._reler_grupo()
            for lid in ids:
                m = self.grupo.membro(lid)
                if m:
                    m["categoria"] = cat
            self.grupo.salvar()
            self._carregar_base()

        def _remover(self):
            ids = self._ids_selecionados()
            if not ids or not messagebox.askyesno("Remover", f"Tirar {n.qt(len(ids), 'membro', 'membros')} do grupo?", parent=self):
                return
            self._reler_grupo()
            self.grupo.membros = [m for m in self.grupo.membros if m["id"] not in ids]
            self.grupo.salvar()
            self.lb_prog.configure(text="Removido. Clique em “Só recalcular” para tirar das estatísticas.")
            self._carregar_base()

        def _abrir_lattes(self):
            for lid in self._ids_selecionados()[:10]:
                webbrowser.open("http://lattes.cnpq.br/" + lid)

        # ------------------------------------------- download / scriptLattes
        def _botoes_tarefa(self, livre):
            for b in (self.bt_tudo, self.bt_faltam, self.bt_gerar):
                b.state(["!disabled"] if livre else ["disabled"])

        def _rodar(self, etapas):
            if self.tarefa or not self.grupo:
                return
            self._reler_grupo()
            if not self.grupo.membros:
                messagebox.showinfo("Atualizar", "Adicione membros antes (IDs Lattes).", parent=self)
                return
            self.etapas, self.log = list(etapas), []
            self._botoes_tarefa(False)
            self._proxima_etapa()

        def _proxima_etapa(self):
            if not self.etapas:
                self.tarefa = None
                self._fotos.clear()
                self._botoes_tarefa(True)
                self._carregar_base()
                return
            etapa = self.etapas.pop(0)
            args = {"baixar": ["--baixar"], "faltam": ["--baixar", "--faltam"], "gerar": ["--gerar"]}[etapa]
            exe = sys.executable
            if exe.lower().endswith("pythonw.exe") and os.path.exists(exe[:-5] + ".exe"):
                exe = exe[:-5] + ".exe"
            env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            self._fim_ok = False
            self.tarefa = subprocess.Popen([exe, ESTE] + args + [self.grupo.pasta], cwd=n.AQUI, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                           text=True, encoding="utf-8", errors="replace",
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if etapa == "gerar":
                self.pb.configure(mode="indeterminate", value=0)
                self.pb.start(12)
            else:
                self.pb.configure(mode="determinate", value=0)
            threading.Thread(target=self._ler_saida, args=(self.tarefa,), daemon=True).start()

        def _ler_saida(self, proc):
            for linha in proc.stdout:
                self.fila.put(linha.rstrip("\n"))
            proc.wait()
            self.fila.put(("fim_processo", proc.returncode))

        def _ler_fila(self):
            try:
                while True:
                    x = self.fila.get_nowait()
                    if isinstance(x, tuple):
                        self.pb.stop()
                        self.pb.configure(mode="determinate", maximum=1, value=1 if self._fim_ok else 0)
                        if x[1] != 0 and not self._fim_ok:
                            self.lb_prog.configure(text="Algo falhou. Clique em “Ver registro” para os detalhes.")
                            self.etapas = []
                        self._proxima_etapa()
                        continue
                    if x.startswith("@@ prog "):
                        _, _, k, total, txt = x.split(" ", 4)
                        if self.pb["mode"] == "determinate":
                            self.pb.configure(maximum=max(int(total), 1), value=int(k))
                        self.lb_prog.configure(text=txt)
                    elif x.startswith("@@ fim "):
                        _, _, estado, txt = x.split(" ", 3)
                        self.lb_prog.configure(text=txt)
                        self._fim_ok = estado == "ok"
                        if estado != "ok":
                            self.etapas = []
                    else:
                        self.log.append(x)
                        if len(self.log) > 4000:
                            del self.log[:1000]
                        if getattr(self, "tx_log", None) and self.tx_log.winfo_exists():
                            self.tx_log.insert("end", x + "\n")
                            self.tx_log.see("end")
            except queue.Empty:
                pass
            self.after(120, self._ler_fila)

        def _ver_log(self):
            j = tk.Toplevel(self)
            j.title("Registro")
            j.geometry(f"{self.px(820)}x{self.px(480)}")
            self.tx_log = tk.Text(j, font=("Consolas", 9), relief="flat", padx=8, pady=8)
            self.tx_log.pack(fill="both", expand=True)
            self.tx_log.insert("end", "\n".join(self.log) + ("\n" if self.log else "(vazio)\n"))
            self.tx_log.see("end")

        def _abrir_scriptlattes(self):
            if self.grupo and self.grupo.tem_relatorio():
                webbrowser.open(pathlib.Path(self.grupo.saida, "index.html").as_uri())

        # ----------------------------------------------------- periodo
        def _aplicar_preset(self, recalcular=True):
            _nome, de, ate = self.presets[self.cb_preset.current()]
            if de is None:
                return
            self.v_de.set(str(de))
            self.v_ate.set(str(ate))
            if recalcular:
                self._mudou_periodo()

        def _marcar_preset(self):
            try:
                de, ate = int(self.v_de.get()), int(self.v_ate.get())
            except ValueError:
                return
            for i, (_n, a, b) in enumerate(self.presets):
                if (a, b) == (de, ate):
                    self.cb_preset.current(i)
                    return
            self.cb_preset.current(len(self.presets) - 1)

        def _mudou_periodo(self):
            self._marcar_preset()
            self._agendar(self._recalcular, 250)

        def _periodo(self):
            try:
                a, b = int(self.v_de.get()), int(self.v_ate.get())
            except ValueError:
                return None
            if a > b:
                a, b = b, a
            return max(a, 1900), min(b, 2100)

        def _agendar(self, fn, ms):
            if self._agendado:
                self.after_cancel(self._agendado)
            self._agendado = self.after(ms, fn)

        # ----------------------------------------------------- calculo
        def _recalcular(self):
            self._agendado = None
            g, base = self.grupo, self.base
            per = self._periodo() if base else None
            cats_on = {c for c, v in self.v_cats.items() if v.get()}
            tudo = len(cats_on) == len(self.v_cats)
            self.mb_cat.configure(text="Todas" if tudo else (", ".join(sorted(cats_on)) or "Nenhuma")[:28])
            pronto = bool(base and per)
            for b in (self.bt_excel, self.bt_relatorio):
                b.state(["!disabled"] if pronto else ["disabled"])
            if not pronto:
                self.est = None
                msg = ("Crie um grupo para começar (botão “Novo grupo”, no alto)." if not g else
                       "Adicione os membros na aba Membros e clique em “Atualizar tudo”." if not g.membros else
                       "Clique em “Atualizar tudo” (aba Membros) para baixar os currículos e gerar as estatísticas.")
                self.status.configure(text=msg)
                self.lb_sel.configure(text="")
                self._limpar_abas(msg)
                return
            self.pref["de"], self.pref["ate"] = str(per[0]), str(per[1])
            n.gravar_json(n.PREFERENCIAS, self.pref)
            sel = [m["id"] for m in g.membros if m.get("incluir", True) and (m.get("categoria") or "Sem categoria") in cats_on and m["id"] in base.pessoas]
            self.est = n.com_anterior(base, sel, *per)
            self.lb_sel.configure(text=f"{n.qt(len(sel), 'membro', 'membros')} nas estatísticas")
            datas = [d for d in (g.cv_data(i) for i in base.pessoas) if d]
            self.status.configure(text=f"{n.qt(len(base.pessoas), 'currículo processado', 'currículos processados')}"
                                  + (f" · baixados entre {min(datas):%d/%m/%Y} e {max(datas):%d/%m/%Y}" if datas else "")
                                  + " · trabalhos repetidos entre currículos contam uma vez")
            self._preencher_abas()

        def _limpar_abas(self, msg):
            self.lb_resumo.configure(text="Sem dados ainda")
            self.lb_resumo_sub.configure(text=msg)
            for v, t, d, s in self.cards:
                v.configure(text="–")
                for x in (t, d, s):
                    x.configure(text="")
            for tab in list(self.tabs.values()) + [self.t_or_res, self.t_itens, self.t_ind]:
                tab.mostrar([""], [])
            self.tx.delete("1.0", "end")
            self.catalogo = []
            self.lst_graf.delete(0, "end")
            self.cb_graf_resumo["values"] = []
            self.g_resumo.mostrar(None)
            self.g_principal.mostrar(None)
            self.lb_graf.configure(text="")
            self._mostrar_equipe()

        def _delta(self, atual, cats):
            ant = self.est.anterior
            if ant is None:
                return "", MUDO
            antes = sum(ant.n[c] for c in cats)
            v = n.variacao(atual, antes)
            if v is None:
                return f"antes: {n.num(antes)} ({ant.a}–{ant.b})", MUDO
            seta = "▲" if v > 0 else "▼" if v < 0 else "="
            return f"{seta} {abs(v)}% vs {ant.a}–{ant.b} ({n.num(antes)})", (marca.SUBIU if v > 0 else marca.DESCEU if v < 0 else MUDO)

        def _preencher_abas(self):
            est, base, g = self.est, self.base, self.grupo
            per = f"{est.a}" if est.a == est.b else f"{est.a}–{est.b}"
            self.lb_resumo.configure(text=f"{g.nome} · {per}")
            self.lb_resumo_sub.configure(text=f"{n.qt(len(est.sel), 'membro considerado', 'membros considerados')}. "
                                         "Orientações em andamento e projetos contam os ativos no período; a comparação é com o período anterior de mesma duração.")
            N = est.n

            def nivel(pre):
                return " · ".join(f"{a} {N[pre + k]}" for k, a in (("doutorado", "D"), ("mestrado", "M"), ("ic", "IC"), ("tcc", "TCC"), ("posdoc", "PD")) if N[pre + k])
            pct = f"{round(100 * est.artigos_parceria / N['artigos'])}% com 2+ membros do grupo" if N["artigos"] else ""
            dados = [
                (["artigos"], "Artigos em periódicos", (f"+ {N['aceitos']} aceitos · " if N["aceitos"] else "") + pct, True),
                (["completos"], "Trabalhos completos em eventos", f"{N['expandidos'] + N['resumos']} resumos em eventos", True),
                (["livros", "capitulos"], "Livros e capítulos", f"{N['livros']} livros · {N['capitulos']} capítulos", True),
                (n.OC, "Orientações concluídas", nivel("oc_"), True),
                (n.OA, "Orientações em andamento", nivel("oa_"), False),
                (n.PJ, "Projetos ativos", f"{est.coordenados} coordenados pelo grupo", False),
                (["software", "patentes", "tecnica"], "Produção técnica", f"{N['software']} softwares · {N['patentes']} patentes/registros", True),
                (["premios"], "Prêmios e títulos", "", True),
                (["bancas"], "Participações em bancas", "", True),
                (["ev_part", "ev_org"], "Eventos", f"{N['ev_part']} participações · {N['ev_org']} organizados", True),
            ]
            for (v, t, d, s), (cats, titulo, sub, comparar) in zip(self.cards, dados):
                valor = sum(N[c] for c in cats)
                v.configure(text=n.num(valor))
                t.configure(text=titulo)
                txt, cor = self._delta(valor, cats) if comparar else ("", MUDO)
                d.configure(text=txt, fg=cor)
                s.configure(text=sub)

            self.catalogo = n.graficos(est, base, g)
            titulos = [t for _k, t, _s in self.catalogo]
            sel_lista = self.lst_graf.curselection()
            self.lst_graf.delete(0, "end")
            for t in titulos:
                self.lst_graf.insert("end", "  " + t)
            self.lst_graf.selection_set(sel_lista[0] if sel_lista else 0)
            self._mostrar_grafico()
            atual = self.cb_graf_resumo.get()
            self.cb_graf_resumo["values"] = titulos
            self.cb_graf_resumo.set(atual if atual in titulos else titulos[0])
            self._grafico_resumo()

            cab, l = n.tabela_indicadores(est, base, g)
            self.t_ind.mostrar(cab, l, [230, 80, 300])
            self.tabs["ind"].mostrar(cab, l, [320, 120, 420])
            cab, l = n.tabela_por_ano(est)
            self.tabs["ano"].mostrar(cab, l, [300] + [62] * (len(cab) - 1))
            cab, l = n.tabela_por_membro(est, base, g)
            self.tabs["membro"].mostrar(cab, l)
            cab, l = n.tabela_orientacoes_resumo(est)
            self.t_or_res.mostrar(cab, l, [300, 180, 160], total=True)
            cab, l = n.tabela_orientacoes(est, base)
            self.tabs["orient"].mostrar(cab, l, [110, 210, 60, 240, 520, 260])
            cab, l = n.tabela_projetos(est, base)
            self.tabs["proj"].mostrar(cab, l, [120, 60, 60, 520, 240, 300])
            cab, l = n.tabela_veiculos(est)
            self.tabs["veic"].mostrar(cab, l, [100, 640, 90])
            self._mostrar_itens()
            self.tx.delete("1.0", "end")
            self.tx.insert("1.0", n.texto_relatorio(est, g, base))
            self._mostrar_equipe()

        def _mostrar_itens(self):
            if not self.est:
                return
            cats = self.tipos_itens[self.cb_tipo.current()][1]
            cab, l = n.tabela_itens(self.est, self.base, cats, self.v_busca.get())
            self.t_itens.mostrar(cab, l, [210, 55, 460, 300, 260, 160, 240])
            self.lb_itens.configure(text=n.qt(len(l), "item", "itens"))

        # ----------------------------------------------------- graficos
        def _grafico_atual(self):
            sel = self.lst_graf.curselection()
            return self.catalogo[sel[0]] if sel and self.catalogo else None

        def _mostrar_grafico(self):
            g = self._grafico_atual()
            if not g:
                return
            chave, titulo, spec = g
            per = f"{self.est.a}" if self.est.a == self.est.b else f"{self.est.a}–{self.est.b}"
            self.lb_graf.configure(text=titulo)
            sub = {"rede": "Cada círculo é um membro (tamanho: produção no período); cada linha, trabalhos em comum. Os nomes aparecem nos mais conectados.",
                   "membros": "Cada membro conta os artigos do seu currículo; um artigo em parceria conta para todos os autores do grupo."}.get(chave, "")
            self.lb_graf_sub.configure(text=f"{self.grupo.nome} · {per}" + (f" · {sub}" if sub else ""))
            self.g_principal.mostrar(spec)

        def _grafico_resumo(self):
            t = self.cb_graf_resumo.get()
            for _k, titulo, spec in self.catalogo:
                if titulo == t:
                    self.g_resumo.mostrar(spec)
                    return

        def _salvar_grafico(self, formato):
            g = self._grafico_atual()
            if not g or not self.est:
                return
            chave, titulo, spec = g
            nome = re.sub(r"[^\w\- ]+", "", f"{titulo} {self.grupo.nome} {self.est.a}-{self.est.b}").strip()
            caminho = filedialog.asksaveasfilename(parent=self, title="Salvar gráfico", defaultextension="." + formato,
                                                   initialfile=nome + "." + formato, initialdir=self._pasta_rel(),
                                                   filetypes=[("Imagem PNG", "*.png")] if formato == "png" else [("Imagem SVG", "*.svg")])
            if not caminho:
                return
            h = gr.altura_sugerida(spec)
            try:
                if formato == "png":
                    gr.png(spec, caminho, 1000, h)
                else:
                    with open(caminho, "w", encoding="utf-8") as f:
                        f.write(gr.svg(spec, 1000, h).replace('width="100%"', 'width="1000" height="%d"' % h, 1))
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Salvar gráfico", f"Não foi possível salvar:\n{e}", parent=self)
                return
            self.status.configure(text="Gráfico salvo em " + caminho)

        def _copiar_dados_grafico(self):
            g = self._grafico_atual()
            if not g:
                return
            spec = g[2]
            if spec["tipo"] == "colunas":
                linhas = [["Ano"] + [s[0] for s in spec["series"]]] + [[c] + [s[1][i] for s in spec["series"]] for i, c in enumerate(spec["categorias"])]
            elif spec["tipo"] == "barras":
                linhas = [["Item", "Valor"]] + [[r, v] for r, v in zip(spec["rotulos"], spec["valores"])]
            else:
                nomes = {i: nome for i, nome, _p, _g in spec["nos"]}
                linhas = [["Membro", "Membro", "Trabalhos em comum"]] + sorted([[nomes.get(a, a), nomes.get(b, b), p] for a, b, p in spec["arestas"]], key=lambda r: -r[2])
            self.clipboard_clear()
            self.clipboard_append("\n".join("\t".join(str(x) for x in r) for r in linhas))
            self.status.configure(text="Dados do gráfico copiados (cole no Excel).")

        # ----------------------------------------------------- relatorios
        def _pasta_rel(self):
            if not self.grupo:
                return n.AQUI
            os.makedirs(self.grupo.relatorios, exist_ok=True)
            return self.grupo.relatorios

        def _gerar_relatorio(self):
            if not self.est:
                return
            secoes = [k for k, v in self.v_secoes.items() if v.get()]
            if not secoes:
                messagebox.showinfo("Relatório", "Marque ao menos uma seção (aba Relatórios).", parent=self)
                return
            nome = re.sub(r"[^\w\- ]+", "", f"Relatório {self.grupo.nome} {self.est.a}-{self.est.b}").strip()
            caminho = os.path.join(self._pasta_rel(), f"{nome} ({datetime.datetime.now():%Y-%m-%d %Hh%M}).html")
            try:
                conteudo = relatorio.gerar(self.est, self.base, self.grupo, secoes)
                with open(caminho, "w", encoding="utf-8") as f:
                    f.write(conteudo)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Relatório", f"Não foi possível gerar o relatório:\n{e}", parent=self)
                return
            self._listar_relatorios()
            self.status.configure(text="Relatório salvo em " + caminho)
            webbrowser.open(pathlib.Path(caminho).as_uri())

        def _listar_relatorios(self):
            linhas = []
            if self.grupo and os.path.isdir(self.grupo.relatorios):
                for arq in sorted(os.listdir(self.grupo.relatorios), key=lambda a: -os.path.getmtime(os.path.join(self.grupo.relatorios, a))):
                    c = os.path.join(self.grupo.relatorios, arq)
                    if os.path.isfile(c):
                        linhas.append([arq, f"{datetime.datetime.fromtimestamp(os.path.getmtime(c)):%d/%m/%Y %H:%M}", f"{os.path.getsize(c) // 1024 + 1} KB"])
            self.t_rel.mostrar(["Arquivo", "Salvo em", "Tamanho"], linhas, [560, 150, 90])

        def _rel_selecionados(self):
            return [os.path.join(self.grupo.relatorios, self.t_rel.tv.item(s, "values")[0]) for s in self.t_rel.tv.selection()] if self.grupo else []

        def _abrir_relatorio_sel(self):
            for c in self._rel_selecionados()[:5]:
                n.abrir(c)

        def _abrir_pasta_relatorios(self):
            if self.grupo:
                n.abrir(self._pasta_rel())

        def _excluir_relatorio(self):
            sel = self._rel_selecionados()
            if sel and messagebox.askyesno("Excluir", f"Excluir {n.qt(len(sel), 'arquivo', 'arquivos')}?", parent=self):
                for c in sel:
                    try:
                        os.remove(c)
                    except OSError:
                        pass
                self._listar_relatorios()

        # ----------------------------------------------------- saidas
        def _copiar_texto(self):
            self.clipboard_clear()
            self.clipboard_append(self.tx.get("1.0", "end").strip())
            self.status.configure(text="Texto copiado.")

        def _exportar(self):
            est, base, g = self.est, self.base, self.grupo
            if not est:
                return
            nome = re.sub(r"[^\w\- ]+", "", g.nome).strip() or "grupo"
            caminho = filedialog.asksaveasfilename(parent=self, title="Exportar para Excel", defaultextension=".xlsx",
                                                   initialfile=f"Estatísticas {nome} {est.a}-{est.b}.xlsx", initialdir=self._pasta_rel(),
                                                   filetypes=[("Planilha do Excel", "*.xlsx")])
            if not caminho:
                return
            resumo = [["Grupo", g.nome], ["Período", f"{est.a} a {est.b}"], ["Membros considerados", len(est.sel)],
                      ["Gerado em", f"{datetime.date.today():%d/%m/%Y}"], ["Gerado com", f"{marca.NOME} {marca.VERSAO}"], ["", ""]]
            for cat in n.CATS:
                if est.n[cat]:
                    resumo.append([f"{n.CATS[cat][1]} · {n.rotulo(cat)}", est.n[cat]])
            abas = [("Resumo", ["Indicador", "Valor"], resumo),
                    ("Indicadores",) + n.tabela_indicadores(est, base, g),
                    ("Por ano",) + n.tabela_por_ano(est),
                    ("Por membro",) + n.tabela_por_membro(est, base, g),
                    ("Orientações",) + n.tabela_orientacoes(est, base),
                    ("Projetos",) + n.tabela_projetos(est, base),
                    ("Periódicos e eventos",) + n.tabela_veiculos(est),
                    ("Itens",) + n.tabela_itens(est, base),
                    ("Texto", ["Texto para relatório"], [[p] for p in n.texto_relatorio(est, g, base).split("\n\n")])]
            try:
                n.salvar_excel(caminho, abas)
            except ImportError:
                messagebox.showerror("Exportar", "Falta a biblioteca openpyxl. Rode “python iniciar.py --instalar”.", parent=self)
                return
            except PermissionError:
                messagebox.showerror("Exportar", "Não deu para salvar: a planilha está aberta no Excel?", parent=self)
                return
            self._listar_relatorios()
            self.status.configure(text="Planilha salva em " + caminho)
            if messagebox.askyesno("Exportar", "Planilha salva. Abrir agora?", parent=self):
                n.abrir(caminho)

        def _aba_mudou(self):
            atual = [k for k, f in self.abas.items() if str(f) == self.nb.select()]
            sem_filtro = atual and atual[0] in ("membros", "sobre")
            if sem_filtro:
                self.filtros.pack_forget()
            elif not self.filtros.winfo_ismapped():
                self.filtros.pack(fill="x", before=self.nb)

        def _fechar(self):
            if self.tarefa and self.tarefa.poll() is None:
                if not messagebox.askyesno("Sair", "Há uma atualização em andamento. Interromper e sair?", parent=self):
                    return
                self.tarefa.kill()
            self.destroy()

    app = App()
    app._aba_mudou()
    return app


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--baixar":
        n.cmd_baixar(sys.argv[-1], "--faltam" in sys.argv)
    elif len(sys.argv) >= 3 and sys.argv[1] == "--gerar":
        n.cmd_gerar(sys.argv[-1])
    else:
        interface().mainloop()
