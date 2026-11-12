"""Bounded original JPEG/PNG; preserve bytes/orientation, never detect faces."""
from pathlib import Path
import struct
import zlib

MAX_BYTES = 10 * 1024**2
MAX_PIXELS = 24_000_000
MAX_METADATA = 4 * 1024**2


def policy():
    return {'id': 'original_photo_v1', 'max_source_bytes': MAX_BYTES, 'max_pixels': MAX_PIXELS, 'max_metadata_bytes': MAX_METADATA}


def validate_media(media, size):
    if (not isinstance(media, dict) or set(media) != {'kind','format','width','height','orientation'}
            or media['kind'] != 'image' or media['format'] not in {'jpeg','png'}
            or type(size) is not int or not 0 < size <= MAX_BYTES
            or any(type(media[k]) is not int for k in ('width','height','orientation'))
            or not 0 < media['width'] * media['height'] <= MAX_PIXELS
            or min(media['width'],media['height']) < 1 or not 1 <= media['orientation'] <= 8):
        raise ValueError('사진은 JPEG·PNG 한 장, 10MiB·2400만 화소 이내여야 합니다.')
    return dict(media)


def orientation(tiff):
    if len(tiff) < 8 or tiff[:2] not in (b'II',b'MM'):
        raise ValueError('사진 회전 정보를 확인할 수 없습니다.')
    endian = '<' if tiff[:2] == b'II' else '>'
    if struct.unpack_from(endian+'H',tiff,2)[0] != 42:
        raise ValueError('사진 회전 정보 형식이 다릅니다.')
    start = struct.unpack_from(endian+'I',tiff,4)[0]
    if start < 8 or start+2 > len(tiff): raise ValueError('손상된 사진 회전 정보입니다.')
    count = struct.unpack_from(endian+'H',tiff,start)[0]
    if count > 256 or start+2+count*12+4 > len(tiff): raise ValueError('사진 회전 정보가 너무 크거나 손상되었습니다.')
    value = 1
    for offset in range(start+2,start+2+count*12,12):
        tag,kind,n = struct.unpack_from(endian+'HHI',tiff,offset)
        if tag == 274:
            if kind != 3 or n != 1: raise ValueError('사진 회전 정보 형식이 다릅니다.')
            value = struct.unpack_from(endian+'H',tiff,offset+8)[0]
    if not 1 <= value <= 8: raise ValueError('지원되지 않는 사진 회전 정보입니다.')
    return value



def metadata_size(kind, body, remaining):
    """Reject compressed text/profile expansion before the decoder sees it."""
    try:
        if kind in {b'iCCP', b'zTXt'}:
            pos=body.index(b'\0')
            if not 1 <= pos <= 79 or body[pos+1] != 0: raise ValueError()
            prefix=pos+2
            compressed=body[prefix:]
        elif kind == b'iTXt':
            pos=body.index(b'\0')
            if not 1 <= pos <= 79 or body[pos+1] not in (0,1) or body[pos+2] != 0: raise ValueError()
            flag=body[pos+1]
            start=body.index(b'\0',pos+3)+1
            start=body.index(b'\0',start)+1
            if not flag:
                if len(body)>remaining: raise ValueError()
                return len(body)
            prefix=start
            compressed=body[prefix:]
        else:
            if len(body)>remaining: raise ValueError()
            return len(body)
        if prefix>remaining: raise ValueError()
        remaining-=prefix
        decoder=zlib.decompressobj()
        expanded=decoder.decompress(compressed,remaining+1)
        if len(expanded)>remaining or not decoder.eof or decoder.unused_data: raise ValueError()
        return prefix+len(expanded)
    except (ValueError,IndexError,zlib.error):
        raise ValueError('사진 부가 정보가 너무 크거나 손상되었습니다.') from None


def framing(raw):
    width=height=0; rotate=1
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        pos=8; header=False; data=False; ended=False; metadata_bytes=0
        while pos+12 <= len(raw):
            length=struct.unpack_from('>I',raw,pos)[0]; kind=raw[pos+4:pos+8]; end=pos+12+length
            if end > len(raw): raise ValueError('손상된 PNG입니다.')
            body=raw[pos+8:pos+8+length]
            if zlib.crc32(kind+body)&0xffffffff != struct.unpack_from('>I',raw,end-4)[0]: raise ValueError('PNG 검사값이 다릅니다.')
            if kind not in {b'IDAT',b'IHDR',b'IEND'}:
                metadata_bytes += metadata_size(kind,body,MAX_METADATA-metadata_bytes)
            if not header and kind != b'IHDR': raise ValueError('PNG 헤더가 없습니다.')
            if kind == b'IHDR':
                if header or length != 13: raise ValueError('PNG 헤더가 다릅니다.')
                width,height=struct.unpack_from('>II',body);header=True
            elif kind in {b'acTL',b'fcTL',b'fdAT'}: raise ValueError('움직이는 사진은 지원하지 않습니다.')
            elif kind == b'eXIf': rotate=orientation(body)
            elif kind == b'IDAT': data=True
            elif kind == b'IEND':
                if length or not data or end != len(raw): raise ValueError('단일 PNG 사진이 필요합니다.')
                ended=True;break
            pos=end
        if not ended: raise ValueError('끝까지 읽을 수 있는 PNG가 필요합니다.')
        format='png'
    elif raw.startswith(b'\xff\xd8'):
        pos=2; scan=False; ended=False
        while pos < len(raw):
            if raw[pos] != 255: raise ValueError('손상된 JPEG입니다.')
            while pos < len(raw) and raw[pos] == 255: pos+=1
            if pos >= len(raw): break
            marker=raw[pos];pos+=1
            if marker == 217:
                if pos != len(raw) or not scan: raise ValueError('단일 JPEG 사진이 필요합니다.')
                ended=True;break
            if marker in {0,216}: raise ValueError('단일 JPEG 사진이 필요합니다.')
            if pos+2 > len(raw): break
            length=struct.unpack_from('>H',raw,pos)[0];end=pos+length
            if length < 2 or end > len(raw): raise ValueError('손상된 JPEG입니다.')
            body=raw[pos+2:end]
            if marker in {192,194}:
                if len(body)<6 or width: raise ValueError('JPEG 크기 정보가 다릅니다.')
                height,width=struct.unpack_from('>HH',body,1)
            if marker == 225 and body.startswith(b'Exif\0\0'): rotate=orientation(body[6:])
            if marker == 226 and body.startswith(b'MPF\0'): raise ValueError('여러 장의 사진은 지원하지 않습니다.')
            pos=end
            if marker == 218:
                scan=True
                while pos < len(raw):
                    if raw[pos] != 255: pos+=1;continue
                    if pos+1 < len(raw) and (raw[pos+1] == 0 or 208 <= raw[pos+1] <= 215): pos+=2;continue
                    break
        if not ended: raise ValueError('끝까지 읽을 수 있는 JPEG가 필요합니다.')
        format='jpeg'
    else:
        raise ValueError('JPEG·PNG 원본 사진을 선택하세요.')
    return validate_media(dict(kind='image',format=format,width=width,height=height,orientation=rotate),len(raw))


def probe(path):
    """Existing CPU decoder only, one bounded still image, no output/transpose."""
    path = Path(path)
    with path.open('rb') as stream: signature=stream.read(8)
    if not (signature.startswith(b'\xff\xd8') or signature == b'\x89PNG\r\n\x1a\n'): return None
    if not 0 < path.stat().st_size <= MAX_BYTES: raise ValueError('사진은 10MiB 이내여야 합니다.')
    media=framing(path.read_bytes())
    from mideagent_media_tools.operations import process
    process(['ffmpeg','-v','error','-nostdin','-xerror','-max_alloc','67108864','-hwaccel','none',
             '-threads','1','-filter_threads','1','-protocol_whitelist','file,pipe','-format_whitelist','image2pipe',
             '-f','image2pipe','-c:v','png' if media['format']=='png' else 'mjpeg','-noautorotate',
             '-err_detect','explode','-i',str(path),'-frames:v','1','-f','null','-'],timeout=10)
    return media


def asset_media(asset):
    meta=asset.get('metadata',{});media=meta.get('media') or {}
    if 'image_original_policy' not in meta and media.get('kind') != 'image': return None
    if (meta.get('registration_state')!='verified' or meta.get('image_original_policy')!=policy()
            or meta.get('media_type')!={'jpeg':'image/jpeg','png':'image/png'}.get(media.get('format'))):
        raise ValueError('검증된 사진 원본이 필요합니다.')
    return validate_media(media,asset['bytes'])


def verify_path(path, media, size):
    if path.stat().st_size != size or probe(path) != validate_media(media,size):
        raise ValueError('사진 원본의 실제 내용·유형이 다릅니다.')
