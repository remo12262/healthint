import { useState, useEffect, useRef, useCallback } from "react"

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

function riskColor(score) {
  if (score >= 80) return "#E24B4A"
  if (score >= 60) return "#EF9F27"
  if (score >= 30) return "#378ADD"
  return "#1D9E75"
}

export default function App() {
  const canvasRef = useRef(null)
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const [alerts, setAlerts] = useState([])
  const [stats, setStats] = useState({})
  const [selected, setSelected] = useState(null)
  const [nodeDetails, setNodeDetails] = useState(null)
  const [tab, setTab] = useState("graph")
  const [loading, setLoading] = useState(true)
  const posRef = useRef({})
  const velRef = useRef({})
  const animRef = useRef(null)
  const hoveredRef = useRef(null)
  const draggingRef = useRef(null)
  const dragOffRef = useRef({x:0,y:0})

  const fetchData = useCallback(async () => {
    try {
      const [gRes, aRes, sRes] = await Promise.all([
        fetch(`${API}/api/graph`),
        fetch(`${API}/api/alerts`),
        fetch(`${API}/api/stats`),
      ])
      const g = await gRes.json()
      const a = await aRes.json()
      const s = await sRes.json()
      setNodes(g.nodes || [])
      setEdges(g.edges || [])
      setAlerts(a || [])
      setStats(s || {})
      setLoading(false)
    } catch (e) {
      console.error(e)
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || nodes.length === 0) return
    const W = canvas.width, H = canvas.height
    const cx = W / 2, cy = H / 2
    nodes.forEach((n, i) => {
      if (!posRef.current[n.id]) {
        const angle = (i / nodes.length) * Math.PI * 2
        const r = Math.min(W, H) * 0.3
        posRef.current[n.id] = {
          x: cx + Math.cos(angle) * r + (Math.random()-0.5)*80,
          y: cy + Math.sin(angle) * r + (Math.random()-0.5)*80,
        }
        velRef.current[n.id] = { vx:0, vy:0 }
      }
    })
  }, [nodes])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || nodes.length === 0) return
    const ctx = canvas.getContext("2d")
    let tick = 0

    function force() {
      const W = canvas.width, H = canvas.height
      const cx = W/2, cy = H/2
      nodes.forEach(a => {
        const pa = posRef.current[a.id]
        if (!pa) return
        const vel = velRef.current[a.id] || {vx:0,vy:0}
        nodes.forEach(b => {
          if (a.id === b.id) return
          const pb = posRef.current[b.id]
          if (!pb) return
          const dx = pa.x - pb.x, dy = pa.y - pb.y
          const dist = Math.sqrt(dx*dx + dy*dy) || 1
          const f = 5000 / (dist*dist)
          vel.vx += (dx/dist)*f; vel.vy += (dy/dist)*f
        })
        vel.vx += (cx - pa.x)*0.004
        vel.vy += (cy - pa.y)*0.004
        velRef.current[a.id] = vel
      })
      edges.forEach(e => {
        const ps = posRef.current[e.source], pt = posRef.current[e.target]
        if (!ps || !pt) return
        const vs = velRef.current[e.source] || {vx:0,vy:0}
        const vt = velRef.current[e.target] || {vx:0,vy:0}
        const dx = pt.x - ps.x, dy = pt.y - ps.y
        const dist = Math.sqrt(dx*dx + dy*dy) || 1
        const f = (dist - 130) * 0.015
        vs.vx += (dx/dist)*f; vs.vy += (dy/dist)*f
        vt.vx -= (dx/dist)*f; vt.vy -= (dy/dist)*f
      })
      nodes.forEach(n => {
        if (n.id === draggingRef.current?.id) return
        const p = posRef.current[n.id]
        const v = velRef.current[n.id]
        if (!p || !v) return
        v.vx *= 0.75; v.vy *= 0.75
        p.x = Math.max(50, Math.min(canvas.width-50, p.x + v.vx))
        p.y = Math.max(40, Math.min(canvas.height-40, p.y + v.vy))
      })
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const sel = selected
      const hov = hoveredRef.current

      edges.forEach(e => {
        const ps = posRef.current[e.source], pt = posRef.current[e.target]
        if (!ps || !pt) return
        const isHl = sel && (e.source === sel || e.target === sel)
        ctx.beginPath()
        ctx.moveTo(ps.x, ps.y)
        ctx.lineTo(pt.x, pt.y)
        ctx.strokeStyle = isHl ? "rgba(29,158,117,0.7)" : "rgba(128,128,128,0.12)"
        ctx.lineWidth = isHl ? 2 : 0.8
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

      nodes.forEach(n => {
        const p = posRef.current[n.id]
        if (!p) return
        const color = NODE_COLORS[n.type] || "#888"
        const isSel = n.id === sel
        const isHov = hov && n.id === hov.id
        const isConn = sel && edges.some(e => (e.source===sel&&e.target===n.id)||(e.target===sel&&e.source===n.id))
        const alpha = sel && !isSel && !isConn ? 0.2 : 1
        const r = isSel ? 14 : isHov ? 12 : Math.max(7, Math.min(12, n.risk_score/10))

        ctx.save()
        ctx.globalAlpha = alpha
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

        ctx.font = `${isSel ? "500" : "400"} 11px sans-serif`
        ctx.fillStyle = "rgba(0,0,0,0.75)"
        ctx.textAlign = "center"
        ctx.fillText(n.label, p.x, p.y + r + 13)
        ctx.restore()
      })
    }

    function loop() {
      if (tick < 300) { force(); tick++ }
      draw()
      animRef.current = requestAnimationFrame(loop)
    }
    animRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(animRef.current)
  }, [nodes, edges, selected])

  function getNodeAt(mx, my) {
    for (let i = nodes.length-1; i >= 0; i--) {
      const n = nodes[i]; const p = posRef.current[n.id]
      if (!p) continue
      const dx = mx-p.x, dy = my-p.y
      if (Math.sqrt(dx*dx+dy*dy) < 18) return n
    }
    return null
  }

  async function selectNode(n) {
    setSelected(n ? n.id : null)
    if (n) {
      const res = await fetch(`${API}/api/node/${n.id}`)
      const data = await res.json()
      setNodeDetails(data)
    } else {
      setNodeDetails(null)
    }
  }

  function onMouseDown(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX-r.left, my = e.clientY-r.top
    const n = getNodeAt(mx, my)
    if (n) { draggingRef.current = n; const p = posRef.current[n.id]; dragOffRef.current = {x:mx-p.x,y:my-p.y} }
  }
  function onMouseMove(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX-r.left, my = e.clientY-r.top
    if (draggingRef.current) {
      const p = posRef.current[draggingRef.current.id]
      p.x = mx-dragOffRef.current.x; p.y = my-dragOffRef.current.y
      velRef.current[draggingRef.current.id] = {vx:0,vy:0}
    } else {
      hoveredRef.current = getNodeAt(mx, my)
      e.currentTarget.style.cursor = hoveredRef.current ? "pointer" : "default"
    }
  }
  function onMouseUp(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX-r.left, my = e.clientY-r.top
    const n = getNodeAt(mx, my)
    if (!draggingRef.current || Math.abs(mx-(posRef.current[draggingRef.current.id]?.x+dragOffRef.current.x||0)) < 5) {
      selectNode(selected === n?.id ? null : n)
    }
    draggingRef.current = null
  }

  async function triggerRefresh() {
    await fetch(`${API}/api/refresh`, {method:"POST"})
    setTimeout(fetchData, 3000)
  }

  const W = 680, H = 500

  return (
    <div style={{fontFamily:"var(--font-sans,sans-serif)",color:"var(--color-text-primary)",minHeight:"100vh",background:"var(--color-background-tertiary)"}}>
      {/* Header */}
      <div style={{background:"var(--color-background-primary)",borderBottom:"0.5px solid var(--color-border-tertiary)",padding:"12px 20px",display:"flex",alignItems:"center",gap:16}}>
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
          <span style={{fontSize:12,color:"var(--color-text-tertiary)"}}>{stats.nodes} nodi · {stats.edges} relazioni</span>
          <button onClick={triggerRefresh} style={{fontSize:12,padding:"4px 12px",borderRadius:6,border:"0.5px solid var(--color-border-secondary)",background:"var(--color-background-secondary)",cursor:"pointer",color:"var(--color-text-secondary)"}}>↻ Aggiorna</button>
        </div>
      </div>

      {loading && <div style={{padding:40,textAlign:"center",color:"var(--color-text-secondary)"}}>Caricamento grafo sanitario...</div>}

      {/* Graph tab */}
      {!loading && tab === "graph" && (
        <div style={{display:"flex",gap:0}}>
          <div style={{flex:1,position:"relative"}}>
            <div style={{position:"absolute",top:12,left:12,zIndex:10,background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderRadius:8,padding:"8px 12px",display:"flex",flexWrap:"wrap",gap:"6px 12px",maxWidth:460}}>
              {Object.entries(NODE_COLORS).map(([type,color]) => (
                <div key={type} style={{display:"flex",alignItems:"center",gap:4,fontSize:11,color:"var(--color-text-secondary)"}}>
                  <div style={{width:7,height:7,borderRadius:"50%",background:color}}/>
                  {type}
                </div>
              ))}
            </div>
            <canvas ref={canvasRef} width={W} height={H}
              style={{width:"100%",height:500,display:"block"}}
              onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp}
              onMouseLeave={()=>{draggingRef.current=null;hoveredRef.current=null}}
            />
          </div>

          {/* Side panel */}
          <div style={{width:240,borderLeft:"0.5px solid var(--color-border-tertiary)",background:"var(--color-background-primary)",padding:16,overflowY:"auto",maxHeight:500}}>
            {!nodeDetails && <p style={{fontSize:12,color:"var(--color-text-tertiary)"}}>Clicca un nodo per dettagli</p>}
            {nodeDetails && (
              <div>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:8}}>
                  <span style={{fontSize:11,padding:"2px 8px",borderRadius:4,background:NODE_COLORS[nodeDetails.node?.type]+"22",color:NODE_COLORS[nodeDetails.node?.type],fontWeight:500}}>{nodeDetails.node?.type}</span>
                  <span style={{fontSize:12,padding:"2px 8px",borderRadius:4,background:riskColor(nodeDetails.node?.risk_score)+"22",color:riskColor(nodeDetails.node?.risk_score),fontWeight:500}}>Risk {nodeDetails.node?.risk_score}</span>
                </div>
                <div style={{fontSize:15,fontWeight:500,marginBottom:6}}>{nodeDetails.node?.label}</div>
                {nodeDetails.node?.region && <div style={{fontSize:12,color:"var(--color-text-tertiary)",marginBottom:8}}>📍 {nodeDetails.node.region}</div>}
                <div style={{fontSize:12,color:"var(--color-text-secondary)",lineHeight:1.5,marginBottom:12}}>{nodeDetails.node?.description}</div>
                {nodeDetails.relations?.length > 0 && (
                  <>
                    <div style={{fontSize:11,fontWeight:500,color:"var(--color-text-tertiary)",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:6}}>Relazioni ({nodeDetails.relations.length})</div>
                    {nodeDetails.relations.map((r,i) => {
                      const isSource = r.source === nodeDetails.node?.id
                      const other = isSource ? r.target_label : r.source_label
                      return (
                        <div key={i} style={{fontSize:12,padding:"6px 8px",borderRadius:6,background:"var(--color-background-secondary)",marginBottom:4}}>
                          <div style={{color:"var(--color-text-primary)",fontWeight:500}}>{isSource?"→":"←"} {other}</div>
                          <div style={{fontSize:11,color:"var(--color-text-tertiary)"}}>{r.type}</div>
                        </div>
                      )
                    })}
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Alerts tab */}
      {!loading && tab === "alerts" && (
        <div style={{padding:20,maxWidth:800}}>
          <h2 style={{fontSize:15,fontWeight:500,marginBottom:16}}>Alert predittivi SSN ({alerts.length})</h2>
          {alerts.length === 0 && <p style={{color:"var(--color-text-tertiary)",fontSize:13}}>Nessun alert. Clicca Aggiorna per generare nuovi alert.</p>}
          {alerts.map((a,i) => (
            <div key={i} style={{background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderLeft:`3px solid ${SEVERITY_COLOR[a.severity]||"#888"}`,borderRadius:8,padding:"12px 16px",marginBottom:12}}>
              <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:6}}>
                <span style={{fontSize:11,fontWeight:500,padding:"2px 8px",borderRadius:4,background:SEVERITY_COLOR[a.severity]+"22",color:SEVERITY_COLOR[a.severity]}}>{a.severity}</span>
                <span style={{fontSize:14,fontWeight:500}}>{a.title}</span>
              </div>
              <p style={{fontSize:13,color:"var(--color-text-secondary)",marginBottom:8,lineHeight:1.5}}>{a.description}</p>
              {a.timeframe && <div style={{fontSize:12,color:"var(--color-text-tertiary)"}}>⏱ Timeframe: {a.timeframe}</div>}
              {a.recommendation && <div style={{fontSize:12,color:"var(--color-text-secondary)",marginTop:6,padding:"6px 8px",background:"var(--color-background-secondary)",borderRadius:4}}>💡 {a.recommendation}</div>}
            </div>
          ))}
        </div>
      )}

      {/* Risk scores tab */}
      {!loading && tab === "risk" && (
        <div style={{padding:20,maxWidth:700}}>
          <h2 style={{fontSize:15,fontWeight:500,marginBottom:16}}>Risk Score — Entità ad alto rischio SSN</h2>
          <div style={{display:"grid",gap:8}}>
            {nodes.sort((a,b)=>b.risk_score-a.risk_score).slice(0,15).map((n,i) => (
              <div key={n.id} style={{background:"var(--color-background-primary)",border:"0.5px solid var(--color-border-tertiary)",borderRadius:8,padding:"10px 16px",display:"flex",alignItems:"center",gap:12}}>
                <span style={{fontSize:12,color:"var(--color-text-tertiary)",minWidth:20}}>#{i+1}</span>
                <div style={{width:8,height:8,borderRadius:"50%",background:NODE_COLORS[n.type]||"#888"}}/>
                <div style={{flex:1}}>
                  <div style={{fontWeight:500,fontSize:13}}>{n.label}</div>
                  <div style={{fontSize:11,color:"var(--color-text-tertiary)"}}>{n.type} · {n.region||"—"}</div>
                </div>
                <div style={{textAlign:"right"}}>
                  <div style={{fontSize:14,fontWeight:500,color:riskColor(n.risk_score)}}>{n.risk_score}</div>
                  <div style={{fontSize:10,color:"var(--color-text-tertiary)"}}>risk score</div>
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
