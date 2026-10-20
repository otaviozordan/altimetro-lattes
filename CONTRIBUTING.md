# Como contribuir

Obrigado pelo interesse em melhorar o Altímetro!

## Relatar um problema ou sugerir algo

Abra uma *issue* contando:

- o sistema (Windows, macOS ou Linux) e a versão do Python (`python --version`);
- o que você fez, o que esperava e o que aconteceu;
- o registro da atualização, se o problema foi no download ou no scriptLattes (aba **Gerenciar membros → Ver registro**).

Não anexe a pasta `grupos/` nem currículos inteiros. Se precisar de um exemplo, um ID Lattes público basta.

## Mandar uma alteração

1. Faça um *fork* e crie um ramo (`git checkout -b minha-melhoria`).
2. Rode o programa com `python iniciar.py` e confira a sua mudança com um grupo de teste.
3. Mantenha o estilo do código: nomes e comentários em português, funções curtas e sem dependências novas sem necessidade (o programa precisa continuar simples de instalar em Windows, macOS e Linux).
4. Abra um *pull request* explicando o que mudou e por quê.

Ao contribuir, você concorda que o seu código seja distribuído sob a licença do projeto (GPL-3.0).

## Onde mexer

| Quero... | Arquivo |
|---|---|
| uma métrica ou tabela nova | `nucleo.py` (`indicadores`, `tabela_*`) |
| um gráfico novo | `nucleo.py` (`graficos`) e, para um tipo novo de desenho, `graficos.py` |
| mudar o relatório HTML | `relatorio.py` |
| mudar a janela | `altimetro.py` |
| mudar cores ou logo | `marca.py` |
| ajustar a leitura do Lattes | `scriptLattes/` (marque a alteração com `# Altimetro:`) |
