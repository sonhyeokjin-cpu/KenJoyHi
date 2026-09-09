"""Typed, indexed chunks. SQLite remains the session container.

All new arrays are little-endian float64. Missing values keep their timestamps.
Legacy level-0 blobs are read as float64 only; original integer blobs must be
re-imported because the old format did not record a dtype.
"""
from contextlib import contextmanager
import sqlite3
import numpy as np

CHUNK_POINTS = 250_000
MAX_RAW_POINTS = 5_000_000


def ensure_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS parameters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS timeseries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, parameter_id INTEGER,
            level INTEGER, time_data BLOB, value_data BLOB
        );
        CREATE TABLE IF NOT EXISTS channel_meta (
            parameter_id INTEGER PRIMARY KEY, dtype TEXT NOT NULL,
            count INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS channel_chunks (
            parameter_id INTEGER NOT NULL, ordinal INTEGER NOT NULL,
            start REAL NOT NULL, end REAL NOT NULL, count INTEGER NOT NULL,
            time_data BLOB NOT NULL, value_data BLOB NOT NULL,
            PRIMARY KEY(parameter_id, ordinal)
        );
        CREATE INDEX IF NOT EXISTS chunks_time
            ON channel_chunks(parameter_id, start, end);
    ''')


def validate_arrays(time, values):
    t = np.asarray(time)
    y = np.asarray(values)
    if t.ndim != 1 or y.ndim != 1 or t.size != y.size:
        raise ValueError('Time and values must be one-dimensional arrays of equal length')
    if t.dtype.kind not in 'biuf' or y.dtype.kind not in 'biuf':
        raise ValueError('Only real numeric arrays are supported')
    t = np.ascontiguousarray(t, dtype='<f8')
    y = np.ascontiguousarray(y, dtype='<f8')
    if not np.all(np.isfinite(t)) or (t.size > 1 and np.any(np.diff(t) <= 0)):
        raise ValueError('Time must be finite and strictly increasing (no duplicates)')
    if np.any(np.isinf(y)):
        raise ValueError('Infinite values are not supported; use NaN for missing samples')
    return t, y


class ChannelWriter:
    def __init__(self, conn, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('A channel name is required')
        self.conn = conn
        conn.execute('INSERT OR IGNORE INTO parameters(name) VALUES (?)', (name,))
        self.pid = conn.execute('SELECT id FROM parameters WHERE name=?', (name,)).fetchone()[0]
        for table in ('channel_chunks', 'channel_meta', 'timeseries'):
            conn.execute(f'DELETE FROM {table} WHERE parameter_id=?', (self.pid,))
        self.count = 0
        self.ordinal = 0
        self.start = self.end = None

    def append(self, time, values):
        t, y = validate_arrays(time, values)
        if not t.size:
            return
        if self.end is not None and t[0] <= self.end:
            raise ValueError('Channel chunks must have increasing, non-overlapping time')
        if self.start is None:
            self.start = float(t[0])
        for offset in range(0, t.size, CHUNK_POINTS):
            ct, cy = t[offset:offset + CHUNK_POINTS], y[offset:offset + CHUNK_POINTS]
            self.conn.execute('INSERT INTO channel_chunks VALUES (?,?,?,?,?,?,?)',
                              (self.pid, self.ordinal, float(ct[0]), float(ct[-1]),
                               len(ct), ct.tobytes(), cy.tobytes()))
            self.ordinal += 1
        self.end = float(t[-1])
        self.count += t.size

    def finish(self):
        if not self.count:
            raise ValueError('A channel must contain at least one sample')
        self.conn.execute('INSERT INTO channel_meta VALUES (?,?,?,?,?)',
                          (self.pid, '<f8', int(self.count), self.start, self.end))


@contextmanager
def channel_writer(path, name):
    conn = sqlite3.connect(path)
    try:
        ensure_schema(conn)
        conn.execute('BEGIN IMMEDIATE')
        writer = ChannelWriter(conn, name)
        yield writer
        writer.finish()
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def metadata(path, name):
    with sqlite3.connect(path) as conn:
        ensure_schema(conn)
        row = conn.execute('''SELECT m.count,m.start,m.end FROM channel_meta m
            JOIN parameters p ON p.id=m.parameter_id WHERE p.name=?''', (name,)).fetchone()
    if row:
        return dict(count=row[0], start=row[1], end=row[2])
    count = 0
    start = end = None
    for t, _ in iter_chunks(path, name):
        count += len(t)
        if len(t):
            start = float(t[0]) if start is None else start
            end = float(t[-1])
    return dict(count=count, start=start, end=end)


def iter_chunks(path, name, start=-np.inf, end=np.inf):
    if np.isnan(start) or np.isnan(end) or start > end:
        raise ValueError('Invalid time range')
    conn = sqlite3.connect(path)
    try:
        ensure_schema(conn)
        row = conn.execute('SELECT id FROM parameters WHERE name=?', (name,)).fetchone()
        if not row:
            return
        pid = row[0]
        modern = conn.execute('SELECT 1 FROM channel_meta WHERE parameter_id=?', (pid,)).fetchone()
        if modern:
            rows = conn.execute('''SELECT time_data,value_data FROM channel_chunks
                WHERE parameter_id=? AND end>=? AND start<=? ORDER BY ordinal''', (pid, start, end))
        else:
            rows = conn.execute('''SELECT time_data,value_data FROM timeseries
                WHERE parameter_id=? AND level=0 ORDER BY id DESC LIMIT 1''', (pid,))
        for tb, yb in rows:
            if len(tb) != len(yb) or len(tb) % 8:
                raise ValueError('Legacy dtype/length mismatch. Re-import the original source file.')
            t, y = np.frombuffer(tb, dtype='<f8'), np.frombuffer(yb, dtype='<f8')
            if not modern:
                validate_arrays(t, y)
            lo, hi = np.searchsorted(t, [start, end], side='left')
            hi = np.searchsorted(t, end, side='right')
            if hi > lo:
                yield t[lo:hi], y[lo:hi]
    finally:
        conn.close()


def read_arrays(path, name, start=-np.inf, end=np.inf, max_points=MAX_RAW_POINTS):
    chunks, count = [], 0
    for t, y in iter_chunks(path, name, start, end):
        count += len(t)
        if max_points is not None and count > max_points:
            raise ValueError(f'Raw analysis exceeds {max_points:,} samples; select a smaller time range')
        chunks.append((t, y))
    if not chunks:
        return np.array([], dtype=float), np.array([], dtype=float)
    return np.concatenate([x[0] for x in chunks]), np.concatenate([x[1] for x in chunks])


def statistics(path, name, start=-np.inf, end=np.inf):
    count = valid = 0
    minimum, maximum = np.inf, -np.inf
    min_time = max_time = None
    for t, y in iter_chunks(path, name, start, end):
        count += len(t)
        finite = np.isfinite(y)
        valid += int(finite.sum())
        if not finite.any():
            continue
        ft, fy = t[finite], y[finite]
        imin, imax = int(np.argmin(fy)), int(np.argmax(fy))
        if fy[imin] < minimum:
            minimum, min_time = float(fy[imin]), float(ft[imin])
        if fy[imax] > maximum:
            maximum, max_time = float(fy[imax]), float(ft[imax])
    return dict(count=count, valid_count=valid, missing_count=count-valid,
                min=minimum if valid else None, max=maximum if valid else None,
                min_time=min_time, max_time=max_time)


def envelope(path, name, start, end, resolution):
    """Bounded first/min/max/last envelope, with a NaN marker for gaps.

    Bins are based on time, not index. Aggregation never feeds numerical analysis.
    At most five samples per bucket, independent of original channel length.
    """
    resolution = int(resolution)
    if not 1 <= resolution <= 10000:
        raise ValueError('Resolution must be between 1 and 10000')
    meta = metadata(path, name)
    if not meta['count']:
        return [], [], meta
    start, end = max(start, meta['start']), min(end, meta['end'])
    if start > end:
        return [], [], meta
    bins = {}
    span = end - start
    for t, y in iter_chunks(path, name, start, end):
        ids = np.zeros(len(t), dtype=int) if span == 0 else np.minimum(
            ((t-start)/span*resolution).astype(int), resolution-1)
        edges = np.r_[0, np.flatnonzero(np.diff(ids))+1, len(ids)]
        for lo, hi in zip(edges[:-1], edges[1:]):
            bt, by = t[lo:hi], y[lo:hi]
            key = int(ids[lo])
            state = bins.setdefault(key, {'first': (float(bt[0]), float(by[0])),
                                          'min': None, 'max': None, 'gap': None,
                                          'last': None})
            state['last'] = (float(bt[-1]), float(by[-1]))
            finite = np.isfinite(by)
            if not finite.all() and state['gap'] is None:
                state['gap'] = (float(bt[np.flatnonzero(~finite)[0]]), float('nan'))
            if finite.any():
                ft, fy = bt[finite], by[finite]
                for label, idx, sign in [('min', int(np.argmin(fy)), 1), ('max', int(np.argmax(fy)), -1)]:
                    point = (float(ft[idx]), float(fy[idx]))
                    if state[label] is None or sign*point[1] < sign*state[label][1]:
                        state[label] = point
    points = {}
    for state in bins.values():
        for point in state.values():
            if point is not None:
                points[point[0]] = point[1]
    times = sorted(points)
    # JSON ``null`` is used for missing samples; the browser converts it to
    # NaN before constructing typed arrays (never to the misleading value 0).
    values = [points[t] if np.isfinite(points[t]) else None for t in times]
    return times, values, meta
