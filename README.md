# 📡 NOC FMT - Command Center

Painel de controle e monitoramento operacional desenvolvido em **Streamlit** e **Python** para equipes de Centro de Operações de Rede (NOC), focado na gestão de backlogs de redes fixas e móveis, cruzamento de anéis, chamados críticos e acompanhamento de indicadores em tempo real.

---

## 🚀 Principais Funcionalidades

- **Ingestão e Fusão Inteligente:** Upload e cruzamento automatizado entre bases operacionais da Rede Fixa (FMT) e Móvel (FMMT).
- **Cálculo de Downtime Real:** O tempo do chamado é calculado de forma dinâmica subtraindo a **Data de Criação** pela **data e hora atuais**, garantindo precisão e eliminando distorções de colunas de *aging* legadas.
- **Detecção de Anéis Abertos:** Cruzamento automático de dados de incidentes com bases de alarmes e topologia (Grafana).
- **Gestão B2B (Corporativo):** Separação e controle de chamados corporativos por tipo de rede (Fixa/Móvel) e grupos acionados.
- **Handover Operacional:** Comparativo automático entre plantões para identificar chamados entrantes (novos) e saintes (concluídos).
- **Histórico Cumulativo CRC & Diário:** Armazenamento de snapshots diários automáticos na virada do dia e gestão contínua de casos de rede.
- **Mecanismo de Cores por Criticidade:** Identificação visual rápida de chamados antigos ou críticos diretamente na interface.

---

## 🛠️ Tecnologias Utilizadas

- **Frontend & UI:** [Streamlit](https://streamlit.io/)
- **Manipulação de Dados:** [Pandas](https://pandas.pydata.org/)
- **Visualização de Dados:** [Altair](https://altair-viz.github.io/)
- **Banco de Dados & ORM:** SQLAlchemy (Compatível com PostgreSQL na nuvem e SQLite local)
- **Segurança:** Criptografia de senhas com `bcrypt`

---
