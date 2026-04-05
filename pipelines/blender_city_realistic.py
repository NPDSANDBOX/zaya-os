#!/usr/bin/env python3
"""
ZAYA PIPELINE — Realistic Futuristic City with MPFB Humans
Creates a cyberpunk city with real MakeHuman characters walking and interacting.

Run headless:
  blender -b -P blender_city_realistic.py -- <spec.json>

spec.json:
  {
    "output": "/path/to/output.mp4",
    "duration": 5,
    "fps": 24,
    "resolution_x": 1920,
    "resolution_y": 1080,
    "samples": 64,
    "num_people": 6
  }

Author: Mike Henri
System: Zaya OS
"""
import bpy
import bmesh
import json
import sys
import os
import math
import random
import shutil
from mathutils import Vector, Euler

# ─── PARSE ARGS ──────────────────────────────────────
argv = sys.argv
spec_path = argv[argv.index("--") + 1] if "--" in argv else None

if spec_path:
    with open(spec_path) as f:
        SPEC = json.load(f)
else:
    SPEC = {}

OUTPUT = SPEC.get("output", "/opt/zaya_os/hub/io/output/video/futuristic_city_realistic.mp4")
DURATION = SPEC.get("duration", 5)
FPS = SPEC.get("fps", 24)
RES_X = SPEC.get("resolution_x", 1920)
RES_Y = SPEC.get("resolution_y", 1080)
SAMPLES = SPEC.get("samples", 64)
NUM_PEOPLE = SPEC.get("num_people", 6)
TOTAL_FRAMES = DURATION * FPS
SEED = SPEC.get("seed", 42)

random.seed(SEED)

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

print(f"[CITY_REAL] Output: {OUTPUT}")
print(f"[CITY_REAL] Duration: {DURATION}s | FPS: {FPS} | Frames: {TOTAL_FRAMES}")
print(f"[CITY_REAL] Resolution: {RES_X}x{RES_Y} | Samples: {SAMPLES}")
print(f"[CITY_REAL] People: {NUM_PEOPLE}")


# ─── CLEANUP & ENABLE MPFB ───────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)

# Enable MPFB addon
try:
    bpy.ops.preferences.addon_enable(module="mpfb")
    print("[CITY_REAL] MPFB addon enabled.")
except Exception as e:
    print(f"[CITY_REAL] MPFB enable warning: {e}")

# Import MPFB services
from mpfb.services import HumanService, TargetService, AnimationService, LocationService
from mpfb.entities.objectproperties import HumanObjectProperties

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = TOTAL_FRAMES
scene.render.fps = FPS


# ─── HELPER FUNCTIONS ────────────────────────────────

def create_emission_material(name, color, strength=5.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = strength
    links.new(emission.outputs[0], output.inputs[0])
    return mat


def create_pbr_material(name, color, metallic=0.0, roughness=0.5, emission_color=None, emission_strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    principled = nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    if emission_color and emission_strength > 0:
        principled.inputs["Emission Color"].default_value = (*emission_color, 1.0)
        principled.inputs["Emission Strength"].default_value = emission_strength
    return mat


def create_glass_material(name, color, roughness=0.05):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    glass = nodes.new("ShaderNodeBsdfGlass")
    glass.inputs["Color"].default_value = (*color, 1.0)
    glass.inputs["Roughness"].default_value = roughness
    links.new(glass.outputs[0], output.inputs[0])
    return mat


def add_object(obj):
    bpy.context.collection.objects.link(obj)
    return obj


def make_cube(name, location, scale, material):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.scale = scale
    obj.data.materials.append(material)
    add_object(obj)
    return obj


def make_plane(name, location, scale, material):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.scale = scale
    obj.data.materials.append(material)
    add_object(obj)
    return obj


# ─── MATERIALS ───────────────────────────────────────

mat_building_dark = create_pbr_material("BuildingDark", (0.015, 0.015, 0.025), metallic=0.85, roughness=0.2)
mat_building_mid = create_pbr_material("BuildingMid", (0.03, 0.03, 0.05), metallic=0.7, roughness=0.3)
mat_building_glass = create_glass_material("BuildingGlass", (0.2, 0.4, 0.6), roughness=0.02)
mat_concrete = create_pbr_material("Concrete", (0.06, 0.06, 0.065), metallic=0.1, roughness=0.85)

mat_ground = create_pbr_material("Ground", (0.008, 0.008, 0.012), metallic=0.9, roughness=0.08)
mat_sidewalk = create_pbr_material("Sidewalk", (0.04, 0.04, 0.045), metallic=0.3, roughness=0.7)

mat_neon_cyan = create_emission_material("NeonCyan", (0.0, 0.85, 1.0), strength=20.0)
mat_neon_magenta = create_emission_material("NeonMagenta", (1.0, 0.0, 0.55), strength=20.0)
mat_neon_orange = create_emission_material("NeonOrange", (1.0, 0.45, 0.0), strength=15.0)
mat_neon_violet = create_emission_material("NeonViolet", (0.55, 0.0, 1.0), strength=15.0)
mat_neon_green = create_emission_material("NeonGreen", (0.0, 1.0, 0.35), strength=12.0)
mat_neon_white = create_emission_material("NeonWhite", (0.9, 0.95, 1.0), strength=8.0)
neon_mats = [mat_neon_cyan, mat_neon_magenta, mat_neon_orange, mat_neon_violet, mat_neon_green]

mat_hologram = create_emission_material("Hologram", (0.0, 0.5, 1.0), strength=4.0)


# ─── GROUND & ROAD ──────────────────────────────────

print("[CITY_REAL] Building environment...")

# Main ground
make_plane("Ground", (0, 0, 0), (200, 200, 1), mat_ground)

# Road surface
make_plane("Road", (0, 0, 0.005), (16, 200, 1), mat_ground)

# Sidewalks
make_plane("SidewalkL", (-12, 0, 0.02), (8, 200, 1), mat_sidewalk)
make_plane("SidewalkR", (12, 0, 0.02), (8, 200, 1), mat_sidewalk)

# Road center neon line
make_plane("CenterLine", (0, 0, 0.015), (0.06, 200, 1), mat_neon_cyan)

# Lane markings
for i in range(-10, 10):
    make_plane(f"Lane_L_{i}", (-4, i * 6, 0.01), (0.04, 4, 1), mat_neon_white)
    make_plane(f"Lane_R_{i}", (4, i * 6, 0.01), (0.04, 4, 1), mat_neon_white)


# ─── BUILDINGS ───────────────────────────────────────

print("[CITY_REAL] Generating buildings...")

def create_building_complex(name, x, y, base_w, base_d, height):
    """Create a detailed building with glass panels and neon accents."""
    # Main structure
    mat = random.choice([mat_building_dark, mat_building_mid])
    main = make_cube(f"{name}_main", (x, y, height/2), (base_w, base_d, height), mat)

    # Glass facade panels
    num_floors = int(height / 1.5)
    num_cols = max(2, int(base_w / 1.2))
    face_y = y + base_d/2 + 0.02  # Front face

    for floor in range(num_floors):
        for col in range(num_cols):
            if random.random() < 0.2:
                continue  # Some windows dark

            ww = base_w / num_cols * 0.7
            wh = 1.0
            wx = x - base_w/2 + (base_w/num_cols) * (col + 0.5)
            wz = 1.5 + floor * 1.5

            # Window — either glass or emissive (lit room)
            if random.random() < 0.6:
                # Warm interior light
                warmth = random.uniform(0.6, 1.0)
                win_mat = create_emission_material(
                    f"{name}_win_{floor}_{col}",
                    (warmth, warmth * 0.8, warmth * 0.4),
                    strength=random.uniform(1.0, 4.0)
                )
            else:
                win_mat = random.choice(neon_mats)

            win = make_plane(
                f"{name}_win_{floor}_{col}",
                (wx, face_y, wz),
                (ww, wh, 1),
                win_mat
            )
            win.rotation_euler = (math.pi/2, 0, 0)

    # Neon accent strip on building edge
    if random.random() < 0.7:
        neon_mat = random.choice(neon_mats)
        strip_h = random.uniform(height * 0.3, height * 0.8)
        make_cube(
            f"{name}_neon_strip",
            (x + base_w/2 + 0.05, y, strip_h/2 + 1),
            (0.06, 0.1, strip_h),
            neon_mat
        )

    # Rooftop antenna / structure
    if height > 15 and random.random() < 0.5:
        ant_h = random.uniform(2, 5)
        make_cube(
            f"{name}_antenna",
            (x, y, height + ant_h/2),
            (0.15, 0.15, ant_h),
            mat_building_mid
        )
        # Red light on top
        make_cube(
            f"{name}_light",
            (x, y, height + ant_h + 0.2),
            (0.25, 0.25, 0.25),
            create_emission_material(f"{name}_red", (1, 0, 0), strength=10)
        )

    return main


# Left row — close buildings
for i in range(14):
    h = random.uniform(10, 35)
    w = random.uniform(4, 7)
    d = random.uniform(5, 9)
    x = -18 + random.uniform(-2, 0)
    y = -50 + i * 7.5 + random.uniform(-0.5, 0.5)
    create_building_complex(f"BldgL{i}", x, y, w, d, h)

# Right row — close buildings
for i in range(14):
    h = random.uniform(10, 35)
    w = random.uniform(4, 7)
    d = random.uniform(5, 9)
    x = 18 + random.uniform(0, 2)
    y = -50 + i * 7.5 + random.uniform(-0.5, 0.5)
    create_building_complex(f"BldgR{i}", x, y, w, d, h)

# Distant skyline
for i in range(12):
    h = random.uniform(30, 70)
    w = random.uniform(6, 15)
    d = random.uniform(6, 12)
    x = random.uniform(-50, 50)
    y = 70 + random.uniform(0, 40)
    make_cube(f"Skyline{i}", (x, y, h/2), (w, d, h), mat_building_dark)

print("[CITY_REAL] Buildings done.")


# ─── NEON SIGNS & HOLOGRAMS ─────────────────────────

for i in range(25):
    side = random.choice([-1, 1])
    x = side * random.uniform(14, 17)
    y = random.uniform(-40, 50)
    z = random.uniform(3, 18)
    length = random.uniform(1.5, 5)
    make_cube(
        f"NeonSign_{i}", (x, y, z),
        (length, 0.06, random.uniform(0.1, 0.4)),
        random.choice(neon_mats)
    )

# Floating hologram panels
for i in range(5):
    side = random.choice([-1, 1])
    holo = make_plane(
        f"Hologram_{i}",
        (side * random.uniform(8, 14), random.uniform(-15, 35), random.uniform(9, 18)),
        (random.uniform(2, 4), random.uniform(1.5, 3), 1),
        mat_hologram
    )
    holo.rotation_euler = (math.pi/2 + random.uniform(-0.1, 0.1), 0, random.uniform(-0.2, 0.2))

    # Hologram flicker animation
    for f in range(1, TOTAL_FRAMES + 1, 5):
        flicker = random.uniform(0.85, 1.15)
        holo.scale.x = holo.scale.x * flicker
        holo.keyframe_insert(data_path="scale", frame=f)
        holo.scale.x = holo.scale.x / flicker

print("[CITY_REAL] Neon and holograms done.")


# ─── STREET LIGHTS ───────────────────────────────────

for i in range(12):
    for side_val in [-1, 1]:
        x = side_val * 9
        y = -45 + i * 8

        # Pole
        make_cube(f"Pole_{side_val}_{i}", (x, y, 3), (0.06, 0.06, 6), mat_concrete)

        # Arm
        make_cube(f"Arm_{side_val}_{i}", (x - side_val * 1.2, y, 6.2), (2.4, 0.06, 0.06), mat_concrete)

        # Light fixture
        light_data = bpy.data.lights.new(f"SLight_{side_val}_{i}", type="SPOT")
        light_data.energy = 200
        light_data.color = (0.85, 0.9, 1.0)
        light_data.spot_size = math.radians(60)
        light_data.shadow_soft_size = 0.5
        light_obj = bpy.data.objects.new(f"SLight_{side_val}_{i}", light_data)
        light_obj.location = (x - side_val * 2.2, y, 6.0)
        light_obj.rotation_euler = (math.radians(90), 0, 0)
        add_object(light_obj)


# ─── MPFB HUMAN CHARACTERS ──────────────────────────

print(f"[CITY_REAL] Creating {NUM_PEOPLE} MPFB humans...")

# Character phenotype presets — diverse characters
character_presets = [
    {"gender": 0.85, "age": 0.5, "muscle": 0.65, "weight": 0.5,
     "race": {"african": 0.0, "asian": 0.0, "caucasian": 1.0}, "label": "young_male_caucasian"},
    {"gender": 0.15, "age": 0.5, "muscle": 0.4, "weight": 0.45,
     "race": {"african": 0.0, "asian": 1.0, "caucasian": 0.0}, "label": "young_female_asian"},
    {"gender": 0.8, "age": 0.6, "muscle": 0.7, "weight": 0.55,
     "race": {"african": 1.0, "asian": 0.0, "caucasian": 0.0}, "label": "adult_male_african"},
    {"gender": 0.2, "age": 0.45, "muscle": 0.5, "weight": 0.5,
     "race": {"african": 0.0, "asian": 0.0, "caucasian": 1.0}, "label": "young_female_caucasian"},
    {"gender": 0.75, "age": 0.7, "muscle": 0.5, "weight": 0.6,
     "race": {"african": 0.0, "asian": 0.5, "caucasian": 0.5}, "label": "older_male_mixed"},
    {"gender": 0.25, "age": 0.5, "muscle": 0.55, "weight": 0.45,
     "race": {"african": 0.5, "asian": 0.0, "caucasian": 0.5}, "label": "young_female_mixed"},
    {"gender": 0.9, "age": 0.55, "muscle": 0.8, "weight": 0.5,
     "race": {"african": 0.0, "asian": 1.0, "caucasian": 0.0}, "label": "athletic_male_asian"},
    {"gender": 0.1, "age": 0.65, "muscle": 0.4, "weight": 0.5,
     "race": {"african": 1.0, "asian": 0.0, "caucasian": 0.0}, "label": "adult_female_african"},
]

# Clothing colors — cyberpunk palette
clothing_colors = [
    (0.02, 0.02, 0.03),   # Near black
    (0.05, 0.05, 0.08),   # Dark blue-grey
    (0.08, 0.03, 0.03),   # Dark red
    (0.03, 0.03, 0.08),   # Dark navy
    (0.06, 0.06, 0.06),   # Charcoal
    (0.04, 0.02, 0.06),   # Dark purple
]

humans_created = []
walk_cycle_path = os.path.join(
    LocationService.get_mpfb_data("walkcycles"),
    "crappy_experimental_female.json"
)

has_walk_cycle = os.path.exists(walk_cycle_path)
if has_walk_cycle:
    with open(walk_cycle_path, 'r') as f:
        walk_animation = json.load(f)
    print(f"[CITY_REAL] Walk cycle loaded: {walk_cycle_path}")
else:
    walk_animation = None
    print("[CITY_REAL] No walk cycle found — will use simple translation animation")

for i in range(NUM_PEOPLE):
    preset = character_presets[i % len(character_presets)]
    print(f"[CITY_REAL] Creating human {i+1}/{NUM_PEOPLE}: {preset['label']}...")

    # Build macro details
    macro_details = TargetService.get_default_macro_info_dict()
    macro_details["gender"] = preset["gender"]
    macro_details["age"] = preset["age"]
    macro_details["muscle"] = preset["muscle"]
    macro_details["weight"] = preset["weight"]
    macro_details["race"]["african"] = preset["race"]["african"]
    macro_details["race"]["asian"] = preset["race"]["asian"]
    macro_details["race"]["caucasian"] = preset["race"]["caucasian"]

    # Create the human
    try:
        basemesh = HumanService.create_human(
            mask_helpers=True,
            detailed_helpers=True,
            extra_vertex_groups=True,
            feet_on_ground=True,
            scale=0.1,
            macro_detail_dict=macro_details
        )
        basemesh.name = f"Human_{preset['label']}_{i}"
        print(f"[CITY_REAL]   Basemesh created: {basemesh.name}")
    except Exception as e:
        print(f"[CITY_REAL]   ERROR creating human: {e}")
        continue

    # Add rig for animation
    armature = None
    try:
        armature = HumanService.add_builtin_rig(basemesh, "default", import_weights=True)
        armature.name = f"Rig_{preset['label']}_{i}"
        print(f"[CITY_REAL]   Rig added: {armature.name}")
    except Exception as e:
        print(f"[CITY_REAL]   WARNING rig failed: {e}")

    # Apply a simple clothing material over the body
    cloth_color = random.choice(clothing_colors)
    cloth_mat = create_pbr_material(
        f"Clothing_{i}", cloth_color,
        metallic=0.1, roughness=0.7
    )
    # Add neon accent to clothing
    accent_color = random.choice([(0, 0.8, 1), (1, 0, 0.5), (1, 0.4, 0), (0.5, 0, 1), (0, 1, 0.3)])
    accent_mat = create_emission_material(f"Accent_{i}", accent_color, strength=5.0)

    if basemesh.data.materials:
        basemesh.data.materials.append(cloth_mat)
    else:
        basemesh.data.materials.append(cloth_mat)

    # Position on sidewalk
    side = random.choice([-1, 1])
    pos_x = side * random.uniform(9, 12)
    pos_y = random.uniform(-25, 15)
    direction = random.choice([-1, 1])

    # Move to position
    root = armature if armature else basemesh
    root.location = (pos_x, pos_y, 0)

    # Rotation — face walking direction
    if direction > 0:
        root.rotation_euler.z = 0
    else:
        root.rotation_euler.z = math.pi

    # Apply walk cycle if available
    if armature and walk_animation:
        try:
            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.select_all(action='DESELECT')
            armature.select_set(True)
            bpy.ops.object.mode_set(mode='POSE', toggle=False)
            AnimationService.set_key_frames_from_dict(armature, walk_animation, frame_offset=random.randint(0, 10))
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
            print(f"[CITY_REAL]   Walk cycle applied")
        except Exception as e:
            print(f"[CITY_REAL]   Walk cycle error: {e}")

    # Animate translation — walking along the street
    walk_speed = random.uniform(4, 10)
    root.location.y = pos_y
    root.keyframe_insert(data_path="location", frame=1)
    root.location.y = pos_y + direction * walk_speed
    root.keyframe_insert(data_path="location", frame=TOTAL_FRAMES)

    # Linear walk
    if root.animation_data and root.animation_data.action:
        for fc in root.animation_data.action.fcurves:
            if fc.data_path == "location":
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'

    humans_created.append(root)
    print(f"[CITY_REAL]   Positioned at ({pos_x:.1f}, {pos_y:.1f}) direction={'fwd' if direction>0 else 'back'}")

print(f"[CITY_REAL] {len(humans_created)} humans created.")


# ─── ATMOSPHERE ──────────────────────────────────────

world = bpy.data.worlds.new("CyberWorld")
scene.world = world
world.use_nodes = True
nodes = world.node_tree.nodes
links = world.node_tree.links
nodes.clear()

bg = nodes.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.003, 0.003, 0.012, 1.0)
bg.inputs["Strength"].default_value = 0.2

volume = nodes.new("ShaderNodeVolumePrincipled")
volume.inputs["Density"].default_value = 0.006
volume.inputs["Emission Color"].default_value = (0.015, 0.02, 0.04, 1.0)
volume.inputs["Emission Strength"].default_value = 0.03

output = nodes.new("ShaderNodeOutputWorld")
links.new(bg.outputs[0], output.inputs["Surface"])
links.new(volume.outputs[0], output.inputs["Volume"])


# ─── CAMERA ──────────────────────────────────────────

cam_data = bpy.data.cameras.new("MainCam")
cam_data.lens = 32
cam_data.clip_end = 500
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = 12.0
cam_data.dof.aperture_fstop = 2.8

cam = bpy.data.objects.new("MainCam", cam_data)
add_object(cam)
scene.camera = cam

# Street level dolly — smooth forward movement
cam.location = (2.0, -20, 2.0)
cam.rotation_euler = (math.radians(83), 0, math.radians(3))
cam.keyframe_insert(data_path="location", frame=1)
cam.keyframe_insert(data_path="rotation_euler", frame=1)

cam.location = (1.0, 8, 2.2)
cam.rotation_euler = (math.radians(80), 0, math.radians(-2))
cam.keyframe_insert(data_path="location", frame=TOTAL_FRAMES)
cam.keyframe_insert(data_path="rotation_euler", frame=TOTAL_FRAMES)

# Smooth bezier interpolation
if cam.animation_data and cam.animation_data.action:
    for fc in cam.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
            kp.handle_left_type = 'AUTO_CLAMPED'
            kp.handle_right_type = 'AUTO_CLAMPED'

print("[CITY_REAL] Camera: street level dolly with DOF.")


# ─── RENDER SETTINGS (EEVEE) ─────────────────────────

scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = RES_X
scene.render.resolution_y = RES_Y
scene.render.resolution_percentage = 100

eevee = scene.eevee
eevee.taa_render_samples = SAMPLES
eevee.use_bloom = True
eevee.bloom_threshold = 0.4
eevee.bloom_intensity = 0.35
eevee.bloom_radius = 6.5
eevee.use_volumetric_lights = True
eevee.volumetric_tile_size = '4'
eevee.volumetric_samples = 64
eevee.use_ssr = True
eevee.use_ssr_refraction = True
eevee.use_gtao = True
eevee.gtao_distance = 2.0

scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.35

# Frame output
frame_dir = os.path.join(os.path.dirname(OUTPUT), "frames_city_real_temp") + "/"
os.makedirs(frame_dir, exist_ok=True)
scene.render.filepath = frame_dir
scene.render.image_settings.file_format = 'PNG'

print(f"[CITY_REAL] EEVEE: bloom, volumetrics, SSR, AO, DOF, motion blur.")
print(f"[CITY_REAL] Rendering {TOTAL_FRAMES} frames...")

# ─── RENDER ──────────────────────────────────────────

bpy.ops.render.render(animation=True)

print("[CITY_REAL] Frames rendered. Assembling video...")

# ─── ASSEMBLE VIDEO ──────────────────────────────────

import subprocess

cmd = [
    "ffmpeg", "-y",
    "-framerate", str(FPS),
    "-i", frame_dir + "%04d.png",
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    OUTPUT
]
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print(f"[CITY_REAL] ERROR ffmpeg: {r.stderr}")
    sys.exit(1)

shutil.rmtree(frame_dir)

size = os.path.getsize(OUTPUT)
print(f"[CITY_REAL] DONE — {OUTPUT}")
print(f"[CITY_REAL] Duration: {DURATION}s | Size: {size/1024/1024:.1f}MB | People: {len(humans_created)}")

result = {
    "ok": True,
    "output": OUTPUT,
    "duration_s": DURATION,
    "fps": FPS,
    "resolution": f"{RES_X}x{RES_Y}",
    "frames": TOTAL_FRAMES,
    "people": len(humans_created),
    "size_bytes": size
}
print(json.dumps(result))
