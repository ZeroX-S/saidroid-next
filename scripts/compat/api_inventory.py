"""Read Java/DEX linkage metadata without executing application code."""
from dataclasses import dataclass, field
from pathlib import Path
import struct
import zipfile
import re


@dataclass
class ClassInfo:
    name: str
    superclass: str
    interfaces: tuple
    access: int
    fields: dict = field(default_factory=dict)
    methods: dict = field(default_factory=dict)
    origin: str = ''


@dataclass
class Inventory:
    classes: dict = field(default_factory=dict)
    types: set = field(default_factory=set)
    references: set = field(default_factory=set)
    duplicates: list = field(default_factory=list)

    def add(self, other):
        for name, definition in other.classes.items():
            if name in self.classes:
                self.duplicates.append(dict(name=name, first=self.classes[name].origin,
                                            shadowed=definition.origin))
            else:
                self.classes[name] = definition
        self.types.update(other.types)
        self.references.update(other.references)
        self.duplicates.extend(other.duplicates)

    def resolve(self, kind, owner, name, descriptor):
        if owner.startswith('[') and kind == 'method':
            if name == 'clone' and descriptor in ('()' + owner, '()Ljava/lang/Object;'):
                return ClassInfo(owner, 'java/lang/Object', (), 1), 0x101
            owner = 'java/lang/Object'
        pending = [owner]
        visited = set()
        while pending:
            current = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            definition = self.classes.get(current)
            if definition is None:
                continue
            members = definition.fields if kind == 'field' else definition.methods
            if (name, descriptor) in members:
                return definition, members[name, descriptor]
            if kind == 'method' and current in ('java/lang/invoke/MethodHandle', 'java/lang/invoke/VarHandle'):
                polymorphic = [flags for (member, _), flags in members.items()
                               if member == name and flags & 0x180 == 0x180]
                if polymorphic:
                    return definition, polymorphic[0]
            if name in ('<init>', '<clinit>'):
                continue
            # Field resolution searches interfaces before the superclass.
            parents = [*definition.interfaces, definition.superclass]
            if kind == 'method':
                parents = [definition.superclass, *definition.interfaces]
            pending = [parent for parent in parents if parent] + pending
        return None


def mutf8(data):
    text = data.replace(b'\xc0\x80', b'\0').decode('utf-8', 'surrogatepass')
    if any(0xd800 <= ord(character) <= 0xdfff for character in text):
        text = text.encode('utf-16', 'surrogatepass').decode('utf-16', 'surrogatepass')
    return text


def class_name(descriptor):
    descriptor = descriptor.lstrip('[')
    return descriptor[1:-1] if descriptor.startswith('L') and descriptor.endswith(';') else ''


def member_owner(descriptor):
    return descriptor[1:-1] if descriptor.startswith('L') else descriptor


def read_class(data, origin):
    if len(data) < 10 or data[:4] != b'\xca\xfe\xba\xbe':
        raise ValueError('Invalid class file: ' + origin)
    position = 8

    def take(format):
        nonlocal position
        size = struct.calcsize(format)
        if position + size > len(data):
            raise ValueError('Truncated class file: ' + origin)
        values = struct.unpack_from(format, data, position)
        position += size
        return values[0] if len(values) == 1 else values

    count = take('>H')
    pool = [None] * count
    index = 1
    while index < count:
        tag = take('>B')
        if tag == 1:
            size = take('>H')
            pool[index] = (tag, mutf8(data[position:position + size]))
            position += size
        elif tag in (7, 8, 16, 19, 20):
            pool[index] = (tag, take('>H'))
        elif tag in (9, 10, 11, 12, 17, 18):
            pool[index] = (tag, *take('>HH'))
        elif tag == 15:
            pool[index] = (tag, *take('>BH'))
        elif tag in (3, 4):
            position += 4
        elif tag in (5, 6):
            position += 8
            index += 1
        else:
            raise ValueError('Unknown class constant pool tag in ' + origin)
        if position > len(data):
            raise ValueError('Truncated class file: ' + origin)
        index += 1

    def owner(index):
        return pool[pool[index][1]][1] if index else ''

    access, this, superclass = take('>HHH')
    interfaces = tuple(owner(take('>H')) for _ in range(take('>H')))
    definition = ClassInfo(owner(this), owner(superclass), interfaces, access, origin=origin)
    for members in (definition.fields, definition.methods):
        for _ in range(take('>H')):
            flags, name, descriptor, attributes = take('>HHHH')
            members[pool[name][1], pool[descriptor][1]] = flags
            for _ in range(attributes):
                _, size = take('>HI')
                position += size
                if position > len(data):
                    raise ValueError('Truncated class attribute: ' + origin)
    inventory = Inventory(classes={definition.name: definition})
    for entry in pool:
        if entry and entry[0] == 7:
            name = pool[entry[1]][1]
            inventory.types.add(class_name(name) if name.startswith('[') else name)
        if entry and entry[0] in (9, 10, 11):
            _, name, descriptor = pool[entry[2]]
            inventory.references.add(('field' if entry[0] == 9 else 'method',
                                      owner(entry[1]), pool[name][1], pool[descriptor][1]))
    inventory.types.discard('')
    for _, descriptor in [*definition.fields, *definition.methods]:
        inventory.types.update(re.findall(r'L([^;]+);', descriptor))
    for _, _, _, descriptor in inventory.references:
        inventory.types.update(re.findall(r'L([^;]+);', descriptor))
    return inventory


def read_dex(data, origin):
    if data[:8] not in (b'dex\n035\0', b'dex\n037\0', b'dex\n038\0', b'dex\n039\0', b'dex\n040\0'):
        raise ValueError('Unsupported DEX version: ' + origin)
    if len(data) < 112 or struct.unpack_from('<I', data, 32)[0] != len(data):
        raise ValueError('Invalid DEX size: ' + origin)
    if struct.unpack_from('<II', data, 36) != (112, 0x12345678):
        raise ValueError('Unsupported DEX header: ' + origin)

    def u16(offset):
        if offset < 0 or offset + 2 > len(data):
            raise ValueError('Invalid DEX uint16 offset: ' + origin)
        return struct.unpack_from('<H', data, offset)[0]

    def u32(offset):
        if offset < 0 or offset + 4 > len(data):
            raise ValueError('Invalid DEX uint32 offset: ' + origin)
        return struct.unpack_from('<I', data, offset)[0]

    def uleb(offset):
        result = 0
        for shift in range(0, 35, 7):
            if offset >= len(data):
                raise ValueError('Truncated DEX uleb128: ' + origin)
            value = data[offset]
            offset += 1
            if shift == 28 and value > 15:
                raise ValueError('DEX uleb128 exceeds uint32: ' + origin)
            result |= (value & 127) << shift
            if value < 128:
                return result, offset
        raise ValueError('Invalid DEX uleb128: ' + origin)

    counts = struct.unpack_from('<12I', data, 56)
    for index, size in enumerate((4, 4, 12, 8, 8, 32)):
        count, offset = counts[index * 2:index * 2 + 2]
        if count and (offset < 112 or offset + count * size > len(data)):
            raise ValueError('Invalid DEX table bounds: ' + origin)
    strings = []
    for index in range(counts[0]):
        _, start = uleb(u32(counts[1] + index * 4))
        strings.append(mutf8(data[start:data.index(b'\0', start)]))
    types = [strings[u32(counts[3] + index * 4)] for index in range(counts[2])]
    prototypes = []
    for index in range(counts[4]):
        offset = counts[5] + index * 12
        parameters = u32(offset + 8)
        arguments = ''
        if parameters:
            arguments = ''.join(types[u16(parameters + 4 + item * 2)]
                                for item in range(u32(parameters)))
        prototypes.append('(' + arguments + ')' + types[u32(offset + 4)])
    fields = []
    for index in range(counts[6]):
        offset = counts[7] + index * 8
        fields.append(('field', member_owner(types[u16(offset)]), strings[u32(offset + 4)],
                       types[u16(offset + 2)]))
    methods = []
    for index in range(counts[8]):
        offset = counts[9] + index * 8
        methods.append(('method', member_owner(types[u16(offset)]), strings[u32(offset + 4)],
                        prototypes[u16(offset + 2)]))
    inventory = Inventory(types={class_name(name) for name in types} - {''},
                          references=set(fields + methods))
    for index in range(counts[10]):
        offset = counts[11] + index * 32
        name = class_name(types[u32(offset)])
        superclass = u32(offset + 8)
        interfaces = u32(offset + 12)
        definition = ClassInfo(name, class_name(types[superclass]) if superclass != 0xffffffff else '',
                               tuple(class_name(types[u16(interfaces + 4 + item * 2)])
                                     for item in range(u32(interfaces))) if interfaces else (),
                               u32(offset + 4), origin=origin)
        position = u32(offset + 24)
        if position:
            sizes = []
            for _ in range(4):
                count, position = uleb(position)
                sizes.append(count)
            for section, count in enumerate(sizes):
                member_index = 0
                for _ in range(count):
                    delta, position = uleb(position)
                    flags, position = uleb(position)
                    member_index += delta
                    if section < 2:
                        _, declared_owner, member, descriptor = fields[member_index]
                        definition.fields[member, descriptor] = flags
                    else:
                        _, declared_owner, member, descriptor = methods[member_index]
                        definition.methods[member, descriptor] = flags
                        _, position = uleb(position)
                    if declared_owner != name:
                        raise ValueError('DEX member owner differs from class: ' + origin)
        inventory.classes[name] = definition
    return inventory


def read_path(path):
    path = Path(path)
    inventory = Inventory()
    if path.is_dir():
        for entry in sorted(path.rglob('*.class')):
            inventory.add(read_class(entry.read_bytes(), str(entry)))
        return inventory
    if path.suffix == '.dex':
        return read_dex(path.read_bytes(), str(path))
    if path.suffix == '.class':
        return read_class(path.read_bytes(), str(path))
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            if not entry.filename.endswith(('.class', '.dex')):
                continue
            if entry.file_size > 256 * 1024 * 1024:
                raise ValueError('Bytecode entry exceeds 256 MiB: ' + entry.filename)
            origin = str(path) + '!' + entry.filename
            data = archive.read(entry)
            inventory.add(read_dex(data, origin) if entry.filename.endswith('.dex')
                          else read_class(data, origin))
    if not inventory.classes:
        raise ValueError('No Java/DEX class definitions in ' + str(path))
    return inventory
