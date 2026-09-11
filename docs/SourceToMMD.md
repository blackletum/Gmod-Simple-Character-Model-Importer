# Source to MMD

The **Source → MMD** tab is an experimental Windows workflow for converting an
extracted GMod / Half-Life 2 character into an MMD `.pmx`. It shares the app's
managed Blender installation and keeps its own conversion settings. Changing
the forward workflow's target game does not change this tab.

## Before starting

Use the normal [source setup and launch instructions](../README.md#run-without-building).
Launch the current source checkout to use this experimental feature; an older
release executable will not contain it.

Prepare an extracted character model and its assets:

- The character `.mdl`, with its companion `.vvd` and `.dx90.vtx` files. Keep any
  other supplied companion files together. Animation-only `.mdl` libraries
  cannot be converted into character geometry.
- The character's material tree, including `.vmt` material definitions and the
  `.vtf` textures they reference. Preserve the folders beneath `materials`.
- A writable output folder with room for the PMX, textures, and intermediate
  Blender files.

This workflow currently uses Windows versions of Crowbar and VTFCmd. The
repository bundles the Crowbar command-line decompiler at
`external_tools/crowbar/cli/CrowbarCommandLineDecomp.exe` and VTFCmd under
`external_tools/vtfcmd`. Blender add-ons are prepared from `plugins_software` in
a separate Source-to-MMD profile beneath
`%LOCALAPPDATA%\MMDCharacterImporter\source_to_mmd\blender_profile`.

The input picker accepts an extracted `.mdl`; unpack `.gma` or `.vpk` archives
before starting. Source-to-MMD does not run StudioMDL, install a game addon,
or require a Steam game installation when all input assets are supplied.

## Convert through the GUI

1. Open **Source → MMD**, beside the main import and model manager tabs.
2. Set **Source model** to the character `.mdl`.
3. Set **Materials folder** to the extracted addon's root or its `materials`
   folder. The field is optional when the converter can find the materials
   beside the model's folder structure. Supplying it explicitly is useful
   when models and materials were copied separately.
4. Choose **Output folder** and click **Analyze model**. This decompiles the
   source, finds the render meshes and bodygroups, and extracts the textures.
5. Review the analysis notes and **Character parts**. Required meshes stay
   selected. Choosing another part in a bodygroup deselects its alternative;
   a group can be left empty only when the source allows a blank variant.
6. Optionally enable **Show additional options** and choose a `.vmd` under
   **Motion check (optional)**.
7. Click **Convert to MMD**. Progress and tool output appear in the tab. The
   exported PMX loads into the preview when conversion succeeds.
8. Inspect the preview, read the report, and open the PMX in MMD to test poses,
   expressions, and motion playback.

**Cancel** stops the active conversion tools. Closing the app during a reverse
conversion requests cancellation and waits for cleanup before destroying its
worker. Saved files remain available for inspection. Another import or a
Blender maintenance operation must finish before this workflow starts.

Changing the input, material root, or destination clears the current analysis;
analyze again before converting. Each export from an existing analysis uses a
fresh output subfolder, so an older successful PMX cannot be mistaken for the
result of a failed retry.

## Results and checkpoints

Use **Open output**, **Open PMX**, **Open Blender checkpoint**, **Open report**,
and **Open log** from the tab. After a VMD check, **Open motion preview** opens
the Blender file with the reimported PMX and test motion.

The analysis folder contains `source_manifest.json`, decompiled source files,
extracted textures, and its analysis log. The conversion folder contains:

| File or folder | Purpose |
| --- | --- |
| `<model>.pmx` and its texture files | Portable MMD output; keep the textures with the PMX. |
| `mmd_model.blend` | Final editable Blender checkpoint. |
| `blend_stages/` | Rig, materials, and expressions before final export. |
| `conversion_report.json` | Overall results, warnings, output paths, and validation. |
| `rig_report.json`, `material_report.json`, `expression_report.json`, `export_report.json` | Stage-specific findings and conversion decisions. |
| `validation.json` | Structural checks on the exported PMX. |
| `conversion.log` and `logs/` | Combined and individual tool output. |
| `motion_check.json`, `motion_preview.blend` | Optional VMD sample results and animated Blender checkpoint. |
| `failure.json` | Stage and error details when a run fails after its workspace is created. |

On failure, the live log names the working folder. **Open output** also provides
access to saved files when no successful PMX was returned. Fix a missing asset
or invalid selection, then analyze or convert again as appropriate.

## What the checks establish

Every export checks for missing geometry, invalid skin weights or bone
references, invalid hierarchy, missing/nonportable textures, and malformed
vertex morphs. These checks can reject a broken file; they do not establish
that the character moves or looks correct.

The optional VMD check reimports the **exported PMX** into Blender through
`mmd_tools`, applies the selected VMD, and samples up to 32 frames across the
motion. It rejects non-finite coordinates or extreme expansion/collapse of
the mesh bounds, and rejects motions with no matching animated controls.
The GUI and reports identify whether this check ran.

Small deformation errors, bad contacts, expression quality, motion compatibility,
and differences between Blender and MMD still require visual review. Native
MMD playback has not yet been validated for this initial workflow.

## Current limits

- **Character coverage:** development starts with the supplied Alyx models.
  Other Source skeletons, custom bodygroups, materials, and facial controls may
  need additional handling. This is not a guarantee of general Source-model
  compatibility or a GMod-to-L4D2 converter.
- **Physics:** no automatic MMD secondary rigid bodies or joints are generated.
- **Eyes:** iris appearance is reconstructed, but iris gaze remains static;
  Source eye tracking and shader behavior are not reproduced as MMD controls.
- **Expressions:** Source flexes are preserved, and standard MMD expression
  combinations are approximate. Their names alone do not establish good facial
  movement; check blinking and mouth shapes on the exported model.
- **Rig deformation:** neutral arms and fingers are calibrated for shared MMD
  poses, rebinding the mesh and all shape keys together. Qualified ValveBiped
  arm and joint helpers use portable linear skinning; elbow/knee helper bones reproduce recognized half-angle VRD responses
  through PMX append rotations. Complex or unknown procedural helpers
  retain their weights and still need manual refinement. The report lists both.
- **Preview and motion:** the GUI model preview is static. The optional VMD
  check runs in Blender; use its motion checkpoint or MMD for animated review.
- **Platforms and packaging:** this reverse workflow currently requires
  Windows. Source runs are the current development path; a newly built
  executable needs separate packaged-runtime verification.

## Command line for local diagnostics

The GUI is the normal entry point. The same backend can run from an activated
project Python environment for diagnostics:

```powershell
python .\tools\source_to_mmd_core.py --mdl "C:\models\alyx.mdl" --materials-root "C:\character\materials" --out "C:\exports\mmd" --analyze-only
```

Remove `--analyze-only` to convert. Add `--motion "C:\motions\test.vmd"` for the
optional Blender check. `--blender-exe` and `--blender-profile` can select a
specific Blender executable and isolated add-on profile for local testing.
The GUI uses the app's managed installation by default.

For a prepared local development runtime, `MCI_SOURCE_BLENDER` and
`MCI_SOURCE_PROFILE` select the executable and isolated reverse profile from
the GUI as well. These overrides do not change the forward workflow's profile.

## Development checks

Run `python -m unittest discover -s tests -v` for input planning and morph recipe
regressions. Blender rig tests skip under ordinary Python. Run them with the
reverse add-ons enabled, `SOURCE_MMD_TEST_QC` pointing to a decompiled fixture QC,
and `SOURCE_MMD_TEST_MESHES` containing the selected reference mesh stems:

```powershell
blender --background --python-exit-code 1 --python tests/test_source_to_mmd_rig.py
```

The initial local checks cover the supplied Alyx, Alyx Episode Two, and Alyx
interior files. Real GUI workers analyze and export all three. Alyx's exported
PMX has also been reimported for a 32-frame VMD sample check, with selected
poses and neutral/blink/mouth expressions visually inspected in Blender.

The second rig revision also uses a supplied Miku PMX and peace VPD to check
arm/finger pose directions, and measures mouth apertures at weights 0, 0.5 and
1. Vowels select Source's lip-opening AU27/AU27Z targets when available, using
the authored jaw range. Export orders PMX parents before children and remaps
all bone references for simpler consumers. These are improvements to the model;
MocuMocoDance playback has not been directly verified by the automated checks.


## Third rig revision

The converter uses the original Source Spine landmark as a shared upper/lower
body rotation pivot. The center and other joint positions remain unchanged.
Neutral foot yaw is aligned forward when the source ankle/toe direction is
unambiguous. Four twist controls now distribute their rotation through twelve
hidden append helpers, reducing the pinching of a two-bone linear blend.
Verified Source elbow and knee helpers retain their weights and receive half
the joint rotation; other procedural responses remain approximations.

Vowels use the Source phoneme controller suppression rules to keep lip actions
from stacking excessively. The standard `にこり` control affects eyebrows;
`口の微笑み` preserves the previous mouth smile as a separate custom expression.
The original Source flexes remain editable. Alyx exports 106 bones and 62 morphs.

Regression coverage includes shared-waist rotation, foot direction, portable
append references, and original rig checks. Exported-PMX stress diagnostics
cover arm twists, elbow bends, knee bends, planted feet and vowel overlap.
These checks cannot guarantee every motion or model's contact and expression
quality. The local GUI and source scripts use these changes directly; a new
packaged executable still needs a separate build and runtime check.
