"""Regression checks for Source mouth targets, without Blender or model assets."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/source_to_mmd'))
from morph_recipes import default_recipes, open_jaw_actions, source_phoneme_actions


class MouthRecipeTests(unittest.TestCase):
    def test_standard_nikori_does_not_drive_mouth_smile(self):
        recipes = default_recipes({'AU1', 'AU12'})
        self.assertEqual(recipes['にこり']['category'], 'eyebrow')
        self.assertNotIn('AU12', recipes['にこり']['weights'])
        self.assertIn('AU1', recipes['にこり']['weights'])
        self.assertEqual(recipes['口の微笑み']['category'], 'mouth')
        self.assertIn('AU12', recipes['口の微笑み']['weights'])

    def test_source_controllers_attenuate_competing_lip_actions(self):
        names = {'AU25', 'AU18', 'AU22', 'AU26', 'AU27'}
        actions = source_phoneme_actions(names, jaw=1, mouth_drop=1, part=1, pucker=1, funnel=1)
        # Independently evaluating the authored QC equations yields these
        # suppressed values, rather than three fully stacked lip shapes.
        self.assertAlmostEqual(actions['AU25'], 5/12)
        self.assertAlmostEqual(actions['AU18'], 5/12)
        self.assertAlmostEqual(actions['AU22'], 1/3)
        self.assertAlmostEqual(actions['AU27'], .4)
        self.assertAlmostEqual(actions['AU26'], .6)

    def test_symmetric_controller_jaw_stays_inside_authored_range(self):
        names = {'AU25', 'AU18', 'AU22', 'AU22Z', 'AU26', 'AU26Z', 'AU27', 'AU27Z', 'AU20'}
        for jaw in (0, .5, 1, 1.5, 2):
            actions = source_phoneme_actions(names, jaw=jaw, mouth_drop=1, part=.6)
            self.assertAlmostEqual(sum(v for k,v in actions.items() if k.startswith(('AU26','AU27'))), min(jaw,1))
            self.assertTrue(all(0 <= value <= 1 for value in actions.values()))

    def test_neutral_controllers_do_not_move_the_face(self):
        names = {'AU25', 'AU18', 'AU22', 'AU26', 'AU27'}
        self.assertEqual(source_phoneme_actions(names), {})

    def test_funnel_full_range_is_a_replacement_target(self):
        names = {'AU22', 'AU22Z'}
        self.assertEqual(source_phoneme_actions(names, funnel=2), {'AU22Z': 1})

    def test_blink_matches_source_upper_lid_rule(self):
        recipes = default_recipes({'upper_left','upper_right','lower_left','lower_right'})
        self.assertEqual(recipes['まばたき']['weights'], {'upper_right':1,'upper_left':1})
        self.assertEqual(recipes['ウィンク']['weights'], {'upper_left':1})
        self.assertEqual(recipes['ウィンク右']['weights'], {'upper_right':1})

    def test_open_target_is_used_instead_of_closed_lip_jaw(self):
        # Upper lip/lower lip/chin vertical displacements. Source AU26 moves
        # the jaw but not the aperture; AU27 includes lower-lip separation.
        source = {'AU26': (-.2, -.2, -.5), 'AU27': (0, -.6, -.5),
                  'AU27Z': (0, -.9, -.7), 'AU25': (.03, -.03, 0)}
        before = dict(source)
        recipe = default_recipes(source)['あ']['weights']
        result = [sum(source[k][i]*weight for k, weight in recipe.items()) for i in range(3)]
        self.assertGreater(result[0]-result[1], .65)
        self.assertLess(result[2], 0)
        self.assertEqual(source, before)

    def test_full_range_target_crossfades_instead_of_double_jaw(self):
        names = {'AU27', 'AU27Z'}
        for amount in (1, 1.25, 1.5, 1.75, 2):
            weights = open_jaw_actions(names, amount)
            self.assertAlmostEqual(sum(weights.values()), 1)
            self.assertTrue(all(0 <= value <= 1 for value in weights.values()))
        self.assertEqual(open_jaw_actions(names, 2), {'AU27Z': 1})

    def test_no_extrapolation_without_full_range_shape(self):
        self.assertEqual(open_jaw_actions({'AU27'}, 2), {'AU27': 1})
        self.assertEqual(open_jaw_actions({'AU26', 'AU26Z'}, 2), {'AU26Z': 1})
        self.assertIsNone(open_jaw_actions({'AU25'}, 1))

    def test_split_flex_pairs_get_symmetric_weights(self):
        names = {name+side for name in ('AU27', 'AU27Z', 'AU25', 'AU20', 'AU18', 'AU22') for side in ('R', 'L')}
        recipes = default_recipes(names)
        self.assertTrue(set('あいうえお').issubset(recipes))
        for name in 'あいうえお':
            weights = recipes[name]['weights']
            for source, value in weights.items():
                if source.endswith('R'):
                    self.assertEqual(weights[source[:-1]+'L'], value)

    def test_mmd_half_weight_is_a_partial_opening(self):
        # These recipes become ordinary PMX vertex offsets, so a half-weight
        # lip-sync key must interpolate the same anatomical opening.
        source = {'AU27': (0, -.6), 'AU27Z': (0, -.9), 'AU25': (.03, -.03)}
        weights = default_recipes(source)['あ']['weights']
        endpoint = sum((source[k][0]-source[k][1])*v for k, v in weights.items())
        apertures = [endpoint*weight for weight in (0, .5, 1)]
        self.assertEqual(apertures[0], 0)
        self.assertGreater(apertures[1], 0)
        self.assertLess(apertures[1], apertures[2])

    def test_invalid_controller_values_are_rejected(self):
        for value in (-.1, 2.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                open_jaw_actions({'AU27'}, value)


if __name__ == '__main__':
    unittest.main()
