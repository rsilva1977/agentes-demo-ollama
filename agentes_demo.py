#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
🤖 LABORATÓRIO PEDAGÓGICO DE AGENTES IA (Zero Dependências + Ollama)
=============================================================================
Uma aplicação interativa de terminal para demonstrar, de forma visual e
pedagógica, como funcionam os Agentes de IA (Ciclo ReAct, Tool Calling,
Prevenção de Alucinações, Ação no Ambiente e Orquestração Multi-Agente).

Configurado por omissão para: ministral-3:3b via Ollama (localhost:11434)
Dependências externas: NENHUMA (100% Python Standard Library)
=============================================================================
"""

import argparse
import datetime
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple


# =============================================================================
# 1. PALETA VISUAL &INTERFACE DE TERMINAL (ANSI ESCAPE CODES)
# =============================================================================

class Cor:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Cores de texto
    CINZA = "\033[90m"
    VERMELHO = "\033[91m"
    VERDE = "\033[92m"
    AMARELO = "\033[93m"
    AZUL = "\033[94m"
    MAGENTA = "\033[95m"
    CIANO = "\033[96m"
    BRANCO = "\033[97m"

    # Fundos suaves para badges
    BG_AZUL = "\033[44;97;1m"
    BG_VERDE = "\033[42;30;1m"
    BG_AMARELO = "\033[43;30;1m"
    BG_MAGENTA = "\033[45;97;1m"
    BG_VERMELHO = "\033[41;97;1m"
    BG_CIANO = "\033[46;30;1m"


def largura_terminal() -> int:
    cols, _ = shutil.get_terminal_size((88, 24))
    return min(max(cols - 2, 68), 96)


def limpar_ansi(texto: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", texto)


def quebrar_texto(texto: str, largura: int) -> List[str]:
    linhas_finais = []
    for paragrafo in texto.splitlines():
        if not paragrafo.strip():
            linhas_finais.append("")
            continue
        palavras = paragrafo.split(" ")
        linha_atual = ""
        for palavra in palavras:
            teste = f"{linha_atual} {palavra}".strip() if linha_atual else palavra
            if len(limpar_ansi(teste)) <= largura:
                linha_atual = teste
            else:
                if linha_atual:
                    linhas_finais.append(linha_atual)
                linha_atual = palavra
        if linha_atual:
            linhas_finais.append(linha_atual)
    return linhas_finais or [""]


def caixa(
    titulo: str,
    conteudo: str,
    cor_borda: str = Cor.CIANO,
    icone: str = "📌",
    rodape: str = "",
) -> None:
    larg = largura_terminal()
    larg_interna = larg - 4

    titulo_fmt = f" {icone} {titulo} " if icone else f" {titulo} "
    tam_titulo = len(limpar_ansi(titulo_fmt))
    tracos_topo = max(1, larg - 2 - tam_titulo)

    print(f"{cor_borda}╭─{Cor.BOLD}{titulo_fmt}{Cor.RESET}{cor_borda}{'─' * (tracos_topo - 1)}╮{Cor.RESET}")

    for linha in quebrar_texto(conteudo, larg_interna):
        visivel = len(limpar_ansi(linha))
        espacos = max(0, larg_interna - visivel)
        print(f"{cor_borda}│{Cor.RESET} {linha}{' ' * espacos} {cor_borda}│{Cor.RESET}")

    if rodape:
        rodape_fmt = f" {rodape} "
        tam_rod = len(limpar_ansi(rodape_fmt))
        tracos_baixo = max(1, larg - 2 - tam_rod)
        print(f"{cor_borda}╰─{Cor.DIM}{rodape_fmt}{Cor.RESET}{cor_borda}{'─' * (tracos_baixo - 1)}╯{Cor.RESET}")
    else:
        print(f"{cor_borda}╰{'─' * (larg - 2)}╯{Cor.RESET}")


def nota_pedagogica(titulo: str, explicacao: str, ativo: bool = True) -> None:
    if not ativo:
        return
    caixa(
        titulo=f"NOTA PEDAGÓGICA: {titulo}",
        conteudo=f"{Cor.AMARELO}{explicacao}{Cor.RESET}",
        cor_borda=Cor.AMARELO,
        icone="💡",
    )


class Spinner:
    """Indicador visual animado enquanto o LLM local gera a resposta (com contador de tokens em streaming)."""

    def __init__(self, mensagem: str = "A pensar..."):
        self.mensagem = mensagem
        self.ativo = False
        self.thread: Optional[threading.Thread] = None
        self.inicio = 0.0
        self.tokens_gerados = 0

    def registar_token(self, n: int = 1) -> None:
        self.tokens_gerados += n

    def _animar(self) -> None:
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        while self.ativo:
            decorrido = time.time() - self.inicio
            frame = frames[idx % len(frames)]
            info_tokens = f" · {self.tokens_gerados} tokens" if self.tokens_gerados > 0 else ""
            sys.stdout.write(
                f"\r  {Cor.CIANO}{Cor.BOLD}{frame}{Cor.RESET} {self.mensagem} "
                f"{Cor.CINZA}({decorrido:.1f}s{info_tokens}){Cor.RESET}   "
            )
            sys.stdout.flush()
            time.sleep(0.08)
            idx += 1

    def __enter__(self):
        self.ativo = True
        self.inicio = time.time()
        self.tokens_gerados = 0
        self.thread = threading.Thread(target=self._animar, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.ativo = False
        if self.thread:
            self.thread.join()
        sys.stdout.write("\r" + " " * (largura_terminal()) + "\r")
        sys.stdout.flush()


# =============================================================================
# 2. MUNDO SIMULADO ("LUSITANATECH") - BASE DE DADOS E SISTEMA DE SEGURANÇA
# =============================================================================

class MundoSimulado:
    """
    Ambiente determinístico com dados privados em memória (SQLite + Logs + Firewall).
    Um LLM nunca teve acesso a estes dados no seu treino — só um Agente com ferramentas
    consegue investigar, cruzar factos e agir sobre este ambiente!
    """

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.ips_bloqueados: List[Dict[str, str]] = []
        self.tickets_resolvidos: List[Dict[str, str]] = []
        self._inicializar_dados()

    def _inicializar_dados(self) -> None:
        cur = self.conn.cursor()

        # Tabela de Produtos
        cur.execute("""
            CREATE TABLE produtos (
                id INTEGER PRIMARY KEY,
                codigo TEXT,
                nome TEXT,
                categoria TEXT,
                preco_eur REAL,
                stock INTEGER
            )
        """)
        produtos = [
            (1, "LT-GPU-09", "Placa Neural Lusitana X90", "Hardware IA", 1450.00, 3),
            (2, "LT-SRV-02", "Mini-Servidor Edge Tejo", "Servidores", 890.00, 12),
            (3, "LT-KEY-77", "Token Criptográfico Quântico", "Segurança", 210.00, 0),
            (4, "LT-NAS-04", "Cofre de Dados Atlântico 16TB", "Armazenamento", 640.00, 7),
        ]
        cur.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?)", produtos)

        # Tabela de Vendas (Outubro/Novembro)
        cur.execute("""
            CREATE TABLE vendas (
                id INTEGER PRIMARY KEY,
                cliente TEXT,
                produto_codigo TEXT,
                quantidade INTEGER,
                total_eur REAL,
                data TEXT
            )
        """)
        vendas = [
            (101, "Inês Monteiro (BioLab Porto)", "LT-GPU-09", 4, 5800.00, "2026-11-02"),
            (102, "Carlos Tavares (Fintech Douro)", "LT-SRV-02", 2, 1780.00, "2026-11-03"),
            (103, "Sofia Almeida (CyberShield LX)", "LT-KEY-77", 5, 1050.00, "2026-11-04"),
            (104, "Inês Monteiro (BioLab Porto)", "LT-NAS-04", 2, 1280.00, "2026-11-05"),
        ]
        cur.executemany("INSERT INTO vendas VALUES (?, ?, ?, ?, ?, ?)", vendas)

        # Logs de Segurança e Rede (para o Modo Detetive Cyber-Forense)
        self.logs_servidor = [
            {"hora": "02:58:10", "nivel": "INFO", "ip": "10.0.4.12", "utilizador": "marta.silva", "evento": "Backup automático concluído com sucesso."},
            {"hora": "03:11:42", "nivel": "WARN", "ip": "10.0.8.99", "utilizador": "admin_temp", "evento": "5 tentativas falhadas de SSH na base de dados central."},
            {"hora": "03:14:05", "nivel": "CRITICAL", "ip": "10.0.8.99", "utilizador": "admin_temp", "evento": "Acesso root obtido! Exportação do ficheiro 'clientes_vip.db' (420 MB)."},
            {"hora": "03:15:19", "nivel": "INFO", "ip": "10.0.4.15", "utilizador": "pedro.costa", "evento": "Verificação de rotina de sensores térmicos."},
            {"hora": "03:16:02", "nivel": "ALERT", "ip": "10.0.8.99", "utilizador": "admin_temp", "evento": "Tentativa de ligação externa para IP desconhecido 185.220.101.44."},
        ]

        self.diretorio_ips = {
            "10.0.4.12": {"responsavel": "Marta Silva", "departamento": "DevOps", "estado": "Autorizado (Turno Noite)"},
            "10.0.4.15": {"responsavel": "Pedro Costa", "departamento": "Infraestrutura", "estado": "Autorizado"},
            "10.0.8.99": {
                "responsavel": "Terminal de Testes #4 (Laboratório Antigo)",
                "credencial_associada": "Rui Gonçalves (Ex-Consultor Externo - Contrato terminou há 15 dias)",
                "departamento": "Externo / Desativado",
                "estado": "SUSPEITO - Credencial devia estar revogada!",
            },
        }

        self.conn.commit()


# =============================================================================
# 3. REGISTO DE FERRAMENTAS (TOOLS) DISPONÍVEIS PARA OS AGENTES
# =============================================================================

class RegistoFerramentas:
    """Gere as ferramentas que o Agente pode invocar e os respetivos esquemas JSON."""

    def __init__(self, mundo: MundoSimulado):
        self.mundo = mundo
        self.ferramentas: Dict[str, Dict[str, Any]] = {}
        self._registar_todas()

    def _registar_todas(self) -> None:
        self.registar(
            nome="consultar_loja_sql",
            descricao=(
                "Executa uma consulta nas tabelas da loja LusitanaTech. "
                "Podes passar 'resumo_geral' para ver todas as tabelas (produtos e vendas) "
                "ou uma query SQL SELECT nas tabelas 'produtos' (codigo, nome, categoria, preco_eur, stock) "
                "e 'vendas' (cliente, produto_codigo, quantidade, total_eur, data)."
            ),
            parametros={
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Escreve 'resumo_geral' ou uma query SQL SELECT.",
                    }
                },
                "required": ["consulta"],
            },
            funcao=self.tool_consultar_loja_sql,
        )

        self.registar(
            nome="calculadora_precisa",
            descricao="Calcula expressões matemáticas com precisão absoluta (ex: '7080 * 0.175' ou '7080 - (7080 * 0.175)').",
            parametros={
                "type": "object",
                "properties": {
                    "expressao": {
                        "type": "string",
                        "description": "Expressão matemática usando +, -, *, /, parênteses.",
                    }
                },
                "required": ["expressao"],
            },
            funcao=self.tool_calculadora_precisa,
        )

        self.registar(
            nome="ler_logs_seguranca",
            descricao="Lê os logs do servidor para investigar incidentes cibernéticos. Filtra por nível ('TODOS', 'CRITICAL', 'WARN', 'ALERT').",
            parametros={
                "type": "object",
                "properties": {
                    "filtro_nivel": {
                        "type": "string",
                        "description": "Usa 'TODOS' ou um nível específico como 'CRITICAL'.",
                    }
                },
                "required": ["filtro_nivel"],
            },
            funcao=self.tool_ler_logs_seguranca,
        )

        self.registar(
            nome="investigar_ip_interno",
            descricao="Consulta a quem pertence um endereço IP interno da empresa (ex: '10.0.8.99') e o estado das credenciais.",
            parametros={
                "type": "object",
                "properties": {
                    "ip": {
                        "type": "string",
                        "description": "Endereço IP a investigar (ex: '10.0.8.99').",
                    }
                },
                "required": ["ip"],
            },
            funcao=self.tool_investigar_ip_interno,
        )

        self.registar(
            nome="bloquear_ip_firewall",
            descricao="AÇÃO ATIVA: Bloqueia imediatamente um endereço IP malicioso na firewall da empresa e revoga a credencial.",
            parametros={
                "type": "object",
                "properties": {
                    "ip": {
                        "type": "string",
                        "description": "Endereço IP a bloquear (ex: '10.0.8.99').",
                    },
                    "motivo": {
                        "type": "string",
                        "description": "Justificação técnica para o bloqueio.",
                    },
                },
                "required": ["ip", "motivo"],
            },
            funcao=self.tool_bloquear_ip_firewall,
        )

    def registar(
        self,
        nome: str,
        descricao: str,
        parametros: Dict[str, Any],
        funcao: Callable[..., str],
    ) -> None:
        self.ferramentas[nome] = {
            "nome": nome,
            "descricao": descricao,
            "parametros": parametros,
            "funcao": funcao,
        }

    def obter_schemas_ollama(self, nomes_permitidos: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        schemas = []
        for nome, info in self.ferramentas.items():
            if nomes_permitidos and nome not in nomes_permitidos:
                continue
            schemas.append({
                "type": "function",
                "function": {
                    "name": nome,
                    "description": info["descricao"],
                    "parameters": info["parametros"],
                },
            })
        return schemas

    def executar(self, nome: str, argumentos: Dict[str, Any]) -> str:
        if nome not in self.ferramentas:
            return json.dumps({
                "erro": f"Ferramenta '{nome}' não existe. Ferramentas válidas: {list(self.ferramentas.keys())}"
            }, ensure_ascii=False)
        try:
            return self.ferramentas[nome]["funcao"](**argumentos)
        except TypeError as e:
            # Caso o modelo passe argumentos com nome ligeiramente diferente
            func = self.ferramentas[nome]["funcao"]
            valores = list(argumentos.values())
            try:
                if len(valores) == 1:
                    return func(valores[0])
                elif len(valores) == 2:
                    return func(valores[0], valores[1])
            except Exception:
                pass
            return json.dumps({"erro": f"Erro nos argumentos de {nome}: {str(e)}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"erro": f"Falha ao executar {nome}: {str(e)}"}, ensure_ascii=False)

    # --- Implementações das Ferramentas ---

    def tool_consultar_loja_sql(self, consulta: str = "resumo_geral") -> str:
        cur = self.mundo.conn.cursor()
        consulta_limpa = consulta.strip()
        if (
            consulta_limpa.lower() in ("resumo_geral", "resumo", "all", "tudo", "*")
            or not consulta_limpa.upper().startswith("SELECT")
        ):
            cur.execute("SELECT * FROM produtos")
            prods = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM vendas")
            vendas = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT cliente, SUM(total_eur) as total_gasto_eur, COUNT(*) as num_compras "
                "FROM vendas GROUP BY cliente ORDER BY total_gasto_eur DESC"
            )
            ranking = [dict(r) for r in cur.fetchall()]
            return json.dumps({
                "produtos_em_catalogo": prods,
                "historico_vendas": vendas,
                "ranking_clientes_por_total_gasto": ranking,
            }, ensure_ascii=False, indent=2)

        try:
            cur.execute(consulta_limpa)
            linhas = [dict(r) for r in cur.fetchall()]
            if not linhas:
                return self.tool_consultar_loja_sql("resumo_geral")
            return json.dumps({"resultado_sql": linhas}, ensure_ascii=False, indent=2)
        except Exception as e:
            # Fallback amigável: devolve o erro e o resumo para o modelo 3B não ficar preso
            resumo = json.loads(self.tool_consultar_loja_sql("resumo_geral"))
            return json.dumps({
                "aviso_sql": f"A query '{consulta_limpa}' deu erro ({e}). Aqui tens os dados completos das tabelas:",
                "dados_completos": resumo,
            }, ensure_ascii=False, indent=2)

    def tool_calculadora_precisa(self, expressao: str) -> str:
        # Limpa símbolos de moeda ou texto extra
        limpa = re.sub(r"[^0-9+\-*/().% ]", "", expressao.replace(",", "."))
        limpa = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100.0)", limpa)
        ambiente_seguro = {"__builtins__": None, "round": round, "abs": abs, "math": math}
        try:
            resultado = eval(limpa, ambiente_seguro, {})
            return json.dumps({
                "expressao_avaliada": limpa,
                "resultado_exato": round(float(resultado), 4),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"erro_calculo": str(e), "expressao_recebida": expressao}, ensure_ascii=False)

    def tool_ler_logs_seguranca(self, filtro_nivel: str = "TODOS") -> str:
        filtro = filtro_nivel.strip().upper()
        if filtro in ("TODOS", "ALL", "*"):
            logs = self.mundo.logs_servidor
        else:
            logs = [l for l in self.mundo.logs_servidor if filtro in l["nivel"]]
            if not logs:
                logs = self.mundo.logs_servidor
        return json.dumps({"logs_encontrados": logs}, ensure_ascii=False, indent=2)

    def tool_investigar_ip_interno(self, ip: str) -> str:
        ip_limpo = ip.strip()
        info = self.mundo.diretorio_ips.get(ip_limpo)
        if info:
            return json.dumps({"ip": ip_limpo, "registo": info}, ensure_ascii=False, indent=2)
        return json.dumps({
            "aviso": f"IP '{ip_limpo}' não encontrado isoladamente. Registos internos disponíveis:",
            "todos_os_ips": self.mundo.diretorio_ips,
        }, ensure_ascii=False, indent=2)

    def tool_bloquear_ip_firewall(self, ip: str, motivo: str = "Atividade maliciosa detetada") -> str:
        registo = {
            "ip_bloqueado": ip.strip(),
            "motivo": motivo,
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "estado_firewall": "BLOQUEADO COM SUCESSO (Regra DROP ativa + Credencial revogada)",
        }
        self.mundo.ips_bloqueados.append(registo)
        return json.dumps(registo, ensure_ascii=False, indent=2)


# =============================================================================
# 4. CLIENTE OLLAMA (100% STANDARD LIBRARY - urllib.request)
# =============================================================================

class ClienteOllama:
    """Comunica diretamente com a API HTTP local do Ollama sem pacotes externos."""

    def __init__(self, modelo: str = "ministral-3:3b", host: str = "http://localhost:11434"):
        self.modelo = modelo
        self.host = host.rstrip("/")

    def verificar_ligacao(self) -> Tuple[bool, List[str], str]:
        """Verifica se o servidor Ollama está ativo e quais os modelos instalados."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=4) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
                modelos = [m.get("name", "") for m in dados.get("models", [])]
                return True, modelos, ""
        except Exception as e:
            return False, [], str(e)

    def chat(
        self,
        mensagens: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperatura: float = 0.1,
        max_tokens: int = 600,
        on_token: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Envia o pedido para o Ollama em modo STREAMING (stream=True).
        Vantagem técnica: Como os tokens chegam incrementalmente linha a linha (NDJSON),
        a ligação HTTP nunca sofre TimeoutError durante respostas longas em CPU/GPU local!
        """
        payload: Dict[str, Any] = {
            "model": self.modelo,
            "messages": mensagens,
            "stream": True,
            "options": {
                "temperature": temperatura,
                "num_ctx": 4096,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        corpo = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=corpo,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        conteudo_acumulado: List[str] = []
        tool_calls_acumuladas: List[Dict[str, Any]] = []
        papel_msg = "assistant"

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for linha_bytes in resp:
                    linha = linha_bytes.decode("utf-8", errors="replace").strip()
                    if not linha:
                        continue
                    try:
                        chunk = json.loads(linha)
                    except Exception:
                        continue

                    msg_chunk = chunk.get("message", {})
                    if msg_chunk.get("role"):
                        papel_msg = msg_chunk["role"]

                    pedaco_texto = msg_chunk.get("content") or ""
                    if pedaco_texto:
                        conteudo_acumulado.append(pedaco_texto)
                        if on_token:
                            on_token(1)

                    tc_chunk = msg_chunk.get("tool_calls")
                    if tc_chunk and isinstance(tc_chunk, list):
                        tool_calls_acumuladas.extend(tc_chunk)
                        if on_token:
                            on_token(1)

                    if chunk.get("done"):
                        break
        except (TimeoutError, urllib.error.URLError) as e:
            texto_parcial = "".join(conteudo_acumulado).strip()
            if texto_parcial or tool_calls_acumuladas:
                return {
                    "message": {
                        "role": papel_msg,
                        "content": texto_parcial,
                        "tool_calls": tool_calls_acumuladas,
                    }
                }
            return {
                "message": {
                    "role": "assistant",
                    "content": (
                        f"[Aviso: O servidor Ollama demorou demasiado tempo a responder ({e}). "
                        "Tenta novamente ou verifica se o modelo está carregado em memória.]"
                    ),
                }
            }

        msg_final: Dict[str, Any] = {
            "role": papel_msg,
            "content": "".join(conteudo_acumulado),
        }
        if tool_calls_acumuladas:
            msg_final["tool_calls"] = tool_calls_acumuladas

        return {"message": msg_final}


# =============================================================================
# 5. MOTOR DO AGENTE ReAct (RACIOCÍNIO + AÇÃO + OBSERVAÇÃO)
# =============================================================================

class MotorAgente:
    """
    Implementa o ciclo de vida pedagógico de um Agente:
    Perceção -> Pensamento (Reasoning) -> Ação (Tool Call) -> Observação -> Resposta.
    Suporta tanto Tool Calling nativo do Ollama como parsing híbrido de JSON para
    máxima fiabilidade em modelos compactos de 3B parâmetros (como ministral-3:3b).
    """

    def __init__(
        self,
        cliente: ClienteOllama,
        registo_tools: RegistoFerramentas,
        modo_passo_a_passo: bool = False,
        modo_raio_x: bool = False,
        mostrar_notas_pedagogicas: bool = True,
    ):
        self.cliente = cliente
        self.registo = registo_tools
        self.modo_passo_a_passo = modo_passo_a_passo
        self.modo_raio_x = modo_raio_x
        self.mostrar_notas = mostrar_notas_pedagogicas

    def _extrair_tool_calls_fallback(self, texto: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Caso um modelo pequeno escreva a chamada da ferramenta no texto em vez do campo
        nativo `tool_calls` (ex: bloco ```json ... ``` ou [TOOL_CALLS]), extrai-a de forma limpa.
        """
        chamadas = []
        pensamento_limpo = texto

        # 1. Formato Mistral [TOOL_CALLS] [{"name": "...", "arguments": {...}}]
        if "[TOOL_CALLS]" in texto:
            partes = texto.split("[TOOL_CALLS]", 1)
            pensamento_limpo = partes[0].strip()
            resto = partes[1].strip()
            try:
                arr = json.loads(resto)
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, dict) and "name" in item:
                            chamadas.append({
                                "function": {
                                    "name": item["name"],
                                    "arguments": item.get("arguments", {}),
                                }
                            })
                    if chamadas:
                        return pensamento_limpo, chamadas
            except Exception:
                pass

        # 2. Procura blocos JSON com {"name": ..., "arguments": ...} ou {"tool": ..., "args": ...}
        padrao_json = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
        matches = padrao_json.findall(texto)
        if not matches:
            # Tenta encontrar um objeto JSON isolado se contiver o nome de uma tool registada
            for nome_t in self.registo.ferramentas.keys():
                if nome_t in texto and "{" in texto and "}" in texto:
                    inicio = texto.find("{")
                    fim = texto.rfind("}")
                    if inicio != -1 and fim > inicio:
                        matches = [texto[inicio : fim + 1]]
                    break

        for candidato in matches:
            try:
                obj = json.loads(candidato)
                if isinstance(obj, dict):
                    nome = obj.get("name") or obj.get("tool") or obj.get("ferramenta")
                    args = (
                        obj.get("arguments")
                        or obj.get("args")
                        or obj.get("parametros")
                        or obj.get("parameters")
                        or {}
                    )
                    if nome in self.registo.ferramentas:
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        chamadas.append({"function": {"name": nome, "arguments": args}})
                        pensamento_limpo = texto.replace(candidato, "").replace("```json", "").replace("```", "").strip()
            except Exception:
                continue

        return pensamento_limpo, chamadas

    def executar_ciclo_react(
        self,
        nome_agente: str,
        papel_sistema: str,
        pergunta_utilizador: str,
        tools_permitidas: List[str],
        max_passos: int = 6,
    ) -> str:
        schemas = self.registo.obter_schemas_ollama(tools_permitidas)

        instrucao_react = (
            f"{papel_sistema}\n\n"
            "INSTRUÇÕES DE FUNCIONAMENTO (CICLO ReAct):\n"
            "1. Tens acesso a ferramentas reais ligadas ao sistema. NUNCA inventes dados, preços, IPs ou cálculos.\n"
            "2. Sempre que precisares de consultar dados ou executar uma ação, invoca a ferramenta adequada.\n"
            "3. Quando já tiveres todas as observações necessárias das ferramentas, responde SEMPRE em Português de Portugal (PT-PT) "
            "claro, estruturado e direto (usa termos como 'utilizador', 'ficheiro', 'equipa', 'stock', 'registo' e evita o gerúndio), "
            "com base EXCLUSIVAMENTE nos dados observados."
        )

        mensagens: List[Dict[str, Any]] = [
            {"role": "system", "content": instrucao_react},
            {"role": "user", "content": pergunta_utilizador},
        ]

        print(f"\n{Cor.BG_AZUL} 🤖 AGENTE ATIVO: {nome_agente} {Cor.RESET} {Cor.CINZA}(Modelo: {self.cliente.modelo}){Cor.RESET}")
        caixa(" TAREFA / OBJETIVO ENTREGUE AO AGENTE", pergunta_utilizador, cor_borda=Cor.AZUL, icone="🎯")

        ferramentas_usadas_historico = set()

        for passo in range(1, max_passos + 1):
            if self.modo_raio_x:
                caixa(
                    f"RAIO-X DO CONTEXTO (Passo {passo} - {len(mensagens)} mensagens na memória)",
                    json.dumps(mensagens[-2:], ensure_ascii=False, indent=2),
                    cor_borda=Cor.CINZA,
                    icone="🔬",
                )

            with Spinner(f"[{nome_agente}] Passo {passo}/{max_passos}: A analisar contexto e decidir ação...") as sp:
                resposta_raw = self.cliente.chat(
                    mensagens,
                    tools=schemas,
                    temperatura=0.1,
                    on_token=sp.registar_token,
                )

            msg = resposta_raw.get("message", {})
            conteudo_texto = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls and conteudo_texto:
                conteudo_texto, tool_calls = self._extrair_tool_calls_fallback(conteudo_texto)

            # Se o agente decidiu invocar ferramentas:
            if tool_calls:
                pensamento_visivel = conteudo_texto if conteudo_texto else (
                    "Preciso de invocar uma ferramenta externa para obter dados factuais ou agir no sistema "
                    "antes de formular a resposta."
                )
                caixa(
                    f"PASSO {passo} · PENSAMENTO / DECISÃO (REASONING)",
                    f"{Cor.MAGENTA}{pensamento_visivel}{Cor.RESET}",
                    cor_borda=Cor.MAGENTA,
                    icone="🧠",
                )

                # Regista a mensagem do assistente na memória da conversa
                mensagens.append(msg)

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    nome_tool = fn.get("name", "")
                    args_tool = fn.get("arguments", {})
                    if isinstance(args_tool, str):
                        try:
                            args_tool = json.loads(args_tool)
                        except Exception:
                            args_tool = {"consulta": args_tool}

                    assinatura_call = f"{nome_tool}:{json.dumps(args_tool, sort_keys=True)}"

                    caixa(
                        f"PASSO {passo} · AÇÃO (TOOL CALL) → {nome_tool}()",
                        f"{Cor.CIANO}Ferramenta:{Cor.RESET} {Cor.BOLD}{nome_tool}{Cor.RESET}\n"
                        f"{Cor.CIANO}Argumentos:{Cor.RESET} {json.dumps(args_tool, ensure_ascii=False)}",
                        cor_borda=Cor.CIANO,
                        icone="🔧",
                    )

                    if passo == 1 and self.mostrar_notas:
                        nota_pedagogica(
                            "O que é uma 'Tool Call' (Chamada de Ferramenta)?",
                            "Repara que o LLM NÃO executa código diretamente no seu cérebro neural! "
                            "Em vez disso, ele interrompe a geração de texto e emite um pedido estruturado JSON: "
                            f"«Quero chamar a função '{nome_tool}' com os argumentos {json.dumps(args_tool, ensure_ascii=False)}». "
                            "A nossa aplicação Python interceta esse pedido, executa o código real com segurança e devolve o resultado.",
                            ativo=self.mostrar_notas,
                        )

                    if self.modo_passo_a_passo:
                        input(
                            f"  {Cor.BG_AMARELO} ⏸ PAUSA PEDAGÓGICA {Cor.RESET} "
                            f"{Cor.AMARELO}Prime [ENTER] para autorizar a execução da ferramenta '{nome_tool}'...{Cor.RESET}"
                        )

                    resultado_tool = self.registo.executar(nome_tool, args_tool)

                    # Mostra a Observação obtida do ambiente
                    resumo_obs = resultado_tool
                    if len(resumo_obs) > 750 and not self.modo_raio_x:
                        resumo_obs = resumo_obs[:750] + "\n... [dados completos entregues à memória do Agente]"

                    caixa(
                        f"PASSO {passo} · OBSERVAÇÃO (DADOS REAIS DO AMBIENTE)",
                        f"{Cor.VERDE}{resumo_obs}{Cor.RESET}",
                        cor_borda=Cor.VERDE,
                        icone="📡",
                    )

                    # Devolve o resultado da ferramenta ao contexto do modelo
                    mensagens.append({
                        "role": "tool",
                        "content": resultado_tool,
                    })

                    # Proteção contra loops repetitivos em modelos pequenos
                    if assinatura_call in ferramentas_usadas_historico:
                        mensagens.append({
                            "role": "user",
                            "content": (
                                "Já executaste esta ferramenta e já tens os dados necessários acima. "
                                "Por favor, analisa os dados observados e apresenta agora a resposta final completa em Português de Portugal (PT-PT)."
                            ),
                        })
                    ferramentas_usadas_historico.add(assinatura_call)

                continue

            # Se não chamou ferramentas e produziu a resposta final:
            if conteudo_texto:
                caixa(
                    f"CONCLUSÃO DO AGENTE ({nome_agente}) APÓS {passo} PASSO(S)",
                    f"{Cor.BRANCO}{conteudo_texto}{Cor.RESET}",
                    cor_borda=Cor.VERDE,
                    icone="✅",
                )
                return conteudo_texto

        # Caso atinja o limite de passos, pede síntese final sem ferramentas
        with Spinner(f"[{nome_agente}] A sintetizar conclusão final com os dados recolhidos...") as sp:
            mensagens.append({
                "role": "user",
                "content": "Com base em todas as observações das ferramentas acima, escreve agora a resposta final detalhada em Português de Portugal (PT-PT).",
            })
            resp_final = self.cliente.chat(
                mensagens,
                tools=None,
                temperatura=0.1,
                on_token=sp.registar_token,
            )
            texto_final = resp_final.get("message", {}).get("content", "Não foi possível concluir.")

        caixa(
            f"CONCLUSÃO DO AGENTE ({nome_agente})",
            texto_final,
            cor_borda=Cor.VERDE,
            icone="✅",
        )
        return texto_final


# =============================================================================
# 6. CENÁRIOS PEDAGÓGICOS INTERATIVOS
# =============================================================================

def cenario_1_llm_vs_agente(
    cliente: ClienteOllama,
    motor: MotorAgente,
) -> None:
    """
    Demonstração 1: Comparação direta entre um LLM isolado e um Agente ReAct
    perante dados privados e cálculos exatos.
    """
    print("\n" + "═" * largura_terminal())
    print(f"{Cor.BG_MAGENTA} EXPERIÊNCIA 1: LLM ISOLADO vs. AGENTE COM FERRAMENTAS (GROUNDING) {Cor.RESET}")
    print("═" * largura_terminal())

    nota_pedagogica(
        "Porque é que um LLM sozinho falha em dados empresariais e contas?",
        "Um LLM tradicional é apenas um 'cérebro fechado numa sala sem janelas': só conhece o que "
        "aprendeu no treino e prevê a próxima palavra estatisticamente.\n"
        "Vamos fazer EXATAMENTE a mesma pergunta sobre a empresa 'LusitanaTech' primeiro ao modelo "
        "isolado (sem ferramentas) e depois a um Agente equipado com SQL e Calculadora.",
        ativo=True,
    )

    pergunta = (
        "Na loja LusitanaTech, qual é o cliente que mais dinheiro gastou no total das vendas, "
        "qual é o valor total exato gasto por esse cliente, qual o stock atual da 'Placa Neural Lusitana X90' "
        "e quanto fica o total gasto por esse cliente se lhe aplicarmos um desconto especial de 17.5%?"
    )

    # Parte A: LLM Isolado
    print(f"\n{Cor.BG_VERMELHO} PARTE A: LLM ISOLADO (Sem Ferramentas / Apenas Prompt Direto) {Cor.RESET}")
    caixa("PERGUNTA ENVIADA AO LLM ISOLADO", pergunta, cor_borda=Cor.VERMELHO, icone="❓")

    with Spinner(f"A perguntar ao {cliente.modelo} SEM ferramentas...") as sp:
        resp_isolado = cliente.chat(
            mensagens=[
                {
                    "role": "system",
                    "content": "Responde de forma curta em Português de Portugal (PT-PT) à pergunta do utilizador.",
                },
                {"role": "user", "content": pergunta},
            ],
            tools=None,
            temperatura=0.2,
            max_tokens=300,
            on_token=sp.registar_token,
        )
    texto_isolado = resp_isolado.get("message", {}).get("content", "")
    caixa(
        "RESPOSTA DO LLM ISOLADO (Sem acesso ao mundo exterior)",
        f"{Cor.VERMELHO}{texto_isolado}{Cor.RESET}",
        cor_borda=Cor.VERMELHO,
        icone="⚠️",
        rodape="Repara: O modelo ou admite que não tem acesso aos dados ou tenta adivinhar/alucinar!",
    )

    input(f"\n  {Cor.CIANO}👉 Prime [ENTER] para ver como o AGENTE ReAct resolve o mesmo problema...{Cor.RESET}")

    # Parte B: Agente com Ferramentas
    print(f"\n{Cor.BG_VERDE} PARTE B: AGENTE ReAct (Com acesso a SQL + Calculadora Precisa) {Cor.RESET}")
    papel = (
        "És o Agente Analista Financeiro da LusitanaTech. "
        "Primeiro usa a ferramenta 'consultar_loja_sql' (podes usar consulta='resumo_geral') para descobrir "
        "quem é o cliente que mais gastou, quanto gastou e qual o stock da Placa Neural Lusitana X90. "
        "Depois usa a ferramenta 'calculadora_precisa' para calcular o valor com 17.5% de desconto (ex: total * 0.825)."
    )

    motor.executar_ciclo_react(
        nome_agente="Agente Analista LusitanaTech",
        papel_sistema=papel,
        pergunta_utilizador=pergunta,
        tools_permitidas=["consultar_loja_sql", "calculadora_precisa"],
        max_passos=5,
    )

    nota_pedagogica(
        "Resumo da Vantagem #1 dos Agentes: Grounding (Ancoragem na Realidade)",
        "1. O LLM deixou de adivinhar: usou 'consultar_loja_sql' para descobrir que Inês Monteiro (BioLab Porto) "
        "gastou 7080.00 EUR (5800 + 1280) e que o stock da Placa Neural X90 é de 3 unidades.\n"
        "2. Em vez de fazer cálculo mental probabilístico, usou 'calculadora_precisa' (7080 * 0.825 = 5841.0 EUR).\n"
        "Isto chama-se 'Grounding': ligar o raciocínio linguístico a fontes de verdade determinísticas!",
        ativo=True,
    )


def cenario_2_detetive_cyber(
    motor: MotorAgente,
    mundo: MundoSimulado,
) -> None:
    """
    Demonstração 2: Investigação autónoma multi-passo (encadeamento de ferramentas)
    e capacidade de AGIR para alterar o estado do mundo (bloquear firewall).
    """
    print("\n" + "═" * largura_terminal())
    print(f"{Cor.BG_MAGENTA} EXPERIÊNCIA 2: DETETIVE CYBER-FORENSE (INVESTIGAÇÃO + AÇÃO ATIVA) {Cor.RESET}")
    print("═" * largura_terminal())

    nota_pedagogica(
        "Encadeamento Autónomo (Multi-Step) e Ação no Mundo",
        "Um verdadeiro Agente não faz apenas pesquisas: ele toma decisões sequenciais onde a "
        "Observação do Passo 1 determina o que investigar no Passo 2, e no fim executa uma AÇÃO "
        "que modifica o estado do sistema (neste caso, bloquear o intruso na Firewall).",
        ativo=True,
    )

    missao = (
        "Alerta de Segurança! Ocorreu uma anomalia no servidor esta madrugada por volta das 03:14. "
        "Segue estes passos:\n"
        "1. Lê os logs de segurança ('ler_logs_seguranca' com filtro_nivel='TODOS') para descobrir qual o IP suspeito e o que foi roubado.\n"
        "2. Investiga esse IP interno ('investigar_ip_interno') para descobrir a quem pertencia a credencial.\n"
        "3. Bloqueia imediatamente esse IP malicioso na firewall ('bloquear_ip_firewall') indicando o motivo.\n"
        "4. Apresenta um relatório forense completo do incidente."
    )

    papel = (
        "És o Agente de Resposta a Incidentes de Cibersegurança da LusitanaTech. "
        "Investiga os logs, identifica o IP responsável pelo ataque crítico, descobre a quem está associado esse IP "
        "e bloqueia-o na firewall antes de apresentares o teu relatório final."
    )

    motor.executar_ciclo_react(
        nome_agente="Agente Cyber-Sentinela",
        papel_sistema=papel,
        pergunta_utilizador=missao,
        tools_permitidas=["ler_logs_seguranca", "investigar_ip_interno", "bloquear_ip_firewall"],
        max_passos=6,
    )

    # Mostra prova real de que o estado do mundo foi alterado pelo Agente!
    if mundo.ips_bloqueados:
        caixa(
            "VERIFICAÇÃO DO ESTADO DO SISTEMA (MUNDO REAL ALTERADO PELO AGENTE!)",
            f"{Cor.VERDE}A Firewall da LusitanaTech tem agora as seguintes regras ativas criadas pelo Agente:{Cor.RESET}\n"
            + json.dumps(mundo.ips_bloqueados, ensure_ascii=False, indent=2),
            cor_borda=Cor.VERDE,
            icone="🛡️",
        )


def cenario_3_equipa_multi_agente(
    cliente: ClienteOllama,
    motor: MotorAgente,
) -> None:
    """
    Demonstração 3: Orquestração Multi-Agente (Especialização + Crítica/Reflexão).
    Agente 1 (Analista de Dados) -> Agente 2 (Auditor Cético / Crítico) -> Agente 3 (Estrategista).
    """
    print("\n" + "═" * largura_terminal())
    print(f"{Cor.BG_MAGENTA} EXPERIÊNCIA 3: EQUIPA MULTI-AGENTE (ESPECIALIZAÇÃO & REFLEXÃO) {Cor.RESET}")
    print("═" * largura_terminal())

    nota_pedagogica(
        "Porque usar VÁRIOS Agentes em vez de um só?",
        "Quando damos demasiadas instruções e ferramentas a um único agente, o seu contexto fica "
        "poluído e ele perde foco. Na arquitetura Multi-Agente dividimos o problema por especialistas:\n"
        "  • Agente 1 (Analista de Dados): Focado apenas em extrair factos e números da Base de Dados.\n"
        "  • Agente 2 (Auditor de Risco / Crítico): Tem uma persona cética; analisa os dados do Agente 1 "
        "e aponta vulnerabilidades (ex: ruturas de stock e riscos de segurança).\n"
        "  • Agente 3 (Diretor Executivo): Sintetiza o relatório do Analista e os alertas do Crítico num Plano de Ação.",
        ativo=True,
    )

    # --- AGENTE 1: ANALISTA DE DADOS ---
    print(f"\n{Cor.BG_CIANO} ETAPA 1/3 · AGENTE ANALISTA DE OPERAÇÕES (Extração de Factos) {Cor.RESET}")
    relatorio_analista = motor.executar_ciclo_react(
        nome_agente="Agente 1 · Analista de Dados",
        papel_sistema=(
            "És o Analista de Dados da LusitanaTech. Usa 'consultar_loja_sql' com 'resumo_geral' "
            "para levantar os números exatos de produtos, stocks atuais (especialmente produtos com stock 0 ou baixo) "
            "e o volume de vendas. Sê conciso (máximo 120 palavras)."
        ),
        pergunta_utilizador=(
            "Consulta a base de dados da loja ('resumo_geral') e lista em 3 tópicos curtos: "
            "1) Produtos com stock crítico (0 ou <= 3 unidades), "
            "2) Produto mais vendido em valor e 3) Receita total acumulada."
        ),
        tools_permitidas=["consultar_loja_sql", "calculadora_precisa"],
        max_passos=4,
    )

    # --- HANDOFF PARA AGENTE 2: AUDITOR CRÍTICO ---
    print(f"\n  {Cor.AMARELO}🔄 [HANDOFF MULTI-AGENTE] A transferir relatório do Agente 1 para o Agente 2 (Auditor de Risco)...{Cor.RESET}")
    print(f"\n{Cor.BG_AMARELO} ETAPA 2/3 · AGENTE AUDITOR DE RISCO & SEGURANÇA (Reflexão e Crítica) {Cor.RESET}")

    resumo_analista_curto = relatorio_analista[:800]
    relatorio_critico = motor.executar_ciclo_react(
        nome_agente="Agente 2 · Auditor de Risco",
        papel_sistema=(
            "És um Auditor de Risco rigoroso e cético. O teu trabalho é cruzar o relatório comercial "
            "com os logs de cibersegurança ('ler_logs_seguranca' com filtro_nivel='TODOS') e apontar os 3 maiores "
            "perigos imediatos para a empresa (ruturas de stock + brechas de segurança nos servidores). "
            "Sê direto e conciso (máximo 120 palavras)."
        ),
        pergunta_utilizador=(
            f"O Analista de Dados produziu este levantamento comercial:\n---\n{resumo_analista_curto}\n---\n"
            "Agora consulta os logs de segurança ('ler_logs_seguranca' com filtro_nivel='TODOS') e faz uma "
            "Crítica de Risco curta combinando os problemas de stock com o incidente de segurança detetado nos servidores."
        ),
        tools_permitidas=["ler_logs_seguranca"],
        max_passos=4,
    )

    # --- HANDOFF PARA AGENTE 3: DIRETOR ESTRATÉGICO ---
    print(f"\n  {Cor.VERDE}🔄 [HANDOFF MULTI-AGENTE] A transferir dados do Analista + Crítica do Auditor para o Agente 3 (CEO)...{Cor.RESET}")
    print(f"\n{Cor.BG_VERDE} ETAPA 3/3 · AGENTE DIRETOR EXECUTIVO (Síntese e Decisão Estratégica) {Cor.RESET}")

    resumo_critico_curto = relatorio_critico[:800]
    prompt_ceo = (
        f"RELATÓRIO DO AGENTE ANALISTA:\n{resumo_analista_curto}\n\n"
        f"PARECER DO AGENTE AUDITOR DE RISCO:\n{resumo_critico_curto}\n\n"
        "Com base no trabalho destes dois agentes, elabora um Plano Executivo conciso em 3 pontos prioritários:\n"
        "1. Reposição de Stock urgente;\n"
        "2. Fidelização da cliente VIP Inês Monteiro;\n"
        "3. Medidas imediatas de Cibersegurança."
    )

    with Spinner("[Agente 3 · Diretor Executivo] A sintetizar o Plano Estratégico Final...") as sp:
        resp_ceo = cliente.chat(
            mensagens=[
                {
                    "role": "system",
                    "content": (
                        "És o Agente Diretor Executivo (CEO) da LusitanaTech. Sintetizas os relatórios "
                        "dos teus agentes especialistas num plano executivo claro, conciso e acionável "
                        "em Português de Portugal (PT-PT, sem gerúndios e com vocabulário europeu)."
                    ),
                },
                {"role": "user", "content": prompt_ceo},
            ],
            tools=None,
            temperatura=0.2,
            max_tokens=450,
            on_token=sp.registar_token,
        )

    plano_final = resp_ceo.get("message", {}).get("content", "")
    caixa(
        "PLANO ESTRATÉGICO FINAL (SÍNTESE DA EQUIPA MULTI-AGENTE)",
        f"{Cor.BRANCO}{plano_final}{Cor.RESET}",
        cor_borda=Cor.VERDE,
        icone="🏆",
    )


def cenario_4_sandbox_interativo(
    motor: MotorAgente,
    mundo: MundoSimulado,
) -> None:
    """
    Modo 4: Laboratório Livre onde o utilizador pode fazer qualquer pergunta ou dar missões
    ao Agente com acesso a todas as ferramentas da LusitanaTech.
    """
    print("\n" + "═" * largura_terminal())
    print(f"{Cor.BG_CIANO} MODO 4: LABORATÓRIO LIVRE (CONVERSA COM O SUPER-AGENTE) {Cor.RESET}")
    print("═" * largura_terminal())

    sugestoes = (
        "Sugestões de perguntas para experimentares:\n"
        "  • «Qual é o produto mais caro da loja e quanto custam 7 unidades com 12% de desconto?»\n"
        "  • «Que produtos estão com stock zero e quem comprou esse produto anteriormente?»\n"
        "  • «Verifica nos logs se o utilizador pedro.costa fez algo suspeito e diz-me qual é o IP dele.»\n"
        "  • (Escreve 'sair' para voltar ao menu principal)"
    )
    caixa("COMO USAR O LABORATÓRIO LIVRE", sugestoes, cor_borda=Cor.CIANO, icone="🎮")

    todas_tools = list(motor.registo.ferramentas.keys())

    while True:
        try:
            pergunta = input(f"\n{Cor.CIANO}{Cor.BOLD}Tu > {Cor.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not pergunta or pergunta.lower() in ("sair", "exit", "voltar", "q"):
            break

        motor.executar_ciclo_react(
            nome_agente="Super-Agente LusitanaTech",
            papel_sistema=(
                "És o Super-Agente autónomo da LusitanaTech. Tens acesso à base de dados da loja "
                "('consultar_loja_sql'), calculadora ('calculadora_precisa'), logs ('ler_logs_seguranca'), "
                "diretório de IPs ('investigar_ip_interno') e firewall ('bloquear_ip_firewall'). "
                "Usa sempre as ferramentas antes de responder."
            ),
            pergunta_utilizador=pergunta,
            tools_permitidas=todas_tools,
            max_passos=5,
        )


def inspecionar_mundo_simulado(mundo: MundoSimulado) -> None:
    """Permite ao utilizador ver diretamente as tabelas SQLite e os logs que estão na memória."""
    print("\n" + "═" * largura_terminal())
    print(f"{Cor.BG_AZUL} 🗄️  INSPEÇÃO DIRETA DO AMBIENTE SIMULADO ('LUSITANATECH') {Cor.RESET}")
    print("═" * largura_terminal())

    cur = mundo.conn.cursor()
    cur.execute("SELECT * FROM produtos")
    produtos = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM vendas")
    vendas = [dict(r) for r in cur.fetchall()]

    caixa(
        "TABELA SQL: 'produtos'",
        json.dumps(produtos, ensure_ascii=False, indent=2),
        cor_borda=Cor.AZUL,
        icone="📦",
    )
    caixa(
        "TABELA SQL: 'vendas'",
        json.dumps(vendas, ensure_ascii=False, indent=2),
        cor_borda=Cor.AZUL,
        icone="💶",
    )
    caixa(
        "LOGS DO SERVIDOR & DIRETÓRIO DE IPs",
        json.dumps(
            {
                "logs_servidor": mundo.logs_servidor,
                "diretorio_ips": mundo.diretorio_ips,
                "firewall_ips_bloqueados_pelos_agentes": mundo.ips_bloqueados,
            },
            ensure_ascii=False,
            indent=2,
        ),
        cor_borda=Cor.CIANO,
        icone="🔐",
    )


# =============================================================================
# 7. MENU PRINCIPAL E ARRANQUE DA APLICAÇÃO
# =============================================================================

def mostrar_cabecalho(cliente: ClienteOllama, motor: MotorAgente, modelos_disp: List[str]) -> None:
    larg = largura_terminal()
    print("\n" + f"{Cor.CIANO}╔{'═' * (larg - 2)}╗{Cor.RESET}")
    titulo = "🤖 LABORATÓRIO PEDAGÓGICO DE AGENTES IA (Python + Ollama)"
    esp = max(0, larg - 4 - len(titulo))
    print(f"{Cor.CIANO}║{Cor.RESET} {Cor.BOLD}{Cor.BRANCO}{titulo}{Cor.RESET}{' ' * esp} {Cor.CIANO}║{Cor.RESET}")
    sub = "Aprende como os Agentes pensam (ReAct), usam Ferramentas e colaboram em Equipa"
    esp2 = max(0, larg - 4 - len(sub))
    print(f"{Cor.CIANO}║{Cor.RESET} {Cor.DIM}{sub}{Cor.RESET}{' ' * esp2} {Cor.CIANO}║{Cor.RESET}")
    print(f"{Cor.CIANO}╚{'═' * (larg - 2)}╝{Cor.RESET}")

    estado_pausa = f"{Cor.VERDE}ATIVO{Cor.RESET}" if motor.modo_passo_a_passo else f"{Cor.CINZA}OFF{Cor.RESET}"
    estado_raiox = f"{Cor.VERDE}ATIVO{Cor.RESET}" if motor.modo_raio_x else f"{Cor.CINZA}OFF{Cor.RESET}"
    estado_notas = f"{Cor.VERDE}ATIVO{Cor.RESET}" if motor.mostrar_notas else f"{Cor.CINZA}OFF{Cor.RESET}"

    print(
        f"  {Cor.BOLD}Modelo Ollama:{Cor.RESET} {Cor.CIANO}{cliente.modelo}{Cor.RESET}  │  "
        f"{Cor.BOLD}Passo-a-Passo [P]:{Cor.RESET} {estado_pausa}  │  "
        f"{Cor.BOLD}Raio-X JSON [X]:{Cor.RESET} {estado_raiox}  │  "
        f"{Cor.BOLD}Notas [N]:{Cor.RESET} {estado_notas}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Laboratório Pedagógico de Agentes IA com Ollama (Zero Dependências)"
    )
    parser.add_argument(
        "--modelo",
        default="ministral-3:3b",
        help="Nome do modelo no Ollama (por omissão: ministral-3:3b)",
    )
    parser.add_argument(
        "--host",
        default="http://localhost:11434",
        help="URL do servidor Ollama (por omissão: http://localhost:11434)",
    )
    parser.add_argument(
        "--modo",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="Executar diretamente um cenário (1=LLM vs Agente, 2=Detetive, 3=Multi-Agente, 4=Sandbox, 5=Ver Dados)",
    )
    parser.add_argument(
        "--passo-a-passo",
        action="store_true",
        help="Pausa antes de cada Tool Call para inspeção pedagógica",
    )
    parser.add_argument(
        "--raio-x",
        action="store_true",
        help="Mostra o JSON bruto de mensagens enviadas ao LLM em cada passo",
    )
    args = parser.parse_args()

    cliente = ClienteOllama(modelo=args.modelo, host=args.host)
    mundo = MundoSimulado()
    registo = RegistoFerramentas(mundo)
    motor = MotorAgente(
        cliente=cliente,
        registo_tools=registo,
        modo_passo_a_passo=args.passo_a_passo,
        modo_raio_x=args.raio_x,
        mostrar_notas_pedagogicas=True,
    )

    # Verifica ligação ao Ollama
    ok, modelos_disp, erro = cliente.verificar_ligacao()
    if not ok:
        caixa(
            "ERRO DE LIGAÇÃO AO OLLAMA LOCAL",
            f"Não foi possível contactar o servidor Ollama em {args.host}.\n"
            f"Detalhe: {erro}\n\n"
            "Certifica-te de que o Ollama está a correr no teu terminal:\n"
            "  $ ollama serve\n"
            "  $ ollama pull ministral-3:3b",
            cor_borda=Cor.VERMELHO,
            icone="🚨",
        )
        sys.exit(1)

    if modelos_disp and args.modelo not in modelos_disp:
        # Verifica se existe correspondência parcial
        similares = [m for m in modelos_disp if args.modelo.split(":")[0] in m]
        if similares:
            cliente.modelo = similares[0]
        else:
            caixa(
                "AVISO DE MODELO OLLAMA",
                f"O modelo '{args.modelo}' não foi encontrado na lista {modelos_disp}.\n"
                f"A usar '{modelos_disp[0]}' ou executa: ollama pull {args.modelo}",
                cor_borda=Cor.AMARELO,
                icone="⚠️",
            )
            cliente.modelo = modelos_disp[0]

    # Se foi passado --modo por linha de comandos, executa diretamente e sai
    if args.modo == 1:
        cenario_1_llm_vs_agente(cliente, motor)
        return
    elif args.modo == 2:
        cenario_2_detetive_cyber(motor, mundo)
        return
    elif args.modo == 3:
        cenario_3_equipa_multi_agente(cliente, motor)
        return
    elif args.modo == 4:
        cenario_4_sandbox_interativo(motor, mundo)
        return
    elif args.modo == 5:
        inspecionar_mundo_simulado(mundo)
        return

    # Loop Interativo Principal
    while True:
        mostrar_cabecalho(cliente, motor, modelos_disp)
        menu_texto = (
            f"{Cor.BOLD}{Cor.AMARELO}[1]{Cor.RESET} 🥊 {Cor.BOLD}LLM Isolado vs. Agente com Ferramentas{Cor.RESET}\n"
            f"    {Cor.DIM}Vê na prática porque um LLM sozinho alucina ou falha e como o Agente usa SQL + Calculadora.{Cor.RESET}\n\n"
            f"{Cor.BOLD}{Cor.AMARELO}[2]{Cor.RESET} 🕵️‍♂️ {Cor.BOLD}Detetive Cyber-Forense (Agente Autónomo Multi-Passo){Cor.RESET}\n"
            f"    {Cor.DIM}O Agente investiga logs de um ataque às 03:14h, cruza IPs de funcionários e bloqueia a Firewall!{Cor.RESET}\n\n"
            f"{Cor.BOLD}{Cor.AMARELO}[3]{Cor.RESET} 🤝 {Cor.BOLD}Equipa Multi-Agente (Analista → Auditor Crítico → CEO){Cor.RESET}\n"
            f"    {Cor.DIM}Três agentes com personas e ferramentas diferentes colaboram e reveem o trabalho uns dos outros.{Cor.RESET}\n\n"
            f"{Cor.BOLD}{Cor.AMARELO}[4]{Cor.RESET} 🎮 {Cor.BOLD}Laboratório Livre (Conversa com o Super-Agente){Cor.RESET}\n"
            f"    {Cor.DIM}Faz as tuas próprias perguntas e desafia o Agente a usar as ferramentas em tempo real.{Cor.RESET}\n\n"
            f"{Cor.BOLD}{Cor.AMARELO}[5]{Cor.RESET} 🗄️  {Cor.BOLD}Inspecionar Base de Dados & Logs Simulados ('LusitanaTech'){Cor.RESET}\n"
            f"    {Cor.DIM}Vê os dados reais em memória para comprovares que o Agente não inventa nada.{Cor.RESET}\n\n"
            f"{Cor.CINZA}────────────────────────────────────────────────────────────────────────────{Cor.RESET}\n"
            f"{Cor.BOLD}[P]{Cor.RESET} Alternar Modo Passo-a-Passo   "
            f"{Cor.BOLD}[X]{Cor.RESET} Alternar Raio-X do Prompt JSON   "
            f"{Cor.BOLD}[N]{Cor.RESET} Alternar Notas Pedagógicas   "
            f"{Cor.BOLD}[0]{Cor.RESET} Sair"
        )
        caixa("ESCOLHE UMA EXPERIÊNCIA PEDAGÓGICA", menu_texto, cor_borda=Cor.CIANO, icone="🧭")

        try:
            escolha = input(f"\n{Cor.CIANO}{Cor.BOLD}Opção > {Cor.RESET}").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Cor.VERDE}Até à próxima! Continua a explorar o mundo dos Agentes IA. 👋{Cor.RESET}")
            break

        if escolha == "1":
            cenario_1_llm_vs_agente(cliente, motor)
            input(f"\n{Cor.CINZA}[Prime ENTER para voltar ao menu principal]{Cor.RESET}")
        elif escolha == "2":
            cenario_2_detetive_cyber(motor, mundo)
            input(f"\n{Cor.CINZA}[Prime ENTER para voltar ao menu principal]{Cor.RESET}")
        elif escolha == "3":
            cenario_3_equipa_multi_agente(cliente, motor)
            input(f"\n{Cor.CINZA}[Prime ENTER para voltar ao menu principal]{Cor.RESET}")
        elif escolha == "4":
            cenario_4_sandbox_interativo(motor, mundo)
        elif escolha == "5":
            inspecionar_mundo_simulado(mundo)
            input(f"\n{Cor.CINZA}[Prime ENTER para voltar ao menu principal]{Cor.RESET}")
        elif escolha == "P":
            motor.modo_passo_a_passo = not motor.modo_passo_a_passo
        elif escolha == "X":
            motor.modo_raio_x = not motor.modo_raio_x
        elif escolha == "N":
            motor.mostrar_notas = not motor.mostrar_notas
        elif escolha in ("0", "Q", "SAIR", "EXIT"):
            print(f"\n{Cor.VERDE}Até à próxima! Continua a explorar o mundo dos Agentes IA. 👋{Cor.RESET}")
            break


if __name__ == "__main__":
    main()
