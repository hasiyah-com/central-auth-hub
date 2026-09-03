"use client";

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";

type Alert = { id:string; rule:string; severity:string; ip:string|null; user_id:string|null; detail:Record<string,unknown>|null; resolved:boolean; created_at:string|null };
type AlertsResponse = { data:{ alerts:Alert[]; total:number; rules:Record<string,string> } };
type ScanResponse = { scanned_minutes:number; new_alerts:number; alerts:Array<{id:string;rule:string;severity:string;ip:string|null}> };

export default function ApiAlertsPage() {
  const [data,setData]=useState<AlertsResponse["data"]|null>(null);
  const [days,setDays]=useState(7);
  const [error,setError]=useState<string|null>(null);
  const [scanning,setScanning]=useState(false);
  const [scanMsg,setScanMsg]=useState<string|null>(null);
  const [filterRule,setFilterRule]=useState("");
  const [filterResolved,setFilterResolved]=useState("");

  const load=useCallback(()=>{
    setError(null);
    let url=`/admin/api-alerts?days=${days}`;
    if(filterRule) url+=`&rule=${filterRule}`;
    if(filterResolved) url+=`&resolved=${filterResolved}`;
    clientFetch<AlertsResponse>(url).then((response)=>setData(response.data)).catch((cause)=>setError(cause.detail||"โหลด Alerts ไม่สำเร็จ"));
  },[days,filterRule,filterResolved]);
  useEffect(load,[load]);

  async function scan(){
    setScanning(true);setScanMsg(null);
    try{const response=await clientFetch<ScanResponse>("/admin/api-alerts/scan?minutes=5",{method:"POST"});setScanMsg(response.new_alerts>0?`พบ ${response.new_alerts} Alert ใหม่`:"ไม่พบพฤติกรรมผิดปกติ");load();}
    catch(cause){setScanMsg((cause as {detail?:string}).detail||"สแกนไม่สำเร็จ");}
    finally{setScanning(false);}
  }
  async function resolve(id:string){try{await clientFetch(`/admin/api-alerts/${id}/resolve`,{method:"POST"});load();}catch{}}

  const alerts=data?.alerts??[];
  const critical=alerts.filter((alert)=>alert.severity==="critical"&&!alert.resolved).length;
  const warning=alerts.filter((alert)=>alert.severity==="warning"&&!alert.resolved).length;
  const resolved=alerts.filter((alert)=>alert.resolved).length;
  const actions=<div className="cx-command-actions"><select className="cx-command-select" value={days} onChange={(event)=>setDays(Number(event.target.value))}><option value={1}>1 วัน</option><option value={7}>7 วัน</option><option value={30}>30 วัน</option></select><button className="cx-primary-action" type="button" onClick={scan} disabled={scanning}>{scanning?"กำลังสแกน…":"สแกนตอนนี้"}</button></div>;

  return <>
    <Topbar title="API Alerts" actions={actions}/>
    <main className="cx-document">
      <section className="cx-kpis three"><article className="cx-kpi danger"><span className="mono">CRITICAL · OPEN</span><strong>{critical}</strong><small>unauthorized probing</small></article><article className="cx-kpi"><span className="mono">WARNING · OPEN</span><strong>{warning}</strong><small>rate, errors, bots</small></article><article className="cx-kpi signal"><span className="mono">RESOLVED</span><strong>{resolved}</strong><small>review completed</small></article></section>
      {scanMsg&&<div className="cx-alert">{scanMsg}</div>}{error&&<div className="cx-alert danger">{error}</div>}
      <section className="cx-panel">
        <header><div><span className="mono">RULE-BASED API ANOMALY DETECTION</span><h2>รายการแจ้งเตือน API</h2></div><span className="cx-data">{alerts.length} / {data?.total??0} ALERTS</span></header>
        <div className="cx-toolbar"><label><span className="cx-filter-label">RULE</span><select value={filterRule} onChange={(event)=>setFilterRule(event.target.value)}><option value="">ทุกกฎ</option>{Object.keys(data?.rules||{}).map((rule)=><option key={rule} value={rule}>{rule}</option>)}</select></label><select value={filterResolved} onChange={(event)=>setFilterResolved(event.target.value)}><option value="">ทุกสถานะ</option><option value="false">ยังไม่ตรวจ</option><option value="true">ตรวจแล้ว</option></select></div>
        <div className="cx-alert-list">
          {data&&alerts.length===0&&<div className="cx-empty"><strong>ไม่พบ Alert ในช่วงนี้</strong><span className="mono">API SECURITY QUEUE CLEAR</span></div>}
          {alerts.map((alert)=><article key={alert.id} className={alert.resolved?"resolved":""}>
            <i className={`cx-dot ${alert.severity==="critical"?"danger":"warn"}`}><i/></i>
            <div><b>{alert.rule.replaceAll("_"," ")}</b><small className="mono">{alert.created_at?new Date(alert.created_at).toLocaleString("th-TH"):"—"} · {alert.ip||"NO IP"}</small></div>
            <span className={`cx-chip ${alert.severity==="critical"?"danger":"warn"}`}>{alert.resolved?"RESOLVED":alert.severity.toUpperCase()}</span>
            <pre>{JSON.stringify(alert.detail||{},null,2)}</pre>
            {!alert.resolved&&<button type="button" onClick={()=>resolve(alert.id)}>ทำเครื่องหมายว่าตรวจแล้ว</button>}
          </article>)}
        </div>
      </section>
    </main>
  </>;
}
