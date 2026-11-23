import json
import math
import re


def normalized_box(coords, width, height):
    """Convert XYXY coordinates to the contest format; ignore empty boxes."""
    x1, y1, x2, y2 = coords
    if not all(math.isfinite(value) for value in coords):
        raise ValueError("Non-finite box coordinates")
    left, right = (min(1.0, max(0.0, x / width)) for x in (x1, x2))
    top, bottom = (min(1.0, max(0.0, y / height)) for y in (y1, y2))
    if right <= left or bottom <= top:
        return None
    return dict(left=left, top=top, width=right-left, height=bottom-top)


def parse_qwen(text):
    """Parse the whole response, accepting an optional Markdown JSON fence."""
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text.strip(), re.S | re.I)
    items = json.loads(fenced.group(1) if fenced else text)
    if not isinstance(items, list):
        raise ValueError("Expected a JSON list")
    boxes = []
    for item in items:
        coords = item.get("bbox_2d") if isinstance(item, dict) else None
        if not isinstance(coords, list) or len(coords) != 4 or not all(
            type(value) in (int, float) and 0 <= value <= 1000 for value in coords
        ):
            raise ValueError("Expected four bbox_2d coordinates in [0, 1000]")
        box = normalized_box(coords, 1000, 1000)
        if box is None:
            raise ValueError("Qwen returned an empty or reversed box")
        boxes.append(box)
    return boxes


class QwenResponseError(ValueError):
    def __init__(self, message, raw_response):
        super().__init__(message)
        self.raw_response = raw_response


def choose_device():
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def load_detector(config, device):
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    from transformers import BitsAndBytesConfig

    processor = AutoProcessor.from_pretrained(config.model_id, revision=config.revision)
    if config.backend == "qwen":
        from transformers import Qwen3VLForConditionalGeneration
        dtype = torch.float16 if device.startswith("cuda") else torch.bfloat16
        options = {"dtype": dtype}
        if config.load_in_4bit:
            if not device.startswith("cuda"):
                raise ValueError("This 4-bit configuration requires a CUDA device")
            options["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=dtype,
            )
            options["device_map"] = {"": device}
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            config.model_id, revision=config.revision, **options
        )
        if not config.load_in_4bit:
            model.to(device)
    else:
        model = AutoModelForZeroShotObjectDetection.from_pretrained(
            config.model_id, revision=config.revision
        ).to(device)
    return processor, model.eval()


def predict_one(detector, config, image, device):
    """Return candidates (each with a box and optional score) and model text."""
    import torch
    from PIL import Image

    processor, model = detector
    with torch.inference_mode():
        if config.backend == "qwen":
            resized = image.copy()
            resized.thumbnail(
                (config.image_max_side, config.image_max_side), Image.Resampling.LANCZOS
            )
            messages = [{"role": "user", "content": [
                {"type": "image", "image": resized},
                {"type": "text", "text": config.prompt},
            ]}]
            chat_text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
            inputs = processor(
                text=[chat_text], images=[resized], return_tensors="pt"
            ).to(device)
            ids = model.generate(
                **inputs, max_new_tokens=config.max_new_tokens, do_sample=False
            )
            text = processor.batch_decode(
                ids[:, inputs.input_ids.shape[1]:], skip_special_tokens=True
            )[0]
            try:
                boxes = parse_qwen(text)
            except ValueError as error:
                raise QwenResponseError(str(error), text) from error
            return [{"box": box, "score": None} for box in boxes], text

        size = [(image.height, image.width)]
        query = config.prompt if config.backend == "dino" else [list(config.prompt)]
        inputs = processor(images=image, text=query, return_tensors="pt").to(device)
        outputs = model(**inputs)
        if config.backend == "dino":
            result = processor.post_process_grounded_object_detection(
                outputs, input_ids=inputs.input_ids, target_sizes=size,
                threshold=config.candidate_threshold, text_threshold=config.text_threshold,
            )[0]
        else:
            result = processor.image_processor.post_process_object_detection(
                outputs, target_sizes=size, threshold=config.candidate_threshold
            )[0]

    candidates = []
    for coords, score in zip(result["boxes"].tolist(), result["scores"].tolist()):
        box = normalized_box(coords, image.width, image.height)
        if box is not None:
            candidates.append({"box": box, "score": score})
    return candidates, None


def select_boxes(candidates, threshold):
    return [
        candidate["box"] for candidate in candidates
        if candidate["score"] is None or candidate["score"] >= threshold
    ]
