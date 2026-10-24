"""Explicit, conservative editing of a PDF structure tree.

Changing tags does not establish PDF/UA conformance. No content is inferred:
the human chooses roles, alternatives and order; veraPDF remains independent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pdf_signatures import _snapshot

ROLES = {'Document','Part','Sect','Div','P','H','H1','H2','H3','H4','H5','H6',
         'L','LI','Lbl','LBody','Table','TR','TH','TD','THead','TBody','TFoot',
         'Figure','Formula','Caption','Note','Link','Span','Quote','BlockQuote'}


def _raw(obj, key, default=None):
    try: return obj.raw_get(key)
    except KeyError: return default


def _object(value):
    return value.get_object() if isinstance(value, g.IndirectObject) else value


def _id(value):
    return f'{value.idnum}:{value.generation}' if isinstance(value,g.IndirectObject) else None


def _array(value):
    value = _object(value)
    if value is None: return []
    return list(value) if isinstance(value,g.ArrayObject) else [value]


def _text(value, label, maximum=16384):
    if not isinstance(value,str) or len(value)>maximum or '\0' in value:
        raise ValueError(f'{label}: informe texto com até {maximum} caracteres, sem NUL.')
    return value


def _language(value):
    value=_text(value,'Idioma',64)
    if not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*',value):
        raise ValueError('Use um idioma BCP 47, por exemplo pt-BR ou en.')
    return value


def _pages(reader):
    count=int(reader.root['/Pages']['/Count'])
    if not 0<count<=100000: raise ValueError('Quantidade de páginas inválida.')
    return { _id(reader.find_page_for_modification(i)[0]): i+1 for i in range(count) }


def _tree(reader):
    pages=_pages(reader); root=_object(_raw(reader.root,'/StructTreeRoot'))
    nodes=[]; index={}; active=set(); seen=set()
    def walk(reference,parent,depth,inherited_page=None):
        if depth>128 or len(nodes)>=100000: raise ValueError('A árvore de tags excede os limites de inspeção.')
        obj=_object(reference)
        if not isinstance(obj,g.DictionaryObject) or '/S' not in obj: return
        identity=_id(reference)
        if identity is None: raise ValueError('Esta árvore contém tags diretas; normalize a estrutura em um editor especializado antes de editar.')
        if identity in seen or identity in active: raise ValueError('A árvore contém ciclos ou uma tag com mais de um pai.')
        active.add(identity); seen.add(identity)
        role=str(obj['/S']).lstrip('/')
        kids=_array(_raw(obj,'/K')); child_ids=[]; content=[]
        for child in kids:
            value=_object(child)
            if isinstance(value,g.DictionaryObject) and '/S' in value: child_ids.append(_id(child))
            elif isinstance(value,g.NumberObject): content.append({'mcid':int(value)})
            elif isinstance(value,g.DictionaryObject): content.append({'type':str(value.get('/Type','')), 'mcid':int(value['/MCID']) if '/MCID' in value else None})
        page_number=pages.get(_id(_raw(obj,'/Pg')),inherited_page)
        attributes=_object(_raw(obj,'/A')); scope=None
        for attrs in _array(attributes):
            attrs=_object(attrs)
            if isinstance(attrs,g.DictionaryObject) and _object(attrs.get('/O'))=='/Table': scope=str(_object(attrs.get('/Scope',''))).lstrip('/') or None
        item={'id':identity,'parent':parent,'role':role,'page':page_number,
              'alt':str(_object(obj.get('/Alt',''))),'actual_text':str(_object(obj.get('/ActualText',''))),
              'title':str(_object(obj.get('/T',''))),'language':str(_object(obj.get('/Lang',''))),
              'scope':scope,'children':child_ids,'content':content,'depth':depth}
        nodes.append(item);index[identity]=(reference,obj)
        for child in kids: walk(child,identity,depth+1,page_number)
        active.remove(identity)
    if isinstance(root,g.DictionaryObject):
        for child in _array(_raw(root,'/K')): walk(child,None,0)
    return root,nodes,index,pages


def inspect_pdf(input_path,output_path,options=None):
    with _snapshot(input_path) as snapshot, snapshot.open('rb') as source:
        reader=PdfFileReader(source,strict=True)
        if reader.encrypted: raise ValueError('Desbloqueie uma cópia antes de editar ou inspecionar tags.')
        root,nodes,_,pages=_tree(reader)
        mark=_object(reader.root.get('/MarkInfo',{}))
        if not isinstance(mark,(dict,g.DictionaryObject)):raise ValueError('MarkInfo inválido.')
        report={'schema_version':1,'kind':'accessibility-tree','input_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                'pages':len(pages),'language':str(_object(reader.root.get('/Lang',''))),
                'has_structure_tree':isinstance(root,g.DictionaryObject),'marked':bool(_object(mark.get('/Marked',False))),
                'nodes':nodes,'manual_review_required':True,'pdfua_conformant':None,
                'limitations':['A presença de tags não comprova PDF/UA.',
                    'Confira significado, ordem de leitura, tabelas e texto alternativo com leitor de tela.']}
    with Path(output_path).open('x',encoding='utf-8') as destination: json.dump(report,destination,ensure_ascii=False,indent=2)
    return report


def _create_page_tags(writer,specifications):
    if '/StructTreeRoot' in writer.root: raise ValueError('O PDF já tem tags; edite a estrutura existente para preservar seus vínculos.')
    count=len(_pages(writer))
    if not isinstance(specifications,list) or len(specifications)!=count:
        raise ValueError('A criação manual exige exatamente um bloco declarado por página.')
    pages=[s.get('page') for s in specifications if isinstance(s,dict)]
    if any(type(p) is not int for p in pages) or sorted(pages)!=list(range(1,count+1)):
        raise ValueError('Cada página precisa aparecer exatamente uma vez na ordem de leitura escolhida.')
    tree=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructTreeRoot')}); tree_ref=writer.add_object(tree)
    document=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructElem'),g.pdf_name('/S'):g.pdf_name('/Document'),g.pdf_name('/P'):tree_ref})
    document_ref=writer.add_object(document); children=g.ArrayObject(); parent_nums=[]
    for item in specifications:
        role=item.get('role','P')
        if role not in ROLES or role in {'TH','TD','TR','Table','THead','TBody','TFoot'}:
            raise ValueError('Um bloco de página não cria células de tabela; use P, títulos, Figure ou outro papel não tabular.')
        page_number=item['page']; page_ref,_=writer.find_page_for_modification(page_number-1); page=page_ref.get_object()
        # Reject existing marked content, including unregistered MCIDs: nesting it
        # would create ambiguous parent-tree ownership rather than repair it.
        for stream in _array(_raw(page,'/Contents')):
            body=_object(stream).data
            if re.search(rb'(?<![A-Za-z])(?:BDC|BMC|EMC)(?![A-Za-z])',body):
                raise ValueError('Há conteúdo marcado preexistente. A criação por página não pode reassociá-lo com segurança.')
        node=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructElem'),g.pdf_name('/S'):g.pdf_name('/'+role),
            g.pdf_name('/P'):document_ref,g.pdf_name('/Pg'):page_ref,g.pdf_name('/K'):g.NumberObject(0)})
        if 'alt' in item: node[g.pdf_name('/Alt')]=g.pdf_string(_text(item['alt'],'Texto alternativo'))
        if role=='Figure' and not item.get('alt','').strip(): raise ValueError('Uma figura precisa de texto alternativo significativo informado por você.')
        node_ref=writer.add_object(node);children.append(node_ref)
        page[g.pdf_name('/StructParents')]=g.NumberObject(page_number-1);writer.mark_update(page_ref)
        parent_nums.extend([g.NumberObject(page_number-1),g.ArrayObject([node_ref])])
        writer.add_stream_to_page(page_number-1,writer.add_object(g.StreamObject(stream_data=b'/'+role.encode('ascii')+b' <</MCID 0>> BDC\nq\n')),prepend=True)
        writer.add_stream_to_page(page_number-1,writer.add_object(g.StreamObject(stream_data=b'\nQ\nEMC\n')))
    document[g.pdf_name('/K')]=children
    # Number trees require sorted keys, even when the reading order is custom.
    pairs=sorted(zip(parent_nums[::2],parent_nums[1::2]),key=lambda p:int(p[0]))
    tree[g.pdf_name('/K')]=g.ArrayObject([document_ref])
    tree[g.pdf_name('/ParentTree')]=writer.add_object(g.DictionaryObject({g.pdf_name('/Nums'):g.ArrayObject([item for pair in pairs for item in pair])}))
    tree[g.pdf_name('/ParentTreeNextKey')]=g.NumberObject(count)
    writer.root[g.pdf_name('/StructTreeRoot')]=tree_ref
    writer.root[g.pdf_name('/MarkInfo')]=g.DictionaryObject({g.pdf_name('/Marked'):g.BooleanObject(True)})


def remediate_pdf(input_path,output_path,options):
    edits=options.get('edits',[])
    if not isinstance(edits,list) or len(edits)>10000 or not all(isinstance(e,dict) for e in edits):
        raise ValueError('edits deve ser uma lista de até 10.000 alterações explícitas.')
    with _snapshot(input_path) as snapshot, snapshot.open('rb') as source:
        writer=IncrementalPdfFileWriter(source,strict=True)
        if writer.prev.encrypted: raise ValueError('Desbloqueie uma cópia antes de corrigir a estrutura.')
        if writer.prev.embedded_signatures: raise ValueError('Corrija as tags antes de assinar: a edição modificaria um documento já assinado.')
        expected=options.get('input_sha256')
        if not isinstance(expected,str) or expected!=hashlib.sha256(snapshot.read_bytes()).hexdigest():
            raise ValueError('Inspecione novamente o documento: a correção exige o SHA-256 exato da origem revisada.')
        if options.get('create_page_tags') is not None: _create_page_tags(writer,options['create_page_tags'])
        _,nodes,index,_=_tree(writer)
        seen=set()
        for edit in edits:
            identity=edit.get('id')
            if identity not in index or identity in seen: raise ValueError('Tag desconhecida ou repetida nas alterações.')
            seen.add(identity);reference,node=index[identity]
            if set(edit)-{'id','role','alt','actual_text','title','language','children','scope'}:
                raise ValueError('A alteração contém um campo não suportado.')
            if 'role' in edit:
                if edit['role'] not in ROLES: raise ValueError('Papel estrutural não suportado.')
                node[g.pdf_name('/S')]=g.pdf_name('/'+edit['role'])
            for option,key in [('alt','/Alt'),('actual_text','/ActualText'),('title','/T'),('language','/Lang')]:
                if option in edit:
                    if option=='language' and edit[option]=='':
                        node.pop('/Lang',None)
                        continue
                    value=_language(edit[option]) if option=='language' else _text(edit[option],option)
                    node[g.pdf_name(key)]=g.pdf_string(value)
            if 'scope' in edit:
                if node['/S']!='/TH' or edit['scope'] not in ('Row','Column','Both'):
                    raise ValueError('Scope Row, Column ou Both é permitido somente em cabeçalhos TH.')
                attrs=_array(_raw(node,'/A'))
                kept=[a for a in attrs if not (isinstance(_object(a),g.DictionaryObject) and _object(a).get('/O')=='/Table')]
                old=next((_object(a) for a in attrs if isinstance(_object(a),g.DictionaryObject) and _object(a).get('/O')=='/Table'),{})
                table=g.DictionaryObject(dict(old)); table[g.pdf_name('/O')]=g.pdf_name('/Table');table[g.pdf_name('/Scope')]=g.pdf_name('/'+edit['scope'])
                node[g.pdf_name('/A')]=g.ArrayObject(kept+[table])
            if 'children' in edit:
                current=_array(_raw(node,'/K')); ids=[_id(k) if isinstance(_object(k),g.DictionaryObject) and '/S' in _object(k) else None for k in current]
                order=edit['children']
                if (not ids or None in ids or not isinstance(order,list) or not all(isinstance(i,str) for i in order)
                    or len(order)!=len(ids) or len(set(order))!=len(order) or set(order)!=set(ids)):
                    raise ValueError('Reordene somente todos os filhos estruturais do mesmo pai, sem remover conteúdo nem mover MCIDs.')
                references=dict(zip(ids,current)); node[g.pdf_name('/K')]=g.ArrayObject([references[i] for i in order])
            writer.mark_update(reference)
        if 'language' in options: writer.root[g.pdf_name('/Lang')]=g.pdf_string(_language(options['language']))
        writer.update_root()
        # A missing tree is not "fixed" with Marked=true or PDF/UA metadata.
        if '/StructTreeRoot' not in writer.root: raise ValueError('Este PDF não tem tags. Defina primeiro os blocos de página manualmente.')
        with Path(output_path).open('xb') as destination: writer.write(destination)
