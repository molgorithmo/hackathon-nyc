"""Conservative enhancement with an invertible map back to source coordinates."""

import cv2
import numpy as np


def enhance(image):
    if image is None or image.size == 0:
        raise ValueError('Unreadable or empty image')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    h, w = gray.shape
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80,
                            minLineLength=max(60, w // 8), maxLineGap=20)
    angles = []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            if abs(angle) <= 15:
                angles.append(angle)
    angle = float(np.median(angles)) if len(angles) >= 3 else 0.0
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    # Expand the canvas so deskewing never crops the source page.
    corners = np.array([[[0., 0.], [w, 0.], [w, h], [0., h]]], dtype=np.float64)
    rotated = cv2.transform(corners, matrix)[0]
    minimum, maximum = rotated.min(axis=0), rotated.max(axis=0)
    matrix[:, 2] -= minimum
    size = tuple(int(v) for v in np.ceil(maximum - minimum))
    aligned = cv2.warpAffine(gray, matrix, size, borderValue=255)
    cleaned = cv2.fastNlMeansDenoising(aligned, h=5)
    contrast = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(cleaned)
    blurred = cv2.GaussianBlur(contrast, (0, 0), 1.0)
    output = cv2.addWeighted(contrast, 1.4, blurred, -0.4, 0)
    return output, dict(angle_degrees=angle, original_size=[w, h], output_size=list(size),
                        source_to_processed=matrix.tolist(),
                        processed_to_source=cv2.invertAffineTransform(matrix).tolist())


def source_polygon(polygon, metadata):
    points = np.asarray(polygon, dtype=np.float64)[None]
    matrix = np.asarray(metadata['processed_to_source'], dtype=np.float64)
    return cv2.transform(points, matrix)[0].tolist()
