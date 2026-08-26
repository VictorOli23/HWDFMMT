import streamlit as st
import pandas as pd
import sqlite3
import re
import io
from datetime import datetime

st.set_page_config(
    page_title="NOC FMT - Backlog & Gestão Operacional",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 1. BANCO DE DADOS LOCAL (CRC E QUADRANTES)
# ==========================================
def init_db():
    conn = sqlite3.connect("crc_database.db")
    cursor = conn.cursor()
    # Tabela Histórico CRC
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crc_historico (
            tsk TEXT PRIMARY KEY,
            ne_id TEXT,
            end_id TEXT,
            status TEXT,
            aging TEXT,
            descricao TEXT,
            data_atualizacao TEXT
        )
    """)
    # Tabela Base Fixa de Quadrantes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quadrantes (
            end_id TEXT PRIMARY KEY,
            quadrante TEXT
        )
    """)
    conn.commit()
    conn.close()

def upsert_crc(df_crc):
    conn = sqlite3.connect("crc_database.db")
    cursor = conn.cursor()
    
    cols = [str(c).upper().strip() for c in df_crc.columns]
    df_crc.columns = cols
    
    col_tsk = next((c for c in cols if any(k in c for k in ["NUMERO", "NÚMERO", "TSK", "CHAMADO", "ORDEM"])), cols[0])
    col_ne = next((c for c in cols if "NE" in c), cols[min(1, len(cols)-1)])
    col_end = next((c for c in cols if "END" in c), cols[min(2, len(cols)-1)])
    col_status = next((c for c in cols if "STATUS" in c), cols[min(3, len(cols)-1)])
    col_aging = next((c for c in cols if "AGING" in c), None)
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    novos, atualizados = 0, 0
    
    for _, row in df_crc.iterrows():
        tsk_val = str(row.get(col_tsk, "")).strip()
        if not tsk_val or tsk_val.lower() in ["nan", "none", ""]:
            continue
            
        ne_val = str(row.get(col_ne, ""))
        end_val = str(row.get(col_end, ""))
        st_val = str(row.get(col_status, ""))
        aging_val = str(row.get(col_aging, "")) if col_aging else ""
        
        cursor.execute("SELECT tsk FROM crc_historico WHERE tsk = ?", (tsk_val,))
        if cursor.fetchone():
            cursor.execute("""
                UPDATE crc_historico 
                SET ne_id = ?, end_id = ?, status = ?, aging = ?, data_atualizacao = ?
                WHERE tsk = ?
            """, (ne_val, end_val, st_val, aging_val, now, tsk_val))
            atualizados += 1
        else:
            cursor.execute("""
                INSERT INTO crc_historico (tsk, ne_id, end_id, status, aging, descricao, data_atualizacao)
                VALUES (?, ?, ?, ?, ?, '', ?)
            """, (tsk_val, ne_val, end_val, st_val, aging_val, now))
            novos += 1
            
    conn.commit()
    conn.close()
    return novos, atualizados

def get_crc_data():
    conn = sqlite3.connect("crc_database.db")
    df = pd.read_sql_query("SELECT * FROM crc_historico", conn)
    conn.close()
    return df

def upsert_quadrantes(df_quad):
    conn = sqlite3.connect("crc_database.db")
    cursor = conn.cursor()
    
    col_end = next((c for c in df_quad.columns if "END" in str(c).upper()), df_quad.columns[0])
    col_q_val = next((c for c in df_quad.columns if any(k in str(c).upper() for k in ["QD", "QUADRANTE", "ANF"])), df_quad.columns[-1])
    
    novos, atualizados = 0, 0
    for _, row in df_quad.iterrows():
        end_val = str(row.get(col_end, "")).strip().upper()
        quad_val = str(row.get(col_q_val, "")).strip().upper()
        
        if not end_val or end_val == "NAN" or end_val == "NONE":
            continue
            
        cursor.execute("SELECT end_id FROM quadrantes WHERE end_id = ?", (end_val,))
        if cursor.fetchone():
            cursor.execute("UPDATE quadrantes SET quadrante = ? WHERE end_id = ?", (quad_val, end_val))
            atualizados += 1
        else:
            cursor.execute("INSERT INTO quadrantes (end_id, quadrante) VALUES (?, ?)", (end_val, quad_val))
            novos += 1
            
    conn.commit()
    conn.close()
    return novos, atualizados

def get_quadrantes_map():
    conn = sqlite3.connect("crc_database.db")
    df = pd.read_sql_query("SELECT * FROM quadrantes", conn)
    conn.close()
    if df.empty:
        return {}
    return dict(zip(df['end_id'], df['quadrante']))

init_db()

# ==========================================
# 2. FUNÇÕES AUXILIARES DE PROCESSAMENTO
# ==========================================
def load_file(file, target_sheet_hints=None):
    if file is None:
        return pd.DataFrame()
    
    if file.name.endswith(".csv"):
        content = file.getvalue().decode('utf-8', errors='ignore')
        lines = content.splitlines()
        skip = 1 if len(lines) > 0 and "sep=" in lines[0].lower() else 0
        try:
            df = pd.read_csv(io.StringIO(content), skiprows=skip, sep=None, engine='python')
        except:
            df = pd.read_csv(io.StringIO(content), skiprows=skip, sep=';', engine='python')
    else:
        xls = pd.ExcelFile(file)
        sheet_to_load = xls.sheet_names[0]
        if target_sheet_hints:
            for s in xls.sheet_names:
                if any(hint.upper() in s.upper() for hint in target_sheet_hints):
                    sheet_to_load = s
                    break
        df = pd.read_excel(xls, sheet_name=sheet_to_load)
        
        if str(df.columns[0]).startswith("Unnamed:") and len(df) > 0:
            for idx in range(min(10, len(df))):
                row_vals = [str(x).upper() for x in df.iloc[idx].values]
                if any(k in "".join(row_vals) for k in ["NÚMERO", "NUMERO", "TSK", "END ID", "NE ID", "TIPO DO EQUIPAMENTO"]):
                    df.columns = df.iloc[idx]
                    df = df.iloc[idx+1:].reset_index(drop=True)
                    break
    return df

def get_single_series(df, col_name_hints, fallback_val=""):
    col_found = None
    for hint in col_name_hints:
        match = next((c for c in df.columns if hint in str(c).upper().strip()), None)
        if match:
            col_found = match
            break
            
    if not col_found:
        return pd.Series([fallback_val] * len(df), index=df.index, dtype=str)
        
    extracted = df[col_found]
    if isinstance(extracted, pd.DataFrame):
        return extracted.iloc[:, 0].fillna("").astype(str)
    return extracted.fillna("").astype(str)

def categorize_status(st_str):
    s = str(st_str).upper()
    if any(k in s for k in ["ACIONADO", "NOTIFICADO", "ENCAMINHADO"]):
        return "Acionado"
    elif any(k in s for k in ["INICIADO", "ANDAMENTO", "CAMPO", "ATENDIMENTO", "EM ATENDIMENTO"]):
        return "Iniciado"
    elif any(k in s for k in ["TRAMITADO", "AGUARDANDO", "PAUSA", "TERCEIRO", "PENDENTE", "ESCALONADO"]):
        return "Tramitado"
    elif any(k in s for k in ["ENCERRADO", "CONCLUIDO", "CANCELADO", "FECHADO", "RESOLVIDO"]):
        return "Encerrado"
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
            days = diff.days
            hours, remainder = divmod(diff.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{days}d {hours:02d}h {minutes:02d}m"
        except:
            pass
    ag_val = str(row.get("AGING", "")).strip()
    return ag_val if ag_val and ag_val not in ["nan", "None"] else "0d 00h"

# ==========================================
# 3. INTERFACE E MENU
# ==========================================
st.sidebar.title("📡 NOC FMT Command Center")
menu = st.sidebar.radio(
    "Navegação",
    [
        "📥 Upload & Processamento",
        "📂 Backlog Operacional (Fixa)",
        "📱 Backlog Móvel",
        "🔄 Handover (Entrantes/Saintes)",
        "💼 Gestão B2B",
        "📺 Apresentação Executiva",
        "📊 Métricas & Trâmites",
        "📋 Base Geral FMT",
        "🗄️ Histórico CRC"
    ]
)

if "df_fmt_consolidado" not in st.session_state:
    st.session_state.df_fmt_consolidado = pd.DataFrame()
if "df_fmt_previous" not in st.session_state:
    st.session_state.df_fmt_previous = pd.DataFrame() 
if "df_b2b_consolidado" not in st.session_state:
    st.session_state.df_b2b_consolidado = pd.DataFrame()
if "df_movel_consolidado" not in st.session_state:
    st.session_state.df_movel_consolidado = pd.DataFrame()

# ==========================================
# ABA 1: UPLOAD & CRUZAMENTO
# ==========================================
if menu == "📥 Upload & Processamento":
    st.title("📥 Ingestão, Cruzamento e Regras de Negócio")
    st.caption("Faça upload das bases reais. O sistema irá ler as colunas, processar Anéis e DWDM.")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Bases Operacionais")
        f_fmt = st.file_uploader("1. Base Fixa FMT (Ex: u_task_evento)", type=["xlsx", "csv"])
        f_fmmt = st.file_uploader("2. Base Total FMMT (Para cruzamento Anel)", type=["xlsx", "csv"])
        f_b2b = st.file_uploader("3. Base B2B (Corporativo)", type=["xlsx", "csv"])
        f_movel_backlog = st.file_uploader("4. Base Apenas Móvel (Backlog Dedicado)", type=["xlsx", "csv"])

    with col2:
        st.subheader("Bases de Apoio & Correlação")
        f_grafana = st.file_uploader("5. Base Grafana (Alarmes CSV)", type=["xlsx", "csv"])
        f_quadrantes = st.file_uploader("6. Base de Quadrantes (Permanente / Suba apenas uma vez)", type=["xlsx", "csv"])
        f_crc = st.file_uploader("7. Base CRC (Histórico)", type=["xlsx", "csv"])

    if st.button("🚀 Processar e Integrar Todas as Bases", type="primary", use_container_width=True):
        with st.spinner("Lendo planilhas, mapeando colunas e cruzando dados..."):
            
            # 1. PROCESSAMENTO DA BASE FIXA FMT E CRUZAMENTOS
            if f_fmt:
                df_fmt_raw = load_file(f_fmt, ["BACKLOG", "FMT", "TASK", "EVENTO"])
                df_fmmt = load_file(f_fmmt, ["FMMT", "MOVEL"]) if f_fmmt else pd.DataFrame()
                df_graf = load_file(f_grafana, ["GRAFANA", "ANEIS", "ALARMES"]) if f_grafana else pd.DataFrame()

                # Processar novos Quadrantes no Banco de Dados se foi feito o upload
                if f_quadrantes:
                    df_quad_raw = load_file(f_quadrantes, ["QUAD", "QD", "ANF"])
                    if not df_quad_raw.empty:
                        novos_q, at_q = upsert_quadrantes(df_quad_raw)
                        st.success(f"✅ Base de Quadrantes Atualizada: {novos_q} novos adicionados e {at_q} atualizados.")

                s_tsk = get_single_series(df_fmt_raw, ["NÚMERO", "NUMERO", "TSK", "CHAMADO", "ORDEM"], "")
                s_end_id = get_single_series(df_fmt_raw, ["END ID", "END_ID", "SITE"], "")
                s_ne_id = get_single_series(df_fmt_raw, ["NE ID DO EVENTO", "NE ID", "NENAME"], "")
                s_tipo_equip = get_single_series(df_fmt_raw, ["TIPO DO EQUIPAMENTO", "TIPO NE", "EQUIPAMENTO"], "")
                s_status_raw = get_single_series(df_fmt_raw, ["STATUS"], "Não Acionado")
                s_falha = get_single_series(df_fmt_raw, ["ALARME", "FALHA"], "")
                s_aging = get_single_series(df_fmt_raw, ["AGING"], "-")
                s_data_cria = get_single_series(df_fmt_raw, ["DATA DE CRIAÇÃO", "DATA_CRIACAO", "CRIA"], "")
                s_tecnico = get_single_series(df_fmt_raw, ["NOME DO TÉCNICO", "NOME TÉCNICO CAMPO", "TÉCNICO", "TECNICO", "RESPONSÁVEL"], "")
                s_resumo = get_single_series(df_fmt_raw, ["RESUMO", "OBSERVAÇÕES"], "")
                s_obs = get_single_series(df_fmt_raw, ["OBS", "NOTAS"], "")

                s_dwdm = s_tipo_equip.apply(lambda val: "SIM" if "DWDM" in str(val).upper().strip() else "NÃO")

                df_fmt = pd.DataFrame({
                    "TSK": s_tsk,
                    "END_ID": s_end_id,
                    "NE_ID": s_ne_id,
                    "TIPO_EQUIPAMENTO": s_tipo_equip,
                    "DWDM": s_dwdm,
                    "FALHA": s_falha,
                    "AGING": s_aging,
                    "DATA_CRIACAO": s_data_cria,
                    "STATUS": s_status_raw.apply(categorize_status),
                    "RESUMO": s_resumo.apply(lambda r: "Em Campo" if "CAMPO" in str(r).upper() else ("Tramitado" if "TRAMITADO" in str(r).upper() else ("Encerrado" if "ENCERRADO" in str(r).upper() else str(r)))),
                    "TECNICO": s_tecnico,
                    "OBS": s_obs
                })

                # Mapeamento de Quadrantes usando o Banco de Dados Permanente
                quad_map = get_quadrantes_map()
                df_fmt["QUADRANTE"] = df_fmt["END_ID"].astype(str).str.strip().str.upper().map(quad_map)
                df_fmt["QUADRANTE"] = df_fmt["QUADRANTE"].fillna(
                    df_fmt["END_ID"].astype(str).apply(lambda x: re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE).group(0).upper() if re.search(r'(QD\s*\d+|ANF\s*\d+)', str(x), re.IGNORECASE) else "NÃO INFORMADO")
                )

                df_fmt["TEMPO_DO_CHAMADO"] = df_fmt.apply(calculate_tempo_chamado, axis=1)

                graf_full_text = " | ".join(str(val).upper().strip() for val in df_graf.values.flatten() if pd.notna(val)) if not df_graf.empty else ""

                def check_anel_grafana(row):
                    if not graf_full_text:
                        return "NÃO"
                    ne = str(row.get("NE_ID", "")).strip().upper()
                    end = str(row.get("END_ID", "")).strip().upper()

                    if ne and len(ne) >= 5 and ne in graf_full_text:
                        return "SIM"
                    if end and len(end) >= 5 and end in graf_full_text:
                        return "SIM"
                    return "NÃO"

                df_fmt["ANEL_ABERTO"] = df_fmt.apply(check_anel_grafana, axis=1)

                if not st.session_state.df_fmt_consolidado.empty:
                    st.session_state.df_fmt_previous = st.session_state.df_fmt_consolidado.copy()

                st.session_state.df_fmt_consolidado = df_fmt
                aneis_count = (df_fmt["ANEL_ABERTO"] == "SIM").sum()
                st.success(f"✅ Base Fixa: {len(df_fmt)} registros lidos. Encontrados {aneis_count} Anéis Abertos cruzando com Grafana.")

            # 2. PROCESSAMENTO DO CRC
            if f_crc:
                df_crc_raw = load_file(f_crc, ["CRC"])
                novos, at = upsert_crc(df_crc_raw)
                st.success(f"✅ Base CRC: {novos} novos chamados adicionados e {at} atualizados no histórico.")
                
            # Atualiza a base fixa com CRC do banco
            if not st.session_state.df_fmt_consolidado.empty:
                df_crc_db = get_crc_data()
                crc_tsks = set(df_crc_db["tsk"].dropna().astype(str).str.strip())
                st.session_state.df_fmt_consolidado["IS_CRC"] = st.session_state.df_fmt_consolidado["TSK"].astype(str).str.strip().apply(lambda x: "SIM" if x in crc_tsks else "NÃO")

            # 3. PROCESSAMENTO DA BASE B2B
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

                df_b2b_proc = pd.DataFrame({
                    "TSK": s_b2b_tsk,
                    "END_ID": s_b2b_end,
                    "NE_ID": s_b2b_ne,
                    "FALHA": s_b2b_falha,
                    "AGING": s_b2b_aging,
                    "DATA_CRIACAO": s_b2b_cria,
                    "STATUS": s_b2b_status.apply(categorize_status),
                    "RESUMO": s_b2b_res.apply(lambda r: "Em Campo" if "CAMPO" in str(r).upper() else ("Tramitado" if "TRAMITADO" in str(r).upper() else ("Encerrado" if "ENCERRADO" in str(r).upper() else str(r)))),
                    "TECNICO": s_b2b_tec,
                    "OBS": s_b2b_obs
                })
                df_b2b_proc["TEMPO_DO_CHAMADO"] = df_b2b_proc.apply(calculate_tempo_chamado, axis=1)
                st.session_state.df_b2b_consolidado = df_b2b_proc
                st.success(f"✅ Base B2B: {len(df_b2b_proc)} registros lidos.")
                
                if not st.session_state.df_fmt_consolidado.empty:
                    b2b_tokens = set(df_b2b_proc["TSK"].dropna().astype(str).str.strip().str.upper()).union(set(df_b2b_proc["NE_ID"].dropna().astype(str).str.strip().str.upper()))
                    st.session_state.df_fmt_consolidado["IS_B2B"] = st.session_state.df_fmt_consolidado.apply(lambda r: "SIM" if str(r["TSK"]).upper() in b2b_tokens or str(r["NE_ID"]).upper() in b2b_tokens else "NÃO", axis=1)

            # 4. PROCESSAMENTO DA BASE MÓVEL (BACKLOG DEDICADO)
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
                    "TSK": s_tsk_m,
                    "END_ID": s_end_m,
                    "NE_ID": s_ne_m,
                    "FALHA": s_falha_m,
                    "AGING": s_aging_m,
                    "DATA_CRIACAO": s_cria_m,
                    "STATUS": s_status_m.apply(categorize_status),
                    "RESUMO": s_resumo_m.apply(lambda r: "Em Campo" if "CAMPO" in str(r).upper() else ("Tramitado" if "TRAMITADO" in str(r).upper() else ("Encerrado" if "ENCERRADO" in str(r).upper() else str(r)))),
                    "TECNICO": s_tec_m,
                    "OBS": s_obs_m
                })
                df_movel["TEMPO_DO_CHAMADO"] = df_movel.apply(calculate_tempo_chamado, axis=1)
                st.session_state.df_movel_consolidado = df_movel
                st.success(f"✅ Base Móvel (Backlog): {len(df_movel)} registros lidos.")

# ==========================================
# ABA 2: BACKLOG OPERACIONAL (FIXA)
# ==========================================
elif menu == "📂 Backlog Operacional (Fixa)":
    st.title("📂 Backlog Operacional (Rede Fixa)")
    st.caption("Visão operacional espelhada na planilha padrão da equipe Fixa.")

    df = st.session_state.df_fmt_consolidado

    if df.empty:
        st.warning("Nenhuma base carregada. Realize o upload na primeira aba.")
    else:
        for c in ["DWDM", "ANEL_ABERTO", "IS_B2B", "IS_CRC"]:
            if c not in df.columns:
                df[c] = "NÃO"

        cols_backlog = ["TSK", "END_ID", "NE_ID", "TEMPO_DO_CHAMADO", "AGING", "FALHA", "STATUS", "OBS", "RESUMO", "TECNICO", "DWDM", "ANEL_ABERTO", "IS_CRC", "QUADRANTE"]

        for c in cols_backlog:
            if c not in df.columns:
                df[c] = ""

        df_bk_view = df.loc[:, ~df.columns.duplicated()].copy()

        c_f1, c_f2, c_f3, c_f4 = st.columns([1, 1, 1, 2])
        with c_f1:
            st_opts = ["Todos"] + sorted(list(df_bk_view["STATUS"].dropna().unique()))
            sel_st = st.selectbox("Filtrar Status:", options=st_opts, key="bk_status")
        with c_f2:
            sel_anel = st.selectbox("Anel Aberto:", options=["Todos", "SIM", "NÃO"], key="bk_anel")
        with c_f3:
            sel_dwdm = st.selectbox("DWDM:", options=["Todos", "SIM", "NÃO"], key="bk_dwdm")
        with c_f4:
            busca_bk = st.text_input("🔍 Busca rápida (NE ID, TSK / Número, Técnico, Quadrante):", key="bk_busca")

        if sel_st != "Todos":
            df_bk_view = df_bk_view[df_bk_view["STATUS"] == sel_st]
        if sel_anel != "Todos":
            df_bk_view = df_bk_view[df_bk_view["ANEL_ABERTO"] == sel_anel]
        if sel_dwdm != "Todos":
            df_bk_view = df_bk_view[df_bk_view["DWDM"] == sel_dwdm]
        if busca_bk:
            df_bk_view = df_bk_view[df_bk_view.astype(str).apply(lambda row: row.str.contains(busca_bk, case=False).any(), axis=1)]

        column_config = {
            "TSK": st.column_config.TextColumn("TSK", disabled=True),
            "END_ID": st.column_config.TextColumn("END ID", disabled=True),
            "NE_ID": st.column_config.TextColumn("NE ID", disabled=True),
            "TEMPO_DO_CHAMADO": st.column_config.TextColumn("DOWNTIME", disabled=True),
            "AGING": st.column_config.TextColumn("AGING", disabled=True),
            "FALHA": st.column_config.TextColumn("FALHA", disabled=True),
            "STATUS": st.column_config.SelectboxColumn(
                "Status",
                options=["Iniciado", "Acionado", "Encerrado", "Tramitado", "Não Acionado"],
                required=True
            ),
            "OBS": st.column_config.TextColumn("Obs.:", width="large"),
            "RESUMO": st.column_config.SelectboxColumn(
                "RESUMO",
                options=["Em Campo", "Tramitado", "Encerrado", "Em Análise", "Acionado", "Outros"]
            ),
            "TECNICO": st.column_config.TextColumn("TÉCNICO"),
            "DWDM": st.column_config.TextColumn("TIPO NE", disabled=True),
            "ANEL_ABERTO": st.column_config.TextColumn("ANEL", disabled=True),
            "IS_CRC": st.column_config.TextColumn("CRC", disabled=True),
            "QUADRANTE": st.column_config.TextColumn("QDRs", disabled=True),
        }

        edited_bk = st.data_editor(
            df_bk_view[cols_backlog],
            column_config=column_config,
            use_container_width=True,
            height=560,
            key="backlog_editor_unique"
        )

        col_b1, col_b2 = st.columns([1, 4])
        with col_b1:
            if st.button("💾 Salvar Alterações", type="primary", use_container_width=True):
                df_global = st.session_state.df_fmt_consolidado.copy()
                for _, row in edited_bk.iterrows():
                    tsk_key = row["TSK"]
                    idx = df_global[df_global["TSK"] == tsk_key].index
                    if not idx.empty:
                        for field in ["STATUS", "RESUMO", "TECNICO", "OBS"]:
                            df_global.loc[idx, field] = row[field]

                st.session_state.df_fmt_consolidado = df_global
                st.success("✅ Backlog Fixa atualizado com sucesso!")
                st.rerun()

        with col_b2:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_bk_view[cols_backlog].to_excel(writer, index=False, sheet_name="Backlog_Fixa")
            excel_data = output.getvalue()
            st.download_button(
                label="📥 Baixar Backlog Fixa em Excel (.xlsx)",
                data=excel_data,
                file_name=f"Backlog_Fixa_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ==========================================
# ABA 3: BACKLOG MÓVEL
# ==========================================
elif menu == "📱 Backlog Móvel":
    st.title("📱 Backlog Móvel")
    st.caption("Visão e gestão exclusiva da base móvel, sem cruzamento com anéis/quadrantes da Fixa.")

    df_movel = st.session_state.df_movel_consolidado

    if df_movel.empty:
        st.warning("Nenhuma base Móvel carregada. Faça o upload na primeira aba (Opção 4).")
    else:
        stats_movel = get_status_counts(df_movel, status_col="STATUS")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Móvel", stats_movel["Total"])
        m2.metric("Acionados", stats_movel["Acionado"])
        m3.metric("Iniciados / Campo", stats_movel["Iniciado"])
        m4.metric("Tramitados", stats_movel["Tramitado"])
        m5.metric("Encerrados", stats_movel["Encerrado"])

        st.divider()

        cols_movel = ["TSK", "END_ID", "NE_ID", "TEMPO_DO_CHAMADO", "AGING", "FALHA", "STATUS", "OBS", "RESUMO", "TECNICO"]
        for c in cols_movel:
            if c not in df_movel.columns:
                df_movel[c] = ""

        df_movel_view = df_movel.loc[:, ~df_movel.columns.duplicated()].copy()

        c_m1, c_m2 = st.columns([1, 3])
        with c_m1:
            st_movel_opts = ["Todos"] + sorted(list(df_movel_view["STATUS"].dropna().unique()))
            sel_movel_st = st.selectbox("Filtrar por Status Móvel:", options=st_movel_opts)
        with c_m2:
            busca_movel = st.text_input("🔍 Busca Móvel (Número / TSK, NE ID, Falha, Técnico):")

        if sel_movel_st != "Todos":
            df_movel_view = df_movel_view[df_movel_view["STATUS"] == sel_movel_st]
        if busca_movel:
            df_movel_view = df_movel_view[df_movel_view.astype(str).apply(lambda row: row.str.contains(busca_movel, case=False).any(), axis=1)]

        column_config_movel = {
            "TSK": st.column_config.TextColumn("TSK / Número", disabled=True),
            "END_ID": st.column_config.TextColumn("END ID", disabled=True),
            "NE_ID": st.column_config.TextColumn("NE ID", disabled=True),
            "TEMPO_DO_CHAMADO": st.column_config.TextColumn("Tempo Chamado", disabled=True),
            "AGING": st.column_config.TextColumn("Aging", disabled=True),
            "FALHA": st.column_config.TextColumn("Falha", disabled=True),
            "STATUS": st.column_config.SelectboxColumn(
                "Status",
                options=["Iniciado", "Acionado", "Encerrado", "Tramitado", "Não Acionado"],
                required=True
            ),
            "RESUMO": st.column_config.SelectboxColumn(
                "Resumo",
                options=["Em Campo", "Tramitado", "Encerrado", "Em Análise", "Acionado", "Outros"]
            ),
            "TECNICO": st.column_config.TextColumn("Técnico Responsável"),
            "OBS": st.column_config.TextColumn("Observações / Trâmites", width="large"),
        }

        edited_movel = st.data_editor(
            df_movel_view[cols_movel],
            column_config=column_config_movel,
            use_container_width=True,
            height=500,
            key="movel_editor_unique"
        )

        col_save_m1, col_save_m2 = st.columns([1, 4])
        with col_save_m1:
            if st.button("💾 Salvar Alterações Móvel", type="primary", use_container_width=True):
                df_global_movel = st.session_state.df_movel_consolidado.copy()
                for _, row in edited_movel.iterrows():
                    tsk_key = row["TSK"]
                    idx = df_global_movel[df_global_movel["TSK"] == tsk_key].index
                    if not idx.empty:
                        for field in ["STATUS", "RESUMO", "TECNICO", "OBS"]:
                            df_global_movel.loc[idx, field] = row[field]

                st.session_state.df_movel_consolidado = df_global_movel
                st.success("✅ Base Móvel salva com sucesso!")
                st.rerun()

        with col_save_m2:
            output_movel = io.BytesIO()
            with pd.ExcelWriter(output_movel, engine="openpyxl") as writer:
                df_movel_view[cols_movel].to_excel(writer, index=False, sheet_name="Backlog_Movel")
            excel_data_movel = output_movel.getvalue()
            st.download_button(
                label="📥 Baixar Backlog Móvel em Excel (.xlsx)",
                data=excel_data_movel,
                file_name=f"Backlog_Movel_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ==========================================
# ABA 4: HANDOVER (SAINTES E ENTRANTES)
# ==========================================
elif menu == "🔄 Handover (Entrantes/Saintes)":
    st.title("🔄 Handover Operacional")
    st.caption("Acompanhe o que entrou de novo e o que saiu do seu backlog da Fixa desde a última atualização da base.")

    df_new = st.session_state.get("df_fmt_consolidado", pd.DataFrame())
    df_old = st.session_state.get("df_fmt_previous", pd.DataFrame())

    if df_new.empty or df_old.empty:
        st.info("⚠️ **Como usar o Handover:**\n\nPara ver a diferença, o sistema precisa ter memória. Você carregou apenas uma base hoje.\n\nQuando você fizer o **Upload de uma nova planilha atualizada** na primeira aba, o sistema automaticamente guardará a anterior e mostrará aqui os Entrantes e Saintes.")
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

        t1, t2 = st.tabs(["🟢 Ver Entrantes", "🔴 Ver Saintes"])

        with t1:
            st.subheader(f"🟢 Chamados Entrantes ({len(df_entrantes)})")
            if not df_entrantes.empty:
                cols_show = ["TSK", "END_ID", "NE_ID", "QUADRANTE", "FALHA", "AGING", "STATUS"]
                cols_show = [c for c in cols_show if c in df_entrantes.columns]
                st.dataframe(df_entrantes[cols_show], use_container_width=True)
            else:
                st.success("Nenhum chamado novo entrou na base desde a última atualização.")

        with t2:
            st.subheader(f"🔴 Chamados Saintes ({len(df_saintes)})")
            if not df_saintes.empty:
                cols_show = ["TSK", "END_ID", "NE_ID", "QUADRANTE", "FALHA", "STATUS", "TECNICO", "OBS"]
                cols_show = [c for c in cols_show if c in df_saintes.columns]
                st.dataframe(df_saintes[cols_show], use_container_width=True)
            else:
                st.info("Nenhum chamado saiu da base desde a última atualização.")

# ==========================================
# ABA 5: GESTÃO B2B
# ==========================================
elif menu == "💼 Gestão B2B":
    st.title("💼 Gestão B2B (Corporativo)")
    st.caption("Painel e edição exclusiva para chamados B2B.")

    df_b2b = st.session_state.df_b2b_consolidado

    if df_b2b.empty:
        st.warning("Nenhuma base B2B carregada. Envie o arquivo B2B na primeira aba.")
    else:
        stats_b2b = get_status_counts(df_b2b, status_col="STATUS")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total B2B", stats_b2b["Total"])
        m2.metric("Acionados", stats_b2b["Acionado"])
        m3.metric("Iniciados / Campo", stats_b2b["Iniciado"])
        m4.metric("Tramitados", stats_b2b["Tramitado"])
        m5.metric("Encerrados", stats_b2b["Encerrado"])

        st.divider()

        cols_b2b = ["TSK", "TEMPO_DO_CHAMADO", "NE_ID", "END_ID", "FALHA", "STATUS", "RESUMO", "TECNICO", "OBS"]
        for c in cols_b2b:
            if c not in df_b2b.columns:
                df_b2b[c] = ""

        df_b2b_view = df_b2b.loc[:, ~df_b2b.columns.duplicated()].copy()

        c_b1, c_b2 = st.columns([1, 2])
        with c_b1:
            st_b2b_opts = ["Todos"] + sorted(list(df_b2b_view["STATUS"].dropna().unique()))
            sel_b2b_st = st.selectbox("Filtrar por Status B2B:", options=st_b2b_opts)
        with c_b2:
            busca_b2b = st.text_input("🔍 Busca B2B (Número / TSK, NE ID, Falha, Técnico):")

        if sel_b2b_st != "Todos":
            df_b2b_view = df_b2b_view[df_b2b_view["STATUS"] == sel_b2b_st]
        if busca_b2b:
            df_b2b_view = df_b2b_view[df_b2b_view.astype(str).apply(lambda row: row.str.contains(busca_b2b, case=False).any(), axis=1)]

        column_config_b2b = {
            "TSK": st.column_config.TextColumn("Número / TSK", disabled=True),
            "TEMPO_DO_CHAMADO": st.column_config.TextColumn("Tempo Chamado", disabled=True),
            "NE_ID": st.column_config.TextColumn("NE ID", disabled=True),
            "END_ID": st.column_config.TextColumn("END ID", disabled=True),
            "FALHA": st.column_config.TextColumn("Falha", disabled=True),
            "STATUS": st.column_config.SelectboxColumn(
                "Status",
                options=["Iniciado", "Acionado", "Encerrado", "Tramitado", "Não Acionado"],
                required=True
            ),
            "RESUMO": st.column_config.SelectboxColumn(
                "Resumo",
                options=["Em Campo", "Tramitado", "Encerrado", "Em Análise", "Acionado", "Outros"]
            ),
            "TECNICO": st.column_config.TextColumn("Técnico Responsável"),
            "OBS": st.column_config.TextColumn("Observações / Trâmites", width="large"),
        }

        edited_b2b = st.data_editor(
            df_b2b_view[cols_b2b],
            column_config=column_config_b2b,
            use_container_width=True,
            height=500,
            key="b2b_editor_unique"
        )

        col_save_b1, col_save_b2 = st.columns([1, 4])
        with col_save_b1:
            if st.button("💾 Salvar Alterações B2B", type="primary", use_container_width=True):
                df_global_b2b = st.session_state.df_b2b_consolidado.copy()
                for _, row in edited_b2b.iterrows():
                    tsk_key = row["TSK"]
                    idx = df_global_b2b[df_global_b2b["TSK"] == tsk_key].index
                    if not idx.empty:
                        for field in ["STATUS", "RESUMO", "TECNICO", "OBS"]:
                            df_global_b2b.loc[idx, field] = row[field]

                st.session_state.df_b2b_consolidado = df_global_b2b
                st.success("✅ Base B2B salva com sucesso!")
                st.rerun()

        with col_save_b2:
            output_b2b = io.BytesIO()
            with pd.ExcelWriter(output_b2b, engine="openpyxl") as writer:
                df_b2b_view[cols_b2b].to_excel(writer, index=False, sheet_name="B2B_Operacao")
            excel_data_b2b = output_b2b.getvalue()
            st.download_button(
                label="📥 Baixar Base B2B em Excel (.xlsx)",
                data=excel_data_b2b,
                file_name=f"B2B_Operacao_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ==========================================
# ABA 6: APRESENTAÇÃO EXECUTIVA
# ==========================================
elif menu == "📺 Apresentação Executiva":
    st.title("📺 Apresentação Executiva - Painel NOC FMT")
    df = st.session_state.df_fmt_consolidado

    if df.empty:
        st.warning("Nenhuma base Fixa carregada. Realize o upload na primeira aba.")
    else:
        for c in ["DWDM", "ANEL_ABERTO", "IS_B2B", "IS_CRC"]:
            if c not in df.columns:
                df[c] = "NÃO"

        st.subheader("⏳ Filtro por Tempo de Vida (Aging)")
        col_ag1, _ = st.columns([1, 2])
        aging_options = ["Todos"] + sorted(list(df["AGING"].dropna().astype(str).unique()))
        selected_aging = col_ag1.selectbox("Selecione a faixa de Aging:", options=aging_options)
        
        df_view = df if selected_aging == "Todos" else df[df["AGING"].astype(str) == selected_aging]
        st.divider()

        def render_presentation_card(title, emoji, sub_df):
            st.markdown(f"### {emoji} {title}")
            stats = get_status_counts(sub_df, status_col="STATUS")
            
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric(f"Total {title}", stats["Total"])
            c2.metric("Acionados", stats["Acionado"])
            c3.metric("Iniciados", stats["Iniciado"])
            c4.metric("Tramitados", stats["Tramitado"])
            c5.metric("Encerrados", stats["Encerrado"])

            if not sub_df.empty:
                with st.expander(f"Ver lista detalhada de {title} ({len(sub_df)} registros)"):
                    cols_show = [c for c in ["TSK", "TEMPO_DO_CHAMADO", "ANEL_ABERTO", "DWDM", "NE_ID", "QUADRANTE", "STATUS", "RESUMO", "TECNICO", "OBS"] if c in sub_df.columns]
                    st.dataframe(sub_df[cols_show], use_container_width=True)
            else:
                st.caption(f"Nenhum registro ativo para {title} com o filtro atual.")
            st.write("")

        # 1. DWDM
        df_dwdm = df_view[df_view["DWDM"] == "SIM"]
        render_presentation_card("Equipamentos DWDM", "🟣", df_dwdm)
        st.divider()

        # 2. Anéis Abertos
        df_aneis = df_view[df_view["ANEL_ABERTO"] == "SIM"]
        render_presentation_card("Anéis Abertos (Cruzamento Grafana x FMT)", "🔴", df_aneis)
        st.divider()

        # 3. B2B
        df_b2b_view = df_view[df_view["IS_B2B"] == "SIM"]
        render_presentation_card("Casos B2B (Fixa / Móvel)", "🔵", df_b2b_view)
        st.divider()

        # 4. CRC
        df_crc_view = df_view[df_view["IS_CRC"] == "SIM"]
        render_presentation_card("Casos Histórico CRC", "🟢", df_crc_view)

# ==========================================
# ABA 7: MÉTRICAS & TRÂMITES
# ==========================================
elif menu == "📊 Métricas & Trâmites":
    st.title("📊 Resumo Geral de Trâmites & Pipeline Operacional")
    df = st.session_state.df_fmt_consolidado

    if df.empty:
        st.info("Nenhuma base carregada. Processe os dados na aba de upload.")
    else:
        stats_total = get_status_counts(df, status_col="STATUS")
        
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Equipamentos FMT", stats_total["Total"])
        m2.metric("Acionados", stats_total["Acionado"])
        m3.metric("Iniciados / Campo", stats_total["Iniciado"])
        m4.metric("Tramitados / Aguardando", stats_total["Tramitado"])
        m5.metric("Encerrados", stats_total["Encerrado"])

        st.divider()

        g1, g2 = st.columns(2)
        with g1:
            st.subheader("Volume por Quadrante (Top 10)")
            if "QUADRANTE" in df.columns:
                st.bar_chart(df["QUADRANTE"].value_counts().head(10))
        with g2:
            st.subheader("Volume por Status")
            if "STATUS" in df.columns:
                st.bar_chart(df["STATUS"].value_counts())

# ==========================================
# ABA 8: BASE GERAL FMT
# ==========================================
elif menu == "📋 Base Geral FMT":
    st.title("📋 Base Geral de Equipamentos FMT")
    df = st.session_state.df_fmt_consolidado

    if df.empty:
        st.info("Nenhuma base carregada.")
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

        st.dataframe(df_filtered, use_container_width=True, height=520)

        csv = df_filtered.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Baixar Base Filtrada (CSV)", data=csv, file_name="equipamentos_fmt_completo.csv", mime="text/csv")

# ==========================================
# ABA 9: HISTÓRICO CRC
# ==========================================
elif menu == "🗄️ Histórico CRC":
    st.title("🗄️ Base Cumulativa CRC")
    st.caption("Esta base é gravada de forma incremental e nunca é deletada nos uploads.")

    df_crc_view = get_crc_data()
    st.metric("Total de Registros Armazenados no Histórico CRC", len(df_crc_view))
    
    busca_crc = st.text_input("Buscar TSK no Histórico CRC:")
    if busca_crc:
        df_crc_view = df_crc_view[df_crc_view["tsk"].str.contains(busca_crc, case=False, na=False)]

    st.dataframe(df_crc_view, use_container_width=True)
