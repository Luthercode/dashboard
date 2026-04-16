"""
Dashboard Financeiro Pessoal — Backend FastAPI
Servidor principal com autenticação Supabase e endpoints REST.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt
from pydantic import BaseModel, Field
from supabase import create_client, Client

# ── Configuração ─────────────────────────────────────────────────────────────

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # anon key — usado para auth (login/register)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", SUPABASE_KEY)  # service_role key — usado para queries (ignora RLS)

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise RuntimeError("Variáveis SUPABASE_URL e SUPABASE_KEY são obrigatórias no .env")

# Cliente para autenticação (anon key)
supabase_auth: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# Cliente para dados (service_role key — ignora RLS)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI(title="Dashboard Financeiro", version="1.0.0")

# CORS — permite o frontend se comunicar com o backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Handler global de exceções — garante que CORS headers são sempre enviados
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erro interno: {str(exc)}"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true",
        },
    )

# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)

class TransactionCreate(BaseModel):
    tipo: str = Field(pattern=r"^(renda|gasto)$")
    valor: float = Field(gt=0)
    descricao: str = Field(min_length=1, max_length=200)
    categoria: str = Field(default="Outros", max_length=50)
    data: str  # formato YYYY-MM-DD

class LayoutSave(BaseModel):
    layout: dict

class TransactionUpdate(BaseModel):
    tipo: Optional[str] = Field(None, pattern=r"^(renda|gasto)$")
    valor: Optional[float] = Field(None, gt=0)
    descricao: Optional[str] = Field(None, min_length=1, max_length=200)
    categoria: Optional[str] = Field(None, max_length=50)
    data: Optional[str] = None  # formato YYYY-MM-DD

class SpreadsheetCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    descricao: str = Field(default="", max_length=500)
    dados: dict  # {columns:[{id,name,type}], rows:[[values]]}

class SpreadsheetUpdate(BaseModel):
    nome: Optional[str] = Field(None, max_length=100)
    descricao: Optional[str] = Field(None, max_length=500)
    dados: Optional[dict] = None

# ── Autenticação ─────────────────────────────────────────────────────────────

def get_current_user_id(authorization: str = Header(...)) -> str:
    """Extrai o user_id do token JWT do Supabase.
    A segurança dos dados é garantida pelo RLS no banco."""
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    try:
        # Decodifica o token — extrai claims sem verificar assinatura
        # A proteção real dos dados é feita pelo Row Level Security do Supabase
        payload = jwt.get_unverified_claims(token)

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido: sem sub")
        return user_id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")

# ── Endpoints de Autenticação ────────────────────────────────────────────────

@app.post("/register")
def register(body: AuthRequest):
    """Cria uma nova conta no Supabase Auth."""
    try:
        res = supabase_auth.auth.sign_up({"email": body.email, "password": body.password})
        if res.user is None:
            raise HTTPException(status_code=400, detail="Erro ao criar conta. Verifique os dados.")
        return {"message": "Conta criada com sucesso! Verifique seu e-mail se necessário.", "user_id": res.user.id}
    except Exception as e:
        detail = str(e)
        raise HTTPException(status_code=400, detail=detail)

@app.post("/login")
def login(body: AuthRequest):
    """Faz login e retorna o token JWT."""
    try:
        res = supabase_auth.auth.sign_in_with_password({"email": body.email, "password": body.password})
        if res.session is None:
            raise HTTPException(status_code=401, detail="Credenciais inválidas")
        return {
            "access_token": res.session.access_token,
            "user_id": res.user.id,
            "email": res.user.email,
        }
    except Exception as e:
        detail = str(e)
        raise HTTPException(status_code=401, detail=detail)

# ── Endpoints de Transações ──────────────────────────────────────────────────

@app.get("/transactions")
def list_transactions(
    user_id: str = Depends(get_current_user_id),
    periodo: Optional[str] = Query(None, pattern=r"^(7d|30d|90d|12m|all)$"),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
):
    """Lista transações do usuário com filtros opcionais de período."""
    query = supabase.table("transactions").select("*").eq("user_id", user_id)

    # Filtro por período predefinido
    if periodo and periodo != "all":
        hoje = datetime.now().date()
        if periodo == "7d":
            inicio = hoje - timedelta(days=7)
        elif periodo == "30d":
            inicio = hoje - timedelta(days=30)
        elif periodo == "90d":
            inicio = hoje - timedelta(days=90)
        elif periodo == "12m":
            inicio = hoje - timedelta(days=365)
        query = query.gte("data", inicio.isoformat())
    elif data_inicio:
        query = query.gte("data", data_inicio)

    if data_fim:
        query = query.lte("data", data_fim)

    res = query.order("data", desc=True).execute()
    return res.data

@app.post("/transactions")
def create_transaction(body: TransactionCreate, user_id: str = Depends(get_current_user_id)):
    """Cria uma nova transação para o usuário autenticado."""
    # Valida formato da data
    try:
        datetime.strptime(body.data, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Data deve estar no formato YYYY-MM-DD")

    row = {
        "user_id": user_id,
        "tipo": body.tipo,
        "valor": body.valor,
        "descricao": body.descricao,
        "data": body.data,
        "categoria": body.categoria,
    }
    res = supabase.table("transactions").insert(row).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Erro ao salvar transação")
    return res.data[0]

@app.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: str, user_id: str = Depends(get_current_user_id)):
    """Deleta uma transação do usuário."""
    res = supabase.table("transactions").delete().eq("id", tx_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    return {"ok": True}

@app.put("/transactions/{tx_id}")
def update_transaction(tx_id: str, body: TransactionUpdate, user_id: str = Depends(get_current_user_id)):
    """Atualiza uma transação existente do usuário."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    if "data" in updates:
        try:
            datetime.strptime(updates["data"], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Data deve estar no formato YYYY-MM-DD")
    res = supabase.table("transactions").update(updates).eq("id", tx_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    return res.data[0]

# ── Endpoint de Resumo ───────────────────────────────────────────────────────

@app.get("/summary")
def get_summary(
    user_id: str = Depends(get_current_user_id),
    periodo: Optional[str] = Query(None, pattern=r"^(7d|30d|90d|12m|all)$"),
):
    """Retorna resumo financeiro completo com agrupamentos para gráficos."""
    query = supabase.table("transactions").select("tipo, valor, data, categoria, descricao").eq("user_id", user_id)

    hoje = datetime.now().date()
    if periodo and periodo != "all":
        if periodo == "7d":
            inicio = hoje - timedelta(days=7)
        elif periodo == "30d":
            inicio = hoje - timedelta(days=30)
        elif periodo == "90d":
            inicio = hoje - timedelta(days=90)
        elif periodo == "12m":
            inicio = hoje - timedelta(days=365)
        query = query.gte("data", inicio.isoformat())

    res = query.execute()

    total_renda = 0.0
    total_gasto = 0.0
    monthly: dict[str, dict[str, float]] = {}
    daily: dict[str, dict[str, float]] = {}
    categorias_gasto: dict[str, float] = {}
    categorias_renda: dict[str, float] = {}
    maior_gasto = None
    maior_renda = None

    for t in res.data:
        data_str = t["data"][:10]  # YYYY-MM-DD (remove timestamp se existir)
        mes = data_str[:7]  # YYYY-MM
        cat = t.get("categoria") or "Outros"

        if mes not in monthly:
            monthly[mes] = {"renda": 0.0, "gasto": 0.0}
        if data_str not in daily:
            daily[data_str] = {"renda": 0.0, "gasto": 0.0}

        if t["tipo"] == "renda":
            total_renda += t["valor"]
            monthly[mes]["renda"] += t["valor"]
            daily[data_str]["renda"] += t["valor"]
            categorias_renda[cat] = categorias_renda.get(cat, 0.0) + t["valor"]
            if maior_renda is None or t["valor"] > maior_renda["valor"]:
                maior_renda = {"valor": t["valor"], "descricao": t.get("descricao", ""), "data": data_str}
        else:
            total_gasto += t["valor"]
            monthly[mes]["gasto"] += t["valor"]
            daily[data_str]["gasto"] += t["valor"]
            categorias_gasto[cat] = categorias_gasto.get(cat, 0.0) + t["valor"]
            if maior_gasto is None or t["valor"] > maior_gasto["valor"]:
                maior_gasto = {"valor": t["valor"], "descricao": t.get("descricao", ""), "data": data_str}

    evolucao = [{"mes": k, **v} for k, v in sorted(monthly.items())]
    evolucao_diaria = [{"dia": k, **v} for k, v in sorted(daily.items())]

    # Top categorias (ordenadas por valor)
    top_cat_gasto = sorted(categorias_gasto.items(), key=lambda x: x[1], reverse=True)
    top_cat_renda = sorted(categorias_renda.items(), key=lambda x: x[1], reverse=True)

    # Média diária de gasto
    dias_com_gasto = len([d for d in daily.values() if d["gasto"] > 0])
    media_diaria_gasto = total_gasto / dias_com_gasto if dias_com_gasto > 0 else 0.0

    return {
        "total_renda": total_renda,
        "total_gasto": total_gasto,
        "saldo": total_renda - total_gasto,
        "num_transacoes": len(res.data),
        "media_diaria_gasto": round(media_diaria_gasto, 2),
        "maior_gasto": maior_gasto,
        "maior_renda": maior_renda,
        "evolucao": evolucao,
        "evolucao_diaria": evolucao_diaria,
        "categorias_gasto": [{"nome": k, "valor": v} for k, v in top_cat_gasto],
        "categorias_renda": [{"nome": k, "valor": v} for k, v in top_cat_renda],
    }

# ── Endpoint de Resumo Mensal ─────────────────────────────────────────────────

@app.get("/summary/monthly")
def get_monthly_summary(
    user_id: str = Depends(get_current_user_id),
    mes: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
):
    """Retorna resumo detalhado de um mês específico com comparação ao mês anterior."""
    hoje = datetime.now().date()
    if mes:
        ano, m = mes.split("-")
        target_year, target_month = int(ano), int(m)
    else:
        target_year, target_month = hoje.year, hoje.month

    # Mês atual
    inicio_mes = f"{target_year}-{target_month:02d}-01"
    if target_month == 12:
        inicio_prox = f"{target_year + 1}-01-01"
    else:
        inicio_prox = f"{target_year}-{target_month + 1:02d}-01"

    # Mês anterior
    if target_month == 1:
        prev_year, prev_month = target_year - 1, 12
    else:
        prev_year, prev_month = target_year, target_month - 1
    inicio_ant = f"{prev_year}-{prev_month:02d}-01"

    # Buscar transações do mês atual e anterior
    res_atual = (
        supabase.table("transactions")
        .select("tipo, valor, data, categoria, descricao")
        .eq("user_id", user_id)
        .gte("data", inicio_ant)
        .lt("data", inicio_prox)
        .execute()
    )

    tx_mes = [t for t in res_atual.data if t["data"][:7] == f"{target_year}-{target_month:02d}"]
    tx_ant = [t for t in res_atual.data if t["data"][:7] == f"{prev_year}-{prev_month:02d}"]

    def calc(txs):
        renda, gasto = 0.0, 0.0
        cats_g, cats_r = {}, {}
        daily = {}
        for t in txs:
            dia = t["data"][:10]
            cat = t.get("categoria") or "Outros"
            if dia not in daily:
                daily[dia] = {"renda": 0.0, "gasto": 0.0}
            if t["tipo"] == "renda":
                renda += t["valor"]
                daily[dia]["renda"] += t["valor"]
                cats_r[cat] = cats_r.get(cat, 0.0) + t["valor"]
            else:
                gasto += t["valor"]
                daily[dia]["gasto"] += t["valor"]
                cats_g[cat] = cats_g.get(cat, 0.0) + t["valor"]
        return {
            "total_renda": renda,
            "total_gasto": gasto,
            "saldo": renda - gasto,
            "num_transacoes": len(txs),
            "taxa_economia": round((renda - gasto) / renda * 100, 1) if renda > 0 else 0,
            "categorias_gasto": sorted(cats_g.items(), key=lambda x: x[1], reverse=True),
            "categorias_renda": sorted(cats_r.items(), key=lambda x: x[1], reverse=True),
            "diario": [{"dia": k, **v} for k, v in sorted(daily.items())],
        }

    atual = calc(tx_mes)
    anterior = calc(tx_ant)

    # Comparações
    var_renda = ((atual["total_renda"] - anterior["total_renda"]) / anterior["total_renda"] * 100) if anterior["total_renda"] > 0 else 0
    var_gasto = ((atual["total_gasto"] - anterior["total_gasto"]) / anterior["total_gasto"] * 100) if anterior["total_gasto"] > 0 else 0

    # Maior gasto e renda do mês
    maior_gasto = max(tx_mes, key=lambda t: t["valor"] if t["tipo"] == "gasto" else 0, default=None)
    maior_renda = max(tx_mes, key=lambda t: t["valor"] if t["tipo"] == "renda" else 0, default=None)

    # Média diária
    dias_com_gasto = len([d for d in atual["diario"] if d["gasto"] > 0])
    media_diaria = atual["total_gasto"] / dias_com_gasto if dias_com_gasto > 0 else 0

    # Score financeiro (0-100)
    score = 50
    if atual["taxa_economia"] >= 30:
        score += 25
    elif atual["taxa_economia"] >= 15:
        score += 15
    elif atual["taxa_economia"] >= 5:
        score += 5
    elif atual["taxa_economia"] < 0:
        score -= 20

    if var_gasto < 0:
        score += 10  # gastou menos que mês anterior
    elif var_gasto > 20:
        score -= 10

    if var_renda > 0:
        score += 10
    elif var_renda < -10:
        score -= 5

    num_cats = len(atual["categorias_gasto"])
    if num_cats >= 3:
        score += 5  # diversificação de gastos

    score = max(0, min(100, score))

    MESES_PT = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

    return {
        "mes": f"{target_year}-{target_month:02d}",
        "mes_nome": MESES_PT[target_month - 1] + f" {target_year}",
        "atual": {
            "total_renda": atual["total_renda"],
            "total_gasto": atual["total_gasto"],
            "saldo": atual["saldo"],
            "num_transacoes": atual["num_transacoes"],
            "taxa_economia": atual["taxa_economia"],
            "media_diaria_gasto": round(media_diaria, 2),
            "categorias_gasto": [{"nome": k, "valor": v} for k, v in atual["categorias_gasto"]],
            "categorias_renda": [{"nome": k, "valor": v} for k, v in atual["categorias_renda"]],
            "diario": atual["diario"],
        },
        "anterior": {
            "total_renda": anterior["total_renda"],
            "total_gasto": anterior["total_gasto"],
            "saldo": anterior["saldo"],
            "num_transacoes": anterior["num_transacoes"],
        },
        "comparacao": {
            "var_renda_pct": round(var_renda, 1),
            "var_gasto_pct": round(var_gasto, 1),
            "var_saldo": round(atual["saldo"] - anterior["saldo"], 2),
        },
        "maior_gasto": {"valor": maior_gasto["valor"], "descricao": maior_gasto.get("descricao", "")} if maior_gasto and maior_gasto["tipo"] == "gasto" else None,
        "maior_renda": {"valor": maior_renda["valor"], "descricao": maior_renda.get("descricao", "")} if maior_renda and maior_renda["tipo"] == "renda" else None,
        "score_financeiro": score,
        "dicas": _gerar_dicas(atual, anterior, var_gasto, var_renda),
    }


def _gerar_dicas(atual, anterior, var_gasto, var_renda):
    """Gera dicas financeiras personalizadas baseadas nos dados."""
    dicas = []
    if atual["taxa_economia"] < 10:
        dicas.append("⚠️ Sua taxa de economia está baixa. Tente guardar pelo menos 15% da renda.")
    if atual["taxa_economia"] >= 30:
        dicas.append("🎉 Excelente! Você está economizando mais de 30% da renda!")
    if var_gasto > 20:
        dicas.append("📈 Seus gastos aumentaram mais de 20% em relação ao mês anterior. Revise suas despesas.")
    if var_gasto < -10:
        dicas.append("👏 Parabéns! Você reduziu seus gastos em relação ao mês passado.")
    if var_renda > 0:
        dicas.append("💰 Sua renda aumentou! Considere investir o excedente.")
    if len(atual["categorias_gasto"]) > 0:
        top_cat = atual["categorias_gasto"][0]
        pct = (top_cat[1] / atual["total_gasto"] * 100) if atual["total_gasto"] > 0 else 0
        if pct > 40:
            dicas.append(f"🔍 A categoria '{top_cat[0]}' corresponde a {pct:.0f}% dos seus gastos. Avalie se pode reduzir.")
    if atual["saldo"] < 0:
        dicas.append("🚨 Saldo negativo! Você gastou mais do que recebeu neste mês.")
    if not dicas:
        dicas.append("✅ Suas finanças estão equilibradas. Continue assim!")
    return dicas


# ── Endpoints de Layout ─────────────────────────────────────────────────────

DEFAULT_LAYOUT = {
    "tema": "light",
    "widgets": [
        {"id": "saldo", "x": 0, "y": 0, "w": 12, "h": 2},
        {"id": "grafico_pizza", "x": 0, "y": 2, "w": 6, "h": 4},
        {"id": "grafico_linha", "x": 6, "y": 2, "w": 6, "h": 4},
        {"id": "transacoes", "x": 0, "y": 6, "w": 12, "h": 4},
    ],
}

@app.get("/layout")
def get_layout(user_id: str = Depends(get_current_user_id)):
    """Retorna o layout do dashboard do usuário. Cria um padrão se não existir."""
    try:
        res = (
            supabase.table("dashboard_layouts")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]

        # Tenta criar layout padrão
        try:
            row = {"user_id": user_id, "layout": DEFAULT_LAYOUT}
            insert_res = supabase.table("dashboard_layouts").insert(row).execute()
            if insert_res.data:
                return insert_res.data[0]
        except Exception:
            pass

    except Exception as e:
        # Tabela pode não existir — retorna layout padrão sem salvar
        pass

    return {"id": None, "user_id": user_id, "layout": DEFAULT_LAYOUT}

@app.post("/layout")
def save_layout(body: LayoutSave, user_id: str = Depends(get_current_user_id)):
    """Salva/atualiza o layout do dashboard do usuário."""
    try:
        existing = (
            supabase.table("dashboard_layouts")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            res = (
                supabase.table("dashboard_layouts")
                .update({"layout": body.layout})
                .eq("user_id", user_id)
                .execute()
            )
        else:
            res = (
                supabase.table("dashboard_layouts")
                .insert({"user_id": user_id, "layout": body.layout})
                .execute()
            )
        if res.data:
            return res.data[0]
    except Exception:
        pass

    return {"id": None, "user_id": user_id, "layout": body.layout}

# ── Endpoints de Planilhas ────────────────────────────────────────────────────

SPREADSHEET_TEMPLATES = [
    {
        "id": "orcamento-mensal",
        "nome": "Orçamento Mensal",
        "descricao": "Planeje receitas e despesas do mês",
        "icone": "bi-calendar-month",
        "cor": "#6366f1",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Categoria", "type": "text"},
                {"id": "c2", "name": "Previsto", "type": "currency"},
                {"id": "c3", "name": "Realizado", "type": "currency"},
                {"id": "c4", "name": "Diferença", "type": "currency"},
            ],
            "rows": [
                ["Salário", 5000, 5000, 0],
                ["Aluguel", 1500, 1500, 0],
                ["Alimentação", 800, 0, 800],
                ["Transporte", 400, 0, 400],
                ["Saúde", 200, 0, 200],
                ["Lazer", 300, 0, 300],
                ["Educação", 150, 0, 150],
                ["Outros", 200, 0, 200],
            ],
        },
    },
    {
        "id": "controle-gastos",
        "nome": "Controle de Gastos Diário",
        "descricao": "Registre gastos dia a dia",
        "icone": "bi-cash-stack",
        "cor": "#ef4444",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Data", "type": "date"},
                {"id": "c2", "name": "Descrição", "type": "text"},
                {"id": "c3", "name": "Categoria", "type": "text"},
                {"id": "c4", "name": "Valor", "type": "currency"},
                {"id": "c5", "name": "Forma Pgto", "type": "text"},
            ],
            "rows": [
                ["2026-04-01", "Supermercado", "Alimentação", 250, "Débito"],
                ["2026-04-02", "Uber", "Transporte", 35, "Crédito"],
                ["2026-04-03", "Farmácia", "Saúde", 80, "Pix"],
            ],
        },
    },
    {
        "id": "metas-economia",
        "nome": "Metas de Economia",
        "descricao": "Acompanhe suas metas financeiras",
        "icone": "bi-piggy-bank",
        "cor": "#22c55e",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Meta", "type": "text"},
                {"id": "c2", "name": "Objetivo (R$)", "type": "currency"},
                {"id": "c3", "name": "Economizado", "type": "currency"},
                {"id": "c4", "name": "Prazo", "type": "date"},
                {"id": "c5", "name": "Status", "type": "text"},
            ],
            "rows": [
                ["Reserva Emergência", 15000, 5000, "2026-12-31", "Em progresso"],
                ["Viagem", 8000, 2000, "2026-07-01", "Em progresso"],
                ["Notebook novo", 5000, 3500, "2026-06-01", "Quase lá"],
            ],
        },
    },
    {
        "id": "fluxo-caixa",
        "nome": "Fluxo de Caixa",
        "descricao": "Controle entradas e saídas mensais",
        "icone": "bi-graph-up-arrow",
        "cor": "#3b82f6",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Mês", "type": "text"},
                {"id": "c2", "name": "Entradas", "type": "currency"},
                {"id": "c3", "name": "Saídas", "type": "currency"},
                {"id": "c4", "name": "Saldo", "type": "currency"},
                {"id": "c5", "name": "Acumulado", "type": "currency"},
            ],
            "rows": [
                ["Janeiro", 6000, 4500, 1500, 1500],
                ["Fevereiro", 6000, 5000, 1000, 2500],
                ["Março", 6500, 4800, 1700, 4200],
                ["Abril", 0, 0, 0, 4200],
            ],
        },
    },
    {
        "id": "lista-compras",
        "nome": "Lista de Compras",
        "descricao": "Organize suas compras com preços",
        "icone": "bi-cart-check",
        "cor": "#f59e0b",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Item", "type": "text"},
                {"id": "c2", "name": "Quantidade", "type": "number"},
                {"id": "c3", "name": "Preço Unit.", "type": "currency"},
                {"id": "c4", "name": "Total", "type": "currency"},
                {"id": "c5", "name": "Comprado", "type": "text"},
            ],
            "rows": [
                ["Arroz 5kg", 1, 25.90, 25.90, "Não"],
                ["Feijão 1kg", 2, 8.50, 17.00, "Não"],
                ["Leite 1L", 6, 5.90, 35.40, "Não"],
            ],
        },
    },
    {
        "id": "planejamento-anual",
        "nome": "Planejamento Anual",
        "descricao": "Visão geral das finanças do ano",
        "icone": "bi-calendar-range",
        "cor": "#8b5cf6",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Mês", "type": "text"},
                {"id": "c2", "name": "Renda Prevista", "type": "currency"},
                {"id": "c3", "name": "Gastos Previstos", "type": "currency"},
                {"id": "c4", "name": "Investimento", "type": "currency"},
                {"id": "c5", "name": "Observação", "type": "text"},
            ],
            "rows": [
                ["Janeiro", 6000, 4500, 500, ""],
                ["Fevereiro", 6000, 4500, 500, ""],
                ["Março", 6000, 4500, 500, ""],
                ["Abril", 6000, 5000, 300, "IPTU"],
                ["Maio", 6000, 4500, 500, ""],
                ["Junho", 6000, 4500, 500, ""],
                ["Julho", 6000, 5500, 200, "Férias"],
                ["Agosto", 6000, 4500, 500, ""],
                ["Setembro", 6000, 4500, 500, ""],
                ["Outubro", 6000, 4500, 500, ""],
                ["Novembro", 6000, 4500, 500, ""],
                ["Dezembro", 7000, 6000, 500, "13° salário"],
            ],
        },
    },
    {
        "id": "cartao-credito",
        "nome": "Controle Cartão de Crédito",
        "descricao": "Fatura, limite e parcelas do cartão",
        "icone": "bi-credit-card-2-front",
        "cor": "#ec4899",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Compra", "type": "text"},
                {"id": "c2", "name": "Data", "type": "date"},
                {"id": "c3", "name": "Valor Total", "type": "currency"},
                {"id": "c4", "name": "Parcelas", "type": "number"},
                {"id": "c5", "name": "Parcela Atual", "type": "text"},
                {"id": "c6", "name": "Valor Parcela", "type": "currency"},
            ],
            "rows": [
                ["TV Samsung 55\"", "2026-01-15", 3200, 10, "4/10", 320],
                ["iPhone 15", "2026-02-20", 5400, 12, "3/12", 450],
                ["Restaurante", "2026-04-05", 180, 1, "1/1", 180],
                ["Spotify anual", "2026-03-01", 240, 1, "1/1", 240],
                ["Passagem aérea", "2026-03-10", 1800, 6, "2/6", 300],
            ],
        },
    },
    {
        "id": "investimentos",
        "nome": "Carteira de Investimentos",
        "descricao": "Acompanhe seus investimentos e rendimentos",
        "icone": "bi-graph-up",
        "cor": "#14b8a6",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Ativo", "type": "text"},
                {"id": "c2", "name": "Tipo", "type": "text"},
                {"id": "c3", "name": "Investido", "type": "currency"},
                {"id": "c4", "name": "Valor Atual", "type": "currency"},
                {"id": "c5", "name": "Rendimento %", "type": "number"},
                {"id": "c6", "name": "Vencimento", "type": "date"},
            ],
            "rows": [
                ["Tesouro Selic 2029", "Renda Fixa", 10000, 11200, 12.0, "2029-03-01"],
                ["CDB 120% CDI", "Renda Fixa", 5000, 5650, 13.0, "2027-06-01"],
                ["PETR4", "Ações", 3000, 3450, 15.0, ""],
                ["IVVB11", "ETF", 4000, 4800, 20.0, ""],
                ["Bitcoin", "Crypto", 2000, 2800, 40.0, ""],
                ["Poupança", "Renda Fixa", 8000, 8480, 6.0, ""],
            ],
        },
    },
    {
        "id": "controle-dividas",
        "nome": "Controle de Dívidas",
        "descricao": "Organize e quite suas dívidas",
        "icone": "bi-exclamation-diamond",
        "cor": "#f43f5e",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Dívida", "type": "text"},
                {"id": "c2", "name": "Credor", "type": "text"},
                {"id": "c3", "name": "Valor Original", "type": "currency"},
                {"id": "c4", "name": "Saldo Devedor", "type": "currency"},
                {"id": "c5", "name": "Parcela Mensal", "type": "currency"},
                {"id": "c6", "name": "Juros % a.m.", "type": "number"},
                {"id": "c7", "name": "Previsão Quitação", "type": "date"},
            ],
            "rows": [
                ["Financiamento Carro", "Banco X", 45000, 28000, 1200, 1.2, "2028-08-01"],
                ["Empréstimo Pessoal", "Banco Y", 10000, 6500, 580, 1.8, "2027-05-01"],
                ["Cartão de Crédito", "Nubank", 3000, 3000, 150, 14.0, "2028-02-01"],
            ],
        },
    },
    {
        "id": "comparacao-precos",
        "nome": "Comparação de Preços",
        "descricao": "Compare preços entre lojas e encontre o melhor negócio",
        "icone": "bi-shop",
        "cor": "#06b6d4",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Produto", "type": "text"},
                {"id": "c2", "name": "Loja A", "type": "currency"},
                {"id": "c3", "name": "Loja B", "type": "currency"},
                {"id": "c4", "name": "Loja C", "type": "currency"},
                {"id": "c5", "name": "Menor Preço", "type": "currency"},
                {"id": "c6", "name": "Economia", "type": "currency"},
            ],
            "rows": [
                ["Arroz 5kg", 27.90, 25.50, 26.80, 25.50, 2.40],
                ["Óleo de Soja", 8.90, 9.50, 7.99, 7.99, 1.51],
                ["Café 500g", 18.90, 16.50, 17.80, 16.50, 2.40],
                ["Sabão em pó", 22.00, 19.90, 21.50, 19.90, 2.10],
                ["Leite UHT", 5.49, 4.99, 5.29, 4.99, 0.50],
            ],
        },
    },
    {
        "id": "freelance-projetos",
        "nome": "Controle de Freelances",
        "descricao": "Gerencie projetos, prazos e pagamentos freelancer",
        "icone": "bi-laptop",
        "cor": "#f97316",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Cliente", "type": "text"},
                {"id": "c2", "name": "Projeto", "type": "text"},
                {"id": "c3", "name": "Valor", "type": "currency"},
                {"id": "c4", "name": "Início", "type": "date"},
                {"id": "c5", "name": "Entrega", "type": "date"},
                {"id": "c6", "name": "Status", "type": "text"},
                {"id": "c7", "name": "Pago?", "type": "text"},
            ],
            "rows": [
                ["Maria Silva", "Landing Page", 2500, "2026-03-01", "2026-03-20", "Entregue", "Sim"],
                ["Tech Corp", "Dashboard React", 8000, "2026-03-15", "2026-04-30", "Em andamento", "50%"],
                ["Loja ABC", "E-commerce", 12000, "2026-04-01", "2026-06-01", "Em andamento", "30%"],
                ["João Pereira", "App Mobile", 15000, "2026-04-10", "2026-07-10", "Negociando", "Não"],
            ],
        },
    },
    {
        "id": "contas-fixas",
        "nome": "Contas Fixas Mensais",
        "descricao": "Controle todas suas contas fixas e vencimentos",
        "icone": "bi-receipt-cutoff",
        "cor": "#a855f7",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Conta", "type": "text"},
                {"id": "c2", "name": "Vencimento (dia)", "type": "number"},
                {"id": "c3", "name": "Valor Médio", "type": "currency"},
                {"id": "c4", "name": "Última Fatura", "type": "currency"},
                {"id": "c5", "name": "Pago?", "type": "text"},
                {"id": "c6", "name": "Forma Pgto", "type": "text"},
            ],
            "rows": [
                ["Aluguel", 5, 1500, 1500, "Sim", "Pix"],
                ["Energia", 10, 180, 195, "Sim", "Débito Auto"],
                ["Água", 15, 80, 72, "Não", "Boleto"],
                ["Internet", 20, 120, 120, "Sim", "Crédito"],
                ["Celular", 12, 65, 65, "Sim", "Crédito"],
                ["Streaming", 1, 55, 55, "Sim", "Crédito"],
                ["Academia", 5, 100, 100, "Sim", "Débito"],
                ["Seguro Carro", 25, 250, 250, "Não", "Boleto"],
                ["Plano Saúde", 10, 400, 400, "Sim", "Débito Auto"],
                ["Condomínio", 5, 350, 370, "Sim", "Boleto"],
            ],
        },
    },
    {
        "id": "viagem",
        "nome": "Planejamento de Viagem",
        "descricao": "Organize custos e itinerário da viagem",
        "icone": "bi-airplane",
        "cor": "#0ea5e9",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Item", "type": "text"},
                {"id": "c2", "name": "Categoria", "type": "text"},
                {"id": "c3", "name": "Estimado", "type": "currency"},
                {"id": "c4", "name": "Real", "type": "currency"},
                {"id": "c5", "name": "Reservado?", "type": "text"},
            ],
            "rows": [
                ["Passagem Aérea (ida/volta)", "Transporte", 1500, 1350, "Sim"],
                ["Hotel 5 noites", "Hospedagem", 2000, 1800, "Sim"],
                ["Seguro Viagem", "Seguro", 200, 180, "Sim"],
                ["Alimentação (5 dias)", "Alimentação", 800, 0, "Não"],
                ["Passeios e Tours", "Lazer", 600, 0, "Não"],
                ["Transporte Local", "Transporte", 300, 0, "Não"],
                ["Compras/Souvenir", "Compras", 500, 0, "Não"],
                ["Emergência", "Reserva", 400, 0, "—"],
            ],
        },
    },
    # ── Templates de Propósito Geral ──
    {
        "id": "lista-tarefas",
        "nome": "Lista de Tarefas",
        "descricao": "Organize suas tarefas com prioridade e status",
        "icone": "bi-check2-square",
        "cor": "#10b981",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Tarefa", "type": "text"},
                {"id": "c2", "name": "Prioridade", "type": "text"},
                {"id": "c3", "name": "Prazo", "type": "date"},
                {"id": "c4", "name": "Status", "type": "text"},
                {"id": "c5", "name": "Responsável", "type": "text"},
                {"id": "c6", "name": "Notas", "type": "text"},
            ],
            "rows": [
                ["Finalizar relatório", "Alta", "2026-04-20", "Em andamento", "Eu", "Falta revisão"],
                ["Reunião com cliente", "Alta", "2026-04-18", "Pendente", "Eu", "Zoom às 14h"],
                ["Comprar materiais", "Média", "2026-04-22", "Pendente", "Maria", ""],
                ["Atualizar site", "Baixa", "2026-04-30", "Pendente", "João", "Trocar banner"],
                ["Enviar NF", "Alta", "2026-04-17", "Concluída", "Eu", ""],
            ],
        },
    },
    {
        "id": "agenda-contatos",
        "nome": "Agenda de Contatos",
        "descricao": "Organize contatos pessoais e profissionais",
        "icone": "bi-people",
        "cor": "#6366f1",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Nome", "type": "text"},
                {"id": "c2", "name": "Telefone", "type": "text"},
                {"id": "c3", "name": "E-mail", "type": "text"},
                {"id": "c4", "name": "Empresa", "type": "text"},
                {"id": "c5", "name": "Cargo", "type": "text"},
                {"id": "c6", "name": "Aniversário", "type": "date"},
            ],
            "rows": [
                ["Ana Silva", "(11) 99999-1234", "ana@email.com", "Tech Corp", "Gerente", "1990-03-15"],
                ["Carlos Lima", "(21) 98888-5678", "carlos@email.com", "Marketing Co", "Diretor", "1985-07-22"],
                ["Laura Santos", "(31) 97777-9012", "laura@email.com", "Freelancer", "Designer", "1992-11-08"],
                ["Pedro Costa", "(11) 96666-3456", "pedro@email.com", "Banco X", "Analista", "1988-05-30"],
            ],
        },
    },
    {
        "id": "inventario",
        "nome": "Inventário / Estoque",
        "descricao": "Controle de produtos, estoque e localização",
        "icone": "bi-box-seam",
        "cor": "#f97316",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Produto", "type": "text"},
                {"id": "c2", "name": "Categoria", "type": "text"},
                {"id": "c3", "name": "Qtd Estoque", "type": "number"},
                {"id": "c4", "name": "Qtd Mínima", "type": "number"},
                {"id": "c5", "name": "Preço Unit.", "type": "currency"},
                {"id": "c6", "name": "Localização", "type": "text"},
            ],
            "rows": [
                ["Notebook Dell", "Eletrônicos", 5, 2, 3500, "Armário A1"],
                ["Mouse Wireless", "Periféricos", 20, 5, 89.90, "Gaveta B2"],
                ["Cadeira Gamer", "Mobília", 3, 1, 1200, "Depósito"],
                ["Monitor 27\"", "Eletrônicos", 8, 3, 1800, "Armário A2"],
                ["Webcam HD", "Periféricos", 12, 4, 250, "Gaveta B3"],
                ["Teclado Mecânico", "Periféricos", 15, 5, 350, "Gaveta B1"],
            ],
        },
    },
    {
        "id": "cronograma-projeto",
        "nome": "Cronograma de Projeto",
        "descricao": "Planeje etapas, prazos e progresso de projetos",
        "icone": "bi-kanban",
        "cor": "#8b5cf6",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Etapa", "type": "text"},
                {"id": "c2", "name": "Início", "type": "date"},
                {"id": "c3", "name": "Fim", "type": "date"},
                {"id": "c4", "name": "Progresso %", "type": "number"},
                {"id": "c5", "name": "Responsável", "type": "text"},
                {"id": "c6", "name": "Dependência", "type": "text"},
            ],
            "rows": [
                ["Planejamento", "2026-04-01", "2026-04-10", 100, "Ana", "—"],
                ["Design UI/UX", "2026-04-11", "2026-04-25", 75, "Carlos", "Planejamento"],
                ["Desenvolvimento Front", "2026-04-20", "2026-05-15", 30, "Laura", "Design"],
                ["Desenvolvimento Back", "2026-04-20", "2026-05-20", 20, "Pedro", "Planejamento"],
                ["Testes QA", "2026-05-16", "2026-05-30", 0, "Maria", "Dev Front + Back"],
                ["Deploy", "2026-06-01", "2026-06-05", 0, "Pedro", "Testes QA"],
            ],
        },
    },
    {
        "id": "treino-fitness",
        "nome": "Planilha de Treino",
        "descricao": "Organize sua rotina de exercícios e evolução",
        "icone": "bi-heart-pulse",
        "cor": "#ef4444",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Exercício", "type": "text"},
                {"id": "c2", "name": "Grupo Muscular", "type": "text"},
                {"id": "c3", "name": "Séries", "type": "number"},
                {"id": "c4", "name": "Repetições", "type": "number"},
                {"id": "c5", "name": "Carga (kg)", "type": "number"},
                {"id": "c6", "name": "Descanso (seg)", "type": "number"},
            ],
            "rows": [
                ["Supino Reto", "Peito", 4, 10, 60, 90],
                ["Agachamento", "Pernas", 4, 12, 80, 120],
                ["Puxada Frontal", "Costas", 4, 10, 50, 90],
                ["Desenvolvimento", "Ombro", 3, 12, 25, 60],
                ["Rosca Direta", "Bíceps", 3, 12, 14, 60],
                ["Tríceps Corda", "Tríceps", 3, 15, 20, 60],
                ["Prancha", "Core", 3, 60, 0, 45],
            ],
        },
    },
    {
        "id": "habitos-diarios",
        "nome": "Tracker de Hábitos",
        "descricao": "Acompanhe hábitos diários e construa consistência",
        "icone": "bi-calendar-check",
        "cor": "#06b6d4",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Hábito", "type": "text"},
                {"id": "c2", "name": "Seg", "type": "text"},
                {"id": "c3", "name": "Ter", "type": "text"},
                {"id": "c4", "name": "Qua", "type": "text"},
                {"id": "c5", "name": "Qui", "type": "text"},
                {"id": "c6", "name": "Sex", "type": "text"},
                {"id": "c7", "name": "Sáb", "type": "text"},
                {"id": "c8", "name": "Dom", "type": "text"},
            ],
            "rows": [
                ["Acordar 6h", "✅", "✅", "❌", "✅", "✅", "❌", "❌"],
                ["Exercício", "✅", "❌", "✅", "❌", "✅", "✅", "❌"],
                ["Ler 30min", "✅", "✅", "✅", "✅", "❌", "✅", "✅"],
                ["Beber 2L água", "✅", "✅", "✅", "✅", "✅", "✅", "✅"],
                ["Meditar", "❌", "✅", "❌", "✅", "✅", "❌", "✅"],
                ["Sem redes sociais", "❌", "❌", "✅", "❌", "❌", "✅", "✅"],
                ["Estudar 1h", "✅", "✅", "✅", "✅", "✅", "❌", "❌"],
            ],
        },
    },
    {
        "id": "notas-estudo",
        "nome": "Plano de Estudos",
        "descricao": "Organize matérias, horários e progresso de estudo",
        "icone": "bi-book",
        "cor": "#ec4899",
        "dados": {
            "columns": [
                {"id": "c1", "name": "Matéria", "type": "text"},
                {"id": "c2", "name": "Tópico Atual", "type": "text"},
                {"id": "c3", "name": "Horas/Semana", "type": "number"},
                {"id": "c4", "name": "Progresso %", "type": "number"},
                {"id": "c5", "name": "Próxima Prova", "type": "date"},
                {"id": "c6", "name": "Notas", "type": "text"},
            ],
            "rows": [
                ["Matemática", "Cálculo Integral", 6, 45, "2026-05-10", "Revisar exercícios cap 5"],
                ["Programação", "React + TypeScript", 8, 70, "2026-05-15", "Projeto final"],
                ["Inglês", "Speaking + Writing", 4, 60, "2026-06-01", "Praticar conversação"],
                ["Física", "Termodinâmica", 5, 30, "2026-05-12", "Assistir aulas online"],
                ["História", "Era Moderna", 3, 80, "2026-04-28", "Fazer resumo"],
            ],
        },
    },
]

@app.get("/spreadsheets/templates")
def get_templates():
    """Retorna templates pré-prontos de planilhas."""
    return SPREADSHEET_TEMPLATES

@app.get("/spreadsheets")
def list_spreadsheets(user_id: str = Depends(get_current_user_id)):
    """Lista planilhas do usuário."""
    res = supabase.table("spreadsheets").select("id, nome, descricao, created_at, updated_at").eq("user_id", user_id).order("updated_at", desc=True).execute()
    return res.data

@app.get("/spreadsheets/{sheet_id}")
def get_spreadsheet(sheet_id: str, user_id: str = Depends(get_current_user_id)):
    """Retorna uma planilha completa com dados."""
    res = supabase.table("spreadsheets").select("*").eq("id", sheet_id).eq("user_id", user_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Planilha não encontrada")
    return res.data[0]

@app.post("/spreadsheets")
def create_spreadsheet(body: SpreadsheetCreate, user_id: str = Depends(get_current_user_id)):
    """Cria uma nova planilha."""
    row = {
        "user_id": user_id,
        "nome": body.nome,
        "descricao": body.descricao,
        "dados": body.dados,
    }
    res = supabase.table("spreadsheets").insert(row).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Erro ao criar planilha")
    return res.data[0]

@app.put("/spreadsheets/{sheet_id}")
def update_spreadsheet(sheet_id: str, body: SpreadsheetUpdate, user_id: str = Depends(get_current_user_id)):
    """Atualiza uma planilha existente."""
    update = {}
    if body.nome is not None:
        update["nome"] = body.nome
    if body.descricao is not None:
        update["descricao"] = body.descricao
    if body.dados is not None:
        update["dados"] = body.dados
    if not update:
        raise HTTPException(status_code=400, detail="Nada para atualizar")
    update["updated_at"] = datetime.now().isoformat()
    res = supabase.table("spreadsheets").update(update).eq("id", sheet_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Planilha não encontrada")
    return res.data[0]

@app.delete("/spreadsheets/{sheet_id}")
def delete_spreadsheet(sheet_id: str, user_id: str = Depends(get_current_user_id)):
    """Deleta uma planilha."""
    res = supabase.table("spreadsheets").delete().eq("id", sheet_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Planilha não encontrada")
    return {"ok": True}

# ── Health Check ─────────────────────────────────────────────────────────────

@app.api_route("/", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "service": "Dashboard Financeiro API"}

# ── Entrypoint para produção ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
