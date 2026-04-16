from src.monitoring.store import insert_prediction
from src.monitoring.quality import compute_image_quality, quality_flags


def log_prediction(image, predicted_class, confidence, latency_ms):
    if image is None:
        brightness = None
        blur_var = None
        width = None
        height = None
        flags = []
    else:
        brightness, blur_var, width, height = compute_image_quality(image)
        flags = quality_flags(brightness, blur_var)

    return insert_prediction(
        predicted_class=predicted_class,
        confidence=confidence,
        latency_ms=latency_ms,
        brightness=brightness,
        blur_var=blur_var,
        width=width,
        height=height,
        quality_warnings=flags
    )