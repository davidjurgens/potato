# Run from the repo root: python examples/advanced/codebook-lab-naacl-frames/generate.py
"""Generate codebook variants with the experiment's generation_model and
save them to run/variants/ (skips any variant file that already exists)."""
import os, sys, yaml
sys.path.insert(0, os.getcwd())
from potato.codebook_lab import io_utils
from potato.codebook_lab.endpoints import build_endpoint
from potato.codebook_lab.variant_generator import DIRECTIVES, generate_variant

d = "examples/advanced/codebook-lab-naacl-frames"
cfg = yaml.safe_load(open(f"{d}/experiment.yaml"))
seed = io_utils.load_seed_codebook(f"{d}/seed_codebook.yaml")
out = f"{d}/{cfg['output_dir']}"
ep = build_endpoint(cfg["generation_model"])

# OllamaEndpoint doesn't pass num_ctx, and Ollama's 4096 default would
# silently cut the seed-codebook prompt plus a full 14-label JSON reply.
num_ctx = cfg["generation_model"].get("num_ctx")
if num_ctx:
    _chat = ep.client.chat
    ep.client.chat = lambda *a, options=None, **k: _chat(
        *a, options={**(options or {}), "num_ctx": num_ctx}, **k)

for i in range(int(cfg["num_variants"])):
    directive = DIRECTIVES[i % len(DIRECTIVES)]
    vid = f"v{i + 1:02d}_{directive['key']}"
    if os.path.exists(f"{out}/variants/{vid}.json"):
        continue
    for attempt in range(2):
        try:
            io_utils.save_variant(out, generate_variant(ep, seed, vid, directive))
            print(f"saved {vid}", flush=True)
            break
        except Exception as e:
            print(f"{vid} attempt {attempt + 1} failed: {e}", flush=True)
