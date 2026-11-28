"""Mock Plimsoll Core + Insight for UI testing. Mirrors the real response
shapes, the 409 bodies, and Flask's RFC 1123 datetime serialisation."""
import json, sys, copy
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

NOW = datetime.now(timezone.utc)
ts = lambda mins: format_datetime(NOW - timedelta(minutes=mins), usegmt=True)

SKUS = [
 {"sku":"HL-PAL-0001","description":"Pallet wrap, 500mm clear","uom":"ROLL","hazard_class":None},
 {"sku":"HL-CRT-0002","description":"Carton, double wall 600x400x400","uom":"EA","hazard_class":None},
 {"sku":"HL-BAT-0003","description":"Lithium-ion cell pack 18650","uom":"EA","hazard_class":"UN3480"},
 {"sku":"HL-FLU-0004","description":"Hydraulic fluid ISO 46, 20L","uom":"DRUM","hazard_class":"UN1268"},
 {"sku":"HL-STR-0005","description":"Strapping, polyester 16mm","uom":"ROLL","hazard_class":None}]
LOCS = [{"code":c,"zone":z,"capacity":cap} for c,z,cap in [
 ("RECV-01","RECV",2000),("RECV-02","RECV",2000),("A-01-01","BULK",800),("A-01-02","BULK",800),
 ("A-02-01","BULK",800),("B-01-01","PICK",200),("B-01-02","PICK",200),("B-02-01","PICK",200),("DISP-01","DISP",5000)]]
ZONE = {l["code"]:l["zone"] for l in LOCS}
S = {}
def reset():
    S["stock"] = {("HL-PAL-0001","A-01-01"):240,("HL-PAL-0001","B-01-01"):36,("HL-CRT-0002","A-01-02"):600,
                  ("HL-CRT-0002","B-01-02"):120,("HL-BAT-0003","A-02-01"):90,("HL-STR-0005","B-02-01"):48}
    S["moves"] = []
    for i,((sku,loc),q) in enumerate(S["stock"].items()):
        S["moves"].append(dict(id=i+1,occurred_at=ts(600),sku=sku,from_location=None,to_location=loc,qty=q,reason="ADJUST",actor="seed/opening-balance"))
    S["receipts"] = {"RCV-5001":{"id":"RCV-5001","carrier":"Harbourline Freight","status":"EXPECTED","arrived_at":None,
        "lines":[{"line_no":1,"sku":"HL-CRT-0002","qty_expected":300,"qty_received":0},{"line_no":2,"sku":"HL-STR-0005","qty_expected":60,"qty_received":0}]},
        "RCV-5002":{"id":"RCV-5002","carrier":"Coastal Haulage","status":"EXPECTED","arrived_at":None,
        "lines":[{"line_no":1,"sku":"HL-BAT-0003","qty_expected":40,"qty_received":0}]}}
    S["orders"] = {"ORD-7001":{"id":"ORD-7001","customer":"Austral Distribution","status":"NEW","created_at":ts(95),
        "lines":[{"line_no":1,"sku":"HL-PAL-0001","qty":48,"qty_picked":0},{"line_no":2,"sku":"HL-CRT-0002","qty":80,"qty_picked":0}]},
        "ORD-6990":{"id":"ORD-6990","customer":"Prestons Retail Group","status":"DISPATCHED","created_at":ts(1500),
        "lines":[{"line_no":1,"sku":"HL-STR-0005","qty":12,"qty_picked":12}]}}
    S["shipments"] = {"SHP-1001":"in-transit","SHP-2002":"delayed","SHP-3003":"customs-hold","SHP-6990":"in-transit"}
reset()
def mv(sku,frm,to,q,reason,actor):
    S["moves"].append(dict(id=len(S["moves"])+1,occurred_at=ts(0),sku=sku,from_location=frm,to_location=to,qty=q,reason=reason,actor=actor))
def add(sku,loc,q): S["stock"][(sku,loc)] = S["stock"].get((sku,loc),0)+q
def stock_lines(sku=None,loc=None):
    out=[{"sku":k[0],"location":k[1],"zone":ZONE[k[1]],"qty":v} for k,v in sorted(S["stock"].items()) if (not sku or k[0]==sku) and (not loc or k[1]==loc)]
    return {"lines":out,"on_hand":sum(x["qty"] for x in out)}
def recon():
    led={}
    for m in S["moves"]:
        if m["to_location"]: led[(m["sku"],m["to_location"])]=led.get((m["sku"],m["to_location"]),0)+m["qty"]
        if m["from_location"]: led[(m["sku"],m["from_location"])]=led.get((m["sku"],m["from_location"]),0)-m["qty"]
    keys=set(led)|set(S["stock"]); d=[]
    for k in sorted(keys):
        b,l=S["stock"].get(k,0),led.get(k,0)
        if b!=l: d.append({"sku":k[0],"location":k[1],"balance":b,"ledger":l,"difference":b-l})
    return {"host":"harbourline-reports-7d9c-x2k4p","balanced":not d,"verdict":"OUT-OF-BALANCE" if d else "IN-BALANCE","discrepancy_count":len(d),"discrepancies":d}

class H(SimpleHTTPRequestHandler):
    def __init__(s,*a,**k): super().__init__(*a,directory=sys.argv[1],**k)
    def log_message(s,*a): pass
    def j(s,obj,code=200):
        b=json.dumps(obj).encode(); s.send_response(code); s.send_header("Content-Type","application/json"); s.send_header("Content-Length",str(len(b))); s.end_headers(); s.wfile.write(b)
    def do_GET(s):
        u=urlparse(s.path); p=u.path; q={k:v[0] for k,v in parse_qs(u.query).items()}
        if p=="/__reset": reset(); return s.j({"ok":True})
        if p=="/__corrupt": add("HL-BAT-0003","A-02-01",7); return s.j({"ok":True})
        if p=="/api/health": return s.j({"status":"ok","host":"harbourline-api-6b984cd588-m5b6q","env":"kubernetes"})
        if p=="/api/stock": return s.j(stock_lines(q.get("sku"),q.get("location")))
        if p=="/api/skus": return s.j(SKUS)
        if p=="/api/locations": return s.j(LOCS)
        if p=="/api/movements": return s.j(list(reversed(S["moves"]))[:int(q.get("limit",50))])
        if p=="/api/receipts": return s.j([{"id":r["id"],"carrier":r["carrier"],"status":r["status"],"arrived_at":r["arrived_at"],
             "expected":sum(l["qty_expected"] for l in r["lines"]),"received":sum(l["qty_received"] for l in r["lines"])} for r in S["receipts"].values()])
        if p.startswith("/api/receipts/"): r=S["receipts"].get(p.split("/")[3]); return s.j(r) if r else s.j({"error":"no such receipt"},404)
        if p=="/api/orders": return s.j([{"id":o["id"],"customer":o["customer"],"status":o["status"],"created_at":o["created_at"],
             "ordered":sum(l["qty"] for l in o["lines"]),"picked":sum(l["qty_picked"] for l in o["lines"])} for o in S["orders"].values()])
        if p.startswith("/api/orders/"): o=S["orders"].get(p.split("/")[3]); return s.j(o) if o else s.j({"error":"no such order"},404)
        if p=="/api/shipments": return s.j({k:{"origin":"-","destination":"-","status":v} for k,v in S["shipments"].items()})
        if p=="/reports/reconciliation": return s.j(recon())
        if p=="/reports/stock":
            by={}; bz={}
            for (sku,loc),v in S["stock"].items(): by.setdefault(sku,{"qty":0,"locations":0}); by[sku]["qty"]+=v; by[sku]["locations"]+=1; bz[ZONE[loc]]=bz.get(ZONE[loc],0)+v
            return s.j({"by_sku":by,"by_zone":bz,"on_hand":sum(S["stock"].values())})
        if p=="/reports/throughput":
            br={}; ba={}
            for m in S["moves"]:
                br.setdefault(m["reason"],{"movements":0,"units":0}); br[m["reason"]]["movements"]+=1; br[m["reason"]]["units"]+=m["qty"]
                ba.setdefault(m["actor"],{"movements":0,"units":0}); ba[m["actor"]]["movements"]+=1; ba[m["actor"]]["units"]+=m["qty"]
            return s.j({"by_reason":br,"by_actor":dict(sorted(ba.items(),key=lambda x:-x[1]["units"]))})
        if p=="/reports/open-orders": return s.j({"open_orders":[],"count":0})
        if p=="/reports/summary": return s.j({"total":3,"by_status":{}})
        return super().do_GET()
    def do_POST(s):
        n=int(s.headers.get("Content-Length",0)); b=json.loads(s.rfile.read(n) or b"{}"); p=urlparse(s.path).path; actor=b.get("actor","x")
        if p.endswith("/receive"):
            r=S["receipts"].get(p.split("/")[3]); l=next((x for x in r["lines"] if x["line_no"]==b["line_no"]),None)
            if l["qty_received"]+b["qty"]>l["qty_expected"]: return s.j({"error":"rejected by database constraint","constraint":"no_silent_over_receipt"},409)
            l["qty_received"]+=b["qty"]; add(l["sku"],"RECV-01",b["qty"]); mv(l["sku"],None,"RECV-01",b["qty"],"RECEIPT",actor)
            if r["status"]=="EXPECTED": r["status"]="ARRIVED"; r["arrived_at"]=ts(0)
            return s.j({"received":b["qty"],"sku":l["sku"],"into":"RECV-01","actor":actor},201)
        if p=="/api/putaway":
            k=(b["sku"],b["from"])
            if b["to"] not in ZONE: return s.j({"error":"unknown sku or location","constraint":"stock_location_fkey"},400)
            if S["stock"].get(k,0)<b["qty"]: return s.j({"error":"insufficient stock at source","sku":b["sku"],"location":b["from"],"requested":b["qty"]},409)
            S["stock"][k]-=b["qty"]; add(b["sku"],b["to"],b["qty"]); mv(b["sku"],b["from"],b["to"],b["qty"],"PUTAWAY",actor)
            return s.j({"moved":b["qty"],"sku":b["sku"],"from":b["from"],"to":b["to"],"actor":actor},201)
        if p.endswith("/pick"):
            o=S["orders"][p.split("/")[3]]; l=next(x for x in o["lines"] if x["line_no"]==b["line_no"]); out=l["qty"]-l["qty_picked"]; q=b.get("qty",out)
            if q>out: return s.j({"error":"exceeds outstanding quantity","outstanding":out},409)
            src=sorted([(loc,v) for (sk,loc),v in S["stock"].items() if sk==l["sku"] and v>0 and ZONE[loc] in("PICK","BULK")],key=lambda x:(ZONE[x[0]]!="PICK",x[1]))
            if sum(v for _,v in src)<q: return s.j({"error":"insufficient stock for sku","sku":l["sku"],"requested":q,"available":sum(v for _,v in src)},409)
            rem=q; alloc=[]
            for loc,v in src:
                if not rem: break
                t=min(rem,v); S["stock"][(l["sku"],loc)]-=t; mv(l["sku"],loc,"DISP-01",t,"PICK",actor); alloc.append({"location":loc,"zone":ZONE[loc],"qty":t}); rem-=t
            add(l["sku"],"DISP-01",q); l["qty_picked"]+=q
            o["status"]="PICKED" if all(x["qty_picked"]>=x["qty"] for x in o["lines"]) else "PICKING"
            return s.j({"picked":q,"sku":l["sku"],"allocation":alloc,"order_status":o["status"],"actor":actor},201)
        if p.endswith("/dispatch"):
            o=S["orders"][p.split("/")[3]]
            if o["status"]!="PICKED": return s.j({"error":"order is not fully picked","status":o["status"]},409)
            for l in o["lines"]: S["stock"][(l["sku"],"DISP-01")]-=l["qty_picked"]; mv(l["sku"],"DISP-01",None,l["qty_picked"],"DISPATCH",actor)
            o["status"]="DISPATCHED"; sid="SHP-"+o["id"].split("-")[-1]; S["shipments"][sid]="in-transit"
            return s.j({"dispatched":o["id"],"shipment":sid,"carrier":b.get("carrier","Harbourline Freight"),"actor":actor},201)
        return s.j({"error":"not found"},404)
if __name__ == "__main__":
    # usage: mock_backend.py <web dir to serve> <port>
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
