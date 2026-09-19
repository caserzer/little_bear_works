#!/usr/bin/env python3
"""Generate A4 print editions from grade6 Markdown (Python markdown, bs4, pypdf + Chrome).
Run: python3 scripts/build_printable_pdfs.py --prepare / --render / --finalize
Intermediate HTML lives in /tmp/bear_print; original teaching material stays unchanged.
"""
from pathlib import Path
import argparse, hashlib, html, json, re, subprocess, zipfile
import markdown
from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'grade6/printable/2026-09-19'
TMP=Path('/tmp/bear_print')
SUBJECTS={'Math':'数学','English':'英语','Chinese':'语文'}
CSS='''
@page { size: A4; margin: 17mm 17mm 18mm;
 @bottom-center {content: "第 " counter(page) " 页 / 共 " counter(pages) " 页"; font:9pt "Noto Sans CJK SC"; color:#555;}
}
*{box-sizing:border-box} body{font-family:"Noto Sans CJK SC","Arial",sans-serif;font-size:11pt;line-height:1.65;color:#111;margin:0}
h1{font-size:20pt;line-height:1.4;margin:0 0 5mm;padding-bottom:3mm;border-bottom:1.2pt solid #333}
h2{font-size:14pt;line-height:1.45;margin:6mm 0 3mm;break-after:avoid}
h3{font-size:12pt;margin:4mm 0 2mm;break-after:avoid} p{margin:2.5mm 0;orphans:3;widows:3}
ul,ol{padding-left:6mm;margin:2.5mm 0}li{margin-bottom:1.7mm} a{color:inherit;text-decoration:none}
table{width:100%;border-collapse:collapse;font-size:9pt;line-height:1.5;margin:3mm 0;table-layout:auto}
th,td{border:0.6pt solid #888;padding:1.8mm;vertical-align:top;overflow-wrap:anywhere}th{background:#eee;font-weight:700}thead{display:table-header-group}tr{break-inside:avoid}
blockquote{border-left:2pt solid #aaa;margin:4mm 0;padding:0 4mm} code{font-family:inherit;font-size:10pt;overflow-wrap:anywhere}
.question{break-inside:avoid;margin:0 0 4mm}.question h2,.question h3{margin-top:3mm}
.lesson{break-before:page} .answerline{height:9mm;border-bottom:0.5pt solid #aaa}
.response{margin:3mm 0 4mm;break-inside:avoid}.response-label{font-size:9pt;color:#555}
.grid{display:grid;grid-template-columns:repeat(20,1fr);border-top:0.5pt solid #aaa;border-left:0.5pt solid #aaa;margin:3mm 0}
.grid span{height:8mm;border-right:0.5pt solid #aaa;border-bottom:0.5pt solid #aaa}
.meta{font-size:9pt;color:#555;margin-bottom:4mm}.tasknote{font-size:9pt;color:#555}
@media screen {body{width:176mm;margin:17mm auto}.lesson{margin-top:15mm}}
'''
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def answer_area(subject,qid,text):
    if subject=='Chinese' and (qid in ['B05','P31']):
        n=300 if qid=='B05' else 240
        return '<div class="response"><div class="response-label">正文（每行20格，可续写）：</div><div class="grid">'+('<span></span>'*n)+'</div></div>'
    n=3
    if subject=='Math': n=4 if qid[0]!='P' else 3
    elif subject=='English':
        n=2
        if qid in ['B03','B04']:n=5
        if qid in ['B05','P31']:n=9
        if '写作' in text or re.search(r'\d+[—～-]\d+词',text):n=9
    else:
        n=2
        if qid in ['A07','A08','B01','B03','R08','P08','P30']:n=4
        if qid in ['B02','B04','P20','P28']:n=5
        if qid=='R07':n=3
    return '<div class="response"><div class="response-label">作答：</div>'+('<div class="answerline"></div>'*n)+'</div>'
def prepare():
    OUT.mkdir(parents=True,exist_ok=True);TMP.mkdir(parents=True,exist_ok=True)
    jobs=[]
    for sub,label in SUBJECTS.items():
        for folder in ['lessons','practice','answers']:
            for source in sorted((ROOT/'grade6'/sub/folder).glob('*.md')):
                name=source.stem.split('_整理批次_',1)[-1]
                target=OUT/f'{label}_{name}.pdf'
                soup=BeautifulSoup(markdown.markdown(re.sub(r'_{2,}', lambda m: r'\_' * len(m.group()), source.read_text()),extensions=['tables','sane_lists','nl2br']),'html.parser')
                # External resources are never fetched while printing; preserve visible link labels.
                for a in soup.find_all('a'):
                    if a.get('href','').startswith(('http://','https://')):continue
                    a.attrs.pop('href',None)
                for hr in soup.find_all('hr'):hr.decompose()
                for node in soup.find_all('p'):
                    t=node.get_text().strip()
                    if re.fullmatch(r'(?:作答|解答|过程与答案|阅读作答|正文)?[：:]?\s*_+\s*',t) or t in ['解答：','过程与答案：','正文：','阅读作答：']:
                        node.decompose()
                children=list(soup.contents); chunks=[]; current=[]
                for node in children:
                    if getattr(node,'name',None) in ['h2','h3']:
                        if current:chunks.append(current)
                        current=[node]
                    else:current.append(node)
                if current:chunks.append(current)
                parts=[]
                for chunk in chunks:
                    head=next((n for n in chunk if getattr(n,'name',None)),None)
                    heading=head.get_text() if head else ''
                    q=re.match(r'([PABR]\d{2})\b',heading)
                    isq=bool(q and folder=='practice')
                    classes='question' if isq else 'section'
                    if folder=='lessons' and re.match(r'L\d+\b',heading):classes+=' lesson'
                    body=''.join(str(n) for n in chunk)
                    if isq:body+=answer_area(sub,q.group(1),BeautifulSoup(body,'html.parser').get_text())
                    parts.append(f'<section class="{classes}">{body}</section>')
                audience='家长/教师用' if folder in ['lessons','answers'] else '学生练习'
                if '口语' in name:audience='口语考核·含家长主持说明'
                if '人物观察' in name:
                    parts.append('<div class="response"><div class="response-label">人物片段补充书写区：</div><div class="grid">'+('<span></span>'*240)+'</div></div>')
                title=f'{label} · {name}'
                sheet=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>{CSS}
@page {{ @top-left {{content:"六年级 · {label} · {audience}";font:8pt "Noto Sans CJK SC";color:#555}} }}
</style></head><body><div class="meta">A4打印版 · 整理批次2026-09-19 · {audience}</div>{''.join(parts)}</body></html>'''
                h=TMP/f'{sub}_{name}.html';h.write_text(sheet)
                jobs.append({'subject':sub,'label':label,'category':folder,'name':name,'source':str(source.relative_to(ROOT)),'source_sha256':digest(source),'html':str(h),'pdf':str(target),'title':title})
    (TMP/'jobs.json').write_text(json.dumps(jobs,ensure_ascii=False,indent=2))
    print(f'Prepared {len(jobs)} documents',flush=True)
def render():
    jobs=json.loads((TMP/'jobs.json').read_text())
    for j in jobs:
        command=['google-chrome','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-background-networking','--no-pdf-header-footer','--allow-file-access-from-files','--user-data-dir='+str(TMP/'render-profile'),'--print-to-pdf='+j['pdf'],Path(j['html']).as_uri()]
        r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace'))
        if not Path(j['pdf']).exists():raise RuntimeError(j['pdf'])
        print('Rendered '+j['title'],flush=True)
def finalize():
    jobs=json.loads((TMP/'jobs.json').read_text());records=[]
    for j in jobs:
        assert digest(ROOT/j['source'])==j['source_sha256'],'Source changed during conversion'
        pdf=PdfReader(j['pdf']); texts=[p.extract_text() or '' for p in pdf.pages]
        assert all(len(t.strip())>25 for t in texts),(j['title'],'empty page')
        for page in pdf.pages:
            assert abs(float(page.mediabox.width)-595.28)<2 and abs(float(page.mediabox.height)-841.89)<2,'not A4'
        full='\n'.join(texts)
        for code in re.findall(r'^#{2,3} ([LPABR]\d+)\b',(ROOT/j['source']).read_text(),re.M):
            assert code in full,(j['title'],'missing '+code)
        records.append({k:v for k,v in j.items() if k not in ['html','pdf']}|{'pdf':Path(j['pdf']).name,'pages':len(pdf.pages),'pdf_sha256':digest(Path(j['pdf']))})
    bundles=[('全部教案合订本',lambda j:j['category']=='lessons'),('全部笔试卷合订本',lambda j:j['category']=='practice' and j['name'].startswith('考核')),('全部专项练习合订本',lambda j:j['name']=='专项练习'),('全部答案与评分合订本',lambda j:j['category']=='answers')]
    bundle_records=[]
    for title,condition in bundles:
        writer=PdfWriter(); members=[]
        for j in jobs:
            if condition(j):writer.append(j['pdf'],outline_item=j['title']);members.append(Path(j['pdf']).name)
        writer.add_metadata({'/Title':title,'/Author':'小熊作业资料'})
        target=OUT/(title+'.pdf')
        with target.open('wb') as f:writer.write(f)
        bundle_records.append({'pdf':target.name,'pages':len(writer.pages),'members':members,'sha256':digest(target)})
    manifest={'paper':'A4','batch':'2026-09-19','originals_unchanged':True,'individual_documents':records,'bundles':bundle_records}
    (OUT/'打印清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    lines=['# 六年级三科可打印资料','',f'已生成{len(records)}份独立PDF和{len(bundle_records)}份合订本。覆盖三科24课教案、9套笔试卷、英语口语考核、96道专项练习、人物观察记录及全部配套答案。','',
    'A4纵向，建议按“实际大小/100%”打印；双面打印选择长边翻转。学生卷留有书写空间，语文长片段配作文格。合订本中的新文件从新页开始，但不强制从奇数页开始；需要每套卷单独成册时请打印独立PDF。','',
    '教案、答案单独保存；英语口语PDF含家长主持说明，未并入笔试合订本。原始Markdown内容保留，打印版仅调整字体、分页和答题空间。','',
    '## 整册打印','', '| 合订本 | 页数 |','|---|---:|']
    for b in bundle_records:lines.append(f"| [{b['pdf']}]({b['pdf']}) | {b['pages']} |")
    for sub,label in SUBJECTS.items():
        lines.extend(['',f'## {label}','','| PDF | 页数 | 源文件 |','|---|---:|---|'])
        for j in records:
            if j['subject']==sub:lines.append(f"| [{j['name']}]({j['pdf']}) | {j['pages']} | [Markdown](../../../{j['source'].removeprefix('grade6/')}) |")
    # From grade6/printable/date the subject directory is two levels up.
    lines=[line.replace('(../../../Math/','(../../Math/').replace('(../../../English/','(../../English/').replace('(../../../Chinese/','(../../Chinese/') for line in lines]
    lines.extend(['','生成脚本：[build_printable_pdfs.py](../../../scripts/build_printable_pdfs.py)。清单记录源文件与PDF哈希，便于后续重新生成和核对。',''])
    (OUT/'README.md').write_text('\n'.join(lines))
    zip_path=OUT.parent/'2026-09-19_三科可打印PDF.zip'
    with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.iterdir()):
            if f.is_file():z.write(f,arcname=f.name)
    print(json.dumps({'individual_pdfs':len(records),'bundles':len(bundle_records),'individual_pages':sum(j['pages'] for j in records),'zip':str(zip_path)},ensure_ascii=False),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--prepare',action='store_true');a.add_argument('--render',action='store_true');a.add_argument('--finalize',action='store_true');opt=a.parse_args()
    if opt.prepare:prepare()
    if opt.render:render()
    if opt.finalize:finalize()
