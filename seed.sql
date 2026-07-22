-- Carga inicial de referência: os institutos de pesquisa monitorados.
-- Dado real (não fictício) — seguro carregar em qualquer ambiente sempre que
-- a tabela institutos estiver vazia (produção incluída: collectors/*.py
-- dependem desses instituto_id via foreign key). Pesquisas de demonstração
-- ficam em seed_demo_pesquisas.sql, carregado só em teste (ver db/core.py).

-- Inserção dos 14 institutos monitorados
INSERT INTO institutos (id, nome, sigla, site, ativo) VALUES
(1, 'Datafolha', 'Datafolha', 'datafolha.folha.uol.com.br', 1),
(2, 'Ibope/IPEC', 'IPEC', 'ipecinteligencia.com.br', 1),
(3, 'Quaest', 'Quaest', 'quaest.com.br', 1),
(4, 'Genial/Quaest', 'Genial/Quaest', 'quaest.com.br/genial', 1),
(5, 'Atlas', 'AtlasIntel', 'atlasintel.org', 1),
(6, 'Paraná', 'Paraná Pesquisas', 'paranapesquisas.com.br', 1),
(7, 'Real Time', 'Real Time Big Data', 'realtimebigdata.com.br', 1),
(8, 'Nexus/BTG Pactual', 'NEXUS', 'nexuspesquisas.com.br', 1),
(9, 'Verita', 'VERITA', 'verita.com.br', 1),
(10, 'Futura Inteligência', 'Futura', 'futurainteligencia.com.br', 1),
(11, 'PoderData', 'PoderData', 'poderdata.com.br', 1),
(12, 'Meio/Ideia', 'Ideia', 'institutoideia.com.br', 1),
(13, 'Vox Populi', 'Vox Populi', 'voxpopuli.com.br', 1),
(14, 'Instituto Gerp', 'Gerp', 'institutogerpesquisas.com.br', 1);
