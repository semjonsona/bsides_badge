import os
import string
import struct
import bs4

TITLE_SIZE = 64

def text_encode(txt):
    txt = ''.join([c for c in txt if c in """!"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyz{|}~ \n"""])
    return txt.encode('ascii')

if __name__ == '__main__':
    bb = bytearray()
    for fn in os.listdir('books'):
        print(fn)
        if not fn.lower().endswith(f".html"):
            continue
        s = bs4.BeautifulSoup(open('books/' + fn))
        chapters = []
        brief = s.find_all('header')[0].text.strip('\n').replace('\n', '\n\n')
        book_name = brief.split('\n')[0]
        chapters.append(('= Description =', brief))
        for article in s.find_all('article'):
            title = article.find('h1').text
            text = ""
            for p in article.find_all('p')[1:-1]:
                text += p.text
                text += '\n\n'
            chapters.append((title, text))

        sb = bytearray()
        book_name = text_encode(book_name)
        for name, text in chapters:
            name = text_encode(name)
            text = text_encode(text)
            sb += b'1'  # type text
            sb += struct.pack("<I", len(name))
            sb += name
            sb += struct.pack("<I", len(text))
            sb += text
        bb += b'0'  # type book
        bb += struct.pack("<I", len(book_name))
        bb += book_name
        bb += struct.pack("<I", len(sb))
        bb += sb
    open('books.bin', 'wb').write(bb)
