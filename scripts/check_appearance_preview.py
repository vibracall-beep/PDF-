#!/usr/bin/env python3
"""Bind the seven-frame appearance diagnostic to one unchanged minimal bundle.

Uses only the standard library. No engine, runtime installation, rendering,
image correction, signature change, or application-wide approval occurs here.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import plistlib
import re
import stat
import struct
import tarfile
import zlib

MIB = 1024 ** 2
MAX_TAR = 300 * MIB
MAX_PNG = 80 * MIB
MAX_REPORT = 2 * MIB
FILES = {'Contents/MacOS/PDF': 256 * MIB, 'Contents/Info.plist': 65536,
         'Contents/Resources/installation.lock': 0, 'Contents/_CodeSignature/CodeResources': 8 * MIB}
DIRECTORIES = ('PDF.app', 'PDF.app/Contents', 'PDF.app/Contents/MacOS',
               'PDF.app/Contents/Resources', 'PDF.app/Contents/_CodeSignature')
PHASES = ('light-initial', 'dark-attached-1', 'dark-attached-2', 'customization',
          'dark-recreated', 'light-return', 'system')
SELECTIONS = ('light', 'dark', 'dark', 'light', 'dark', 'light', 'system')
PNG_NAMES = ('PDF-appearance.png',) + tuple('PDF-appearance.' + phase + '.png' for phase in PHASES[1:])
CHECKS = ('seven-original-frames-in-order', 'light-dark-customization-light-system-selections',
          'same-real-window', 'six-workspace-toolbar-reports',
          'three-controls-central-contrast-every-workspace-frame', 'attached-toolbar-identities-preserved',
          'two-separate-dark-attached-captures', 'toolbar-controls-return-after-customization',
          'system-releases-appkit-overrides', 'no-document-session', 'background-work-drained', 'private-state-cleanup')
CONTROLS = ('autoSidebar', 'pdf.commands.toolbar', 'pdf.customize.toolbar')
CONTROL_LABELS = {
    'autoSidebar': {'Hide Sidebar', 'Show Sidebar', 'Ocultar Barra Lateral',
                    'Mostrar Barra Lateral', 'Ocultar barra lateral', 'Mostrar barra lateral'},
    'pdf.commands.toolbar': {'Comandos'}, 'pdf.customize.toolbar': {'Personalizar'},
}
CONTROL_IDENTIFICATION = 'public-NSToolbarItem-label-paletteLabel-and-actual-view'


def require(condition, detail):
    if not condition:
        raise ValueError('Appearance diagnostic: ' + detail)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(data):
    return {'bytes': len(data), 'sha256': sha(data)}


def read_regular(path, limit, empty=False):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and (0 if empty else 1) <= before.st_size <= limit,
                'input must be a bounded regular file: ' + str(path))
        data = stream.read(limit + 1); after = os.fstat(stream.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (len(data), after.st_mtime_ns, after.st_ctime_ns) and len(data) == after.st_size,
                'input changed during reading')
    return data


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('Non-finite JSON is not accepted.')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def write_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    with Path(path).open('xb') as stream:
        stream.write(data)
    return fingerprint(data)


def source_identity(source):
    require(isinstance(source, str) and re.fullmatch('[0-9a-f]{40}', source), 'exact source commit required')


def bundle_files(app, production_plist):
    app = Path(app)
    require(app.is_dir() and not app.is_symlink(), 'real diagnostic app directory required')
    actual = {}
    found_dirs = {'PDF.app'}
    for path in app.rglob('*'):
        info = path.lstat(); name = path.relative_to(app).as_posix()
        require(not stat.S_ISLNK(info.st_mode), 'bundle links are not allowed')
        if stat.S_ISDIR(info.st_mode):
            found_dirs.add('PDF.app/' + name)
            continue
        require(name in FILES and stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                'unexpected or linked bundle input: ' + name)
        data = read_regular(path, FILES[name], empty=FILES[name] == 0)
        mode = stat.S_IMODE(info.st_mode)
        require(mode in (0o444, 0o644, 0o755) and (mode == 0o755) == (name == 'Contents/MacOS/PDF'),
                'unexpected diagnostic file permissions')
        actual[name] = dict(fingerprint(data), mode=mode)
    require(set(actual) == set(FILES) and found_dirs == set(DIRECTORIES),
            'minimal bundle inventory differs; no runtime or engine may be included')
    plist = read_regular(app/'Contents/Info.plist', 65536)
    require(plist == read_regular(production_plist, 65536), 'production Info.plist changed')
    metadata = plistlib.loads(plist)
    require(metadata.get('CFBundleIdentifier') == 'local.pdf.desktop' and metadata.get('CFBundleExecutable') == 'PDF',
            'production bundle identity differs')
    return actual


def pack(app, production_plist, source, sdk, output):
    source_identity(source)
    require(re.fullmatch(r'26(?:\.[0-9]+){0,2}', sdk) is not None, 'the first bundle must use SDK 26')
    files = bundle_files(app, production_plist)
    output = Path(output); output.mkdir(mode=0o700, parents=True, exist_ok=False)
    archive = output/'PDF-appearance-bundle.tar.gz'
    with archive.open('xb') as target, gzip.GzipFile(fileobj=target, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as tar:
            for name in DIRECTORIES:
                item = tarfile.TarInfo(name); item.type = tarfile.DIRTYPE; item.mode = 0o700
                tar.addfile(item)
            for name, record in sorted(files.items()):
                data = read_regular(Path(app)/name, FILES[name], empty=FILES[name] == 0)
                require(fingerprint(data) == {key: record[key] for key in ('bytes', 'sha256')}, 'bundle changed while packing')
                item = tarfile.TarInfo('PDF.app/' + name); item.size = len(data); item.mode = record['mode']
                tar.addfile(item, io.BytesIO(data))
    manifest = {'schemaVersion': 1, 'scope': 'minimal-appearance-diagnostic-only', 'sourceCommit': source,
                'builtSDK': sdk, 'files': files, 'tar': fingerprint(read_regular(archive, MAX_TAR)),
                'sourceCommitAuthenticatedByThisHelper': False, 'completeApplicationApproved': False}
    write_json(output/'appearance-bundle.json', manifest)
    (output/'PDF-appearance-bundle.tar.gz.sha256').write_text(manifest['tar']['sha256'] + '  PDF-appearance-bundle.tar.gz\n')
    return manifest


def manifest_at(path, source, expected_hash=None):
    source_identity(source)
    raw = read_regular(path, MAX_REPORT)
    if expected_hash is not None:
        require(re.fullmatch('[0-9a-f]{64}', expected_hash) is not None and sha(raw) == expected_hash, 'manifest checksum differs')
    value = parse_json(raw)
    require(isinstance(value, dict) and set(value) == {'schemaVersion', 'scope', 'sourceCommit', 'builtSDK', 'files', 'tar',
            'sourceCommitAuthenticatedByThisHelper', 'completeApplicationApproved'}, 'manifest fields differ')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['sourceCommit'] == source
            and value['scope'] == 'minimal-appearance-diagnostic-only'
            and value['sourceCommitAuthenticatedByThisHelper'] is False and value['completeApplicationApproved'] is False
            and re.fullmatch(r'26(?:\.[0-9]+){0,2}', value['builtSDK']), 'manifest identity or scope differs')
    require(isinstance(value['files'], dict) and set(value['files']) == set(FILES), 'manifest file inventory differs')
    for name, record in list(value['files'].items()) + [('tar', value['tar'])]:
        require(isinstance(record, dict) and set(record) == ({'bytes', 'sha256'} if name == 'tar' else {'bytes', 'sha256', 'mode'}), 'file record fields differ')
        require(type(record['bytes']) is int and (0 if name.endswith('installation.lock') else 1) <= record['bytes'] <= (MAX_TAR if name == 'tar' else FILES[name])
                and isinstance(record['sha256'], str) and re.fullmatch('[0-9a-f]{64}', record['sha256']), 'invalid file size/hash')
        if name != 'tar':
            require(type(record['mode']) is int and record['mode'] in (0o444, 0o644, 0o755)
                    and (record['mode'] == 0o755) == (name == 'Contents/MacOS/PDF'), 'unsafe file mode')
    return value


def inspect_archive(archive, manifest, expected_hash):
    require(re.fullmatch('[0-9a-f]{64}', expected_hash) is not None, 'independent archive hash required')
    compressed = read_regular(archive, MAX_TAR)
    require(sha(compressed) == expected_hash == manifest['tar']['sha256']
            and len(compressed) == manifest['tar']['bytes'], 'archive checksum or size differs before extraction')
    decoder = zlib.decompressobj(31)
    raw = decoder.decompress(compressed, MAX_TAR + 1)
    require(len(raw) <= MAX_TAR and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
            and len(raw) % 512 == 0, 'gzip is oversized, truncated, concatenated or has trailing data')
    files = {}; names = []; cursor = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as tar:
        for item in tar:
            require(item.offset == cursor and item.offset_data == cursor + 512 and not item.pax_headers,
                    'extended or unexpected tar headers are not permitted')
            cursor = item.offset_data + ((item.size + 511) // 512) * 512
            require(item.name not in names and len(names) < len(DIRECTORIES) + len(FILES), 'duplicate or excessive archive members')
            names.append(item.name)
            require(item.uid == item.gid == 0 and item.linkname == '', 'unexpected ownership or archive link')
            if item.name in DIRECTORIES:
                require(item.isdir() and item.size == 0 and item.mode == 0o700, 'directory type/permissions differ')
                continue
            name = item.name.removeprefix('PDF.app/')
            require(item.name == 'PDF.app/' + name and name in FILES and item.isreg(), 'unsafe archive path or type')
            record = manifest['files'][name]
            require(item.size == record['bytes'] and item.mode == record['mode'], 'member size/mode differs')
            data = tar.extractfile(item).read(FILES[name] + 1)
            require(fingerprint(data) == {key: record[key] for key in ('bytes', 'sha256')}, 'member checksum differs')
            files[name] = data
    require(set(names) == set(DIRECTORIES) | {'PDF.app/' + name for name in FILES}
            and set(files) == set(FILES), 'archive inventory incomplete')
    require(len(raw) - cursor >= 1024 and not any(raw[cursor:]), 'tar trailer is missing or contains hidden payload')
    return files


def restore(archive, manifest_path, source, expected_hash, manifest_hash, destination, production_plist):
    manifest = manifest_at(manifest_path, source, manifest_hash)
    files = inspect_archive(archive, manifest, expected_hash)
    require(files['Contents/Info.plist'] == read_regular(production_plist, 65536), 'archived production plist differs')
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    app = destination/'PDF.app'
    for name in DIRECTORIES:
        (destination/name).mkdir(mode=0o700)
    for name, data in files.items():
        path = app/name
        with path.open('xb') as stream: stream.write(data)
        path.chmod(manifest['files'][name]['mode'])
    require(bundle_files(app, production_plist) == manifest['files'], 'restored bundle bytes differ')
    return app


def png_dimensions(raw):
    require(raw[:8] == b'\x89PNG\r\n\x1a\n', 'PNG signature differs')
    cursor = 8; seen = []; payload = bytearray(); dimensions = None; idat_ended = False
    while cursor < len(raw):
        require(cursor + 12 <= len(raw), 'truncated PNG chunk')
        length, kind = struct.unpack('>I4s', raw[cursor:cursor+8]); end = cursor + 12 + length
        require(end <= len(raw) and length <= MAX_PNG, 'invalid PNG chunk size')
        content = raw[cursor+8:end-4]
        require(zlib.crc32(kind + content) & 0xffffffff == struct.unpack('>I', raw[end-4:end])[0], 'PNG CRC differs')
        if not seen:
            require(kind == b'IHDR' and length == 13, 'PNG must begin with one IHDR')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', content)
            require(100 < width <= 8192 and 100 < height <= 8192 and width*height <= 16_777_216
                    and depth == 8 and color in (0, 2, 4, 6) and compression == filtering == interlace == 0,
                    'unsupported or excessive PNG dimensions/encoding')
            dimensions = (width, height); channels = {0:1, 2:3, 4:2, 6:4}[color]
        elif kind == b'IHDR': raise ValueError('Duplicate PNG IHDR.')
        if kind == b'IDAT':
            require(not idat_ended, 'noncontiguous PNG image chunks'); payload.extend(content)
        elif b'IDAT' in seen: idat_ended = True
        require(kind[0] & 32 or kind in (b'IHDR', b'IDAT', b'IEND', b'PLTE'), 'unknown critical PNG chunk')
        seen.append(kind); cursor = end
        if kind == b'IEND':
            require(length == 0 and cursor == len(raw) and b'IDAT' in seen, 'invalid PNG trailer'); break
    require(seen and seen[-1] == b'IEND', 'PNG end missing')
    stride = dimensions[0] * channels + 1; expected = stride * dimensions[1]
    decoder = zlib.decompressobj(); pixels = decoder.decompress(payload, expected + 1)
    require(len(pixels) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
            and all(pixels[row*stride] <= 4 for row in range(dimensions[1])), 'PNG image data is incomplete or oversized')
    return dimensions


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def rect(value):
    require(isinstance(value, dict) and set(value) == {'x', 'y', 'width', 'height'}
            and all(finite(x) for x in value.values()) and value['width'] > 0 and value['height'] > 0, 'invalid geometry')
    return value


def native_toolbar_items(value):
    observed = value.get('nativeToolbarItems')
    require(isinstance(observed, dict) and observed.get('traversalLimited') is False
            and type(observed.get('maximumItems')) is int and observed['maximumItems'] == 64
            and type(observed.get('maximumDepth')) is int and observed['maximumDepth'] == 4,
            'complete bounded public toolbar item observation required')
    items = observed.get('items')
    require(isinstance(items, list) and len(items) <= 64, 'public toolbar item inventory exceeds its bound')
    depths = []; children = [0] * len(items)
    for index, item in enumerate(items):
        require(isinstance(item, dict) and type(item.get('index')) is int and item['index'] == index
                and all(isinstance(item.get(key), str) for key in ('itemIdentifier','label','paletteLabel'))
                and type(item.get('subitemCount')) is int and 0 <= item['subitemCount'] <= 64,
                'invalid indexed public toolbar item')
        parent = item.get('parent')
        require(parent is None or type(parent) is int and 0 <= parent < index, 'toolbar item parent is invalid or cyclic')
        depths.append(0 if parent is None else depths[parent] + 1)
        require(depths[-1] <= 4, 'toolbar item group depth exceeds its bound')
        if parent is not None: children[parent] += 1
    require(all(item['subitemCount'] == children[index] for index, item in enumerate(items)), 'toolbar subitem census differs')
    return items


def toolbar_view_bindings(value, items, expected):
    providers = value.get('toolbarProviders')
    require(isinstance(providers, list) and len(providers) == 1 and isinstance(providers[0], dict),
            'one observed real toolbar hierarchy is required')
    toolbar = providers[0]; provider = toolbar.get('node')
    require(isinstance(provider, dict) and provider.get('role') == 'AXToolbar'
            and provider.get('isNSView') is True and provider.get('belongsToWindow') is True
            and provider.get('hiddenOrHasHiddenAncestor') is False
            and toolbar.get('directChildrenTruncated') is False and toolbar.get('nativeHierarchyTruncated') is False
            and type(toolbar.get('maximumNativeViews')) is int and toolbar['maximumNativeViews'] == 128
            and type(toolbar.get('maximumNativeDepth')) is int and toolbar['maximumNativeDepth'] == 12,
            'toolbar is hidden, outside the window, ambiguous or truncated')
    require(type(toolbar.get('directChildCount')) is int and 0 <= toolbar['directChildCount'] <= 128
            and isinstance(toolbar.get('directChildren'), list) and len(toolbar['directChildren']) == toolbar['directChildCount'],
            'direct toolbar provider count differs')
    nodes = toolbar.get('nativeViews')
    require(isinstance(nodes, list) and 1 <= len(nodes) <= 128, 'bounded native toolbar view tree required')
    views = {}; depths = []
    for index, node in enumerate(nodes):
        require(isinstance(node, dict) and type(node.get('index')) is int and node['index'] == index
                and isinstance(node.get('view'), dict), 'native toolbar tree index/view missing')
        parent = node.get('parent')
        require((index == 0 and parent is None) or (index > 0 and type(parent) is int and 0 <= parent < index),
                'native toolbar view is not rooted in the single actual toolbar')
        depths.append(0 if parent is None else depths[parent] + 1)
        require(depths[-1] <= 12, 'native toolbar hierarchy exceeds its depth bound')
        view = node['view']; identity = view.get('identity')
        require(isinstance(identity, str) and bool(identity.strip()) and identity not in views,
                'native toolbar view identity is missing or duplicated')
        views[identity] = (index, view)
    root_view = nodes[0]['view']
    require(root_view.get('provider') == provider and finite(root_view.get('alpha')) and root_view['alpha'] > 0,
            'native tree root differs from the visible toolbar provider')
    used_items = set()
    for control in value['controls']:
        key = control['auditKey']
        require(control.get('label') in CONTROL_LABELS[key] and control.get('paletteLabel') == control['label']
                and isinstance(control.get('identifier'), str) and bool(control['identifier'].strip())
                and isinstance(control.get('effectiveAppearance'), str) and bool(control['effectiveAppearance'].strip())
                and finite(control.get('alpha')) and control['alpha'] > 0
                and control.get('identification') == CONTROL_IDENTIFICATION,
                'control lacks exact public labels, actual itemIdentifier or visible alpha')
        matches = [item for item in items if item['label'] in CONTROL_LABELS[key] and item['paletteLabel'] == item['label']]
        require(len(matches) == 1 and matches[0]['index'] not in used_items, 'public toolbar label selection is missing or ambiguous')
        item = matches[0]; used_items.add(item['index']); view = item.get('view')
        require(item['itemIdentifier'] == control['identifier'] and item['label'] == control['label']
                and item['paletteLabel'] == control['paletteLabel'] and isinstance(view, dict)
                and view.get('identity') == control['identity'] and control['identity'] in views,
                'selected control does not identify the observed public item.view')
        node_index, tree_view = views[control['identity']]
        require(node_index > 0, 'the toolbar root cannot be substituted for an item.view')
        for observed in (view, tree_view):
            node = observed.get('provider')
            require(isinstance(node, dict) and node.get('isNSView') is True and node.get('belongsToWindow') is True
                    and node.get('hiddenOrHasHiddenAncestor') is False and finite(observed.get('alpha')) and observed['alpha'] > 0,
                    'actual item.view is hidden or belongs to another window')
            rect(observed.get('bounds')); rect(observed.get('windowFrame')); rect(observed.get('screenFrame'))
            require(all(observed.get(field) == control.get(field) for field in
                        ('identity','windowFrame','screenFrame','alpha','effectiveAppearance','effectiveStyle'))
                    and observed['effectiveStyle'] == expected,
                    'control identity, geometry, alpha or style differs from its actual item.view/tree')
        require(view.get('bounds') == tree_view.get('bounds')
                and view.get('appearanceOverride') == tree_view.get('appearanceOverride'),
                'public item.view and toolbar descendant disagree')


def snapshot(value, selection, workspace):
    require(isinstance(value, dict) and value.get('selection') == selection
            and type(value.get('windowNumber')) is int and value['windowNumber'] > 0
            and finite(value.get('uptime')) and finite(value.get('backingScale')) and value['backingScale'] > 0,
            'invalid observed toolbar window')
    rect(value['windowFrame'])
    expected = value.get('applicationEffectiveStyle') if selection == 'system' else selection
    require(expected in ('light', 'dark') and all(value.get(key) == expected for key in
            ('applicationEffectiveStyle', 'windowEffectiveStyle', 'contentEffectiveStyle')), 'observed style differs from selection')
    if selection == 'system':
        require(value.get('applicationOverride') is None and value.get('windowOverride') is None, 'system mode retained an override')
    require(type(value.get('windowToolbarPresent')) is bool and type(value.get('windowToolbarVisible')) is bool
            and type(value.get('workspaceToolbarProviderCount')) is int and value['workspaceToolbarProviderCount'] >= 0,
            'real toolbar presence was not observed')
    controls = value.get('controls')
    items = native_toolbar_items(value)
    if not workspace:
        require(controls == [] and value['workspaceToolbarProviderCount'] == 0
                and value.get('errors') == []
                and not any(item['label'] in labels for item in items for labels in CONTROL_LABELS.values()),
                'workspace toolbar absence during customization is not established')
        return value
    require(value.get('errors') == [] and value['windowToolbarPresent'] is True and value['windowToolbarVisible'] is True
            and value['workspaceToolbarProviderCount'] == 1, 'workspace toolbar is missing, ambiguous or hidden')
    require(isinstance(controls, list) and len(controls) == 3 and all(isinstance(c, dict) for c in controls)
            and [c.get('auditKey') for c in controls] == list(CONTROLS)
            and all(isinstance(c.get('identity'), str) and c['identity'].strip() for c in controls)
            and len({c['identity'] for c in controls}) == 3, 'three unique actual controls required')
    styles = value.get('toolbarEffectiveStyles')
    require(isinstance(styles, list) and 0 < len(styles) <= 100 and all(style == expected for style in styles)
            and all(c.get('effectiveStyle') == expected for c in controls), 'toolbar/control style differs from selection')
    toolbar_view_bindings(value, items, expected)
    return value


def toolbar(report, selection, width, height):
    require(isinstance(report, dict) and type(report.get('schemaVersion')) is int and report['schemaVersion'] == 1
            and report.get('scope') == 'three-own-window-toolbar-symbols-central-pixels'
            and report.get('passed') is True and report.get('errors') == []
            and report.get('universalWCAGCertification') is False and report.get('humanVisualReview') is False,
            'toolbar report failed or overclaims its scope')
    before, after = report['before'], report['after']
    for value in (before, after):
        snapshot(value, selection, True)
    require(before['uptime'] <= after['uptime'] and all(before[key] == after[key] for key in
            ('windowNumber', 'windowFrame', 'backingScale', 'controls')), 'controls/window changed during capture')
    require(all(before.get(key) == after.get(key) for key in ('applicationOverride','windowOverride',
            'applicationEffectiveAppearance','windowEffectiveAppearance','contentEffectiveAppearance','toolbarEffectiveAppearances')),
            'effective appearance changed during capture')
    scale_x, scale_y = width/before['windowFrame']['width'], height/before['windowFrame']['height']
    require(abs(scale_x-scale_y) <= 0.01 and abs(scale_x-before['backingScale']) <= 0.01, 'PNG/window scales differ')
    measurements = report.get('measurements')
    require(isinstance(measurements, list) and len(measurements) == 3
            and [m.get('auditKey') for m in measurements] == list(CONTROLS), 'three central pixel measurements required')
    for control, m in zip(before['controls'], measurements):
        central = rect(m['centralPixelBounds']); pixel = rect(m['pixelBounds'])
        local = rect(control['windowFrame']); rect(control['screenFrame'])
        require(local['x'] >= 0 and local['y'] >= 0 and local['x']+local['width'] <= before['windowFrame']['width']
                and local['y']+local['height'] <= before['windowFrame']['height'], 'control lies outside its real window')
        expected_pixel = dict(x=local['x']*scale_x, y=(before['windowFrame']['height']-local['y']-local['height'])*scale_y,
                              width=local['width']*scale_x, height=local['height']*scale_y)
        side = min(expected_pixel['width'], expected_pixel['height'])*0.60
        mid_x, mid_y = expected_pixel['x']+expected_pixel['width']/2, expected_pixel['y']+expected_pixel['height']/2
        x, y = math.ceil(mid_x-side/2), math.ceil(mid_y-side/2)
        expected_central = dict(x=x,y=y,width=math.floor(mid_x+side/2)-x,height=math.floor(mid_y+side/2)-y)
        require(all(abs(pixel[key]-expected_pixel[key]) <= 0.000001 for key in pixel)
                and central == expected_central, 'sample geometry does not identify the central 60% of the actual control')
        require(central['x'] >= 0 and central['y'] >= 0 and central['x']+central['width'] <= width
                and central['y']+central['height'] <= height and central['width'] >= 6 and central['height'] >= 6
                and all(float(v).is_integer() for v in central.values()), 'central sample outside the original PNG')
        require(type(m.get('sampleCount')) is int and m['sampleCount'] == central['width']*central['height'], 'sample count differs from bounds')
        lo, hi, contrast = m['luminanceP05'], m['luminanceP95'], m['centralContrast']
        require(all(finite(x) for x in (lo, hi, contrast, m.get('minimumContrast')))
                and 0 <= lo <= hi <= 1 and m['minimumContrast'] == 3.0 and contrast >= 3.0
                and abs(contrast - (hi+0.05)/(lo+0.05)) <= 0.000001 and m.get('passed') is True,
                'central contrast failed or contradicts luminance measurements')
        for key in ('minimumRGB', 'maximumRGB'):
            require(isinstance(m.get(key), list) and len(m[key]) == 3 and all(type(v) is int and 0 <= v <= 255 for v in m[key]), 'RGB sample bounds invalid')
        require(all(lo <= hi for lo, hi in zip(m['minimumRGB'], m['maximumRGB'])), 'RGB extrema are inverted')
    return report


def validate_report(directory):
    directory = Path(directory); raw = read_regular(directory/'PDF-appearance.appearance.json', MAX_REPORT)
    report = parse_json(raw)
    fields = {'schemaVersion','scope','source','createdAt','status','frames','checks',
              'providersRecreatedAfterCustomization','operatingSystem','nativeDeadlineSeconds','cleanupMaximumSeconds',
              'engineUsed','documentsOpened','humanVisualReview','universalWCAGCertification'}
    require(isinstance(report, dict) and set(report) in (fields, fields | {'failure'}), 'sequence report fields differ')
    require(isinstance(report, dict) and type(report.get('schemaVersion')) is int and report['schemaVersion'] == 1
            and report.get('status') == 'passed' and report.get('failure') is None
            and report.get('scope') == 'appearance-only-real-window' and report.get('source') == 'WindowServer-ScreenCaptureKit',
            'native report identity, status or capture source differs')
    for key in ('engineUsed', 'documentsOpened', 'humanVisualReview', 'universalWCAGCertification'):
        require(report.get(key) is False, 'report overclaims or exercised unrelated operations: ' + key)
    require(type(report.get('nativeDeadlineSeconds')) is int and report['nativeDeadlineSeconds'] == 70
            and type(report.get('cleanupMaximumSeconds')) is int and report['cleanupMaximumSeconds'] == 3,
            'native deadlines differ')
    require(isinstance(report.get('operatingSystem'), str) and report['operatingSystem'].strip()
            and isinstance(report.get('createdAt'), str)
            and datetime.fromisoformat(report['createdAt'].replace('Z', '+00:00')).tzinfo is not None, 'report timestamp/OS missing')
    checks = report.get('checks')
    require(isinstance(checks, list) and len(checks) == len(CHECKS)
            and all(isinstance(c,dict) and set(c) == {'id','passed'} for c in checks)
            and [c.get('id') for c in checks] == list(CHECKS) and all(c.get('passed') is True for c in checks), 'native checks incomplete or failed')
    frames = report.get('frames')
    frame_fields = {'phase','selection','png','bytes','sha256','width','height','windowSnapshot'}
    require(isinstance(frames, list) and len(frames) == 7
            and all(isinstance(f,dict) and set(f) in (frame_fields,frame_fields | {'toolbarReport'}) for f in frames)
            and [f.get('phase') for f in frames] == list(PHASES)
            and [f.get('selection') for f in frames] == list(SELECTIONS)
            and [f.get('png') for f in frames] == list(PNG_NAMES), 'frame order, selection or names differ')
    require({p.name for p in directory.glob('PDF-appearance*.png')} == set(PNG_NAMES), 'missing or extra appearance PNG')
    reports = {}; originals = {'PDF-appearance.appearance.json': fingerprint(raw)}
    for f in frames:
        image = read_regular(directory/f['png'], MAX_PNG); dimensions = png_dimensions(image)
        require(type(f.get('bytes')) is int and f['bytes'] == len(image) and f.get('sha256') == sha(image)
                and all(type(f.get(k)) is int for k in ('width','height')) and dimensions == (f['width'],f['height']), 'original PNG hash, size or dimensions differ')
        originals[f['png']] = fingerprint(image)
        observed = snapshot(f.get('windowSnapshot'), f['selection'], f['phase'] != 'customization')
        require(abs(observed['windowFrame']['width']*observed['backingScale']-f['width']) < 0.01
                and abs(observed['windowFrame']['height']*observed['backingScale']-f['height']) < 0.01,
                'original PNG differs from the observed window geometry/backing scale')
        if f['phase'] == 'customization':
            require(f.get('toolbarReport') is None, 'customization is not a workspace toolbar frame')
        else:
            reports[f['phase']] = toolbar(f.get('toolbarReport'), f['selection'], *dimensions)
            require(f['windowSnapshot'] == f['toolbarReport']['after'], 'frame snapshot differs from the actual post-capture observation')
    numbers = {s['windowNumber'] for r in reports.values() for s in (r['before'],r['after'])}
    numbers.update(f['windowSnapshot']['windowNumber'] for f in frames)
    require(len(numbers) == 1, 'sequence did not use the same real window')
    identities = lambda phase: {c['auditKey']:c['identity'] for c in reports[phase]['before']['controls']}
    require(identities('light-initial') == identities('dark-attached-1') == identities('dark-attached-2'), 'attached controls were replaced')
    recreated = all(identities('dark-recreated')[key] != identities('light-initial')[key] for key in CONTROLS)
    require(type(report.get('providersRecreatedAfterCustomization')) is bool
            and report['providersRecreatedAfterCustomization'] == recreated, 'provider reuse observation contradicts the original tokens')
    require(reports['dark-attached-1']['after']['uptime'] < reports['dark-attached-2']['before']['uptime'], 'dark frames were not separate captures')
    require(all(reports['system'][when].get(key) is None for when in ('before','after') for key in ('applicationOverride','windowOverride')), 'system mode retained an override')
    return report, originals


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    for command in ('pack','restore','check'):
        p = sub.add_parser(command); p.add_argument('--source-commit', required=True)
        p.add_argument('--production-plist', required=True, type=Path)
        if command == 'pack':
            p.add_argument('--app', required=True, type=Path); p.add_argument('--sdk', required=True)
            p.add_argument('--output', required=True, type=Path)
        else:
            p.add_argument('--manifest', required=True, type=Path); p.add_argument('--manifest-sha256', required=True)
            if command == 'restore':
                p.add_argument('--archive', required=True, type=Path); p.add_argument('--archive-sha256', required=True)
                p.add_argument('--destination', required=True, type=Path)
            else:
                p.add_argument('--app', required=True, type=Path); p.add_argument('--directory', required=True, type=Path)
                p.add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'pack':
        result = pack(args.app, args.production_plist, args.source_commit, args.sdk, args.output)
    elif args.command == 'restore':
        result = {'app': str(restore(args.archive,args.manifest,args.source_commit,args.archive_sha256,args.manifest_sha256,args.destination,args.production_plist)), 'recompiled':False,'resigned':False}
    else:
        result = {'schemaVersion':1,'scope':'minimal-appearance-diagnostic-only','sourceCommit':args.source_commit,
                  'sourceCommitAuthenticatedByThisHelper':False,'status':'failed','completeApplicationApproved':False,
                  'humanVisualReview':False,'universalWCAGCertification':False,'engineRuntimeInstalled':False,
                  'externalDeadlineSeconds':90}
        try:
            manifest = manifest_at(args.manifest,args.source_commit,args.manifest_sha256)
            require(bundle_files(args.app,args.production_plist) == manifest['files'], 'bundle changed after capture')
            report, originals = validate_report(args.directory)
            result.update(status='passed',originals=originals,unchangedBundleFiles=manifest['files'],
                          archive=manifest['tar'],operatingSystem=report['operatingSystem'],nativeChecksPassed=len(CHECKS))
        except (ValueError,OSError,KeyError,TypeError,OverflowError,zlib.error) as error:
            result['error'] = str(error)[:2048]; write_json(args.receipt,result); raise
        write_json(args.receipt,result)
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
