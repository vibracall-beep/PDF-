from pathlib import Path
import hashlib,json,struct,math
root=Path('/workspace/.cache/pdf-appearance-9d78ab9-40252786964')
config=json.loads((root/'collector-configuration.json').read_text())
assert config['sourceCommit']=='9d78ab9e38c8d4b0d63c98f18241d1735be7b3cb' and config['runID']==40252786964
allowed={'pdf.commands.toolbar':{'Comandos'},'pdf.customize.toolbar':{'Personalizar'},'autoSidebar':{'Hide Sidebar','Show Sidebar','Ocultar Barra Lateral','Mostrar Barra Lateral','Ocultar barra lateral','Mostrar barra lateral'}}
observations={
 'light-initial':'Página inicial clara: os três símbolos da toolbar estão legíveis; navegação, busca, categorias e cartões do viewport estão separados, sem sobreposição confirmada.',
 'dark-attached-1':'Página inicial escura: sidebar, Comandos e Personalizar permanecem legíveis sobre as superfícies escuras. Não há reaparecimento das cápsulas brancas com símbolos brancos.',
 'dark-attached-2':'Segundo quadro escuro aberto individualmente: os três símbolos continuam legíveis e não há novo bloqueador visual no viewport. Captura estática não prova animação.',
 'customization':'Personalização clara: Espaçamento/Equilibrado e Restaurar estão presentes e legíveis. Abas, controles visíveis, prévia e rodapé não apresentam sobreposição confirmada; conteúdo abaixo da rolagem não foi revisado.',
 'dark-recreated':'Retorno ao workspace escuro após Personalização: os três símbolos estão legíveis; o antigo defeito de contraste não reaparece neste quadro. A busca aparece sem o anel de foco anterior.',
 'light-return':'Retorno ao tema claro: toolbar, navegação e controles visíveis continuam legíveis, sem novo corte ou sobreposição confirmado.',
 'system':'Modo Sistema exibido claro neste runner: os três controles continuam legíveis. A ausência de overrides é corroborada pelo JSON; a imagem sozinha não prova herança do sistema.'}
artifacts=[];all_measurements=[];all_frames=[];bundles=[];total_snapshots=0
for name in ('PDF-appearance-sdk26','PDF-appearance-same-binary-xcode27'):
 directory=root/'extracted'/name
 raw=(directory/'PDF-appearance.appearance.json').read_bytes(); report=json.loads(raw)
 receipt=json.loads((directory/'appearance-validation.json').read_text());bundle=json.loads((directory/'appearance-bundle.json').read_text());bundles.append(bundle)
 assert report['status']==receipt['status']=='passed' and len(report['checks'])==12 and all(c['passed'] for c in report['checks'])
 assert receipt['sourceCommit']==config['sourceCommit'] and receipt['unchangedBundleFiles']==bundle['files'] and receipt['completeApplicationApproved'] is False
 frames=[];identities=[];ratios=[];timings=[]
 for f in report['frames']:
  path=directory/f['png'];data=path.read_bytes();fingerprint={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
  assert fingerprint==receipt['originals'][f['png']] and fingerprint['sha256']==f['sha256'] and len(data)==f['bytes']
  dimensions=struct.unpack('>II',data[16:24]);assert dimensions==(f['width'],f['height'])==(1050,772)
  entry={'file':f['png'],'path':str(path),**fingerprint,'width':f['width'],'height':f['height'],'phase':f['phase'],'selection':f['selection'],'openedIndividuallyWithViewImageOriginal':True,'visualObservation':observations[f['phase']],'confirmedVisualBlockers':[]}
  t=f.get('toolbarReport');snapshot=f['windowSnapshot']
  if t:
   assert t['passed'] and t['errors']==[] and len(t['measurements'])==3
   before,after=t['before'],t['after'];assert before['controls']==after['controls']
   assert before['windowNumber']==after['windowNumber'] and before['windowFrame']==after['windowFrame'] and before['backingScale']==after['backingScale']
   for s in (before,after):
    assert s['errors']==[] and s['workspaceToolbarProviderCount']==1 and len(s['toolbarProviders'])==1
    assert s['windowToolbarPresent'] and s['windowToolbarVisible'] and not s['nativeToolbarItems']['traversalLimited']
    provider=s['toolbarProviders'][0];assert not provider['nativeHierarchyTruncated']
    nodes={n['view']['identity']:n for n in provider['nativeViews']};native_root=provider['nativeViews'][0]['view']
    assert native_root['provider']['role']=='AXToolbar' and native_root['provider']['belongsToWindow'] and not native_root['provider']['hiddenOrHasHiddenAncestor'] and native_root['alpha']>0
    assert len({c['identity'] for c in s['controls']})==3
    for c in s['controls']:
     assert c['identification']=='public-NSToolbarItem-label-paletteLabel-and-actual-view'
     matches=[item for item in s['nativeToolbarItems']['items'] if item['label'] in allowed[c['auditKey']] and item['paletteLabel']==item['label']]
     assert len(matches)==1;item=matches[0];v=item['view']
     assert c['identifier']==item['itemIdentifier'] and c['label']==c['paletteLabel']==item['label']
     assert c['identity']==v['identity'] and c['windowFrame']==v['windowFrame'] and c['screenFrame']==v['screenFrame'] and c['alpha']==v['alpha']>0
     assert v['provider']['belongsToWindow'] and not v['provider']['hiddenOrHasHiddenAncestor']
     assert v['identity'] in nodes and nodes[v['identity']]['view']==v
     assert c['effectiveAppearance']==v['effectiveAppearance'] and c['effectiveStyle']==v['effectiveStyle']
    total_snapshots+=1
   for m in t['measurements']:
    assert m['passed'] and m['minimumContrast']==3 and m['centralContrast']>=3
    assert abs(m['centralContrast']-(m['luminanceP95']+.05)/(m['luminanceP05']+.05))<1e-6
    ratios.append(m['centralContrast']);all_measurements.append({'artifact':name,'phase':f['phase'],**m})
   identities.append({c['auditKey']:c['identity'] for c in before['controls']});timings.append((before['uptime'],after['uptime']))
   entry['nativeMeasurements']=t['measurements'];entry['itemViewBindingsVerifiedBeforeAndAfter']=True
   entry['controls']=before['controls'];entry['snapshotUptimes']={'before':before['uptime'],'after':after['uptime']}
  else:
   entry['visibleSpacingAndRestoreControls']=True
   entry['nativePopupObservation']=[{'title':p['title'],'effectiveStyle':p['effectiveStyle'],'appearanceOverride':p.get('appearanceOverride'),'windowFrame':p['windowFrame'],'ancestorEffectiveStyles':[a['effectiveStyle'] for a in p['ancestors']]} for p in snapshot['nativePopupControls']]
  frames.append(entry);all_frames.append(entry)
 assert identities[0]==identities[1]==identities[2] and timings[1][1]<timings[2][0]
 assert all(identities[0][key]!=identities[3][key] for key in identities[0])
 system=report['frames'][-1]['windowSnapshot'];assert system.get('applicationOverride') is None and system.get('windowOverride') is None
 fingerprints={}
 for filename in ('PDF-appearance.appearance.json','appearance-validation.json','appearance-bundle.json','capture.log'):
  data=(directory/filename).read_bytes();fingerprints[filename]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
 artifacts.append({'artifact':name,'operatingSystem':receipt['operatingSystem'],'nativeStatus':report['status'],'checks':report['checks'],'sourceFiles':fingerprints,'minimumNativeCentralContrast':min(ratios),'publicItemViewBindingsVerifiedInAll12Snapshots':True,'attachedViewIdentitiesStable':True,'viewsRecreatedAfterCustomization':True,'separateDarkCaptureUptimes':True,'systemOverridesReleased':True,'frames':frames})
assert len(all_frames)==14 and total_snapshots==24 and len(all_measurements)==36 and bundles[0]==bundles[1]
result={'schemaVersion':1,'scope':'fourteen-original-focal-appearance-images-and-toolbar-evidence','reviewer':'/root/visual_candidate','configuration':config,'visualInspectionMethod':'Every one of the 14 original PNG files was opened individually through view_image with detail original. Some unchanged frames were reopened for a full contextual comparison. No image was painted, altered, cropped or substituted.','assistantVisualReviewCompleted':True,'humanInteractiveReview':False,'focalVisualApproval':True,'approvalMeaning':'No confirmed visual blocker in these 14 captured viewports and the three measured toolbar controls. Approval is restricted to this minimal appearance diagnostic and exact source/run.','confirmedVisualBlockers':[],'originalPNGsReviewed':14,'nativeWorkspaceSnapshotsVerified':24,'nativeToolbarMeasurements':36,'minimumNativeCentralContrast':min(m['centralContrast'] for m in all_measurements),'bundleManifest':bundles[0],'artifacts':artifacts,'resolvedWithinCapturedPath':[{'id':'PREVIOUS-DARK-TOOLBAR-CONTRAST','observation':'All 12 workspace images retain three legible toolbar symbols. All 36 native central-pixel measurements exceed 3:1; the minimum is 4.136177866044884:1.'},{'id':'PREVIOUS-CUSTOMIZATION26-EMPTY-POPUPS','observation':'Equilibrado and Restaurar are visibly present in the SDK26 customization frame. The five observed native popup controls and their recorded ancestors use the light style. Offscreen popup rendering was not visually assessed.'}],'installedApplicationApproved':False,'packageDeliveryApproved':False,'documentRecoveryValidated':False,'completeToolCatalogValidated':False,'physicalM4PerformanceValidated':False,'universalWCAGCertification':False,'animationsValidated':False,'limitations':['The inspected views are static 1050x772 viewports. Scrollable content below the viewport, other customization tabs and menus not opened in these images are outside the visual review.','Static screenshots do not demonstrate clicks, keyboard navigation, VoiceOver output, animation quality, absence of transient flicker, recovery after crashes, or PDF processing.','The native contrast check covers the central symbols of three toolbar controls with its declared 60-percent sample and p95/p05 luminance ratio. It is not a universal WCAG or all-colors accessibility certification.','The two jobs ran the same minimal SDK26 bundle. This does not validate the fully installed application, its engine/runtime, package-source size, delivery archive or installation on the user equipment.','The separate package-source size blocker and recovery/package work remain outside this review. No approval of those tasks is implied by focal success.','Earlier failed runs and blocked reviews remain unchanged. This report applies only to source9d78ab9 and run40252786964.']}
out=Path('/tmp/pdf-appearance-9d-independent-review.json');out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
md=Path('/tmp/pdf-appearance-9d-independent-review.md')
lines=['# Revisão visual independente do focal 9d','',f'Fonte/controlador: `{config["sourceCommit"]}`. Execução `{config["runID"]}`, tentativa `{config["runAttempt"]}`.','', '**Conclusão restrita ao focal:** os 14 PNGs originais foram abertos individualmente; não identifiquei bloqueador visual confirmado nos viewports capturados. A toolbar está legível em todos os 12 quadros workspace. Espaçamento/Equilibrado e Restaurar estão presentes nas duas capturas de Personalização.','', 'Os dois relatórios nativos passam os 12 checks e contêm 36 medições de contraste. A conferência independente vinculou todos os 24 snapshots antes/depois aos NSToolbarItem e item.view reais registrados, incluindo identidade, aparência, geometria, unicidade e presença na hierarquia nativa. Os tokens permanecem nas três primeiras fases e mudam após Personalização; as duas capturas escuras têm intervalos de observação distintos. Sistema libera os overrides de app/janela.','', 'Menor razão central nativa: **4,136:1 no macOS 26** e **6,878:1 no macOS 27**, acima do limiar de 3:1 deste teste. Esses valores foram lidos e conferidos nos relatórios nativos, sem substituir pixels ou reconstruir imagens.','', 'Os manifestos registram o mesmo executável SDK26.5 nos dois jobs, SHA256 `'+bundles[0]['files']['Contents/MacOS/PDF']['sha256']+'`. O escopo é um bundle mínimo de aparência. **Esta aprovação não valida aplicativo instalado, recuperação de documentos, pacote de entrega, todas as ferramentas, desempenho em M4 físico, VoiceOver ou animações.** O problema separado de tamanho do package-source não é resolvido por este focal.','', 'A inspeção cobre apenas conteúdo visível em 1050×772. A rolagem corta naturalmente as próximas linhas de cartões/controles; conteúdo abaixo desse viewport e abas não abertas não foram avaliados. Não há afirmação de interação humana ou de conformidade WCAG universal.','', '| Artefato | PNG original | SHA256 | Dimensões | Resultado visual |','| --- | --- | --- | --- | --- |']
for artifact in artifacts:
 for f in artifact['frames']:lines.append(f'| {artifact["artifact"]} | {f["file"]} | `{f["sha256"]}` | {f["width"]}×{f["height"]} | Sem bloqueador confirmado no viewport |')
lines+=['','O JSON companheiro conserva nomes, hashes, dimensões, observações por quadro, vínculos aos relatórios originais e medições. Nenhum original, fonte do produto ou revisão anterior foi alterado.','']
md.write_text('\n'.join(lines))
for p in (out,md):print(str(p),hashlib.sha256(p.read_bytes()).hexdigest())
