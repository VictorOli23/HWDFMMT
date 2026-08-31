import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import bcrypt
import re
import io
import os
import altair as alt
from datetime import datetime

# ==========================================
# 1. CONFIGURAÇÃO DA PÁGINA E CSS
# ==========================================
st.set_page_config(
    page_title="NOC FMT - Command Center",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ''
if 'is_admin' not in st.session_state:
    st.session_state['is_admin'] = False

# ==========================================
# 2. CONEXÃO COM O BANCO EM NUVEM E ROTINAS
# ==========================================
DB_URL = os.environ.get("DB_URL")

if not DB_URL:
    try:
        DB_URL = st.secrets["database"]["url"]
    except:
        DB_URL = "sqlite:///crc_database.db"

engine = create_engine(DB_URL)

def init_cloud_db():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usuarios_equipe (
                username VARCHAR(50) PRIMARY KEY,
                password_hash VARCHAR(255) NOT NULL,
                nome_completo VARCHAR(100),
                cargo VARCHAR(50)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS quadrantes (
                end_id VARCHAR(50) PRIMARY KEY,
                quadrante VARCHAR(50)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS crc_historico (
                tsk VARCHAR(50) PRIMARY KEY,
                ne_id VARCHAR(100),
                end_id VARCHAR(100),
                status VARCHAR(50),
                aging VARCHAR(50),
                descricao TEXT,
                data_atualizacao VARCHAR(50)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_config (
                key VARCHAR(50) PRIMARY KEY,
                value VARCHAR(50)
            )
        """))
        conn.commit()

init_cloud_db()

def run_daily_snapshot():
    today_str = datetime.now().strftime("%Y-%m-%d")
    with engine.connect() as conn:
        try:
            res = conn.execute(text("SELECT value FROM system_config WHERE key='last_date'")).fetchone()
            last_date = res[0] if res else None
        except:
            last_date = None
            
        if not last_date:
            conn.execute(text("INSERT INTO system_config (key, value) VALUES ('last_date', :d)"), {"d": today_str})
            conn.commit()
            return
        
        if last_date != today_str:
            try:
                df_fixa = pd.read_sql_table('backlog_fixa', conn)
                if not df_fixa.empty:
                    df_fixa['data_snapshot'] = last_date
                    df_fixa.to_sql('historico_diario', engine, if_exists='append', index=False)
            except:
                pass
            
            tables_to_clear = ['backlog_fixa', 'backlog_fmmt', 'backlog_movel', 'backlog_b2b', 'backlog_grafana', 'backlog_fixa_previous']
            for t in tables_to_clear:
                conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
            
            conn.execute(text("UPDATE system_config SET value=:d WHERE key='last_date'"), {"d": today_str})
            conn.commit()
            st.cache_data.clear()

run_daily_snapshot()

@st.cache_data(ttl=900, show_spinner=False)
def load_table(table_name):
    try:
        with engine.connect() as conn:
            return pd.read_sql_table(table_name, conn)
    except Exception:
        return pd.DataFrame()

def drop_table(table_name):
    try:
        with engine.connect() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            conn.commit()
        st.cache_data.clear()
        return True
    except Exception:
        return False

# ==========================================
# 3. AUTENTICAÇÃO E MOTOR DE CORES
# ==========================================
def verify_login(username, password):
    admin_user = os.environ.get("ADMIN_USER")
    admin_pass = os.environ.get("ADMIN_PASS")
    
    if not admin_user:
        try:
            admin_user = st.secrets["admin"]["username"]
            admin_pass = st.secrets["admin"]["password"]
        except:
            admin_user = "admin"
            admin_pass = "admin"
            
    if username == admin_user and password == admin_pass:
        return True, True
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT password_hash FROM usuarios_equipe WHERE username = :u"), {"u": username}).fetchone()
        if result:
            stored_hash = result[0].encode('utf-8') if isinstance(result[0], str) else result[0]
            if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
                return True, False
    return False, False

def apply_colors(df):
    """Aplica o motor de cores estritamente na coluna de tempo real (TEMPO_DO_CHAMADO e AGING)."""
    def style_aging(val):
        s = str(val).strip().lower()
        if not s or s in ['nan', 'none', '-']: return ''
        
        days = 0.0
        m1 = re.search(r'(\d+)\s*d', s)
        if m1:
            days = float(m1.group(1))
        else:
            m2 = re.search(r'(\d+([.,]\d+)?)', s)
            if m2:
                days = float(m2.group(1).replace(',', '.'))
        
        # Escala de cores do Aging baseada na regra SLA do NOC
        if days >= 10:
            return 'background-color: #8B0000; color: white; font-weight: bold;'
        elif days >= 5:
            return 'background-color: #DC2626; color: white; font-weight: bold;'
        elif days >= 4:
            return 'background-color: #F97316; color: white; font-weight: bold;'
        elif days >= 3:
            return 'background-color: #1E3A8A; color: white; font-weight: bold;'
        elif days >= 1:
            return 'background-color: #BAE6FD; color: #0369A1; font-weight: bold;'
        return ''

    try:
        styler = df.style
        for col in ['AGING', 'aging', 'TEMPO_DO_CHAMADO']:
            if col in df.columns:
                styler = styler.map(style_aging, subset=[col]) if hasattr(styler, 'map') else styler.applymap(style_aging, subset=[col])
        return styler
    except:
        return df

if not st.session_state['logged_in']:
    st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>📡 NOC FMT Login</h1>", unsafe_allow_html=True)
    st.markdown("---")
    
    col_l1, col_l2, col_l3 = st.columns([1, 1, 1])
    with col_l2:
        with st.form("login_form"):
            st.write("Insira suas credenciais corporativas")
            user_input = st.text_input("Usuário")
            pass_input = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar no Sistema", use_container_width=True)
            
            if submitted:
                if not user_input or not pass_input:
                    st.warning("Preencha todos os campos.")
                else:
                    auth_ok, is_admin = verify_login(user_input, pass_input)
                    if auth_ok:
                        st.session_state['logged_in'] = True
                        st.session_state['username'] = user_input
                        st.session_state['is_admin'] = is_admin
                        st.rerun()
                    else:
                        st.error("Usuário ou senha incorretos.")
    st.stop()

# ==========================================
# 4. FUNÇÕES DE BANCO DE DADOS E LIMPEZA
# ==========================================
def upsert_quadrantes(df_quad):
    col_end = next((c for c in df_quad.columns if "END" in str(c).upper()), df_quad.columns[0])
    col_q_val = next((c for c in df_quad.columns if any(k in str(c).upper() for k in ["QD", "QUADRANTE", "ANF"])), df_quad.columns[-1])
    novos, at = 0, 0
    with engine.connect() as conn:
        for _, row in df_quad.iterrows():
            end_val = str(row.get(col_end, "")).strip().upper()
            quad_val = str(row.get(col_q_val, "")).strip().upper()
            if not end_val or end_val == "NAN": continue
            
            exists = conn.execute(text("SELECT end_id FROM quadrantes WHERE end_id = :e"), {"e": end_val}).fetchone()
            if exists:
                conn.execute(text("UPDATE quadrantes SET quadrante = :q WHERE end_id = :e"), {"q": quad_val, "e": end_val})
                at += 1
            else:
                conn.execute(text("INSERT INTO quadrantes (end_id, quadrante) VALUES (:e, :q)"), {"e": end_val, "q": quad_val})
                novos += 1
        conn.commit()
    return novos, at

def get_quadrantes_map():
    with engine.connect() as conn:
        df = pd.read_sql_query("SELECT * FROM quadrantes", conn)
    if df.empty: return {}
    return dict(zip(df['end_id'], df['quadrante']))

def upsert_crc(df_crc):
    cols = [str(c).upper().strip() for c in df_crc.columns]
    df_crc.columns = cols
    col_tsk = next((c for c in cols if any(k in c for k in ["NUMERO", "NÚMERO", "TSK", "CHAMADO", "ORDEM"])), cols[0])
    col_ne = next((c for c in cols if "NE" in c), cols[min(1, len(cols)-1)])
    col_end = next((c for c in cols if "END" in c), cols[min(2, len(cols)-1)])
    col_status = next((c for c in cols if "STATUS" in c), cols[min(3, len(cols)-1)])
    col_aging = next((c for c in cols if "AGING" in c), None)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.connect() as conn:
        for _, row in df_crc.iterrows():
            tsk_val = str(row.get(col_tsk, "")).strip()
            if not tsk_val or tsk_val.lower() in ["nan", "none", ""]: continue
            ne_val = str(row.get(col_ne, "")); end_val = str(row.get(col_end, ""))
            st_val = str(row.get(col_status, "")); aging_val = str(row.get(col_aging, "")) if col_aging else ""
            exists = conn.execute(text("SELECT tsk FROM crc_historico WHERE tsk = :t"), {"t": tsk_val}).fetchone()
            if exists:
                conn.execute(text("""UPDATE crc_historico SET ne_id=:n, end_id=:e, status=:s, aging=:a, data_atualizacao=:d WHERE tsk=:t"""), {"n": ne_val, "e": end_val, "s": st_val, "a": aging_val, "d": now, "t": tsk_val})
            else:
                conn.execute(text("""INSERT INTO crc_historico (tsk, ne_id, end_id, status, aging, descricao, data_atualizacao) VALUES (:t, :n, :e, :s, :a, '', :d)"""), {"t": tsk_val, "n": ne_val, "e": end_val, "s": st_val, "a": aging_val, "d": now})
        conn.commit()

@st.cache_data(ttl=900, show_spinner=False)
def get_crc_data():
    with engine.connect() as conn:
        return pd.read_sql_query("SELECT * FROM crc_historico", conn)

def load_file(file, target_sheet_hints=None):
    if file is None: return pd.DataFrame()
    
    if file.name.endswith(".csv"):
        content = file.getvalue().decode('utf-8', errors='ignore')
        lines = content.splitlines()
        clean_lines = [l for l in lines if "sep=" not in l.lower()[:10]]
        clean_content = "\n".join(clean_lines)
        try:
            df = pd.read_csv(io.StringIO(clean_content), sep=',')
            if len(df.columns) <= 1:
                df = pd.read_csv(io.StringIO(clean_content), sep=';')
        except:
            try: df = pd.read_csv(io.StringIO(clean_content), sep=';', on_bad_lines='skip')
            except: df = pd.DataFrame()
        return df.drop_duplicates()
    else:
        xls = pd.ExcelFile(file)
        sheet_to_load = xls.sheet_names[0]
        if target_sheet_hints:
            for s in xls.sheet_names:
                if any(hint.upper() in s.upper() for hint in target_sheet_hints):
                    sheet_to_load = s
                    break
        df = pd.read_excel(xls, sheet_name=sheet_to_load)
        if len(df) > 0 and any(str(c).startswith("Unnamed") for c in df.columns[:3]):
            for idx in range(min(15, len(df))):
                row_vals = [str(x).upper() for x in df.iloc[idx].values]
                if any(k in "".join(row_vals) for k in ["NÚMERO", "NUMERO", "TSK", "END ID", "NE ID", "ICTTTID", "EVENTO"]):
                    df.columns = df.iloc[idx]
                    df = df.iloc[idx+1:].reset_index(drop=True)
                    break
        return df.drop_duplicates()

def get_single_series(df, col_name_hints, fallback_val=""):
    col_found = next((c for hint in col_name_hints for c in df.columns if hint in str(c).upper().strip()), None)
    if not col_found: return pd.Series([fallback_val] * len(df), index=df.index, dtype=str)
    return df[col_found].iloc[:, 0].fillna("").astype(str) if isinstance(df[col_found], pd.DataFrame) else df[col_found].fillna("").astype(str)

def extrair_colunas(df):
    return {
        "TSK": get_single_series(df, ["NÚMERO", "NUMERO", "TSK", "CHAMADO", "ORDEM"], ""),
        "EVENTO": get_single_series(df, ["EVENTO", "ICTTTID", "INCIDENTE"], ""),
        "END_ID": get_single_series(df, ["END ID", "END_ID", "SITE"], ""),
        "NE_ID": get_single_series(df, ["NE ID DESCRIÇÃO", "NE ID DO EVENTO", "NENAME", "NE ID"], ""),
        "TIPO_EQUIPAMENTO": get_single_series(df, ["TIPO DO EQUIPAMENTO", "TIPO NE", "EQUIPAMENTO"], ""),
        "STATUS": get_single_series(df, ["STATUS"], "Não Acionado"),
        "FALHA": get_single_series(df, ["ALARME", "FALHA"], ""),
        "AGING": get_single_series(df, ["AGING"], "-"),
        "DATA_CRIACAO": get_single_series(df, ["DATA DE CRIAÇÃO", "DATA_CRIACAO", "CRIA"], ""),
        "TECNICO": get_single_series(df, ["NOME DO TÉCNICO", "NOME TÉCNICO CAMPO", "TÉCNICO", "TECNICO", "RESPONSÁVEL"], ""),
        "RESUMO": get_single_series(df, ["RESUMO", "OBSERVAÇÕES"], ""),
        "OBS": get_single_series(df, ["OBS", "NOTAS"], "")
    }

def categorize_status(st_str):
    s = str(st_str).upper()
    if any(k in s for k in ["ACIONADO", "NOTIFICADO", "ENCAMINHADO"]): return "Acionado"
    elif any(k in s for k in ["INICIADO", "ANDAMENTO", "CAMPO", "ATENDIMENTO"]): return "Iniciado"
    elif any(k in s for k in ["TRAMITADO", "AGUARDANDO", "PAUSA", "TERCEIRO", "PENDENTE"]): return "Tramitado"
    elif any(k in s for k in ["ENCERRADO", "CONCLUIDO", "CANCELADO", "RESOLVIDO"]): return "Encerrado"
    return "Não Acionado"

def get_status_counts(sub_df, status_col="STATUS"):
    if sub_df.empty or status_col not in sub_df.columns:
        return {"Acionado": 0, "Iniciado": 0, "Tramitado": 0, "Encerrado": 0, "Total": 0}
    counts = sub_df[status_col].value_counts()
    return {
        "Acionado": int(counts.get("Acionado", 0)),
        "Iniciado": int(counts.get("Iniciado", 0)),
        "Tramitado": int(counts.get("Tramitado", 0)),
        "Encerrado": int(counts.get("Encerrado", 0)),
        "Total": len(sub_df)
    }

def calculate_tempo_chamado(row):
    data_cria = row.get("DATA_CRIACAO", None)
    if pd.notnull(data_cria) and str(data_cria).strip() not in ["", "nan", "None", "-"]:
        try:
            dt = pd.to_datetime(data_cria, dayfirst=True)
            diff = datetime.now() - dt
            days = diff.days; hours, remainder = divmod(diff.seconds, 3600); mins, _ = divmod(remainder, 60)
            return f"{days}d {hours:02d}h {mins:02d}m"
        except: pass
    ag_val = str(row.get("AGING", "")).strip()
    return ag_val if ag_val and ag_val not in ["nan", "None"] else "0d 00h"

# ==========================================
# 6. MENUS DA BARRA LATERAL
# ==========================================
st.sidebar.title(f"📡 NOC FMT")
st.sidebar.markdown(f"**Usuário Logado:** `{st.session_state['username']}`")
if st.sidebar.button("Sair (Logout)"):
    st.session_state['logged_in'] = False
    st.session_state['is_admin'] = False
    st.rerun()

st.sidebar.markdown("---")
abas_disponiveis = [
    "📥 Upload & Processamento",
    "📂 Backlog Operacional (Fixa)",
    "📱 Backlog Móvel",
    "🔄 Handover (Entrantes/Saintes)",
    "💼 Gestão B2B",
    "📺 Apresentação Executiva",
    "🚨 Casos Críticos",
    "📋 Base Geral FMT",
    "🗄️ Histórico CRC",
    "📅 Histórico Diário (Dias)"
]

if st.session_state['is_admin']: abas_disponiveis.insert(0, "👤 Gestão de Usuários (Admin)")
menu = st.sidebar.radio("Navegação", abas_disponiveis)

# ==========================================
# ABA: GESTÃO DE USUÁRIOS
# ==========================================
if menu == "👤 Gestão de Usuários (Admin)":
    st.title("👤 Gerenciamento de Acessos")
    
    with st.expander("➕ Cadastrar Novo Usuário", expanded=False):
        with st.form("add_user_form"):
            new_user = st.text_input("Usuário (Ex: wesley.noc)")
            new_name = st.text_input("Nome Completo")
            new_role = st.selectbox("Cargo", ["Técnico NOC", "Coordenador", "Analista", "Supervisor"])
            new_pass = st.text_input("Senha", type="password")
            if st.form_submit_button("Cadastrar Usuário"):
                hashed_pw = bcrypt.hashpw(new_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                with engine.connect() as conn:
                    try:
                        conn.execute(text("INSERT INTO usuarios_equipe (username, password_hash, nome_completo, cargo) VALUES (:u, :p, :n, :c)"), {"u": new_user, "p": hashed_pw, "n": new_name, "c": new_role})
                        conn.commit()
                        st.success("Criado!")
                    except: st.error("Usuário já existe.")

    st.markdown("### 📋 Usuários Cadastrados")
    try:
        with engine.connect() as conn:
            df_users = pd.read_sql_query("SELECT username, nome_completo, cargo FROM usuarios_equipe", conn)
            df_users.rename(columns={'username': 'Usuário', 'nome_completo': 'Nome', 'cargo': 'Cargo'}, inplace=True)
    except:
        df_users = pd.DataFrame()
        
    if not df_users.empty and "Usuário" in df_users.columns:
        st.dataframe(df_users, use_container_width=True, hide_index=True)
        
        with st.expander("🗑️ Excluir Usuário", expanded=False):
            st.warning("Cuidado: A exclusão é imediata e irreversível.")
            user_to_delete = st.selectbox("Selecione o usuário que deseja remover:", options=df_users["Usuário"].tolist())
            if st.button("🚨 Confirmar Exclusão", type="primary"):
                with engine.connect() as conn:
                    conn.execute(text("DELETE FROM usuarios_equipe WHERE username = :u"), {"u": user_to_delete})
                    conn.commit()
                st.success(f"Usuário '{user_to_delete}' excluído com sucesso!")
                st.rerun()
    else:
        st.info("Nenhum usuário cadastrado no banco de dados.")

# ==========================================
# ABA: UPLOAD & PROCESSAMENTO
# ==========================================
elif menu == "📥 Upload & Processamento":
    st.title("📥 Ingestão, Fusão e Cruzamento")
    st.caption("FUSÃO ATIVA: Retenção de edições manuais garantida. Edições não são perdidas no re-upload.")

    st.markdown("### 📊 Status Atual das Bases na Nuvem")
    df_fixa_check = load_table("backlog_fixa")
    df_fmmt_check = load_table("backlog_fmmt")
    df_movel_check = load_table("backlog_movel")
    df_b2b_check = load_table("backlog_b2b")
    df_grafana_check = load_table("backlog_grafana")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if not df_fixa_check.empty:
            st.success(f"🟢 **Fixa:** {len(df_fixa_check)} reg.")
            if st.button("🗑️ Limpar Fixa"): drop_table("backlog_fixa"); st.rerun()
        if not df_fmmt_check.empty:
            st.success(f"🟢 **FMMT:** {len(df_fmmt_check)} reg.")
            if st.button("🗑️ Limpar FMMT"): drop_table("backlog_fmmt"); st.rerun()
    with c2:
        if not df_movel_check.empty:
            st.success(f"🟢 **Móvel:** {len(df_movel_check)} reg.")
            if st.button("🗑️ Limpar Móvel"): drop_table("backlog_movel"); st.rerun()
        if not df_b2b_check.empty:
            st.success(f"🟢 **B2B:** {len(df_b2b_check)} reg.")
            if st.button("🗑️ Limpar B2B"): drop_table("backlog_b2b"); st.rerun()
    with c3:
        if not df_grafana_check.empty:
            st.success(f"🟢 **Grafana:** {len(df_grafana_check)} reg.")
            if st.button("🗑️ Limpar Grafana"): drop_table("backlog_grafana"); st.rerun()

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Bases Operacionais")
        f_fmt = st.file_uploader("1. Base Fixa FMT", type=["xlsx", "csv"])
        f_fmmt = st.file_uploader("2. Base Móvel FMMT (SMART / Anéis)", type=["xlsx", "csv"])
        f_movel_backlog = st.file_uploader("3. Base Móvel (Backlog Dedicado)", type=["xlsx", "csv"])
        f_b2b = st.file_uploader("4. Base B2B (Corporativo)", type=["xlsx", "csv"])

    with col2:
        st.subheader("Bases de Apoio & Correlação")
        f_grafana = st.file_uploader("5. Base Grafana", type=["xlsx", "csv"])
        f_quadrantes = st.file_uploader("6. Base Quadrantes", type=["xlsx", "csv"])
        f_crc = st.file_uploader("7. Base CRC (Histórico)", type=["xlsx", "csv"])

    if st.button("🚀 Processar e Enviar para a Nuvem", type="primary", use_container_width=True):
        if not f_fmt:
            st.error("A Base Total Fixa FMT é obrigatória.")
        else:
            with st.spinner("Realizando a Fusão das bases, preservando edições e cruzando Anéis..."):
                st.cache_data.clear() 
                
                df_old_fixa = load_table("backlog_fixa")
                df_old_movel = load_table("backlog_movel")
                df_old_b2b = load_table("backlog_b2b")
                
                if not df_old_fixa.empty:
                    try:
                        df_old_fixa.to_sql('backlog_fixa_previous', engine, if_exists='replace', index=False)
                    except:
                        pass
                
                df_fmt_raw = load_file(f_fmt, ["BACKLOG", "FMT", "TASK", "EVENTO"])
                
                df_fmmt_raw = pd.DataFrame()
                if f_fmmt:
                    df_fmmt_raw = load_file(f_fmmt, ["FMMT", "MOVEL", "SMART"])
                    if not df_fmmt_raw.empty: df_fmmt_raw.to_sql('backlog_fmmt', engine, if_exists='replace', index=False)

                df_graf_raw = pd.DataFrame()
                if f_grafana:
                    df_graf_raw = load_file(f_grafana, ["GRAFANA", "ANEIS", "ALARMES"])
                    if not df_graf_raw.empty: df_graf_raw.to_sql('backlog_grafana', engine, if_exists='replace', index=False)

                if f_quadrantes:
                    df_q = load_file(f_quadrantes, ["QUAD", "QD", "ANF"])
                    if not df_q.empty: upsert_quadrantes(df_q)

                if f_crc:
                    df_crc_raw = load_file(f_crc, ["CRC"])
                    if not df_crc_raw.empty: upsert_crc(df_crc_raw)

                quad_map = get_quadrantes_map()
                
                df_fmt_base = pd.DataFrame(extrair_colunas(df_fmt_raw))
                df_fmt_base["ORIGEM"] = "FMT"
                
                df_fmmt_process = df_fmmt_raw if f_fmmt else load_table("backlog_fmmt")
                if not df_fmmt_process.empty:
                    df_fmmt_base = pd.DataFrame(extrair_colunas(df_fmmt_process))
                    df_fmmt_base["ORIGEM"] = "FMMT (Fusão)"
                    df_fmt = pd.concat([df_fmt_base, df_fmmt_base], ignore_index=True)
                else:
                    df_fmt = df_fmt_base

                s_dwdm = df_fmt["TIPO_EQUIPAMENTO"].apply(lambda val: "SIM" if "DWDM" in str(val).upper().strip() else "NÃO")
                df_fmt["DWDM"] = s_dwdm
                df_fmt["STATUS"] = df_fmt["STATUS"].apply(categorize_status)
                df_fmt["RESUMO"] = df_fmt["RESUMO"].apply(lambda r: "Em Campo" if "CAMPO" in str(r).upper() else ("Tramitado" if "TRAMITADO" in str(r).upper() else ("Encerrado" if "ENCERRADO" in str(r).upper() else str(r))))
                
                df_fmt = df_fmt[df_fmt["TSK"].astype(str).str.strip() != ""]
                df_fmt = df_fmt.drop_duplicates(subset=["TSK"], keep='first')

                df_fmt["QUADRANTE"] = df_fmt["END_ID"].astype(str).str.strip().str.upper().map(quad_map)
                df_fmt["QUADRANTE"] = df_fmt["QUADRANTE"].fillna(df_fmt["END_ID"].astype(str).apply(lambda x: re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE).group(0).upper() if re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE) else "NÃO INFORMADO"))
                df_fmt["TEMPO_DO_CHAMADO"] = df_fmt.apply(calculate_tempo_chamado, axis=1)

                if not df_old_fixa.empty:
                    dict_st = dict(zip(df_old_fixa["TSK"], df_old_fixa["STATUS"]))
                    dict_res = dict(zip(df_old_fixa["TSK"], df_old_fixa["RESUMO"]))
                    dict_tec = dict(zip(df_old_fixa["TSK"], df_old_fixa["TECNICO"]))
                    dict_obs = dict(zip(df_old_fixa["TSK"], df_old_fixa["OBS"]))
                    df_fmt["STATUS"] = df_fmt.apply(lambda r: dict_st.get(r["TSK"], r["STATUS"]), axis=1)
                    df_fmt["RESUMO"] = df_fmt.apply(lambda r: dict_res.get(r["TSK"], r["RESUMO"]), axis=1)
                    df_fmt["TECNICO"] = df_fmt.apply(lambda r: dict_tec.get(r["TSK"], r["TECNICO"]), axis=1)
                    df_fmt["OBS"] = df_fmt.apply(lambda r: dict_obs.get(r["TSK"], r["OBS"]), axis=1)

                global_names = set()
                global_events = set()
                
                df_graf_process = df_graf_raw if f_grafana else load_table("backlog_grafana")
                if not df_graf_process.empty:
                    cols = [str(c).upper().strip() for c in df_graf_process.columns]
                    col_graf_ne = next((c for c in cols if any(k in c for k in ["NENAME", "NE ID", "ELEMENTO"])), None)
                    col_graf_eve = next((c for c in cols if any(k in c for k in ["ICTTTID", "EVENTO", "INCIDENTE"])), None)
                    if col_graf_ne: global_names.update(df_graf_process.iloc[:, cols.index(col_graf_ne)].dropna().astype(str).str.strip().str.upper())
                    if col_graf_eve: global_events.update(df_graf_process.iloc[:, cols.index(col_graf_eve)].dropna().astype(str).str.strip().str.upper())

                lixos = ["", "NAN", "NONE", "NULL", "-", "ROUTER", "SWITCH", "SIM", "NÃO", "SEM TSK"]
                for lx in lixos: 
                    global_names.discard(lx)
                    global_events.discard(lx)

                def check_anel_omni_search(row):
                    if not global_names and not global_events: return "NÃO"
                    ne_fmt = str(row.get("NE_ID", "")).strip().upper()
                    ev_fmt = str(row.get("EVENTO", "")).strip().upper()
                    if len(ev_fmt) >= 5 and ev_fmt in global_events: return "SIM"
                    if len(ne_fmt) >= 5 and ne_fmt in global_names: return "SIM"
                    return "NÃO"

                df_fmt["ANEL_ABERTO"] = df_fmt.apply(check_anel_omni_search, axis=1)

                df_crc_db = get_crc_data()
                crc_tsks = set(df_crc_db["tsk"].dropna().astype(str).str.strip().str.upper()) if not df_crc_db.empty else set()
                df_fmt["IS_CRC"] = df_fmt["TSK"].astype(str).str.strip().str.upper().apply(lambda x: "SIM" if x in crc_tsks else "NÃO")

                df_fmt["IS_B2B"] = "NÃO" 
                if f_b2b:
                    df_b2b_raw = load_file(f_b2b, ["B2B", "CORPORATIVO"])
                    s_b2b_tsk = get_single_series(df_b2b_raw, ["NÚMERO", "NUMERO", "TSK", "CHAMADO", "ORDEM"], "")
                    s_b2b_end = get_single_series(df_b2b_raw, ["END ID", "END_ID", "SITE"], "")
                    s_b2b_ne = get_single_series(df_b2b_raw, ["NE ID DO EVENTO", "NE ID", "NENAME"], "")
                    s_b2b_status = get_single_series(df_b2b_raw, ["STATUS"], "Não Acionado")
                    s_b2b_falha = get_single_series(df_b2b_raw, ["ALARME", "FALHA"], "")
                    s_b2b_aging = get_single_series(df_b2b_raw, ["AGING"], "-")
                    s_b2b_cria = get_single_series(df_b2b_raw, ["DATA DE CRIAÇÃO", "DATA_CRIACAO", "CRIA"], "")
                    s_b2b_tec = get_single_series(df_b2b_raw, ["NOME DO TÉCNICO", "NOME TÉCNICO CAMPO", "TÉCNICO", "TECNICO"], "")
                    s_b2b_res = get_single_series(df_b2b_raw, ["RESUMO", "OBSERVAÇÕES"], "")
                    s_b2b_obs = get_single_series(df_b2b_raw, ["OBS", "NOTAS"], "")
                    s_b2b_grupo = get_single_series(df_b2b_raw, ["GRUPO ACIONADO", "GRUPO_ACIONADO", "GRUPO"], "NÃO INFORMADO")
                    
                    df_b2b_proc = pd.DataFrame({
                        "TSK": s_b2b_tsk, "END_ID": s_b2b_end, "NE_ID": s_b2b_ne, "FALHA": s_b2b_falha, "AGING": s_b2b_aging, "DATA_CRIACAO": s_b2b_cria,
                        "STATUS": s_b2b_status.apply(categorize_status), "RESUMO": s_b2b_res.apply(lambda r: "Em Campo" if "CAMPO" in str(r).upper() else ("Tramitado" if "TRAMITADO" in str(r).upper() else ("Encerrado" if "ENCERRADO" in str(r).upper() else str(r)))),
                        "TECNICO": s_b2b_tec, "OBS": s_b2b_obs, "GRUPO_ACIONADO": s_b2b_grupo
                    })
                    df_b2b_proc = df_b2b_proc.drop_duplicates(subset=["TSK"], keep='first')
                    df_b2b_proc["QUADRANTE"] = df_b2b_proc["END_ID"].astype(str).str.strip().str.upper().map(quad_map)
                    df_b2b_proc["QUADRANTE"] = df_b2b_proc["QUADRANTE"].fillna(df_b2b_proc["END_ID"].astype(str).apply(lambda x: re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE).group(0).upper() if re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE) else "NÃO INFORMADO"))
                    df_b2b_proc["TEMPO_DO_CHAMADO"] = df_b2b_proc.apply(calculate_tempo_chamado, axis=1)

                    if not df_old_b2b.empty:
                        d_st = dict(zip(df_old_b2b["TSK"], df_old_b2b["STATUS"]))
                        d_rs = dict(zip(df_old_b2b["TSK"], df_old_b2b["RESUMO"]))
                        d_tc = dict(zip(df_old_b2b["TSK"], df_old_b2b["TECNICO"]))
                        d_ob = dict(zip(df_old_b2b["TSK"], df_old_b2b["OBS"]))
                        df_b2b_proc["STATUS"] = df_b2b_proc.apply(lambda r: d_st.get(r["TSK"], r["STATUS"]), axis=1)
                        df_b2b_proc["RESUMO"] = df_b2b_proc.apply(lambda r: d_rs.get(r["TSK"], r["RESUMO"]), axis=1)
                        df_b2b_proc["TECNICO"] = df_b2b_proc.apply(lambda r: d_tc.get(r["TSK"], r["TECNICO"]), axis=1)
                        df_b2b_proc["OBS"] = df_b2b_proc.apply(lambda r: d_ob.get(r["TSK"], r["OBS"]), axis=1)

                    df_b2b_proc.to_sql('backlog_b2b', engine, if_exists='replace', index=False)

                    b2b_tokens = set(df_b2b_proc["TSK"].dropna().astype(str).str.strip().str.upper()).union(set(df_b2b_proc["NE_ID"].dropna().astype(str).str.strip().str.upper()))
                    df_fmt["IS_B2B"] = df_fmt.apply(lambda r: "SIM" if str(r["TSK"]).upper() in b2b_tokens or str(r["NE_ID"]).upper() in b2b_tokens else "NÃO", axis=1)
                else:
                    df_b2b_cloud = load_table("backlog_b2b")
                    if not df_b2b_cloud.empty:
                        b2b_tokens = set(df_b2b_cloud["TSK"].dropna().astype(str).str.strip().str.upper()).union(set(df_b2b_cloud["NE_ID"].dropna().astype(str).str.strip().str.upper()))
                        df_fmt["IS_B2B"] = df_fmt.apply(lambda r: "SIM" if str(r["TSK"]).upper() in b2b_tokens or str(r["NE_ID"]).upper() in b2b_tokens else "NÃO", axis=1)

                df_fmt.to_sql('backlog_fixa', engine, if_exists='replace', index=False)
                aneis_count = (df_fmt["ANEL_ABERTO"] == "SIM").sum()
                
                st.success(f"✅ Fusão e Retenção Concluídas! Suas edições foram salvas e mescladas.\nAnéis Abertos encontrados: {aneis_count}")

                if f_movel_backlog:
                    df_movel_raw = load_file(f_movel_backlog, ["MOVEL", "MOBILE", "BACKLOG"])
                    s_tsk_m = get_single_series(df_movel_raw, ["NÚMERO", "NUMERO", "TSK", "CHAMADO", "ORDEM"], "")
                    s_end_m = get_single_series(df_movel_raw, ["END ID", "END_ID", "SITE"], "")
                    s_ne_m = get_single_series(df_movel_raw, ["NE ID DO EVENTO", "NE ID", "NENAME"], "")
                    s_status_m = get_single_series(df_movel_raw, ["STATUS"], "Não Acionado")
                    s_falha_m = get_single_series(df_movel_raw, ["ALARME", "FALHA"], "")
                    s_aging_m = get_single_series(df_movel_raw, ["AGING"], "-")
                    s_cria_m = get_single_series(df_movel_raw, ["DATA DE CRIAÇÃO", "DATA_CRIACAO", "CRIA"], "")
                    s_tec_m = get_single_series(df_movel_raw, ["NOME DO TÉCNICO", "NOME TÉCNICO CAMPO", "TÉCNICO", "TECNICO", "RESPONSÁVEL"], "")
                    s_resumo_m = get_single_series(df_movel_raw, ["RESUMO", "OBSERVAÇÕES"], "")
                    s_obs_m = get_single_series(df_movel_raw, ["OBS", "NOTAS"], "")

                    df_movel = pd.DataFrame({
                        "TSK": s_tsk_m, "END_ID": s_end_m, "NE_ID": s_ne_m, "FALHA": s_falha_m, "AGING": s_aging_m, "DATA_CRIACAO": s_cria_m,
                        "STATUS": s_status_m.apply(categorize_status), "RESUMO": s_resumo_m.apply(lambda r: "Em Campo" if "CAMPO" in str(r).upper() else ("Tramitado" if "TRAMITADO" in str(r).upper() else ("Encerrado" if "ENCERRADO" in str(r).upper() else str(r)))),
                        "TECNICO": s_tec_m, "OBS": s_obs_m
                    })
                    df_movel = df_movel.drop_duplicates(subset=["TSK"], keep='first')
                    df_movel["QUADRANTE"] = df_movel["END_ID"].astype(str).str.strip().str.upper().map(quad_map)
                    df_movel["QUADRANTE"] = df_movel["QUADRANTE"].fillna(df_movel["END_ID"].astype(str).apply(lambda x: re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE).group(0).upper() if re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE) else "NÃO INFORMADO"))
                    df_movel["TEMPO_DO_CHAMADO"] = df_movel.apply(calculate_tempo_chamado, axis=1)

                    if not df_old_movel.empty:
                        d_st_m = dict(zip(df_old_movel["TSK"], df_old_movel["STATUS"]))
                        d_rs_m = dict(zip(df_old_movel["TSK"], df_old_movel["RESUMO"]))
                        d_tc_m = dict(zip(df_old_movel["TSK"], df_old_movel["TECNICO"]))
                        d_ob_m = dict(zip(df_old_movel["TSK"], df_old_movel["OBS"]))
                        df_movel["STATUS"] = df_movel.apply(lambda r: d_st_m.get(r["TSK"], r["STATUS"]), axis=1)
                        df_movel["RESUMO"] = df_movel.apply(lambda r: d_rs_m.get(r["TSK"], r["RESUMO"]), axis=1)
                        df_movel["TECNICO"] = df_movel.apply(lambda r: d_tc_m.get(r["TSK"], r["TECNICO"]), axis=1)
                        df_movel["OBS"] = df_movel.apply(lambda r: d_ob_m.get(r["TSK"], r["OBS"]), axis=1)

                    df_movel.to_sql('backlog_movel', engine, if_exists='replace', index=False)

                st.cache_data.clear() 
                st.rerun()

# ==========================================
# ABA 4: BACKLOG OPERACIONAL (FIXA)
# ==========================================
elif menu == "📂 Backlog Operacional (Fixa)":
    st.title("📂 Backlog Operacional (Rede Fixa)")
    
    col_sync, _ = st.columns([1, 5])
    if col_sync.button("🔄 Atualizar Base da Nuvem"): 
        st.cache_data.clear()
        st.rerun()

    df = load_table("backlog_fixa")

    if df.empty:
        st.warning("Nenhuma base Fixa encontrada na nuvem. Faça o upload na primeira aba.")
    else:
        for c in ["DWDM", "ANEL_ABERTO", "IS_B2B", "IS_CRC", "QUADRANTE"]:
            if c not in df.columns: df[c] = "NÃO"
        if "ORIGEM" not in df.columns: df["ORIGEM"] = "FMT"

        cols_backlog = ["TSK", "EVENTO", "END_ID", "NE_ID", "TEMPO_DO_CHAMADO", "AGING", "FALHA", "STATUS", "OBS", "RESUMO", "TECNICO", "DWDM", "ANEL_ABERTO", "IS_CRC", "QUADRANTE", "ORIGEM"]
        for c in cols_backlog:
            if c not in df.columns: df[c] = ""

        df_bk_view = df.loc[:, ~df.columns.duplicated()].copy()

        r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
        with r1_c1:
            sel_cat = st.selectbox("Categoria (Fila/Sainte):", ["Todas", "Fila (Pendentes)", "Saintes (Concluídos)"], key="bk_cat")
        with r1_c2:
            st_opts = ["Todos"] + sorted(list(df_bk_view["STATUS"].dropna().unique()))
            sel_st = st.selectbox("Status Específico:", options=st_opts, key="bk_status")
        with r1_c3:
            origem_opts = ["Todas", "FMT", "FMMT (Fusão)"]
            sel_origem = st.selectbox("Origem (Base):", options=origem_opts, key="bk_origem")
        with r1_c4:
            busca_bk = st.text_input("🔍 Busca rápida:", key="bk_busca")

        r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)
        with r2_c1:
            sel_anel = st.selectbox("Anel Aberto:", options=["Todos", "SIM", "NÃO"], key="bk_anel")
        with r2_c2:
            sel_dwdm = st.selectbox("DWDM:", options=["Todos", "SIM", "NÃO"], key="bk_dwdm")
        with r2_c3:
            quad_opts = ["Todos"] + sorted([str(x) for x in df_bk_view["QUADRANTE"].dropna().unique()])
            sel_quad = st.selectbox("Quadrante:", options=quad_opts, key="bk_quad")

        if sel_cat == "Fila (Pendentes)":
            df_bk_view = df_bk_view[df_bk_view["STATUS"].isin(["Não Acionado", "Acionado", "Iniciado"])]
        elif sel_cat == "Saintes (Concluídos)":
            df_bk_view = df_bk_view[df_bk_view["STATUS"].isin(["Tramitado", "Encerrado"])]

        if sel_st != "Todos": df_bk_view = df_bk_view[df_bk_view["STATUS"] == sel_st]
        if sel_origem != "Todas": df_bk_view = df_bk_view[df_bk_view["ORIGEM"] == sel_origem]
        if sel_anel != "Todos": df_bk_view = df_bk_view[df_bk_view["ANEL_ABERTO"] == sel_anel]
        if sel_dwdm != "Todos": df_bk_view = df_bk_view[df_bk_view["DWDM"] == sel_dwdm]
        if sel_quad != "Todos": df_bk_view = df_bk_view[df_bk_view["QUADRANTE"] == sel_quad]
        if busca_bk: df_bk_view = df_bk_view[df_bk_view.astype(str).apply(lambda row: row.str.contains(busca_bk, case=False).any(), axis=1)]

        column_config = {
            "TSK": st.column_config.TextColumn("TSK", disabled=True),
            "EVENTO": st.column_config.TextColumn("Evento", disabled=True),
            "END_ID": st.column_config.TextColumn("END ID", disabled=True),
            "NE_ID": st.column_config.TextColumn("NE ID", disabled=True),
            "TEMPO_DO_CHAMADO": st.column_config.TextColumn("DOWNTIME", disabled=True),
            "AGING": st.column_config.TextColumn("AGING", disabled=True),
            "FALHA": st.column_config.TextColumn("FALHA", disabled=True),
            "STATUS": st.column_config.SelectboxColumn("Status", options=["Iniciado", "Acionado", "Encerrado", "Tramitado", "Não Acionado"], required=True),
            "OBS": st.column_config.TextColumn("Obs.:", width="large"),
            "RESUMO": st.column_config.SelectboxColumn("RESUMO", options=["Em Campo", "Tramitado", "Encerrado", "Em Análise", "Acionado", "Outros"]),
            "TECNICO": st.column_config.TextColumn("TÉCNICO"),
            "DWDM": st.column_config.TextColumn("TIPO NE", disabled=True),
            "ANEL_ABERTO": st.column_config.TextColumn("ANEL", disabled=True),
            "IS_CRC": st.column_config.TextColumn("CRC", disabled=True),
            "QUADRANTE": st.column_config.TextColumn("QDRs", disabled=True),
            "ORIGEM": st.column_config.TextColumn("Origem", disabled=True),
        }

        edited_bk = st.data_editor(apply_colors(df_bk_view[cols_backlog]), column_config=column_config, use_container_width=True, height=560, key="backlog_editor_unique")

        col_b1, col_b2 = st.columns([1, 4])
        with col_b1:
            if st.button("💾 Salvar Alterações na Nuvem", type="primary", use_container_width=True):
                with engine.connect() as conn:
                    for idx, row in edited_bk.iterrows():
                        old_row = df_bk_view.loc[idx]
                        if (row["STATUS"] != old_row["STATUS"] or 
                            row["RESUMO"] != old_row["RESUMO"] or 
                            row["TECNICO"] != old_row["TECNICO"] or 
                            row["OBS"] != old_row["OBS"]):
                            
                            conn.execute(text("""
                                UPDATE backlog_fixa 
                                SET "STATUS" = :st, "RESUMO" = :res, "TECNICO" = :tec, "OBS" = :obs 
                                WHERE "TSK" = :tsk
                            """), {"st": row["STATUS"], "res": row["RESUMO"], "tec": row["TECNICO"], "obs": row["OBS"], "tsk": row["TSK"]})
                    conn.commit()
                st.cache_data.clear()
                st.success(f"✅ Atualização enviada para a Nuvem por {st.session_state['username']}!")
                st.rerun()

        with col_b2:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_bk_view[cols_backlog].to_excel(writer, index=False, sheet_name="Backlog_Fixa")
            st.download_button("📥 Baixar Backlog Fixa em Excel (.xlsx)", data=output.getvalue(), file_name=f"Backlog_Fixa_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================
# ABA 5: BACKLOG MÓVEL
# ==========================================
elif menu == "📱 Backlog Móvel":
    st.title("📱 Backlog Móvel")
    
    col_sync, _ = st.columns([1, 5])
    if col_sync.button("🔄 Atualizar Base da Nuvem"): 
        st.cache_data.clear()
        st.rerun()

    df_movel = load_table("backlog_movel")

    if df_movel.empty:
        st.warning("Nenhuma base Móvel encontrada na Nuvem. Faça o upload na primeira aba (Opção 3).")
    else:
        if "QUADRANTE" not in df_movel.columns: df_movel["QUADRANTE"] = "NÃO INFORMADO"
        
        stats_movel = get_status_counts(df_movel, status_col="STATUS")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Móvel", stats_movel["Total"])
        m2.metric("Acionados", stats_movel["Acionado"])
        m3.metric("Iniciados / Campo", stats_movel["Iniciado"])
        m4.metric("Tramitados", stats_movel["Tramitado"])
        m5.metric("Encerrados", stats_movel["Encerrado"])

        st.divider()

        cols_movel = ["TSK", "END_ID", "QUADRANTE", "NE_ID", "TEMPO_DO_CHAMADO", "AGING", "FALHA", "STATUS", "OBS", "RESUMO", "TECNICO"]
        for c in cols_movel:
            if c not in df_movel.columns: df_movel[c] = ""

        df_movel_view = df_movel.loc[:, ~df_movel.columns.duplicated()].copy()

        c_m1, c_m2, c_m3, c_m4 = st.columns(4)
        with c_m1:
            sel_cat_m = st.selectbox("Categoria (Fila/Sainte):", ["Todas", "Fila (Pendentes)", "Saintes (Concluídos)"], key="mv_cat")
        with c_m2:
            st_movel_opts = ["Todos"] + sorted(list(df_movel_view["STATUS"].dropna().unique()))
            sel_movel_st = st.selectbox("Status Específico:", options=st_movel_opts, key="mv_st")
        with c_m3:
            quad_opts_m = ["Todos"] + sorted([str(x) for x in df_movel_view["QUADRANTE"].dropna().unique()])
            sel_movel_quad = st.selectbox("Filtrar Quadrante:", options=quad_opts_m, key="mv_quad")
        with c_m4:
            busca_movel = st.text_input("🔍 Busca Móvel:", key="mv_busca")

        if sel_cat_m == "Fila (Pendentes)":
            df_movel_view = df_movel_view[df_movel_view["STATUS"].isin(["Não Acionado", "Acionado", "Iniciado"])]
        elif sel_cat_m == "Saintes (Concluídos)":
            df_movel_view = df_movel_view[df_movel_view["STATUS"].isin(["Tramitado", "Encerrado"])]

        if sel_movel_st != "Todos": df_movel_view = df_movel_view[df_movel_view["STATUS"] == sel_movel_st]
        if sel_movel_quad != "Todos": df_movel_view = df_movel_view[df_movel_view["QUADRANTE"] == sel_movel_quad]
        if busca_movel: df_movel_view = df_movel_view[df_movel_view.astype(str).apply(lambda row: row.str.contains(busca_movel, case=False).any(), axis=1)]

        column_config_movel = {
            "TSK": st.column_config.TextColumn("TSK / Número", disabled=True),
            "END_ID": st.column_config.TextColumn("END ID", disabled=True),
            "QUADRANTE": st.column_config.TextColumn("QDRs", disabled=True),
            "NE_ID": st.column_config.TextColumn("NE ID", disabled=True),
            "TEMPO_DO_CHAMADO": st.column_config.TextColumn("Tempo Chamado", disabled=True),
            "AGING": st.column_config.TextColumn("Aging", disabled=True),
            "FALHA": st.column_config.TextColumn("Falha", disabled=True),
            "STATUS": st.column_config.SelectboxColumn("Status", options=["Iniciado", "Acionado", "Encerrado", "Tramitado", "Não Acionado"], required=True),
            "RESUMO": st.column_config.SelectboxColumn("Resumo", options=["Em Campo", "Tramitado", "Encerrado", "Em Análise", "Acionado", "Outros"]),
            "TECNICO": st.column_config.TextColumn("Técnico Responsável"),
            "OBS": st.column_config.TextColumn("Observações / Trâmites", width="large"),
        }

        edited_movel = st.data_editor(apply_colors(df_movel_view[cols_movel]), column_config=column_config_movel, use_container_width=True, height=500, key="movel_editor_unique")

        col_save_m1, col_save_m2 = st.columns([1, 4])
        with col_save_m1:
            if st.button("💾 Salvar Alterações na Nuvem", type="primary", use_container_width=True):
                with engine.connect() as conn:
                    for idx, row in edited_movel.iterrows():
                        old_row = df_movel_view.loc[idx]
                        if (row["STATUS"] != old_row["STATUS"] or 
                            row["RESUMO"] != old_row["RESUMO"] or 
                            row["TECNICO"] != old_row["TECNICO"] or 
                            row["OBS"] != old_row["OBS"]):
                            
                            conn.execute(text("""
                                UPDATE backlog_movel 
                                SET "STATUS" = :st, "RESUMO" = :res, "TECNICO" = :tec, "OBS" = :obs 
                                WHERE "TSK" = :tsk
                            """), {"st": row["STATUS"], "res": row["RESUMO"], "tec": row["TECNICO"], "obs": row["OBS"], "tsk": row["TSK"]})
                    conn.commit()
                st.cache_data.clear()
                st.success(f"✅ Atualização enviada para a Nuvem por {st.session_state['username']}!")
                st.rerun()

        with col_save_m2:
            output_movel = io.BytesIO()
            with pd.ExcelWriter(output_movel, engine="openpyxl") as writer:
                df_movel_view[cols_movel].to_excel(writer, index=False, sheet_name="Backlog_Movel")
            st.download_button("📥 Baixar Backlog Móvel em Excel (.xlsx)", data=output_movel.getvalue(), file_name=f"Backlog_Movel_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================
# ABA 6: HANDOVER (SAINTES E ENTRANTES)
# ==========================================
elif menu == "🔄 Handover (Entrantes/Saintes)":
    st.title("🔄 Handover Operacional")
    st.caption("Acompanhe o que entrou de novo e o que saiu do seu backlog da Fixa desde a última atualização da base.")

    df_new = load_table("backlog_fixa")
    df_old = load_table("backlog_fixa_previous")

    if df_new.empty or df_old.empty:
        st.info("⚠️ O sistema precisa de pelo menos dois uploads de planilha para comparar o antes e o depois.")
    else:
        tsks_old = set(df_old["TSK"].dropna().astype(str).str.strip())
        tsks_new = set(df_new["TSK"].dropna().astype(str).str.strip())

        entrantes_tsks = tsks_new - tsks_old
        saintes_tsks = tsks_old - tsks_new

        df_entrantes = df_new[df_new["TSK"].isin(entrantes_tsks)]
        df_saintes = df_old[df_old["TSK"].isin(saintes_tsks)]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Base Anterior", len(df_old))
        c2.metric("Total Base Atual", len(df_new))
        c3.metric("🟢 Entrantes (Novos)", len(entrantes_tsks))
        c4.metric("🔴 Saintes (Saíram)", len(saintes_tsks))

        st.divider()

        col_btn1, col_btn2 = st.columns([1, 2])
        with col_btn1:
            output_ho = io.BytesIO()
            with pd.ExcelWriter(output_ho, engine="openpyxl") as writer:
                if not df_entrantes.empty:
                    df_entrantes.to_excel(writer, index=False, sheet_name="Entrantes (Novos)")
                else:
                    pd.DataFrame({"Mensagem": ["Nenhum chamado entrante nesta atualização."]}).to_excel(writer, index=False, sheet_name="Entrantes (Novos)")
                
                if not df_saintes.empty:
                    df_saintes.to_excel(writer, index=False, sheet_name="Saintes (Saíram)")
                else:
                    pd.DataFrame({"Mensagem": ["Nenhum chamado sainte nesta atualização."]}).to_excel(writer, index=False, sheet_name="Saintes (Saíram)")

            st.download_button(
                label="📥 Baixar Relatório de Handover (.xlsx)", 
                data=output_ho.getvalue(), 
                file_name=f"Handover_Operacional_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )

        st.write("")
        t1, t2 = st.tabs(["🟢 Ver Entrantes", "🔴 Ver Saintes"])

        with t1:
            st.subheader(f"🟢 Chamados Entrantes ({len(df_entrantes)})")
            if not df_entrantes.empty:
                cols_show = ["TSK", "END_ID", "NE_ID", "QUADRANTE", "FALHA", "AGING", "STATUS"]
                cols_show = [c for c in cols_show if c in df_entrantes.columns]
                st.dataframe(apply_colors(df_entrantes[cols_show]), use_container_width=True)
            else:
                st.success("Nenhum chamado novo entrou na base desde a última atualização.")

        with t2:
            st.subheader(f"🔴 Chamados Saintes ({len(df_saintes)})")
            if not df_saintes.empty:
                cols_show = ["TSK", "END_ID", "NE_ID", "QUADRANTE", "FALHA", "STATUS", "TECNICO", "OBS"]
                cols_show = [c for c in cols_show if c in df_saintes.columns]
                st.dataframe(apply_colors(df_saintes[cols_show]), use_container_width=True)
            else:
                st.info("Nenhum chamado saiu da base desde a última atualização.")

# ==========================================
# ABA 7: GESTÃO B2B
# ==========================================
elif menu == "💼 Gestão B2B":
    st.title("💼 Gestão B2B (Corporativo)")
    
    col_sync, _ = st.columns([1, 5])
    if col_sync.button("🔄 Atualizar Base da Nuvem"): 
        st.cache_data.clear()
        st.rerun()
        
    df_b2b = load_table("backlog_b2b")

    if df_b2b.empty:
        st.warning("Nenhuma base B2B carregada na nuvem. Envie o arquivo B2B na primeira aba.")
    else:
        if "QUADRANTE" not in df_b2b.columns: df_b2b["QUADRANTE"] = "NÃO INFORMADO"
        if "GRUPO_ACIONADO" not in df_b2b.columns: df_b2b["GRUPO_ACIONADO"] = "NÃO INFORMADO"

        stats_b2b = get_status_counts(df_b2b, status_col="STATUS")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total B2B", stats_b2b["Total"])
        m2.metric("Acionados", stats_b2b["Acionado"])
        m3.metric("Iniciados / Campo", stats_b2b["Iniciado"])
        m4.metric("Tramitados", stats_b2b["Tramitado"])
        m5.metric("Encerrados", stats_b2b["Encerrado"])

        st.divider()

        cols_b2b = ["TSK", "TEMPO_DO_CHAMADO", "QUADRANTE", "GRUPO_ACIONADO", "NE_ID", "END_ID", "FALHA", "STATUS", "RESUMO", "TECNICO", "OBS", "AGING"]
        for c in cols_b2b:
            if c not in df_b2b.columns: df_b2b[c] = ""

        df_b2b_view = df_b2b.loc[:, ~df_b2b.columns.duplicated()].copy()

        c_b1, c_b2, c_b3, c_b4 = st.columns(4)
        with c_b1:
            sel_cat_b = st.selectbox("Categoria (Fila/Sainte):", ["Todas", "Fila (Pendentes)", "Saintes (Concluídos)"], key="b2b_cat")
        with c_b2:
            st_b2b_opts = ["Todos"] + sorted(list(df_b2b_view["STATUS"].dropna().unique()))
            sel_b2b_st = st.selectbox("Status Específico:", options=st_b2b_opts, key="b2b_st")
        with c_b3:
            quad_opts_b = ["Todos"] + sorted([str(x) for x in df_b2b_view["QUADRANTE"].dropna().unique()])
            sel_b2b_quad = st.selectbox("Filtrar Quadrante:", options=quad_opts_b, key="b2b_quad")
        with c_b4:
            sel_b2b_rede = st.selectbox("Rede:", options=["Todas", "Fixa", "Móvel"], key="b2b_rede")

        c_b5, c_b6 = st.columns([1, 3])
        with c_b5:
            grupo_opts = ["Todos"] + sorted(list(df_b2b_view["GRUPO_ACIONADO"].dropna().unique()))
            sel_b2b_grupo = st.selectbox("Grupo Acionado:", options=grupo_opts, key="b2b_grupo")
        with c_b6:
            busca_b2b = st.text_input("🔍 Busca B2B (Número / TSK, NE ID, Falha, Técnico):", key="b2b_busca")

        if sel_cat_b == "Fila (Pendentes)":
            df_b2b_view = df_b2b_view[df_b2b_view["STATUS"].isin(["Não Acionado", "Acionado", "Iniciado"])]
        elif sel_cat_b == "Saintes (Concluídos)":
            df_b2b_view = df_b2b_view[df_b2b_view["STATUS"].isin(["Tramitado", "Encerrado"])]

        if sel_b2b_st != "Todos": df_b2b_view = df_b2b_view[df_b2b_view["STATUS"] == sel_b2b_st]
        if sel_b2b_quad != "Todos": df_b2b_view = df_b2b_view[df_b2b_view["QUADRANTE"] == sel_b2b_quad]
        if sel_b2b_grupo != "Todos": df_b2b_view = df_b2b_view[df_b2b_view["GRUPO_ACIONADO"] == sel_b2b_grupo]
        
        def is_fixa(val):
            v = str(val).strip().upper()
            return v in ["", "NAN", "NONE", "NULL", "-"]

        if sel_b2b_rede == "Fixa":
            df_b2b_view = df_b2b_view[df_b2b_view["NE_ID"].apply(is_fixa)]
        elif sel_b2b_rede == "Móvel":
            df_b2b_view = df_b2b_view[~df_b2b_view["NE_ID"].apply(is_fixa)]
            
        if busca_b2b: df_b2b_view = df_b2b_view[df_b2b_view.astype(str).apply(lambda row: row.str.contains(busca_b2b, case=False).any(), axis=1)]

        column_config_b2b = {
            "TSK": st.column_config.TextColumn("Número / TSK", disabled=True),
            "TEMPO_DO_CHAMADO": st.column_config.TextColumn("Tempo Chamado", disabled=True),
            "QUADRANTE": st.column_config.TextColumn("QDRs", disabled=True),
            "GRUPO_ACIONADO": st.column_config.TextColumn("Grupo Acionado", disabled=True),
            "NE_ID": st.column_config.TextColumn("NE ID", disabled=True),
            "END_ID": st.column_config.TextColumn("END ID", disabled=True),
            "FALHA": st.column_config.TextColumn("Falha", disabled=True),
            "STATUS": st.column_config.SelectboxColumn("Status", options=["Iniciado", "Acionado", "Encerrado", "Tramitado", "Não Acionado"], required=True),
            "RESUMO": st.column_config.SelectboxColumn("Resumo", options=["Em Campo", "Tramitado", "Encerrado", "Em Análise", "Acionado", "Outros"]),
            "TECNICO": st.column_config.TextColumn("Técnico Responsável"),
            "OBS": st.column_config.TextColumn("Observações / Trâmites", width="large"),
            "AGING": st.column_config.TextColumn("Aging", disabled=True),
        }

        edited_b2b = st.data_editor(apply_colors(df_b2b_view[cols_b2b]), column_config=column_config_b2b, use_container_width=True, height=500, key="b2b_editor_unique")

        col_save_b1, col_save_b2 = st.columns([1, 4])
        with col_save_b1:
            if st.button("💾 Salvar Alterações na Nuvem", type="primary", use_container_width=True):
                with engine.connect() as conn:
                    for idx, row in edited_b2b.iterrows():
                        old_row = df_b2b_view.loc[idx]
                        if (row["STATUS"] != old_row["STATUS"] or 
                            row["RESUMO"] != old_row["RESUMO"] or 
                            row["TECNICO"] != old_row["TECNICO"] or 
                            row["OBS"] != old_row["OBS"]):
                            
                            conn.execute(text("""
                                UPDATE backlog_b2b 
                                SET "STATUS" = :st, "RESUMO" = :res, "TECNICO" = :tec, "OBS" = :obs 
                                WHERE "TSK" = :tsk
                            """), {"st": row["STATUS"], "res": row["RESUMO"], "tec": row["TECNICO"], "obs": row["OBS"], "tsk": row["TSK"]})
                    conn.commit()
                st.cache_data.clear()
                st.success(f"✅ Atualização enviada para a Nuvem por {st.session_state['username']}!")
                st.rerun()

        with col_save_b2:
            output_b2b = io.BytesIO()
            with pd.ExcelWriter(output_b2b, engine="openpyxl") as writer:
                df_b2b_view[cols_b2b].to_excel(writer, index=False, sheet_name="B2B_Operacao")
            st.download_button("📥 Baixar Base B2B em Excel (.xlsx)", data=output_b2b.getvalue(), file_name=f"B2B_Operacao_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================
# ABA 8: APRESENTAÇÃO EXECUTIVA
# ==========================================
elif menu == "📺 Apresentação Executiva":
    st.title("📺 Apresentação Executiva - Painel NOC FMT")
    st.markdown("Visão consolidada do Backbone para report gerencial e tomada de decisão rápida.")
    
    df = load_table("backlog_fixa")
    df_old = load_table("backlog_fixa_previous")
    df_hist = load_table("historico_diario")

    if df.empty:
        st.warning("Nenhuma base Fixa carregada na nuvem.")
    else:
        for c in ["DWDM", "ANEL_ABERTO", "IS_B2B", "IS_CRC", "QUADRANTE"]:
            if c not in df.columns: df[c] = "NÃO"

        st.markdown("### 🌐 Resumo Global da Operação")
        cg1, cg2, cg3, cg4 = st.columns(4)
        cg1.metric("Total de Eventos Ativos", len(df))
        cg2.metric("Anéis Abertos (Crítico)", (df["ANEL_ABERTO"] == "SIM").sum())
        cg3.metric("Equipamentos DWDM", (df["DWDM"] == "SIM").sum())
        cg4.metric("Atenção B2B", (df["IS_B2B"] == "SIM").sum())

        st.divider()

        st.markdown("### 🔄 Fluxo Operacional (Última Atualização)")
        tsks_old = set(df_old["TSK"].dropna().astype(str).str.strip()) if not df_old.empty else set()
        tsks_new = set(df["TSK"].dropna().astype(str).str.strip()) if not df.empty else set()

        entrantes_tsks = tsks_new - tsks_old
        saintes_fisicos = tsks_old - tsks_new
        saintes_status = df[df["STATUS"].isin(["Tramitado", "Encerrado"])].shape[0]
        
        ch1, ch2, ch3 = st.columns(3)
        ch1.metric("📥 Entrantes (Ao atualizar a base)", len(entrantes_tsks))
        ch2.metric("📤 Saintes (Saíram ao atualizar a base)", len(saintes_fisicos))
        ch3.metric("✅ Saintes Atuais (Já Encerrados/Tramitados)", saintes_status)

        st.divider()

        st.subheader("⏳ Filtro Operacional por Aging")
        col_ag1, _ = st.columns([1, 2])
        aging_options = ["Todos"] + sorted(list(df["AGING"].dropna().astype(str).unique()))
        selected_aging = col_ag1.selectbox("Selecione a faixa de Aging para detalhamento:", options=aging_options)
        
        df_view = df if selected_aging == "Todos" else df[df["AGING"].astype(str) == selected_aging]
        st.write("")

        st.markdown("### 📍 Visão Geográfica Global (Top 10 Quadrantes Impactados)")
        if "QUADRANTE" in df_view.columns and not df_view.empty:
            quad_counts = df_view[df_view["QUADRANTE"] != "NÃO INFORMADO"]["QUADRANTE"].value_counts().head(10).reset_index()
            quad_counts.columns = ["Quadrante", "Qtde"]
            if not quad_counts.empty:
                chart_global = alt.Chart(quad_counts).mark_bar(color="#F59E0B").encode(
                    y=alt.Y('Quadrante:N', sort='-x', title=""),
                    x=alt.X('Qtde:Q', title=""),
                    tooltip=['Quadrante', 'Qtde']
                ).properties(height=250)
                st.altair_chart(chart_global, use_container_width=True)
            else:
                st.info("Nenhum quadrante mapeado para os chamados nesta faixa de Aging.")
        else:
            st.info("Dados de quadrante indisponíveis para este filtro.")
            
        st.divider()

        def render_presentation_card(title, emoji, sub_df, color_theme):
            with st.container(border=True):
                st.markdown(f"<h3 style='color: {color_theme};'>{emoji} {title}</h3>", unsafe_allow_html=True)
                stats = get_status_counts(sub_df, status_col="STATUS")
                
                # Para Tratativa: Tudo que NÃO está Encerrado nem Tramitado
                pendentes = sub_df[~sub_df["STATUS"].isin(["Tramitado", "Encerrado"])].shape[0]
                
                cm1, cm2 = st.columns(2)
                cm1.metric("🔥 Agora para Tratativa", pendentes)
                cm2.metric("📊 Total Geral (Upado)", stats["Total"])
                    
                st.write("---")

                c_metrics, c_chart1, c_chart2 = st.columns([1.2, 1.5, 1.5])
                
                with c_metrics:
                    st.markdown("**Status Resumido:**")
                    st.markdown(f"🔴 **{stats['Acionado']}** Acionados")
                    st.markdown(f"🟡 **{stats['Iniciado']}** Iniciados")
                    st.markdown(f"🔵 **{stats['Tramitado']}** Tramitados")
                    st.markdown(f"🟢 **{stats['Encerrado']}** Encerrados")

                with c_chart1:
                    st.markdown("**Distribuição Lateral:**")
                    status_df = pd.DataFrame({
                        "Status": ["Acionados", "Iniciados", "Tram.", "Encerr."],
                        "Qtde": [stats["Acionado"], stats["Iniciado"], stats["Tramitado"], stats["Encerrado"]]
                    })
                    chart_st = alt.Chart(status_df).mark_bar(color=color_theme).encode(
                        y=alt.Y('Status:N', sort=['Acionados', 'Iniciados', 'Tram.', 'Encerr.'], title=""),
                        x=alt.X('Qtde:Q', title=""),
                        tooltip=['Status', 'Qtde']
                    ).properties(height=180)
                    st.altair_chart(chart_st, use_container_width=True)
                    
                with c_chart2:
                    st.markdown("**Top 5 Quadrantes:**")
                    if "QUADRANTE" in sub_df.columns:
                        quad_counts_card = sub_df[sub_df["QUADRANTE"] != "NÃO INFORMADO"]["QUADRANTE"].value_counts().head(5).reset_index()
                        quad_counts_card.columns = ["Quadrante", "Qtde"]
                        if not quad_counts_card.empty:
                            chart_qd = alt.Chart(quad_counts_card).mark_bar(color="#F59E0B").encode(
                                y=alt.Y('Quadrante:N', sort='-x', title=""),
                                x=alt.X('Qtde:Q', title=""),
                                tooltip=['Quadrante', 'Qtde']
                            ).properties(height=180)
                            st.altair_chart(chart_qd, use_container_width=True)
                        else:
                            st.caption("Sem dados.")
                    else:
                        st.caption("Sem dados.")

                st.write("---")
                st.markdown(f"**🔍 Detalhamento (Selecione o Status para filtrar):**")
                sel_tab = st.radio("Filtro:", ["Todos", "Acionado", "Iniciado", "Tramitado", "Encerrado"], horizontal=True, label_visibility="collapsed", key=f"rad_{title}")
                
                df_show = sub_df.copy()
                if sel_tab != "Todos":
                    df_show = df_show[df_show["STATUS"] == sel_tab]
                    
                cols_show = [c for c in ["TSK", "TEMPO_DO_CHAMADO", "ANEL_ABERTO", "DWDM", "NE_ID", "QUADRANTE", "STATUS", "RESUMO", "TECNICO", "AGING"] if c in df_show.columns]
                
                if not df_show.empty:
                    st.dataframe(apply_colors(df_show[cols_show]), use_container_width=True, hide_index=True)
                else:
                    st.caption(f"Nenhum chamado '{sel_tab}' encontrado.")

            st.write("")

        # 1. Anéis Abertos
        df_aneis = df_view[df_view["ANEL_ABERTO"] == "SIM"]
        render_presentation_card("Anéis Abertos (Alto Impacto)", "🚨", df_aneis, "#DC2626")

        # 2. DWDM
        df_dwdm = df_view[df_view["DWDM"] == "SIM"]
        render_presentation_card("Equipamentos DWDM (Alta Capacidade)", "🟣", df_dwdm, "#7C3AED")

        # 3. B2B Separado por Fixa e Móvel
        df_b2b_view = df_view[df_view["IS_B2B"] == "SIM"]
        
        def is_fixa(val):
            v = str(val).strip().upper()
            return v in ["", "NAN", "NONE", "NULL", "-"]
            
        if not df_b2b_view.empty:
            mask_fixa = df_b2b_view["NE_ID"].apply(is_fixa)
            df_b2b_fixa = df_b2b_view[mask_fixa]
            df_b2b_movel = df_b2b_view[~mask_fixa]
        else:
            df_b2b_fixa = pd.DataFrame(columns=df_b2b_view.columns)
            df_b2b_movel = pd.DataFrame(columns=df_b2b_view.columns)

        render_presentation_card("B2B Fixa (Corporativo)", "🏢", df_b2b_fixa, "#0284C7")
        render_presentation_card("B2B Móvel (Corporativo)", "📱", df_b2b_movel, "#2563EB")

        # 4. CRC
        df_crc_view = df_view[df_view["IS_CRC"] == "SIM"]
        render_presentation_card("Casos com Histórico CRC", "🟢", df_crc_view, "#16A34A")

# ==========================================
# ABA NOVO: CASOS CRÍTICOS (MANUAL)
# ==========================================
elif menu == "🚨 Casos Críticos":
    st.title("🚨 Gestão de Casos Críticos")
    st.markdown("Insira e atualize os casos críticos manualmente. Use o gerador abaixo para copiar o relatório e enviar por e-mail.")

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS casos_criticos (
                "TIPO" VARCHAR(50),
                "Numero Chamado" VARCHAR(50),
                "NE-ID" VARCHAR(100),
                "END-ID" VARCHAR(100),
                "QDR" VARCHAR(50),
                "Status atual" VARCHAR(50),
                "Descrição" TEXT,
                "Previsão e Nivel Escalonado" VARCHAR(150)
            )
        """))
        conn.commit()

    df_crit = load_table("casos_criticos")
    cols_crit = ["TIPO", "Numero Chamado", "NE-ID", "END-ID", "QDR", "Status atual", "Descrição", "Previsão e Nivel Escalonado"]
    
    if df_crit.empty:
        df_crit = pd.DataFrame(columns=cols_crit)
    else:
        for c in cols_crit:
            if c not in df_crit.columns:
                df_crit[c] = ""

    df_crit = df_crit[cols_crit]

    config = {
        "TIPO": st.column_config.SelectboxColumn("TIPO", options=["Ultrafibra", "100G", "400G", "Massiva"]),
        "Descrição": st.column_config.TextColumn("Descrição", width="large"),
        "Previsão e Nivel Escalonado": st.column_config.TextColumn("Previsão e Nivel Escalonado", width="large"),
    }

    edited_crit = st.data_editor(apply_colors(df_crit), num_rows="dynamic", column_config=config, use_container_width=True)

    if st.button("💾 Salvar Casos Críticos", type="primary"):
        edited_crit.to_sql("casos_criticos", engine, if_exists="replace", index=False)
        st.cache_data.clear()
        st.success("Tabela de casos críticos salva com sucesso!")
        st.rerun()

    st.divider()
    st.subheader("✉️ Gerador de Relatório para E-mail (Print)")
    
    sel_tipo = st.selectbox("Filtrar TIPO para o E-mail:", ["Todos", "Ultrafibra", "100G", "400G", "Massiva"])
    
    df_mail = edited_crit.copy()
    if sel_tipo != "Todos":
        df_mail = df_mail[df_mail["TIPO"] == sel_tipo]

    if not df_mail.empty:
        html_table = df_mail.to_html(index=False)
        html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; color: #000; border: 1px solid #ccc;">')
        html_table = html_table.replace('<th>', '<th style="background-color: #B91C1C; color: white; padding: 8px; border: 1px solid #ddd; text-align: center; font-weight: bold;">')
        html_table = html_table.replace('<td>', '<td style="padding: 8px; border: 1px solid #ddd; text-align: center;">')
        
        styled_html = f"""
        <div style="font-family: Arial, sans-serif; margin-bottom: 10px;">
            <h4 style="color: #B91C1C; margin-bottom: 5px;">Relatório de Casos Críticos {f'- {sel_tipo}' if sel_tipo != 'Todos' else ''}</h4>
            {html_table}
        </div>
        """
        
        st.info("💡 **Dica:** Selecione a tabela abaixo inteira com o mouse, aperte `Ctrl+C` e cole diretamente no corpo do Outlook com `Ctrl+V`. A formatação será mantida!")
        st.markdown(styled_html, unsafe_allow_html=True)
    else:
        st.warning("Não há dados cadastrados para gerar o e-mail com este filtro.")

# ==========================================
# ABA 10: BASE GERAL FMT
# ==========================================
elif menu == "📋 Base Geral FMT":
    st.title("📋 Base Geral de Equipamentos FMT")
    df = load_table("backlog_fixa")

    if df.empty:
        st.info("Nenhuma base carregada na nuvem.")
    else:
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            if "QUADRANTE" in df.columns:
                quad_opts = sorted([str(x) for x in df["QUADRANTE"].dropna().unique()])
                quad_filter = st.multiselect("Filtrar Quadrante:", options=quad_opts)
            else:
                quad_filter = []
        with col_f2:
            st_opts = sorted([str(x) for x in df["STATUS"].dropna().unique()])
            status_filter = st.multiselect("Filtrar Status:", options=st_opts)
        with col_f3:
            busca = st.text_input("🔍 Busca por TSK / Número, NE ID, END ID:")

        df_filtered = df.copy()
        if quad_filter and "QUADRANTE" in df.columns:
            df_filtered = df_filtered[df_filtered["QUADRANTE"].isin(quad_filter)]
        if status_filter:
            df_filtered = df_filtered[df_filtered["STATUS"].isin(status_filter)]
        if busca:
            df_filtered = df_filtered[df_filtered.astype(str).apply(lambda row: row.str.contains(busca, case=False).any(), axis=1)]

        st.dataframe(apply_colors(df_filtered), use_container_width=True, height=520)

        csv = df_filtered.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Baixar Base Filtrada (CSV)", data=csv, file_name="equipamentos_fmt_completo.csv", mime="text/csv")

# ==========================================
# ABA 11: HISTÓRICO CRC
# ==========================================
elif menu == "🗄️ Histórico CRC":
    st.title("🗄️ Base Cumulativa CRC")
    st.caption("Gestão e edição do Histórico Permanente CRC.")

    df_crc_view = get_crc_data()
    
    if df_crc_view.empty:
        st.info("O Histórico CRC está vazio. Faça um upload com os dados da aba CRC na tela inicial para começar.")
    else:
        st.metric("Total de Registros Armazenados no Histórico CRC", len(df_crc_view))
        
        c_c1, c_c2 = st.columns(2)
        with c_c1:
            busca_crc = st.text_input("🔍 Buscar TSK ou NE ID no Histórico CRC:")
        with c_c2:
            current_end_ids = list(df_crc_view["end_id"].dropna().astype(str).unique())
            custom_opts = ["FMMT", "Encerrado", "FMO", "Outros"]
            all_end_id_options = ["Todos"] + sorted(list(set(current_end_ids + custom_opts)))
            sel_end_id = st.selectbox("Filtrar por END ID / Equipe:", options=all_end_id_options)

        if busca_crc:
            df_crc_view = df_crc_view[df_crc_view.astype(str).apply(lambda row: row.str.contains(busca_crc, case=False).any(), axis=1)]
        
        if sel_end_id != "Todos":
            df_crc_view = df_crc_view[df_crc_view["end_id"].astype(str) == sel_end_id]

        for c in ["tsk", "ne_id", "end_id", "status", "aging", "descricao", "data_atualizacao"]:
            if c not in df_crc_view.columns:
                df_crc_view[c] = ""
        
        end_id_col_opts = sorted(list(set(current_end_ids + custom_opts)))

        col_cfg_crc = {
            "tsk": st.column_config.TextColumn("TSK", disabled=True),
            "ne_id": st.column_config.TextColumn("NE ID", disabled=True),
            "end_id": st.column_config.SelectboxColumn("END ID / Equipe", options=end_id_col_opts),
            "status": st.column_config.SelectboxColumn("Status", options=["Acionado", "Iniciado", "Tramitado", "Encerrado", "Não Acionado"]),
            "aging": st.column_config.TextColumn("Aging", disabled=True),
            "descricao": st.column_config.TextColumn("Descrição", width="large"),
            "data_atualizacao": st.column_config.TextColumn("Última Atualização", disabled=True)
        }

        edited_crc = st.data_editor(
            apply_colors(df_crc_view[["tsk", "ne_id", "end_id", "status", "aging", "descricao", "data_atualizacao"]]), 
            column_config=col_cfg_crc, 
            use_container_width=True, 
            height=500, 
            key="crc_editor"
        )

        col_crc_btn1, col_crc_btn2 = st.columns([1, 4])
        with col_crc_btn1:
            if st.button("💾 Salvar Alterações no Histórico CRC", type="primary", use_container_width=True):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with engine.connect() as conn:
                    for idx, row in edited_crc.iterrows():
                        old_row = df_crc_view.loc[idx]
                        if (row["status"] != old_row["status"] or 
                            row["descricao"] != old_row["descricao"] or 
                            row["end_id"] != old_row["end_id"]):
                            
                            conn.execute(text("""
                                UPDATE crc_historico 
                                SET status = :st, descricao = :desc, end_id = :end, data_atualizacao = :dt 
                                WHERE tsk = :tsk
                            """), {
                                "st": row["status"], 
                                "desc": row["descricao"], 
                                "end": row["end_id"], 
                                "dt": now,
                                "tsk": row["tsk"]
                            })
                    conn.commit()
                st.cache_data.clear()
                st.success("✅ Histórico CRC atualizado com sucesso!")
                st.rerun()

# ==========================================
# ABA 12: HISTÓRICO DIÁRIO (EOD)
# ==========================================
elif menu == "📅 Histórico Diário (Dias)":
    st.title("📅 Histórico Diário (Snapshots)")
    st.caption("Arquivos de fechamento salvos automaticamente na virada do dia (00:00).")
    
    df_hist = load_table("historico_diario")
    if df_hist.empty:
        st.info("Nenhum histórico diário gerado ainda. O sistema salvará o primeiro hoje à meia-noite.")
    else:
        dias_disponiveis = sorted(df_hist["data_snapshot"].unique(), reverse=True)
        selected_dia = st.selectbox("Selecione o Dia para visualizar e baixar:", options=dias_disponiveis)
        
        df_view = df_hist[df_hist["data_snapshot"] == selected_dia]
        st.metric(f"Total de Registros do Plantão ({selected_dia})", len(df_view))
        st.dataframe(apply_colors(df_view), use_container_width=True)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_view.to_excel(writer, index=False, sheet_name=f"Fixa_{selected_dia}")
        st.download_button("📥 Baixar Relatório do Dia em Excel", data=output.getvalue(), file_name=f"Backlog_Fixa_Historico_{selected_dia}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
