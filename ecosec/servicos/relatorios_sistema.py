"""Relatórios do sistema (S-01 a S-07): para o administrador e a auditoria.

    S-01 Log de acessos              cada autenticação, concedida ou negada
    S-02 Tentativas negadas          só as negações, com o motivo (o que a auditoria mais olha)
    S-03 Bloqueios ativos            matrículas travadas pela S1 neste momento
    S-04 Integridade da cadeia       a verificação da trilha (S10)
    S-05 Estatísticas de reconhecimento   taxas por nível e motivos de negação
    S-06 Galeria biométrica          quem tem rosto no modelo, amostras e consentimento
    S-07 Auditoria de exportação     tudo o que saiu do sistema, e o que foi barrado
    S-08 Alertas de anomalia         o monitor lê a trilha e aponta o que merece atenção (alerta precoce)
    S-09 Matriz de permissões        papel × classificação × operação: o que cada um pode, por extenso
    S-10 Revisão de acessos          quem é admin, quem aprovou, celular, último login e termo aceito

Cada relatório devolve (colunas, linhas): a tela só desenha a tabela.
Nada aqui altera dado: são consultas. (Registrar que a revisão do S-10 foi
feita é uma ação do ServicoAdministracao, com aprovação de outro admin.)
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

RELATORIOS = {
    "S-01": "Log de acessos",
    "S-02": "Tentativas negadas",
    "S-03": "Bloqueios ativos",
    "S-04": "Integridade da cadeia de hash",
    "S-05": "Estatísticas de reconhecimento",
    "S-06": "Galeria biométrica",
    "S-07": "Auditoria de exportação",
    "S-08": "Alertas de anomalia",
    "S-09": "Matriz de permissões",
    "S-10": "Revisão de acessos",
}


@dataclass(frozen=True)
class Tabela:
    codigo: str
    titulo: str
    explicacao: str
    colunas: tuple[str, ...]
    linhas: tuple[tuple, ...]


class ServicoRelatoriosSistema:
    def __init__(self, trilha, tentativas, administracao, relogio=datetime.now):
        self.trilha, self.tentativas, self.admin = trilha, tentativas, administracao
        self.relogio = relogio

    def gerar(self, codigo: str) -> Tabela:
        return {"S-01": self._s01, "S-02": self._s02, "S-03": self._s03, "S-04": self._s04,
                "S-05": self._s05, "S-06": self._s06, "S-07": self._s07, "S-08": self._s08,
                "S-09": self._s09, "S-10": self._s10}[codigo]()

    # ------------------------------------------------------------ apoio
    def _eventos(self, *tipos):
        """A trilha como o ADMINISTRADOR a vê: o detalhe das consultas e exportações do acervo mascarado."""
        return [r for r in self.trilha.recentes_para_administrador(5000) if not tipos or r.evento.evento in tipos]

    @staticmethod
    def _momento(r):
        return f"{r.evento.momento:%d/%m/%Y %H:%M:%S}"

    # ------------------------------------------------------------ relatórios
    def _s01(self):
        linhas = tuple((r.id, self._momento(r), r.evento.nivel_solicitado or "", r.evento.resultado, r.evento.motivo,
                        r.evento.camadas, r.evento.usuario_id or "", r.evento.matricula_informada or "")
                       for r in self._eventos("AUTENTICACAO"))
        return Tabela("S-01", RELATORIOS["S-01"], "Toda tentativa de autenticação, da mais recente para a mais antiga.",
                      ("#", "Momento", "Nível", "Resultado", "Motivo", "Camadas", "Usuário", "Matrícula informada"),
                      linhas)

    def _s02(self):
        negadas = [r for r in self._eventos() if r.evento.resultado == "NEGADO"]
        linhas = tuple((r.id, self._momento(r), r.evento.evento, r.evento.motivo, r.evento.nivel_solicitado or "",
                        r.evento.matricula_informada or "", r.evento.detalhe or "") for r in negadas)
        return Tabela("S-02", RELATORIOS["S-02"], "Toda negação registrada (login, painel, consulta, exportação). "
                      "Muitas negações seguidas para a mesma matrícula indicam tentativa de invasão.",
                      ("#", "Momento", "Evento", "Motivo", "Nível", "Matrícula informada", "Detalhe"), linhas)

    def _s03(self):
        agora = self.relogio()
        linhas = tuple((r.matricula, r.falhas, f"{r.bloqueado_ate:%d/%m/%Y %H:%M}",
                        f"{max(0, int((r.bloqueado_ate - agora).total_seconds() // 60))} min")
                       for r in self.tentativas.bloqueadas(agora))
        return Tabela("S-03", RELATORIOS["S-03"], "Matrículas bloqueadas agora pela S1 Contenção (inclui as que "
                      "não existem: o bloqueio não revela quais matrículas são reais).",
                      ("Matrícula", "Falhas", "Bloqueada até", "Restante"), linhas)

    def _s04(self):
        resultado = self.trilha.verificar()
        return Tabela("S-04", RELATORIOS["S-04"], "Recalcula a cadeia SHA-256 da trilha inteira.",
                      ("Situação", "Registros conferidos", "Registro rompido", "Problema"),
                      (("ÍNTEGRA" if resultado.integra else "ADULTERADA", resultado.registros_verificados,
                        resultado.id_rompido or "", resultado.problema or ""),))

    def _s05(self):
        por_nivel = defaultdict(Counter)
        motivos = Counter()
        distancias = defaultdict(list)
        for r in self._eventos("AUTENTICACAO"):
            e = r.evento
            por_nivel[e.nivel_solicitado][e.resultado] += 1
            if e.resultado == "NEGADO":
                motivos[e.motivo] += 1
            if e.resultado == "CONCEDIDO" and e.distancia is not None:
                distancias[e.nivel_solicitado].append(e.distancia)
        linhas = []
        for nivel in sorted(n for n in por_nivel if n):
            c = por_nivel[nivel]
            total = c["CONCEDIDO"] + c["NEGADO"]
            media = sum(distancias[nivel]) / len(distancias[nivel]) if distancias[nivel] else None
            linhas.append((f"Nível {nivel}", total, c["CONCEDIDO"], c["NEGADO"],
                           f"{c['CONCEDIDO'] / total:.0%}" if total else "sem dados", f"{media:.1f}" if media else "sem dados"))
        for motivo, n in motivos.most_common():
            linhas.append((f"  negado por {motivo}", n, "", "", "", ""))
        return Tabela("S-05", RELATORIOS["S-05"], "Operacional, a partir da trilha. Não substitui a avaliação "
                      "experimental (curva DET), que usa um conjunto de teste controlado.",
                      ("Nível / motivo", "Tentativas", "Concedidas", "Negadas", "Taxa de concessão",
                       "Distância média (concedidas)"), tuple(linhas))

    def _s06(self):
        linhas = tuple((l.usuario.matricula, l.usuario.nome, l.usuario.perfil.rotulo, "Sim" if l.no_modelo else "NÃO",
                        l.amostras, "Vigente" if l.consentimento_vigente else "Revogado",
                        "Sim" if l.autoriza_pesquisa else "Não", "Ativo" if l.usuario.ativo else "Inativo")
                       for l in self.admin.listar())
        return Tabela("S-06", RELATORIOS["S-06"], "Quem tem modelo facial, quantas amostras o formaram e se o "
                      "consentimento sustenta o tratamento. Rosto no modelo sem consentimento vigente é "
                      "irregularidade a corrigir.",
                      ("Matrícula", "Nome", "Perfil", "Rosto no modelo", "Amostras", "Consentimento",
                       "Pesquisa (b)", "Situação"), linhas)

    def _s07(self):
        linhas = tuple((r.id, self._momento(r), r.evento.resultado, r.evento.motivo, r.evento.nivel_solicitado or "",
                        r.evento.usuario_id or "", r.evento.detalhe or "") for r in self._eventos("EXPORTACAO"))
        return Tabela("S-07", RELATORIOS["S-07"], "Tudo o que saiu do sistema (e o que foi barrado). Se uma cópia "
                      "vazar, a marca d'água dela aponta quem exportou; esta lista confirma quando.",
                      ("#", "Momento", "Resultado", "Política", "Nível", "Usuário", "Detalhe"), linhas)

    def _s08(self):
        from ecosec.seguranca.evidencia import monitor
        alertas = monitor.detectar(self.trilha.recentes_para_administrador(5000))
        linhas = tuple((a.gravidade, a.regra, f"{a.momento:%d/%m/%Y %H:%M:%S}", a.usuario_id or "", a.matricula or "",
                        a.descricao) for a in alertas)
        return Tabela("S-08", RELATORIOS["S-08"], "O monitor lê a trilha e aponta padrões de risco: varredura de "
                      "matrículas, rajada de exportações, sessões de risco alto, exportações barradas, acesso de "
                      "emergência aberto e códigos recusados em aprovações ou na emergência. ALTO pede "
                      "verificação imediata; MÉDIO, acompanhamento. Nada aqui altera a trilha.",
                      ("Gravidade", "Regra", "Momento", "Usuário", "Matrícula", "Descrição"), linhas)

    def _s09(self):
        from ecosec.seguranca import autorizacao
        rotulo = {"PERMITIDO": "Permitido", "PERMITIDO_COM_VERIFICACAO": "Permitido, com rosto conferido",
                  "NEGADO": "Negado"}
        linhas = tuple((papel, classificacao, operacao.replace("_", " ").lower(), rotulo[efeito])
                       for papel, classificacao, operacao, efeito in autorizacao.tabela())
        return Tabela("S-09", RELATORIOS["S-09"], "A matriz que decide TODA operação sobre o acervo (confiança "
                      "zero: o que não está aqui é negado). Com risco de contexto ALTO, exportações e dados SECRETOS "
                      "são negados mesmo onde a matriz permitiria.",
                      ("Papel", "Classificação", "Operação", "Efeito"), linhas)

    def _s10(self):
        from ecosec.dominio import termo
        eventos = self._eventos()
        ultimo_login = {}
        for r in eventos:                                  # do mais novo para o mais antigo: o primeiro é o último
            if r.evento.evento == "ENTRADA" and r.evento.resultado == "CONCEDIDO" and r.evento.usuario_id:
                ultimo_login.setdefault(r.evento.usuario_id, r.evento.momento)
        revisao = next((r for r in eventos if r.evento.motivo == "REVISAO_ACESSOS"), None)
        matricula = {u.id: u.matricula for u in (l.usuario for l in self.admin.listar())}
        adms = {a.usuario_id: a for a in self.admin.administradores.listar()}
        agora, linhas = self.relogio(), []
        for l in self.admin.listar():
            u, a = l.usuario, adms.get(l.usuario.id)
            if not u.ativo and (a is None or not a.ativo):
                continue                                   # a revisão olha quem ainda tem acesso
            papel = "" if a is None or not a.ativo else (
                f"Admin desde {a.designado_em:%d/%m/%Y}"
                + (f", por {matricula.get(a.designado_por, '?')}" if a.designado_por else ", configuração inicial")
                + (f", aprovado por {matricula.get(a.aprovado_por, '?')}" if a.aprovado_por else ""))
            celular = "" if a is None or not a.ativo else (
                f"Sim, {self.admin.codigos_restantes(u.id)} códigos de recuperação" if a.celular_cadastrado
                else "NÃO cadastrado")
            login = ultimo_login.get(u.id)
            dias = f"{login:%d/%m/%Y} ({(agora - login).days} dias)" if login else "nunca entrou"
            vigente = self.admin.consentimentos.vigente_de(u.id)
            versao = ("SEM consentimento" if vigente is None else
                      f"v{vigente.versao_termo}" + ("" if vigente.versao_termo == termo.VERSAO else " (anterior)"))
            linhas.append((u.matricula, u.nome, u.perfil.rotulo, "Ativo" if u.ativo else "Inativo", papel or "Não",
                           celular, dias, versao))
        ultima = (f"Última revisão registrada: {revisao.evento.momento:%d/%m/%Y %H:%M}." if revisao
                  else "Nenhuma revisão registrada ainda.")
        return Tabela("S-10", RELATORIOS["S-10"], "Conferência periódica de quem tem acesso: cada administrador "
                      "(quem designou e quem aprovou), se o celular está cadastrado, há quanto tempo cada pessoa não "
                      "entra e qual versão do termo ela aceitou. Conferido pelo grupo, registre a revisão (pede "
                      f"outro administrador). {ultima}",
                      ("Matrícula", "Nome", "Perfil", "Situação", "Administrador", "Celular", "Último login",
                       "Termo aceito"), tuple(linhas))
