-- Carga de dados iniciais históricos (Janeiro a Junho 2026) para o Pulso Eleitoral
-- Mapeamento de institutos atualizado conforme Passo 2

-- Inserção dos 7 institutos monitorados
INSERT INTO institutos (id, nome, sigla, site, ativo) VALUES 
(1, 'Datafolha', 'Datafolha', 'datafolha.folha.uol.com.br', 1),
(2, 'Ibope/IPEC', 'IPEC', 'ipecinteligencia.com.br', 1),
(3, 'Quaest', 'Quaest', 'quaest.com.br', 1),
(4, 'Genial/Quaest', 'Genial/Quaest', 'quaest.com.br/genial', 1),
(5, 'Atlas', 'AtlasIntel', 'atlasintel.org', 1),
(6, 'Paraná', 'Paraná Pesquisas', 'paranapesquisas.com.br', 1),
(7, 'Real Time', 'Real Time Big Data', 'realtimebigdata.com.br', 1);

-- ============================================================================
-- PESQUISAS PRESIDENCIAIS
-- ============================================================================

-- 1. Datafolha - Jan/2026 (instituto_id = 1)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (1, 1, 'presidente', '2026-01-15', '2026-01-17', 2500, 2.0, 'Folha de S.Paulo', 'BR-00001/2026', 'https://datafolha.folha.uol.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(1, 'Lula', 'PT', 42.0, 'estimulada'),
(1, 'Bolsonaro', 'PL', 36.0, 'estimulada'),
(1, 'Ciro', 'PDT', 6.0, 'estimulada'),
(1, 'Simone', 'MDB', 4.0, 'estimulada'),
(1, 'Outros/Nulos/Brancos/Indecisos', '—', 12.0, 'estimulada');

-- 2. Ibope/IPEC - Fev/2026 (instituto_id = 2)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (2, 2, 'presidente', '2026-02-10', '2026-02-12', 2000, 2.2, 'Rede Globo', 'BR-00002/2026', 'https://ipecinteligencia.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(2, 'Lula', 'PT', 41.5, 'estimulada'),
(2, 'Bolsonaro', 'PL', 35.5, 'estimulada'),
(2, 'Ciro', 'PDT', 7.0, 'estimulada'),
(2, 'Simone', 'MDB', 5.0, 'estimulada'),
(2, 'Outros/Nulos/Brancos/Indecisos', '—', 11.0, 'estimulada');

-- 3. Quaest - Fev/2026 (instituto_id = 3)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (3, 3, 'presidente', '2026-02-25', '2026-02-27', 2000, 2.2, 'Banco Genial', 'BR-00003/2026', 'https://quaest.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(3, 'Lula', 'PT', 43.0, 'estimulada'),
(3, 'Bolsonaro', 'PL', 38.0, 'estimulada'),
(3, 'Ciro', 'PDT', 5.5, 'estimulada'),
(3, 'Simone', 'MDB', 3.5, 'estimulada'),
(3, 'Outros/Nulos/Brancos/Indecisos', '—', 10.0, 'estimulada');

-- 4. Genial/Quaest - Mar/2026 (instituto_id = 4)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (4, 4, 'presidente', '2026-03-12', '2026-03-14', 2500, 2.0, 'Banco Genial', 'BR-00004/2026', 'https://quaest.com.br/genial');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(4, 'Lula', 'PT', 40.0, 'estimulada'),
(4, 'Tarcísio', 'REPUBLICANOS', 22.0, 'estimulada'),
(4, 'Ciro', 'PDT', 8.0, 'estimulada'),
(4, 'Simone', 'MDB', 6.0, 'estimulada'),
(4, 'Outros/Nulos/Brancos/Indecisos', '—', 24.0, 'estimulada');

-- 5. Atlas - Mar/2026 (instituto_id = 5)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (5, 5, 'presidente', '2026-03-22', '2026-03-24', 2000, 2.0, 'Foco Político', 'BR-00005/2026', 'https://atlasintel.org');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(5, 'Lula', 'PT', 40.5, 'estimulada'),
(5, 'Bolsonaro', 'PL', 36.5, 'estimulada'),
(5, 'Ciro', 'PDT', 6.2, 'estimulada'),
(5, 'Simone', 'MDB', 4.5, 'estimulada'),
(5, 'Outros/Nulos/Brancos/Indecisos', '—', 12.3, 'estimulada');

-- 6. Paraná - Abr/2026 (instituto_id = 6)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (6, 6, 'presidente', '2026-04-05', '2026-04-07', 2020, 2.2, 'Partido Conservador', 'BR-00006/2026', 'https://paranapesquisas.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(6, 'Lula', 'PT', 42.1, 'estimulada'),
(6, 'Bolsonaro', 'PL', 35.8, 'estimulada'),
(6, 'Ciro', 'PDT', 5.9, 'estimulada'),
(6, 'Simone', 'MDB', 4.8, 'estimulada'),
(6, 'Outros/Nulos/Brancos/Indecisos', '—', 11.4, 'estimulada');

-- 7. Real Time - Abr/2026 (instituto_id = 7)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (7, 7, 'presidente', '2026-04-18', '2026-04-20', 2000, 2.0, 'Record TV', 'BR-00007/2026', 'https://realtimebigdata.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(7, 'Lula', 'PT', 41.0, 'estimulada'),
(7, 'Bolsonaro', 'PL', 37.0, 'estimulada'),
(7, 'Ciro', 'PDT', 6.0, 'estimulada'),
(7, 'Simone', 'MDB', 4.0, 'estimulada'),
(7, 'Outros/Nulos/Brancos/Indecisos', '—', 12.0, 'estimulada');

-- 8. Datafolha - Mai/2026 (instituto_id = 1)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (8, 1, 'presidente', '2026-05-10', '2026-05-12', 2500, 2.0, 'Folha de S.Paulo', 'BR-00008/2026', 'https://datafolha.folha.uol.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(8, 'Lula', 'PT', 43.5, 'estimulada'),
(8, 'Bolsonaro', 'PL', 36.2, 'estimulada'),
(8, 'Ciro', 'PDT', 5.1, 'estimulada'),
(8, 'Simone', 'MDB', 3.9, 'estimulada'),
(8, 'Outros/Nulos/Brancos/Indecisos', '—', 11.3, 'estimulada');

-- 9. Quaest - Mai/2026 (instituto_id = 3)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (9, 3, 'presidente', '2026-05-24', '2026-05-26', 2000, 2.2, 'Banco Genial', 'BR-00009/2026', 'https://quaest.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(9, 'Lula', 'PT', 42.8, 'estimulada'),
(9, 'Bolsonaro', 'PL', 36.8, 'estimulada'),
(9, 'Ciro', 'PDT', 5.5, 'estimulada'),
(9, 'Simone', 'MDB', 4.2, 'estimulada'),
(9, 'Outros/Nulos/Brancos/Indecisos', '—', 10.7, 'estimulada');

-- 10. Atlas - Jun/2026 (instituto_id = 5)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (10, 5, 'presidente', '2026-06-08', '2026-06-10', 2000, 2.0, 'Foco Político', 'BR-00010/2026', 'https://atlasintel.org');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(10, 'Lula', 'PT', 44.2, 'estimulada'),
(10, 'Bolsonaro', 'PL', 37.5, 'estimulada'),
(10, 'Ciro', 'PDT', 4.8, 'estimulada'),
(10, 'Simone', 'MDB', 3.5, 'estimulada'),
(10, 'Outros/Nulos/Brancos/Indecisos', '—', 10.0, 'estimulada');


-- ============================================================================
-- PESQUISAS GOVERNADOR DO RIO DE JANEIRO
-- ============================================================================

-- 11. Paraná - Jan/2026 (instituto_id = 6)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (11, 6, 'governador_rj', '2026-01-20', '2026-01-22', 1500, 2.5, 'Band Rio', 'RJ-00001/2026', 'https://paranapesquisas.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(11, 'Eduardo Paes', 'PSD', 32.0, 'estimulada'),
(11, 'Cláudio Castro', 'PL', 28.0, 'estimulada'),
(11, 'Marcelo Freixo', 'PT', 15.0, 'estimulada'),
(11, 'Rodrigo Neves', 'PDT', 8.0, 'estimulada'),
(11, 'Outros/Nulos/Brancos/Indecisos', '—', 17.0, 'estimulada');

-- 12. Real Time - Fev/2026 (instituto_id = 7)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (12, 7, 'governador_rj', '2026-02-15', '2026-02-17', 1500, 2.5, 'Record TV Rio', 'RJ-00002/2026', 'https://realtimebigdata.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(12, 'Eduardo Paes', 'PSD', 33.5, 'estimulada'),
(12, 'Cláudio Castro', 'PL', 27.5, 'estimulada'),
(12, 'Marcelo Freixo', 'PT', 14.5, 'estimulada'),
(12, 'Rodrigo Neves', 'PDT', 7.5, 'estimulada'),
(12, 'Outros/Nulos/Brancos/Indecisos', '—', 17.0, 'estimulada');

-- 13. Quaest - Mar/2026 (instituto_id = 3)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (13, 3, 'governador_rj', '2026-03-08', '2026-03-10', 1200, 2.8, 'Banco Genial', 'RJ-00003/2026', 'https://quaest.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(13, 'Eduardo Paes', 'PSD', 34.0, 'estimulada'),
(13, 'Cláudio Castro', 'PL', 26.5, 'estimulada'),
(13, 'Marcelo Freixo', 'PT', 13.8, 'estimulada'),
(13, 'Rodrigo Neves', 'PDT', 9.2, 'estimulada'),
(13, 'Outros/Nulos/Brancos/Indecisos', '—', 16.5, 'estimulada');

-- 14. Atlas - Apr/2026 (instituto_id = 5)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (14, 5, 'governador_rj', '2026-04-12', '2026-04-14', 1800, 2.3, 'Foco Rio', 'RJ-00004/2026', 'https://atlasintel.org');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(14, 'Eduardo Paes', 'PSD', 35.5, 'estimulada'),
(14, 'Cláudio Castro', 'PL', 25.0, 'estimulada'),
(14, 'Marcelo Freixo', 'PT', 13.0, 'estimulada'),
(14, 'Rodrigo Neves', 'PDT', 10.0, 'estimulada'),
(14, 'Outros/Nulos/Brancos/Indecisos', '—', 16.5, 'estimulada');

-- 15. Datafolha - Mai/2026 (instituto_id = 1)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (15, 1, 'governador_rj', '2026-05-18', '2026-05-20', 1500, 2.5, 'Folha de S.Paulo', 'RJ-00005/2026', 'https://datafolha.folha.uol.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(15, 'Eduardo Paes', 'PSD', 36.8, 'estimulada'),
(15, 'Cláudio Castro', 'PL', 24.2, 'estimulada'),
(15, 'Marcelo Freixo', 'PT', 12.5, 'estimulada'),
(15, 'Rodrigo Neves', 'PDT', 9.5, 'estimulada'),
(15, 'Outros/Nulos/Brancos/Indecisos', '—', 17.0, 'estimulada');

-- 16. Quaest - Jun/2026 (instituto_id = 3)
INSERT INTO pesquisas (id, instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url) 
VALUES (16, 3, 'governador_rj', '2026-06-05', '2026-06-07', 1500, 2.5, 'Banco Genial', 'RJ-00006/2026', 'https://quaest.com.br');
INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo) VALUES 
(16, 'Eduardo Paes', 'PSD', 37.2, 'estimulada'),
(16, 'Cláudio Castro', 'PL', 23.8, 'estimulada'),
(16, 'Marcelo Freixo', 'PT', 12.0, 'estimulada'),
(16, 'Rodrigo Neves', 'PDT', 10.2, 'estimulada'),
(16, 'Outros/Nulos/Brancos/Indecisos', '—', 16.8, 'estimulada');
