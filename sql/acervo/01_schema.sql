-- =============================================================================
-- EcoSecurity: banco do ACERVO (o cofre)                         MySQL 8.0/8.4
--
-- Cadastro consolidado de passivos perigosos pendentes de coleta, com
-- a camada causal (atividade geradora e motivo da permanência).
--
-- A aplicação acessa este banco com uma conta só de leitura. Alimentar o
-- acervo é tarefa administrativa (ferramenta de importação, conta root).
--
-- Padrão de texto (ecosec/dominio/texto.py), repetido aqui em CHECK para o banco
-- recusar o que fugir dele: nomes e descrições em maiúsculas, sem acento, só
-- A-Z, 0-9 e espaço. REGEXP_LIKE(..., 'c') = sensível à caixa (a collation do
-- banco é insensível). Códigos (AG-01, PD-0001) e referências técnicas (base
-- legal, CNAE) mantêm a pontuação que lhes dá sentido. Descrições operacionais
-- longas aceitam também , . ; : ( ) / - (padrão próprio, mais largo).
-- =============================================================================

-- ---------------------------------------------------------------- camada causal
-- Catálogo: nenhum código aparece sem nome e descrição.
CREATE TABLE IF NOT EXISTS atividade_geradora (
    id                    INT          PRIMARY KEY AUTO_INCREMENT,
    codigo                VARCHAR(10)  NOT NULL,            -- AG-01 a AG-13
    nome                  VARCHAR(40)  NOT NULL,            -- rótulo curto: "AG-08 · RADIOTERAPIA E FONTES SELADAS"
    descricao_operacional VARCHAR(400) NOT NULL,
    cnae_subclasse        VARCHAR(30)  NOT NULL,            -- '8640-2/11' ou '9601-7/01; 9601-7/02'
    exemplos              VARCHAR(300) NOT NULL,
    observacao            TEXT,
    CONSTRAINT uq_atividade_codigo UNIQUE (codigo),
    CONSTRAINT ck_atividade_nome CHECK (REGEXP_LIKE(nome, '^[A-Z0-9 ]+$', 'c')),
    CONSTRAINT ck_atividade_texto CHECK (REGEXP_LIKE(descricao_operacional, '^[A-Z0-9 ,.;:()/-]+$', 'c')
        AND REGEXP_LIKE(exemplos, '^[A-Z0-9 ,.;:()/-]+$', 'c')),
    CONSTRAINT ck_atividade_cnae CHECK (
        REGEXP_LIKE(cnae_subclasse, '^[0-9]{4}-[0-9]/[0-9]{2}(; [0-9]{4}-[0-9]/[0-9]{2})*$'))
);

CREATE TABLE IF NOT EXISTS motivo_permanencia (
    id                    INT          PRIMARY KEY AUTO_INCREMENT,
    codigo                VARCHAR(10)  NOT NULL,            -- MP-01 a MP-10
    nome                  VARCHAR(40)  NOT NULL,
    descricao_operacional VARCHAR(400) NOT NULL,            -- por que a pendência fica parada
    base_legal            TEXT,
    grupo                 VARCHAR(15)  NOT NULL,            -- quem paga
    acao_institucional    TEXT,
    CONSTRAINT uq_motivo_codigo UNIQUE (codigo),
    CONSTRAINT ck_motivo_nome CHECK (REGEXP_LIKE(nome, '^[A-Z0-9 ]+$', 'c')),
    CONSTRAINT ck_motivo_texto CHECK (REGEXP_LIKE(descricao_operacional, '^[A-Z0-9 ,.;:()/-]+$', 'c')),
    CONSTRAINT ck_motivo_grupo CHECK (grupo IN ('COBRAVEL', 'PUBLICO', 'INFRAESTRUTURA', 'FISCALIZACAO'))
);

-- Eventos regulatórios: anotações dos gráficos e efeitos do gerador.
-- Só CONFIRMADO (conferido na fonte citada) vira anotação: o serviço do acervo descarta os demais.
CREATE TABLE IF NOT EXISTS evento_regulatorio (
    id          INT           PRIMARY KEY AUTO_INCREMENT,
    data_evento DATE          NOT NULL,
    rotulo      VARCHAR(40)   NOT NULL,                     -- o que aparece no gráfico
    descricao   VARCHAR(300)  NOT NULL,
    classes     SET('AREA CONTAMINADA', 'CLASSE I NBR 10004', 'REJEITO RADIOATIVO CNEN') NOT NULL,
    efeito      VARCHAR(10)   NOT NULL,
    base_legal  VARCHAR(200)  NULL,
    verificacao VARCHAR(12)   NOT NULL,
    CONSTRAINT uq_evento UNIQUE (data_evento, rotulo),
    CONSTRAINT ck_evento_rotulo CHECK (REGEXP_LIKE(rotulo, '^[A-Z0-9 ]+$', 'c')),
    CONSTRAINT ck_evento_efeito CHECK (efeito IN ('ENTRADAS', 'SAIDAS', 'AMBOS', 'ANOTACAO')),
    CONSTRAINT ck_evento_verificacao CHECK (verificacao IN ('CONFIRMADO', 'A CONFIRMAR'))
);

-- ---------------------------------------------------------------- pendências
CREATE TABLE IF NOT EXISTS pendencia (
    id                 INT           PRIMARY KEY AUTO_INCREMENT,
    codigo             VARCHAR(20)   NOT NULL,
    substancia         VARCHAR(200)  NOT NULL,
    classe_risco       VARCHAR(50)   NOT NULL,              -- CLASSE I NBR 10004, REJEITO RADIOATIVO CNEN...
    quantidade         DECIMAL(12,3),
    unidade            VARCHAR(20),                         -- por extenso: TONELADAS, METROS CUBICOS
    -- endereço granular
    logradouro         VARCHAR(150)  NOT NULL,
    numero             VARCHAR(10)   NOT NULL,              -- "1500" ou "S/N"
    complemento        VARCHAR(60)   NULL,                  -- GALPAO 3, QUADRA 7 LOTE 12
    bairro             VARCHAR(80)   NOT NULL,
    municipio          VARCHAR(100)  NOT NULL,
    uf                 CHAR(2)       NOT NULL,
    cep                CHAR(8)       NOT NULL,              -- só dígitos, sem hífen
    latitude           DECIMAL(9,6),
    longitude          DECIMAL(9,6),
    data_identificacao DATE          NOT NULL,              -- entrada no cadastro (histórico do risco)
    prazo_coleta       DATE,                                -- previsão de coleta
    situacao           VARCHAR(30)   NOT NULL,
    -- ciclo de vida: a data de encerramento é a da etapa final (etapa_gerenciamento.final)
    data_encerramento  DATE          NULL,
    etapa_atual        VARCHAR(40)   NOT NULL,
    atividade_id       INT           NOT NULL,              -- RF-19: nenhuma pendência sem causa
    motivo_id          INT           NOT NULL,
    sintetico          BOOLEAN       NOT NULL DEFAULT TRUE, -- TRUE = gerado por sinteticos.py
    fonte              VARCHAR(300),
    data_acesso_fonte  DATE,
    CONSTRAINT uq_pendencia_codigo UNIQUE (codigo),
    CONSTRAINT fk_pendencia_atividade FOREIGN KEY (atividade_id) REFERENCES atividade_geradora (id),
    CONSTRAINT fk_pendencia_motivo FOREIGN KEY (motivo_id) REFERENCES motivo_permanencia (id),
    CONSTRAINT ck_pendencia_uf CHECK (REGEXP_LIKE(uf, '^[A-Z]{2}$', 'c')),
    CONSTRAINT ck_pendencia_cep CHECK (REGEXP_LIKE(cep, '^[0-9]{8}$')),
    CONSTRAINT ck_pendencia_numero CHECK (REGEXP_LIKE(numero, '^([0-9]+[A-Z]?|S/N)$', 'c')),
    CONSTRAINT ck_pendencia_textos CHECK (
        REGEXP_LIKE(substancia, '^[A-Z0-9 ]+$', 'c') AND REGEXP_LIKE(classe_risco, '^[A-Z0-9 ]+$', 'c')
        AND REGEXP_LIKE(logradouro, '^[A-Z0-9 ]+$', 'c') AND REGEXP_LIKE(bairro, '^[A-Z0-9 ]+$', 'c')
        AND REGEXP_LIKE(municipio, '^[A-Z0-9 ]+$', 'c') AND REGEXP_LIKE(situacao, '^[A-Z0-9 ]+$', 'c')
        AND (complemento IS NULL OR REGEXP_LIKE(complemento, '^[A-Z0-9 ]+$', 'c'))
        AND (unidade IS NULL OR REGEXP_LIKE(unidade, '^[A-Z ]+$', 'c'))),
    CONSTRAINT ck_pendencia_datas CHECK (prazo_coleta IS NULL OR prazo_coleta >= data_identificacao),
    CONSTRAINT ck_pendencia_encerramento CHECK (data_encerramento IS NULL OR data_encerramento > data_identificacao),
    CONSTRAINT ck_pendencia_etapa CHECK (REGEXP_LIKE(etapa_atual, '^[A-Z0-9 ]+$', 'c')),
    INDEX ix_pendencia_uf (uf),
    INDEX ix_pendencia_identificacao (data_identificacao),
    INDEX ix_pendencia_encerramento (data_encerramento)
);

-- Etapas do ciclo de vida, em ordem. A última de uma pendência encerrada tem final = TRUE e
-- data_etapa = pendencia.data_encerramento (conferido pelo preparar_banco).
CREATE TABLE IF NOT EXISTS etapa_gerenciamento (
    id           INT          PRIMARY KEY AUTO_INCREMENT,
    pendencia_id INT          NOT NULL,
    ordem        TINYINT      NOT NULL,
    nome         VARCHAR(40)  NOT NULL,
    data_etapa   DATE         NOT NULL,
    final        BOOLEAN      NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_etapa UNIQUE (pendencia_id, ordem),
    CONSTRAINT ck_etapa_nome CHECK (REGEXP_LIKE(nome, '^[A-Z0-9 ]+$', 'c')),
    CONSTRAINT fk_etapa_pendencia FOREIGN KEY (pendencia_id) REFERENCES pendencia (id)
);

-- Cadeia de responsabilidade: nomeia empresas e pessoas, só a partir do N2 (RF-21).
-- O nível mínimo mora NA LINHA: a consulta já devolve só o que o nível autoriza,
-- em vez de buscar tudo e filtrar na aplicação.
CREATE TABLE IF NOT EXISTS responsavel (
    id                 INT          PRIMARY KEY AUTO_INCREMENT,
    pendencia_id       INT          NOT NULL,
    nome               VARCHAR(200) NOT NULL,
    vinculo            ENUM('GERADOR_ORIGINAL','SUCESSOR','PROPRIETARIO_ATUAL',
                            'TRANSPORTADOR','DESTINADOR') NOT NULL,
    situacao_cadastral VARCHAR(50),
    nivel_minimo       TINYINT      NOT NULL DEFAULT 2,
    CONSTRAINT ck_responsavel_nivel CHECK (nivel_minimo BETWEEN 2 AND 3),
    CONSTRAINT ck_responsavel_textos CHECK (REGEXP_LIKE(nome, '^[A-Z0-9 ]+$', 'c')
        AND (situacao_cadastral IS NULL OR REGEXP_LIKE(situacao_cadastral, '^[A-Z0-9 ]+$', 'c'))),
    CONSTRAINT fk_responsavel_pendencia FOREIGN KEY (pendencia_id) REFERENCES pendencia (id)
);

-- ---------------------------------------------------------------- itens (imagens)
CREATE TABLE IF NOT EXISTS item_acervo (
    id                INT          PRIMARY KEY AUTO_INCREMENT,
    codigo            VARCHAR(20)  NOT NULL,                -- A1-01, A2-04...
    titulo            VARCHAR(200) NOT NULL,
    tipo              ENUM('DOCUMENTO','MAPA','FOTO','RELATORIO') NOT NULL,
    arquivo           VARCHAR(300),
    nivel_minimo      TINYINT      NOT NULL,                -- abaixo disso o item nem é listado
    -- FALSE = regiões sensíveis ainda não revisadas: o item inteiro é tratado
    -- como sensível e só o nível 3 o vê (falha segura também no conteúdo)
    regioes_revisadas BOOLEAN      NOT NULL DEFAULT FALSE,
    sintetico         BOOLEAN      NOT NULL DEFAULT TRUE,
    uf                CHAR(2),
    pendencia_id      INT,
    fonte             VARCHAR(300),
    data_acesso_fonte DATE,
    CONSTRAINT uq_item_codigo UNIQUE (codigo),
    CONSTRAINT ck_item_nivel CHECK (nivel_minimo BETWEEN 1 AND 3),
    CONSTRAINT ck_item_titulo CHECK (REGEXP_LIKE(titulo, '^[A-Z0-9 ]+$', 'c')),
    CONSTRAINT fk_item_pendencia FOREIGN KEY (pendencia_id) REFERENCES pendencia (id)
);

-- Região de um item que só aparece íntegra para nível >= nivel_minimo (S8 Tarja).
-- Para os relatórios (desenhados na hora), a importação grava o inventário das
-- regiões que o desenho anota na visão completa: auditável sem abrir a aplicação.
CREATE TABLE IF NOT EXISTS regiao_sensivel (
    id           INT         PRIMARY KEY AUTO_INCREMENT,
    item_id      INT         NOT NULL,
    x            INT         NOT NULL,
    y            INT         NOT NULL,
    largura      INT         NOT NULL,
    altura       INT         NOT NULL,
    rotulo       VARCHAR(50) NOT NULL,                      -- ENDERECO, RESPONSAVEL, COORDENADA...
    nivel_minimo TINYINT     NOT NULL,
    CONSTRAINT ck_regiao_nivel CHECK (nivel_minimo BETWEEN 2 AND 3),
    CONSTRAINT ck_regiao_dimensoes CHECK (largura > 0 AND altura > 0),
    CONSTRAINT fk_regiao_item FOREIGN KEY (item_id) REFERENCES item_acervo (id)
);

-- ---------------------------------------------------------------- visões do nível 1
-- Agregadas: sem endereço, coordenada nem responsável (RF-20). Só pendências ATIVAS.
-- Supressão de célula pequena: some a linha com menos de 3 pendências e, se no grupo de
-- margem conhecida sobrar uma só escondida, some também a menor visível (senão sairia por subtração).
-- O 3 acompanha [indice_pressao] supressao_minima (conferido em testes/test_regras_acervo.py). Aqui a
-- complementar é feita numa passada, pela margem principal; o serviço (analise.suprimir) itera todas.
CREATE OR REPLACE VIEW vw_n1_por_atividade AS
WITH base AS (
    SELECT p.uf, a.codigo AS atividade, a.nome, COUNT(*) AS pendencias
    FROM pendencia p JOIN atividade_geradora a ON a.id = p.atividade_id
    WHERE p.data_encerramento IS NULL
    GROUP BY p.uf, a.codigo, a.nome
), marcada AS (
    SELECT b.*,
           SUM(b.pendencias < 3) OVER (PARTITION BY b.uf) AS escondidas_na_uf,
           ROW_NUMBER() OVER (PARTITION BY b.uf, b.pendencias < 3 ORDER BY b.pendencias, b.atividade) AS ordem
    FROM base b
)
SELECT uf, atividade, nome, pendencias
FROM marcada
WHERE pendencias >= 3 AND NOT (escondidas_na_uf = 1 AND ordem = 1);

-- "fora_da_previsao" = prazo_coleta vencido (previsão do caso), que não é o prazo-limite da classe
CREATE OR REPLACE VIEW vw_n1_por_motivo AS
WITH base AS (
    SELECT m.codigo AS motivo, m.nome, COUNT(*) AS pendencias,
           SUM(p.prazo_coleta < CURRENT_DATE) AS fora_da_previsao
    FROM pendencia p JOIN motivo_permanencia m ON m.id = p.motivo_id
    WHERE p.data_encerramento IS NULL
    GROUP BY m.codigo, m.nome
), marcada AS (
    SELECT b.*,
           SUM(b.pendencias < 3) OVER () AS escondidas,
           ROW_NUMBER() OVER (PARTITION BY b.pendencias < 3 ORDER BY b.pendencias, b.motivo) AS ordem
    FROM base b
)
SELECT motivo, nome, pendencias, fora_da_previsao
FROM marcada
WHERE pendencias >= 3 AND NOT (escondidas = 1 AND ordem = 1);

-- Série anual por classe: entradas, saídas e estoque ativo no fim de cada ano.
-- É o que prova que a curva pode cair: ver a consulta de queda no preparar_banco.
-- Vai de 2006 (início da série; antes, só estoque herdado) até o ano corrente: sem ano final fixo, a
-- série não para de crescer na virada do ano.
CREATE OR REPLACE VIEW vw_fluxo_estoque_anual AS
WITH RECURSIVE anos (ano) AS (
    SELECT 2006 UNION ALL SELECT ano + 1 FROM anos WHERE ano < YEAR(CURRENT_DATE)
)
SELECT a.ano,
       p.classe_risco,
       SUM(YEAR(p.data_identificacao) = a.ano)                          AS entradas,
       SUM(YEAR(p.data_encerramento) = a.ano)                           AS saidas,
       SUM(p.data_identificacao <= MAKEDATE(a.ano + 1, 1) - INTERVAL 1 DAY
           AND (p.data_encerramento IS NULL
                OR p.data_encerramento > MAKEDATE(a.ano + 1, 1) - INTERVAL 1 DAY)) AS ativas_fim_do_ano
FROM anos a
CROSS JOIN pendencia p
GROUP BY a.ano, p.classe_risco;
