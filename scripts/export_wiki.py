"""Validate and export repository-backed wiki pages; no network or Git writes."""

import argparse
import re
from pathlib import Path
from urllib.parse import quote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/wiki'
REPOSITORY = 'https://github.com/DDINGJOO/JJAM-TONG'
PAGES = (
    'Home', 'Product-and-Scope', 'Requirements-and-Scenarios',
    'Architecture-and-Decisions', 'Research-and-Experiments',
    'Roadmap-and-Workflow', '_Sidebar', '_Footer',
)
LINK = re.compile(r'(\[[^\]\n]+\]\()([^\s)]+)(\))')


def export(output):
    rendered = {}
    for name in PAGES:
        source = SOURCE / (name + '.md')
        content = source.read_text(encoding='utf-8')

        def rewrite(match):
            target = match.group(2)
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                return match.group(0)
            resolved = (source.parent / url.path).resolve()
            relative = resolved.relative_to(ROOT)
            if not resolved.is_file():
                raise ValueError('Missing link target: ' + str(relative))
            if resolved.parent == SOURCE and resolved.stem in PAGES:
                link = REPOSITORY + '/wiki/' + quote(resolved.stem)
            else:
                link = REPOSITORY + '/blob/main/' + quote(relative.as_posix())
            if url.fragment:
                link += '#' + url.fragment
            return match.group(1) + link + match.group(3)

        rendered[name + '.md'] = LINK.sub(rewrite, content)

    for name in rendered:
        destination = output / name
        if destination.is_symlink() or destination.resolve().is_relative_to(SOURCE):
            raise ValueError('Output must preserve the source files: ' + str(destination))
    output.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (output / name).write_text(content, encoding='utf-8')
    print('Validated and exported %d wiki files to %s' % (len(rendered), output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/wiki-export')
    export(parser.parse_args().output.resolve())
