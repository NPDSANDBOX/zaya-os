#!/usr/bin/env python3
"""
ZAYA PIPELINE — Book-to-Video
Reads immersive book text and extracts scenes for video production.
The book IS the script — each paragraph carries visual, sound, smell, touch, time.

Invented by Mike Henri.

Pipeline:
  Book text (.txt/.docx)
    → Scene Extractor (parses paragraphs into visual scenes)
    → Shot Builder (generates prompts for Wan2GP)
    → Audio Builder (narration + sound effects)
    → Production Queue (ready for Wan2GP batch processing)

Input: Episode text file
Output: Production JSON with scenes, prompts, audio cues, camera movements

Usage:
  python3 pipeline_book_to_video.py <episode.txt> [--output /path/to/output/]

Author: Mike Henri
System: Zaya OS
"""
import sys
import json
import os
import re
import time
from pathlib import Path

# NEVER /tmp
WORK_DIR = "/opt/zaya_os/hub/data/contracts/book_to_video"
OUTPUT_BASE = "/opt/zaya_os/projects/story/production"
FRAMES_DIR = "/opt/zaya_os/projects/story/frames"
EPISODES_DIR = "/opt/zaya_os/projects/story/episodes"


def log(msg):
    print(f"[BOOK2VIDEO] {msg}", flush=True)


class SceneExtractor:
    """
    Extracts production scenes from immersive book text.
    The book is written so the reader enters the story —
    every paragraph has visual, sound, environment, emotion.
    """

    # Scene break markers
    SCENE_BREAKS = [
        r'^\[',           # [brackets] = scene break
        r'^Location:',     # Location header
        r'^Year ',         # Year header
        r'^\—',           # Dialogue start
        r'^Glitch Sound:', # Sound direction
    ]

    # Sensory keywords for classification
    VISUAL_KEYS = [
        'light', 'dark', 'color', 'glow', 'shadow', 'reflection', 'neon',
        'rain', 'sun', 'fog', 'smoke', 'flash', 'flicker', 'pixel', 'glitch',
        'door', 'window', 'street', 'building', 'room', 'table', 'screen',
        'face', 'eyes', 'hair', 'hand', 'body', 'walk', 'run', 'sit',
        'portrait', 'stained-glass', 'chandelier', 'marble', 'velvet',
    ]

    SOUND_KEYS = [
        'sound', 'noise', 'echo', 'voice', 'whisper', 'laugh', 'cry',
        'meow', 'creak', 'tick', 'hum', 'buzz', 'static', 'keyboard',
        'footstep', 'rain', 'thunder', 'silence', 'music',
    ]

    SMELL_KEYS = [
        'smell', 'scent', 'aroma', 'odor', 'perfume', 'ozone', 'coffee',
        'frying', 'wood', 'rain', 'damp', 'electric',
    ]

    EMOTION_KEYS = [
        'fear', 'courage', 'chill', 'warm', 'cold', 'pressure', 'tension',
        'uneasy', 'determined', 'hesitate', 'instinct', 'wonder', 'dread',
    ]

    CAMERA_MAP = {
        'wide': ['city', 'street', 'building', 'skyline', 'crowd', 'mansion', 'room'],
        'close_up': ['face', 'eyes', 'hand', 'finger', 'lips', 'tear'],
        'medium': ['walk', 'sit', 'stand', 'approach', 'gesture'],
        'pov': ['sees', 'looks', 'watches', 'stares', 'notices', 'perceives'],
        'dolly': ['enters', 'approaches', 'walks toward', 'moves through'],
        'tilt_up': ['above', 'ceiling', 'sky', 'tower', 'rises', 'levitate'],
        'tilt_down': ['ground', 'floor', 'feet', 'beneath', 'below'],
    }

    def __init__(self):
        self.scenes = []

    def extract(self, text):
        """Extract scenes from book text."""
        lines = text.strip().split('\n')

        # Parse header
        header = self._parse_header(lines)

        # Split into paragraphs
        paragraphs = self._split_paragraphs(text)

        # Process each paragraph into a scene element
        scene_num = 0
        current_scene = {
            "scene_id": 0,
            "title": header.get("title", "Unknown"),
            "location": header.get("location", "Unknown"),
            "year": header.get("year", "Unknown"),
            "shots": [],
        }

        for para in paragraphs:
            para = para.strip()
            if not para or para == '[]':
                continue

            # Check if this is a new location/scene break
            if para.startswith('Location:') or para.startswith('Year '):
                if current_scene["shots"]:
                    self.scenes.append(current_scene)
                    scene_num += 1
                    current_scene = {
                        "scene_id": scene_num,
                        "title": "",
                        "location": para.replace("Location:", "").strip() if "Location:" in para else current_scene["location"],
                        "year": para.replace("Year", "").strip() if "Year" in para else current_scene["year"],
                        "shots": [],
                    }
                continue

            # Classify the paragraph
            shot = self._classify_paragraph(para)
            if shot:
                current_scene["shots"].append(shot)

        # Add last scene
        if current_scene["shots"]:
            self.scenes.append(current_scene)

        return self.scenes

    def _parse_header(self, lines):
        """Parse episode header (title, chapter, location, year)."""
        header = {}
        for line in lines[:10]:
            line = line.strip()
            if not line:
                continue
            if line.startswith('CHAPTER'):
                header['chapter'] = line
            elif line.startswith('Location:'):
                header['location'] = line.replace('Location:', '').strip()
            elif line.startswith('Year'):
                header['year'] = line.replace('Year', '').strip()
            elif not header.get('title') and line.isupper() or (len(line) < 60 and not line.startswith('—')):
                if 'chapter' in header and 'title' not in header:
                    header['title'] = line
        return header

    def _split_paragraphs(self, text):
        """Split text into meaningful paragraphs."""
        # Split on double newline or dialogue markers
        paragraphs = re.split(r'\n\s*\n', text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _classify_paragraph(self, para):
        """Classify a paragraph into shot type with production metadata."""
        para_lower = para.lower()

        # Check if dialogue
        if para.startswith('—') or para.startswith('"') or ':' in para[:50]:
            return self._parse_dialogue(para)

        # Check if sound direction
        if 'sound:' in para_lower or 'glitch sound' in para_lower:
            return self._parse_sound_direction(para)

        # Check if easter egg (reversed text)
        if self._is_reversed_text(para):
            return {
                "type": "easter_egg",
                "text": para,
                "decoded": para[::-1],
                "production_note": "Hidden message — subtle visual glitch overlay",
            }

        # Visual/narrative paragraph — the core of the immersive book
        return self._parse_visual_narrative(para)

    def _parse_dialogue(self, para):
        """Parse dialogue into speaker + line."""
        # Pattern: "Name (emotion):" or "— Name:" or "Name:"
        speaker = "unknown"
        emotion = "neutral"
        line = para

        # Try to extract speaker
        match = re.match(r'(?:—\s*)?["\']?(\w+)\s*(?:\(([^)]+)\))?\s*:', para)
        if match:
            speaker = match.group(1).lower()
            emotion = match.group(2) if match.group(2) else "neutral"
            line = para[match.end():].strip().strip('"').strip("'")

        return {
            "type": "dialogue",
            "speaker": speaker,
            "emotion": emotion,
            "line": line,
            "text": para,
            "production": {
                "audio": "tts",  # Piper TTS or voice clone
                "lip_sync": True if speaker != "puzzi" else False,
                "camera": "close_up",
                "expression_frame": f"{emotion}*.png",  # Match from frames/
            }
        }

    def _parse_sound_direction(self, para):
        """Parse explicit sound direction."""
        return {
            "type": "sound_direction",
            "text": para,
            "production": {
                "audio": "mmaudio",  # Generate with MMAudio
                "description": para,
            }
        }

    def _parse_visual_narrative(self, para):
        """Parse a visual/narrative paragraph — the heart of the immersive book."""
        para_lower = para.lower()

        # Detect sensory layers
        visuals = [k for k in self.VISUAL_KEYS if k in para_lower]
        sounds = [k for k in self.SOUND_KEYS if k in para_lower]
        smells = [k for k in self.SMELL_KEYS if k in para_lower]
        emotions = [k for k in self.EMOTION_KEYS if k in para_lower]

        # Determine camera movement
        camera = self._suggest_camera(para_lower)

        # Determine motion intensity
        motion = "low"
        if any(w in para_lower for w in ['run', 'chase', 'flash', 'explode', 'burst', 'rush']):
            motion = "high"
        elif any(w in para_lower for w in ['walk', 'move', 'approach', 'flicker', 'sway']):
            motion = "medium"

        # Build Wan2GP prompt from the paragraph
        wan_prompt = self._build_wan_prompt(para, visuals, sounds, emotions)

        return {
            "type": "visual_narrative",
            "text": para,
            "sensory": {
                "visual": visuals,
                "sound": sounds,
                "smell": smells,
                "emotion": emotions,
            },
            "production": {
                "wan_prompt": wan_prompt,
                "camera": camera,
                "motion": motion,
                "duration_s": max(3, min(10, len(para.split()) // 15)),  # ~15 words per second
                "audio_ambient": self._suggest_ambient(sounds, smells),
            }
        }

    def _suggest_camera(self, text):
        """Suggest camera movement based on text content."""
        for cam_type, keywords in self.CAMERA_MAP.items():
            if any(k in text for k in keywords):
                return cam_type
        return "medium"

    def _build_wan_prompt(self, para, visuals, sounds, emotions):
        """Convert immersive paragraph to Wan2GP-compatible prompt."""
        # Start with the visual description, cleaned for AI prompt
        prompt = para

        # Remove dialogue markers and clean
        prompt = re.sub(r'—\s*"[^"]*"', '', prompt)
        prompt = re.sub(r'\[\]', '', prompt)
        prompt = prompt.strip()

        # Add cinematic qualifiers
        if any(e in emotions for e in ['fear', 'dread', 'tension']):
            prompt += ", dark moody atmosphere, dramatic lighting"
        elif any(e in emotions for e in ['warm', 'courage']):
            prompt += ", warm golden lighting, hopeful atmosphere"

        prompt += ", cinematic, high quality, detailed"

        return prompt

    def _suggest_ambient(self, sounds, smells):
        """Suggest ambient audio based on sensory keywords."""
        ambient = []
        if 'rain' in sounds or 'rain' in smells:
            ambient.append("rain")
        if 'thunder' in sounds:
            ambient.append("thunder")
        if 'static' in sounds or 'glitch' in sounds:
            ambient.append("digital_glitch")
        if 'echo' in sounds:
            ambient.append("reverb_hall")
        if 'silence' in sounds:
            ambient.append("silence_tension")
        if 'footstep' in sounds:
            ambient.append("footsteps")
        if 'coffee' in smells:
            ambient.append("kitchen_ambient")
        return ambient if ambient else ["ambient_subtle"]

    def _is_reversed_text(self, para):
        """Check if paragraph is reversed text (easter egg)."""
        words = para.strip().split()
        if len(words) <= 5 and all(len(w) < 20 for w in words):
            reversed_text = ' '.join(w[::-1] for w in words)
            # Check if reversed makes more sense (has common English words)
            common = ['the', 'what', 'is', 'of', 'to', 'a', 'i', 'become', 'someone', 'memory']
            if any(w.lower() in common for w in reversed_text.split()):
                return True
        return False


class ProductionBuilder:
    """Builds production-ready output from extracted scenes."""

    def __init__(self, episode_name, output_dir):
        self.episode_name = episode_name
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def build(self, scenes):
        """Build production package from scenes."""
        production = {
            "episode": self.episode_name,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_scenes": len(scenes),
            "total_shots": sum(len(s["shots"]) for s in scenes),
            "estimated_duration_s": 0,
            "scenes": [],
            "wan_queue": [],  # Ready for Wan2GP batch processing
            "audio_cues": [],
            "narration_segments": [],
        }

        shot_index = 0
        for scene in scenes:
            scene_data = {
                "scene_id": scene["scene_id"],
                "location": scene["location"],
                "year": scene["year"],
                "shots": [],
            }

            for shot in scene["shots"]:
                shot_data = {
                    "shot_index": shot_index,
                    **shot,
                }
                scene_data["shots"].append(shot_data)

                # Add to Wan2GP queue if visual
                if shot["type"] == "visual_narrative":
                    prod = shot["production"]
                    production["wan_queue"].append({
                        "shot_index": shot_index,
                        "prompt": prod["wan_prompt"],
                        "camera": prod["camera"],
                        "motion": prod["motion"],
                        "duration_s": prod["duration_s"],
                    })
                    production["estimated_duration_s"] += prod["duration_s"]

                    # Audio cues
                    for ambient in prod.get("audio_ambient", []):
                        production["audio_cues"].append({
                            "shot_index": shot_index,
                            "type": ambient,
                        })

                elif shot["type"] == "dialogue":
                    prod = shot["production"]
                    production["narration_segments"].append({
                        "shot_index": shot_index,
                        "speaker": shot["speaker"],
                        "emotion": shot["emotion"],
                        "line": shot["line"],
                        "tts_engine": "piper" if shot["speaker"] != "puzzi" else "chatterbox",
                    })
                    production["estimated_duration_s"] += max(2, len(shot["line"].split()) // 3)

                elif shot["type"] == "sound_direction":
                    production["audio_cues"].append({
                        "shot_index": shot_index,
                        "type": "custom",
                        "description": shot["text"],
                    })

                shot_index += 1

            production["scenes"].append(scene_data)

        return production

    def save(self, production):
        """Save production package."""
        # Main production JSON
        prod_path = os.path.join(self.output_dir, f"{self.episode_name}_production.json")
        with open(prod_path, 'w') as f:
            json.dump(production, f, indent=2, ensure_ascii=False)
        log(f"Production saved: {prod_path}")

        # Wan2GP queue (for batch processing)
        queue_path = os.path.join(self.output_dir, f"{self.episode_name}_wan_queue.json")
        with open(queue_path, 'w') as f:
            json.dump(production["wan_queue"], f, indent=2, ensure_ascii=False)
        log(f"Wan2GP queue saved: {queue_path}")

        # Narration script (for TTS)
        narration_path = os.path.join(self.output_dir, f"{self.episode_name}_narration.json")
        with open(narration_path, 'w') as f:
            json.dump(production["narration_segments"], f, indent=2, ensure_ascii=False)
        log(f"Narration script saved: {narration_path}")

        # Summary
        log(f"")
        log(f"=== PRODUCTION SUMMARY: {self.episode_name} ===")
        log(f"Scenes: {production['total_scenes']}")
        log(f"Shots: {production['total_shots']}")
        log(f"Wan2GP prompts: {len(production['wan_queue'])}")
        log(f"Narration segments: {len(production['narration_segments'])}")
        log(f"Audio cues: {len(production['audio_cues'])}")
        log(f"Estimated duration: {production['estimated_duration_s']}s ({production['estimated_duration_s']//60}m{production['estimated_duration_s']%60}s)")
        log(f"Output: {self.output_dir}")

        return prod_path


def run(episode_path, output_dir=None):
    """Run the book-to-video pipeline."""
    if not os.path.exists(episode_path):
        raise FileNotFoundError(f"Episode not found: {episode_path}")

    # Read episode text
    if episode_path.endswith('.docx'):
        try:
            from docx import Document
            doc = Document(episode_path)
            text = '\n\n'.join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError("python-docx required for .docx files")
    else:
        with open(episode_path) as f:
            text = f.read()

    episode_name = Path(episode_path).stem
    if not output_dir:
        output_dir = os.path.join(OUTPUT_BASE, episode_name)

    log(f"Episode: {episode_name}")
    log(f"Source: {episode_path}")
    log(f"Text length: {len(text)} chars, {len(text.split())} words")

    # Extract scenes
    extractor = SceneExtractor()
    scenes = extractor.extract(text)
    log(f"Extracted {len(scenes)} scenes")

    # Build production
    builder = ProductionBuilder(episode_name, output_dir)
    production = builder.build(scenes)
    prod_path = builder.save(production)

    # Output result
    result = {
        "ok": True,
        "episode": episode_name,
        "production_file": prod_path,
        "scenes": production["total_scenes"],
        "shots": production["total_shots"],
        "wan_prompts": len(production["wan_queue"]),
        "narration_segments": len(production["narration_segments"]),
        "estimated_duration_s": production["estimated_duration_s"],
    }
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: pipeline_book_to_video.py <episode.txt|.docx> [--output /path/]")
        print("")
        print("Reads immersive book text and extracts production scenes.")
        print("The book IS the script — no intermediate screenplay needed.")
        sys.exit(0)

    episode_path = sys.argv[1]
    output_dir = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        output_dir = sys.argv[idx + 1]

    run(episode_path, output_dir)
