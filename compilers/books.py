import os
import struct
import bs4
import re

import util

def text_encode(txt):
    def insert_breaks_in_ascii_letters(text: str, chunk: int = 16) -> str:
        pattern = rf'[A-Za-z\-\_\?\^]{{{chunk + 1},}}'
        def repl(m):
            s = m.group(0)
            parts = [s[i:i + chunk] for i in range(0, len(s), chunk)]
            return '--\n'.join(parts)
        return re.sub(pattern, repl, text)

    txt = util.prepare_text(txt, fallback='_', loud=True)
    txt = insert_breaks_in_ascii_letters(txt)
    return txt.encode('ascii')

def with_length(obj):
    return struct.pack("<I", len(obj)) + obj

def compile(obj):
    if isinstance(obj, str):
        return text_encode(obj)
    elif isinstance(obj, list):  # e.g. top level books nav is this
        sb = bytearray()
        for el in obj:
            assert isinstance(el, tuple) and len(el) == 2 and isinstance(el[0], str)
            el_type = b'0' if isinstance(el[1], list) else b'1' if isinstance(el[1], str) else None
            assert el_type is not None
            sb += el_type
            sb += with_length(compile(el[0]))
            sb += with_length(compile(el[1]))
        return sb
    else:
        raise Exception('Incorrect hierarchy')


if __name__ == '__main__':
    books = []
    for fn in os.listdir('books'):
        print('Processing', fn)
        if not fn.lower().endswith(f".html"):
            continue
        s = bs4.BeautifulSoup(open('books/' + fn), features="lxml")
        chapters = []
        brief = s.find_all('header')[0].text.strip('\n').replace('\n', '\n\n')
        book_name = brief.split('\n')[0]
        chapters.append(('= Description =', brief))
        for chapter in s.find_all('article'):
            title = chapter.find('h1').text
            texts = [""]
            for p in chapter.find_all('p')[1:-1]:
                texts[-1] += p.text
                if len(texts[-1]) < 10000:
                    texts[-1] += '\n\n'
                else:
                    texts.append("")
            if len(texts) == 1:
                texts = texts[0]
            else:
                ln = len(texts)
                texts = [(f'{i+1}/{ln}', text) for i, text in enumerate(texts)]
            chapters.append((title, texts))
        books.append((book_name, chapters))

    bb = compile(books)
    print('books.bin size: ', len(bb))
    open('books.bin', 'wb').write(bb)
