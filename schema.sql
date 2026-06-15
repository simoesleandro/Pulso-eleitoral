-- Schema do banco de dados SQLite para o projeto Pulso Eleitoral

-- 1. Institutos de pesquisa
CREATE TABLE IF NOT EXISTS institutos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    sigla TEXT,
    site TEXT,
    ativo INTEGER DEFAULT 1, -- 1 = ativo, 0 = inativo
    criado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 2. Pesquisas eleitorais
CREATE TABLE IF NOT EXISTS pesquisas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instituto_id INTEGER NOT NULL,
    cargo TEXT NOT NULL, -- 'presidente' | 'governador_rj'
    data_pesquisa TEXT NOT NULL, -- Formato YYYY-MM-DD (período de campo da pesquisa)
    data_publicacao TEXT NOT NULL, -- Formato YYYY-MM-DD
    tamanho_amostra INTEGER NOT NULL,
    margem_erro REAL NOT NULL,
    contratante TEXT,
    registro_tse TEXT NOT NULL UNIQUE, -- Código de registro único no TSE (ex: BR-12345/2026)
    fonte_url TEXT,
    coletado_em TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(instituto_id) REFERENCES institutos(id) ON DELETE CASCADE
);

-- 3. Intenções de voto associadas a cada pesquisa
CREATE TABLE IF NOT EXISTS intencoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pesquisa_id INTEGER NOT NULL,
    candidato TEXT NOT NULL,
    partido TEXT,
    percentual REAL NOT NULL,
    tipo TEXT NOT NULL, -- 'espontanea' | 'estimulada'
    FOREIGN KEY(pesquisa_id) REFERENCES pesquisas(id) ON DELETE CASCADE
);

-- 4. Eventos e marcos políticos importantes da campanha
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL, -- Formato YYYY-MM-DD
    titulo TEXT NOT NULL,
    descricao TEXT,
    cargo TEXT NOT NULL, -- 'presidente' | 'governador_rj' | 'geral'
    impacto TEXT NOT NULL, -- 'positivo' | 'negativo' | 'neutro' | 'indefinido'
    criado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 5. Alertas de variação gerados pelo sistema
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL, -- 'variacao' | 'recorde' | 'nova_pesquisa'
    candidato TEXT NOT NULL,
    cargo TEXT NOT NULL, -- 'presidente' | 'governador_rj'
    variacao REAL, -- Variação em pontos percentuais (ex: 2.5)
    pesquisa_id INTEGER,
    enviado_telegram INTEGER DEFAULT 0, -- 0 = não enviado, 1 = enviado
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(pesquisa_id) REFERENCES pesquisas(id) ON DELETE SET NULL
);

-- 6. Cache de análises de tendências geradas pela IA (Gemini)
CREATE TABLE IF NOT EXISTS analises_ia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cargo TEXT NOT NULL UNIQUE, -- 'presidente' | 'governador_rj'
    texto TEXT NOT NULL,
    criado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Índices de desempenho recomendados no PRD
CREATE INDEX IF NOT EXISTS idx_intencoes_pesquisa_id ON intencoes(pesquisa_id);
CREATE INDEX IF NOT EXISTS idx_intencoes_candidato ON intencoes(candidato);
CREATE INDEX IF NOT EXISTS idx_pesquisas_cargo ON pesquisas(cargo);
CREATE INDEX IF NOT EXISTS idx_pesquisas_data_pesquisa ON pesquisas(data_pesquisa);
CREATE INDEX IF NOT EXISTS idx_alertas_cargo ON alertas(cargo);
