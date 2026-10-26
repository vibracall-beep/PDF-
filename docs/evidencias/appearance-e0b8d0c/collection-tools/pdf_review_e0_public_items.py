from pathlib import Path
import hashlib,json
root=Path('/workspace/.cache/pdf-appearance-e0b8d0c-40249767201')
configuration=json.loads((root/'collector-configuration.json').read_text())
allowed={'Comandos':'pdf.commands.toolbar','Personalizar':'pdf.customize.toolbar','Hide Sidebar':'autoSidebar','Show Sidebar':'autoSidebar','Ocultar Barra Lateral':'autoSidebar','Mostrar Barra Lateral':'autoSidebar','Ocultar barra lateral':'autoSidebar','Mostrar barra lateral':'autoSidebar'}
artifacts=[];snapshot_count=0
for name in ('PDF-appearance-sdk26','PDF-appearance-same-binary-xcode27'):
 directory=root/'extracted'/name
 raw=(directory/'PDF-appearance.appearance.json').read_bytes();report=json.loads(raw)
 phases=[];attached=[]
 for frame in report['frames']:
  phase={'phase':frame['phase'],'selection':frame['selection'],'png':frame['png'],'pngSha256':frame['sha256'],'dimensions':[frame['width'],frame['height']]}
  toolbar=frame.get('toolbarReport')
  if toolbar is not None:
   observations=[]
   for timing in ('before','after'):
    snapshot=toolbar[timing]
    assert len(snapshot['toolbarProviders'])==1
    provider=snapshot['toolbarProviders'][0]
    assert not provider['nativeHierarchyTruncated'] and not snapshot['nativeToolbarItems']['traversalLimited']
    nodes={node['view']['identity']:node for node in provider['nativeViews']};chosen={}
    for item in snapshot['nativeToolbarItems']['items']:
     key=allowed.get(item['label'])
     if key is None:continue
     assert key not in chosen and item['paletteLabel']==item['label']
     view=item['view'];assert view['identity'] in nodes and view==nodes[view['identity']]['view']
     assert view['provider']['belongsToWindow'] and not view['provider']['hiddenOrHasHiddenAncestor'] and view['alpha']>0
     b=view['windowFrame'];assert b['width']>0 and b['height']>0 and b['x']>=0 and b['y']>=0 and b['x']+b['width']<=snapshot['windowFrame']['width'] and b['y']+b['height']<=snapshot['windowFrame']['height']
     chosen[key]={'itemIdentifier':item['itemIdentifier'],'label':item['label'],'paletteLabel':item['paletteLabel'],'viewIdentity':view['identity'],'windowFrame':b,'screenFrame':view['screenFrame'],'effectiveAppearance':view['effectiveAppearance'],'effectiveStyle':view['effectiveStyle'],'alpha':view['alpha'],'nativeNodeIndex':nodes[view['identity']]['index'],'sameObservationInNativeHierarchy':True}
    assert set(chosen)=={'autoSidebar','pdf.commands.toolbar','pdf.customize.toolbar'} and len({v['viewIdentity'] for v in chosen.values()})==3
    observations.append({'timing':timing,'windowNumber':snapshot['windowNumber'],'nativeToolbarItemCount':len(snapshot['nativeToolbarItems']['items']),'nativeViewCount':len(provider['nativeViews']),'AXDirectChildCount':provider['directChildCount'],'nativeSelectedControls':len(snapshot['controls']),'prospectivePublicItemEvidence':chosen})
    snapshot_count+=1
   assert observations[0]['prospectivePublicItemEvidence']==observations[1]['prospectivePublicItemEvidence']
   phase['observations']=observations;phase['nativePixelMeasurements']=toolbar['measurements']
   attached.append({k:v['viewIdentity'] for k,v in observations[0]['prospectivePublicItemEvidence'].items()})
  else:
   snapshot=frame['windowSnapshot'];phase['applicationWindowContentStyles']=[snapshot['applicationEffectiveStyle'],snapshot['windowEffectiveStyle'],snapshot['contentEffectiveStyle']]
   phase['nativePopupControls']=snapshot['nativePopupControls']
  phases.append(phase)
 assert attached[0]==attached[1]==attached[2]
 fingerprints={}
 for filename in ('PDF-appearance.appearance.json','capture.log','validation.log'):
  data=(directory/filename).read_bytes();fingerprints[filename]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
 artifacts.append({'artifact':name,'directory':str(directory),'originalNativeStatus':report['status'],'checks':report['checks'],'files':fingerprints,'firstThreePhaseViewIdentitiesStable':True,'recreatedViewIdentitiesDiffer':attached[0]!=attached[3],'phases':phases})
assert snapshot_count==24
result={'schemaVersion':1,'scope':'public-native-toolbar-item-identification-evidence','configuration':configuration,'observedWorkspaceSnapshots':snapshot_count,'artifacts':artifacts,'selectionEvidence':'Each original workspace snapshot exposes exactly one public NSToolbarItem whose label and paletteLabel equal Comandos, one equal Personalizar, and one observed sidebar name. Their three distinct item.views belong to the same real toolbar/window, with identical observations in the native hierarchy. Their complete metadata and geometry are stable before/after each PNG; their identities are also stable over the first three phases. This is evidence for a new observer implementation, not a retroactive passing native result.','nativeContrastApproved':False,'applicationApproved':False,'originalNativeGateResultsPreserved':True,'limitations':['The original application report still selected zero controls and produced zero native contrast measurements. Its failed status remains unchanged.','No class, generated UUID, undocumented system identifier, item order or screen position selected the prospective evidence. Labels and paletteLabels are the public semantic identifiers observed and controlled by this app.','Only the SDK26 customization PNG was opened by this technical review; it visibly restores Equilibrado and Restaurar. The complete 14-image review belongs to scope_audit in /tmp/pdf-appearance-e0-independent-review.{md,json}.','Static source review and offline evidence cannot replace the next native compile/execution of the corrected observer. No original PNG, JSON, log, or prior report was edited.']}
p=Path('/tmp/pdf-appearance-e0b8d0c-public-items-diagnosis.json');p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
md=Path('/tmp/pdf-appearance-e0b8d0c-public-items-diagnosis.md');md.write_text('''# Diagnóstico dos itens públicos da toolbar — focal e0\n\nA execução40249767201 continua reprovada: o aplicativo selecionou zero controles e não produziu medidas de contraste. Este relatório não altera esse resultado.\n\nOs24snapshots workspace (antes/depois, seis fases em dois sistemas) oferecem uma alternativa pública comprovável: um NSToolbarItem com label/paletteLabel Comandos, outro Personalizar e outro com o nome observado do sidebar. Cada item possui uma view real e única, pertencente à mesma janela/toolbar; identidade, aparência e geometria coincidem com a observação da hierarquia NSView. A evidência foi conferida em todos24snapshots. Os metadados completos não mudam durante cada PNG, e as identidades permanecem nas três primeiras fases; recriam-se após Personalização nos dois sistemas.\n\nA implementação seguinte pode selecionar pelos labels e paletteLabels exatos e validar item.view, descendência da única toolbar, janela, visibilidade, alpha, bounds e estabilidade. Deve registrar o itemIdentifier real separado do auditKey lógico, sem usar UUID, identifier interno do sistema, classe privada, ordem ou coordenada fixa para escolher o controle. O limiar3:1 e todos os demais gates permanecem. Essa proposta e sua implementação exigem um novo focal nativo.\n\nNo primeiro PNG de personalização do macOS26, Equilibrado e Restaurar estão visíveis. Os cinco NSPopUpButton e seus ancestrais agora têm aparência clara; isso é limitado ao percurso capturado. A revisão dos14originais pertence a scope_audit. O JSON companheiro preserva hashes, dimensões, checks nativos e a evidência individual dos24snapshots.\n''')
s=md.read_text()
for a,b in [('execução40249767201','execução 40249767201'),('Os24snapshots','Os 24 snapshots'),('todos24snapshots','todos os 24 snapshots'),('limiar3:1','limiar 3:1'),('macOS26','macOS 26'),('dos14originais','dos 14 originais'),('dos24snapshots','dos 24 snapshots')]:s=s.replace(a,b)
md.write_text(s)
for file in (p,md):print(str(file),hashlib.sha256(file.read_bytes()).hexdigest())
