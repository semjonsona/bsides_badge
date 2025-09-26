from datetime import datetime
import os
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans

IMAGE_SIZE = 1024  # 128*64 bits / 8
COLOR_SIZE = 48  # 16 colors × 3 bytes

if __name__ == '__main__':
    bb = bytearray()
    for fn in os.listdir('pictures'):
        print(f'{fn}')
        img = Image.open('pictures/' + fn)
        img = img.resize((128, 64), Image.LANCZOS)
        img = img.convert("RGB")

        arr = np.asarray(img)
        h, w, c = arr.shape
        arr = arr.reshape((h * w, c))
        kmeans = KMeans(n_clusters=16, random_state=42)
        kmeans.fit(arr)
        cl = np.round(kmeans.cluster_centers_).astype(int)

        img = img.convert("1", dither=Image.FLOYDSTEINBERG)

        bb.extend(np.frombuffer(img.tobytes(), dtype=np.uint8))
        bb.extend(cl.astype(np.uint8).tobytes())
        assert len(bb) % (IMAGE_SIZE + COLOR_SIZE) == 0, fn

    bb.extend(f'# generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")}'.encode())
    open('gallery.bin', 'wb').write(bb)
