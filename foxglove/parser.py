from pathlib import Path
import re

def parse_loged_fields(header_path: Path) -> dict[int, str]:
    text = header_path.read_text()

    # Remove Comments
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # Find `enum LOGED_FIELDS { ... };` — also tolerates `enum class`
    match = re.search(
        r"enum\s+(?:class\s+)?LOGED_FIELDS\s*(?::\s*\w+\s*)?\{([^}]*)\}",
        text,
    )
    if not match:
        raise ValueError(f"Could not find enum LOGED_FIELDS in {header_path}")

    body = match.group(1)
    fields: dict[int, str] = {}
    next_index = 0

    for raw_entry in body.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue

        # Handle explicit values: `FOO = 5`
        if "=" in entry:
            name, value_str = (s.strip() for s in entry.split("=", 1))
            try:
                next_index = int(value_str, 0)  # base 0 → handles 0x, decimal, etc.
            except ValueError:
                raise ValueError(
                    f"Non-literal enum value in LOGED_FIELDS: {entry!r}. "
                    f"This parser only handles integer literals."
                )
        else:
            name = entry

        # Skip the sentinel — it's not a real field
        if name == "FIELD_COUNT":
            next_index += 1
            continue

        fields[next_index] = name.lower()
        next_index += 1

    if not fields:
        raise ValueError(f"LOGED_FIELDS enum in {header_path} is empty")

    return fields

