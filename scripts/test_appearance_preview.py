"""Offline negative controls for the small appearance-only evidence contract."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import plistlib
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zlib

import check_appearance_preview as check

SOURCE = 'a' * 40


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def png(width=256, height=256):
    row = b'\x00' + (b'\x00\x00\x00\xff' * (width//2)) + (b'\xff\xff\xff\xff' * (width-width//2))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(row*height)) + chunk(b'IEND', b'')


def box(x, y, width, height):
    return dict(x=x,y=y,width=width,height=height)


def bind_native_metadata(value):
    def provider(role, identifier=None):
        return dict(nativeClass='NSViewFixture',role=role,identifier=identifier,label='Observed provider',
                    isNSView=True,belongsToWindow=True,hiddenOrHasHiddenAncestor=False)
    toolbar_node=provider('AXToolbar')
    root_view=dict(provider=toolbar_node,identity='toolbar-root',bounds=box(0,0,256,66),windowFrame=box(0,190,256,66),
                   screenFrame=box(0,190,256,66),alpha=1,effectiveAppearance=value['windowEffectiveAppearance'],
                   effectiveStyle=value['windowEffectiveStyle'])
    nodes=[dict(index=0,view=root_view)];items=[]
    for index,control in enumerate(value['controls']):
        view=dict(provider=provider('AXButton',control['auditKey']),identity=control['identity'],bounds=box(0,0,40,40),
                  windowFrame=copy.deepcopy(control['windowFrame']),screenFrame=copy.deepcopy(control['screenFrame']),
                  alpha=control['alpha'],effectiveAppearance=control['effectiveAppearance'],effectiveStyle=control['effectiveStyle'])
        nodes.append(dict(index=index+1,parent=0,view=copy.deepcopy(view)))
        items.append(dict(index=index,nativeClass='NSToolbarItem',itemIdentifier=control['identifier'],label=control['label'],
                          paletteLabel=control['paletteLabel'],view=view,subitemCount=0))
    value['nativeToolbarItems']=dict(items=items,traversalLimited=False,maximumItems=64,maximumDepth=4)
    value['toolbarProviders']=[dict(node=toolbar_node,directChildCount=0,directChildren=[],directChildrenTruncated=False,
                                    nativeViews=nodes,nativeHierarchyTruncated=False,maximumNativeViews=128,maximumNativeDepth=12)] if items else []


def snapshot(selection, tick, recreated=False, customization=False):
    controls = []
    for index,key in enumerate(check.CONTROLS):
        label=('Hide Sidebar','Comandos','Personalizar')[index]
        controls.append(dict(auditKey=key,identifier='actual-item-'+key,label=label,paletteLabel=label,alpha=1,
                             identity=('new-' if recreated else 'first-')+key,
                             windowFrame=box(20+index*60,200,40,40),screenFrame=box(20+index*60,200,40,40),
                             effectiveAppearance='NSAppearanceNameDarkAqua' if selection=='dark' else 'NSAppearanceNameAqua',
                             identification=check.CONTROL_IDENTIFICATION,effectiveStyle='dark' if selection=='dark' else 'light'))
    value=dict(uptime=tick,windowNumber=55,windowFrame=box(0,0,256,256),backingScale=1,selection=selection,
               applicationEffectiveAppearance='NSAppearanceNameDarkAqua' if selection=='dark' else 'NSAppearanceNameAqua',
               windowEffectiveAppearance='NSAppearanceNameDarkAqua' if selection=='dark' else 'NSAppearanceNameAqua',
               contentEffectiveAppearance='NSAppearanceNameDarkAqua' if selection=='dark' else 'NSAppearanceNameAqua',
               toolbarEffectiveAppearances=['NSAppearanceNameDarkAqua' if selection=='dark' else 'NSAppearanceNameAqua'],
               toolbarItemIdentifiers=['commands','customize'],controls=[] if customization else controls,errors=[],
               applicationEffectiveStyle='dark' if selection=='dark' else 'light',windowEffectiveStyle='dark' if selection=='dark' else 'light',
               contentEffectiveStyle='dark' if selection=='dark' else 'light',toolbarEffectiveStyles=['dark' if selection=='dark' else 'light'])
    value.update(windowToolbarPresent=not customization,windowToolbarVisible=not customization,workspaceToolbarProviderCount=0 if customization else 1)
    if selection!='system':
        value.update(applicationOverride=value['applicationEffectiveAppearance'],windowOverride=value['windowEffectiveAppearance'])
    bind_native_metadata(value)
    return value


def report_fixture(directory):
    image=png(); frames=[]
    for index,(phase,selection,name) in enumerate(zip(check.PHASES,check.SELECTIONS,check.PNG_NAMES)):
        (directory/name).write_bytes(image)
        before=snapshot(selection,index*2+1,recreated=index>=4,customization=phase=='customization')
        f=dict(phase=phase,selection=selection,png=name,bytes=len(image),sha256=check.sha(image),width=256,height=256,windowSnapshot=copy.deepcopy(before))
        if phase!='customization':
            measurements=[]
            for offset,key in enumerate(check.CONTROLS):
                measurements.append(dict(auditKey=key,pixelBounds=box(20+offset*60,16,40,40),centralPixelBounds=box(28+offset*60,24,24,24),
                    sampleCount=576,minimumRGB=[0,0,0],maximumRGB=[255,255,255],luminanceP05=0,luminanceP95=1,
                    centralContrast=21,minimumContrast=3.0,passed=True))
            after=copy.deepcopy(before);after['uptime']+=0.5
            f['windowSnapshot']=copy.deepcopy(after)
            f['toolbarReport']=dict(schemaVersion=1,scope='three-own-window-toolbar-symbols-central-pixels',before=before,after=after,
                measurements=measurements,errors=[],passed=True,universalWCAGCertification=False,humanVisualReview=False,methodology='synthetic report-consistency fixture; not native pixel measurement')
        frames.append(f)
    return dict(schemaVersion=1,scope='appearance-only-real-window',source='WindowServer-ScreenCaptureKit',createdAt='2026-10-26T00:00:00Z',status='passed',
        frames=frames,checks=[dict(id=name,passed=True) for name in check.CHECKS],operatingSystem='fixture macOS',nativeDeadlineSeconds=70,cleanupMaximumSeconds=3,
        engineUsed=False,documentsOpened=False,humanVisualReview=False,universalWCAGCertification=False,providersRecreatedAfterCustomization=True)


class AppearanceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.app=self.root/'original/PDF.app'
        for path in ('Contents/MacOS','Contents/Resources','Contents/_CodeSignature'):
            (self.app/path).mkdir(parents=True,exist_ok=True)
        self.plist=self.root/'production.plist'
        self.plist.write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.pdf.desktop','CFBundleExecutable':'PDF'}))
        inputs={'Contents/MacOS/PDF':b'fixture executable, never run','Contents/Info.plist':self.plist.read_bytes(),
                'Contents/Resources/installation.lock':b'','Contents/_CodeSignature/CodeResources':b'fixture signature, not signing validation'}
        for name,data in inputs.items():
            p=self.app/name;p.write_bytes(data);p.chmod(0o755 if name.endswith('/PDF') else (0o444 if name.endswith('.lock') else 0o644))
        self.transfer=self.root/'transfer'
        self.manifest=check.pack(self.app,self.plist,SOURCE,'26.0',self.transfer)
        self.archive=self.transfer/'PDF-appearance-bundle.tar.gz'
        self.manifest_path=self.transfer/'appearance-bundle.json'
        self.output=self.root/'frames';self.output.mkdir()
        self.report=report_fixture(self.output)

    def save_report(self):
        (self.output/'PDF-appearance.appearance.json').write_text(json.dumps(self.report))

    def validate(self):
        self.save_report();return check.validate_report(self.output)

    def frame_snapshots(self,index=0):
        frame=self.report['frames'][index]
        return (frame['windowSnapshot'],frame['toolbarReport']['before'],frame['toolbarReport']['after'])

    def altered_tar(self, mutate):
        raw=gzip.decompress(self.archive.read_bytes());members=[]
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as tar:
            for item in tar:
                members.append((copy.copy(item),tar.extractfile(item).read() if item.isreg() else None))
        mutate(members)
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w',format=tarfile.USTAR_FORMAT) as tar:
            for item,data in members:tar.addfile(item,io.BytesIO(data) if data is not None else None)
        self.archive.write_bytes(gzip.compress(out.getvalue(),mtime=0))
        self.manifest['tar']=check.fingerprint(self.archive.read_bytes())

    def inspect(self):
        return check.inspect_archive(self.archive,self.manifest,self.manifest['tar']['sha256'])

    def test_same_bundle_roundtrip_and_all_original_frames(self):
        destination=self.root/'restored'
        restored=check.restore(self.archive,self.manifest_path,SOURCE,self.manifest['tar']['sha256'],check.sha(self.manifest_path.read_bytes()),destination,self.plist)
        self.assertEqual(check.bundle_files(restored,self.plist),self.manifest['files'])
        _,files=self.validate();self.assertEqual(len(files),8)

    def test_wrong_archive_hash_refuses_before_destination_creation(self):
        destination=self.root/'must-not-exist'
        with self.assertRaises(ValueError):
            check.restore(self.archive,self.manifest_path,SOURCE,'b'*64,check.sha(self.manifest_path.read_bytes()),destination,self.plist)
        self.assertFalse(destination.exists())

    def test_wrong_manifest_hash_and_source_refused(self):
        for source,digest in ((SOURCE,'c'*64),('d'*40,check.sha(self.manifest_path.read_bytes()))):
            with self.subTest(source=source),self.assertRaises(ValueError):check.manifest_at(self.manifest_path,source,digest)

    def test_tar_traversal_and_absolute_path_refused(self):
        for name in ('PDF.app/../../escape','/tmp/escape'):
            with self.subTest(name=name):
                self.altered_tar(lambda members:setattr(members[-1][0],'name',name))
                with self.assertRaises(ValueError):self.inspect()

    def test_tar_symlink_and_hardlink_refused(self):
        for kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):
            def mutation(members):
                item,data=members[-1];item.type=kind;item.linkname='../../outside';item.size=0;members[-1]=(item,None)
            self.altered_tar(mutation)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.inspect()

    def test_tar_duplicate_and_missing_member_refused(self):
        self.altered_tar(lambda members:members.append(members[-1]))
        with self.assertRaises(ValueError):self.inspect()
        self.altered_tar(lambda members:members.pop())
        self.altered_tar(lambda members:members.pop())
        with self.assertRaises(ValueError):self.inspect()

    def test_tar_hidden_trailer_and_concatenated_gzip_refused(self):
        original=self.archive.read_bytes()
        for value in (gzip.compress(gzip.decompress(original)+b'payload'+bytes(505)),original+gzip.compress(b'other'),original+b'junk'):
            self.archive.write_bytes(value);self.manifest['tar']=check.fingerprint(value)
            with self.subTest(length=len(value)),self.assertRaises(ValueError):self.inspect()

    def test_decompression_bound_refuses_bomb(self):
        value=gzip.compress(bytes(100_000));self.archive.write_bytes(value);self.manifest['tar']=check.fingerprint(value)
        with patch.object(check,'MAX_TAR',4096),self.assertRaises(ValueError):self.inspect()

    def test_bundle_runtime_extra_link_and_changed_plist_refused(self):
        extra=self.app/'Contents/Resources/engine.py';extra.write_text('not allowed')
        with self.assertRaises(ValueError):check.bundle_files(self.app,self.plist)
        extra.unlink();extra.symlink_to(self.plist)
        with self.assertRaises(ValueError):check.bundle_files(self.app,self.plist)
        extra.unlink();self.plist.write_bytes(self.plist.read_bytes()+b'\n')
        with self.assertRaises(ValueError):check.bundle_files(self.app,self.plist)

    def test_report_failed_cannot_be_promoted_by_passed_checks(self):
        self.report.update(status='failed',failure='observed low contrast')
        with self.assertRaises(ValueError):self.validate()

    def test_missing_duplicate_and_extra_png_refused(self):
        p=self.output/check.PNG_NAMES[2];original=p.read_bytes();p.unlink()
        with self.assertRaises((ValueError,OSError)):self.validate()
        p.write_bytes(original);self.report['frames'][2]['png']=check.PNG_NAMES[1]
        with self.assertRaises(ValueError):self.validate()
        self.report['frames'][2]['png']=check.PNG_NAMES[2];(self.output/'PDF-appearance.extra.png').write_bytes(original)
        with self.assertRaises(ValueError):self.validate()

    def test_png_hash_dimensions_crc_and_trailing_data_refused(self):
        self.report['frames'][0]['sha256']='0'*64
        with self.assertRaises(ValueError):self.validate()
        self.report['frames'][0]['sha256']=check.sha(png());self.report['frames'][0]['width']=255
        with self.assertRaises(ValueError):self.validate()
        broken=bytearray(png());broken[-1]^=1
        for data in (bytes(broken),png()+b'junk'):
            with self.subTest(length=len(data)),self.assertRaises(ValueError):check.png_dimensions(data)

    def test_scope_overclaims_and_missing_check_refused(self):
        for key in ('engineUsed','documentsOpened','humanVisualReview','universalWCAGCertification'):
            self.report[key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate()
            self.report[key]=False
        self.report['checks'][-1]=self.report['checks'][0]
        with self.assertRaises(ValueError):self.validate()

    def test_contrast_false_pass_and_inconsistent_sample_count_refused(self):
        m=self.report['frames'][0]['toolbarReport']['measurements'][0]
        m['centralContrast']=1.0
        with self.assertRaises(ValueError):self.validate()
        m['centralContrast']=21;m['sampleCount']=1
        with self.assertRaises(ValueError):self.validate()

    def test_capture_identity_change_and_system_override_refused(self):
        before=self.report['frames'][1]['toolbarReport']['before'];before['controls'][0]['identity']='different'
        with self.assertRaises(ValueError):self.validate()
        self.report=report_fixture(self.output)
        self.report['frames'][-1]['toolbarReport']['after']['applicationOverride']='NSAppearanceNameDarkAqua'
        with self.assertRaises(ValueError):self.validate()

    def test_duplicate_json_keys_and_nonfinite_refused(self):
        for value in ('{"schemaVersion":1,"schemaVersion":1}','{"value":NaN}','{"value":Infinity}'):
            with self.subTest(value=value),self.assertRaises(ValueError):check.parse_json(value)

    def test_region_elsewhere_in_png_is_not_a_toolbar_measurement(self):
        m=self.report['frames'][0]['toolbarReport']['measurements'][0]
        m['centralPixelBounds']['x']+=1
        with self.assertRaises(ValueError):self.validate()
        m['centralPixelBounds']['x']-=1;m['pixelBounds']['y']+=10
        with self.assertRaises(ValueError):self.validate()

    def test_requested_theme_and_customization_snapshot_are_real(self):
        self.report['frames'][1]['toolbarReport']['before']['windowEffectiveStyle']='light'
        with self.assertRaises(ValueError):self.validate()
        self.report=report_fixture(self.output)
        self.report['frames'][3]['windowSnapshot']['workspaceToolbarProviderCount']=1
        with self.assertRaises(ValueError):self.validate()

    def test_provider_reuse_is_allowed_but_observation_must_match(self):
        f=self.report['frames'][4]
        for value in (f['windowSnapshot'],f['toolbarReport']['before'],f['toolbarReport']['after']):
            for c in value['controls']:c['identity']='first-'+c['auditKey']
            bind_native_metadata(value)
        self.report['providersRecreatedAfterCustomization']=False
        self.validate()
        self.report['providersRecreatedAfterCustomization']=True
        with self.assertRaises(ValueError):self.validate()

    def test_customization_geometry_and_observation_error_refused(self):
        observed=self.report['frames'][3]['windowSnapshot']
        for width in (128,255.5):
            observed['windowFrame']['width']=width
            with self.subTest(width=width),self.assertRaises(ValueError):self.validate()
        observed['windowFrame']['width']=256;observed['errors']=['public provider traversal failed']
        with self.assertRaises(ValueError):self.validate()

    def test_unrecognized_report_field_and_boolean_schema_refused(self):
        self.report['completeApplicationApproved']=True
        with self.assertRaises(ValueError):self.validate()
        self.report.pop('completeApplicationApproved');self.report['schemaVersion']=True
        with self.assertRaises(ValueError):self.validate()

    def test_exact_public_labels_palette_identifier_and_method_required(self):
        for field,value in (('label','Unrelated'),('paletteLabel','Different'),('identifier','unobserved-item'),
                            ('identification','private-class-or-position'),('alpha',0),('effectiveAppearance','')):
            self.report=report_fixture(self.output)
            for observed in self.frame_snapshots():observed['controls'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate()
        self.report=report_fixture(self.output)
        for observed in self.frame_snapshots():
            observed['controls'][0].update(label='Show Sidebar',paletteLabel='Show Sidebar')
        with self.assertRaises(ValueError):self.validate()

    def test_control_must_match_public_item_view_geometry_style_and_alpha(self):
        for field,value in (('identity','unobserved-view'),('windowFrame',box(21,200,40,40)),
                            ('screenFrame',box(20,201,40,40)),('effectiveStyle','dark'),('alpha',0.5)):
            self.report=report_fixture(self.output)
            for observed in self.frame_snapshots():observed['nativeToolbarItems']['items'][0]['view'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate()

    def test_selected_item_view_must_be_descendant_of_its_visible_same_window_toolbar(self):
        for change in ('missing-view','other-window','hidden','duplicate-identity','root-substitution'):
            self.report=report_fixture(self.output)
            for observed in self.frame_snapshots():
                tree=observed['toolbarProviders'][0]['nativeViews']
                if change=='missing-view':tree.pop()
                elif change=='other-window':tree[1]['view']['provider']['belongsToWindow']=False
                elif change=='hidden':tree[1]['view']['provider']['hiddenOrHasHiddenAncestor']=True
                elif change=='duplicate-identity':tree[2]['view']['identity']=tree[1]['view']['identity']
                else:tree[0]['view']['identity']=tree[1]['view']['identity'];tree[1]['view']['identity']='unselected'
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate()

    def test_public_label_match_cannot_be_missing_or_ambiguous(self):
        for change in ('duplicate-label','missing-view','missing-metadata'):
            self.report=report_fixture(self.output)
            for observed in self.frame_snapshots():
                if change=='missing-metadata':observed.pop('nativeToolbarItems');continue
                items=observed['nativeToolbarItems']['items']
                if change=='missing-view':items[0].pop('view')
                else:
                    extra=copy.deepcopy(items[0]);extra['index']=len(items);items.append(extra)
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate()

    def test_incomplete_or_cyclic_item_and_native_tree_observations_refused(self):
        for change in ('item-truncation','tree-truncation','item-cycle','tree-cycle','no-toolbar','missing-tree'):
            self.report=report_fixture(self.output)
            for observed in self.frame_snapshots():
                items=observed['nativeToolbarItems'];toolbar=observed['toolbarProviders'][0]
                if change=='item-truncation':items['traversalLimited']=True
                elif change=='tree-truncation':toolbar['nativeHierarchyTruncated']=True
                elif change=='item-cycle':items['items'][1]['parent']=1
                elif change=='tree-cycle':toolbar['nativeViews'][1]['parent']=1
                elif change=='no-toolbar':observed['toolbarProviders']=[]
                else:toolbar.pop('nativeViews')
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate()

    def test_customization_cannot_hide_recorded_workspace_toolbar_items(self):
        observed=self.report['frames'][3]['windowSnapshot']
        observed['nativeToolbarItems']=copy.deepcopy(self.report['frames'][0]['windowSnapshot']['nativeToolbarItems'])
        with self.assertRaises(ValueError):self.validate()

    def test_unique_logical_keys_and_absolute_three_to_one_minimum_remain_mandatory(self):
        for observed in self.frame_snapshots():observed['controls'][1]['auditKey']=observed['controls'][0]['auditKey']
        with self.assertRaises(ValueError):self.validate()
        self.report=report_fixture(self.output)
        measurement=self.report['frames'][0]['toolbarReport']['measurements'][0]
        measurement.update(luminanceP05=0,luminanceP95=0.0995,centralContrast=2.99,passed=True)
        with self.assertRaises(ValueError):self.validate()


if __name__=='__main__':unittest.main()
