"""Tiny Hugging Face models built on the spot, for trainer tests.

Nothing here downloads. A word-level fast tokenizer is built from the test's
own sentences, and a two-layer model with a 32-wide hidden state is
initialized from a config and saved to a directory, which a trainer then
loads by path exactly as it would load a hub id. Fitting one takes a second
or two on a CPU.

The tokenizer is a *fast* tokenizer because span training needs its offset
mapping.
"""

import os
from typing import Iterable

SPECIAL = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "<eos>"]


def build_tokenizer(texts: Iterable[str]):
    from tokenizers import Tokenizer, models, pre_tokenizers, processors
    from transformers import PreTrainedTokenizerFast

    vocab = {token: i for i, token in enumerate(SPECIAL)}
    for text in texts:
        for word in pre_tokenizers.BertPreTokenizer().pre_tokenize_str(text):
            vocab.setdefault(word[0].lower(), len(vocab))
    tok = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    from tokenizers import normalizers
    tok.normalizer = normalizers.Lowercase()
    tok.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tok.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", pair="[CLS] $A [SEP] $B [SEP]",
        special_tokens=[("[CLS]", vocab["[CLS]"]), ("[SEP]", vocab["[SEP]"])])
    return PreTrainedTokenizerFast(
        tokenizer_object=tok, unk_token="[UNK]", pad_token="[PAD]",
        cls_token="[CLS]", sep_token="[SEP]", mask_token="[MASK]")


def tiny_encoder(directory: str, texts: Iterable[str]) -> str:
    """A two-layer BERT with a word-level tokenizer, saved to *directory*."""
    from transformers import BertConfig, BertModel

    tokenizer = build_tokenizer(texts)
    config = BertConfig(vocab_size=len(tokenizer), hidden_size=32,
                        num_hidden_layers=2, num_attention_heads=2,
                        intermediate_size=64, max_position_embeddings=128)
    os.makedirs(directory, exist_ok=True)
    BertModel(config).save_pretrained(directory)
    tokenizer.save_pretrained(directory)
    return directory


def tiny_causal_lm(directory: str, texts: Iterable[str]) -> str:
    """A two-layer GPT-2 with a word-level tokenizer, saved to *directory*."""
    from transformers import GPT2Config, GPT2LMHeadModel

    tokenizer = build_tokenizer(texts)
    tokenizer.eos_token = "<eos>"
    tokenizer.bos_token = "<eos>"
    config = GPT2Config(vocab_size=len(tokenizer), n_embd=32, n_layer=2,
                        n_head=2, n_positions=256,
                        bos_token_id=tokenizer.eos_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                        pad_token_id=tokenizer.pad_token_id)
    os.makedirs(directory, exist_ok=True)
    GPT2LMHeadModel(config).save_pretrained(directory)
    tokenizer.save_pretrained(directory)
    return directory


def tiny_vit(directory: str, image_size: int = 32) -> str:
    """A two-layer ViT over 32-pixel images, with its image processor."""
    from transformers import ViTConfig, ViTImageProcessor, ViTModel

    config = ViTConfig(image_size=image_size, patch_size=8, hidden_size=32,
                       num_hidden_layers=2, num_attention_heads=2,
                       intermediate_size=64)
    os.makedirs(directory, exist_ok=True)
    ViTModel(config).save_pretrained(directory)
    ViTImageProcessor(size={"height": image_size, "width": image_size}
                      ).save_pretrained(directory)
    return directory


def colour_images(directory: str, n: int, seed: int = 0):
    """*n* small PNGs, alternately reddish and bluish, with their labels."""
    import random

    from PIL import Image

    rng = random.Random(seed)
    os.makedirs(directory, exist_ok=True)
    out = []
    for i in range(n):
        label = "red" if i % 2 == 0 else "blue"
        base = (200, 40, 40) if label == "red" else (40, 40, 200)
        colour = tuple(max(0, min(255, c + rng.randint(-30, 30))) for c in base)
        path = os.path.join(directory, "img%03d.png" % i)
        Image.new("RGB", (40, 40), colour).save(path)
        out.append((path, label))
    return out


def tiny_wav2vec2(directory: str) -> str:
    """A one-layer wav2vec 2.0 with an 80-sample frame hop, at 16 kHz."""
    from transformers import (Wav2Vec2Config, Wav2Vec2FeatureExtractor,
                              Wav2Vec2Model)

    config = Wav2Vec2Config(
        hidden_size=32, num_hidden_layers=1, num_attention_heads=2,
        intermediate_size=64, conv_dim=(16, 16, 16), conv_stride=(5, 4, 4),
        conv_kernel=(10, 4, 4), num_conv_pos_embeddings=16,
        num_conv_pos_embedding_groups=2, feat_extract_norm="group",
        do_stable_layer_norm=False, mask_time_prob=0.0)
    os.makedirs(directory, exist_ok=True)
    Wav2Vec2Model(config).save_pretrained(directory)
    Wav2Vec2FeatureExtractor(sampling_rate=16000, do_normalize=True,
                             return_attention_mask=False
                             ).save_pretrained(directory)
    return directory


def beep_recordings(directory: str, n: int, seconds: float = 2.0,
                    rate: int = 16000, seed: int = 0):
    """*n* WAV files of quiet noise with one or two 1 kHz beeps each.

    Returns ``[(path, [{"start_time", "end_time", "label"}])]``.
    """
    import random

    import numpy
    import soundfile

    rng = random.Random(seed)
    noise = numpy.random.default_rng(seed)
    os.makedirs(directory, exist_ok=True)
    out = []
    for i in range(n):
        samples = noise.normal(0, 0.01, int(seconds * rate)).astype("float32")
        segments = []
        for _ in range(rng.randint(1, 2)):
            length = rng.uniform(0.2, 0.5)
            start = rng.uniform(0, seconds - length)
            if any(start < s["end_time"] and start + length > s["start_time"]
                   for s in segments):
                continue
            a, b = int(start * rate), int((start + length) * rate)
            t = numpy.arange(b - a) / rate
            samples[a:b] += 0.5 * numpy.sin(2 * numpy.pi * 1000 * t)
            segments.append({"start_time": round(start, 3),
                             "end_time": round(start + length, 3),
                             "label": "beep"})
        path = os.path.join(directory, "rec%03d.wav" % i)
        soundfile.write(path, samples, rate)
        out.append((path, segments))
    return out
