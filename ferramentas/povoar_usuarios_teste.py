"""Usuários de TESTE (servidor, diretor, ministro, um externo e um administrador, que é um externo com o papel)
num banco descartável.

    .venv\\Scripts\\python.exe -m ferramentas.povoar_usuarios_teste            cria (ou recria) e confere
    .venv\\Scripts\\python.exe -m ferramentas.povoar_usuarios_teste --apagar   só apaga o banco

Por que não no banco real (ecosec_seguranca):
  * estes usuários não têm rosto no modelo: não entram no sistema nem podem
    ser vinculados como administrador;
  * a conta da aplicação não tem DELETE: uma vez lá, só o root os tiraria;
  * consentimento é prova (LGPD art. 8º, §2º): um aceite que ninguém deu não
    pode ficar ao lado dos verdadeiros.

Por isso o banco é `<prefixo_teste>usuarios`, criado com a conta de testes
(ecosec_teste), que só alcança os bancos descartáveis. Requer o
`python -m ferramentas.preparar_banco` antes (é ele que cria a conta e o .env).

Tudo pelo mesmo código da aplicação: entidades do domínio (com as invariantes),
política de senha do config, bcrypt com o custo do config, termo vigente renderizado
e o hash SHA-256 do texto exato, gravados pelos repositórios MySQL.
"""
import argparse
import sys
from dataclasses import replace
from datetime import datetime

from ecosec import segredos
from ecosec.configuracao import carregar
from ecosec.dominio import termo
from ecosec.dominio.entidades import Administrador, Consentimento, Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.repositorios.contratos import ErroRepositorio
from ecosec.repositorios.mysql import (BancoMySQL, ParametrosConexao, RepositorioAdministradoresMySQL,
                                       RepositorioConsentimentosMySQL, RepositorioUsuariosMySQL, conectar_direto)
from ecosec.repositorios.mysql.scripts import executar_scripts
from ecosec.seguranca.acesso import s2_conhecimento
from ecosec.seguranca.acesso.s2_conhecimento import PoliticaSenha

SUFIXO_BANCO = "usuarios"

# (matrícula, nome, perfil, UF, senha, autoriza pesquisa). Matrículas no alfabeto
# do cadastro (sem I, O, 0 e 1). Senhas conhecidas de propósito: banco de teste.
# Um cadastro, um perfil: o administrador é um Externo com o papel, sem camada.
USUARIOS = (
    ("TSTSRVA", "Servidor de Teste", Perfil.SERVIDOR, None, "Servidor2026", False),
    ("TSTDRTA", "Diretor de Teste", Perfil.DIRETOR, "SP", "Diretor2026", True),
    ("TSTMNSA", "Ministro de Teste", Perfil.MINISTRO, None, "Ministro#2026-N3", True),
    ("TSTADMA", "Administrador de Teste", Perfil.EXTERNO, None, "Admin#2026-Teste", False),
    ("TSTEXTA", "Externo de Teste", Perfil.EXTERNO, None, "Externo#2026-Teste", False),
)


def _conta_teste():
    usuario, senha = segredos.ler(segredos.DB_TESTE_USUARIO), segredos.ler(segredos.DB_TESTE_SENHA)
    if not usuario or not senha:
        raise SystemExit("[FALHA] Conta de testes ausente no .env. Rode antes: python -m ferramentas.preparar_banco")
    return usuario, senha


def _nome_banco(cfg) -> str:
    return cfg["banco.prefixo_teste"] + SUFIXO_BANCO


def apagar(cfg=None) -> None:
    cfg = cfg or carregar()
    usuario, senha = _conta_teste()
    conexao = conectar_direto(cfg["banco.host"], int(cfg["banco.porta"]), usuario, senha)
    try:
        cursor = conexao.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{_nome_banco(cfg)}`")
        cursor.close()
    finally:
        conexao.close()
    print(f"Banco {_nome_banco(cfg)} apagado.")


def povoar(cfg=None) -> bool:
    """Recria o banco de teste, grava os usuários e confere cada um. True se tudo conferiu."""
    cfg = cfg or carregar()
    if cfg["lgpd.versao_termo"] != termo.VERSAO:
        raise SystemExit(f"[FALHA] Termo do config ({cfg['lgpd.versao_termo']}) diverge do código ({termo.VERSAO}).")
    host, porta, nome = cfg["banco.host"], int(cfg["banco.porta"]), _nome_banco(cfg)
    usuario_db, senha_db = _conta_teste()
    custo = int(cfg["s2_conhecimento.custo_bcrypt"])
    contato = cfg["lgpd.contato"]

    conexao = conectar_direto(host, porta, usuario_db, senha_db)
    try:
        cursor = conexao.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{nome}`")     # recria: rodar de novo dá o mesmo estado
        cursor.execute(f"CREATE DATABASE `{nome}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cursor.close()
        conexao.database = nome
        print(f"Banco descartável {nome}: {executar_scripts(conexao, 'seguranca')} comandos do schema")
    finally:
        conexao.close()

    banco = BancoMySQL(ParametrosConexao(host, porta, nome, usuario_db, senha_db))
    usuarios, consentimentos = RepositorioUsuariosMySQL(banco), RepositorioConsentimentosMySQL(banco)
    tudo_certo = True
    print(f"\n{'matrícula':<10}{'perfil':<20}{'UF':<4}{'senha':<20}{'bcrypt':<8}{'termo':<7}conferência")
    for matricula, nome_pessoa, perfil, uf, senha, autoriza in USUARIOS:
        politica = PoliticaSenha.de_configuracao(cfg, perfil.camada or Nivel.N3)    # sem camada: a mais forte
        faltam = s2_conhecimento.pendencias(senha, politica)
        if faltam:
            raise SystemExit(f"[FALHA] Senha de {matricula} fora da política do perfil {perfil.rotulo}: {faltam}")
        # o termo vem ANTES do usuário, como no cadastro real
        aceite = Consentimento(titular_nome=nome_pessoa, versao_termo=termo.VERSAO, momento=datetime.now(),
                               hash_termo=termo.calcular_hash(termo.renderizar(nome_pessoa, contato, autoriza)),
                               autoriza_pesquisa=autoriza)
        gravado = usuarios.adicionar(Usuario(matricula=matricula, nome=nome_pessoa, nivel=None, perfil=perfil,
                                             uf=uf, senha_hash=s2_conhecimento.gerar_hash(senha, custo)))
        consentimentos.registrar(replace(aceite, usuario_id=gravado.id))

        # conferência pelo caminho de leitura, como o login faria
        lido = usuarios.por_matricula(matricula)
        vigente = consentimentos.vigente_de(lido.id)
        custo_gravado = int(lido.senha_hash.split("$")[2])
        checagens = {
            "senha confere": s2_conhecimento.conferir(senha, lido.senha_hash, custo),
            "senha errada recusada": not s2_conhecimento.conferir(senha + "x", lido.senha_hash, custo),
            "custo bcrypt": custo_gravado == custo,
            "consentimento vigente": vigente is not None,
            "hash do termo confere": vigente is not None and termo.confere(
                vigente.versao_termo, nome_pessoa, contato, autoriza, vigente.hash_termo) is True,
        }
        falhas = [k for k, ok in checagens.items() if not ok]
        tudo_certo &= not falhas
        print(f"{matricula:<10}{perfil.rotulo:<20}{uf or '-':<4}{senha:<20}{custo_gravado:<8}"
              f"{vigente.versao_termo:<7}"
              + ("OK" if not falhas else "FALHA: " + ", ".join(falhas)))
    admin = usuarios.por_matricula("TSTADMA")
    administradores = RepositorioAdministradoresMySQL(banco)
    administradores.salvar(Administrador(admin.id, datetime.now()))
    tudo_certo &= administradores.obter(admin.id) is not None
    print(f"\nAdministrador de teste: TSTADMA (Externo com o papel de administrador, sem camada; governança\n"
          f"gravada na tabela administrador deste banco descartável). Os administradores reais não são tocados.")
    return tudo_certo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apagar", action="store_true", help="só apaga o banco descartável de usuários de teste")
    args = parser.parse_args()
    try:
        if args.apagar:
            apagar()
            return 0
        ok = povoar()
    except ErroRepositorio as erro:
        print(f"\n[FALHA] {erro}")
        return 2
    print("\n[ OK ] Usuários de teste gravados e conferidos." if ok else "\n[FALHA] Alguma conferência falhou.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
