import string
from datetime import datetime
import os
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans

import util

IMAGE_SIZE = 1024  # 128*64 bits / 8
COLOR_SIZE = 48  # 16 colors × 3 bytes
TEXT_SIZE = 32

DEBUG = False

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
        if DEBUG:
            import matplotlib.pyplot as plt
            img = Image.new("RGB", (16, 1))
            img.putdata([tuple(c) for c in cl])
            img = img.resize((16 * 32, 32), Image.NEAREST)  # scale for visibility
            plt.imshow(img)
            plt.axis("off")
            plt.show()

        img = img.convert("1", dither=Image.FLOYDSTEINBERG)

        fn = os.path.splitext(os.path.basename(fn))[0]
        text = util.prepare_text(fn)
        if len(text) > TEXT_SIZE:
            text = text[:TEXT_SIZE // 2] + text[-TEXT_SIZE // 2:]
        while len(text) < TEXT_SIZE:
            text += '\0'

        bb.extend(np.frombuffer(img.tobytes(), dtype=np.uint8))
        bb.extend(cl.astype(np.uint8).tobytes())
        bb.extend(text.encode())
        assert len(bb) % (IMAGE_SIZE + COLOR_SIZE + TEXT_SIZE) == 0, fn

    bb.extend(f'generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")}'.encode())
    print('gallery.bin size: ', len(bb))
    open('gallery.bin', 'wb').write(bb)
