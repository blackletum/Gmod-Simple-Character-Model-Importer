"""Input-planning regressions; no Blender, game install or Valve assets required."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from source_to_mmd import decompile_and_extract as source
from source_to_mmd_core import validate_selection

class SourcePlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        for name in ['body','hat','hair','body_lod','physics']:
            (self.root/(name+'.smd')).write_text('version 1\ntriangles\nskin\n0\n0\n0\nend\n')
    def tearDown(self):self.temp.cleanup()

    def test_qc_keeps_required_body_and_one_bodygroup_variant(self):
        plan=source.qc_parts('''$modelname "npc/test.mdl"
$model "character" "body.smd" { flexfile "face.vta" { flex "blink" frame 1 } }
$bodygroup "headwear" { studio "hat" studio "hair.smd" blank }
$lod 10 { replacemodel "body.smd" "body_lod.smd" }
$collisionmodel "physics.smd" {}
''',self.root)
        self.assertEqual(plan['mandatory_meshes'],['body'])
        self.assertEqual(plan['default_meshes'],['body','hat'])
        self.assertEqual(set(plan['mesh_names']),{'body','hat','hair'})
        self.assertEqual(validate_selection(plan,['body','hair']),['body','hair'])
        self.assertEqual(validate_selection(plan,['body']),['body'])
        for selected in [['hat'],['body','hat','hair'],['body','physics']]:
            with self.assertRaises(ValueError):validate_selection(plan,selected)

    def test_animation_or_unknown_qc_never_falls_back_to_largest_smd(self):
        with self.assertRaisesRegex(source.PipelineError,'no render meshes'):
            source.qc_parts('$modelname "animations.mdl"\n$sequence idle "body.smd"',self.root)

    def test_nested_reference_path_is_preserved(self):
        (self.root/'meshes').mkdir()
        (self.root/'meshes/body.smd').write_text('version 1')
        plan=source.qc_parts('$body "body" "meshes/body.smd"',self.root)
        self.assertEqual(Path(plan['mesh_sources']['body']),self.root/'meshes/body.smd')
        with self.assertRaisesRegex(source.PipelineError,'same name'):
            source.qc_parts('$body first "meshes/body.smd"\n$body second "body.smd"',self.root)

    def test_patch_material_inherits_texture_and_overrides_transparency(self):
        (self.root/'base.vmt').write_text('VertexLitGeneric { "$basetexture" "models/a/skin" "$translucent" "0" }')
        (self.root/'patch.vmt').write_text('Patch { include "base.vmt" replace { "$translucent" "1" "$alpha" 0.5 } }')
        shader,params=source.read_vmt(self.root/'patch.vmt',self.root)
        self.assertEqual(shader,'vertexlitgeneric')
        self.assertEqual(params,{'$basetexture':'models/a/skin','$translucent':'1','$alpha':'0.5'})

    def test_include_cycles_and_resource_escape_are_rejected(self):
        (self.root/'a.vmt').write_text('Patch { include "b.vmt" }')
        (self.root/'b.vmt').write_text('Patch { include "a.vmt" }')
        with self.assertRaisesRegex(source.PipelineError,'Cyclic'):
            source.read_vmt(self.root/'a.vmt',self.root)
        with self.assertRaisesRegex(source.PipelineError,'escapes'):
            source.inside(self.root,'../outside.vtf')

    def test_qc_eye_metadata_is_read_as_numbers(self):
        eyes=source.parse_eyes('eyeball "eye_left" "Head" 1.3 -2.9 65.2 "eyeball_l" 1 -4 "iris_unused" 0.682')
        self.assertEqual(eyes[0]['material'],'eyeball_l')
        self.assertAlmostEqual(eyes[0]['iris_scale'],0.682)
        self.assertEqual(eyes[0]['origin_source'],[1.3,-2.9,65.2])

if __name__=='__main__':unittest.main()
