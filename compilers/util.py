from datetime import datetime
import struct

CHARSET = """\n !"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"""
TRANSITIONS = {'“': '"', '”': '"', '…': '...', "’": "'", "‘": "'", "—": '---', 'á': "a'", 'é': "e'", 'ï': 'ii',
               'ç': 'c,', '№': 'No', 'â': 'a', 'è': 'e`', '\t': '   ', "–": "-"}

def prepare_text(txt, fallback='', loud=False):
    if loud:
        unk = [c for c in list(set(txt)) if c not in CHARSET and c not in TRANSITIONS]
        if len(unk) != 0:
            print('unknown characters:', [(u, u.encode().hex()) for u in unk])
    return ''.join(c if c in CHARSET else TRANSITIONS[c] if c in TRANSITIONS else fallback for c in txt)


def compile_info():
    return f'generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'.encode()


def with_length(obj):
    return struct.pack("<I", len(obj)) + obj
