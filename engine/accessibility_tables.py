"""Explicit table attributes and byte-exact header associations for PDF tags.

This validates the declared structural grid, not the visual/semantic truth of a
table. It never moves MCIDs, rewrites page streams or infers header meanings.
"""
from collections import deque

from pyhanko.pdf_utils import generic as g

from pdf_accessibility import _raw, _object, _id, _array

FIELDS = {'row_span':'/RowSpan','column_span':'/ColSpan','headers':'/Headers'}


def _bytes(value):
    value=_object(value)
    if not isinstance(value,(g.TextStringObject,g.ByteStringObject)):
        raise ValueError('Os identificadores estruturais precisam ser strings PDF, sem conversão implícita.')
    try: result=value.original_bytes
    except Exception as error:
        raise ValueError('Não foi possível preservar os bytes de um identificador estrutural.') from error
    if not 1<=len(result)<=256:
        raise ValueError('Um identificador estrutural precisa ter de 1 a 256 bytes.')
    return result


def set_attribute(node,key,value):
    """Copy only the selected Table dictionaries, retaining shared neighbours."""
    original=_object(_raw(node,'/A'))
    if original is not None and not isinstance(original,(g.ArrayObject,g.DictionaryObject)):
        raise ValueError('Os atributos da tag não permitem alterar a tabela com segurança.')
    attributes=_array(original);result=[];found=False;changed=False
    for reference in attributes:
        obj=_object(reference)
        if isinstance(obj,g.DictionaryObject) and _object(_raw(obj,'/O'))=='/Table':
            found=True
            if value is None and key not in obj:
                result.append(reference);continue
            replacement=g.DictionaryObject({name:obj.raw_get(name) for name in obj})
            if value is None:replacement.pop(key,None)
            else:replacement[g.pdf_name(key)]=value
            result.append(replacement);changed=True
        else:result.append(reference)
    if value is not None and not found:
        result.append(g.DictionaryObject({g.pdf_name('/O'):g.pdf_name('/Table'),g.pdf_name(key):value}));changed=True
    if changed:
        node[g.pdf_name('/A')]=result[0] if isinstance(original,g.DictionaryObject) and len(result)==1 else g.ArrayObject(result)


def attributes(node):
    result={};present=set()
    raw=_object(_raw(node,'/A'))
    if raw is not None and not isinstance(raw,(g.DictionaryObject,g.ArrayObject)):
        raise ValueError('Atributos de tabela malformados.')
    for reference in _array(raw):
        obj=_object(reference)
        if not isinstance(obj,g.DictionaryObject) or _object(_raw(obj,'/O'))!='/Table':continue
        for name,key in FIELDS.items():
            if key not in obj:continue
            value=_object(_raw(obj,key));present.add(name)
            if name=='headers':
                if not isinstance(value,g.ArrayObject) or len(value)>1000:
                    raise ValueError('Headers precisa ser uma lista de até 1.000 identificadores.')
                value=[_bytes(item) for item in value]
                if len(set(value))!=len(value):raise ValueError('A célula contém cabeçalhos duplicados.')
            else:
                if not isinstance(value,g.NumberObject) or not 1<=int(value)<=1000:
                    raise ValueError('RowSpan e ColSpan precisam ser inteiros de 1 a 1.000.')
                value=int(value)
            if name in result and result[name]!=value:
                raise ValueError('Há valores de tabela conflitantes em atributos compartilhados ou revisionados.')
            result[name]=value
    return result,present


def _table_id(identity,records):
    seen=set();current=records[identity]['parent']
    while current is not None:
        if current in seen:raise ValueError('Ciclo na ascendência de uma tabela.')
        seen.add(current)
        if records[current]['role']=='Table':return current
        current=records[current]['parent']
    return None


def _identifiers(index):
    by_bytes={};by_tag={}
    for identity,(_,node) in index.items():
        if '/ID' not in node:continue
        value=_bytes(_raw(node,'/ID'))
        if value in by_bytes:raise ValueError('Há IDs estruturais duplicados; resolva a ambiguidade antes de associar cabeçalhos.')
        by_bytes[value]=identity;by_tag[identity]=value
    return by_bytes,by_tag


def describe(nodes,index):
    """Inspection remains possible when legacy attributes need manual repair."""
    records={node['id']:node for node in nodes}
    try:by_bytes,_=_identifiers(index);identity_error=None
    except ValueError as error:by_bytes={};identity_error=str(error)
    for record in nodes:
        record['table_id']=_table_id(record['id'],records)
        record['row_span']=None;record['column_span']=None;record['headers']=None
        record['table_attribute_error']=None
        if record['role'] not in ('TH','TD'):continue
        try:
            values,present=attributes(index[record['id']][1])
            record['present_fields'].extend(sorted(present))
            record['row_span']=values.get('row_span');record['column_span']=values.get('column_span')
            headers=values.get('headers',[])
            if headers and identity_error:raise ValueError(identity_error)
            if any(header not in by_bytes for header in headers):raise ValueError('Há cabeçalhos sem ID estrutural correspondente.')
            record['headers']=[by_bytes[header] for header in headers]
        except ValueError as error:record['table_attribute_error']=str(error)


def _read_id_tree(root,index,expected):
    reference=_raw(root,'/IDTree')
    if reference is None:return
    seen=set();entries={};count=0
    def walk(reference,depth):
        nonlocal count
        if depth>64:raise ValueError('IDTree excede o limite de profundidade.')
        obj=_object(reference);identity=_id(reference) or ('direct',id(obj))
        if identity in seen:raise ValueError('IDTree contém ciclo ou filho repetido.')
        seen.add(identity);count+=1
        if count>10000 or not isinstance(obj,g.DictionaryObject) or set(obj)-{'/Names','/Kids','/Limits'}:
            raise ValueError('IDTree contém uma estrutura não suportada.')
        if ('/Names' in obj)==('/Kids' in obj):raise ValueError('Cada nó de IDTree precisa ter Names ou Kids.')
        pairs=[]
        if '/Names' in obj:
            values=_object(_raw(obj,'/Names'))
            if not isinstance(values,g.ArrayObject) or len(values)%2:raise ValueError('Names de IDTree está malformado.')
            for offset in range(0,len(values),2):
                key=_bytes(values[offset]);target=_id(values.raw_get(offset+1))
                if target not in index or expected.get(key)!=target or key in entries:
                    raise ValueError('IDTree tem IDs duplicados, órfãos ou apontando para outra tag.')
                entries[key]=target;pairs.append(key)
                if len(entries)>100000:raise ValueError('IDTree excede 100.000 identificadores.')
        else:
            children=_object(_raw(obj,'/Kids'))
            if not isinstance(children,g.ArrayObject) or not children:raise ValueError('Kids de IDTree está malformado.')
            for child in children:
                keys=walk(child,depth+1)
                if not keys:raise ValueError('IDTree contém um filho sem nomes.')
                pairs.extend(keys)
        if pairs!=sorted(pairs) or len(pairs)!=len(set(pairs)):
            raise ValueError('Os nomes de IDTree não estão em ordem binária estrita.')
        if '/Limits' in obj:
            limits=_object(_raw(obj,'/Limits'))
            if not isinstance(limits,g.ArrayObject) or len(limits)!=2 or not pairs or [_bytes(x) for x in limits]!=[pairs[0],pairs[-1]]:
                raise ValueError('Limits de IDTree não corresponde aos nomes armazenados.')
        return pairs
    walk(reference,0)
    if entries!=expected:raise ValueError('IDTree não indexa exatamente os IDs da árvore estrutural.')


def _write_id_tree(writer,root,by_bytes,index):
    pairs=sorted(by_bytes.items());level=[]
    for start in range(0,len(pairs),64):
        chunk=pairs[start:start+64];names=g.ArrayObject()
        for key,identity in chunk:names.extend([g.ByteStringObject(key),index[identity][0]])
        node=g.DictionaryObject({g.pdf_name('/Names'):names,g.pdf_name('/Limits'):g.ArrayObject([
            g.ByteStringObject(chunk[0][0]),g.ByteStringObject(chunk[-1][0])])})
        level.append((writer.add_object(node),chunk[0][0],chunk[-1][0]))
    while len(level)>1:
        next_level=[]
        for start in range(0,len(level),64):
            chunk=level[start:start+64]
            node=g.DictionaryObject({g.pdf_name('/Kids'):g.ArrayObject([item[0] for item in chunk]),
                g.pdf_name('/Limits'):g.ArrayObject([g.ByteStringObject(chunk[0][1]),g.ByteStringObject(chunk[-1][2])])})
            next_level.append((writer.add_object(node),chunk[0][1],chunk[-1][2]))
        level=next_level
    if level:root[g.pdf_name('/IDTree')]=level[0][0]


def _table_cells(table,records,index):
    def children(identity):
        values=_array(_raw(index[identity][1],'/K'))
        ids=[_id(value) for value in values]
        if any(value is None for value in ids) or ids!=records[identity]['children']:
            raise ValueError('Os contêineres da tabela precisam ter apenas filhos estruturais inequívocos.')
        return ids
    rows=[]
    for identity in children(table):
        role=records[identity]['role']
        if role=='Caption':continue
        if role=='TR':rows.append(identity)
        elif role in ('THead','TBody','TFoot'):
            section=children(identity)
            if any(records[child]['role']!='TR' for child in section):raise ValueError('A seção da tabela contém filhos diferentes de TR.')
            rows.extend(section)
        else:raise ValueError('A tabela precisa conter linhas TR ou seções THead/TBody/TFoot explícitas.')
    if not 1<=len(rows)<=1000:raise ValueError('A grade da tabela precisa ter de 1 a 1.000 linhas.')
    occupied=set();cells=[];width=0
    for row,identity in enumerate(rows):
        column=0
        for cell in children(identity):
            if records[cell]['role'] not in ('TH','TD'):raise ValueError('Uma linha da tabela contém uma tag diferente de TH/TD.')
            values,_=attributes(index[cell][1]);height=values.get('row_span',1);span=values.get('column_span',1)
            while (row,column) in occupied:column+=1
            if row+height>len(rows) or column+span>1000:raise ValueError('A célula mesclada ultrapassa os limites da grade declarada.')
            if len(occupied)+height*span>100000:raise ValueError('A grade excede 100.000 posições; divida a tabela antes de corrigir.')
            places={(r,c) for r in range(row,row+height) for c in range(column,column+span)}
            if occupied.intersection(places):raise ValueError('As células mescladas se sobrepõem na grade declarada.')
            occupied.update(places);column+=span;width=max(width,column);cells.append(cell)
            if len(occupied)>100000:raise ValueError('A grade excede 100.000 posições; divida a tabela antes de corrigir.')
    if not width or len(occupied)!=len(rows)*width:
        raise ValueError('A grade declarada contém lacunas; confira RowSpan, ColSpan e as células de cada linha.')
    return cells


def _validate_headers(cells,records,index,by_bytes,table):
    edges={identity:[] for identity in cells};incoming={identity:0 for identity in cells}
    for identity in cells:
        values,_=attributes(index[identity][1])
        for key in values.get('headers',[]):
            target=by_bytes.get(key)
            if target not in edges or target==identity or records[target]['role']!='TH' or _table_id(target,records)!=table:
                raise ValueError('Cada cabeçalho precisa identificar outra tag TH da mesma tabela.')
            edges[identity].append(target);incoming[target]+=1
    ready=deque(identity for identity,number in incoming.items() if number==0);visited=0
    while ready:
        identity=ready.popleft();visited+=1
        for target in edges[identity]:
            incoming[target]-=1
            if incoming[target]==0:ready.append(target)
    if visited!=len(cells):raise ValueError('As associações entre cabeçalhos contêm um ciclo.')


def _guard_changed_header_roles(index,edits):
    changed={edit['id'] for edit in edits if 'role' in edit and edit['role']!='TH' and '/ID' in index[edit['id']][1]}
    if not changed:return
    _,by_tag=_identifiers(index);keys={by_tag[identity] for identity in changed}
    for _,node in index.values():
        for reference in _array(_raw(node,'/A')):
            obj=_object(reference)
            if not isinstance(obj,g.DictionaryObject) or _object(_raw(obj,'/O'))!='/Table' or '/Headers' not in obj:continue
            values=_object(_raw(obj,'/Headers'))
            if not isinstance(values,g.ArrayObject):raise ValueError('Há uma associação Headers malformada; corrija-a antes de mudar o papel do cabeçalho.')
            if any(_bytes(value) in keys for value in values):
                raise ValueError('Uma célula ainda referencia este cabeçalho. Remova a associação ou mantenha o papel TH.')


def apply(writer,root,nodes,index,edits,digest):
    selected=[edit for edit in edits if set(edit).intersection(FIELDS)]
    if not selected:
        _guard_changed_header_roles(index,edits);return
    records={node['id']:node for node in nodes};tables=set();header_edits=[]
    for edit in selected:
        identity=edit['id'];reference,node=index[identity];table=_table_id(identity,records)
        if records[identity]['role'] not in ('TH','TD') or table is None:
            raise ValueError('Defina a célula como TH/TD dentro de uma estrutura Table/TR antes de editar suas associações ou extensões.')
        tables.add(table)
        for name in ('row_span','column_span'):
            if name not in edit:continue
            value=edit[name]
            if value is not None and (type(value) is not int or not 1<=value<=1000):
                raise ValueError('RowSpan e ColSpan precisam ser inteiros de 1 a 1.000, ou null para remover.')
            set_attribute(node,FIELDS[name],None if value is None else g.NumberObject(value))
        if 'headers' in edit:header_edits.append(edit)
        writer.mark_update(reference)
    if header_edits:
        by_bytes,by_tag=_identifiers(index);_read_id_tree(root,index,by_bytes)
        for edit in header_edits:
            identity=edit['id'];value=edit['headers'];table=_table_id(identity,records)
            if value is not None and (not isinstance(value,list) or len(value)>1000 or
                not all(isinstance(target,str) and target in index for target in value) or len(set(value))!=len(value)):
                raise ValueError('Selecione até 1.000 tags de cabeçalho conhecidas e distintas.')
            names=[]
            for target in value or []:
                if target==identity or records[target]['role']!='TH' or _table_id(target,records)!=table:
                    raise ValueError('Cada cabeçalho precisa identificar outra tag TH da mesma tabela.')
                if target not in by_tag:
                    base=f'PDF-TH-{digest[:12]}-{target.replace(":","-")}'.encode('ascii');key=base;suffix=0
                    while key in by_bytes:suffix+=1;key=base+f'-{suffix}'.encode('ascii')
                    by_bytes[key]=target;by_tag[target]=key
                    ref,header=index[target];header[g.pdf_name('/ID')]=g.ByteStringObject(key);writer.mark_update(ref)
                names.append(g.ByteStringObject(by_tag[target]))
            set_attribute(index[identity][1],'/Headers',None if value is None else g.ArrayObject(names))
        _write_id_tree(writer,root,by_bytes,index)
        writer.mark_update(_raw(writer.root,'/StructTreeRoot'))
    else:by_bytes,_=_identifiers(index)
    for table in tables:
        cells=_table_cells(table,records,index);_validate_headers(cells,records,index,by_bytes,table)
    _guard_changed_header_roles(index,edits)
