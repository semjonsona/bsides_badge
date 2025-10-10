from PIL import Image
import numpy as np
from bitstring import BitArray
from books import compress

if __name__ == '__main__':
    img = Image.open('ecscspecial/0a356142c7184ae283480e277bf81dda.gif')
    #p = bytearray()
    bitarrays = []
    for i in range(4, img.n_frames):
        img.seek(i)
        frame = img.crop((125, 50, 375, 250)).resize((128, 64), Image.NEAREST).convert("1", dither=Image.NONE)
        by = np.frombuffer(frame.tobytes(), dtype=np.uint8)
        #p.extend(by)
        bitarrays.append(BitArray(frame.tobytes()))
    ll = [bitarrays[0].bin] + [(bitarrays[i] ^ bitarrays[i -1 ]).bin for i in range(1, len(bitarrays))]
    #open('ecscspecial/ecscspecial.bin', 'wb').write(p)
    c = compress(ll, 256)
    print()
