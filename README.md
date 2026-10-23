# Elencos da Série A

**Veja o projeto:** https://lucasnvieira.github.io/elencos-serie-a/

Relatório de coleta e limpeza de dados: como montei uma base com os elencos do Campeonato Brasileiro Série A de 2016 a 2025, da coleta nas páginas de elenco da ESPN Brasil até a busca, em outras fontes, pelas alturas que faltavam.

## O que o relatório mostra

- **Coleta:** 200 páginas de elenco (20 clubes em 10 temporadas), coletadas com Python (requests e Selenium) depois de um mapeamento simples das requisições do site.
- **Modelagem:** o arquivo único da coleta virou um banco relacional com 5 tabelas ligadas por chaves (diagrama no passo 03).
- **Limpeza e conferências:** vazios viram NULL, textos são aparados, e o script para na primeira conferência que falha (20 clubes por ano, campeão na 1ª posição, chaves únicas e ligadas).
- **Altura em polegadas:** a ESPN guarda a altura em polegadas inteiras, então só existem 19 valores diferentes.
- **Cobertura de altura:** de 89,9% para 96,3% das linhas de elenco, com Wikidata, Wikipedia e Transfermarkt, sem nenhuma altura estimada.
- **O caso Jordan:** dois jogadores com o mesmo nome que a busca automática juntou e a conferência manual separou.

## Estrutura

```
app/index.html            o relatório (HTML, CSS e JavaScript, sem dependências)
scripts/preparar_app.py   o script que monta as tabelas e faz as conferências
```

## Dados e licenças

A base completa **não é publicada** neste repositório. Os elencos e a maior parte das alturas vêm da ESPN, e parte das alturas vem do Transfermarkt, e os termos de uso dos dois não autorizam a redistribuição. O relatório mostra só contagens, médias e poucos exemplos individuais, necessários para explicar o processo. A seção 10 do relatório detalha cada fonte e a sua licença.

| fonte | uso | licença ou termos |
|---|---|---|
| ESPN Brasil | elencos, posições, nacionalidades e 3.049 alturas | não autoriza a redistribuição |
| Transfermarkt | 186 alturas | não autoriza a redistribuição |
| Wikipedia (en e pt) | 189 alturas | CC BY-SA 4.0 |
| Wikidata | 25 alturas | CC0 |

Este é um projeto educacional.

## Reproduzir no seu computador

Só é preciso se você quiser ver o relatório sem internet ou mexer nele. Como a base não é publicada, o script de `scripts/` serve como referência do método e não roda sozinho.

```bash
python -m http.server 8765 --directory app
```

Depois, abra http://localhost:8765 no navegador (o endereço aponta para o seu próprio computador).

## Licença

Código (`app/` e `scripts/`): [MIT](LICENSE). Os números do relatório pertencem às fontes acima e não estão cobertos pela licença MIT.
