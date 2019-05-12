#!/bin/env python
import io
import itertools
import os
import struct
import sys
from array import array
from collections import namedtuple
from typing import List

import PIL
from PIL import Image

output_dir = os.path.join(os.path.dirname(__file__), 'unpacked')

def mkdir(path):
    if not os.path.exists(path):
        os.makedirs(path)

class Parser:
    format = None
    container_class = None

    @classmethod
    def get_total_bytes(cls):
        return sum(size for size, _ in cls.format)

    @classmethod
    def _read_buffer(cls, fh):
        total_bytes = cls.get_total_bytes()
        all_data = fh.read(total_bytes)
        if len(all_data) != total_bytes:
            raise Exception(f'{len(all_data)} != {total_bytes}')
        return all_data

    @classmethod
    def parse_data(cls, data):
        retval = []
        offset = 0
        for size, format in cls.format:
            part = data[offset:offset + size]
            offset += size
            if len(part) != size:
                raise Exception(f'{len(part)} != {size}')
            unpacked = struct.unpack(format, part)
            if len(unpacked) == 1:
                unpacked = unpacked[0]
            retval.append(unpacked)
        return cls.container_class(*retval)

    @classmethod
    def read(cls, buffer) -> container_class:
        data = cls._read_buffer(buffer)
        retval = cls.parse_data(data)
        return retval

    @classmethod
    def build_bytes(cls, parts):
        bytes_list = []
        for (size, format), part in zip(cls.format, parts):
            if not isinstance(part, tuple):
                part = (part,)
            data = struct.pack(format, *part)
            if len(data) != size:
                raise Exception(f'{len(part)} != {size}')
            bytes_list.append(data)
        retval = b''.join(bytes_list)
        return retval

    @classmethod
    def write(cls, buffer, parts):
        buffer.write(cls.build_bytes(parts))

class HeaderParser(Parser):
    HeaderContainer = namedtuple('HeaderContainer', ['sig', 'version', 'stuff', 'res_count'])
    format = [(5, '5B'), (1, 'B'), (10, '10B'), (4, 'I')]
    container_class = HeaderContainer

class TOCParser(Parser):
    TOCEntry = namedtuple('TOCEntry', 'abs_offset')
    format = [(4, '<I')]
    container_class = TOCEntry


class ImageHeaderParser(Parser):
    ImageHeader = namedtuple('ImageHeader', ['sig', 'width', 'height', 'row_length', 'bits_per_pixel', 'palette_colors', 'transparency'])
    format = [(4, '4B'), (2, 'H'), (2, 'H'), (2, 'H'), (2, 'H'), (2, 'H'), (2, 'H')]
    container_class = ImageHeader

class PaletteParser(Parser):
    PaletteData = namedtuple('PaletteData', ['r', 'g', 'b', 'pad'])
    format = [(1, 'B'), (1, 'B'), (1, 'B'), (1, 'B')]
    container_class = PaletteData

class Bitwriter:
    def __init__(self):
        self.bytes = []
        self.last_byte = None
        self.pos = 0

    def add(self, number, bits):
        if self.last_byte is None:
            self.last_byte = 0
        self.last_byte <<= bits
        self.last_byte |= number
        self.pos += bits
        if self.pos >= 8:
            self.bytes.append(self.last_byte)
            self.last_byte = 0
            self.pos = 0

    def build(self):
        if self.last_byte is not None:
            self.last_byte <<= 8 - self.pos
            self.bytes.append(self.last_byte)
        return array('B', self.bytes).tobytes()


def bitwalker(byte_data):
    for byte in byte_data:
        for bitpos in range(7, -1, -1):
            yield (byte & (1 << bitpos)) >> bitpos

def chunkwise(count, iterable):
    chunk = []
    for i in iterable:
        chunk.append(i)
        if len(chunk) == count:
            yield chunk
            chunk = []
    if chunk:
        yield chunk

def bits_to_int(bits):
    retval = 0
    for idx, bit in enumerate(bits[::-1]):
        retval += bit << idx
    return retval

def convert_palette_image_to_png(image_info: ImageHeaderParser.ImageHeader, image_data):
    width = image_info.width
    height = image_info.height
    img = Image.new('P', (width, height))
    img_buf = io.BytesIO(image_data)

    palette = [PaletteParser.read(img_buf) for _ in range(image_info.palette_colors)]
    raw_palette = list(itertools.chain.from_iterable((p.r, p.g, p.b) for p in palette))

    img.putpalette(raw_palette)
    for y in range(height):
        row_data = img_buf.read(image_info.row_length)
        for x, bits in enumerate(chunkwise(image_info.bits_per_pixel, bitwalker(row_data))):
            if x > width - 1:
                break  # if image width is not a multiple of 8, there might be too many bits for this row
            palette_idx = bits_to_int(bits)
            # color = palette[palette_idx]
            img.putpixel((x, y), palette_idx)

    out_img_buffer = io.BytesIO()
    img.save(out_img_buffer, format='png')
    return out_img_buffer.getvalue()

def convert_png_image_to_palette_image(image_data, original_image_info:ImageHeaderParser.ImageHeader):
    buf = io.BytesIO(image_data)
    im = Image.open(buf)
    raw_palette = im.getpalette()[:original_image_info.palette_colors * 3]
    header = ImageHeaderParser.ImageHeader(
        sig=original_image_info.sig,
        width=im.size[0],
        height=im.size[1],
        row_length=original_image_info.row_length,
        bits_per_pixel=original_image_info.bits_per_pixel,
        palette_colors=len(raw_palette) // 3,
        transparency=original_image_info.transparency,
    )
    header_data = ImageHeaderParser.build_bytes(header)
    palette_data = b''.join(
        PaletteParser.build_bytes(PaletteParser.PaletteData(r, g, b, 0))
        for r, g, b in chunkwise(3, raw_palette)
    )

    image_data = []
    for y in range(original_image_info.height):
        bitwriter = Bitwriter()
        for x in range(original_image_info.width):
            if x >= original_image_info.width:
                bit = 0
            else:
                bit = im.getpixel((x, y))
            bitwriter.add(bit, original_image_info.bits_per_pixel)
        image_data.append(bitwriter.build()[:original_image_info.row_length])

    return header_data + palette_data + b''.join(image_data)




def write_resource(image_info, image_data, filename):
    mkdir(output_dir)
    png_bytes = convert_palette_image_to_png(image_info, image_data)
    with open(filename, 'wb') as fh:
        fh.write(png_bytes)

ResFile = namedtuple('ResFile', ['header', 'toc', 'resources'])
Resource = namedtuple('Resource', [
    'image_info',
    'image_data',
    'filename',
])

def parse_resource(data, idx):
    image_info: ImageHeaderParser.ImageHeader = ImageHeaderParser.parse_data(data)
    image_data = data[ImageHeaderParser.get_total_bytes():]
    rebuild = ImageHeaderParser.build_bytes(image_info)
    filename = os.path.join(output_dir, f'{idx}.png')
    return Resource(
        image_info=image_info,
        image_data=image_data,
        filename=filename,
    )

def parse_res_file(buffer):
    header: HeaderParser.HeaderContainer = HeaderParser.read(buffer)
    toc: List[TOCParser.TOCEntry] = []
    for _ in range(header.res_count):
        toc.append(TOCParser.read(buffer))
    prev_abs_offset = 0
    resources = []
    for idx, entry in enumerate(toc[1:]):
        resource_len = entry.abs_offset - prev_abs_offset
        prev_abs_offset = entry.abs_offset
        resources.append(parse_resource(buffer.read(resource_len), idx))
    resources.append(parse_resource(buffer.read(), len(toc)))  # read the rest of the file as the last resource

    return ResFile(
        header=header,
        toc=toc,
        resources=resources,
    )

def repack_res_file(output_file, resfile: ResFile):
    with open(output_file, 'wb') as outfh:
        outfh.write(HeaderParser.build_bytes(resfile.header))
        for toc in resfile.toc:
            outfh.write(TOCParser.build_bytes(toc))
        for resource in parsed.resources:
            with open(resource.filename, 'rb') as fh:
                png_data = fh.read()
            img_data = convert_png_image_to_palette_image(png_data, resource.image_info)
            outfh.write(img_data)


command = sys.argv[1]
filename = sys.argv[2]

assert os.path.exists(filename)
with open(filename, 'rb') as fh:
    data = fh.read()
buffer = io.BytesIO(data)
parsed = parse_res_file(buffer)

if command == 'unpack':
    for resource in parsed.resources:
        write_resource(resource.image_info, resource.image_data, resource.filename)
elif command == 'repack':
    repack_res_file(filename.rsplit('.res')[0] + '.new.res', parsed)
elif command == 'justdoit':
    for resource in parsed.resources:
        write_resource(resource.image_info, resource.image_data, resource.filename)
    repack_res_file(filename.rsplit('.res')[0] + '.new.res', parsed)


