import { useState, useEffect, useRef, useCallback, useMemo } from "react"

const API = import.meta.env.VITE_API_URL || "http://localhost:8000"

const NODE_COLORS = {
  HospitalNetwork:   "#1D9E75",
  PharmaCompany:     "#7F77DD",
  RegulatorAgency:   "#378ADD",
  RegionalAuthority: "#D85A30",
  ProcurementBody:   "#BA7517",
  ResearchInstitute: "#5A9E8A",
  PrivateGroup:      "#A32D2D",
  InsuranceBody:     "#888780",
  Person:            "#D4537E",
}

const SEVERITY_COLOR = {
  CRITICAL: "#E24B4A",
  HIGH:     "#EF9F27",
  MEDIUM:   "#378ADD",
  LOW:      "#1D9E75",
}

// Le date dal backend sono in UTC senza fuso: si aggiunge la Z prima di convertirle
function formatDateTime(iso) {
  if (!iso) return ""
  const d = new Date(iso + (/(Z|[+-]\d\d:\d\d)$/.test(iso) ? "" : "Z"))
  return d.toLocaleDateString("it-IT", {day:"numeric", month:"long", year:"numeric"}) +
    " alle " + d.toLocaleTimeString("it-IT", {hour:"2-digit", minute:"2-digit"})
}

const zoomBtn = {width:34,height:34,border:"0.5px solid var(--color-border-tertiary)",borderRadius:4,background:"var(--color-background-secondary)",cursor:"pointer",fontSize:18,lineHeight:"30px"}

// Tipo di relazione in italiano, dal punto di vista del nodo selezionato
const REL_LABEL = {
  FORNISCE:      ["fornisce", "riceve forniture da"],
  CONTROLLA:     ["controlla", "è controllato da"],
  FINANZIA:      ["finanzia", "è finanziato da"],
  ACCREDITA:     ["accredita", "è accreditato da"],
  COLLABORA_CON: ["collabora con", "collabora con"],
  COMUNICA_SU:   ["pubblica atti o comunicati che riguardano", "è citato in atti o comunicati di"],
  RISCHIO_PER:   ["è un fattore di rischio per", "è esposto a un rischio da"],
  MEMBRO_DI:     ["fa parte di", "comprende"],
  REGOLA:        ["regola", "è regolato da"],
  VINCE_APPALTO: ["vince appalti di", "assegna appalti a"],
  INDAGA_SU:     ["indaga su", "è oggetto di indagine da"],
}

const NODE_TYPE_LABEL = {
  HospitalNetwork: "Azienda sanitaria o ospedaliera", PharmaCompany: "Azienda farmaceutica o di dispositivi",
  RegulatorAgency: "Ente regolatore", RegionalAuthority: "Regione o autorità sanitaria territoriale", ProcurementBody: "Centrale acquisti / associazione",
  ResearchInstitute: "Istituto di ricerca", PrivateGroup: "Gruppo sanitario privato", InsuranceBody: "Fondo / assicurazione",
  Person: "Persona", EpidemicEvent: "Evento epidemico",
}
// Tipi senza colore dedicato (eventi e minacce sanitarie estratti dalle notizie)
const OTHER_COLOR = "#888780"
const OTHER_LABEL = "Evento o minaccia sanitaria"

// Layout a forze (stesso schema di d3-force): repulsione tra i nodi, molle sulle relazioni,
// gravità debole verso il centro e collisione tra nodi. Nessun limite rigido ai bordi:
// è la vista ("Adatta") a inquadrare il grafo, qualunque sia la sua estensione.
const SIM = {
  charge: -110, chargeMax: 420,   // repulsione e distanza oltre cui non agisce
  linkDist: 55,                   // lunghezza a riposo delle relazioni
  gravity: 0.07,                  // richiamo verso il centro (tiene vicini i nodi isolati)
  collidePad: 7,                  // spazio minimo tra i bordi di due nodi
  velocityDecay: 0.4, alphaDecay: 0.0228, alphaMin: 0.002,
}
// Etichette sempre visibili: rischio alto (anello, > 60) o nodi con molte relazioni.
// Le altre compaiono al passaggio del mouse, con la selezione o ingrandendo.
const LABEL_RISK = 60, LABEL_HUB_DEGREE = 8, LABEL_ZOOM = 1.6, LABEL_MAX = 30

function nodeRadius(n) { return Math.max(7, Math.min(12, (n.risk_score || 0) / 10)) }

function shortLabel(s) { return s.length > LABEL_MAX ? s.slice(0, LABEL_MAX - 1).trimEnd() + "…" : s }

const NO_SOURCE = "Fonte da verificare"

function formatDay(d) {
  if (!d) return ""
  const m = String(d).match(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/)
  if (!m) return String(d)
  return m[3] ? `${m[3]}/${m[2]}/${m[1]}` : `${m[2]}/${m[1]}`
}

// Fonte di un documento citato da una relazione: richiamo FDA o notizia OMS, con link e data.
// donIndex: notizie OMS scaricate (id DON -> titolo e data di pubblicazione)
function docOrigin(doc, r, donIndex = {}) {
  const recall = /^[DZ]-\d+-\d+$/.test(doc) ? doc : (r.id || "").startsWith("recall_") ? r.id.slice(7) : null
  if (recall) {
    const kind = recall.startsWith("Z-") ? "device" : "drug"
    return {kind: "fda", recall, date: r.date, label: `Richiamo FDA ${recall} (openFDA)`,
      url: `https://api.fda.gov/${kind}/enforcement.json?search=recall_number:%22${encodeURIComponent(recall)}%22`}
  }
  // Notizie OMS: id "2026-DON599" oppure, per le più vecchie, il nome della pagina
  if (/^\d{4}-DON\d+$/.test(doc) || /^[a-z0-9]+(-[a-z0-9]+){3,}$/.test(doc)) {
    const don = donIndex[doc]
    return {kind: "who", doc, date: don?.date || r.date, published: !!don?.date,
      label: don?.title ? `OMS – ${don.title}` : `OMS – Disease Outbreak News ${doc}`,
      url: `https://www.who.int/emergencies/disease-outbreak-news/item/${doc}`}
  }
  if (/^https?:\/\//.test(doc)) {
    const title = r.doc_titles?.[doc]
    return {kind: "web", url: doc, date: r.date,
      published: true, label: title || new URL(doc).hostname}
  }
  return {kind: "manual"}
}

// Tutte le fonti di una relazione: dopo l'accorpamento dei doppioni possono essere più d'una
function relationSources(r, donIndex) {
  const docs = [...new Set([r.source_doc, ...(r.source_docs || [])].filter(Boolean))]
  if (!docs.length && (r.id || "").startsWith("recall_")) docs.push(r.id.slice(7))
  return docs.map(d => docOrigin(d, r, donIndex)).filter(o => o.kind !== "manual")
}

// Fonte principale (tipo e link) di una relazione
function relationOrigin(r, donIndex = {}) {
  return relationSources(r, donIndex)[0] || {kind: "manual"}
}

// Fonti di un nodo, ricavate dai dati che lo hanno generato:
// - azienda con richiamo FDA: i suoi richiami;
// - entità estratta dall'AI dalle notizie OMS: le notizie delle sue relazioni;
// - enti di base inseriti a mano e nodi senza relazioni: nessuna fonte.
// - enti del nucleo fisso italiano: il sito istituzionale.
function nodeOrigin(node, relations, donIndex) {
  const basis = node?.risk_basis || ""
  const kind = basis.startsWith("Richiamo FDA") ? "fda" : basis.startsWith("Stima dell'AI") ? "who"
    : basis.startsWith("Ente del nucleo") ? "nucleus" : "manual"
  const site = node?.website ? [{kind: "site", url: node.website, label: `Sito istituzionale – ${node.full_name || node.label}`}] : []
  if (kind === "manual" || kind === "nucleus") return {kind, sources: site}
  const seen = new Map()
  relations.forEach(r => relationSources(r, donIndex).forEach(o => {
    const ok = kind === "fda" ? o.kind === "fda" && r.source === node.id : (o.kind === "who" || o.kind === "web") && r.type !== "COMUNICA_SU"
    if (ok && !seen.has(o.url)) seen.set(o.url, o)
  }))
  const sources = [...seen.values()].sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")))
  return {kind, sources: [...site, ...sources]}
}

function SourceLinks({sources}) {
  if (!sources.length) return <span style={{color:"#A32D2D",fontWeight:500}}>{NO_SOURCE}</span>
  return sources.map(s => (
    <div key={s.url} style={{marginTop:2}}>
      <a href={s.url} target="_blank" rel="noopener noreferrer" style={{color:"#0F6E56"}}>{s.label}</a>
      {s.date && <span> · {s.kind === "fda" ? "richiamo del " : s.published ? "pubblicato il " : "data: "}{formatDay(s.date)}</span>}
    </div>
  ))
}

// "[Class II] Z-3233-2026: motivo" -> classe e motivo leggibili
function parseRecallFact(fact) {
  const m = String(fact || "").match(/^\[Class (I{1,3})\]\s*[^:]*:\s*(.*)$/)
  return m ? {cls: m[1], reason: m[2]} : null
}

const CLASS_TEXT = {I: "Classe I (rischio grave)", II: "Classe II (rischio moderato)", III: "Classe III (rischio basso)"}

const ITALY_COLOR = {ALTA: "#E24B4A", MEDIA: "#EF9F27", BASSA: "#378ADD", NESSUNA: "#1D9E75"}

function riskColor(score) {
  if (score >= 80) return "#E24B4A"
  if (score >= 60) return "#EF9F27"
  if (score >= 30) return "#378ADD"
  return "#1D9E75"
}

export default function App() {
  const canvasRef = useRef(null)
  const [allNodes, setNodes] = useState([])
  const [allEdges, setEdges] = useState([])
  // Filtro del grafo: tutto, solo Italia (enti italiani e aziende con richiami distribuiti in Italia), internazionale
  // (si può aprire direttamente con ?vista=italia o ?vista=internazionale)
  const [scope, setScope] = useState(() => ({italia: "it", internazionale: "int"})[
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("vista") : ""] || "all")
  const nodes = useMemo(() => scope === "all" ? allNodes
    : allNodes.filter(n => scope === "it" ? n.italy || n.italy_related : !n.italy), [allNodes, scope])
  const edges = useMemo(() => {
    if (scope === "all") return allEdges
    const ids = new Set(nodes.map(n => n.id))
    return allEdges.filter(e => ids.has(e.source) && ids.has(e.target))
  }, [allEdges, nodes, scope])
  const [alerts, setAlerts] = useState([])
  const [signals, setSignals] = useState(null)
  const [stats, setStats] = useState({})
  const [selected, setSelected] = useState(null)
  const [nodeDetails, setNodeDetails] = useState(null)
  const [tab, setTab] = useState("graph")
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [notice, setNotice] = useState(null)   // {kind: "info"|"error"|"ok", text}
  const [loadError, setLoadError] = useState(null)
  const [zoom, setZoom] = useState(100)
  const [selectedEdge, setSelectedEdge] = useState(null)
  // Dimensione reale del canvas in pixel CSS e layout stretto (telefono)
  const [size, setSize] = useState({w: 800, h: 600})
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.innerWidth < 760)
  const wrapRef = useRef(null)
  const detailsRef = useRef(null)
  const pointersRef = useRef(new Map())
  const pinchRef = useRef(null)
  const fitRef = useRef(1)
  const posRef = useRef({})
  const velRef = useRef({})
  const animRef = useRef(null)
  const hoveredRef = useRef(null)
  const draggingRef = useRef(null)
  const dragOffRef = useRef({x:0,y:0})
  // Vista del grafo: zoom e spostamento, in pixel del canvas
  const viewRef = useRef({scale:1, x:0, y:0})
  const panRef = useRef(null)
  // Temperatura della simulazione (1 = appena avviata, sotto alphaMin = ferma)
  const alphaRef = useRef(1)
  // Finché l'utente non sposta o ingrandisce, la vista segue il grafo mentre si assesta
  const autoFitRef = useRef(true)

  const fetchData = useCallback(async () => {
    // Il backend Render può impiegare fino a un minuto a svegliarsi
    const get = path => fetch(`${API}${path}`, {signal: AbortSignal.timeout(60000)}).then(r => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`)
      return r.json()
    })
    try {
      const [g, a, s, st, sig] = await Promise.all([
        get("/api/graph"), get("/api/alerts"), get("/api/stats"), get("/api/status").catch(() => null),
        get("/api/signals").catch(() => null),
      ])
      if (!Array.isArray(g?.nodes) || g.nodes.length === 0) throw new Error("il grafo ricevuto non contiene nodi")
      setNodes(g.nodes)
      setEdges(Array.isArray(g.edges) ? g.edges : [])
      setAlerts(Array.isArray(a) ? a : [])
      setStats(s || {})
      if (st) setStatus(st)
      setSignals(sig)
      setLoadError(null)
    } catch (e) {
      console.error("[HEALTHINT] caricamento dati non riuscito:", e)
      setLoadError(e.message || String(e))
    }
    setLoading(false)
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  // Notizie OMS scaricate, per titolo e data di pubblicazione delle fonti
  const donIndex = {}
  ;(signals?.who || []).forEach(s => {
    const id = String(s.url || "").split("/").pop()
    if (id) donIndex[id] = s
  })
  const nodeById = Object.fromEntries(allNodes.map(n => [n.id, n]))
  const relationsOf = id => allEdges.filter(e => e.source === id || e.target === id).map(e => ({
    ...e, source_label: nodeById[e.source]?.label || e.source, target_label: nodeById[e.target]?.label || e.target,
  })).sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0))
  // Quante informazioni del grafo hanno una fonte con link
  const coverage = (() => {
    const nodesWith = nodes.filter(n => nodeOrigin(n, relationsOf(n.id), donIndex).sources.length > 0).length
    const edgesWith = edges.filter(e => relationOrigin(e, donIndex).kind !== "manual").length
    return {nodesWith, edgesWith}
  })()
  const presentTypes = new Set(nodes.map(n => n.type))
  const updatedAt = status?.updated_at || stats.updated_at

  // Il canvas segue la larghezza del suo contenitore; la vista adatta il grafo allo spazio disponibile
  useEffect(() => {
    function onResize() { setNarrow(window.innerWidth < 760) }
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const w = Math.max(260, Math.round(el.clientWidth))
      const h = Math.max(300, Math.round(el.clientHeight))
      setSize(s => (s.w === w && s.h === h) ? s : {w, h})
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [loading, loadError, tab, narrow])
  // Se cambia la dimensione: con la vista automatica si reinquadra, altrimenti resta centrata
  const prevSizeRef = useRef(null)
  useEffect(() => {
    const prev = prevSizeRef.current
    prevSizeRef.current = size
    // Con la vista automatica il grafo si riassesta sulle nuove proporzioni
    if (!prev || autoFitRef.current) { alphaRef.current = Math.max(alphaRef.current, 0.3); fitView(); return }
    const v = viewRef.current
    v.x += (size.w - prev.w) / 2
    v.y += (size.h - prev.h) / 2
  }, [size.w, size.h])

  async function refreshNow() {
    setNotice(null)
    let res
    try {
      res = await fetch(`${API}/api/refresh/manual`, {method: "POST"})
    } catch {
      setNotice({kind:"error", text:"Server non raggiungibile: riprova tra poco."})
      return
    }
    if (res.status !== 202) {
      const body = await res.json().catch(() => ({}))
      setNotice({kind: res.status === 429 ? "info" : "error", text: body.detail || `Errore ${res.status}`})
      return
    }
    setRefreshing(true)
    setNotice({kind:"info", text:"Aggiornamento in corso: scarico le fonti e rigenero gli alert, ci vuole circa un minuto…"})
    const before = status?.last_attempt
    // Si attende che il server finisca (massimo 5 minuti)
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 5000))
      const st = await fetch(`${API}/api/status`).then(r => r.json()).catch(() => null)
      if (!st || st.running || st.last_attempt === before) continue
      setStatus(st)
      await fetchData()
      setRefreshing(false)
      if (st.last_error) setNotice({kind:"error", text:`Aggiornamento non riuscito, restano i dati precedenti: ${st.last_error}`})
      else if (st.alerts_error) setNotice({kind:"error", text:`Dati aggiornati, ma gli alert non sono stati generati: ${st.alerts_error}`})
      else setNotice({kind:"ok", text:"Dati aggiornati."})
      return
    }
    setRefreshing(false)
    setNotice({kind:"error", text:"L'aggiornamento sta impiegando più del previsto: ricarica la pagina tra qualche minuto."})
  }

  // Posizioni iniziali a spirale (fillotassi) attorno al centro; i nodi già presenti restano dove sono
  useEffect(() => {
    if (nodes.length === 0) return
    let added = 0
    nodes.forEach((n, i) => {
      if (!posRef.current[n.id]) {
        const radius = 18 * Math.sqrt(0.5 + i), angle = i * Math.PI * (3 - Math.sqrt(5))
        posRef.current[n.id] = {x: Math.cos(angle) * radius, y: Math.sin(angle) * radius}
        velRef.current[n.id] = {vx: 0, vy: 0}
        added++
      }
    })
    // Si riscalda la simulazione: del tutto se i nodi sono nuovi, poco se è cambiato solo qualcosa
    alphaRef.current = Math.max(alphaRef.current, added > nodes.length / 2 ? 1 : 0.4)
  }, [nodes])

  // Un passo della simulazione a forze
  function simTick(alpha) {
    const pos = posRef.current, vel = velRef.current
    const list = nodes.filter(n => pos[n.id]).map(n => ({id: n.id, p: pos[n.id], v: vel[n.id] || (vel[n.id] = {vx: 0, vy: 0}), r: nodeRadius(n)}))
    const maxD2 = SIM.chargeMax * SIM.chargeMax
    for (let i = 0; i < list.length; i++) {
      const a = list[i]
      for (let j = i + 1; j < list.length; j++) {
        const b = list[j]
        let dx = b.p.x - a.p.x, dy = b.p.y - a.p.y
        let l2 = dx * dx + dy * dy
        if (l2 === 0) { dx = (Math.random() - 0.5) * 1e-3; dy = (Math.random() - 0.5) * 1e-3; l2 = dx * dx + dy * dy }
        // Repulsione (decresce con la distanza)
        if (l2 < maxD2) {
          const w = SIM.charge * alpha / Math.max(l2, 1)
          a.v.vx += dx * w; a.v.vy += dy * w
          b.v.vx -= dx * w; b.v.vy -= dy * w
        }
        // Collisione: due nodi non si sovrappongono mai
        const rr = a.r + b.r + SIM.collidePad
        if (l2 < rr * rr) {
          const l = Math.sqrt(l2)
          const m = (rr - l) / l * 0.5
          a.v.vx -= dx * m; a.v.vy -= dy * m
          b.v.vx += dx * m; b.v.vy += dy * m
        }
      }
    }
    // Molle sulle relazioni, più deboli verso i nodi con molti collegamenti
    const count = {}
    edges.forEach(e => { count[e.source] = (count[e.source] || 0) + 1; count[e.target] = (count[e.target] || 0) + 1 })
    edges.forEach(e => {
      const ps = pos[e.source], pt = pos[e.target]
      if (!ps || !pt || e.source === e.target) return
      const vs = vel[e.source], vt = vel[e.target]
      const dx = pt.x + vt.vx - ps.x - vs.vx, dy = pt.y + vt.vy - ps.y - vs.vy
      const l = Math.sqrt(dx * dx + dy * dy) || 1
      const k = (l - SIM.linkDist) / l * alpha / Math.min(count[e.source], count[e.target])
      const bias = count[e.source] / (count[e.source] + count[e.target])
      vt.vx -= dx * k * bias; vt.vy -= dy * k * bias
      vs.vx += dx * k * (1 - bias); vs.vy += dy * k * (1 - bias)
    })
    // La gravità segue le proporzioni del riquadro: su uno schermo largo il grafo si allarga
    const aspect = Math.min(2, Math.max(0.5, size.w / size.h))
    list.forEach(o => {
      o.v.vx -= o.p.x * SIM.gravity / aspect * alpha
      o.v.vy -= o.p.y * SIM.gravity * aspect * alpha
      if (o.id === draggingRef.current?.id) { o.v.vx = 0; o.v.vy = 0; return }
      o.v.vx *= 1 - SIM.velocityDecay; o.v.vy *= 1 - SIM.velocityDecay
      o.p.x += o.v.vx; o.p.y += o.v.vy
    })
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || nodes.length === 0) return
    const ctx = canvas.getContext("2d")
    const degree = {}
    edges.forEach(e => { degree[e.source] = (degree[e.source] || 0) + 1; degree[e.target] = (degree[e.target] || 0) + 1 })

    // Primo avvio: si fa assestare il grafo prima di mostrarlo
    if (alphaRef.current >= 1) {
      let alpha = 1
      for (let i = 0; i < 120; i++) { simTick(alpha); alpha *= 1 - SIM.alphaDecay }
      alphaRef.current = alpha
    }

    function draw() {
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const view = viewRef.current
      ctx.setTransform(view.scale, 0, 0, view.scale, view.x, view.y)
      const sel = selected
      const selEdge = selectedEdge
      const selEdgeObj = selEdge && edges.find(e => e.id === selEdge)
      const hov = hoveredRef.current

      edges.forEach(e => {
        const ps = posRef.current[e.source], pt = posRef.current[e.target]
        if (!ps || !pt) return
        const isEdgeSel = selEdge && e.id === selEdge
        const isHl = isEdgeSel || (sel && (e.source === sel || e.target === sel))
        ctx.beginPath()
        ctx.moveTo(ps.x, ps.y)
        ctx.lineTo(pt.x, pt.y)
        ctx.strokeStyle = isEdgeSel ? "rgba(216,90,48,0.9)" : isHl ? "rgba(29,158,117,0.7)" : "rgba(128,128,128,0.16)"
        ctx.lineWidth = (isEdgeSel ? 3.5 : isHl ? 2 : 0.8) / Math.sqrt(view.scale)
        ctx.stroke()
        if (isHl) {
          const mx = (ps.x+pt.x)/2, my = (ps.y+pt.y)/2
          const angle = Math.atan2(pt.y-ps.y, pt.x-ps.x)
          ctx.beginPath()
          ctx.moveTo(mx-8*Math.cos(angle-0.4), my-8*Math.sin(angle-0.4))
          ctx.lineTo(mx, my)
          ctx.lineTo(mx-8*Math.cos(angle+0.4), my-8*Math.sin(angle+0.4))
          ctx.strokeStyle = "rgba(29,158,117,0.8)"
          ctx.lineWidth = 1.5
          ctx.stroke()
        }
      })

      // Etichette candidate, in ordine di priorità: selezione e passaggio del mouse, poi rischio e collegamenti
      const zoomedIn = view.scale / fitRef.current >= LABEL_ZOOM
      const labels = []
      nodes.forEach(n => {
        const p = posRef.current[n.id]
        if (!p) return
        const color = NODE_COLORS[n.type] || OTHER_COLOR
        const isSel = n.id === sel
        const isHov = hov && n.id === hov.id
        const isConn = (sel && edges.some(e => (e.source===sel&&e.target===n.id)||(e.target===sel&&e.source===n.id)))
          || (selEdgeObj && (selEdgeObj.source === n.id || selEdgeObj.target === n.id))
        const dimmed = (sel || selEdgeObj) && !isSel && !isConn
        const r = isSel ? 14 : isHov ? 12 : nodeRadius(n)

        ctx.save()
        ctx.globalAlpha = dimmed ? 0.2 : 1
        if (isSel || isHov) {
          ctx.beginPath(); ctx.arc(p.x, p.y, r+6, 0, Math.PI*2)
          ctx.fillStyle = color+"33"; ctx.fill()
        }
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI*2)
        ctx.fillStyle = color; ctx.fill()
        ctx.strokeStyle = "rgba(255,255,255,0.6)"; ctx.lineWidth = 1.5; ctx.stroke()

        if (n.risk_score > 60) {
          ctx.beginPath(); ctx.arc(p.x, p.y, r+3, 0, Math.PI*2)
          ctx.strokeStyle = riskColor(n.risk_score)+"88"; ctx.lineWidth = 1; ctx.stroke()
        }
        ctx.restore()

        const forced = isSel || isHov || isConn
        const important = n.risk_score > LABEL_RISK || (degree[n.id] || 0) >= LABEL_HUB_DEGREE
        if (dimmed || !(forced || important || zoomedIn)) return
        labels.push({n, p, r, forced, isSel, priority: forced ? 1000 : (important ? 200 : 0) + n.risk_score + (degree[n.id] || 0)})
      })

      // Le etichette si disegnano a dimensione fissa sullo schermo, saltando quelle che si sovrapporrebbero
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.textAlign = "center"
      ctx.textBaseline = "top"
      ctx.lineJoin = "round"
      const placed = []
      labels.sort((a, b) => b.priority - a.priority).forEach(({n, p, r, forced, isSel}) => {
        const text = forced ? n.label : shortLabel(n.label)
        ctx.font = `${isSel ? "600" : "400"} 12px sans-serif`
        const w = ctx.measureText(text).width
        const x = p.x * view.scale + view.x, y = p.y * view.scale + view.y + (r + 3) * view.scale + 2
        const box = {x1: x - w / 2 - 2, x2: x + w / 2 + 2, y1: y - 1, y2: y + 14}
        if (box.x2 < 0 || box.x1 > canvas.width || box.y2 < 0 || box.y1 > canvas.height) return
        if (!forced && placed.some(b => box.x1 < b.x2 && box.x2 > b.x1 && box.y1 < b.y2 && box.y2 > b.y1)) return
        placed.push(box)
        ctx.strokeStyle = "rgba(255,255,255,0.9)"; ctx.lineWidth = 3
        ctx.strokeText(text, x, y)
        ctx.fillStyle = "rgba(0,0,0,0.8)"
        ctx.fillText(text, x, y)
      })
    }

    function loop() {
      if (alphaRef.current > SIM.alphaMin || draggingRef.current) {
        simTick(Math.max(alphaRef.current, draggingRef.current ? 0.1 : 0))
        alphaRef.current *= 1 - SIM.alphaDecay
        if (autoFitRef.current) fitView()
      }
      draw()
      animRef.current = requestAnimationFrame(loop)
    }
    animRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(animRef.current)
  }, [nodes, edges, selected, selectedEdge, loading, tab, size])

  // Zoom con la rotella attorno al puntatore (listener non passivo per bloccare lo scroll della pagina)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    function onWheel(e) {
      e.preventDefault()
      const r = canvas.getBoundingClientRect()
      const px = (e.clientX - r.left) * canvas.width / r.width
      const py = (e.clientY - r.top) * canvas.height / r.height
      zoomAt(Math.exp(-e.deltaY * 0.0015), px, py)
    }
    canvas.addEventListener("wheel", onWheel, {passive: false})
    return () => canvas.removeEventListener("wheel", onWheel)
  }, [nodes, loading, tab, size])

  // Zoom relativo alla vista "adattata" allo schermo (100% = tutto il grafo visibile)
  function zoomAt(factor, px, py) {
    const v = viewRef.current
    const fit = fitRef.current
    const scale = Math.min(fit * 6, Math.max(fit * 0.5, v.scale * factor))
    const k = scale / v.scale
    v.x = px - (px - v.x) * k
    v.y = py - (py - v.y) * k
    v.scale = scale
    autoFitRef.current = false
    setZoom(Math.round(scale / fit * 100))
  }

  function zoomButton(factor) {
    const canvas = canvasRef.current
    if (canvas) zoomAt(factor, canvas.width / 2, canvas.height / 2)
  }

  // Inquadra tutti i nodi nello spazio disponibile (100% di zoom)
  function fitView() {
    const pts = nodes.map(n => posRef.current[n.id]).filter(Boolean)
    if (!pts.length) return
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
    const x1 = Math.min(...xs), x2 = Math.max(...xs), y1 = Math.min(...ys), y2 = Math.max(...ys)
    // Margine per nodi ed etichette ai bordi
    const mx = 70, my = 40
    const scale = Math.min(2, (size.w - 2 * mx) / Math.max(x2 - x1, 1), (size.h - 2 * my - 16) / Math.max(y2 - y1, 1))
    fitRef.current = scale
    viewRef.current = {scale, x: size.w / 2 - (x1 + x2) / 2 * scale, y: (size.h - 16) / 2 - (y1 + y2) / 2 * scale}
    setZoom(100)
  }

  function resetView() {
    autoFitRef.current = true
    fitView()
  }

  function toCanvasPixels(cssX, cssY) {
    const canvas = canvasRef.current
    if (!canvas) return {x: cssX, y: cssY}
    const r = canvas.getBoundingClientRect()
    return {x: cssX * (canvas.width / r.width), y: cssY * (canvas.height / r.height)}
  }

  function toCanvasCoords(cssX, cssY) {
    const {x, y} = toCanvasPixels(cssX, cssY)
    const v = viewRef.current
    return {x: (x - v.x) / v.scale, y: (y - v.y) / v.scale}
  }

  // Raggio di tocco in pixel dello schermo: più largo per il dito
  function hitRadius(touch) {
    return (touch ? 24 : 14) / viewRef.current.scale
  }

  function getNodeAt(cssX, cssY, touch) {
    const {x, y} = toCanvasCoords(cssX, cssY)
    const hit = hitRadius(touch)
    let best = null, bestD = Infinity
    for (const n of nodes) {
      const p = posRef.current[n.id]
      if (!p) continue
      const d = Math.hypot(x - p.x, y - p.y)
      if (d < hit && d < bestD) { best = n; bestD = d }
    }
    return best
  }

  // Relazione più vicina al punto toccato (distanza dal segmento)
  function getEdgeAt(cssX, cssY, touch) {
    const {x, y} = toCanvasCoords(cssX, cssY)
    const hit = hitRadius(touch) * 0.6
    let best = null, bestD = Infinity
    for (const e of edges) {
      const a = posRef.current[e.source], b = posRef.current[e.target]
      if (!a || !b) continue
      const dx = b.x - a.x, dy = b.y - a.y
      const len2 = dx * dx + dy * dy || 1
      const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / len2))
      const d = Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy))
      if (d < hit && d < bestD) { best = e; bestD = d }
    }
    return best
  }

  function selectNode(n) {
    setSelectedEdge(null)
    setSelected(n ? n.id : null)
    setNodeDetails(n ? {node: n, relations: relationsOf(n.id)} : null)
  }

  function selectEdge(e) {
    setSelected(null)
    setNodeDetails(null)
    setSelectedEdge(e ? e.id : null)
  }

  function localPoint(ev) {
    const r = ev.currentTarget.getBoundingClientRect()
    return {cssX: ev.clientX - r.left, cssY: ev.clientY - r.top}
  }

  function onPointerDown(ev) {
    ev.currentTarget.setPointerCapture?.(ev.pointerId)
    const {cssX, cssY} = localPoint(ev)
    pointersRef.current.set(ev.pointerId, {cssX, cssY})
    if (pointersRef.current.size === 2) {
      // Due dita: zoom, si annullano trascinamenti in corso
      const [a, b] = [...pointersRef.current.values()]
      pinchRef.current = {dist: Math.hypot(a.cssX - b.cssX, a.cssY - b.cssY) || 1}
      draggingRef.current = null
      panRef.current = null
      return
    }
    if (pointersRef.current.size > 2) return
    const touch = ev.pointerType !== "mouse"
    const n = getNodeAt(cssX, cssY, touch)
    if (n) {
      draggingRef.current = n
      const {x, y} = toCanvasCoords(cssX, cssY)
      const p = posRef.current[n.id]
      dragOffRef.current = {x: x-p.x, y: y-p.y, startX: cssX, startY: cssY}
    } else {
      const start = toCanvasPixels(cssX, cssY)
      panRef.current = {x: start.x, y: start.y, moved: 0}
    }
  }

  function onPointerMove(ev) {
    const {cssX, cssY} = localPoint(ev)
    if (pointersRef.current.has(ev.pointerId)) pointersRef.current.set(ev.pointerId, {cssX, cssY})
    if (pinchRef.current && pointersRef.current.size === 2) {
      const [a, b] = [...pointersRef.current.values()]
      const dist = Math.hypot(a.cssX - b.cssX, a.cssY - b.cssY) || 1
      const mid = toCanvasPixels((a.cssX + b.cssX) / 2, (a.cssY + b.cssY) / 2)
      zoomAt(dist / pinchRef.current.dist, mid.x, mid.y)
      pinchRef.current.dist = dist
      return
    }
    if (draggingRef.current) {
      const {x, y} = toCanvasCoords(cssX, cssY)
      const p = posRef.current[draggingRef.current.id]
      p.x = x-dragOffRef.current.x; p.y = y-dragOffRef.current.y
      velRef.current[draggingRef.current.id] = {vx:0,vy:0}
      autoFitRef.current = false
      alphaRef.current = Math.max(alphaRef.current, 0.1)
    } else if (panRef.current) {
      const now = toCanvasPixels(cssX, cssY)
      const v = viewRef.current
      v.x += now.x - panRef.current.x
      v.y += now.y - panRef.current.y
      autoFitRef.current = false
      panRef.current.moved += Math.abs(now.x - panRef.current.x) + Math.abs(now.y - panRef.current.y)
      panRef.current.x = now.x; panRef.current.y = now.y
      ev.currentTarget.style.cursor = "grabbing"
    } else if (ev.pointerType === "mouse") {
      hoveredRef.current = getNodeAt(cssX, cssY, false)
      ev.currentTarget.style.cursor = hoveredRef.current || getEdgeAt(cssX, cssY, false) ? "pointer" : "default"
    }
  }

  function onPointerUp(ev) {
    const {cssX, cssY} = localPoint(ev)
    pointersRef.current.delete(ev.pointerId)
    if (pinchRef.current) {
      // Fine dello zoom a due dita: nessuna selezione
      if (pointersRef.current.size === 0) pinchRef.current = null
      draggingRef.current = null
      panRef.current = null
      return
    }
    const touch = ev.pointerType !== "mouse"
    const dragging = draggingRef.current
    const panned = panRef.current && panRef.current.moved > (touch ? 10 : 5)
    panRef.current = null
    draggingRef.current = null
    ev.currentTarget.style.cursor = "default"
    if (panned) return
    if (dragging) {
      const moved = Math.hypot(cssX - dragOffRef.current.startX, cssY - dragOffRef.current.startY)
      if (moved < (touch ? 10 : 5)) selectNode(selected === dragging.id ? null : dragging)
      return
    }
    const e = getEdgeAt(cssX, cssY, touch)
    if (e) selectEdge(selectedEdge === e.id ? null : e)
    else selectNode(null)
  }

  function onPointerCancel(ev) {
    pointersRef.current.delete(ev.pointerId)
    if (pointersRef.current.size < 2) pinchRef.current = null
    draggingRef.current = null
    panRef.current = null
    hoveredRef.current = null
  }


  // Da computer la pagina del grafo occupa esattamente la finestra: il grafo prende tutto lo spazio libero
  const fullPage = tab === "graph" && !narrow && !loading && !loadError

  return (
    <div style={{fontFamily:"var(--font-sans,sans-serif)",color:"var(--color-text-primary)",minHeight:"100vh",background:"var(--color-background-tertiary)",
      ...(fullPage ? {height:"100vh",display:"flex",flexDirection:"column"} : {})}}>
      {/* Header */}
      <div style={{background:"var(--color-background-primary)",borderBottom:"0.5px solid var(--color-border-tertiary)",padding:"12px 20px",display:"flex",alignItems:"center",gap:16,flexWrap:"wrap"}}>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <div style={{width:8,height:8,borderRadius:"50%",background:"#1D9E75"}}/>
          <span style={{fontWeight:500,fontSize:16}}>HEALTHINT</span>
          <span style={{fontSize:12,color:"var(--color-text-tertiary)",background:"var(--color-background-secondary)",padding:"2px 8px",borderRadius:4}}>Health System Intelligence Graph</span>
        </div>
        <div style={{display:"flex",gap:20,marginLeft:16}}>
          {[["graph","Grafo"],["alerts","Alert"],["risk","Risk Score"]].map(([k,v]) => (
            <button key={k} onClick={()=>setTab(k)} style={{background:"none",border:"none",cursor:"pointer",fontSize:13,fontWeight:tab===k?500:400,color:tab===k?"var(--color-text-primary)":"var(--color-text-secondary)",borderBottom:tab===k?"2px solid #1D9E75":"2px solid transparent",paddingBottom:4}}>{v}</button>
          ))}
        </div>
        <div style={{marginLeft:"auto",display:"flex",gap:12,alignItems:"center"}}>
          {stats.unread_alerts > 0 && <span style={{background:"#E24B4A",color:"#fff",borderRadius:10,padding:"2px 8px",fontSize:11}}>{stats.unread_alerts} alert</span>}
          {stats.nodes != null && <span style={{fontSize:12,color:"var(--color-text-tertiary)"}}>{stats.nodes} nodi · {stats.edges} relazioni</span>}
          <button onClick={refreshNow} disabled={refreshing}
            style={{fontSize:12,padding:"5px 12px",borderRadius:6,border:"0.5px solid #1D9E75",background:refreshing?"var(--color-background-secondary)":"#1D9E75",color:refreshing?"var(--color-text-secondary)":"#fff",cursor:refreshing?"default":"pointer"}}>
            {refreshing ? "Aggiornamento…" : "Aggiorna dati"}
          </button>
        </div>
      </div>

      {/* Data dell'ultimo aggiornamento del grafo, ben visibile */}
      <div role="status" style={{background:"#E1F5EE",borderBottom:"1px solid #5DCAA5",padding:"10px 20px",display:"flex",flexWrap:"wrap",alignItems:"baseline",gap:"2px 12px"}}>
        <span style={{fontSize:16,fontWeight:600,color:"#0F6E56"}}>
          Grafo aggiornato al {updatedAt ? formatDateTime(updatedAt) : "—"}
        </span>
        <span style={{fontSize:12,color:"#04342C"}}>
          Controllo automatico delle fonti due volte al giorno: la data cambia quando entrano nuovi dati.
        </span>
      </div>

      {/* Fonti */}
      <div style={{background:"var(--color-background-secondary)",borderBottom:"0.5px solid var(--color-border-tertiary)",padding:"8px 20px",fontSize:12,color:"var(--color-text-secondary)",display:"flex",flexWrap:"wrap",gap:"4px 16px"}}>
        <span>
          <strong style={{fontWeight:500}}>Fonti:</strong>{" "}
          {(status?.sources || []).map((src, i) => (
            <span key={src.key}>{i > 0 && " · "}<a href={src.url} target="_blank" rel="noopener noreferrer" style={{color:"inherit"}}>{src.label}</a></span>
          ))}
          {status?.sources?.length > 0 && " · analisi AI: Claude (Anthropic)"}
        </span>
        {status?.new && (
          <span>
            <strong style={{fontWeight:500}}>Novità dell'ultimo aggiornamento:</strong>{" "}
            {status.new.nodes} nodi, {status.new.edges} relazioni, {status.new.alerts} alert
            {Object.values(status.latest_at_source || {}).some(Boolean) && <>{" · dato più recente: "}
              {(status.sources || []).filter(s => status.latest_at_source[s.key]).map(s =>
                `${s.label.split(" (")[0]} ${new Date(status.latest_at_source[s.key]).toLocaleDateString("it-IT")}`).join(" · ")}</>}
          </span>
        )}
      </div>
      {notice && (
        <div role="status" style={{padding:"8px 20px",fontSize:13,
          background: notice.kind === "error" ? "#E24B4A1A" : notice.kind === "ok" ? "#1D9E751A" : "#378ADD1A",
          color: notice.kind === "error" ? "#A32D2D" : "var(--color-text-primary)"}}>
          {notice.text}
        </div>
      )}
      {!notice && status?.last_error && (
        <div role="status" style={{padding:"8px 20px",fontSize:13,background:"#E24B4A1A",color:"#A32D2D"}}>
          L'ultimo tentativo di aggiornamento ({formatDateTime(status.last_attempt)}) non è riuscito: {status.last_error}. Sono mostrati i dati dell'ultimo aggiornamento riuscito.
        </div>
      )}

      {loading && <div style={{padding:40,textAlign:"center",color:"var(--color-text-secondary)"}}>Caricamento grafo sanitario...</div>}

      {!loading && loadError && (
        <div role="alert" style={{margin:20,padding:"24px 20px",textAlign:"center",background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderRadius:8}}>
          <div style={{fontSize:15,fontWeight:500,marginBottom:6}}>Dati non disponibili, riprova tra poco.</div>
          <div style={{fontSize:12,color:"var(--color-text-tertiary)",marginBottom:14}}>Il servizio potrebbe essere in fase di avvio. Dettaglio: {loadError}</div>
          <button onClick={()=>{setLoading(true); fetchData()}} style={{fontSize:13,padding:"6px 14px",borderRadius:6,border:"0.5px solid #1D9E75",background:"#1D9E75",color:"#fff",cursor:"pointer"}}>Riprova</button>
        </div>
      )}

      {/* Graph tab */}
      {!loading && !loadError && tab === "graph" && (
        <div style={fullPage ? {flex:1,minHeight:0,display:"flex",flexDirection:"column"} : undefined}>
          {/* Filtro Italia / internazionale */}
          <div role="group" aria-label="Filtro del grafo" style={{background:"var(--color-background-primary)",borderBottom:"0.5px solid var(--color-border-tertiary)",padding:"8px 20px",display:"flex",flexWrap:"wrap",alignItems:"center",gap:"6px 10px",fontSize:12}}>
            <span style={{color:"var(--color-text-secondary)"}}>Mostra:</span>
            <div style={{display:"inline-flex",border:"0.5px solid #1D9E75",borderRadius:6,overflow:"hidden"}}>
              {[["all","Tutto"],["it","Solo Italia"],["int","Internazionale"]].map(([k,v]) => (
                <button key={k} onClick={() => { setScope(k); selectNode(null); autoFitRef.current = true }} aria-pressed={scope === k}
                  style={{fontSize:12,padding:"5px 12px",border:"none",cursor:"pointer",background:scope === k ? "#1D9E75" : "transparent",color:scope === k ? "#fff" : "var(--color-text-primary)"}}>{v}</button>
              ))}
            </div>
            <span style={{color:"var(--color-text-tertiary)"}}>{nodes.length} nodi · {edges.length} relazioni
              {scope === "it" && " · enti italiani e aziende con richiami FDA distribuiti in Italia"}</span>
          </div>

          {/* Legenda */}
          <details open={!narrow} style={{background:"var(--color-background-primary)",borderBottom:"0.5px solid var(--color-border-tertiary)",padding:"8px 20px",fontSize:12,color:"var(--color-text-secondary)",lineHeight:1.6}}>
            <summary style={{cursor:"pointer",fontWeight:500,color:"var(--color-text-primary)"}}>Come leggere il grafo</summary>
            <div style={{display:"flex",flexWrap:"wrap",gap:"4px 14px",margin:"6px 0"}}>
              {Object.entries(NODE_COLORS).filter(([type]) => presentTypes.has(type)).map(([type,color]) => (
                <span key={type} style={{display:"inline-flex",alignItems:"center",gap:5}}>
                  <span style={{width:9,height:9,borderRadius:"50%",background:color,display:"inline-block"}}/>{NODE_TYPE_LABEL[type] || type}
                </span>
              ))}
              {[...presentTypes].some(t => !NODE_COLORS[t]) && (
                <span style={{display:"inline-flex",alignItems:"center",gap:5}}>
                  <span style={{width:9,height:9,borderRadius:"50%",background:OTHER_COLOR,display:"inline-block"}}/>{OTHER_LABEL}
                </span>
              )}
            </div>
            <div><strong style={{fontWeight:500}}>Nodi</strong>: enti, aziende ed eventi sanitari; il colore indica il tipo, la dimensione il punteggio di rischio (0-100), l'anello esterno un rischio superiore a 60.</div>
            <div><strong style={{fontWeight:500}}>Linee</strong>: relazioni tra due nodi (es. richiamo FDA che riguarda un'azienda, collaborazione, controllo); quando sono evidenziate, la freccia ne indica il verso.</div>
            <div><strong style={{fontWeight:500}}>Fonti</strong>: tocca un nodo o una linea per vedere fonte, link e data. Hanno una fonte con link {coverage.nodesWith} nodi su {nodes.length} e {coverage.edgesWith} relazioni su {edges.length}; gli altri sono indicati come «{NO_SOURCE}».</div>
          </details>

          <div style={{display:"flex",flexDirection:narrow ? "column" : "row",...(fullPage ? {flex:1,minHeight:420} : {})}}>
            <div ref={wrapRef} style={{flex:1,minWidth:0,position:"relative",overflow:"hidden",
              height:narrow ? "min(78vh, 640px)" : "auto",minHeight:narrow ? 360 : 420}}>
              <canvas ref={canvasRef} width={size.w} height={size.h}
                style={{position:"absolute",inset:0,width:"100%",height:"100%",display:"block",touchAction:"none"}}
                onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
                onPointerCancel={onPointerCancel}
                onPointerLeave={ev => { if (ev.pointerType === "mouse") hoveredRef.current = null }}
              />
              <div style={{position:"absolute",bottom:10,left:10,zIndex:10,display:"flex",gap:6,alignItems:"center",background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderRadius:8,padding:"4px 6px",fontSize:12}}>
                <button onClick={()=>zoomButton(1.25)} aria-label="Ingrandisci" style={zoomBtn}>+</button>
                <button onClick={()=>zoomButton(0.8)} aria-label="Riduci" style={zoomBtn}>−</button>
                <button onClick={resetView} style={{...zoomBtn,width:"auto",padding:"0 10px"}}>Adatta</button>
                <span style={{color:"var(--color-text-tertiary)",padding:"0 4px"}}>{zoom}%</span>
              </div>
              {narrow && (selected || selectedEdge) && (
                <button onClick={() => detailsRef.current?.scrollIntoView({behavior:"smooth", block:"start"})}
                  style={{position:"absolute",top:10,right:10,zIndex:10,fontSize:13,padding:"8px 12px",borderRadius:8,border:"none",background:"#1D9E75",color:"#fff",cursor:"pointer",boxShadow:"0 1px 4px rgba(0,0,0,0.2)"}}>
                  Dettagli e fonte ↓
                </button>
              )}
            </div>

            {/* Pannello dei dettagli */}
            <div ref={detailsRef} style={{width:narrow ? "auto" : 320,flexShrink:0,boxSizing:"border-box",borderLeft:narrow ? "none" : "0.5px solid var(--color-border-tertiary)",borderTop:narrow ? "0.5px solid var(--color-border-tertiary)" : "none",background:"var(--color-background-primary)",padding:16,overflowY:narrow ? "visible" : "auto",minHeight:0}}>
              <p style={{fontSize:11,color:"var(--color-text-tertiary)",marginBottom:10}}>
                {narrow ? "Due dita: zoom · trascina: sposta · tocca un nodo o una linea: dettagli e fonte"
                  : "Rotella: zoom · trascina lo sfondo: sposta · clic su un nodo o una linea: dettagli e fonte"}
              </p>
              {!nodeDetails && !selectedEdge && <p style={{fontSize:12,color:"var(--color-text-tertiary)"}}>Nessun elemento selezionato.</p>}

              {selectedEdge && (() => {
                const r = edges.find(e => e.id === selectedEdge)
                if (!r) return null
                const origin = relationOrigin(r, donIndex)
                const recall = origin.kind === "fda" ? parseRecallFact(r.fact) : null
                const src = nodeById[r.source], tgt = nodeById[r.target]
                return (
                  <div>
                    <div style={{fontSize:11,fontWeight:500,color:"var(--color-text-tertiary)",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:6}}>Relazione</div>
                    <div style={{fontSize:14,lineHeight:1.45,marginBottom:8}}>
                      <strong style={{fontWeight:500}}>{src?.label || r.source}</strong>{" "}
                      <em>{origin.kind === "fda" ? "ha un richiamo FDA che riguarda l'ambito di" : (REL_LABEL[r.type] || [r.type])[0]}</em>{" "}
                      <strong style={{fontWeight:500}}>{tgt?.label || r.target}</strong>
                    </div>
                    {recall ? (
                      <div style={{fontSize:12,marginBottom:8}}>
                        <div><strong style={{fontWeight:500}}>Richiamo FDA {origin.recall}</strong> · {CLASS_TEXT[recall.cls] || "Classe " + recall.cls}</div>
                        {recall.reason && <div style={{color:"var(--color-text-secondary)"}}>Motivo: {recall.reason}</div>}
                      </div>
                    ) : (r.fact && <div style={{fontSize:12,color:"var(--color-text-secondary)",marginBottom:8,lineHeight:1.5}}>{r.fact}</div>)}
                    {r.risk_score != null && <div style={{fontSize:12,marginBottom:8}}>Rischio della relazione: <strong style={{fontWeight:500,color:riskColor(r.risk_score)}}>{r.risk_score}/100</strong></div>}
                    <div style={{fontSize:12,padding:"8px 10px",borderRadius:6,background:"var(--color-background-secondary)",lineHeight:1.5}}>
                      <strong style={{fontWeight:500}}>Fonte:</strong>{" "}
                      <SourceLinks sources={relationSources(r, donIndex)}/>
                      {origin.kind === "manual" && r.date && <div>Data indicata: {formatDay(r.date)}</div>}
                      {origin.kind === "web" && r.type === "COMUNICA_SU" && <div style={{color:"var(--color-text-tertiary)"}}>Collegamento ricavato in automatico (senza AI): il documento cita l'ente.</div>}
                      {origin.kind === "who" && <div style={{color:"var(--color-text-tertiary)"}}>Relazione estratta dall'AI {relationSources(r, donIndex).length > 1 ? "da queste notizie" : "da questa notizia"}.</div>}
                    </div>
                  </div>
                )
              })()}

              {nodeDetails && (() => {
                const node = nodeDetails.node
                const origin = nodeOrigin(node, nodeDetails.relations, donIndex)
                return (
                  <div>
                    <div style={{display:"flex",justifyContent:"space-between",gap:8,marginBottom:8}}>
                      <span style={{fontSize:11,padding:"2px 8px",borderRadius:4,background:(NODE_COLORS[node.type]||OTHER_COLOR)+"22",color:NODE_COLORS[node.type]||OTHER_COLOR,fontWeight:500}}>{NODE_TYPE_LABEL[node.type] || OTHER_LABEL}</span>
                      <span title="Punteggio di rischio da 0 a 100" style={{fontSize:12,padding:"2px 8px",borderRadius:4,background:riskColor(node.risk_score)+"22",color:riskColor(node.risk_score),fontWeight:500,flexShrink:0}}>Rischio {node.risk_score}/100</span>
                    </div>
                    <div style={{fontSize:15,fontWeight:500,marginBottom:node.full_name && node.full_name !== node.label ? 2 : 6}}>{node.label}</div>
                    {node.full_name && node.full_name !== node.label && <div style={{fontSize:12,color:"var(--color-text-secondary)",marginBottom:6}}>{node.full_name}</div>}
                    {node.aliases?.length > 0 && (
                      <div style={{fontSize:11,color:"var(--color-text-tertiary)",marginBottom:8,lineHeight:1.45}}>
                        Anche indicato nelle fonti come: {node.aliases.join(" · ")}
                      </div>
                    )}
                    {node.region && <div style={{fontSize:12,color:"var(--color-text-tertiary)",marginBottom:8}}>📍 {node.region}</div>}
                    <div style={{fontSize:12,color:"var(--color-text-secondary)",lineHeight:1.5,marginBottom:8}}>{node.description}</div>
                    {node.risk_basis && <div style={{fontSize:11,color:"var(--color-text-secondary)",marginBottom:8}}>Base del rischio: {node.risk_basis}</div>}
                    <div style={{fontSize:12,padding:"8px 10px",borderRadius:6,background:"var(--color-background-secondary)",lineHeight:1.5,marginBottom:12}}>
                      <strong style={{fontWeight:500}}>Fonte:</strong>{" "}
                      <SourceLinks sources={origin.sources}/>
                      {origin.kind === "who" && origin.sources.length > 0 && <div style={{color:"var(--color-text-tertiary)"}}>Entità estratta dall'AI da questi documenti; il rischio è una stima dell'AI.</div>}
                      {origin.kind === "manual" && <div style={{color:"var(--color-text-tertiary)"}}>{node.website ? "Ente con sito istituzionale; il punteggio di rischio è stato assegnato a mano, senza fonte." : "Ente di base inserito manualmente, con rischio assegnato a mano."}</div>}
                      {origin.kind === "nucleus" && <div style={{color:"var(--color-text-tertiary)"}}>Ente del nucleo fisso italiano, sempre presente nel grafo; il rischio non è stimato. Le relazioni riportano la norma o il documento da cui derivano.</div>}
                      {origin.kind === "who" && origin.sources.length === 0 && <div style={{color:"var(--color-text-tertiary)"}}>Entità estratta dall'AI dalle notizie, senza relazioni che indichino il documento d'origine.</div>}
                    </div>
                    {nodeDetails.relations.length > 0 && (
                      <>
                        <div style={{fontSize:11,fontWeight:500,color:"var(--color-text-tertiary)",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:6}}>Relazioni ({nodeDetails.relations.length})</div>
                        {nodeDetails.relations.map((r,i) => {
                          const isSource = r.source === node.id
                          const other = isSource ? r.target_label : r.source_label
                          const ro = relationOrigin(r, donIndex)
                          const verb = ro.kind === "fda"
                            ? (r.target === "ema" ? "ha un richiamo FDA con distribuzione europea o mondiale (ambito di" : "ha un richiamo FDA con distribuzione in Italia (ambito di")
                            : (REL_LABEL[r.type] || [r.type, r.type])[isSource ? 0 : 1]
                          const recall = ro.kind === "fda" ? parseRecallFact(r.fact) : null
                          return (
                            <div key={r.id || i} style={{fontSize:12,padding:"8px 10px",borderRadius:6,background:"var(--color-background-secondary)",border:"0.5px solid var(--color-border-tertiary)",marginBottom:6,lineHeight:1.45}}>
                              <div style={{display:"flex",justifyContent:"space-between",gap:8,alignItems:"baseline"}}>
                                <span style={{color:"var(--color-text-secondary)"}}>
                                  {node.label} <em>{verb}</em> <strong style={{color:"var(--color-text-primary)",fontWeight:500}}>{other}</strong>{ro.kind === "fda" && ")"}
                                </span>
                                {r.risk_score != null && <span title="Rischio della relazione (0-100)" style={{flexShrink:0,fontSize:11,fontWeight:500,color:riskColor(r.risk_score)}}>{r.risk_score}</span>}
                              </div>
                              {recall ? (
                                <div style={{marginTop:4}}>
                                  <div><strong style={{fontWeight:500}}>Richiamo FDA {ro.recall}</strong> · {CLASS_TEXT[recall.cls] || "Classe " + recall.cls}</div>
                                  {recall.reason && <div style={{color:"var(--color-text-secondary)"}}>Motivo: {recall.reason}</div>}
                                </div>
                              ) : (r.fact && <div style={{marginTop:4,color:"var(--color-text-primary)"}}>{r.fact}</div>)}
                              <div style={{marginTop:4,fontSize:11,color:"var(--color-text-tertiary)"}}>
                                Fonte: <SourceLinks sources={relationSources(r, donIndex)}/>
                                {ro.kind === "manual" && r.date && <span> · data indicata: {formatDay(r.date)}</span>}
                              </div>
                            </div>
                          )
                        })}
                      </>
                    )}
                  </div>
                )
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Alerts tab */}
      {!loading && !loadError && tab === "alerts" && (
        <div style={{padding:20,maxWidth:800}}>
          <h2 style={{fontSize:15,fontWeight:500,marginBottom:4}}>Segnalazioni dalle fonti</h2>
          <p style={{fontSize:12,color:"var(--color-text-tertiary)",marginBottom:12}}>Dati reali scaricati a ogni aggiornamento, senza elaborazione dell'AI.</p>
          {signals?.italy?.length > 0 && (
            <div style={{marginBottom:16}}>
              <div style={{fontSize:12,fontWeight:500,marginBottom:6}}>Ultime dalle fonti italiane (Ministero della Salute in Gazzetta Ufficiale, AIFA, ISS, AGENAS)</div>
              {signals.italy.map((o,i) => (
                <div key={i} style={{background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderLeft:"3px solid #1D9E75",borderRadius:8,padding:"8px 14px",marginBottom:6,fontSize:13,lineHeight:1.45}}>
                  <a href={o.url} target="_blank" rel="noopener noreferrer" style={{color:"var(--color-text-primary)",textDecoration:"none",fontWeight:500}}>{o.title}</a>
                  {o.source === "Gazzetta Ufficiale" && o.summary && <div style={{color:"var(--color-text-secondary)"}}>{o.summary}</div>}
                  <div style={{fontSize:11,color:"var(--color-text-tertiary)"}}>{o.source}{o.date && ` · ${formatDay(o.date)}`}</div>
                </div>
              ))}
            </div>
          )}
          {!signals?.who?.length && !signals?.recalls?.length && !signals?.italy?.length && (
            <p style={{fontSize:13,color:"var(--color-text-tertiary)",marginBottom:16}}>Le segnalazioni compariranno dopo il prossimo aggiornamento dei dati.</p>
          )}
          {signals?.who?.length > 0 && (
            <div style={{marginBottom:16}}>
              <div style={{fontSize:12,fontWeight:500,marginBottom:6}}>Ultimi focolai segnalati dall'OMS</div>
              {signals.who.map((o,i) => (
                <div key={i} style={{background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderLeft:"3px solid #378ADD",borderRadius:8,padding:"8px 14px",marginBottom:6,fontSize:13}}>
                  <a href={o.url} target="_blank" rel="noopener noreferrer" style={{color:"var(--color-text-primary)",textDecoration:"none",fontWeight:500}}>{o.title}</a>
                  <div style={{fontSize:11,color:"var(--color-text-tertiary)"}}>Pubblicato dall'OMS il {formatDay(o.date)}</div>
                </div>
              ))}
            </div>
          )}
          {signals?.recalls?.length > 0 && (
            <div style={{marginBottom:24}}>
              <div style={{fontSize:12,fontWeight:500,marginBottom:6}}>Richiami FDA più recenti con distribuzione in Italia</div>
              {signals.recalls.map((r,i) => (
                <div key={i} style={{background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderLeft:`3px solid ${r.class === "Class I" ? "#E24B4A" : r.class === "Class II" ? "#EF9F27" : "#1D9E75"}`,borderRadius:8,padding:"8px 14px",marginBottom:6,fontSize:13,lineHeight:1.45}}>
                  <div><strong style={{fontWeight:500}}>{r.firm}</strong> · {CLASS_TEXT[(r.class || "").replace("Class ", "")] || r.class} · {r.kind === "device" ? "dispositivo medico" : "farmaco"}</div>
                  <div style={{color:"var(--color-text-secondary)"}}>{r.product}</div>
                  <div style={{color:"var(--color-text-secondary)"}}>Motivo: {r.reason}</div>
                  <div style={{fontSize:11,color:"var(--color-text-tertiary)"}}>Richiamo {r.recall} · pubblicato dalla FDA il {formatDay(r.date)} · <a href={r.url} target="_blank" rel="noopener noreferrer" style={{color:"inherit"}}>vedi alla fonte</a></div>
                </div>
              ))}
            </div>
          )}

          <h2 style={{fontSize:15,fontWeight:500,marginBottom:12}}>Alert generati dall'AI ({alerts.length})</h2>
          {status?.alerts_error && (
            <div role="alert" style={{background:"#E24B4A1A",border:"0.5px solid #E24B4A",borderRadius:8,padding:"10px 14px",marginBottom:16,fontSize:13,color:"#A32D2D"}}>
              La generazione degli alert non è riuscita ({formatDateTime(status.alerts_attempt)}): {status.alerts_error}.
              {alerts.length > 0 && " Sono mostrati gli alert della generazione precedente."}
            </div>
          )}
          {alerts.length === 0 && !status?.alerts_error && <p style={{color:"var(--color-text-tertiary)",fontSize:13}}>Nessun alert generato finora: usa "Aggiorna dati" o attendi il prossimo aggiornamento automatico.</p>}
          {[...alerts].sort((x, y) => ["ALTA","MEDIA","BASSA","NESSUNA"].indexOf(x.italy_relevance) - ["ALTA","MEDIA","BASSA","NESSUNA"].indexOf(y.italy_relevance)).map((a,i) => (
            <div key={i} style={{background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderLeft:`3px solid ${SEVERITY_COLOR[a.severity]||"#888"}`,borderRadius:8,padding:"12px 16px",marginBottom:12}}>
              <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:6}}>
                <span style={{fontSize:11,fontWeight:500,padding:"2px 8px",borderRadius:4,background:SEVERITY_COLOR[a.severity]+"22",color:SEVERITY_COLOR[a.severity]}}>{a.severity}</span>
                <span style={{fontSize:14,fontWeight:500}}>{a.title}</span>
              </div>
              <p style={{fontSize:13,color:"var(--color-text-secondary)",marginBottom:8,lineHeight:1.5}}>{a.description}</p>
              {(a.italy_impact || a.italy_relevance) && (
                <div style={{fontSize:13,lineHeight:1.5,marginBottom:8,padding:"8px 10px",borderRadius:6,background:"#378ADD12",border:"0.5px solid #378ADD55"}}>
                  <div style={{marginBottom:2}}>
                    <strong style={{fontWeight:500}}>🇮🇹 Impatto per l'Italia</strong>
                    {a.italy_relevance && <span style={{marginLeft:8,fontSize:11,fontWeight:500,padding:"1px 8px",borderRadius:4,
                      background:(ITALY_COLOR[a.italy_relevance]||"#888")+"22",color:ITALY_COLOR[a.italy_relevance]||"#888"}}>rilevanza {a.italy_relevance.toLowerCase()}</span>}
                  </div>
                  {a.italy_impact && <div style={{color:"var(--color-text-secondary)"}}>{a.italy_impact}</div>}
                </div>
              )}
              {a.timeframe && <div style={{fontSize:12,color:"var(--color-text-tertiary)"}}>⏱ Orizzonte: {a.timeframe}</div>}
              {a.recommendation && <div style={{fontSize:12,color:"var(--color-text-secondary)",marginTop:6,padding:"6px 8px",background:"var(--color-background-secondary)",borderRadius:4}}>💡 {a.recommendation}</div>}
            </div>
          ))}
        </div>
      )}

      {/* Risk scores tab */}
      {!loading && !loadError && tab === "risk" && (
        <div style={{padding:20,maxWidth:700}}>
          <h2 style={{fontSize:15,fontWeight:500,marginBottom:4}}>Risk Score — entità con il rischio più alto</h2>
          <p style={{fontSize:12,color:"var(--color-text-tertiary)",marginBottom:16,lineHeight:1.5}}>
            Per le aziende con richiami FDA il punteggio è ricalcolato a ogni aggiornamento: gravità del richiamo (classe I 85, II 55, III 25)
            pesata per la sua recenza (100% entro 90 giorni, 75% entro un anno, 50% oltre). Gli enti di base hanno un valore assegnato manualmente.
          </p>
          <div style={{display:"grid",gap:8}}>
            {[...nodes].sort((a,b)=>b.risk_score-a.risk_score).slice(0,15).map((n,i) => (
              <div key={n.id} style={{background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderRadius:8,padding:"10px 16px",display:"flex",alignItems:"center",gap:12}}>
                <span style={{fontSize:12,color:"var(--color-text-tertiary)",minWidth:20}}>#{i+1}</span>
                <div style={{width:8,height:8,borderRadius:"50%",background:NODE_COLORS[n.type]||"#888"}}/>
                <div style={{flex:1}}>
                  <div style={{fontWeight:500,fontSize:13}}>{n.label}</div>
                  <div style={{fontSize:11,color:"var(--color-text-tertiary)"}}>{NODE_TYPE_LABEL[n.type] || n.type} · {n.region||"—"}</div>
                  {n.risk_basis && <div style={{fontSize:11,color:"var(--color-text-secondary)"}}>Motivo: {n.risk_basis}</div>}
                </div>
                <div style={{textAlign:"right"}}>
                  <div style={{fontSize:14,fontWeight:500,color:riskColor(n.risk_score)}}>{n.risk_score}</div>
                  <div style={{fontSize:10,color:"var(--color-text-tertiary)"}}>su 100</div>
                </div>
                <div style={{width:80,height:6,background:"var(--color-background-secondary)",borderRadius:3,overflow:"hidden"}}>
                  <div style={{width:`${n.risk_score}%`,height:"100%",background:riskColor(n.risk_score),borderRadius:3}}/>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
