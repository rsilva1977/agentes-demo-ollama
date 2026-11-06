# 🤖 Laboratório Pedagógico de Agentes IA (`ministral-3:3b` + Ollama)

Uma aplicação interativa de terminal, **sem qualquer dependência externa** (100% Python Standard Library), desenhada para ensinar e demonstrar na prática como funcionam os **Agentes de Inteligência Artificial**.

## 🚀 Como Executar

Apenas precisas de ter o **Python 3** e o **Ollama** a correr localmente com o modelo `ministral-3:3b`:

```bash
python3 agentes_demo.py
```

Também podes ativar modos de inspeção diretamente pela linha de comandos:

```bash
# Pausar antes de cada chamada de ferramenta (Tool Call) para explicar passo a passo
python3 agentes_demo.py --passo-a-passo

# Mostrar o Raio-X do JSON enviado/recebido na memória do Agente
python3 agentes_demo.py --raio-x

# Executar diretamente uma das experiências (1 a 5)
python3 agentes_demo.py --modo 1
```

---

## 🧭 O que esta aplicação demonstra?

A aplicação simula o ecossistema privado de uma empresa tecnológica fictícia (**LusitanaTech**), com uma base de dados **SQLite em memória** (produtos, stocks e histórico de vendas), **logs de cibersegurança** e uma **firewall ativa**.

### 1. 🥊 LLM Isolado vs. Agente com Ferramentas (*Grounding*)
Faz exatamente a mesma pergunta sobre vendas privadas e descontos matemáticos:
- **Parte A (LLM Isolado):** Mostra como um modelo sem ferramentas não tem acesso a dados privados e pode alucinar cálculos.
- **Parte B (Agente ReAct):** O agente decide autonomamente consultar a base de dados (`consultar_loja_sql`) e usar a calculadora determinística (`calculadora_precisa`) antes de responder.

### 2. 🕵️‍♂️ Detetive Cyber-Forense (Ciclo ReAct Multi-Passo + Ação no Mundo)
O Agente investiga um incidente ocorrido às `03:14h`:
1. **Raciocínio → Ação 1:** Lê os logs de segurança (`ler_logs_seguranca`) e descobre uma intrusão via `10.0.8.99`.
2. **Observação → Ação 2:** Cruza o IP no diretório interno (`investigar_ip_interno`) e identifica uma credencial de um ex-consultor que não foi revogada.
3. **Observação → Ação 3:** Modifica o estado real do sistema bloqueando o IP na firewall (`bloquear_ip_firewall`).

### 3. 🤝 Equipa Multi-Agente (Especialização, Handoff & Reflexão)
Demonstra porque dividir problemas complexos por vários agentes especializados supera um único prompt monolítico:
- **Agente 1 (Analista de Dados):** Extrai métricas factuais de vendas e ruturas de stock via SQL.
- **Agente 2 (Auditor de Risco / Crítico):** Cruza o relatório comercial com alertas de cibersegurança sob uma persona cética.
- **Agente 3 (Diretor Executivo):** Sintetiza os dados do Analista e os alertas do Auditor num Plano de Ação de 3 pontos.

### 4. 🎮 Laboratório Livre + Modos Pedagógicos (`[P]` Passo-a-Passo e `[X]` Raio-X)
Permite conversar livremente com o Super-Agente e ligar/desligar:
- **Modo Passo-a-Passo (`[P]`):** Pausa antes da execução de cada ferramenta para explicar o que está a acontecer.
- **Modo Raio-X (`[X]`):** Exibe a lista real de mensagens JSON (`system`, `user`, `assistant`, `tool`) que compõem a memória do Agente.

