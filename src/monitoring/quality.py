try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover - optional dependency fallback
    cv2 = None
    np = None


def compute_image_quality(image):
    if cv2 is None or np is None or image is None:
        return None, None, None, None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    blur_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    height, width = image.shape[:2]

    return brightness, blur_var, width, height


def quality_flags(brightness, blur_var):
    flags = []

    if brightness is None or blur_var is None:
        return flags

    if brightness < 40:
        flags.append("low_brightness")

    if blur_var < 50:
        flags.append("blurry")

    return flags