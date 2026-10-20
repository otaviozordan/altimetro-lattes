<p align="center">
  <img src="marca/logo-128.png" width="96" alt="Logo do Altímetro: um mostrador com o ponteiro subindo sobre barras">
</p>

<h1 align="center">Altímetro</h1>

<p align="center"><strong>Métricas de grupos de pesquisa a partir do Currículo Lattes</strong><br>
Windows · macOS · Linux · software livre (GPL-3.0)</p>

---

O Altímetro levanta, em poucos cliques, os números de um grupo de pesquisa para relatórios, editais, avaliações da CAPES e prestação de contas: produção bibliográfica e técnica, orientações, projetos, prêmios, bancas, eventos e a colaboração entre os membros, em qualquer período.

Você só informa o **ID Lattes** de cada membro. O programa baixa os currículos públicos, processa tudo com o [scriptLattes](https://github.com/jpmenachalco/scriptLattes) e mostra o resultado numa janela, com gráficos, tabelas e relatório pronto.

## O que ele faz

- **Equipe:** quem está no grupo, com a foto do Lattes e os números de cada pessoa no período. Um clique abre a ficha individual, com a produção por ano e as parcerias dentro do grupo.
- **Resumo:** artigos, trabalhos em eventos, livros e capítulos, orientações, projetos, produção técnica, prêmios, bancas e eventos, com a comparação com o período anterior de mesma duração ("▲ 30% vs 2017–2021").
- **Indicadores:** artigos por docente por ano, orientações por docente, colaboração interna (artigos com dois ou mais membros), artigos com DOI, membros com produção, periódicos distintos e projetos coordenados pelo grupo.
- **Gráficos:**
  - por ano: produção, artigos, orientações por nível, projetos ativos e produção técnica;
  - por pessoa e categoria: artigos por membro e produção por categoria de membro;
  - periódicos e eventos mais frequentes;
  - composição do grupo e rede de colaboração entre os membros.

  Todos podem ser salvos em PNG ou SVG.
- **Tabelas:** por ano, por membro, orientações, projetos, periódicos e eventos. Um clique no cabeçalho ordena, e o botão direito copia (cola direto no Excel ou no Word).
- **Relatório:** um arquivo HTML com equipe, números, indicadores, gráficos, tabelas e um texto descritivo pronto. Abre no navegador e pode ser impresso ou salvo em PDF.
- **Excel:** todas as tabelas numa planilha.
- **Períodos prontos:** último ano, últimos 3, 5 ou 10 anos e os quadriênios da CAPES. Também dá para filtrar por categoria de membro (docentes, doutorandos, egressos...).

Um trabalho que aparece no currículo de mais de um membro conta **uma vez** para o grupo (pelo DOI ou pelo título e ano) e uma vez para cada pessoa.

## Instalação

Você precisa do **Python 3.9 ou mais novo** e do **Google Chrome**. O Chrome é usado para baixar os currículos, porque o Lattes só entrega a página a um navegador de verdade.

1. Baixe o projeto: botão **Code → Download ZIP** nesta página (e descompacte), ou

   ```sh
   git clone https://github.com/otaviozordan/altimetro-lattes.git
   ```

2. Abra pelo lançador do seu sistema:

   | Sistema | Como abrir |
   |---|---|
   | Windows | duplo clique em `Altimetro-Windows.bat` |
   | macOS | duplo clique em `Altimetro-macOS.command` (na primeira vez: botão direito → Abrir) |
   | Linux | `./altimetro-linux.sh` |

Na primeira vez, o lançador cria um ambiente Python só do programa (`.venv/`) e instala as bibliotecas, o que leva alguns minutos. Nas seguintes, abre direto.

<details>
<summary>Se faltar algo no Linux ou no macOS</summary>

- **Debian/Ubuntu:** `sudo apt install python3 python3-venv python3-tk`
- **Fedora:** `sudo dnf install python3 python3-tkinter`
- **Arch:** `sudo pacman -S python tk`
- **macOS:** prefira o Python do [python.org](https://www.python.org/downloads/macos/), que já vem com o Tkinter. Com Homebrew: `brew install python python-tk`.

Também dá para rodar à mão: `python3 iniciar.py`. Para reinstalar as bibliotecas: `python3 iniciar.py --instalar`.
</details>

## Como usar

1. **Novo grupo** (no alto) e dê o nome do grupo.
2. Em **Gerenciar membros**, cole os IDs Lattes (16 dígitos) ou os links `http://lattes.cnpq.br/...`, um por linha, escolha a categoria e clique em **Adicionar**. O nome e a foto de cada pessoa vêm do próprio currículo.
3. Clique em **Atualizar tudo**. O download leva uns 20 segundos por currículo, e a janela fica livre enquanto isso.
4. Escolha o **período** e as **categorias** no alto e navegue pelas abas.
5. **Salvar relatório** gera o HTML; **Exportar Excel** gera a planilha.

Para atualizar depois, use **Atualizar tudo** (baixa todos de novo) ou **Baixar só os novos**.

## Privacidade

O Altímetro usa apenas dados **públicos** do Currículo Lattes. Tudo fica no seu computador, na pasta `grupos/`: currículos, fotos, relatórios e a lista de membros. Nada é enviado para servidor nenhum. A pasta `grupos/` está no `.gitignore`, para não ir parar num repositório por engano.

## Estrutura

| Arquivo | Papel |
|---|---|
| `iniciar.py` | prepara o ambiente na primeira vez e abre o programa |
| `altimetro.py` | a janela (Tkinter) |
| `nucleo.py` | grupos, download, leitura dos dados do scriptLattes, métricas, tabelas, texto e Excel |
| `graficos.py` | gráficos desenhados na tela, em SVG e em PNG a partir da mesma especificação |
| `relatorio.py` | relatório em HTML |
| `marca.py`, `marca/` | nome, cores e logo (`python marca.py` regera as imagens) |
| `scriptLattes/` | o scriptLattes, que baixa e processa os currículos |

Cada grupo fica em `grupos/<nome>/`, com `membros.json`, `cache/` (currículos), `fotos/`, `saida/` (o que o scriptLattes gera; `index.html` é o relatório completo dele) e `relatorios/`.

## Créditos e licença

Criado por **Otávio Zordan Alves** — Engenharia Mecânica Aeronáutica, **UNIFEI** (Universidade Federal de Itajubá).

O Altímetro é software livre, sob a [GNU General Public License v3.0](LICENSE): você pode usar, estudar, modificar e redistribuir, mantendo a mesma licença.

A pasta `scriptLattes/` traz o **scriptLattes** de Jesús P. Mena-Chalco e Roberto M. Cesar-Jr. (GPL-2.0 ou posterior). Se usar o Altímetro num trabalho acadêmico, cite também o scriptLattes:

> Mena-Chalco, J. P.; Cesar-Jr., R. M. *scriptLattes: an open-source knowledge extraction system from the Lattes Platform*. Journal of the Brazilian Computer Society, v. 15, n. 4, p. 31–39, 2009.

A cópia incluída tem pequenas alterações, marcadas no código com `# Altimetro:`:
- usa o Selenium Manager quando não há `chromedriver` na pasta;
- lê os arquivos `.config` e `.list` em UTF-8;
- é compatível com o networkx 3.4 ou mais novo;
- tira telefone e fax do endereço profissional nas páginas geradas.

Os dados vêm da Plataforma Lattes (CNPq). O Altímetro não tem vínculo com o CNPq.

## Contribuir

Sugestões, problemas e melhorias são bem-vindos. Veja [CONTRIBUTING.md](CONTRIBUTING.md).
