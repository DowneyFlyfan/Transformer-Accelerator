"""Strict parser for the supported mapped structural Verilog subset.

Pure definitions extracted from the existing placement comparators. Unsupported
statements, duplicate instances and malformed pin associations fail closed.
This parser does not implement general behavioral Verilog elaboration.
"""
if not __debug__:
    raise RuntimeError('Mapped-module qualification requires assertions')
import re


IDENTIFIER = r"(?:\\\S+|[A-Za-z_$][\w$]*)"


DECLARATION = re.compile(r"(?m)^\s*(input|output|wire)\s+(?:\[(\d+):(\d+)\]\s*)?([^;]+);")


ASSOCIATION = re.compile(rf"\.({IDENTIFIER})\s*\(([^()]*)\)")


def declarations(source):
    ports, nets = {}, {}
    for direction, first, last, names in DECLARATION.findall(source):
        span = None if first == "" else (int(first), int(last))
        for name in names.split(","):
            name = name.strip()
            assert re.fullmatch(IDENTIFIER, name), name
            key = name.removeprefix("\\")
            assert nets.get(key, span) == span, key
            nets[key] = span
            if direction != "wire":
                assert key not in ports, key
                ports[key] = direction, span
    return ports, nets


INSTANCE = re.compile(rf"(?m)^[ \t]*(\w+)\s+({IDENTIFIER})\s*\(([^;]*)\);")


ASSIGN = re.compile(r"(?m)^[ \t]*assign[ \t]+([^=;]+)=([^;]+);")


COMMENT = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")


TOKEN = re.compile(r"\\\S+|[A-Za-z0-9_$]+|[^\s]")


def parse_module(source, span):
    header, sep, body = source[slice(*span)].partition(";")
    assert sep
    body = COMMENT.sub("", body)
    ports, nets = declarations(body)
    instances = {}
    for match in INSTANCE.finditer(body):
        master, name, fields = match.groups()
        assert name not in instances, name
        instances[name] = (master, fields)
    remainder = INSTANCE.sub("", ASSIGN.sub("", DECLARATION.sub("", body))).strip()
    assert remainder == "endmodule", remainder[:200]
    return tuple(TOKEN.findall(header)), ports, nets, instances, ASSIGN.findall(body)


def pin_fields(fields):
    matches = ASSOCIATION.findall(fields)
    assert len(dict(matches)) == len(matches) and not ASSOCIATION.sub("", fields).strip(" ,\t\n")
    return dict(matches)


HEADER = re.compile(rb"\s*module\s+[\w$]+\s*\(")


DIRECTION = re.compile(rb"\b(?:input|output)\s+wire\b")


PORT = re.compile(rb"(input|output)\s+wire\s+(\[\d+:\d+\]\s+)?([A-Za-z_$][\w$]*)")


NET_INITIALIZER = re.compile(
    rb"(?m)^([ \t]*wire[ \t]+(?:\[\d+:\d+\][ \t]+)?)([A-Za-z_$][\w$]*)"
    rb"[ \t]*=[ \t]*([^;]+);"
)


def normalize_module(source):
    """Make wire initializers explicit assignments and ANSI ports declarations."""
    header, delimiter, body = source.partition(b");")
    assert delimiter
    if DIRECTION.search(header):
        opening = HEADER.match(header)
        assert opening is not None
        ports, declarations = [], []
        for item in header[opening.end() :].split(b","):
            match = PORT.fullmatch(item.strip())
            assert match is not None, item
            direction, size, name = match.groups()
            ports.append(name)
            declarations.append(b"  " + direction + b" " + (size or b"") + name + b";")
        assert len(ports) == len(set(ports))
        header = header[: opening.end()] + b", ".join(ports)
        body = b"\n" + b"\n".join(declarations) + b"\n" + body
    body = NET_INITIALIZER.sub(
        lambda m: m[1] + m[2] + b";\n  assign " + m[2] + b" = " + m[3] + b";",
        body,
    )
    return header + delimiter + body


SIZED_LITERAL = re.compile(r"\b(\d+)'([dDhHoO])([0-9a-fA-F_]+)\b")


def normalize_literals(text):
    def binary(match):
        width, radix, digits = match.groups()
        width = int(width)
        value = int(digits.replace("_", ""), {"d": 10, "h": 16, "o": 8}[radix.lower()])
        return f"{width}'b{value % (1 << width):0{width}b}"

    return SIZED_LITERAL.sub(binary, text)


def read_module(source):
    source = normalize_literals(source.decode("ascii"))
    return parse_module(source, (0, len(source)))
