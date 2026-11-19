#!/usr/bin/env python3
"""
Job Bot: finds fresher-friendly jobs by location (any job type, remote too),
rates them against YOUR resume, and links straight to the company's own
application form (no job-board middlemen).

    python job_bot.py --resume resume.pdf --locations "Pune,Kolhapur,Bangalore" --remote

Opens/creates jobs.html (interactive dashboard) and jobs.csv. See README.md.
It never submits anything for you. You review and apply.
"""
import argparse
import csv
import datetime as dt
import html
import json
import math
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

UA = {"User-Agent": "Mozilla/5.0 (JobBot; personal job search)"}

# ----------------------------------------------------------------------------
# 1. Where jobs come from: companies' own hiring systems (public JSON APIs).
#    Every link produced is the company's own application page.
#    Slugs that don't exist are skipped silently. Add your own in companies.txt
#    (same format) or with --add-url https://company.com/careers
# ----------------------------------------------------------------------------
SEED_COMPANIES = """
greenhouse: razorpay postman druva whatfix mongodb cloudflare twilio elastic gitlab datadog stripe okta databricks coinswitch thoughtspot
lever: cred meesho zeta palantir
ashby: notion ramp linear
smartrecruiters: Visa BoschGroup
"""

# Big hirers of freshers (IT services, BPO, support). Official career homepages:
# open, search your city, apply there. Not scraped (they need a browser).
CAREER_PAGES = [
    ("Infosys BPM", "Support / BPO", "https://www.infosysbpm.com/careers/"),
    ("Wipro", "IT / Support", "https://careers.wipro.com/"),
    ("TCS", "IT", "https://www.tcs.com/careers"),
    ("Mphasis", "Service desk / IT", "https://careers.mphasis.com/"),
    ("WNS", "Support / BPO", "https://www.wns.com/careers"),
    ("Concentrix", "Support / BPO", "https://careers.concentrix.com/"),
    ("Teleperformance", "Support / BPO", "https://www.teleperformance.com/en-us/careers/"),
    ("Genpact", "Operations / BPO", "https://www.genpact.com/careers"),
    ("Cognizant", "IT / Ops", "https://careers.cognizant.com/"),
    ("Capgemini", "IT / Ops", "https://www.capgemini.com/in-en/careers/"),
    ("HCLTech", "IT / Support", "https://www.hcltech.com/careers"),
    ("Tech Mahindra", "IT / Support", "https://careers.techmahindra.com/"),
    ("Accenture", "IT / Ops", "https://www.accenture.com/in-en/careers"),
    ("HPE", "Tech support", "https://careers.hpe.com/"),
    ("IBM", "IT", "https://www.ibm.com/careers"),
    ("Persistent", "IT", "https://www.persistent.com/careers/"),
    ("LTIMindtree", "IT", "https://www.ltimindtree.com/careers/"),
    ("Amazon", "Ops / Support / IT", "https://www.amazon.jobs/en/"),
]

DEFAULT_ROLES = ("developer,engineer,software,php,laravel,full stack,devops,support,"
                 "service desk,associate,trainee,executive,analyst,intern,junior,fresher")

SKILLS = """php laravel codeigniter mysql sql javascript jquery ajax bootstrap html css react node
java python aws ec2 s3 linux nginx jenkins docker kubernetes git github ci/cd devops api rest
wordpress shopify support troubleshooting helpdesk customer communication excel typing
hindi marathi english sales marketing seo content""".split()

STOP = set("""a an the and or of to in for with on at by is are be as from that this we you your our will have
has can not all any but if it its their they them who what which into more about also other such than then
there these those was were been being should would could may must per etc job role work team ability strong
good knowledge experience years year skills required requirements responsibilities candidate company""".split())

# ----------------------------------------------------------------------------
# Fetchers: each yields dicts with title, company, location, remote, url, desc, posted
# ----------------------------------------------------------------------------

def get_json(url, timeout=20):
    with urlopen(Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fetch_greenhouse(slug):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in d.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") or ""
        yield dict(title=j.get("title", ""), company=j.get("company_name") or slug.title(),
                   location=loc, remote="remote" in loc.lower(), url=j.get("absolute_url", ""),
                   desc=strip_html(j.get("content", "")), posted=(j.get("updated_at") or "")[:10])


def fetch_lever(slug):
    for p in get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        cats = p.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or []) or ""
        ts = p.get("createdAt")
        posted = dt.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else ""
        yield dict(title=p.get("text", ""), company=slug.title(), location=loc,
                   remote=p.get("workplaceType") == "remote" or "remote" in loc.lower(),
                   url=p.get("applyUrl") or p.get("hostedUrl", ""),
                   desc=p.get("descriptionPlain", "") or "", posted=posted)


def fetch_ashby(slug):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for j in d.get("jobs", []):
        loc = j.get("location", "") or ""
        yield dict(title=j.get("title", ""), company=slug.title(), location=loc,
                   remote=bool(j.get("isRemote")) or "remote" in loc.lower(),
                   url=j.get("applyUrl") or j.get("jobUrl", ""),
                   desc=j.get("descriptionPlain", "") or "", posted=(j.get("publishedAt") or "")[:10])


def fetch_workable(slug):
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    for j in d.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        yield dict(title=j.get("title", ""), company=d.get("name") or slug.title(), location=loc,
                   remote=bool(j.get("telecommuting")), url=j.get("url") or j.get("shortlink", ""),
                   desc=strip_html(j.get("description", "")), posted=(j.get("published_on") or "")[:10])


def fetch_smartrecruiters(slug):
    d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&country=in")
    for j in d.get("content", []):
        l = j.get("location") or {}
        loc = ", ".join(x for x in (l.get("city"), l.get("country", "").upper()) if x)
        yield dict(title=j.get("name", ""), company=slug, location=loc, remote=bool(l.get("remote")),
                   url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", desc="",
                   posted=(j.get("releasedDate") or "")[:10])


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "workable": fetch_workable, "smartrecruiters": fetch_smartrecruiters}

DISCOVER = {
    "greenhouse": r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)",
    "lever": r"jobs\.lever\.co/([A-Za-z0-9_-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)",
    "workable": r"apply\.workable\.com/([A-Za-z0-9_-]+)",
    "smartrecruiters": r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)",
}


def parse_companies(text):
    out = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        plat, rest = line.split(":", 1)
        plat = plat.strip().lower()
        if plat in FETCHERS:
            out += [(plat, s) for s in rest.replace(",", " ").split()]
    return out


def discover(url):
    """Find which hiring system a company's careers page uses."""
    body = urlopen(Request(url, headers=UA), timeout=20).read().decode("utf-8", "replace")
    found = set()
    for plat, pat in DISCOVER.items():
        for m in re.finditer(pat, body):
            if m.group(1) not in ("embed", "job_board", "api"):
                found.add((plat, m.group(1)))
    return sorted(found)


def collect(entries, workers=12):
    def run(e):
        try:
            return e, list(FETCHERS[e[0]](e[1])), None
        except Exception as ex:  # 404 = company not on that system; skip quietly
            return e, [], str(ex)

    jobs, ok = [], 0
    with ThreadPoolExecutor(workers) as ex:
        for e, js, err in ex.map(run, entries):
            if err is None:
                ok += 1
                for j in js:
                    j["source"] = e[0]
                jobs += js
    return jobs, ok


# ----------------------------------------------------------------------------
# 2. Filter by location / remote
# ----------------------------------------------------------------------------
ALIASES = {"bangalore": ["bengaluru"], "bengaluru": ["bangalore"], "mumbai": ["navi mumbai", "thane"],
           "delhi": ["new delhi", "gurgaon", "gurugram", "noida"], "pune": ["hinjewadi", "baner", "kharadi"]}
REMOTE_OK = ("india", "anywhere", "worldwide", "global", "apac", "asia")


def location_hit(job, locs, want_remote):
    l = job["location"].lower()
    for x in locs:
        for name in [x.lower()] + ALIASES.get(x.lower(), []):
            if name in l:
                return x
    if l.strip() in ("india", "pan india", "india (any)"):
        return "India-wide"
    if want_remote and (job["remote"] or "remote" in l):
        if any(w in l for w in REMOTE_OK) or l.strip() in ("", "remote"):
            return "Remote"
    return None


# ----------------------------------------------------------------------------
# 3. Rate against the resume (0-100)
#    45 skills/keyword match | 15 title fits your target roles |
#    25 fresher-friendliness | 15 location
# ----------------------------------------------------------------------------
SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head|director|manager|vp|architect|chief)\b", re.I)
FRESHER = re.compile(r"\b(fresher|freshers|graduate|new grad|entry[- ]level|trainee|intern|internship|"
                     r"apprentice|junior|jr\.?|associate|no experience|0\s*[-–to]+\s*[12]\s*years?)\b", re.I)
EXP1 = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:[-–]|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)[^.\n]{0,40}?experience", re.I)
EXP2 = re.compile(r"experience[^.\n]{0,30}?(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I)
TYPES = [("Support", r"support|service desk|helpdesk|help desk|customer|voice|chat|bpo|call cent|care"),
         ("Business", r"data entry|back office"),
         ("Tech", r"developer|engineer|software|devops|sre|qa|tester|programmer|data|cloud|php|laravel|java|python|full.?stack|web"),
         ("Business", r"sales|marketing|\bhr\b|recruit|finance|account|operations|back office|data entry|content|business|analyst|admin|coordinator|executive")]


def toks(s):
    out = []
    for t in re.findall(r"[a-z][a-z0-9+#./\-]+", s.lower()):
        t = t.strip(".-/")
        if len(t) > 2 and t not in STOP:
            out.append(t)
    return out


def min_years(text):
    vals = [int(m.group(1)) for rx in (EXP1, EXP2) for m in rx.finditer(text) if int(m.group(1)) <= 20]
    return min(vals) if vals else None


def job_type(title):
    t = title.lower()
    for name, pat in TYPES:
        if re.search(pat, t):
            return name
    return "Other"


def rate(jobs, resume, roles, max_years, include_senior, min_score):
    docs = [Counter(toks((j["title"] + " ") * 3 + j["desc"])) for j in jobs]
    df = Counter()
    for d in docs:
        df.update(d.keys())
    n = max(len(docs), 1)
    idf = lambda t: math.log((1 + n) / (1 + df[t])) + 1
    rcount = Counter(toks(resume))
    rv = {t: (1 + math.log(c)) * idf(t) for t, c in rcount.items() if t in df}
    sims = []
    for d in docs:
        jv = {t: (1 + math.log(c)) * idf(t) for t, c in d.items()}
        norm = math.sqrt(sum(v * v for v in jv.values())) or 1
        sims.append(sum(rv.get(t, 0) * v for t, v in jv.items()) / norm)
    top = max(sims) if sims and max(sims) > 0 else 1
    rskills = {s for s in SKILLS if s in resume.lower()}
    roles = [r.strip().lower() for r in roles.split(",") if r.strip()]

    kept = []
    for j, sim in zip(jobs, sims):
        title, text = j["title"], j["title"] + " " + j["desc"]
        years = min_years(j["desc"])
        if not include_senior and SENIOR.search(title):
            continue
        if years is not None and years > max_years:
            continue
        hits = sum(1 for r in roles if r in title.lower())
        skill = 45 * sim / top
        tscore = 15 if hits >= 2 else 10 if hits == 1 else 0
        if FRESHER.search(title):
            fresh = 25
        elif years is not None:
            fresh = 22 if years <= 1 else 10
        elif FRESHER.search(j["desc"]):
            fresh = 18
        else:
            fresh = 10
        lh = j["loc_hit"]
        lscore = 12 if lh == "Remote" else 10 if lh == "India-wide" else 15
        score = round(skill + tscore + fresh + lscore)
        if score < min_score:
            continue
        low = text.lower()
        j.update(score=score, rating=round(score / 20 * 2) / 2, years=years, type=job_type(title),
                 matched=sorted(s for s in rskills if re.search(r"\b" + re.escape(s) + r"\b", low))[:8])
        j["desc"] = j["desc"][:240]
        kept.append(j)
    kept.sort(key=lambda x: (x["score"], x["posted"]), reverse=True)
    return kept


# ----------------------------------------------------------------------------
# 4. Resume reading
# ----------------------------------------------------------------------------

def read_resume(path):
    p = path.lower()
    try:
        if p.endswith(".pdf"):
            from pypdf import PdfReader
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
        if p.endswith(".docx"):
            import docx
            return "\n".join(par.text for par in docx.Document(path).paragraphs)
    except ImportError:
        sys.exit("Install the reader first:  pip install pypdf python-docx")
    return open(path, encoding="utf-8", errors="ignore").read()


# ----------------------------------------------------------------------------
# 5. Output: interactive dashboard + CSV
# ----------------------------------------------------------------------------
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Job Bot</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#14181f;--mut:#5b6573;--line:#e2e6ec;--acc:#2457d6;--good:#1a7f4b;--chip:#eef2fb}
@media(prefers-color-scheme:dark){:root{--bg:#0f1318;--card:#171c23;--fg:#e8ecf2;--mut:#9aa6b6;--line:#262d37;--acc:#7aa2ff;--good:#4cc38a;--chip:#1f2a3d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:16px}h1{font-size:22px;margin:4px 0}.sub{color:var(--mut);margin:0 0 14px}
.banner{background:#fff3cd;color:#664d03;border-radius:8px;padding:8px 12px;margin-bottom:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.bar input,.bar select{padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit}
.bar input[type=search]{flex:1;min-width:180px}.bar label{display:flex;align-items:center;gap:6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:10px;display:grid;grid-template-columns:64px 1fr auto;gap:12px;align-items:center}
.card.done{opacity:.5}.score{text-align:center}.score b{font-size:22px;display:block}.score span{font-size:12px;color:var(--mut)}
.meter{height:4px;background:var(--line);border-radius:4px;margin-top:4px}.meter i{display:block;height:4px;background:var(--good);border-radius:4px}
.t{font-weight:600}.m{color:var(--mut);font-size:13px;margin-top:2px}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;margin:4px 4px 0 0;font-size:12px}
a.apply{background:var(--acc);color:#fff;text-decoration:none;padding:9px 14px;border-radius:8px;font-weight:600;white-space:nowrap;display:inline-block}
.done-l{display:block;font-size:12px;color:var(--mut);margin-top:6px;text-align:center}
h2{font-size:17px;margin:24px 0 8px}.pages{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px}
.pages a{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;text-decoration:none;color:var(--fg)}
.pages small{display:block;color:var(--mut)}.empty{color:var(--mut);padding:24px;text-align:center}
@media(max-width:600px){.card{grid-template-columns:52px 1fr}.act{grid-column:1/-1}a.apply{width:100%;text-align:center}}
</style></head><body><div class="wrap">
<h1>Job Bot</h1><p class="sub" id="sub"></p><div id="banner"></div>
<div class="bar"><input type="search" id="q" placeholder="Search title, company, skill">
<select id="loc"></select><select id="typ"></select>
<select id="min"><option value="0">Any rating</option><option value="3">3 stars +</option><option value="3.5">3.5 +</option><option value="4">4 stars +</option></select>
<label><input type="checkbox" id="rem"> Remote only</label><label><input type="checkbox" id="hide"> Hide applied</label></div>
<div id="list"></div>
<h2>Hiring pages to check directly (BPO, IT services, support)</h2><div class="pages" id="pages"></div>
</div><script>
const DATA=__DATA__,META=__META__,$=i=>document.getElementById(i);
const st={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
function opts(sel,first,vals){sel.append(new Option(first,""));vals.forEach(v=>sel.append(new Option(v,v)))}
opts($("loc"),"All locations",[...new Set(DATA.map(d=>d.loc_hit))].sort());
opts($("typ"),"All job types",[...new Set(DATA.map(d=>d.type))].sort());
$("sub").textContent=`${DATA.length} matches for ${META.locations} • generated ${META.when} • each button opens the company's own application page`;
if(META.demo)$("banner").append(Object.assign(el("div","banner","DEMO DATA: sample jobs with fake links. Run the bot with your resume for real results.")));
function render(){
 const q=$("q").value.toLowerCase(),L=$("loc").value,T=$("typ").value,M=+$("min").value,R=$("rem").checked,H=$("hide").checked;
 const box=$("list");box.textContent="";let n=0;
 DATA.forEach(d=>{
  const done=st.get("done:"+d.url)==="1";
  if(L&&d.loc_hit!==L||T&&d.type!==T||d.rating<M||R&&d.loc_hit!=="Remote"||H&&done)return;
  if(q&&!(d.title+" "+d.company+" "+d.matched.join(" ")).toLowerCase().includes(q))return;
  n++;const c=el("div","card"+(done?" done":""));
  const s=el("div","score");s.append(el("b",null,d.rating.toFixed(1)),el("span",null,"of 5"));
  const m=el("div","meter"),i=el("i");i.style.width=d.score+"%";m.append(i);s.append(m);
  const b=el("div");b.append(el("div","t",d.title),el("div","m",d.company+" • "+(d.location||"n/a")+(d.posted?" • "+d.posted:"")));
  [d.type,d.years!=null?d.years+"+ yrs":"exp not stated",...d.matched].forEach(x=>b.append(el("span","chip",x)));
  const a=el("div","act"),l=el("a","apply","Apply on company site ↗");l.href=d.url;l.target="_blank";l.rel="noopener noreferrer";
  const lab=el("label","done-l"),cb=document.createElement("input");cb.type="checkbox";cb.checked=done;
  cb.onchange=()=>{st.set("done:"+d.url,cb.checked?"1":"0");render()};lab.append(cb," Applied");a.append(l,lab);
  c.append(s,b,a);box.append(c)});
 if(!n)box.append(el("div","empty","No jobs match these filters."));
}
["q","loc","typ","min","rem","hide"].forEach(i=>$(i).addEventListener("input",render));
META.careers.forEach(([n,c,u])=>{const a=el("a");a.href=u;a.target="_blank";a.rel="noopener noreferrer";a.append(n,Object.assign(el("small",null,c)));$("pages").append(a)});
render();
</script></body></html>"""


def write_outputs(jobs, meta, out):
    data = json.dumps(jobs, ensure_ascii=False).replace("</", "<\\/")
    page = PAGE.replace("__DATA__", data).replace("__META__", json.dumps(meta).replace("</", "<\\/"))
    open(out, "w", encoding="utf-8").write(page)
    csv_path = re.sub(r"\.html?$", "", out) + ".csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rating", "score", "title", "company", "location", "type", "posted", "apply_link"])
        for j in jobs:
            w.writerow([j["rating"], j["score"], j["title"], j["company"], j["location"], j["type"], j["posted"], j["url"]])
    return csv_path


DEMO_RESUME = "Fresher B.Tech Computer Science PHP Laravel CodeIgniter MySQL JavaScript jQuery Ajax Bootstrap AWS Linux Nginx Jenkins Docker Git support troubleshooting"
DEMO_JOBS = [
    ("PHP Laravel Developer (Fresher)", "Demo Infotech", "Pune", False, "Fresher. Core PHP, Laravel, MySQL, jQuery, Ajax, Bootstrap."),
    ("Technical Support Engineer (Service Desk L1)", "Demo Services", "Pune", False, "Graduate freshers. Troubleshooting, Windows, Linux basics, customer communication."),
    ("DevOps Engineer Trainee", "Demo Cloud", "Pune", False, "0-1 years experience. AWS, Linux, Docker, Jenkins, Git, Nginx."),
    ("Customer Support Executive (Voice)", "Demo BPO", "Kolhapur", False, "Any graduate. Communication in English, Hindi and Marathi. Immediate joining."),
    ("Junior Full Stack Developer", "Demo Labs", "Remote, India", True, "0-2 years experience. JavaScript, MySQL, REST API, Git."),
    ("Data Entry Executive", "Demo Corp", "Kolhapur", False, "Freshers welcome. Typing, Excel, attention to detail."),
    ("Software Engineer", "Demo Systems", "Bengaluru", False, "2+ years of experience in Java Spring. AWS preferred."),
    ("Senior PHP Developer", "Demo Soft", "Pune", False, "5+ years of experience in Laravel."),
]


def main():
    ap = argparse.ArgumentParser(description="Fresher job finder with direct company apply links")
    ap.add_argument("--resume", help=".pdf, .docx or .txt")
    ap.add_argument("--locations", default="Pune,Kolhapur,Bangalore", help="comma-separated cities")
    ap.add_argument("--remote", action="store_true", help="also include remote jobs open to India")
    ap.add_argument("--roles", default=DEFAULT_ROLES, help="title keywords you'd accept")
    ap.add_argument("--companies", default="companies.txt", help="extra companies file (platform: slug slug)")
    ap.add_argument("--add-url", action="append", default=[], help="company careers URL to auto-detect")
    ap.add_argument("--max-years", type=int, default=2, help="drop jobs asking more experience than this")
    ap.add_argument("--include-senior", action="store_true")
    ap.add_argument("--min-score", type=int, default=25)
    ap.add_argument("--out", default="jobs.html")
    ap.add_argument("--demo", action="store_true", help="offline sample data to preview the dashboard")
    a = ap.parse_args()

    locs = [x.strip() for x in a.locations.split(",") if x.strip()]
    if a.demo:
        resume = DEMO_RESUME
        jobs = [dict(title=t, company=c, location=l, remote=r, url="#", desc=d, posted="2026-11-19", source="demo")
                for t, c, l, r, d in DEMO_JOBS]
        ok = 0
    else:
        if not a.resume:
            sys.exit("Give your resume:  --resume resume.pdf   (or try --demo)")
        resume = read_resume(a.resume)
        entries = parse_companies(SEED_COMPANIES)
        try:
            entries += parse_companies(open(a.companies, encoding="utf-8").read())
        except FileNotFoundError:
            pass
        for u in a.add_url:
            try:
                found = discover(u)
                print(f"{u}: found {found or 'no supported hiring system (check it manually)'}")
                entries += found
            except Exception as ex:
                print(f"{u}: could not read page ({ex})")
        entries = sorted(set(entries))
        print(f"Checking {len(entries)} company hiring systems...")
        jobs, ok = collect(entries)
        print(f"{ok} responded, {len(jobs)} openings fetched")

    for j in jobs:
        j["loc_hit"] = location_hit(j, locs, a.remote)
    local = [j for j in jobs if j["loc_hit"]]
    rated = rate(local, resume, a.roles, a.max_years, a.include_senior, a.min_score)
    meta = dict(locations=", ".join(locs) + (" + remote" if a.remote else ""), demo=a.demo,
                when=dt.datetime.now().strftime("%d %b %Y %H:%M"), careers=CAREER_PAGES)
    csv_path = write_outputs(rated, meta, a.out)
    print(f"{len(local)} in your locations, {len(rated)} kept after fresher/experience filter")
    print(f"Open {a.out} in your browser (also saved {csv_path})")
    if not a.demo and not rated:
        print("Nothing matched. Add more companies (companies.txt / --add-url), widen --locations, or add --remote.")


if __name__ == "__main__":
    main()
