from datetime import datetime
import os
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans


if __name__ == '__main__':
    print(f'# generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")}')
    print('import framebuf')
    print('fbs = []')
    print('colors = []')

    for fn in os.listdir('pictures'):
        print(f'# {fn}')
        img = Image.open('pictures/' + fn)
        img = img.resize((128, 64), Image.LANCZOS)

        arr = np.asarray(img)
        h, w, c = arr.shape
        arr = arr.reshape((h * w, c))  # flatten pixels

        # Apply K-Means clustering
        kmeans = KMeans(n_clusters=16, random_state=42)
        kmeans.fit(arr)
        cl = np.round(kmeans.cluster_centers_).astype(int)
        print(f'colors.append({cl.tolist()})')

        img = img.convert("1", dither=Image.FLOYDSTEINBERG)
        packed_bytes = np.frombuffer(img.tobytes(), dtype=np.uint8)
        print(f'data = bytearray.fromhex("{bytearray(packed_bytes).hex()}")')
        print(f'fbs.append(framebuf.FrameBuffer(data, 128, 64, framebuf.MONO_HLSB))')
