"""Every migration's revision id must fit ``alembic_version.version_num``.

Alembic creates that column itself, as ``VARCHAR(32)``, and no migration in
this repo declares it — so the limit is invisible until a deploy hits it. On
31 Aug a revision id of 36 characters passed lint, mypy, the unit suite and the
build, then failed on the very last statement of ``alembic upgrade head``::

    UPDATE alembic_version SET version_num='0003_eval_results_gates_and_failures'
    asyncpg.exceptions.StringDataRightTruncationError:
        value too long for type character varying(32)

The migration's DDL had already applied by then. The stamp was what failed, so
the database was left carrying the new columns while ``alembic_version`` still
read the previous revision, and the API crash-looped on startup for half an
hour.

Nothing about that needed a database to catch. This reads the filenames.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Alembic's own default width for ``alembic_version.version_num``. Not ours to
#: change — the table is created by Alembic before any migration runs.
MAX_REVISION_ID_LENGTH = 32

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations" / "versions"

_REVISION = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"'](?P<id>[^\"']+)[\"']", re.MULTILINE)


def test_every_revision_id_fits_the_alembic_version_column() -> None:
    files = sorted(VERSIONS_DIR.glob("[0-9]*.py"))
    assert files, f"no migrations found under {VERSIONS_DIR}"

    too_long = {}
    for path in files:
        match = _REVISION.search(path.read_text(encoding="utf-8"))
        assert match is not None, f'{path.name} declares no `revision = "..."`'
        revision_id = match.group("id")
        if len(revision_id) > MAX_REVISION_ID_LENGTH:
            too_long[path.name] = (revision_id, len(revision_id))

    assert not too_long, (
        "revision id longer than alembic_version.version_num VARCHAR("
        f"{MAX_REVISION_ID_LENGTH}) — the migration's DDL would apply and the "
        "version stamp would then fail, leaving the database ahead of the "
        "revision it reports: "
        + ", ".join(f"{name} = {rid!r} ({n} chars)" for name, (rid, n) in sorted(too_long.items()))
    )
