#!/usr/bin/env python3
"""
ZAYA PIPELINE — Blender Futuristic City Generator
Creates a cyberpunk city scene with walking people and renders a cinematic animation.

Run headless:
  blender -b -P blender_futuristic_city.py -- <spec.json>

spec.json:
  {
    "output": "/path/to/output.mp4",
    "duration": 5,
    "fps": 24,
    "resolution_x": 1920,
    "resolution_y": 1080,
    "samples": 64
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
from mathutils import Vector, Euler

# ─── PARSE ARGS ──────────────────────────────────────
argv = sys.argv
spec_path = argv[argv.index("--") + 1] if "--" in argv else None

if spec_path:
    with open(spec_path) as f:
        SPEC = json.load(f)
else:
    SPEC = {}

OUTPUT = SPEC.get("output", "/opt/zaya_os/hub/io/output/video/futuristic_city.mp4")
DURATION = SPEC.get("duration", 5)
FPS = SPEC.get("fps", 24)
RES_X = SPEC.get("resolution_x", 1920)
RES_Y = SPEC.get("resolution_y", 1080)
SAMPLES = SPEC.get("samples", 64)
TOTAL_FRAMES = DURATION * FPS
SEED = SPEC.get("seed", 42)

random.seed(SEED)

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

print(f"[CITY] Output: {OUTPUT}")
print(f"[CITY] Duration: {DURATION}s | FPS: {FPS} | Frames: {TOTAL_FRAMES}")
print(f"[CITY] Resolution: {RES_X}x{RES_Y} | Samples: {SAMPLES}")


# ─── CLEANUP SCENE ───────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
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


def create_glass_material(name, color, roughness=0.1):
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


def create_pbr_material(name, color, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    principled = nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    return mat


def add_object(obj):
    bpy.context.collection.objects.link(obj)
    return obj


# ─── MATERIALS ───────────────────────────────────────

# Building materials
mat_building_dark = create_pbr_material("BuildingDark", (0.02, 0.02, 0.03), metallic=0.8, roughness=0.3)
mat_building_mid = create_pbr_material("BuildingMid", (0.04, 0.04, 0.06), metallic=0.7, roughness=0.4)
mat_glass = create_glass_material("Glass", (0.3, 0.5, 0.7), roughness=0.05)

# Neon materials — cyberpunk palette
mat_neon_cyan = create_emission_material("NeonCyan", (0.0, 0.8, 1.0), strength=15.0)
mat_neon_magenta = create_emission_material("NeonMagenta", (1.0, 0.0, 0.6), strength=15.0)
mat_neon_orange = create_emission_material("NeonOrange", (1.0, 0.4, 0.0), strength=12.0)
mat_neon_violet = create_emission_material("NeonViolet", (0.5, 0.0, 1.0), strength=12.0)
mat_neon_green = create_emission_material("NeonGreen", (0.0, 1.0, 0.3), strength=10.0)
neon_materials = [mat_neon_cyan, mat_neon_magenta, mat_neon_orange, mat_neon_violet, mat_neon_green]

# Ground
mat_ground = create_pbr_material("Ground", (0.01, 0.01, 0.015), metallic=0.9, roughness=0.1)

# Hologram
mat_hologram = create_emission_material("Hologram", (0.0, 0.6, 1.0), strength=3.0)

# Person materials
mat_person_body = create_pbr_material("PersonBody", (0.1, 0.1, 0.12), metallic=0.0, roughness=0.7)
person_accent_colors = [
    (0.0, 0.7, 0.9), (0.9, 0.0, 0.5), (0.9, 0.5, 0.0),
    (0.4, 0.0, 0.9), (0.0, 0.9, 0.3), (0.9, 0.9, 0.0)
]

print("[CITY] Building city geometry...")

# ─── GROUND PLANE ────────────────────────────────────

mesh = bpy.data.meshes.new("Ground")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=100)
bm.to_mesh(mesh)
bm.free()
ground = bpy.data.objects.new("Ground", mesh)
ground.data.materials.append(mat_ground)
add_object(ground)

# Road — darker strip down the middle
mesh = bpy.data.meshes.new("Road")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=100)
bm.to_mesh(mesh)
bm.free()
road = bpy.data.objects.new("Road", mesh)
road.scale = (0.08, 1.0, 1.0)
road.location.z = 0.01
road_mat = create_pbr_material("Road", (0.015, 0.015, 0.02), metallic=0.6, roughness=0.2)
road.data.materials.append(road_mat)
add_object(road)

# Road center line — neon strip
mesh = bpy.data.meshes.new("RoadLine")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=100)
bm.to_mesh(mesh)
bm.free()
roadline = bpy.data.objects.new("RoadLine", mesh)
roadline.scale = (0.003, 1.0, 1.0)
roadline.location.z = 0.02
roadline.data.materials.append(mat_neon_cyan)
add_object(roadline)


# ─── BUILDINGS ───────────────────────────────────────

def create_building(name, x, y, width, depth, height, mat):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.scale = (width, depth, height)
    obj.location = (x, y, height / 2)
    obj.data.materials.append(mat)
    add_object(obj)
    return obj


def add_windows(building_obj, rows, cols, neon_mat):
    """Add emissive window strips to a building."""
    bx, by, bz = building_obj.location
    sx, sy, sz = building_obj.scale

    for row in range(rows):
        for col in range(cols):
            if random.random() < 0.3:  # 30% of windows are lit
                continue
            wh = sz / rows * 0.4
            ww = sx / cols * 0.6
            wx = bx - sx/2 + sx/cols * (col + 0.5)
            wz = bz - sz/2 + sz/rows * (row + 0.5)
            wy = by + sy/2 + 0.01  # Front face

            mesh = bpy.data.meshes.new(f"Win_{building_obj.name}_{row}_{col}")
            bm = bmesh.new()
            bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
            bm.to_mesh(mesh)
            bm.free()
            win = bpy.data.objects.new(f"Win_{building_obj.name}_{row}_{col}", mesh)
            win.scale = (ww, wh, 1)
            win.location = (wx, wy, wz)
            win.rotation_euler = (math.pi/2, 0, 0)
            chosen_mat = random.choice(neon_materials) if random.random() < 0.4 else neon_mat
            win.data.materials.append(chosen_mat)
            add_object(win)


# Left side buildings
for i in range(16):
    h = random.uniform(8, 30)
    w = random.uniform(3, 6)
    d = random.uniform(4, 8)
    x = -12 + random.uniform(-3, 0)
    y = -60 + i * 8 + random.uniform(-1, 1)
    mat = random.choice([mat_building_dark, mat_building_mid])
    b = create_building(f"BuildingL{i}", x, y, w, d, h, mat)
    add_windows(b, rows=int(h/2), cols=random.randint(2, 5), neon_mat=random.choice(neon_materials))

# Right side buildings
for i in range(16):
    h = random.uniform(8, 30)
    w = random.uniform(3, 6)
    d = random.uniform(4, 8)
    x = 12 + random.uniform(0, 3)
    y = -60 + i * 8 + random.uniform(-1, 1)
    mat = random.choice([mat_building_dark, mat_building_mid])
    b = create_building(f"BuildingR{i}", x, y, w, d, h, mat)
    add_windows(b, rows=int(h/2), cols=random.randint(2, 5), neon_mat=random.choice(neon_materials))

# Background skyline — tall distant buildings
for i in range(10):
    h = random.uniform(25, 60)
    w = random.uniform(5, 12)
    d = random.uniform(5, 10)
    x = random.uniform(-40, 40)
    y = 80 + random.uniform(0, 30)
    b = create_building(f"Skyline{i}", x, y, w, d, h, mat_building_dark)


# ─── NEON SIGNS ──────────────────────────────────────

def create_neon_bar(name, location, rotation, scale, mat):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = rotation
    obj.scale = scale
    obj.data.materials.append(mat)
    add_object(obj)
    return obj


# Horizontal neon bars on buildings
for i in range(20):
    side = random.choice([-1, 1])
    x = side * random.uniform(8, 11)
    y = random.uniform(-50, 50)
    z = random.uniform(3, 15)
    length = random.uniform(2, 5)
    mat = random.choice(neon_materials)
    create_neon_bar(
        f"Neon_{i}",
        (x, y, z),
        (0, 0, random.uniform(-0.2, 0.2)),
        (length, 0.08, 0.15),
        mat
    )

# Vertical neon strips on some buildings
for i in range(8):
    side = random.choice([-1, 1])
    x = side * random.uniform(9, 12)
    y = random.uniform(-40, 40)
    z = random.uniform(5, 18)
    height = random.uniform(3, 10)
    mat = random.choice(neon_materials)
    create_neon_bar(
        f"NeonV_{i}",
        (x, y, z),
        (0, 0, 0),
        (0.08, 0.15, height),
        mat
    )

print("[CITY] Neon signs placed.")


# ─── FLOATING HOLOGRAM PANELS ────────────────────────

for i in range(4):
    mesh = bpy.data.meshes.new(f"Hologram_{i}")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    holo = bpy.data.objects.new(f"Hologram_{i}", mesh)
    side = random.choice([-1, 1])
    holo.location = (side * random.uniform(6, 10), random.uniform(-20, 30), random.uniform(8, 16))
    holo.rotation_euler = (math.pi/2 + random.uniform(-0.1, 0.1), 0, random.uniform(-0.3, 0.3))
    holo.scale = (random.uniform(1.5, 3.0), random.uniform(1.0, 2.0), 1.0)
    holo.data.materials.append(mat_hologram)
    add_object(holo)

    # Animate hologram glow — subtle flicker
    holo.keyframe_insert(data_path="scale", frame=1)
    for f in range(1, TOTAL_FRAMES + 1, 6):
        flicker = random.uniform(0.9, 1.1)
        holo.scale = (holo.scale.x * flicker, holo.scale.y, 1.0)
        holo.keyframe_insert(data_path="scale", frame=f)
        holo.scale = (holo.scale.x / flicker, holo.scale.y, 1.0)


# ─── PEOPLE (LOW-POLY FIGURES) ───────────────────────

def create_person(name, x, y, accent_color):
    """Create a low-poly person: body + head + accent stripe."""
    # Body — tall box
    mesh = bpy.data.meshes.new(f"{name}_body")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    body = bpy.data.objects.new(f"{name}_body", mesh)
    body.scale = (0.3, 0.25, 0.85)
    body.location = (x, y, 0.85)
    body.data.materials.append(mat_person_body)
    add_object(body)

    # Head — sphere
    mesh = bpy.data.meshes.new(f"{name}_head")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=6, radius=0.2)
    bm.to_mesh(mesh)
    bm.free()
    head = bpy.data.objects.new(f"{name}_head", mesh)
    head.location = (x, y, 1.9)
    head_mat = create_pbr_material(f"{name}_skin", (0.35, 0.25, 0.2), roughness=0.8)
    head.data.materials.append(head_mat)
    add_object(head)

    # Accent stripe — neon detail on body
    mesh = bpy.data.meshes.new(f"{name}_accent")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    accent = bpy.data.objects.new(f"{name}_accent", mesh)
    accent.scale = (0.32, 0.05, 0.08)
    accent.location = (x, y + 0.13, 1.1)
    accent_mat = create_emission_material(f"{name}_glow", accent_color, strength=8.0)
    accent.data.materials.append(accent_mat)
    add_object(accent)

    # Parent head and accent to body
    head.parent = body
    head.location = (0, 0, 1.05)
    accent.parent = body
    accent.location = (0, 0.13, 0.25)

    return body


def animate_person_walk(person, start_y, end_y, sway=True):
    """Animate person walking along Y axis with subtle body sway."""
    person.location.y = start_y
    person.keyframe_insert(data_path="location", frame=1)
    person.location.y = end_y
    person.keyframe_insert(data_path="location", frame=TOTAL_FRAMES)

    if sway:
        # Subtle left-right sway for walk feel
        for f in range(1, TOTAL_FRAMES + 1, 4):
            sway_amount = math.sin(f * 0.5) * 0.04
            person.rotation_euler.y = sway_amount
            person.keyframe_insert(data_path="rotation_euler", frame=f)

    # Linear interpolation for smooth walk
    if person.animation_data and person.animation_data.action:
        for fc in person.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'


# Sidewalk people — left side
print("[CITY] Creating people...")
people = []
for i in range(8):
    x = random.uniform(-7, -5)
    y = random.uniform(-30, 10)
    accent = random.choice(person_accent_colors)
    p = create_person(f"PersonL{i}", x, y, accent)
    speed = random.uniform(5, 15)
    direction = random.choice([-1, 1])
    animate_person_walk(p, y, y + direction * speed)
    people.append(p)

# Sidewalk people — right side
for i in range(8):
    x = random.uniform(5, 7)
    y = random.uniform(-30, 10)
    accent = random.choice(person_accent_colors)
    p = create_person(f"PersonR{i}", x, y, accent)
    speed = random.uniform(5, 15)
    direction = random.choice([-1, 1])
    animate_person_walk(p, y, y + direction * speed)
    people.append(p)

# A few people crossing the road
for i in range(3):
    x_start = random.uniform(-6, -4)
    x_end = random.uniform(4, 6)
    y = random.uniform(-10, 20)
    accent = random.choice(person_accent_colors)
    p = create_person(f"PersonX{i}", x_start, y, accent)
    # Animate X crossing
    p.location.x = x_start
    p.keyframe_insert(data_path="location", frame=1)
    p.location.x = x_end
    p.keyframe_insert(data_path="location", frame=TOTAL_FRAMES)
    # Also slight Y movement
    animate_person_walk(p, y, y + random.uniform(2, 5))
    people.append(p)

print(f"[CITY] {len(people)} people created and animated.")


# ─── STREET LIGHTS ───────────────────────────────────

for i in range(10):
    for side in [-1, 1]:
        x = side * 8
        y = -40 + i * 9

        # Pole
        mesh = bpy.data.meshes.new(f"Pole_{side}_{i}")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(mesh)
        bm.free()
        pole = bpy.data.objects.new(f"Pole_{side}_{i}", mesh)
        pole.scale = (0.08, 0.08, 3.5)
        pole.location = (x, y, 3.5)
        pole.data.materials.append(mat_building_mid)
        add_object(pole)

        # Light
        light_data = bpy.data.lights.new(f"StreetLight_{side}_{i}", type="POINT")
        light_data.energy = 50
        light_data.color = (0.8, 0.9, 1.0)
        light_data.shadow_soft_size = 1.0
        light_obj = bpy.data.objects.new(f"StreetLight_{side}_{i}", light_data)
        light_obj.location = (x, y, 7.2)
        add_object(light_obj)


# ─── ATMOSPHERIC FOG ─────────────────────────────────

# Volumetric world fog
world = bpy.data.worlds.new("CyberWorld")
scene.world = world
world.use_nodes = True
nodes = world.node_tree.nodes
links = world.node_tree.links
nodes.clear()

bg = nodes.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.005, 0.005, 0.015, 1.0)
bg.inputs["Strength"].default_value = 0.3

volume = nodes.new("ShaderNodeVolumePrincipled")
volume.inputs["Density"].default_value = 0.008
volume.inputs["Emission Color"].default_value = (0.02, 0.03, 0.06, 1.0)
volume.inputs["Emission Strength"].default_value = 0.05

output = nodes.new("ShaderNodeOutputWorld")
links.new(bg.outputs[0], output.inputs["Surface"])
links.new(volume.outputs[0], output.inputs["Volume"])

print("[CITY] Atmosphere configured.")


# ─── CAMERA ──────────────────────────────────────────

cam_data = bpy.data.cameras.new("MainCam")
cam_data.lens = 28  # Wide angle for street feel
cam_data.clip_end = 500
cam = bpy.data.objects.new("MainCam", cam_data)
cam.location = (0, -25, 2.5)  # Street level, eye height
cam.rotation_euler = (math.radians(85), 0, 0)  # Looking slightly up
add_object(cam)
scene.camera = cam

# Animate camera — dolly forward
cam.location = (0, -25, 2.5)
cam.keyframe_insert(data_path="location", frame=1)
cam.location = (0, 5, 2.8)  # Move forward and rise slightly
cam.keyframe_insert(data_path="location", frame=TOTAL_FRAMES)

# Subtle rotation — look around slightly
cam.rotation_euler = (math.radians(82), 0, math.radians(-2))
cam.keyframe_insert(data_path="rotation_euler", frame=1)
cam.rotation_euler = (math.radians(80), 0, math.radians(2))
cam.keyframe_insert(data_path="rotation_euler", frame=TOTAL_FRAMES)

# Smooth camera motion
if cam.animation_data and cam.animation_data.action:
    for fc in cam.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
            kp.handle_left_type = 'AUTO_CLAMPED'
            kp.handle_right_type = 'AUTO_CLAMPED'

print("[CITY] Camera set — street level dolly forward.")


# ─── RENDER SETTINGS (EEVEE) ─────────────────────────

scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = RES_X
scene.render.resolution_y = RES_Y
scene.render.resolution_percentage = 100

# EEVEE settings — Blender 4.1 API
eevee = scene.eevee
eevee.taa_render_samples = SAMPLES
eevee.use_bloom = True
eevee.bloom_threshold = 0.5
eevee.bloom_intensity = 0.3
eevee.bloom_radius = 6.0
eevee.use_volumetric_lights = True
eevee.volumetric_tile_size = '4'
eevee.volumetric_samples = 64
eevee.use_ssr = True
eevee.use_ssr_refraction = True
eevee.use_gtao = True
eevee.gtao_distance = 2.0

# Motion blur
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.4

# Output as frames first, then assemble
frame_dir = os.path.dirname(OUTPUT) + "/frames_city_temp/"
os.makedirs(frame_dir, exist_ok=True)
scene.render.filepath = frame_dir
scene.render.image_settings.file_format = 'PNG'

print(f"[CITY] EEVEE configured — bloom, volumetrics, SSR, AO.")
print(f"[CITY] Rendering {TOTAL_FRAMES} frames...")

# ─── RENDER ──────────────────────────────────────────

bpy.ops.render.render(animation=True)

print("[CITY] Frames rendered. Assembling video...")

# ─── ASSEMBLE VIDEO ──────────────────────────────────

import subprocess

# ffmpeg: frames to video
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
    print(f"[CITY] ERROR ffmpeg: {r.stderr}")
    sys.exit(1)

# Clean up frames
import shutil
shutil.rmtree(frame_dir)

# Result
size = os.path.getsize(OUTPUT)
print(f"[CITY] DONE — {OUTPUT}")
print(f"[CITY] Duration: {DURATION}s | Size: {size/1024/1024:.1f}MB")

result = {
    "ok": True,
    "output": OUTPUT,
    "duration_s": DURATION,
    "fps": FPS,
    "resolution": f"{RES_X}x{RES_Y}",
    "frames": TOTAL_FRAMES,
    "people": len(people),
    "size_bytes": size
}
print(json.dumps(result))
