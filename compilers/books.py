# Converts .html files from FimFiction

import os
import struct
import bs4
import re
from collections import Counter

import util

def text_encode(txt):
    txt = util.prepare_text(txt, fallback='_', loud=True)
    return txt

def with_length(obj):
    return struct.pack("<I", len(obj)) + obj

def compile(obj):
    if isinstance(obj, str):  # uncompressed text
        return obj.encode('ascii')
    elif isinstance(obj, bytes):  # compressed text
        return obj
    elif isinstance(obj, list):  # nav
        sb = bytearray()
        for el in obj:
            assert isinstance(el, tuple) and len(el) == 2
            el_type = b'0' if isinstance(el[1], list) else \
                      b'1' if isinstance(el[1], str) else \
                      b'2' if isinstance(el[1], bytes) else None
            assert el_type is not None
            sb += el_type
            sb += with_length(compile(el[0]))
            sb += with_length(compile(el[1]))
        return sb
    else:
        raise Exception('Incorrect hierarchy')

CHUNKS_DELIMITER = 300

def flatten(obj):
    if isinstance(obj, list):
        return ''.join([flatten(e) + '\0' for e in obj])[:-1]
    elif isinstance(obj, tuple):
        return flatten(obj[1])  # do not flatten the name
    elif isinstance(obj, str):
        return obj
    else:
        raise Exception('Incorrect hierarchy')

def inflate(struc, flattened):
    if isinstance(struc, tuple):
        got, flattened = inflate(struc[1], flattened)
        return (struc[0], got), flattened
    if isinstance(struc, list):
        nstruc = []
        for el in struc:
            newel, flattened = inflate(el, flattened)
            nstruc.append(newel)
        return nstruc, flattened
    if isinstance(struc, str):
        p = flattened.index(CHUNKS_DELIMITER)
        return bytes(flattened[:p]), flattened[p + 1:]
    raise Exception('Incorrect hierarchy')


def sheer_stone(initial_chars, rules):
    ts = bytearray()
    for c in initial_chars:
        ts += c.encode() + b'\0'
    for r in rules.values():
        assert(len(r) == 2)
        ts += bytearray(r)
    assert len(ts) == 512
    return ts


def compress(books, max_tokens=256):
    corpus = flatten(books) + '\0'

    initial_chars = sorted(set(corpus))  # \0 at pos 0, as it should be
    char_to_id = {ch:i for i,ch in enumerate(initial_chars)}
    char_to_id['\0'] = CHUNKS_DELIMITER

    seq = [char_to_id[ch] for ch in corpus]

    #forced = ["Twilight", "Applejack", "Rainbow", "Pinkie", "Rarity", "Fluttershy"][::-1]
    forced = []

    rules = {}  # new_id -> list[old_id]
    while len(initial_chars) + len(rules) < max_tokens:
        if len(forced) == 0:
            pairs = Counter((seq[i], seq[i+1]) for i in range(len(seq)-1))
            for group, cnt in pairs.most_common():
                if b'\0' not in group:
                    break
        else:
            group = [char_to_id[c] for c in forced.pop().lower()]
        new_id = len(initial_chars) + len(rules)
        rules[new_id] = group

        new_seq = []
        i = 0
        group0 = group[0]  # cache friendly
        group = list(group)
        ln = len(group)
        while i < len(seq):
            if seq[i] == group0 and seq[i:i+ln] == group:
                new_seq.append(new_id)
                i += ln
            else:
                new_seq.append(seq[i])
                i += 1
        seq = new_seq
        print(f'\rCompressed megaseq len: {len(seq)}, rules: {len(rules)}   ', end='')
    print()

    compressed_books, flattened_more = inflate(books, seq)
    assert len(flattened_more) == 0
    return sheer_stone(initial_chars, rules), compressed_books


if __name__ == '__main__':
    books = []
    for fn in os.listdir('books'):
        print('Processing', fn)
        if not fn.lower().endswith(f".html"):
            continue
        s = bs4.BeautifulSoup(open('books/' + fn), features="lxml")
        chapters = []
        brief = text_encode(s.find_all('header')[0].text.strip('\n'))
        book_name = brief.split('\n')[0]
        chapters.append(('= Description =', brief))
        for chapter in s.find_all('article'):
            title = text_encode(chapter.find('h1').text.strip(' \n'))
            texts = [""]
            elements = chapter.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            elements = [el for el in elements if not el.find_parent(['header', 'footer'])]
            for el in elements:
                texts[-1] += text_encode('{ ' + el.text + ' }')
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

    sheer_stone, books = compress(books)
    bb = compile(books)

    compile_info = util.compile_info()

    out = with_length(compile_info) + with_length(sheer_stone) + with_length(bb)

    print('books.bin size: ', len(out))
    open('books.bin', 'wb').write(out)
