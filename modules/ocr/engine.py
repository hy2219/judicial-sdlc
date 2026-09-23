"""CPU CRAFT detection with offline KLOCR recognition; no EasyOCR recognizer."""

from dataclasses import dataclass
from functools import lru_cache
import math
import sys
import tempfile

from modules.ocr import validate_image_size
from modules.ocr.assets import CONFIDENCE_KIND, model_directory, validate_models

MAX_NEW_TOKENS = 192
BATCH_SIZE = 4
MAX_REGIONS = 5000
DETECTION_CANVAS_SIZE = 1536


@dataclass
class OCRReader:
    detector: object
    processor: object
    model: object
    device: str = "cpu"
    download_enabled: bool = False


@lru_cache(maxsize=1)
def reader():
    validate_models()
    import easyocr
    import torch
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    torch.set_num_threads(2)
    # EasyOCR adds this path to sys.path. Use an empty temporary folder, never
    # a user-controlled ~/.EasyOCR/user_network directory.
    with tempfile.TemporaryDirectory(prefix="judicial-ocr-network-") as empty_network:
        try:
            detector = easyocr.Reader(
                ["ko", "en"], gpu=False, model_storage_directory=str(model_directory()),
                user_network_directory=empty_network, download_enabled=False,
                detect_network="craft", recognizer=False,
                verbose=False, quantize=False,
            )
        finally:
            if empty_network in sys.path:
                sys.path.remove(empty_network)
    directory = model_directory()
    processor = TrOCRProcessor.from_pretrained(
        directory / "processor", local_files_only=True,
    )
    model = VisionEncoderDecoderModel.from_pretrained(
        directory / "model", local_files_only=True, use_safetensors=True,
    ).to("cpu").eval()
    return OCRReader(detector, processor, model)


def crop_regions(horizontal, free, size):
    width, height = size
    boxes = [
        [[left, top], [right, top], [right, bottom], [left, bottom]]
        for left, right, top, bottom in horizontal
    ] + list(free)
    if len(boxes) > MAX_REGIONS:
        raise ValueError("OCR 검출 영역이 처리 한도를 초과했습니다.")
    result = []
    for vertices in boxes:
        if len(vertices) != 4 or any(
            len(point) != 2 or not all(math.isfinite(float(v)) for v in point)
            for point in vertices
        ):
            raise ValueError("OCR 검출기가 잘못된 좌표를 반환했습니다.")
        box = [[float(x), float(y)] for x, y in vertices]
        rect = (
            max(0, math.floor(min(p[0] for p in box))),
            max(0, math.floor(min(p[1] for p in box))),
            min(width, math.ceil(max(p[0] for p in box))),
            min(height, math.ceil(max(p[1] for p in box))),
        )
        if rect[0] >= rect[2] or rect[1] >= rect[3]:
            raise ValueError("OCR 검출 영역이 이미지 범위를 벗어났습니다.")
        result.append((box, rect))
    return sorted(result, key=lambda value: (value[1][1], value[1][0]))


def sequence_confidence(tokens, scores, eos_id):
    """Token probabilities are an uncertainty signal, not calibrated OCR accuracy."""
    import torch

    logs = []
    ended = False
    for token, score in zip(tokens, scores):
        index = int(token)
        if index == eos_id:
            ended = True
            break
        logs.append(torch.log_softmax(score.float(), dim=-1)[index])
    confidence = float(torch.stack(logs).mean().exp()) if logs else 0.0
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("KLOCR이 잘못된 토큰 신뢰도를 반환했습니다.")
    return confidence, not ended


def recognize(image) -> list[dict]:
    validate_image_size(image.width, image.height)
    import numpy as np
    import torch

    runtime = reader()
    blocks = []
    with image.convert("RGB") as rgb:
        # EasyOCR maps detections back to the original image for KLOCR crops.
        horizontal, free = runtime.detector.detect(
            np.asarray(rgb), canvas_size=DETECTION_CANVAS_SIZE, mag_ratio=1.0,
        )
        regions = crop_regions(horizontal[0], free[0], rgb.size)
        for start in range(0, len(regions), BATCH_SIZE):
            batch = regions[start:start + BATCH_SIZE]
            crops = [rgb.crop(rect) for _, rect in batch]
            try:
                pixels = runtime.processor(crops, return_tensors="pt").pixel_values
                with torch.inference_mode():
                    output = runtime.model.generate(
                        pixels, max_new_tokens=MAX_NEW_TOKENS, num_beams=1,
                        do_sample=False, no_repeat_ngram_size=3, length_penalty=1.0,
                        return_dict_in_generate=True, output_scores=True,
                    )
                texts = runtime.processor.batch_decode(
                    output.sequences, skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
                )
                if len(texts) != len(batch) or output.sequences.shape[0] != len(batch):
                    raise ValueError("KLOCR이 검출 영역 수와 다른 결과를 반환했습니다.")
                for index, ((box, _), text) in enumerate(zip(batch, texts)):
                    tokens = output.sequences[index, 1:]
                    confidence, truncated = sequence_confidence(
                        tokens, [step[index] for step in output.scores],
                        runtime.model.config.eos_token_id,
                    )
                    warnings = []
                    if truncated:
                        warnings.append("KLOCR 생성 길이 한도: 원문 일부가 누락됐을 수 있습니다.")
                    if not text.strip():
                        warnings.append("검출 영역의 글자를 인식하지 못했습니다.")
                    blocks.append({
                        "text": text.strip(), "box": box, "confidence": confidence,
                        "confidence_kind": CONFIDENCE_KIND, "warnings": warnings,
                        "recognizer": "KLOCR", "detector": "CRAFT",
                    })
            finally:
                for crop in crops:
                    crop.close()
    return group_lines(blocks)


def group_lines(blocks: list[dict]) -> list[dict]:
    """Group horizontal blocks in a single-column workshop page, keeping words."""
    groups = []
    for block in sorted(blocks, key=lambda item: min(p[1] for p in item["box"])):
        top = min(p[1] for p in block["box"])
        bottom = max(p[1] for p in block["box"])
        center, height = (top + bottom) / 2, bottom - top
        match = next(
            (group for group in groups
             if abs(group["center"] - center) <= min(group["height"], height) * 0.5),
            None,
        )
        if match is None:
            groups.append({"center": center, "height": height, "words": [block]})
        else:
            match["words"].append(block)
    lines = []
    for group in sorted(groups, key=lambda value: value["center"]):
        words = sorted(group["words"], key=lambda word: min(p[0] for p in word["box"]))
        left = min(p[0] for word in words for p in word["box"])
        top = min(p[1] for word in words for p in word["box"])
        right = max(p[0] for word in words for p in word["box"])
        bottom = max(p[1] for word in words for p in word["box"])
        lines.append({
            "text": " ".join(word["text"] for word in words),
            "box": [[left, top], [right, top], [right, bottom], [left, bottom]],
            "confidence": min(word["confidence"] for word in words),
            "confidence_kind": CONFIDENCE_KIND,
            "warnings": list(dict.fromkeys(
                warning for word in words for warning in word.get("warnings", [])
            )),
            "words": words,
        })
    return lines
