"""Raiz de composição: o único lugar que conhece as peças concretas.

Todas as outras camadas recebem as dependências prontas. Trocar memória por
MySQL é decidido aqui, por [persistencia] modo no config: nenhuma regra muda.

Modo "mysql" (uso normal):
  - usuários, consentimentos, amostras e tentativas no banco ecosec_seguranca;
  - modelo facial em modelo/lbph.enc, cifrado com a CHAVE_CIFRAGEM do .env,
    carregado na abertura e salvo a cada cadastro.
Modo "memoria": tudo some ao fechar (desenvolvimento e testes).

Falha segura na abertura: banco fora do ar, contas ausentes ou modelo que não
decifra impedem o sistema de abrir: nunca "abre mesmo assim" em modo
degradado, onde alguém poderia entrar sem as verificações completas.
"""
from dataclasses import dataclass
from pathlib import Path

from ecosec import segredos
from ecosec.configuracao import Configuracao, ErroConfiguracao, carregar
from ecosec.repositorios.memoria import (RepositorioAcervoMemoria, RepositorioAmostrasMemoria, RepositorioConsentimentosMemoria,
                                         RepositorioTentativasMemoria, RepositorioTrilhaMemoria,
                                         RepositorioUsuariosMemoria)
from ecosec.seguranca.acesso import s6_vivacidade
from ecosec.seguranca.acesso.contexto import ParametrosContexto
from ecosec.servicos.acervo import ServicoAcervo
from ecosec.servicos.administracao import ServicoAdministracao
from ecosec.servicos.sessao import ServicoSessao
from ecosec.servicos.autenticacao import ParametrosAutenticacao, ServicoAutenticacao
from ecosec.servicos.cadastro import ServicoCadastro
from ecosec.servicos.identificacao import ServicoIdentificacao
from ecosec.servicos.relatorios_sistema import ServicoRelatoriosSistema
from ecosec.servicos.trilha import ServicoTrilha
from ecosec.visao.aquisicao import Camera
from ecosec.visao.pipeline import PipelineVisao
from ecosec.visao.reconhecimento import ParametrosLBPH, ReconhecedorLBPH

ARQUIVO_MODELO = "lbph.enc"


class ErroAbertura(RuntimeError):
    """O sistema não pode abrir com segurança. A mensagem diz o que fazer."""


@dataclass
class Aplicacao:
    cfg: Configuracao
    reconhecedor: ReconhecedorLBPH
    cadastro: ServicoCadastro
    autenticacao: ServicoAutenticacao
    identificacao: ServicoIdentificacao
    administracao: ServicoAdministracao
    acervo: ServicoAcervo
    relatorios_sistema: ServicoRelatoriosSistema
    sessao: ServicoSessao
    modo_persistencia: str

    def nova_camera(self) -> Camera:
        return Camera.de_configuracao(self.cfg)

    def novo_pipeline(self) -> PipelineVisao:
        """Um por sessão de vídeo: o rastreador KCF guarda estado."""
        return PipelineVisao.de_configuracao(self.cfg)


def _repositorios_memoria():
    from ecosec.repositorios.memoria import RepositorioAdministradoresMemoria, RepositorioEstacoesMemoria
    return (RepositorioUsuariosMemoria(), RepositorioTentativasMemoria(),
            RepositorioConsentimentosMemoria(), RepositorioAmostrasMemoria(), RepositorioTrilhaMemoria(),
            RepositorioAcervoMemoria(), RepositorioEstacoesMemoria(), RepositorioAdministradoresMemoria())


def _repositorios_mysql(cfg, env: Path):
    from ecosec.repositorios.contratos import ErroRepositorio
    from ecosec.repositorios.mysql import (TABELAS_ACERVO, TABELAS_SEGURANCA, BancoMySQL, ParametrosConexao,
                                           RepositorioAcervoMySQL, RepositorioAdministradoresMySQL,
                                           RepositorioAmostrasMySQL, RepositorioConsentimentosMySQL,
                                           RepositorioEstacoesMySQL, RepositorioTentativasMySQL,
                                           RepositorioTrilhaMySQL, RepositorioUsuariosMySQL)
    usuario = segredos.ler(segredos.DB_SEGURANCA_USUARIO, env)
    senha = segredos.ler(segredos.DB_SEGURANCA_SENHA, env)
    if not usuario or not senha:
        raise ErroAbertura("O banco ainda não foi preparado: faltam as credenciais no .env.\n"
                           "Rode:  .venv\\Scripts\\python.exe -m ferramentas.preparar_banco")
    banco = BancoMySQL(ParametrosConexao(cfg["banco.host"], int(cfg["banco.porta"]),
                                         cfg["banco.seguranca"], usuario, senha))
    # o cofre tem conta própria, só de leitura: um defeito na parte de segurança
    # não consegue alterar o acervo, e vice-versa
    cofre = BancoMySQL(ParametrosConexao(cfg["banco.host"], int(cfg["banco.porta"]), cfg["banco.acervo"],
                                         segredos.ler(segredos.DB_ACERVO_USUARIO, env) or "",
                                         segredos.ler(segredos.DB_ACERVO_SENHA, env) or ""))
    try:
        banco.verificar(TABELAS_SEGURANCA)
        cofre.verificar(TABELAS_ACERVO)
    except ErroRepositorio as erro:
        raise ErroAbertura(f"{erro}\nSe você acabou de atualizar o EcoSecurity, rode:  "
                           ".venv\\Scripts\\python.exe -m ferramentas.preparar_banco") from None
    return (RepositorioUsuariosMySQL(banco), RepositorioTentativasMySQL(banco),
            RepositorioConsentimentosMySQL(banco), RepositorioAmostrasMySQL(banco), RepositorioTrilhaMySQL(banco),
            RepositorioAcervoMySQL(cofre), RepositorioEstacoesMySQL(banco), RepositorioAdministradoresMySQL(banco))


def _eliminar(reconhecedor, usuario_id: int, salvar_modelo) -> None:
    """Remove o rosto do modelo e persiste o modelo já sem ele."""
    if reconhecedor.remover(usuario_id) and salvar_modelo is not None:
        if reconhecedor.treinado:
            salvar_modelo()
        else:                                   # era a última pessoa: some o arquivo
            salvar_modelo(apagar=True)


def _conferir_vivacidade(cfg: Configuracao) -> None:
    """Os nomes dos gestos e, com a piscada configurada, o modelo de landmarks são conferidos (e o
    modelo carregado) NA ABERTURA: melhor uma mensagem clara agora do que um N3 que nega no meio da tentativa."""
    try:
        s6_vivacidade.validar(cfg["s6_vivacidade.desafios"], cfg["s6_vivacidade.gesto_obrigatorio"])
    except ValueError as erro:
        raise ErroConfiguracao(str(erro)) from None
    if "PISCAR" not in cfg["s6_vivacidade.desafios"]:
        return
    from ecosec.visao.gestos import ErroModeloLandmarks, ParametrosGestos, carregar_landmarks
    try:
        pg = ParametrosGestos.de_configuracao(cfg)
    except ValueError as erro:                       # ex.: sinal_piscada escrito errado
        raise ErroConfiguracao(str(erro)) from None
    try:
        carregar_landmarks(pg.modelo_landmarks, pg.modelo_landmarks_sha256)
    except ErroModeloLandmarks as erro:
        raise ErroAbertura(f"{erro} A piscada do nível 3 depende desse modelo.") from None


def _rasterizar_documento(html, qr_modulos, orgao, marca):
    """Desenho do documento (Qt) injetado no serviço: a camada de serviços não importa a interface."""
    from ecosec.interface.rasterizar_documento import rasterizar
    return rasterizar(html, qr_modulos, orgao, marca)


def montar(cfg: Configuracao | None = None, caminho_env: Path | None = None,
           modo: str | None = None) -> Aplicacao:
    """Um .env protegido pelo Windows de outra conta (ou outro PC) também é "não abre com segurança": vira
    ErroAbertura, que o programa e todas as ferramentas já mostram com a orientação de restaurar o backup."""
    try:
        return _montar(cfg, caminho_env, modo)
    except segredos.ErroSegredo as erro:
        raise ErroAbertura(str(erro)) from None


def _montar(cfg: Configuracao | None, caminho_env: Path | None, modo: str | None) -> Aplicacao:
    cfg = cfg or carregar()
    env = caminho_env or segredos.CAMINHO_PADRAO
    modo = modo or cfg["persistencia.modo"]
    if modo not in ("mysql", "memoria"):
        raise ErroConfiguracao(f"[persistencia] modo inválido: {modo!r} (use 'mysql' ou 'memoria').")

    _conferir_vivacidade(cfg)
    parametros_lbph = ParametrosLBPH.de_configuracao(cfg)
    salvar_modelo = None
    if modo == "mysql":
        usuarios, tentativas, consentimentos, amostras, repo_trilha, repo_acervo, estacoes, administradores = \
            _repositorios_mysql(cfg, env)
        chave = segredos.garantir_chave_cifragem(env)
        arquivo_modelo = cfg.caminho("modelo") / ARQUIVO_MODELO
        if arquivo_modelo.exists():
            from ecosec.visao.reconhecimento import ErroModelo
            try:
                reconhecedor = ReconhecedorLBPH.carregar_cifrado(arquivo_modelo, chave, parametros_lbph)
            except ErroModelo as erro:
                raise ErroAbertura(f"{erro}\nO modelo facial está em {arquivo_modelo}.") from None
        else:
            reconhecedor = ReconhecedorLBPH(parametros_lbph)

        def salvar_modelo(apagar: bool = False):
            if apagar:
                arquivo_modelo.unlink(missing_ok=True)
            else:
                reconhecedor.salvar_cifrado(arquivo_modelo, chave)
    else:
        usuarios, tentativas, consentimentos, amostras, repo_trilha, repo_acervo, estacoes, administradores = \
            _repositorios_memoria()
        reconhecedor = ReconhecedorLBPH(parametros_lbph)

    from cryptography.fernet import Fernet
    trilha = ServicoTrilha(repo_trilha)
    administracao = ServicoAdministracao.de_configuracao(
        cfg, usuarios, consentimentos, amostras, tentativas,
        ler_hash=lambda: segredos.ler(segredos.ADMIN_SENHA_HASH, env),
        gravar_hash=lambda h: segredos.gravar(segredos.ADMIN_SENHA_HASH, h, env),
        administradores=administradores, cifra_totp=Fernet(segredos.garantir_chave_totp(env)),
        rotulos_modelo=reconhecedor.rotulos,
        eliminar_biometria=lambda usuario_id: _eliminar(reconhecedor, usuario_id, salvar_modelo),
        trilha=trilha)
    # versões antigas: um administrador no .env. Passa para o banco uma vez, e a chave antiga sai do .env
    if modo == "mysql" and administracao.migrar_administrador_legado(segredos.ler(segredos.ADMIN_MATRICULA, env)):
        segredos.apagar(segredos.ADMIN_MATRICULA, env)
    return Aplicacao(
        cfg=cfg,
        reconhecedor=reconhecedor,
        cadastro=ServicoCadastro.de_configuracao(cfg, usuarios, consentimentos, amostras, reconhecedor,
                                                 ao_alterar_modelo=salvar_modelo, trilha=trilha),
        autenticacao=ServicoAutenticacao(usuarios, tentativas, consentimentos, reconhecedor,
                                         ParametrosAutenticacao.de_configuracao(cfg), trilha=trilha,
                                         estacoes=estacoes, contexto_parametros=ParametrosContexto.de_configuracao(cfg),
                                         eh_administrador=administracao.eh_administrador),
        identificacao=ServicoIdentificacao.de_configuracao(cfg, usuarios, consentimentos, reconhecedor, trilha=trilha,
                                                           eh_administrador=administracao.eh_administrador),
        administracao=administracao,
        acervo=ServicoAcervo.de_configuracao(cfg, repo_acervo, trilha, segredos.garantir_chave_marca(env),
                                             rasterizar_documento=_rasterizar_documento),
        relatorios_sistema=ServicoRelatoriosSistema(trilha, tentativas, administracao),
        sessao=ServicoSessao(usuarios, administracao, trilha,
                             inatividade_minutos=float(cfg["sessao.inatividade_minutos"])),
        modo_persistencia=modo,
    )
