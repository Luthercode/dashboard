-- =============================================================
-- SQL para criar as tabelas no Supabase (rode no SQL Editor)
-- =============================================================

-- Tabela de transações financeiras
CREATE TABLE IF NOT EXISTS transactions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('renda', 'gasto')),
    valor NUMERIC(12, 2) NOT NULL CHECK (valor > 0),
    descricao VARCHAR(200) NOT NULL,
    categoria VARCHAR(50) DEFAULT 'Outros',
    data DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Tabela de layouts personalizados do dashboard
CREATE TABLE IF NOT EXISTS dashboard_layouts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    layout JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Tabela de planilhas do usuário
CREATE TABLE IF NOT EXISTS spreadsheets (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    nome VARCHAR(100) NOT NULL,
    descricao VARCHAR(500) DEFAULT '',
    dados JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================================
-- Row Level Security (RLS) — cada usuário só acessa seus dados
-- =============================================================

-- Habilita RLS
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE dashboard_layouts ENABLE ROW LEVEL SECURITY;

-- Políticas para transactions
CREATE POLICY "Users can view own transactions"
    ON transactions FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own transactions"
    ON transactions FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own transactions"
    ON transactions FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own transactions"
    ON transactions FOR DELETE
    USING (auth.uid() = user_id);

-- Políticas para dashboard_layouts
CREATE POLICY "Users can view own layout"
    ON dashboard_layouts FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own layout"
    ON dashboard_layouts FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own layout"
    ON dashboard_layouts FOR UPDATE
    USING (auth.uid() = user_id);

-- =============================================================
-- Índices para performance
-- =============================================================

CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_data ON transactions(user_id, data DESC);
CREATE INDEX IF NOT EXISTS idx_dashboard_layouts_user_id ON dashboard_layouts(user_id);
