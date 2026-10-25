from pathlib import Path
import json,re,hashlib,zipfile
p=Path('/tmp/pdf-cross-437a8f4');jid=121014698642;f=p/f'collector-job-{jid}.log';lines=f.read_text().splitlines();suites=[];native=[];groups=0
for n,l in enumerate(lines,1):
 m=re.search(r'Ran (\d+) tests? in ([\d.]+)s',l)
 if m:suites.append({'count':int(m[1]),'seconds':float(m[2]),'line':n,'resultLine':next((x for x in lines[n:n+8]if re.search(r'\bOK(?: \(skipped=\d+\))?$|FAILED \(',x)),None)})
 if 'Native check passed:' in l:groups+=1
 if 'PDF native smoke tests passed' in l:native.append({'line':n,'groups':groups});groups=0
record={'jobID':jid,'originalLog':f.name,'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'controllerPythonSuites':suites,'nativeSuccessfulRuns':native,'totalNativePassedLines':sum('Native check passed:' in l for l in lines),'nativeFailureLines':sum('Native check failed:' in l for l in lines),'errorAnnotations':[{'line':n,'text':l}for n,l in enumerate(lines,1)if '##[error]' in l]}
(p/'collector-final-counts.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
zpath=p/'collector-attempt-1-logs.zip'
with zipfile.ZipFile(zpath) as z:
 matches=[i for i in z.infolist() if '/' not in i.filename and 'compatible-binary' in i.filename];assert len(matches)==1;b=z.read(matches[0]);assert b==f.read_bytes()
 receipt={'originalZIP':zpath.name,'bytes':zpath.stat().st_size,'sha256':hashlib.sha256(zpath.read_bytes()).hexdigest(),'jobLogMember':matches[0].filename,'jobLogEqualsDirectDownload':True,'jobLogBytes':len(b),'jobLogSHA256':hashlib.sha256(b).hexdigest()}
(p/'collector-log-identity.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
