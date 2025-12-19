/* FlowBot Builder (Adaptado)
   Integração completa com Django e Assets Unificados.
*/

(function(){
  const CFG = window.FLOWBOT;
  if(!CFG) {
    console.error("FLOWBOT config not found!");
    return;
  }

  // DOM Elements
  const paletteList = document.getElementById("paletteList");
  const canvas = document.getElementById("canvas");
  const nodesLayer = document.getElementById("nodesLayer");
  const wires = document.getElementById("wires");
  const propsBody = document.getElementById("propsBody");
  const selectedLabel = document.getElementById("selectedLabel");
  const btnDeleteNode = document.getElementById("btnDeleteNode");
  const btnSave = document.getElementById("btnSave");
  const btnZoomIn = document.getElementById("btnZoomIn");
  const btnZoomOut = document.getElementById("btnZoomOut");
  const btnCenter = document.getElementById("btnCenter");

  const btnStartChat = document.getElementById("btnStartChat");
  const btnSendChat = document.getElementById("btnSendChat");
  const btnResetChat = document.getElementById("btnResetChat");
  const chatLog = document.getElementById("chatLog");
  const chatText = document.getElementById("chatText");

  // State
  let flow = null;
  let mediaItems = [];
  let zoom = 1.0;
  let pan = {x: 0, y: 0};
  let selectedNodeId = null;

  // Connection state
  let linkDrag = null; // {fromNodeId, fromPort, svgPath, svgHit, startPt}
  let isPanning = false;
  let panStart = {x:0, y:0, px:0, py:0};

  // --- HELPERS ---
  function uid(prefix="n"){
    return prefix + "_" + Math.random().toString(16).slice(2, 10);
  }

  function getCSRFToken(){
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function apiGet(url){
    try {
        const r = await fetch(url, {credentials:"same-origin"});
        return await r.json();
    } catch(e) { console.error(e); return {}; }
  }

  async function apiPost(url, payload){
    try {
        const r = await fetch(url, {
          method:"POST",
          credentials:"same-origin",
          headers:{
            "Content-Type":"application/json",
            "X-CSRFToken": getCSRFToken()
          },
          body: JSON.stringify(payload || {})
        });
        return await r.json();
    } catch(e) { console.error(e); return {error: e.toString()}; }
  }

  // --- CANVAS CONTROL ---
  function setZoom(newZoom){
    zoom = Math.max(0.45, Math.min(1.8, newZoom));
    applyTransform();
    redrawAllWires();
  }

  function applyTransform(){
    // Aplica zoom e pan no layer de nós
    nodesLayer.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
    // O SVG (wires) precisa de um tratamento diferente se quisermos usar coordinates normais,
    // mas aqui vamos simplificar redesenhando os wires com as coordenadas transformadas? 
    // Não, melhor transformar o SVG também ou recalcular.
    // O wirePath usa coordenadas do cliente (DOM), então ele deve seguir visualmente.
    // Mas para o SVG ficar alinhado com o nodesLayer que tem transform CSS, 
    // precisamos que o SVG também tenha o transform ou calculamos a posição relativa.
    // A abordagem mais simples: Transformar o container SVG igual ao nodesLayer.
    wires.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
  }

  // Conversão de Coordenadas: Tela -> Mundo (dentro do zoom/pan)
  function clientToWorld(clientX, clientY){
    const rect = canvas.getBoundingClientRect();
    const x = (clientX - rect.left - pan.x) / zoom;
    const y = (clientY - rect.top - pan.y) / zoom;
    return {x,y};
  }

  // Resumo visual do nó (Mini texto)
  function nodeSummary(node){
    const t = node.type;
    const d = node.data || {};
    
    if(t === "text") return (d.text || "").slice(0, 50);
    if(t === "ask_input") return (d.prompt || "").slice(0, 50) + (d.var ? ` [${d.var}]` : "");
    if(t === "set_var") return `${d.key || "var"} = ${d.value || ""}`;
    if(t === "condition") return `${d.source||"var"} ${d.kind||"=="} ${d.value||""}`;
    if(t === "media") {
      const it = mediaItems.find(m => m.id == d.media_id);
      return it ? (it.title || `Arquivo #${it.id}`) : (d.media_id ? `ID #${d.media_id}` : "Nenhum arquivo");
    }
    if(t === "menu") {
      const opts = (d.options || []).map(o => o.label || "").filter(Boolean).slice(0,2).join(" | ");
      return (d.prompt || "Menu") + (opts ? "\n" + opts : "");
    }
    if(t === "capture_contact") return `Capturar: ${d.mode || "both"}`;
    if(t === "start") return "Início do Fluxo";
    if(t === "end") return d.text || "Fim";
    return "";
  }

  function clearEl(el){
    while(el.firstChild) el.removeChild(el.firstChild);
  }

  // --- PALETTE ---
  function buildPalette(){
    clearEl(paletteList);
    CFG.nodeLibrary.forEach(def => {
      const card = document.createElement("div");
      card.className = "fb-block";
      card.draggable = true;
      card.dataset.nodeType = def.type;

      const t = document.createElement("div");
      t.className = "fb-block-title";
      t.textContent = def.label;

      const h = document.createElement("div");
      h.className = "fb-block-help";
      h.textContent = def.help || "";

      card.appendChild(t);
      card.appendChild(h);

      card.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", def.type);
      });

      paletteList.appendChild(card);
    });
  }

  // --- RENDERING ---
  function renderAllNodes(){
    clearEl(nodesLayer);
    const nodes = flow.nodes || {};
    Object.values(nodes).forEach(n => {
      renderNode(n);
    });
    redrawAllWires();
  }

  function renderNode(node){
    const def = CFG.nodeLibrary.find(d => d.type === node.type);
    const nodeEl = document.createElement("div");
    nodeEl.className = "fb-node";
    if(selectedNodeId === node.id) nodeEl.classList.add("selected");
    
    nodeEl.dataset.nodeId = node.id;
    nodeEl.style.left = (node.x || 0) + "px";
    nodeEl.style.top = (node.y || 0) + "px";

    // Header
    const head = document.createElement("div");
    head.className = "fb-node-head";
    
    const title = document.createElement("div");
    title.className = "fb-node-title";
    title.textContent = def ? def.label : node.type;

    const type = document.createElement("div");
    type.className = "fb-node-type";
    type.textContent = node.type;
    
    // Start badge
    if(flow.start_node_id === node.id){
       type.textContent += " (START)";
       type.style.color = "#45f29c";
    }

    head.appendChild(title);
    head.appendChild(type);

    // Body
    const body = document.createElement("div");
    body.className = "fb-node-body";
    const mini = document.createElement("div");
    mini.className = "fb-mini";
    mini.textContent = nodeSummary(node) || "";
    body.appendChild(mini);

    // Ports
    const portsLeft = document.createElement("div");
    portsLeft.className = "fb-ports left";

    const portsRight = document.createElement("div");
    portsRight.className = "fb-ports right";

    const inputs = (def && def.inputs) ? def.inputs : [];
    const outputs = (def && def.outputs) ? def.outputs : [];
    
    // Se for menu, outputs podem vir dinâmicos das options
    let actualOutputs = outputs;
    if(node.type === "menu" && node.data.options && node.data.options.length > 0){
         // Menu tem outputs baseados nas opções + fallback
         // Mas aqui vamos simplificar e usar os outputs definidos nas opções
         // O def do menu já prevê "opt_1", "opt_2", etc.
         // Vamos renderizar apenas os que existem nas opções atuais
         const usedPorts = node.data.options.map(o => o.port);
         // Filtra outputs do def que estão em uso
         actualOutputs = outputs.filter(p => usedPorts.includes(p));
    }

    inputs.forEach(p => {
      const port = makePort(node.id, p, "in");
      portsLeft.appendChild(port.wrap);
    });

    actualOutputs.forEach(p => {
      const port = makePort(node.id, p, "out");
      portsRight.appendChild(port.wrap);
    });

    nodeEl.appendChild(head);
    nodeEl.appendChild(body);
    nodeEl.appendChild(portsLeft);
    nodeEl.appendChild(portsRight);

    // Interaction: Select
    nodeEl.addEventListener("mousedown", (e) => {
      if(e.target.classList.contains("fb-port")) return;
      selectNode(node.id);
    });

    // Interaction: Drag Node
    head.addEventListener("mousedown", (e) => {
      if(e.button !== 0) return;
      selectNode(node.id);
      
      // Posição inicial do mouse no mundo
      const startMouse = clientToWorld(e.clientX, e.clientY);
      const startNodeX = node.x || 0;
      const startNodeY = node.y || 0;

      const onMove = (ev) => {
        const currMouse = clientToWorld(ev.clientX, ev.clientY);
        const dx = currMouse.x - startMouse.x;
        const dy = currMouse.y - startMouse.y;
        
        node.x = Math.round(startNodeX + dx);
        node.y = Math.round(startNodeY + dy);
        
        nodeEl.style.left = node.x + "px";
        nodeEl.style.top = node.y + "px";
        redrawAllWires();
      };

      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };

      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });

    nodesLayer.appendChild(nodeEl);
  }

  function makePort(nodeId, portName, kind){
    const wrap = document.createElement("div");
    wrap.style.position = "relative";
    // wrap.style.pointerEvents = "none";

    const port = document.createElement("div");
    port.className = "fb-port";
    port.dataset.nodeId = nodeId;
    port.dataset.port = portName;
    port.dataset.kind = kind;
    // port.style.pointerEvents = "auto";

    const lbl = document.createElement("div");
    lbl.className = "fb-port-label";
    lbl.textContent = portName;

    wrap.appendChild(port);
    wrap.appendChild(lbl);

    // Wiring Logic
    port.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      e.preventDefault(); // Evita seleção de texto
      if(kind !== "out") return;
      
      // Centro da porta em coordenadas "Mundo" (relativas ao nodesLayer)
      const pt = getPortCenterWorld(port);
      startLinkDrag(nodeId, portName, pt);
    });

    port.addEventListener("mouseup", (e) => {
      e.stopPropagation();
      if(kind !== "in") return;
      if(!linkDrag) return;
      finishLinkDrag(nodeId, portName);
    });

    return {wrap, port, lbl};
  }

  // Pega centro da porta em coordenadas relativas ao nodesLayer (para SVG e Drag)
  function getPortCenterWorld(portEl){
     // Rect da porta na tela
     const r = portEl.getBoundingClientRect();
     // Rect do canvas na tela
     const cRect = canvas.getBoundingClientRect();
     
     // Centro da porta na tela
     const cxScreen = r.left + r.width/2;
     const cyScreen = r.top + r.height/2;

     // Converte para coordenadas dentro do container transformado (Zoom/Pan)
     // Fórmula: (ScreenCoord - CanvasOffset - Pan) / Zoom
     const x = (cxScreen - cRect.left - pan.x) / zoom;
     const y = (cyScreen - cRect.top - pan.y) / zoom;

     return {x, y};
  }

  // Desenha curva Bézier
  function wirePath(a, b){
    const dx = Math.abs(b.x - a.x) * 0.5;
    // Curvatura mínima e máxima para ficar bonito
    const curve = Math.max(40, Math.min(150, dx));
    
    const c1 = {x: a.x + curve, y: a.y};
    const c2 = {x: b.x - curve, y: b.y};
    
    return `M ${a.x} ${a.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${b.x} ${b.y}`;
  }

  function redrawAllWires(){
    clearEl(wires);
    const edges = flow.edges || [];
    
    // Renderiza edges existentes
    edges.forEach(edge => {
      const a = getNodePortCenter(edge.from, edge.fromPort, "out");
      const b = getNodePortCenter(edge.to, edge.toPort, "in");
      
      if(!a || !b) return; // Porta ou nó não existe mais visualmente

      // Fio visível
      const path = document.createElementNS("http://www.w3.org/2000/svg","path");
      path.setAttribute("d", wirePath(a, b));
      path.setAttribute("class","fb-wire");

      // Área de clique (mais grossa, invisível)
      const hit = document.createElementNS("http://www.w3.org/2000/svg","path");
      hit.setAttribute("d", wirePath(a, b));
      hit.setAttribute("class","fb-wire-hit");
      hit.addEventListener("click", () => {
         if(confirm("Remover esta conexão?")){
           flow.edges = flow.edges.filter(e => e.id !== edge.id);
           redrawAllWires();
         }
      });
      
      const g = document.createElementNS("http://www.w3.org/2000/svg","g");
      g.appendChild(path);
      g.appendChild(hit);
      wires.appendChild(g);
    });

    // Renderiza fio sendo arrastado (Temp)
    if(linkDrag && linkDrag.svgPath){
      wires.appendChild(linkDrag.svgPath);
    }
  }

  function getNodeEl(nodeId){
    return nodesLayer.querySelector(`.fb-node[data-node-id="${nodeId}"]`);
  }

  function getNodePortCenter(nodeId, portName, kind){
    const nodeEl = getNodeEl(nodeId);
    if(!nodeEl) return null;
    const port = nodeEl.querySelector(`.fb-port[data-kind="${kind}"][data-port="${portName}"]`);
    if(!port) return null;
    return getPortCenterWorld(port);
  }

  function startLinkDrag(fromNodeId, fromPort, startPt){
    // Cria elemento temporário no SVG
    const temp = document.createElementNS("http://www.w3.org/2000/svg","path");
    temp.setAttribute("class","fb-wire temp");
    temp.setAttribute("d", wirePath(startPt, startPt)); // Ponto a Ponto inicial

    linkDrag = {fromNodeId, fromPort, startPt, svgPath: temp};
    wires.appendChild(temp); // Adiciona ao DOM para ser visível

    const onMove = (e) => {
      if(!linkDrag) return;
      // Mouse atual em coordenadas mundo
      const mouseWorld = clientToWorld(e.clientX, e.clientY);
      linkDrag.svgPath.setAttribute("d", wirePath(linkDrag.startPt, mouseWorld));
    };

    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      // Cancelou arraste (soltou no nada)
      if(linkDrag){
        if(linkDrag.svgPath.parentNode) linkDrag.svgPath.parentNode.removeChild(linkDrag.svgPath);
        linkDrag = null;
      }
    };
    
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  function finishLinkDrag(toNodeId, toPort){
    const from = linkDrag.fromNodeId;
    const fromPort = linkDrag.fromPort;
    
    // Não permite auto-conexão
    if(from === toNodeId){
      cancelLinkDrag(); return;
    }

    // Regra: Apenas 1 conexão saindo de cada porta? 
    // Em fluxos complexos, às vezes permite bifurcação, mas para chatbot geralmente é 1 caminho.
    // Vamos substituir se já existir.
    flow.edges = (flow.edges || []).filter(e => !(e.from === from && e.fromPort === fromPort));

    flow.edges.push({
      id: uid("e"),
      from,
      fromPort,
      to: toNodeId,
      toPort: "in" // Assumindo que inputs sempre se chamam "in"
    });

    cancelLinkDrag();
    redrawAllWires();
  }

  function cancelLinkDrag(){
    if(linkDrag && linkDrag.svgPath && linkDrag.svgPath.parentNode){
        linkDrag.svgPath.parentNode.removeChild(linkDrag.svgPath);
    }
    linkDrag = null;
  }

  // --- SELECTION & PROPS ---
  function selectNode(nodeId){
    selectedNodeId = nodeId;
    // Atualiza classes visuais
    const all = nodesLayer.querySelectorAll(".fb-node");
    all.forEach(el => el.classList.remove("selected"));
    
    const el = getNodeEl(nodeId);
    if(el) el.classList.add("selected");
    
    btnDeleteNode.disabled = !nodeId;
    buildPropsPanel();
  }

  function buildPropsPanel(){
    clearEl(propsBody);
    const node = (flow.nodes || {})[selectedNodeId];
    
    if(!node){
      selectedLabel.textContent = "Propriedades";
      propsBody.innerHTML = `<div class="fb-muted" style="text-align:center; margin-top:20px">Selecione um bloco no canvas para editar suas opções.</div>`;
      btnDeleteNode.disabled = true;
      return;
    }
    
    const def = CFG.nodeLibrary.find(d => d.type === node.type);
    selectedLabel.textContent = (def ? def.label : node.type);

    // Campo Start
    const startWrap = document.createElement("div");
    startWrap.className = "fb-prop";
    startWrap.style.borderColor = (flow.start_node_id === node.id) ? "#45f29c" : "";
    const isStart = (flow.start_node_id === node.id);
    
    startWrap.innerHTML = `
        <label style="color:${isStart ? '#45f29c' : ''}">Ponto de Partida</label>
        <button class="fb-btn ${isStart ? 'fb-btn-primary' : 'fb-btn-secondary'}" style="width:100%" id="btnSetStart">
            ${isStart ? '<i class="fas fa-flag-checkered"></i> É o Início' : 'Definir como Início'}
        </button>
    `;
    startWrap.querySelector("#btnSetStart").onclick = () => {
        flow.start_node_id = node.id;
        renderAllNodes(); // Para atualizar o badge visual
        buildPropsPanel();
    };
    propsBody.appendChild(startWrap);

    // Fields dinâmicos
    const fields = (def && def.fields) ? def.fields : [];
    fields.forEach(f => {
      propsBody.appendChild(propEditor(node, f));
    });

    // ID info (no final)
    const idInfo = document.createElement("div");
    idInfo.className = "fb-muted";
    idInfo.style.fontSize = "0.7rem";
    idInfo.style.marginTop = "20px";
    idInfo.textContent = `Node ID: ${node.id}`;
    propsBody.appendChild(idInfo);
  }

  function propEditor(node, field){
    const wrap = document.createElement("div");
    wrap.className = "fb-prop";
    const lab = document.createElement("label");
    lab.textContent = field.label || field.key;
    wrap.appendChild(lab);

    node.data = node.data || {};
    const k = field.key;
    let el = null;

    if(field.kind === "textarea"){
      el = document.createElement("textarea");
      el.value = node.data[k] || "";
    } else if(field.kind === "select"){
      el = document.createElement("select");
      (field.choices || []).forEach(opt => {
        const o = document.createElement("option");
        o.value = opt; o.textContent = opt;
        el.appendChild(o);
      });
      el.value = node.data[k] || (field.choices && field.choices[0]) || "";
    } else if(field.kind === "media_select"){
      el = document.createElement("select");
      const empty = document.createElement("option");
      empty.value = ""; empty.textContent = "— Selecione —";
      el.appendChild(empty);
      mediaItems.forEach(m => {
        const o = document.createElement("option");
        o.value = m.id;
        o.textContent = m.description || m.file_name || `Mídia #${m.id}`; // Ajuste conforme seu objeto de mídia
        el.appendChild(o);
      });
      el.value = node.data[k] || "";
    } else if(field.kind === "options_multiline"){
      el = document.createElement("textarea");
      el.placeholder = "Opção 1\nOpção 2...";
      // Converte array de objetos em texto multiline
      const opts = (node.data.options || []).map(o => o.label).join("\n");
      el.value = opts;
    } else {
      el = document.createElement("input");
      el.type = "text";
      el.value = node.data[k] || "";
    }

    if(field.placeholder) el.placeholder = field.placeholder;

    // Evento de Save
    el.addEventListener("input", () => {
      if(field.kind === "options_multiline"){
        const lines = el.value.split("\n").map(s => s.trim()).filter(Boolean);
        // Recria as opções e portas
        node.data.options = lines.map((label, idx) => ({
            label: label,
            port: `opt_${idx+1}` // Gera portas opt_1, opt_2, etc.
        }));
        // Como isso altera portas, precisa redesenhar o nó
        renderNodeUpdate(node.id);
      } else if(field.kind === "media_select"){
         node.data[k] = el.value;
      } else {
         node.data[k] = el.value;
      }
      
      // Atualiza o resumo visual (texto mini no corpo do nó)
      updateNodeMini(node);
    });

    wrap.appendChild(el);
    if(field.help){
        const h = document.createElement("div");
        h.className = "hint";
        h.textContent = field.help;
        wrap.appendChild(h);
    }
    return wrap;
  }

  function updateNodeMini(node){
      const nodeEl = getNodeEl(node.id);
      if(nodeEl){
          const mini = nodeEl.querySelector(".fb-mini");
          if(mini) mini.textContent = nodeSummary(node);
      }
  }

  function renderNodeUpdate(nodeId){
      // Redesenha completamente o nó (útil para menu que muda portas)
      const oldEl = getNodeEl(nodeId);
      if(oldEl){
          // Precisamos manter a posição, mas renderNode já usa node.x/y
          // Apenas removemos e criamos de novo
          nodesLayer.removeChild(oldEl);
          // Re-renderiza
          renderNode(flow.nodes[nodeId]);
          // Re-seleciona visualmente
          selectNode(nodeId);
          // Redesenha fios (pois posições das portas podem ter mudado)
          redrawAllWires();
      }
  }

  // --- DND FROM PALETTE ---
  canvas.addEventListener("dragover", (e) => e.preventDefault());
  canvas.addEventListener("drop", (e) => {
    e.preventDefault();
    const type = e.dataTransfer.getData("text/plain");
    if(!type) return;
    
    const pt = clientToWorld(e.clientX, e.clientY);
    const id = uid("n");
    const data = {};

    // Defaults inteligentes
    if(type === "text") data.text = "Nova mensagem...";
    if(type === "ask_input") { data.prompt = "Digite sua resposta:"; data.var = "resposta_usuario"; }
    if(type === "menu") { data.prompt = "Selecione:"; data.options = [{label:"Sim", port:"opt_1"}, {label:"Não", port:"opt_2"}]; }
    
    flow.nodes[id] = {id, type, x: Math.round(pt.x), y: Math.round(pt.y), data};
    
    renderNode(flow.nodes[id]);
    selectNode(id);
  });

  // --- PANNING ---
  canvas.addEventListener("mousedown", (e) => {
    // Botão do meio (1) ou Space+Click
    if(e.button === 1 || (e.button===0 && e.shiftKey)){
      isPanning = true;
      panStart = {x: e.clientX, y: e.clientY, px: pan.x, py: pan.y};
      canvas.style.cursor = "grabbing";
      e.preventDefault();
    }
  });

  window.addEventListener("mousemove", (e) => {
    if(!isPanning) return;
    const dx = e.clientX - panStart.x;
    const dy = e.clientY - panStart.y;
    pan.x = panStart.px + dx;
    pan.y = panStart.py + dy;
    applyTransform();
  });

  window.addEventListener("mouseup", () => {
    if(isPanning){
        isPanning = false;
        canvas.style.cursor = "default";
    }
  });

  // --- ACTIONS ---
  btnZoomIn.onclick = () => setZoom(zoom + 0.1);
  btnZoomOut.onclick = () => setZoom(zoom - 0.1);
  btnCenter.onclick = () => { pan = {x:0, y:0}; setZoom(1.0); };

  btnDeleteNode.onclick = () => {
      if(!selectedNodeId) return;
      if(!confirm("Tem certeza que deseja excluir este nó?")) return;
      
      const nid = selectedNodeId;
      delete flow.nodes[nid];
      // Remove conexões ligadas a ele
      flow.edges = flow.edges.filter(e => e.from !== nid && e.to !== nid);
      
      if(flow.start_node_id === nid) flow.start_node_id = null;
      
      selectedNodeId = null;
      renderAllNodes();
      buildPropsPanel();
  };

  btnSave.onclick = async () => {
      const originalText = btnSave.innerHTML;
      btnSave.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Salvando...';
      btnSave.disabled = true;

      if(!flow.start_node_id){
          alert("ERRO: Você precisa definir um nó como INÍCIO (Start). Selecione um nó e marque a opção nas propriedades.");
          btnSave.innerHTML = originalText;
          btnSave.disabled = false;
          return;
      }

      const res = await apiPost(CFG.urls.saveFlow, {flow});
      if(res.ok || res.success){
          toast("Fluxo salvo com sucesso! ✅");
      } else {
          alert("Erro ao salvar: " + (res.error || "Desconhecido"));
      }
      btnSave.innerHTML = originalText;
      btnSave.disabled = false;
  };

  // --- CHAT SIMULATOR ---
  function addChatBubble(role, text, mediaUrl){
    const el = document.createElement("div");
    el.className = "fb-msg " + (role === "user" ? "user" : "bot");
    
    if(mediaUrl){
        el.innerHTML = `<a href="${mediaUrl}" target="_blank" style="color:inherit; text-decoration:underline"><i class="fas fa-paperclip"></i> Ver Arquivo</a><br>${text || ''}`;
    } else {
        el.textContent = text || "...";
    }
    
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    el.appendChild(meta);
    
    chatLog.appendChild(el);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  async function chatStart(){
      clearEl(chatLog);
      addChatBubble("bot", "Iniciando simulador...");
      const res = await apiGet(CFG.urls.chatStart);
      if(res.outputs){
          res.outputs.forEach(o => processBotOutput(o));
      }
  }

  async function chatSend(){
      const txt = chatText.value.trim();
      if(!txt) return;
      addChatBubble("user", txt);
      chatText.value = "";
      
      const res = await apiPost(CFG.urls.chatSend, {text: txt});
      if(res.outputs){
          res.outputs.forEach(o => processBotOutput(o));
      }
  }

  function processBotOutput(o){
      if(o.type === 'text'){
          addChatBubble("bot", o.text);
      } else if(o.type === 'media'){
          // Tenta achar url da media na lista local
          const m = mediaItems.find(x => x.id == o.media_id);
          addChatBubble("bot", o.text, m ? m.file_url : "#");
      }
  }

  btnStartChat.onclick = chatStart;
  btnSendChat.onclick = chatSend;
  chatText.onkeydown = (e) => { if(e.key==="Enter") chatSend(); };
  btnResetChat.onclick = async () => {
      clearEl(chatLog);
      await apiPost(CFG.urls.chatReset);
      toast("Chat limpo.");
  };

  function toast(msg){
      const t = document.createElement("div");
      t.style.cssText = "position:fixed; bottom:20px; right:20px; background:rgba(0,0,0,0.8); color:#fff; padding:10px 20px; border-radius:30px; z-index:9999; border:1px solid #45f29c;";
      t.innerHTML = `<i class="fas fa-info-circle"></i> ${msg}`;
      document.body.appendChild(t);
      setTimeout(()=>t.remove(), 3000);
  }

  // --- INIT ---
  async function init(){
    console.log("Iniciando FlowBuilder...");
    buildPalette();

    // Carrega dados
    try {
        const [flowRes, mediaRes] = await Promise.all([
          apiGet(CFG.urls.getFlow),
          apiGet(CFG.urls.mediaList)
        ]);

        flow = (flowRes && flowRes.flow) ? flowRes.flow : {nodes:{}, edges:[], start_node_id: null};
        // Garante integridade
        if(!flow.nodes) flow.nodes = {};
        if(!flow.edges) flow.edges = [];

        mediaItems = (mediaRes && mediaRes.items) ? mediaRes.items : [];
        
        renderAllNodes();
        
        // Auto center se tiver nós
        if(Object.keys(flow.nodes).length > 0){
             // Poderia calcular bounding box, mas vamos resetar pro centro por enquanto
             pan = {x: 50, y: 50};
             applyTransform();
        }

    } catch(e){
        console.error("Erro ao carregar dados:", e);
        alert("Erro ao carregar fluxo. Verifique o console.");
    }
  }

  init();

})();