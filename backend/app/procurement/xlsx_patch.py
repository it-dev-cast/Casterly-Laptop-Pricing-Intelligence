"""Minimal OOXML patch: keep original archive members, add prices and standalone report sheets.

Unlike an openpyxl round-trip this retains original drawings, pivot/cache parts, chart XML,
worksheet relationships and unsupported extensions byte-for-byte. Only explicit pricing cells,
asset-sheet dimensions, workbook/style registries and new report parts are modified.
"""
from __future__ import annotations
import io
import posixpath
from zipfile import ZipFile, ZIP_DEFLATED
from xml.dom import minidom as dom

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/package/2006/content-types'


def children(node, tag):
    return [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE and c.localName == tag]


def first(node, tag):
    return next(iter(children(node, tag)), None)


def parse(blob):
    return dom.parseString(blob)


def xml(doc):
    return doc.toxml(encoding='UTF-8')


def members(data):
    with ZipFile(io.BytesIO(data)) as z:
        return {n:z.read(n) for n in z.namelist()}


def sheet_paths(parts):
    book, rel = parse(parts['xl/workbook.xml']), parse(parts['xl/_rels/workbook.xml.rels'])
    paths = {r.getAttribute('Id'):r.getAttribute('Target') for r in children(rel.documentElement, 'Relationship')}
    out = {}
    for sheet in children(first(book.documentElement,'sheets'),'sheet'):
        target = paths[sheet.getAttributeNS(R,'id')]
        out[sheet.getAttribute('name')] = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
    return out


def merge_styles(original, generated):
    a,b = parse(original),parse(generated)
    root,source = a.documentElement,b.documentElement
    offsets = {}
    for tag in ('fonts','fills','borders','cellStyleXfs','cellXfs'):
        aa,bb = first(root,tag),first(source,tag)
        offsets[tag] = len([n for n in aa.childNodes if n.nodeType == n.ELEMENT_NODE]) if aa else 0
        if aa is None:
            aa = a.createElementNS(S,tag)
            root.appendChild(aa)
        for n in (c for c in bb.childNodes if c.nodeType == c.ELEMENT_NODE) if bb else []:
            aa.appendChild(a.importNode(n,True))
        aa.setAttribute('count',str(len([n for n in aa.childNodes if n.nodeType == n.ELEMENT_NODE])))
    af,bf = first(root,'numFmts'),first(source,'numFmts')
    if af is None:
        af = a.createElementNS(S,'numFmts')
        root.insertBefore(af,root.firstChild)
    used = {int(n.getAttribute('numFmtId')) for n in children(af,'numFmt')}
    number_map = {}
    for n in children(bf,'numFmt') if bf else []:
        old = int(n.getAttribute('numFmtId'))
        new = max(used | {163})+1
        used.add(new)
        nn = a.importNode(n,True)
        nn.setAttribute('numFmtId',str(new))
        af.appendChild(nn)
        number_map[old] = new
    af.setAttribute('count',str(len(children(af,'numFmt'))))
    for tag in ('cellStyleXfs','cellXfs'):
        xfs = children(first(root,tag),'xf')
        for xf in xfs[offsets[tag]:]:
            for key,base in (('fontId','fonts'),('fillId','fills'),('borderId','borders')):
                if xf.hasAttribute(key):
                    xf.setAttribute(key,str(int(xf.getAttribute(key))+offsets[base]))
            if xf.hasAttribute('numFmtId'):
                old = int(xf.getAttribute('numFmtId'))
                xf.setAttribute('numFmtId',str(number_map.get(old,old)))
            if xf.hasAttribute('xfId'):
                xf.setAttribute('xfId',str(int(xf.getAttribute('xfId'))+offsets['cellStyleXfs']))
    return xml(a), offsets['cellXfs']


def column_index(ref):
    value = 0
    for c in ref:
        if not c.isalpha():
            break
        value = value*26+ord(c.upper())-64
    return value


def patch(original: bytes, generated: bytes, sheet_name: str, price_col: int, total_col: int | None,
          header_row: int, asset_rows: list[int], *, footer_rows: list[int] = ()) -> tuple[bytes,dict]:
    src,out = members(original),members(generated)
    old_paths,new_paths = sheet_paths(src),sheet_paths(out)
    styles,offset = merge_styles(src['xl/styles.xml'],out['xl/styles.xml'])
    result = dict(src)
    result['xl/styles.xml'] = styles
    original_sheet = old_paths[sheet_name]
    asset,generated_asset = parse(src[original_sheet]),parse(out[new_paths[sheet_name]])
    data = first(asset.documentElement,'sheetData')
    rows = {int(r.getAttribute('r')):r for r in children(data,'row')}
    target_rows = set(asset_rows) | {header_row} | set(footer_rows)
    target_cols = {price_col} | ({total_col} if total_col else set())
    for row in children(first(generated_asset.documentElement,'sheetData'),'row'):
        index = int(row.getAttribute('r'))
        if index not in target_rows:
            continue
        dest = rows.get(index)
        if dest is None:
            dest = asset.createElementNS(S,'row'); dest.setAttribute('r',str(index));data.appendChild(dest)
        for attr in ('ht', 'customHeight'):
            if row.hasAttribute(attr):
                dest.setAttribute(attr, row.getAttribute(attr))
        for cell in children(row,'c'):
            ref = cell.getAttribute('r')
            if column_index(ref) not in target_cols and index not in footer_rows:
                previous = next((c for c in children(dest,'c') if c.getAttribute('r') == ref), None)
                if previous is not None:
                    previous.setAttribute('s', str(int(cell.getAttribute('s') or 0) + offset))
                continue
            for previous in children(dest,'c'):
                if previous.getAttribute('r') == ref:
                    dest.removeChild(previous)
            fresh = asset.importNode(cell,True)
            if fresh.hasAttribute('s'):
                fresh.setAttribute('s',str(int(fresh.getAttribute('s'))+offset))
            # Source cells remain in ascending column order.
            after = next((c for c in children(dest,'c') if column_index(c.getAttribute('r')) > column_index(ref)),None)
            dest.insertBefore(fresh,after)
    # Preserve source values/objects, transplant only the authorized presentation settings.
    order = ['sheetPr','dimension','sheetViews','sheetFormatPr','cols','sheetData','sheetCalcPr',
             'sheetProtection','protectedRanges','scenarios','autoFilter','sortState','dataConsolidate',
             'customSheetViews','mergeCells','phoneticPr','conditionalFormatting','dataValidations',
             'hyperlinks','printOptions','pageMargins','pageSetup','headerFooter','rowBreaks',
             'colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing',
             'legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems',
             'tableParts','extLst']
    for tag in ('sheetViews','cols','autoFilter','printOptions','pageMargins','pageSetup','headerFooter'):
        generated_node = first(generated_asset.documentElement, tag)
        if generated_node is None:
            continue
        previous = first(asset.documentElement, tag)
        fresh = asset.importNode(generated_node, True)
        if previous is not None:
            asset.documentElement.replaceChild(fresh, previous)
        else:
            after = next((n for n in asset.documentElement.childNodes if n.nodeType == n.ELEMENT_NODE
                          and n.localName in order and order.index(n.localName) > order.index(tag)), None)
            asset.documentElement.insertBefore(fresh, after)
    dim = first(asset.documentElement,'dimension')
    gen_dim = first(generated_asset.documentElement,'dimension')
    if dim and gen_dim:
        dim.setAttribute('ref',gen_dim.getAttribute('ref'))
    result[original_sheet] = xml(asset)
    book,rels,types = parse(src['xl/workbook.xml']),parse(src['xl/_rels/workbook.xml.rels']),parse(src['[Content_Types].xml'])
    sheets = first(book.documentElement,'sheets')
    max_id = max(int(s.getAttribute('sheetId')) for s in children(sheets,'sheet'))
    used_rel = {r.getAttribute('Id') for r in children(rels.documentElement,'Relationship')}
    # Copy each new report's image/drawing relationship graph under collision-free names.
    copied = {}
    def copy_part(source, destination=None):
        if source in copied:
            return copied[source]
        destination = destination or posixpath.join(posixpath.dirname(source), 'clpi_' + posixpath.basename(source))
        while destination in result:
            directory, filename = posixpath.split(destination)
            destination = posixpath.join(directory, 'clpi_' + filename)
        copied[source] = destination
        result[destination] = out[source]
        source_rels = posixpath.join(posixpath.dirname(source), '_rels', posixpath.basename(source)+'.rels')
        if source_rels in out:
            graph = parse(out[source_rels])
            for rel in children(graph.documentElement, 'Relationship'):
                if rel.getAttribute('TargetMode') == 'External':
                    continue
                target = rel.getAttribute('Target')
                target = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(source),target))
                rel.setAttribute('Target', '/' + copy_part(target))
            destination_rels = posixpath.join(posixpath.dirname(destination), '_rels', posixpath.basename(destination)+'.rels')
            result[destination_rels] = xml(graph)
        generated_types = parse(out['[Content_Types].xml'])
        for ct in children(generated_types.documentElement, 'Override'):
            if ct.getAttribute('PartName') == '/' + source:
                nn = types.importNode(ct, True)
                nn.setAttribute('PartName', '/' + destination)
                types.documentElement.appendChild(nn)
        for ct in children(generated_types.documentElement, 'Default'):
            if not any(n.getAttribute('Extension') == ct.getAttribute('Extension') for n in children(types.documentElement, 'Default')):
                types.documentElement.appendChild(types.importNode(ct, True))
        return destination
    reports = []
    for title,path in new_paths.items():
        if title in old_paths:
            continue
        max_id += 1
        part = f'xl/worksheets/clpi_report_{max_id}.xml'
        while part in result:
            max_id += 1
            part = f'xl/worksheets/clpi_report_{max_id}.xml'
        rid = f'rIdCLPI{max_id}'
        while rid in used_rel:
            rid += 'x'
        used_rel.add(rid)
        report = parse(out[path])
        for cell in report.getElementsByTagNameNS(S,'c'):
            if cell.hasAttribute('s'):
                cell.setAttribute('s',str(int(cell.getAttribute('s'))+offset))
        copy_part(path, part)
        result[part] = xml(report)
        s = book.createElementNS(S,'sheet');s.setAttribute('name',title);s.setAttribute('sheetId',str(max_id));s.setAttribute('xmlns:r',R);s.setAttributeNS(R,'r:id',rid);sheets.appendChild(s)
        rel = rels.createElementNS(P,'Relationship');rel.setAttribute('Id',rid);rel.setAttribute('Type',R+'/worksheet');rel.setAttribute('Target','/'+part);rels.documentElement.appendChild(rel)
        reports.append(title)
    result['xl/workbook.xml'],result['xl/_rels/workbook.xml.rels'],result['[Content_Types].xml'] = xml(book),xml(rels),xml(types)
    stream=io.BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for path,blob in result.items():
            z.writestr(path,blob)
    modified = [n for n in src if src[n] != result[n]]
    return stream.getvalue(), {'mode':'minimal_ooxml_patch','original_parts':len(src),
        'unchanged_parts':sum(src[n]==result[n] for n in src),'modified_parts':modified,
        'report_sheets':reports,'warning':'Pricing, totals and asset-table presentation updated; original chart/pivot/image parts retained. Recalculate Excel formulas on open; Excel application rendering not verified.'}


def cache_formula_values(data: bytes, values: dict[str, dict[str, object]]) -> bytes:
    """Persist independently computed initial totals for viewers without recalculation."""
    parts = members(data)
    for name, path in sheet_paths(parts).items():
        if name not in values:
            continue
        doc = parse(parts[path])
        for cell in doc.getElementsByTagNameNS(S, 'c'):
            ref = cell.getAttribute('r')
            if ref in values[name] and first(cell, 'f') is not None:
                old = first(cell, 'v')
                if old is not None:
                    cell.removeChild(old)
                value = doc.createElementNS(S, 'v')
                value.appendChild(doc.createTextNode(str(values[name][ref])))
                cell.appendChild(value)
        parts[path] = xml(doc)
    stream = io.BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as z:
        for name, blob in parts.items():
            z.writestr(name, blob)
    return stream.getvalue()
