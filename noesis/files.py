"""Private atomic file replacement shared by generated artifacts and installation."""

import os
from pathlib import Path
import tempfile


def atomic_write(path, content):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temporary=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'.')
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(content.encode('utf-8') if isinstance(content,str) else content)
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)
