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


def _seed() -> None:
    """Random weights from a fixed seed. Unseeded, each run of a test drew
    different starting weights, and a model trained on 80 items scored
    0.73 to 1.0 on the same data."""
    import torch
    torch.manual_seed(0)


def tiny_encoder(directory: str, texts: Iterable[str]) -> str:
    """A two-layer BERT with a word-level tokenizer, saved to *directory*."""
    _seed()
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
    _seed()
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
    _seed()
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
    _seed()
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


def tiny_byt5(directory: str) -> str:
    """A two-layer T5 with ByT5's byte vocabulary (384 ids), saved to
    *directory*. ByT5's tokenizer needs no vocabulary file."""
    _seed()
    from transformers import ByT5Tokenizer, T5Config, T5ForConditionalGeneration

    config = T5Config(vocab_size=384, d_model=64, d_ff=128, d_kv=16, num_layers=2,
                      num_decoder_layers=2, num_heads=4, decoder_start_token_id=0,
                      pad_token_id=0, eos_token_id=1, dropout_rate=0.0)
    os.makedirs(directory, exist_ok=True)
    T5ForConditionalGeneration(config).save_pretrained(directory)
    ByT5Tokenizer().save_pretrained(directory)
    return directory


def tiny_sam(directory: str, image_size: int = 64) -> str:
    """A two-layer SAM whose processor resizes to *image_size*, saved to
    *directory*. The real checkpoints work at 1024; the trainer reads every
    size from the processor, so a small one exercises the same code."""
    _seed()
    from transformers import SamConfig, SamImageProcessor, SamModel, SamProcessor
    from transformers.models.sam.configuration_sam import (
        SamMaskDecoderConfig, SamPromptEncoderConfig, SamVisionConfig)

    vision = SamVisionConfig(hidden_size=32, num_hidden_layers=2, num_attention_heads=2,
                             image_size=image_size, patch_size=8, output_channels=32,
                             mlp_dim=64, global_attn_indexes=[1], window_size=4,
                             num_pos_feats=16)
    prompt = SamPromptEncoderConfig(hidden_size=32, image_size=image_size, patch_size=8,
                                    mask_input_channels=4)
    decoder = SamMaskDecoderConfig(hidden_size=32, num_hidden_layers=2,
                                   num_attention_heads=2, mlp_dim=64,
                                   iou_head_hidden_dim=32)
    config = SamConfig(vision_config=vision.to_dict(), prompt_encoder_config=prompt.to_dict(),
                       mask_decoder_config=decoder.to_dict())
    os.makedirs(directory, exist_ok=True)
    SamModel(config).save_pretrained(directory)
    low = image_size // 4
    SamProcessor(image_processor=SamImageProcessor(
        size={"longest_edge": image_size},
        pad_size={"height": image_size, "width": image_size},
        mask_size={"longest_edge": low},
        mask_pad_size={"height": low, "width": low})).save_pretrained(directory)
    return directory


def tiny_layoutlmv3(directory: str, texts: Iterable[str], image_size: int = 32) -> str:
    """A two-layer LayoutLMv3 with a byte-level BPE tokenizer trained on
    *texts*, and a processor that runs no OCR, saved to *directory*."""
    _seed()
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, processors, trainers
    from transformers import (LayoutLMv3Config, LayoutLMv3ForTokenClassification,
                              LayoutLMv3ImageProcessor, LayoutLMv3Processor,
                              LayoutLMv3TokenizerFast)

    specials = ["<s>", "<pad>", "</s>", "<unk>", "<mask>"]
    tok = Tokenizer(models.BPE(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=True)
    tok.decoder = decoders.ByteLevel()
    tok.train_from_iterator(list(texts) * 3, trainers.BpeTrainer(
        vocab_size=400, special_tokens=specials,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    tok.post_processor = processors.RobertaProcessing(
        ("</s>", tok.token_to_id("</s>")), ("<s>", tok.token_to_id("<s>")))
    tokenizer = LayoutLMv3TokenizerFast(
        tokenizer_object=tok, bos_token="<s>", eos_token="</s>", sep_token="</s>",
        cls_token="<s>", unk_token="<unk>", pad_token="<pad>", mask_token="<mask>",
        add_prefix_space=True)
    processor = LayoutLMv3Processor(
        image_processor=LayoutLMv3ImageProcessor(
            apply_ocr=False, size={"height": image_size, "width": image_size}),
        tokenizer=tokenizer)
    # 4 * coordinate_size + 2 * shape_size must equal hidden_size.
    config = LayoutLMv3Config(
        vocab_size=tokenizer.vocab_size, hidden_size=32, num_hidden_layers=2,
        num_attention_heads=2, intermediate_size=64, input_size=image_size, patch_size=8,
        max_position_embeddings=130, max_2d_position_embeddings=1024,
        coordinate_size=4, shape_size=8, rel_pos_bins=8, max_rel_pos=16,
        rel_2d_pos_bins=8, max_rel_2d_pos=32, pad_token_id=tokenizer.pad_token_id)
    os.makedirs(directory, exist_ok=True)
    LayoutLMv3ForTokenClassification(config).save_pretrained(directory)
    processor.save_pretrained(directory)
    return directory


#: A plain chat template for the tiny VLM: "role: content" lines, the image
#: as its placeholder token.
_TINY_CHAT = ("{% for m in messages %}{{ m['role'] }}: {% if m['content'] is string %}"
              "{{ m['content'] }}{% else %}{% for c in m['content'] %}"
              "{% if c['type'] == 'image' %}<image>{% else %}{{ c['text'] }}{% endif %}"
              "{% endfor %}{% endif %} ; {% endfor %}"
              "{% if add_generation_prompt %}assistant: {% endif %}")


def tiny_vlm(directory: str, texts: Iterable[str], image_size: int = 32) -> str:
    """A two-layer LLaVA (a CLIP vision tower and a Llama) with a word-level
    tokenizer built from *texts*, saved to *directory*. Loads through
    AutoModelForImageTextToText and AutoProcessor, as a hub VLM does."""
    _seed()
    from transformers import (CLIPImageProcessor, CLIPVisionConfig, LlamaConfig,
                              LlavaConfig, LlavaForConditionalGeneration, LlavaProcessor)

    from tokenizers import processors
    tokenizer = build_tokenizer(list(texts) + ['{ } [ ] , : " 0 1 2 3 4 5 6 7 8 9 '
                                               'point bbox absent true'])
    # A chat model's prompt ends where the answer starts; BERT's [SEP] after
    # "assistant:" would be the last thing it saw before generating.
    tokenizer.backend_tokenizer.post_processor = processors.TemplateProcessing(
        single="$A", pair="$A $B")
    tokenizer.add_special_tokens({"additional_special_tokens": ["<image>"]})
    tokenizer.eos_token = "<eos>"
    tokenizer.chat_template = _TINY_CHAT
    vision = CLIPVisionConfig(hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                              num_attention_heads=2, image_size=image_size, patch_size=8,
                              projection_dim=32)
    text = LlamaConfig(vocab_size=len(tokenizer), hidden_size=32, intermediate_size=64,
                       num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=2,
                       max_position_embeddings=256, pad_token_id=tokenizer.pad_token_id,
                       eos_token_id=tokenizer.convert_tokens_to_ids("<eos>"))
    config = LlavaConfig(vision_config=vision.to_dict(), text_config=text.to_dict(),
                         image_token_index=tokenizer.convert_tokens_to_ids("<image>"),
                         vision_feature_select_strategy="default", vision_feature_layer=-1)
    os.makedirs(directory, exist_ok=True)
    LlavaForConditionalGeneration(config).save_pretrained(directory)
    LlavaProcessor(image_processor=CLIPImageProcessor(
        size={"shortest_edge": image_size},
        crop_size={"height": image_size, "width": image_size}),
        tokenizer=tokenizer, patch_size=8, vision_feature_select_strategy="default",
        image_token="<image>", chat_template=_TINY_CHAT,
        num_additional_image_tokens=1).save_pretrained(directory)
    return directory


_WHISPER_SPECIAL = ["<|startoftranscript|>", "<|en|>", "<|transcribe|>", "<|translate|>",
                    "<|startoflm|>", "<|startofprev|>", "<|nocaptions|>", "<|notimestamps|>"]


def tiny_whisper(directory: str, texts: Iterable[str]) -> str:
    """A one-layer Whisper on 16 mel bins, with a byte-level BPE tokenizer
    trained on *texts* and Whisper's own special tokens, saved to
    *directory*. Loads through AutoProcessor as a WhisperProcessor, and its
    labels are ``<|startoftranscript|><|notimestamps|> text <|endoftext|>``
    as a hub Whisper's are."""
    _seed()
    from tokenizers import ByteLevelBPETokenizer
    from transformers import (GenerationConfig, WhisperConfig, WhisperFeatureExtractor,
                              WhisperForConditionalGeneration, WhisperProcessor,
                              WhisperTokenizer)

    os.makedirs(directory, exist_ok=True)
    bpe = ByteLevelBPETokenizer()
    bpe.train_from_iterator(list(texts), vocab_size=400, min_frequency=1,
                            special_tokens=["<|endoftext|>"])
    bpe.save_model(directory)
    tokenizer = WhisperTokenizer(
        os.path.join(directory, "vocab.json"), os.path.join(directory, "merges.txt"),
        unk_token="<|endoftext|>", bos_token="<|endoftext|>", eos_token="<|endoftext|>",
        pad_token="<|endoftext|>")
    tokenizer.add_special_tokens({"additional_special_tokens": _WHISPER_SPECIAL})
    eot = tokenizer.convert_tokens_to_ids("<|endoftext|>")
    start = tokenizer.convert_tokens_to_ids("<|startoftranscript|>")
    config = WhisperConfig(
        vocab_size=len(tokenizer), num_mel_bins=16, d_model=32, encoder_layers=1,
        decoder_layers=1, encoder_attention_heads=2, decoder_attention_heads=2,
        encoder_ffn_dim=64, decoder_ffn_dim=64, max_source_positions=1500,
        max_target_positions=448, pad_token_id=eot, bos_token_id=eot, eos_token_id=eot,
        decoder_start_token_id=start)
    model = WhisperForConditionalGeneration(config)
    model.generation_config = GenerationConfig(
        decoder_start_token_id=start, eos_token_id=eot, pad_token_id=eot,
        no_timestamps_token_id=tokenizer.convert_tokens_to_ids("<|notimestamps|>"),
        is_multilingual=True, max_length=64, suppress_tokens=[], begin_suppress_tokens=[],
        # As a hub Whisper's has them; the CTranslate2 converter reads them.
        lang_to_id={"<|en|>": tokenizer.convert_tokens_to_ids("<|en|>")},
        task_to_id={"transcribe": tokenizer.convert_tokens_to_ids("<|transcribe|>"),
                    "translate": tokenizer.convert_tokens_to_ids("<|translate|>")})
    model.save_pretrained(directory)
    WhisperProcessor(feature_extractor=WhisperFeatureExtractor(feature_size=16),
                     tokenizer=tokenizer).save_pretrained(directory)
    return directory


def spoken_recordings(directory: str, n: int, words, rate: int = 16000, seed: int = 0):
    """*n* WAV files, each a sequence of turns, one per word of a sampled
    sentence: every word has its own tone, so a model can learn which word
    a turn is. Returns ``[(path, [{"start", "end", "text"}])]``."""
    import random

    import numpy
    import soundfile

    rng = random.Random(seed)
    noise = numpy.random.default_rng(seed)
    pitch = {w: 400.0 * 3 ** i for i, w in enumerate(words)}
    os.makedirs(directory, exist_ok=True)
    out = []
    for i in range(n):
        turns, chunks, t = [], [], 0.0
        for _ in range(rng.randint(2, 3)):
            word = rng.choice(list(words))
            length = 0.6
            x = numpy.arange(int(length * rate)) / rate
            chunks.append(0.4 * numpy.sin(2 * numpy.pi * pitch[word] * x))
            turns.append({"start": round(t, 3), "end": round(t + length, 3), "text": word})
            gap = numpy.zeros(int(0.2 * rate))
            chunks.append(gap)
            t += length + 0.2
        samples = numpy.concatenate(chunks).astype("float32")
        samples += noise.normal(0, 0.005, len(samples)).astype("float32")
        path = os.path.join(directory, "talk%03d.wav" % i)
        soundfile.write(path, samples, rate)
        out.append((path, turns))
    return out


def speaker_recordings(directory: str, n: int, seconds: float = 6.0, rate: int = 16000,
                       seed: int = 0):
    """*n* WAV files of two alternating "speakers", a low and a high tone,
    with silence between turns. Speaker names differ per file (``A``/``B``
    in one, ``B``/``A`` in the next), as diarization output does. Returns
    ``[(path, [{"start", "end", "speaker"}])]``."""
    import random

    import numpy
    import soundfile

    rng = random.Random(seed)
    noise = numpy.random.default_rng(seed)
    os.makedirs(directory, exist_ok=True)
    out = []
    for i in range(n):
        samples = noise.normal(0, 0.005, int(seconds * rate)).astype("float32")
        names = ("A", "B") if i % 2 == 0 else ("B", "A")
        turns, t, voice = [], 0.2, rng.randint(0, 1)
        while t < seconds - 0.8:
            length = rng.uniform(0.6, 1.2)
            end = min(seconds - 0.1, t + length)
            a, b = int(t * rate), int(end * rate)
            x = numpy.arange(b - a) / rate
            samples[a:b] += 0.4 * numpy.sin(2 * numpy.pi * (220.0 if voice == 0 else 1400.0) * x)
            turns.append({"start": round(t, 3), "end": round(end, 3), "speaker": names[voice]})
            t = end + rng.uniform(0.2, 0.4)
            voice = 1 - voice
        path = os.path.join(directory, "meet%03d.wav" % i)
        soundfile.write(path, samples, rate)
        out.append((path, turns))
    return out
