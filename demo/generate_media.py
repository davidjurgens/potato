#!/usr/bin/env python3
"""
Generate placeholder media files for the potato demo.

Creates:
  - 5 JPEG images (100x100 solid color)
  - 4 WAV audio files (1-second sine wave tones)
  - 3 MP4 video files (2-second solid color, requires ffmpeg)

Uses only stdlib where possible (struct, wave, math).
Uses PIL/Pillow for images if available, otherwise falls back to raw JPEG construction.
"""

import os
import sys
import math
import wave
import struct
import shutil
import subprocess

MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")


# ---------------------------------------------------------------------------
# 1. JPEG Images
# ---------------------------------------------------------------------------

def generate_images_pillow():
    """Generate JPEG images using PIL/Pillow."""
    from PIL import Image

    images = [
        ("image_01.jpg", (34, 139, 34)),     # green - mountain/landscape
        ("image_02.jpg", (128, 128, 128)),    # gray - city/urban
        ("image_03.jpg", (30, 100, 200)),     # blue - underwater
        ("image_04.jpg", (222, 198, 160)),    # beige - portrait
        ("image_05.jpg", (255, 140, 0)),      # orange - food
    ]

    for filename, color in images:
        path = os.path.join(MEDIA_DIR, filename)
        img = Image.new("RGB", (100, 100), color)
        img.save(path, "JPEG", quality=85)
        size = os.path.getsize(path)
        print(f"  Created {filename} ({size} bytes) - RGB{color}")


def _build_minimal_jpeg(width, height, r, g, b):
    """
    Build a minimal valid JPEG file in memory for a solid-color image.
    Constructs a baseline JPEG with standard Huffman tables.
    """
    import io
    buf = io.BytesIO()

    def write_u8(v):
        buf.write(struct.pack("B", v))

    def write_u16be(v):
        buf.write(struct.pack(">H", v))

    # Convert RGB to YCbCr
    Y  = int( 0.299 * r + 0.587 * g + 0.114 * b)
    Cb = int(-0.1687 * r - 0.3313 * g + 0.5 * b + 128)
    Cr = int( 0.5 * r - 0.4187 * g - 0.0813 * b + 128)
    Y  = max(0, min(255, Y))
    Cb = max(0, min(255, Cb))
    Cr = max(0, min(255, Cr))

    # SOI
    buf.write(b'\xff\xd8')

    # APP0 (JFIF header)
    buf.write(b'\xff\xe0')
    write_u16be(16)
    buf.write(b'JFIF\x00')
    write_u8(1); write_u8(1)
    write_u8(0)
    write_u16be(1); write_u16be(1)
    write_u8(0); write_u8(0)

    # DQT - Quantization tables (all 1s for best quality)
    for table_id in range(2):
        buf.write(b'\xff\xdb')
        write_u16be(67)
        write_u8(table_id)
        for _ in range(64):
            write_u8(1)

    # SOF0 - Start of Frame
    buf.write(b'\xff\xc0')
    write_u16be(17)
    write_u8(8)
    write_u16be(height)
    write_u16be(width)
    write_u8(3)
    write_u8(1); write_u8(0x11); write_u8(0)  # Y
    write_u8(2); write_u8(0x11); write_u8(1)  # Cb
    write_u8(3); write_u8(0x11); write_u8(1)  # Cr

    # Standard JPEG Huffman tables (Annex K)
    dc_lum_bits = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    dc_lum_vals = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    dc_chr_bits = [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    dc_chr_vals = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    ac_lum_bits = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d]
    ac_lum_vals = [
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12,
        0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
        0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08,
        0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
        0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16,
        0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
        0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
        0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
        0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
        0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98,
        0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
        0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6,
        0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
        0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4,
        0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
        0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea,
        0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
        0xf9, 0xfa,
    ]

    ac_chr_bits = [0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77]
    ac_chr_vals = [
        0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21,
        0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
        0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91,
        0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0,
        0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34,
        0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26,
        0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38,
        0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
        0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
        0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
        0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78,
        0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
        0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96,
        0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5,
        0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4,
        0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
        0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2,
        0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
        0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9,
        0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
        0xf9, 0xfa,
    ]

    def write_dht(table_class, table_id, bits, vals):
        buf.write(b'\xff\xc4')
        length = 2 + 1 + 16 + len(vals)
        write_u16be(length)
        write_u8((table_class << 4) | table_id)
        for b in bits:
            write_u8(b)
        for v in vals:
            write_u8(v)

    write_dht(0, 0, dc_lum_bits, dc_lum_vals)
    write_dht(1, 0, ac_lum_bits, ac_lum_vals)
    write_dht(0, 1, dc_chr_bits, dc_chr_vals)
    write_dht(1, 1, ac_chr_bits, ac_chr_vals)

    # Build Huffman code lookup tables
    def build_huffman_codes(bits_list, vals):
        codes = {}
        code = 0
        val_idx = 0
        for length_minus_1, count in enumerate(bits_list):
            length = length_minus_1 + 1
            for _ in range(count):
                codes[vals[val_idx]] = (code, length)
                code += 1
                val_idx += 1
            code <<= 1
        return codes

    dc_lum_codes = build_huffman_codes(dc_lum_bits, dc_lum_vals)
    ac_lum_codes = build_huffman_codes(ac_lum_bits, ac_lum_vals)
    dc_chr_codes = build_huffman_codes(dc_chr_bits, dc_chr_vals)
    ac_chr_codes = build_huffman_codes(ac_chr_bits, ac_chr_vals)

    # SOS - Start of Scan
    buf.write(b'\xff\xda')
    write_u16be(12)
    write_u8(3)
    write_u8(1); write_u8(0x00)  # Y:  DC table 0, AC table 0
    write_u8(2); write_u8(0x11)  # Cb: DC table 1, AC table 1
    write_u8(3); write_u8(0x11)  # Cr: DC table 1, AC table 1
    write_u8(0); write_u8(63); write_u8(0)

    # For solid color: DC = 8 * (pixel_value - 128), all AC = 0
    dc_y  = 8 * (Y - 128)
    dc_cb = 8 * (Cb - 128)
    dc_cr = 8 * (Cr - 128)

    blocks_h = (width + 7) // 8
    blocks_v = (height + 7) // 8

    class BitWriter:
        def __init__(self):
            self.data = bytearray()
            self.current_byte = 0
            self.bit_pos = 7

        def write_bits(self, value, num_bits):
            for i in range(num_bits - 1, -1, -1):
                bit = (value >> i) & 1
                self.current_byte |= (bit << self.bit_pos)
                self.bit_pos -= 1
                if self.bit_pos < 0:
                    self.data.append(self.current_byte)
                    if self.current_byte == 0xFF:
                        self.data.append(0x00)  # byte stuffing
                    self.current_byte = 0
                    self.bit_pos = 7

        def flush(self):
            if self.bit_pos < 7:
                self.current_byte |= (1 << (self.bit_pos + 1)) - 1
                self.data.append(self.current_byte)
                if self.current_byte == 0xFF:
                    self.data.append(0x00)
                self.current_byte = 0
                self.bit_pos = 7

    def encode_dc(bw, dc_val, prev_dc, huff_codes):
        diff = dc_val - prev_dc
        if diff == 0:
            category = 0
        elif diff > 0:
            category = diff.bit_length()
        else:
            category = (-diff).bit_length()

        code, length = huff_codes[category]
        bw.write_bits(code, length)

        if category > 0:
            if diff > 0:
                bw.write_bits(diff, category)
            else:
                bw.write_bits(diff + (1 << category) - 1, category)

        return dc_val

    def encode_ac_eob(bw, huff_codes):
        code, length = huff_codes[0x00]
        bw.write_bits(code, length)

    bw = BitWriter()
    prev_dc_y = 0
    prev_dc_cb = 0
    prev_dc_cr = 0

    for _row in range(blocks_v):
        for _col in range(blocks_h):
            prev_dc_y = encode_dc(bw, dc_y, prev_dc_y, dc_lum_codes)
            encode_ac_eob(bw, ac_lum_codes)
            prev_dc_cb = encode_dc(bw, dc_cb, prev_dc_cb, dc_chr_codes)
            encode_ac_eob(bw, ac_chr_codes)
            prev_dc_cr = encode_dc(bw, dc_cr, prev_dc_cr, dc_chr_codes)
            encode_ac_eob(bw, ac_chr_codes)

    bw.flush()
    buf.write(bytes(bw.data))

    # EOI
    buf.write(b'\xff\xd9')

    return buf.getvalue()


def generate_images_stdlib():
    """Generate JPEG images using only stdlib (raw JPEG construction)."""
    images = [
        ("image_01.jpg", (34, 139, 34)),
        ("image_02.jpg", (128, 128, 128)),
        ("image_03.jpg", (30, 100, 200)),
        ("image_04.jpg", (222, 198, 160)),
        ("image_05.jpg", (255, 140, 0)),
    ]

    for filename, (r, g, b) in images:
        path = os.path.join(MEDIA_DIR, filename)
        jpeg_data = _build_minimal_jpeg(100, 100, r, g, b)
        with open(path, 'wb') as f:
            f.write(jpeg_data)
        size = os.path.getsize(path)
        print(f"  Created {filename} ({size} bytes) - RGB({r},{g},{b}) [stdlib JPEG]")


def generate_images():
    """Generate JPEG images, preferring Pillow if available."""
    try:
        import PIL
        print("Using Pillow for JPEG generation.")
        generate_images_pillow()
    except ImportError:
        print("Pillow not available; constructing JPEGs from raw bytes.")
        generate_images_stdlib()


# ---------------------------------------------------------------------------
# 2. WAV Audio Files
# ---------------------------------------------------------------------------

def generate_audio():
    """Generate WAV audio files with sine wave tones using stdlib wave module."""
    tones = [
        ("audio_01.wav", 440, "A4"),
        ("audio_02.wav", 523, "C5"),
        ("audio_03.wav", 659, "E5"),
        ("audio_04.wav", 349, "F4"),
    ]

    sample_rate = 44100
    duration = 1.0
    amplitude = 16000
    num_samples = int(sample_rate * duration)

    for filename, freq, note_name in tones:
        path = os.path.join(MEDIA_DIR, filename)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)

            frames = bytearray()
            for i in range(num_samples):
                t = i / sample_rate
                sample = int(amplitude * math.sin(2 * math.pi * freq * t))
                frames.extend(struct.pack('<h', sample))

            wf.writeframes(bytes(frames))

        size = os.path.getsize(path)
        print(f"  Created {filename} ({size} bytes) - {freq}Hz sine wave ({note_name})")


# ---------------------------------------------------------------------------
# 3. MP4 Video Files
# ---------------------------------------------------------------------------

def generate_videos():
    """Generate MP4 video files using ffmpeg if available."""
    ffmpeg_path = shutil.which("ffmpeg")

    videos = [
        ("video_01.mp4", "0x228B22", "green"),
        ("video_02.mp4", "0x4682B4", "steel blue"),
        ("video_03.mp4", "0xCD853F", "peru/tan"),
    ]

    if ffmpeg_path:
        print(f"Using ffmpeg at: {ffmpeg_path}")
        for filename, hex_color, desc in videos:
            path = os.path.join(MEDIA_DIR, filename)
            cmd = [
                ffmpeg_path,
                "-y",
                "-f", "lavfi",
                "-i", f"color=c={hex_color}:size=320x240:duration=2:rate=24",
                "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=mono",
                "-t", "2",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-shortest",
                "-movflags", "+faststart",
                path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                size = os.path.getsize(path)
                print(f"  Created {filename} ({size} bytes) - 2s {desc} video")
            else:
                print(f"  ERROR creating {filename}: {result.stderr[:300]}")
    else:
        print("NOTE: ffmpeg not found. Creating minimal MP4 placeholder files.")
        print("      These placeholders are valid MP4 containers but not playable.")
        print("      Install ffmpeg for proper MP4 generation:")
        print("        macOS:  brew install ffmpeg")
        print("        Ubuntu: sudo apt install ffmpeg")
        print()

        for filename, hex_color, desc in videos:
            path = os.path.join(MEDIA_DIR, filename)
            mp4_data = _build_minimal_mp4()
            with open(path, 'wb') as f:
                f.write(mp4_data)
            size = os.path.getsize(path)
            print(f"  Created {filename} ({size} bytes) - minimal MP4 placeholder ({desc})")


def _build_minimal_mp4():
    """Build a minimal valid MP4 file (ftyp + free box). Not playable but valid container."""
    import io
    buf = io.BytesIO()

    def write_box(box_type, data=b''):
        size = 8 + len(data)
        buf.write(struct.pack('>I', size))
        buf.write(box_type)
        buf.write(data)

    # ftyp box
    ftyp_data = b'isom'
    ftyp_data += struct.pack('>I', 0)
    ftyp_data += b'isom'
    ftyp_data += b'mp41'
    write_box(b'ftyp', ftyp_data)

    # free box (padding)
    write_box(b'free', b'\x00' * 8)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    print(f"Generating media files in: {MEDIA_DIR}\n")

    print("=== JPEG Images (100x100) ===")
    generate_images()
    print()

    print("=== WAV Audio Files (1 second, 44100Hz, mono) ===")
    generate_audio()
    print()

    print("=== MP4 Video Files (2 seconds, 320x240) ===")
    generate_videos()
    print()

    print("Done! All media files generated.")


if __name__ == "__main__":
    main()
