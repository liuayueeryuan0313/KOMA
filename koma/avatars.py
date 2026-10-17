"""Small, normalized PNG avatars. No filenames or executable image formats are stored."""
import base64
import binascii
import struct
import zlib

MAX_BYTES=160*1024
MAX_SIDE=192

def decode_avatar(value):
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,') or len(value)>MAX_BYTES*4//3+32:
        raise ValueError('请选择有效头像图片')
    try:
        raw=base64.b64decode(value.split(',',1)[1],validate=True)
        if len(raw)>MAX_BYTES or not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError()
        offset=8;compressed=bytearray();expected=None;ended=False
        while offset<len(raw):
            length=struct.unpack('>I',raw[offset:offset+4])[0]
            kind=raw[offset+4:offset+8];end=offset+8+length
            if end+4>len(raw):raise ValueError()
            content=raw[offset+8:end]
            if zlib.crc32(kind+content)&0xffffffff!=struct.unpack('>I',raw[end:end+4])[0]:raise ValueError()
            if offset==8:
                if kind!=b'IHDR' or length!=13:raise ValueError()
                width,height,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',content)
                if not 1<=width<=MAX_SIDE or not 1<=height<=MAX_SIDE or depth!=8 or color not in (2,6) or compression or filtering or interlace:raise ValueError()
                expected=height*(1+width*(3 if color==2 else 4))
            elif kind==b'IHDR':raise ValueError()
            if kind==b'IDAT':compressed.extend(content)
            if kind==b'IEND':
                if length or end+4!=len(raw):raise ValueError()
                ended=True;break
            offset=end+4
        if not ended or not compressed or expected is None:raise ValueError()
        decoder=zlib.decompressobj();pixels=decoder.decompress(compressed,expected+1)
        if len(pixels)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError()
        return raw
    except (ValueError,struct.error,zlib.error,binascii.Error):
        raise ValueError('头像图片无效，请重新选择') from None
