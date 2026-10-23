"""Gera as tabelas do app a partir da base de elencos da Série A coletada na ESPN.

Uso (a partir da raiz do projeto):
  python scripts/preparar_app.py dados/base_espn          gera a versão 2 em dados/versoes/v2/
  python scripts/preparar_app.py dados/base_espn --app    também troca os dados do app pela versão 2

A versão 1 está congelada em dados/versoes/v1/ e na tag base-v1 do git (ver dados/RECONSTRUCAO.md).

Entrada (saídas do consolidar.py da base, em UTF-8 com BOM):
  elencos_serie_a.csv  uma linha por (temporada, time, jogador)
  jogadores.csv        uma linha por jogador, com os atributos do cadastro
  links.csv            os clubes de cada temporada, na ordem da classificação final
e os complementos feitos à mão, em dados/complementos/:
  estados.csv          as 27 unidades da federação, com a região
  clubes_sede.csv      cidade e UF da sede de cada clube
  alturas.csv          alturas que a ESPN não informa, cada uma com a fonte
  ids_unificados.csv   jogadores com dois IDs na ESPN: qual ID sai e qual fica

Gera, em dados/versoes/v2/:
  estados.csv, clubes.csv, jogadores.csv, elencos.csv, classificacao.csv
  futebol.sqlite        as mesmas tabelas, com chaves, para estudar fora do app
e, com --app, app/dados.js (os dados embutidos no app; não edite à mão)
"""
import argparse
import csv
import json
import os
import sqlite3
from collections import Counter, defaultdict

# Esquema do app: tipos em DuckDB (os mesmos nomes servem no SQLite) e a
# descrição que aparece no painel de tabelas. A ordem das colunas é a da tabela.
ESQUEMA = {
    "estados": {
        "descricao": "As 27 unidades da federação, com a região do IBGE",
        "colunas": [
            ("uf", "VARCHAR", "Sigla da UF (chave)"),
            ("estado", "VARCHAR", "Nome da UF"),
            ("regiao", "VARCHAR", "Norte, Nordeste, Centro-Oeste, Sudeste ou Sul"),
        ],
        "chave": ["uf"],
    },
    "elencos": {
        "descricao": "Quem estava no elenco de cada clube em cada temporada",
        "colunas": [
            ("temporada", "INTEGER", "Ano do Brasileirão (2016 a 2025)"),
            ("time_id", "INTEGER", "Clube, ligado a clubes.time_id"),
            ("jogador_id", "INTEGER", "Jogador, ligado a jogadores.jogador_id"),
            ("camisa", "INTEGER", "Número da camisa; NULL quando a ESPN não informa"),
            ("multi_clube_temporada", "INTEGER", "1 se o jogador esteve em dois clubes no mesmo ano"),
            ("fonte_elenco", "VARCHAR", "De onde veio a linha (ver notas)"),
        ],
        "chave": ["temporada", "time_id", "jogador_id"],
    },
    "jogadores": {
        "descricao": "Um registro por jogador, com o cadastro atual na ESPN",
        "colunas": [
            ("jogador_id", "INTEGER", "ID do jogador na ESPN (chave)"),
            ("jogador_nome", "VARCHAR", "Nome como a ESPN exibe; há nomes repetidos"),
            ("posicao", "VARCHAR", "Goleiro, Defensor, Meio-campista ou Atacante"),
            ("altura_m", "DOUBLE", "Altura em metros; NULL quando nenhuma fonte informa"),
            ("fonte_altura", "VARCHAR", "espn ou a fonte que completou a altura; NULL sem altura"),
            ("nacionalidade", "VARCHAR", "País, em português; NULL quando a ESPN não informa"),
        ],
        "chave": ["jogador_id"],
    },
    "clubes": {
        "descricao": "Os clubes que jogaram a Série A entre 2016 e 2025",
        "colunas": [
            ("time_id", "INTEGER", "ID do clube na ESPN (chave)"),
            ("time_nome", "VARCHAR", "Nome atual, como a ESPN exibe"),
            ("time_slug", "VARCHAR", "Nome do clube na URL da ESPN"),
            ("cidade", "VARCHAR", "Cidade da sede do clube"),
            ("uf", "VARCHAR", "UF da sede, ligada a estados.uf"),
        ],
        "chave": ["time_id"],
    },
    "classificacao": {
        "descricao": "A posição final de cada clube em cada temporada",
        "colunas": [
            ("temporada", "INTEGER", "Ano do Brasileirão"),
            ("time_id", "INTEGER", "Clube, ligado a clubes.time_id"),
            ("posicao_final", "INTEGER", "1 = campeão; 17 a 20 = rebaixados"),
        ],
        "chave": ["temporada", "time_id"],
    },
}

# Conferência da ordem de links.csv: o 1º clube de cada ano tem de ser o campeão.
CAMPEOES = {
    2016: "palmeiras", 2017: "corinthians", 2018: "palmeiras", 2019: "flamengo", 2020: "flamengo",
    2021: "atletico-mg", 2022: "palmeiras", 2023: "palmeiras", 2024: "botafogo", 2025: "flamengo",
}


def ler_csv(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def numero(v, tipo):
    v = v.strip()
    return tipo(v) if v else None


def texto(v):
    # alguns nomes vêm da ESPN com espaço no fim ("Júnior "), o que separaria o mesmo jogador em dois
    v = v.strip()
    return v or None


def montar(pasta, complementos):
    base_elencos = ler_csv(os.path.join(pasta, "elencos_serie_a.csv"))
    base_jogadores = ler_csv(os.path.join(pasta, "jogadores.csv"))
    links = ler_csv(os.path.join(pasta, "links.csv"))
    estados = [(r["uf"], r["estado"], r["regiao"]) for r in ler_csv(os.path.join(complementos, "estados.csv"))]
    sedes = {int(r["time_id"]): (r["time_slug"], r["cidade"], r["uf"])
             for r in ler_csv(os.path.join(complementos, "clubes_sede.csv"))}
    alturas_extra = ler_csv(os.path.join(complementos, "alturas.csv"))
    unificados = {int(r["jogador_id"]): int(r["jogador_id_fica"])
                  for r in ler_csv(os.path.join(complementos, "ids_unificados.csv"))}

    clubes = {}
    for r in base_elencos:
        clube = (int(r["time_id"]), texto(r["time_nome"]), texto(r["time_slug"]))
        assert clubes.setdefault(clube[0], clube) == clube, f"clube com dois nomes: {clube}"
    assert set(sedes) == set(clubes), "clubes_sede.csv não tem exatamente os clubes da base"
    for tid, (slug, cidade, uf) in sedes.items():
        assert slug == clubes[tid][2], f"clubes_sede.csv: {tid} é {clubes[tid][2]}, não {slug}"
        clubes[tid] += (cidade, uf)

    jogadores = {}
    for r in base_jogadores:
        altura = numero(r["altura_m"], float)
        j = (int(r["jogador_id"]), texto(r["jogador_nome"]), texto(r["posicao"]),
             altura, "espn" if altura is not None else None, texto(r["nacionalidade"]))
        assert j[0] not in jogadores, f"jogador repetido: {j}"
        jogadores[j[0]] = j

    elencos = []
    for r in base_elencos:
        jid = int(r["jogador_id"])
        # posição, altura e nacionalidade são do cadastro: têm de bater com a tabela de jogadores
        cadastro = (texto(r["posicao"]), numero(r["altura_m"], float), texto(r["nacionalidade"]))
        j = jogadores[jid]
        espn = (j[2], j[3] if j[4] == "espn" else None, j[5])
        assert cadastro == espn, f"atributo diferente entre tabelas: {jid}"
        elencos.append((int(r["temporada"]), int(r["time_id"]), jid, numero(r["camisa"], int),
                        int(r["multi_clube_temporada"]), texto(r["fonte_elenco"])))

    # a mesma pessoa com dois IDs na ESPN: o ID duplicado sai de jogadores e as linhas
    # de elenco dele passam para o ID que fica, com o cadastro (posição etc.) desse ID
    for dup, fica in unificados.items():
        assert dup in jogadores and fica in jogadores, f"ids_unificados.csv: {dup} ou {fica} não está na base"
        assert fica not in unificados, f"ids_unificados.csv: {fica} também está marcado como duplicado"
        assert jogadores[dup][1] == jogadores[fica][1], f"ids_unificados.csv: nomes diferentes em {dup} e {fica}"
        del jogadores[dup]
    elencos = [(e[0], e[1], unificados.get(e[2], e[2])) + e[3:] for e in elencos]
    clubes_no_ano = Counter((e[0], e[2]) for e in elencos)
    elencos = [e[:4] + (1 if clubes_no_ano[(e[0], e[2])] > 1 else e[4],) + e[5:]
               if e[2] in unificados.values() else e for e in elencos]

    # alturas de outras fontes só preenchem vazios: a da ESPN nunca é trocada
    for r in alturas_extra:
        jid, altura, fonte = int(r["jogador_id"]), float(r["altura_m"]), texto(r["fonte"])
        assert jid not in unificados, f"alturas.csv: {jid} foi unificado; use o ID {unificados.get(jid)}"
        assert jid in jogadores, f"alturas.csv: jogador {jid} não está na base"
        assert jogadores[jid][3] is None, f"alturas.csv: a ESPN já informa a altura de {jid}"
        assert 1.50 <= altura <= 2.10, f"alturas.csv: altura fora do esperado para {jid}: {altura}"
        assert fonte and texto(r["referencia"]), f"alturas.csv: {jid} sem fonte ou referência"
        j = jogadores[jid]
        jogadores[jid] = j[:3] + (altura, fonte) + j[5:]

    # a ordem dos clubes de cada ano em links.csv é a da classificação final daquele ano
    por_ano = defaultdict(list)
    for r in links:
        por_ano[int(r["temporada"])].append(r)
    classificacao = []
    for ano, regs in sorted(por_ano.items()):
        assert len(regs) == 20, f"{ano}: {len(regs)} clubes"
        assert regs[0]["time_slug"] == CAMPEOES[ano], f"{ano}: 1º colocado {regs[0]['time_slug']}"
        classificacao += [(ano, int(r["time_id"]), pos) for pos, r in enumerate(regs, start=1)]

    return {
        "estados": sorted(estados),
        "elencos": sorted(elencos),
        "jogadores": sorted(jogadores.values()),
        "clubes": sorted(clubes.values()),
        "classificacao": classificacao,
    }


def conferir(t):
    for nome, linhas in t.items():
        chave = [c for c, _, _ in ESQUEMA[nome]["colunas"]]
        idx = [chave.index(c) for c in ESQUEMA[nome]["chave"]]
        chaves = Counter(tuple(l[i] for i in idx) for l in linhas)
        assert max(chaves.values()) == 1, f"{nome}: chave repetida"
    ids_clubes = {c[0] for c in t["clubes"]}
    ids_jogadores = {j[0] for j in t["jogadores"]}
    assert {e[1] for e in t["elencos"]} == ids_clubes, "elencos e clubes não batem"
    assert {e[2] for e in t["elencos"]} == ids_jogadores, "elencos e jogadores não batem"
    elencos_ano = {(e[0], e[1]) for e in t["elencos"]}
    assert {(c[0], c[1]) for c in t["classificacao"]} == elencos_ano, "classificação e elencos não batem"
    assert Counter(c[0] for c in t["classificacao"]) == Counter({a: 20 for a in range(2016, 2026)})
    assert len(t["estados"]) == 27, "estados: são 27 UFs"
    assert {c[4] for c in t["clubes"]} <= {e[0] for e in t["estados"]}, "clube com UF que não existe"


def gravar_csv(t, saida):
    for nome, linhas in t.items():
        with open(os.path.join(saida, f"{nome}.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow([c for c, _, _ in ESQUEMA[nome]["colunas"]])
            w.writerows([["" if v is None else v for v in l] for l in linhas])


def gravar_sqlite(t, caminho):
    if os.path.exists(caminho):
        os.remove(caminho)
    con = sqlite3.connect(caminho)
    estrangeiras = {
        "clubes": ["FOREIGN KEY (uf) REFERENCES estados (uf)"],
        "elencos": ["FOREIGN KEY (time_id) REFERENCES clubes (time_id)",
                    "FOREIGN KEY (jogador_id) REFERENCES jogadores (jogador_id)"],
        "classificacao": ["FOREIGN KEY (time_id) REFERENCES clubes (time_id)"],
    }
    for nome in ("estados", "clubes", "jogadores", "elencos", "classificacao"):
        cols = [f"{c} {tipo.replace('DOUBLE', 'REAL').replace('VARCHAR', 'TEXT')}" for c, tipo, _ in ESQUEMA[nome]["colunas"]]
        cols.append(f"PRIMARY KEY ({', '.join(ESQUEMA[nome]['chave'])})")
        con.execute(f"CREATE TABLE {nome} ({', '.join(cols + estrangeiras.get(nome, []))})")
        marcas = ", ".join("?" * len(ESQUEMA[nome]["colunas"]))
        con.executemany(f"INSERT INTO {nome} VALUES ({marcas})", t[nome])
    con.commit()
    con.close()


def gravar_js(t, caminho):
    tabelas = {
        nome: {
            "descricao": ESQUEMA[nome]["descricao"],
            "colunas": [{"nome": c, "tipo": tipo, "descricao": d} for c, tipo, d in ESQUEMA[nome]["colunas"]],
            "linhas": t[nome],
        }
        for nome in ESQUEMA
    }
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("// Gerado por scripts/preparar_app.py - não edite à mão.\n")
        f.write("// Fonte: elencos da Série A 2016-2025 na ESPN Brasil (espn.com.br), coletados em out/2026.\n")
        f.write("window.FUTEBOL = ")
        json.dump({"tabelas": tabelas}, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")


def main(pasta, raiz, app):
    t = montar(pasta, os.path.join(raiz, "dados", "complementos"))
    conferir(t)
    saida = os.path.join(raiz, "dados", "versoes", "v2")
    os.makedirs(saida, exist_ok=True)
    gravar_csv(t, saida)
    gravar_sqlite(t, os.path.join(saida, "futebol.sqlite"))
    if app:
        gravar_js(t, os.path.join(raiz, "app", "dados.js"))

    print("Tabelas geradas:")
    for nome, linhas in t.items():
        print(f"  {nome}: {len(linhas)} linhas")
    vazios = Counter()
    for j in t["jogadores"]:
        vazios["altura_m"] += j[3] is None
        vazios["nacionalidade"] += j[5] is None
    fontes = Counter(j[4] for j in t["jogadores"] if j[4])
    print(f"jogadores sem altura: {vazios['altura_m']} | sem nacionalidade: {vazios['nacionalidade']}")
    print("alturas por fonte: " + ", ".join(f"{f} {n}" for f, n in fontes.most_common()))
    print(f"elencos sem camisa: {sum(e[3] is None for e in t['elencos'])}")
    print("Conferências: chaves únicas, IDs ligados entre as tabelas, 20 clubes por ano, campeões na 1ª posição, UFs dos clubes.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("pasta", help="pasta com elencos_serie_a.csv, jogadores.csv e links.csv")
    p.add_argument("--raiz", default=".", help="raiz do projeto (onde ficam dados/ e app/)")
    p.add_argument("--app", action="store_true", help="também grava app/dados.js com a versão 2")
    a = p.parse_args()
    main(a.pasta, a.raiz, a.app)
