import numpy as np
import easyocr
from PIL.Image import Image

reader = easyocr.Reader(['en', 'bg'], gpu=False)


def image_reader(image: Image) -> list:
    return reader.readtext(np.array(image))


def images_reader(images: list[Image]) -> list[list]:
    return [image_reader(image) for image in images]