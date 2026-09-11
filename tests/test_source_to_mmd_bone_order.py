"""Bone reordering must preserve every bone-index-bearing PMX section."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import types
import unittest

path=Path(__file__).resolve().parents[1]/"tools/source_to_mmd/pmx_bone_order.py"
spec=importlib.util.spec_from_file_location("bone_order_under_test",path)
order=importlib.util.module_from_spec(spec)
spec.loader.exec_module(order)
NS=types.SimpleNamespace


def bone(name,parent,**kwargs):
    values=dict(name=name,parent=parent,displayConnection=-1,additionalTransform=None,
                target=None,ik_links=[],transform_order=0,axis=None,isIK=False,
                localCoordinate=None,transAfterPhis=False,externalTransKey=None)
    values.update(kwargs)
    return NS(**values)


class BoneOrderTests(unittest.TestCase):
    def fixture(self):
        return NS(bones=[bone("root",-1),bone("child",3,displayConnection=2,
            additionalTransform=(0,.5),isIK=True,target=2,ik_links=[NS(target=3)],
            axis=[1,0,0],transform_order=2,externalTransKey=3),
            bone("target",3,displayConnection=[.1,.2,.3]),bone("parent",0)],
            vertices=[NS(weight=NS(bones=[1,2,3,-1],weights=[.2,.3,.5,0],type=2))],
            morphs=[NS(name="bone morph",type_index=lambda:2,offsets=[NS(index=1,location_offset=[1,2,3])]),
                    NS(name="vertex morph",type_index=lambda:1,offsets=[NS(index=1)])],
            display=[NS(name="bones and morph",data=[(0,1),(1,1),(0,-1)])],
            rigids=[NS(bone=2),NS(bone=None)],joints=[NS(src_rigid=1,dest_rigid=0)])

    def test_all_references_follow_bones_without_changing_other_values(self):
        model=self.fixture()
        result=order.reorder_bones_parent_first(model)
        self.assertGreater(result["moved_bones"],0)
        self.assertEqual([b.name for b in model.bones],["root","parent","child","target"])
        child=model.bones[2]
        self.assertEqual(child.parent,1)
        self.assertEqual(child.displayConnection,3)
        self.assertEqual(child.additionalTransform,(0,.5))
        self.assertEqual(child.target,3)
        self.assertEqual(child.ik_links[0].target,1)
        self.assertEqual(child.axis,[1,0,0])
        self.assertEqual(child.transform_order,2)
        self.assertEqual(child.externalTransKey,3,"External key is not a bone index")
        self.assertEqual(model.vertices[0].weight.bones,[2,3,1,-1])
        self.assertEqual(model.vertices[0].weight.weights,[.2,.3,.5,0])
        self.assertEqual(model.morphs[0].offsets[0].index,2)
        self.assertEqual(model.morphs[1].offsets[0].index,1,"Vertex index must not change")
        self.assertEqual(model.display[0].data,[(0,2),(1,1),(0,-1)])
        self.assertEqual(model.rigids[0].bone,3)
        self.assertIsNone(model.rigids[1].bone)
        self.assertEqual(model.joints[0].src_rigid,1)
        self.assertEqual(model.joints[0].dest_rigid,0)
        self.assertEqual(model.bones[3].displayConnection,[.1,.2,.3])

    def test_operation_is_idempotent(self):
        model=self.fixture()
        order.reorder_bones_parent_first(model)
        before=deepcopy(model.bones)
        result=order.reorder_bones_parent_first(model)
        self.assertEqual(result["moved_bones"],0)
        self.assertEqual(model.bones,before)

    def test_invalid_reference_fails_without_partial_mutation(self):
        model=self.fixture()
        model.rigids[0].bone=99
        before=deepcopy(model.bones)
        with self.assertRaisesRegex(ValueError,"rigid body"):
            order.reorder_bones_parent_first(model)
        self.assertEqual(model.bones,before)
        self.assertEqual(model.vertices[0].weight.bones,[1,2,3,-1])

    def test_cycle_fails_without_partial_mutation(self):
        model=self.fixture()
        model.bones[0].parent=1
        before=deepcopy(model.bones)
        with self.assertRaisesRegex(ValueError,"cycle"):
            order.reorder_bones_parent_first(model)
        self.assertEqual(model.bones,before)


if __name__=="__main__":unittest.main()
