from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    name: str
    backend: str
    model_id: str
    prompt: str | tuple[str, ...]
    revision: str = "main"
    candidate_threshold: float = 0.0
    threshold: float = 0.0
    text_threshold: float = 0.25
    max_new_tokens: int = 512
    image_max_side: int = 1024
    load_in_4bit: bool = False


CONFIGS = {
    "grounding_dino": Config(
        "grounding_dino", "dino", "IDEA-Research/grounding-dino-tiny",
        "butterfly. moth.", candidate_threshold=0.30, threshold=0.30,
    ),
    "owlv2": Config(
        "owlv2", "owl", "google/owlv2-base-patch16-ensemble",
        ("a butterfly", "a moth"), candidate_threshold=0.10, threshold=0.10,
    ),
    "qwen": Config(
        "qwen", "qwen", "Qwen/Qwen3-VL-2B-Instruct",
        'Detect every visible adult butterfly or moth. Give each individual '
        'one tight bounding box covering only its visible parts. Ignore '
        'other insects, caterpillars, pupae, and shadows. Return only a JSON '
        'array of objects with "bbox_2d": [x_min, y_min, x_max, y_max], '
        'using integer coordinates from 0 to 1000 relative to the full image. '
        'Return [] if no adult butterfly or moth is visible.',
    ),
}

OWL_EXPERIMENT_THRESHOLDS = (0.15, 0.20, 0.25, 0.30)
