-- Dados de referência do banco de segurança. Idempotente: linhas existentes são ATUALIZADAS.
-- Espelham ecosec/dominio/niveis.py: um teste confere que os dois concordam.
-- Padrão de texto do banco: maiúsculas, sem acento (ecosec/dominio/texto.py).
INSERT INTO nivel (id, titulo, publico, modo, exportacao) VALUES
(1, 'CONSULTA PUBLICA ASSISTIDA', 'SERVIDORES COM PERMISSAO GERAL', '1:N', 'LIVRE'),
(2, 'CONSULTA RESTRITA',          'DIRETORES DE DIVISAO',           '1:1', 'COM_MARCA'),
(3, 'CUSTODIA',                   'MINISTRO DO MEIO AMBIENTE',      '1:1', 'BLOQUEADA')
AS novo ON DUPLICATE KEY UPDATE titulo = novo.titulo, publico = novo.publico;
