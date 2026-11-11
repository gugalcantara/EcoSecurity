-- =============================================================================
-- EcoSecurity: banco de segurança (quem guarda o cofre)          MySQL 8.4
--
-- Executado pela ferramenta:  python -m ferramentas.preparar_banco
-- (ou à mão, já dentro do banco:  mysql -u root -p ecosec_seguranca < este_arquivo)
--
-- Idempotente: CREATE TABLE IF NOT EXISTS. Rodar de novo não apaga nada.
--
-- Decisões:
--  * Datas em DATETIME(6), gravadas pela aplicação (não por DEFAULT do banco):
--    a trilha de auditoria (S10) vai encadear hashes que incluem o momento, e o
--    valor no hash precisa ser exatamente o gravado.
--  * As REGRAS que importam à segurança moram também aqui (CHECK, FK, UNIQUE):
--    se a aplicação tiver um defeito, o banco ainda recusa o estado inválido.
--  * A conta da aplicação não tem DELETE em nenhuma tabela com valor de prova
--    (usuário, consentimento, amostra). Ver ferramentas/preparar_banco.py.
-- =============================================================================

CREATE TABLE IF NOT EXISTS nivel (
    id         TINYINT      PRIMARY KEY,
    titulo     VARCHAR(60)  NOT NULL,
    publico    VARCHAR(100) NOT NULL,
    modo       CHAR(3)      NOT NULL,              -- '1:N' ou '1:1'
    exportacao VARCHAR(12)  NOT NULL,              -- LIVRE, COM_MARCA, BLOQUEADA
    CONSTRAINT ck_nivel_id CHECK (id BETWEEN 1 AND 3)
);

-- Um cadastro, um perfil: EXTERNO (quem não é do quadro do governo; sem camada), SERVIDOR
-- (camada 1), DIRETOR (2) e MINISTRO (3). `nivel` é a camada do perfil, NULL para o Externo. Ser administrador é
-- um PAPEL de um Externo (tabela administrador), não um perfil. Excluir é lógico (excluido_em): a aplicação não tem
-- DELETE aqui.
-- Os CHECKs usam <=> (NULL-safe): um CHECK do MySQL aceita quando a expressão dá NULL.
-- Bancos anteriores recebem estas colunas e CHECKs por ferramentas/preparar_banco.py (migrar_perfis).
CREATE TABLE IF NOT EXISTS usuario (
    id          INT          PRIMARY KEY AUTO_INCREMENT,    -- = rótulo no modelo LBPH
    matricula   VARCHAR(20)  NOT NULL,
    nome        VARCHAR(100) NOT NULL,
    nivel       TINYINT      NULL,
    perfil      VARCHAR(20)  NOT NULL,
    uf          CHAR(2)      NULL,
    senha_hash  CHAR(60)     NOT NULL,                      -- bcrypt: sempre 60 caracteres
    ativo       BOOLEAN      NOT NULL DEFAULT TRUE,
    criado_em   DATETIME(6)  NOT NULL,
    excluido_em DATETIME(6)  NULL,
    CONSTRAINT uq_usuario_matricula UNIQUE (matricula),
    CONSTRAINT fk_usuario_nivel FOREIGN KEY (nivel) REFERENCES nivel (id),
    -- diretor de nível 2 sem região veria todas as UFs se um filtro falhasse
    CONSTRAINT ck_usuario_n2_uf CHECK (nivel <> 2 OR uf IS NOT NULL),
    CONSTRAINT ck_usuario_perfil_nivel CHECK ((perfil = 'SERVIDOR' AND nivel <=> 1) OR (perfil = 'DIRETOR' AND nivel <=> 2)
        OR (perfil = 'MINISTRO' AND nivel <=> 3) OR (perfil = 'EXTERNO' AND nivel IS NULL)),
    CONSTRAINT ck_usuario_uf_perfil CHECK ((perfil = 'DIRETOR') = (uf IS NOT NULL)),
    CONSTRAINT ck_usuario_excluido CHECK (excluido_em IS NULL OR NOT ativo),
    -- um hash bcrypt começa com $2a$, $2b$ ou $2y$; texto puro aqui é defeito grave
    CONSTRAINT ck_usuario_hash CHECK (senha_hash LIKE '$2_$%'),
    -- padrão de texto do banco (ecosec/dominio/texto.py): maiúsculas, sem acento
    CONSTRAINT ck_usuario_nome CHECK (REGEXP_LIKE(nome, '^[A-Z0-9 ]+$', 'c'))
);

-- Aceite do termo (LGPD art. 11, I). Gravado ANTES do usuário existir: o termo
-- vem antes da câmera. Revogação é marcada, nunca apagada.
-- titular_nome entra no hash do termo: novos aceites já chegam padronizados, mas os
-- antigos ficam como foram assinados (sem CHECK aqui, para não invalidar a prova).
CREATE TABLE IF NOT EXISTS consentimento (
    id           INT          PRIMARY KEY AUTO_INCREMENT,
    usuario_id   INT          NULL,
    titular_nome VARCHAR(100) NOT NULL,
    versao_termo VARCHAR(10)  NOT NULL,
    hash_termo   CHAR(64)     NOT NULL,                    -- SHA-256 do texto apresentado
    momento      DATETIME(6)  NOT NULL,
    revogado_em  DATETIME(6)  NULL,
    -- finalidade (b), opcional: estatísticas e experimentos (termo 2.0, art. 8º, §4º)
    autoriza_pesquisa BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_consentimento_usuario FOREIGN KEY (usuario_id) REFERENCES usuario (id),
    INDEX ix_consentimento_usuario (usuario_id)
);

-- Metadado das amostras faciais. A imagem nunca vem para cá: treina o modelo
-- e é apagada. A sessão é a base da divisão treino/teste dos experimentos.
CREATE TABLE IF NOT EXISTS amostra (
    id         INT          PRIMARY KEY AUTO_INCREMENT,
    usuario_id INT          NOT NULL,
    sessao     TINYINT      NOT NULL,
    origem     VARCHAR(20)  NOT NULL,
    qualidade  DECIMAL(6,4) NOT NULL,
    criada_em  DATETIME(6)  NOT NULL,
    CONSTRAINT fk_amostra_usuario FOREIGN KEY (usuario_id) REFERENCES usuario (id),
    INDEX ix_amostra_usuario (usuario_id)
);

-- S10 Trilha: cada evento guarda o hash do anterior (cadeia SHA-256).
-- A conta da aplicação só tem SELECT e INSERT aqui: não consegue alterar nem
-- apagar o passado. Quem tiver a conta root pode adulterar uma linha, mas a
-- cadeia denuncia e LOCALIZA a adulteração (o hash da linha deixa de conferir,
-- e o "hash_anterior" da seguinte também).
-- Nunca grava senha, imagem ou distância de quem não alegou identidade.
CREATE TABLE IF NOT EXISTS log_acesso (
    id                  BIGINT       PRIMARY KEY AUTO_INCREMENT,
    momento             DATETIME(6)  NOT NULL,                  -- da aplicação: entra no hash
    evento              VARCHAR(30)  NOT NULL,                  -- AUTENTICACAO, CADASTRO, ADMIN...
    nivel_solicitado    TINYINT      NULL,
    usuario_id          INT          NULL,
    usuario2_id         INT          NULL,                      -- segunda pessoa (regra dos dois)
    matricula_informada VARCHAR(20)  NULL,
    resultado           VARCHAR(12)  NOT NULL,                  -- CONCEDIDO, NEGADO, REGISTRADO
    motivo              VARCHAR(40)  NOT NULL,
    camadas             VARCHAR(60)  NOT NULL,                  -- ex.: S1,S2,S3,S4
    distancia           DECIMAL(10,4) NULL,
    detalhe             VARCHAR(200) NULL,
    hash_anterior       CHAR(64)     NOT NULL,                  -- 64 zeros no primeiro registro
    hash_registro       CHAR(64)     NOT NULL,
    CONSTRAINT uq_log_hash UNIQUE (hash_registro),
    CONSTRAINT ck_log_resultado CHECK (resultado IN ('CONCEDIDO', 'NEGADO', 'REGISTRADO')),
    CONSTRAINT fk_log_usuario  FOREIGN KEY (usuario_id)  REFERENCES usuario (id),
    CONSTRAINT fk_log_usuario2 FOREIGN KEY (usuario2_id) REFERENCES usuario (id)
);

-- Estado da S1 Contenção, pela matrícula digitada (existindo ou não): se só as
-- reais travassem, o bloqueio revelaria quais matrículas existem.
CREATE TABLE IF NOT EXISTS tentativa (
    matricula     VARCHAR(20) PRIMARY KEY,
    falhas        INT         NOT NULL DEFAULT 0,
    bloqueado_ate DATETIME(6) NULL,
    CONSTRAINT ck_tentativa_falhas CHECK (falhas >= 0)
);

-- O papel de administrador (uma linha por cadastro). Uma pessoa, um rosto, uma
-- matrícula, vários papéis: ser administrador não cria outra identidade.
-- Sem DELETE para a aplicação: tirar o papel marca ativo = FALSE e removido_em.
-- O segredo do celular (TOTP) chega cifrado pela aplicação (Fernet, chave
-- CHAVE_TOTP do .env): quem ler esta tabela não gera os códigos.
CREATE TABLE IF NOT EXISTS administrador (
    usuario_id    INT          PRIMARY KEY,
    designado_em  DATETIME(6)  NOT NULL,
    designado_por INT          NULL,                    -- NULL: configuração inicial ou migração
    aprovado_por  INT          NULL,                    -- NULL: fase de implantação (menos de 2 admins)
    segredo_totp  VARCHAR(200) NULL,                    -- NULL: celular ainda não cadastrado
    ultimo_passo  BIGINT       NULL,                    -- último código aceito (anti-repetição)
    ativo         BOOLEAN      NOT NULL DEFAULT TRUE,
    removido_em   DATETIME(6)  NULL,
    CONSTRAINT fk_administrador_usuario   FOREIGN KEY (usuario_id)    REFERENCES usuario (id),
    CONSTRAINT fk_administrador_designou  FOREIGN KEY (designado_por) REFERENCES usuario (id),
    CONSTRAINT fk_administrador_aprovou   FOREIGN KEY (aprovado_por)  REFERENCES usuario (id),
    -- ninguém aprova o próprio pedido: a regra mora também no banco
    CONSTRAINT ck_administrador_dois CHECK (aprovado_por IS NULL OR aprovado_por <> designado_por),
    CONSTRAINT ck_administrador_removido CHECK (ativo OR removido_em IS NOT NULL)
);

-- Códigos de recuperação do celular (uso único). Só o SHA-256; usado é marcado, nunca apagado.
CREATE TABLE IF NOT EXISTS codigo_recuperacao (
    id          INT          PRIMARY KEY AUTO_INCREMENT,
    usuario_id  INT          NOT NULL,
    hash_codigo CHAR(64)     NOT NULL,
    criado_em   DATETIME(6)  NOT NULL,
    usado_em    DATETIME(6)  NULL,
    CONSTRAINT uq_codigo_hash UNIQUE (hash_codigo),
    CONSTRAINT fk_codigo_usuario FOREIGN KEY (usuario_id) REFERENCES usuario (id),
    INDEX ix_codigo_usuario (usuario_id)
);

-- Estações em que cada pessoa já entrou (MFA adaptativo: o sinal ESTACAO_NOVA eleva a verificação).
-- Guarda só o SHA-256 de "computador|conta do Windows": nem o nome da máquina nem o da conta.
CREATE TABLE IF NOT EXISTS estacao (
    usuario_id   INT         NOT NULL,
    impressao    CHAR(64)    NOT NULL,
    primeiro_uso DATETIME(6) NOT NULL,
    ultimo_uso   DATETIME(6) NOT NULL,
    PRIMARY KEY (usuario_id, impressao),
    CONSTRAINT fk_estacao_usuario FOREIGN KEY (usuario_id) REFERENCES usuario (id)
);
