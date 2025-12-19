import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from .models import FlowConversation, FlowMessage, FlowMedia


# ======================================================================================
# EXECUÇÃO OFFLINE (SEM IA)
# ======================================================================================
# O motor percorre o grafo do FlowBot e gera respostas determinísticas.
#
# Formato esperado do flow_json:
# {
#   "version": 1,
#   "start_node_id": "n_start",
#   "nodes": {
#     "n_start": {"id":"n_start","type":"start","x":80,"y":80,"data": {...}},
#     "n_ask": {"id":"n_ask","type":"ask_input","x":300,"y":120,"data":{"prompt":"Qual seu nome?","var":"nome"}},
#     ...
#   },
#   "edges": [
#     {"id":"e1","from":"n_start","fromPort":"out","to":"n_ask","toPort":"in"},
#     {"id":"e2","from":"n_ask","fromPort":"next","to":"n_end","toPort":"in"}
#   ]
# }
#
# Convenção:
# - Inputs sempre toPort="in".
# - Outputs variam (out, next, yes, no, opt_1, opt_2, etc.)
# ======================================================================================


def _safe_text(x: Any) -> str:
    if x is None:
        return ""
    return str(x)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _match_condition(kind: str, left: str, right: str) -> bool:
    """Comparações simples e seguras."""
    left_n = _normalize(left)
    right_n = _normalize(right)

    if kind == "equals":
        return left_n == right_n
    if kind == "contains":
        return right_n in left_n
    if kind == "startswith":
        return left_n.startswith(right_n)
    if kind == "endswith":
        return left_n.endswith(right_n)
    if kind == "regex":
        try:
            return re.search(right, left, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return False


class FlowRuntimeError(Exception):
    pass


@dataclass
class BotOutput:
    """Saída para o front: texto/mídia e metadados."""
    type: str  # text|media|system
    text: str = ""
    media_id: Optional[int] = None
    delay_ms: int = 0


class FlowEngine:
    """Executa o fluxo para uma FlowConversation."""

    # Evita loop infinito caso o cliente crie ciclo no grafo
    MAX_STEPS_PER_TURN = 30

    def __init__(self, conversation: FlowConversation):
        self.conversation = conversation
        self.bot = conversation.bot
        self.flow = self.bot.flow_json or {}
        self.nodes: Dict[str, Dict[str, Any]] = (self.flow.get("nodes") or {})
        self.edges: List[Dict[str, Any]] = (self.flow.get("edges") or [])
        self.start_node_id: Optional[str] = self.flow.get("start_node_id")

        self._adj = self._build_adjacency()

    def _build_adjacency(self) -> Dict[Tuple[str, str], List[str]]:
        adj: Dict[Tuple[str, str], List[str]] = {}
        for e in self.edges:
            f = e.get("from")
            fp = e.get("fromPort") or "out"
            t = e.get("to")
            if not f or not t:
                continue
            adj.setdefault((f, fp), []).append(t)
        return adj

    def _next_node(self, node_id: str, out_port: str) -> Optional[str]:
        lst = self._adj.get((node_id, out_port), [])
        return lst[0] if lst else None

    def _get_state(self) -> Dict[str, Any]:
        st = self.conversation.state or {}
        st.setdefault("vars", {})
        return st

    def _set_state(self, st: Dict[str, Any]) -> None:
        self.conversation.state = st
        self.conversation.updated_at = timezone.now()
        self.conversation.save(update_fields=["state", "updated_at"])

    def _log(self, from_visitor: bool, message_type: str, text: str = "", media: Optional[FlowMedia] = None):
        FlowMessage.objects.create(
            conversation=self.conversation,
            from_visitor=from_visitor,
            message_type=message_type,
            text=text or "",
            media=media,
        )

    def _emit_text(self, text: str, delay_ms: int = 0) -> BotOutput:
        self._log(from_visitor=False, message_type="text", text=text)
        return BotOutput(type="text", text=text, delay_ms=delay_ms)

    def _emit_media(self, media_id: int, text: str = "", delay_ms: int = 0) -> BotOutput:
        m = FlowMedia.objects.filter(id=media_id, bot=self.bot).first()
        if not m:
            return self._emit_text("[ERRO] Mídia não encontrada.")
        # Log como media; texto opcional vai em text
        self._log(from_visitor=False, message_type="media", text=text or (m.caption or ""), media=m)
        return BotOutput(type="media", text=text or (m.caption or ""), media_id=m.id, delay_ms=delay_ms)

    def _render_template(self, template: str, vars: Dict[str, Any], last_user_text: str) -> str:
        """Template simples: {{var}} e {{last_user_text}}"""
        out = template or ""
        # last_user_text
        out = out.replace("{{last_user_text}}", last_user_text or "")
        # vars
        def repl(m):
            key = m.group(1).strip()
            return _safe_text(vars.get(key, ""))
        out = re.sub(r"\{\{\s*([a-zA-Z0-9_\-]+)\s*\}\}", repl, out)
        return out

    def _ensure_start(self, st: Dict[str, Any]) -> None:
        if st.get("current_node_id"):
            return
        start = self.start_node_id
        if not start:
            # tenta achar um node type=start
            for nid, nd in self.nodes.items():
                if nd.get("type") == "start":
                    start = nid
                    break
        if not start:
            raise FlowRuntimeError("Fluxo sem nó START. Crie um nó 'Start'.")
        st["current_node_id"] = start

    @transaction.atomic
    def handle_user_message(self, user_text: str) -> List[BotOutput]:
        """Processa uma mensagem do visitante e retorna lista de saídas do bot."""
        user_text = _safe_text(user_text).strip()
        self._log(from_visitor=True, message_type="text", text=user_text)

        st = self._get_state()
        st["last_user_text"] = user_text

        # Se estava aguardando resposta de um nó ask_input
        waiting = st.get("waiting")
        if waiting and waiting.get("type") == "ask_input":
            var = waiting.get("var") or "input"
            st["vars"][var] = user_text
            st["waiting"] = None
            # segue pelo output 'next' do nó
            nid = waiting.get("node_id")
            if nid:
                st["current_node_id"] = self._next_node(nid, "next") or self._next_node(nid, "out") or nid

        # Se ainda não tem start, inicializa
        self._ensure_start(st)

        outputs: List[BotOutput] = []
        steps = 0

        while steps < self.MAX_STEPS_PER_TURN:
            steps += 1
            nid = st.get("current_node_id")
            if not nid:
                break

            node = self.nodes.get(nid)
            if not node:
                outputs.append(self._emit_text(f"[ERRO] Nó '{nid}' não existe."))
                st["current_node_id"] = None
                break

            ntype = node.get("type")
            data = node.get("data") or {}
            vars = st.get("vars") or {}
            last_user = st.get("last_user_text") or ""

            # START: apenas passa adiante
            if ntype == "start":
                st["current_node_id"] = self._next_node(nid, "out") or self._next_node(nid, "next")
                continue

            # TEXT
            if ntype == "text":
                msg = self._render_template(_safe_text(data.get("text")), vars, last_user)
                delay = int(data.get("delay_ms") or 0)
                outputs.append(self._emit_text(msg, delay_ms=delay))
                st["current_node_id"] = self._next_node(nid, "out") or self._next_node(nid, "next")
                continue

            # MEDIA
            if ntype == "media":
                media_id = int(data.get("media_id") or 0)
                caption = self._render_template(_safe_text(data.get("caption")), vars, last_user)
                delay = int(data.get("delay_ms") or 0)
                outputs.append(self._emit_media(media_id, text=caption, delay_ms=delay))
                st["current_node_id"] = self._next_node(nid, "out") or self._next_node(nid, "next")
                continue

            # SET VAR
            if ntype == "set_var":
                k = _safe_text(data.get("key")).strip() or "var"
                v = self._render_template(_safe_text(data.get("value")), vars, last_user)
                st["vars"][k] = v
                st["current_node_id"] = self._next_node(nid, "out") or self._next_node(nid, "next")
                continue

            # ASK INPUT
            if ntype == "ask_input":
                prompt = self._render_template(_safe_text(data.get("prompt")), vars, last_user)
                var = _safe_text(data.get("var")).strip() or "input"
                outputs.append(self._emit_text(prompt))
                st["waiting"] = {"type": "ask_input", "node_id": nid, "var": var}
                # não avança até receber resposta
                break

            # CAPTURE CONTACT (nome/whatsapp)
            if ntype == "capture_contact":
                # modo: "name" ou "whatsapp" ou "both"
                mode = _safe_text(data.get("mode") or "both")
                # Se não tem nome, pergunta primeiro
                if mode in ("both", "name") and not self.conversation.visitor_name:
                    outputs.append(self._emit_text(self._render_template(_safe_text(data.get("ask_name") or "Qual seu nome?"), vars, last_user)))
                    st["waiting"] = {"type": "capture_name", "node_id": nid}
                    break
                if mode in ("both", "whatsapp") and not self.conversation.visitor_whatsapp:
                    outputs.append(self._emit_text(self._render_template(_safe_text(data.get("ask_whatsapp") or "Qual seu WhatsApp?"), vars, last_user)))
                    st["waiting"] = {"type": "capture_whatsapp", "node_id": nid}
                    break
                # já tem dados
                st["current_node_id"] = self._next_node(nid, "out") or self._next_node(nid, "next")
                continue

            # CONDITION
            if ntype == "condition":
                # cond: kind + compare source (last_user_text or var)
                source = _safe_text(data.get("source") or "last_user_text")
                left = last_user if source == "last_user_text" else _safe_text(vars.get(source, ""))
                kind = _safe_text(data.get("kind") or "contains")
                right = _safe_text(data.get("value") or "")
                yes_port = _safe_text(data.get("yes_port") or "yes")
                no_port = _safe_text(data.get("no_port") or "no")
                ok = _match_condition(kind, left, right)
                st["current_node_id"] = self._next_node(nid, yes_port if ok else no_port) or self._next_node(nid, "out")
                continue

            # MENU (opções fixas)
            if ntype == "menu":
                # data: prompt, options: [{"label":"1 - Orçamento","port":"opt_1"}, ...]
                prompt = self._render_template(_safe_text(data.get("prompt") or "Escolha uma opção:"), vars, last_user)
                options = data.get("options") or []
                lines = [prompt]
                for idx, opt in enumerate(options, start=1):
                    label = _safe_text(opt.get("label") or f"Opção {idx}")
                    lines.append(f"{idx}. {label}")
                outputs.append(self._emit_text("\n".join(lines)))
                st["waiting"] = {"type": "menu", "node_id": nid}
                break

            # END
            if ntype == "end":
                outputs.append(self._emit_text(_safe_text(data.get("text") or "Fim do atendimento.")))
                st["current_node_id"] = None
                break

            # Nó desconhecido
            outputs.append(self._emit_text(f"[ERRO] Tipo de nó desconhecido: {ntype}"))            
            st["current_node_id"] = None
            break

        # Tratamento de estados waiting adicionais (capture/menu)
        waiting2 = st.get("waiting")
        if waiting2:
            # capture_name
            if waiting2.get("type") == "capture_name":
                # guarda a resposta do usuário na próxima mensagem, então não faz aqui
                pass
            if waiting2.get("type") == "capture_whatsapp":
                pass

        self._set_state(st)
        return outputs

    @transaction.atomic
    def handle_waiting_reply(self, user_text: str) -> List[BotOutput]:
        """Quando o estado estiver aguardando menu/capture, resolve e continua."""
        user_text = _safe_text(user_text).strip()
        self._log(from_visitor=True, message_type="text", text=user_text)

        st = self._get_state()
        st["last_user_text"] = user_text

        waiting = st.get("waiting") or {}
        wtype = waiting.get("type")
        nid = waiting.get("node_id")

        if wtype == "capture_name":
            self.conversation.visitor_name = user_text
            self.conversation.save(update_fields=["visitor_name"])
            st["waiting"] = None
            st["current_node_id"] = self._next_node(nid, "next") or self._next_node(nid, "out") or nid
            self._set_state(st)
            return self.handle_user_message("")  # continua sem nova entrada

        if wtype == "capture_whatsapp":
            self.conversation.visitor_whatsapp = user_text
            self.conversation.save(update_fields=["visitor_whatsapp"])
            st["waiting"] = None
            st["current_node_id"] = self._next_node(nid, "next") or self._next_node(nid, "out") or nid
            self._set_state(st)
            return self.handle_user_message("")  # continua

        if wtype == "menu":
            node = self.nodes.get(nid) or {}
            data = node.get("data") or {}
            options = data.get("options") or []
            # escolhe por número (1..N) ou por label contains
            chosen_port = None
            m = re.match(r"^\s*(\d+)\s*$", user_text)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(options):
                    chosen_port = _safe_text(options[idx].get("port") or f"opt_{idx+1}")
            if not chosen_port:
                # tenta por texto
                for i, opt in enumerate(options, start=1):
                    label = _safe_text(opt.get("label"))
                    if label and _match_condition("contains", label, user_text) or _match_condition("contains", user_text, label):
                        chosen_port = _safe_text(opt.get("port") or f"opt_{i}")
                        break
            if not chosen_port:
                # repete menu
                st["waiting"] = {"type": "menu", "node_id": nid}
                self._set_state(st)
                return [self._emit_text("Não entendi. Responda com o número da opção.")]

            st["waiting"] = None
            st["current_node_id"] = self._next_node(nid, chosen_port) or self._next_node(nid, "out")
            self._set_state(st)
            return self.handle_user_message("")  # continua

        # fallback: fluxo normal
        self._set_state(st)
        return self.handle_user_message(user_text)
