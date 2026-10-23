"""Trusted local USD accounting. No network, credentials, or worker interface."""
from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from src import orchestration_evidence as e

NANO = 1_000_000_000
SCHEMA = 'api-budget-v1'


class Budget:
    def __init__(self, path, *, timezone='America/Los_Angeles', daily=10*NANO,
                 lifetime=100*NANO, clock=time.time):
        e.require(type(daily) is int and 0 < daily <= 10*NANO and
                  type(lifetime) is int and 0 < lifetime <= 100*NANO, 'Reviewed ceiling exceeded')
        self.path = Path(path).absolute()
        self.zone, self.clock = ZoneInfo(timezone), clock
        self.policy = dict(schema=SCHEMA, timezone=timezone, daily=daily, lifetime=lifetime)

    def initialize(self):
        # Explicit first installation only. Never replace a missing deployed ledger.
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        e.regular(self.path)
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''CREATE TABLE metadata(policy TEXT NOT NULL);
                CREATE TABLE requests(id TEXT PRIMARY KEY, binding TEXT NOT NULL, day TEXT NOT NULL,
                  reserved INTEGER NOT NULL, actual INTEGER, receipt TEXT);
                CREATE TABLE events(seq INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL,
                  request TEXT NOT NULL, evidence TEXT NOT NULL);''')
            db.execute('INSERT INTO metadata VALUES (?)', (e.canonical(self.policy),))
        fd = os.open(self.path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    @contextmanager
    def tx(self, write=False):
        e.regular(self.path)
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA trusted_schema=OFF')
            if not write: db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            e.require([r[0] for r in db.execute('SELECT policy FROM metadata')] ==
                      [e.canonical(self.policy)], 'Budget policy mismatch; explicit migration required')
            e.require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Budget integrity failure')
            last = db.execute('SELECT MAX(at) FROM events').fetchone()[0]
            e.require(last is None or self.clock() >= last, 'Budget clock regression')
            yield db
            if write: db.commit()
        finally: db.close()

    def day(self):
        return datetime.fromtimestamp(self.clock(), self.zone).date().isoformat()

    def event(self, db, kind, ident, evidence):
        db.execute('INSERT INTO events(at,kind,request,evidence) VALUES (?,?,?,?)',
                   (self.clock(), kind, ident, e.canonical(evidence)))

    def totals(self, db):
        # Unresolved holds encumber EVERY later day, so midnight cannot free them.
        rows = db.execute('SELECT * FROM requests').fetchall()
        held = sum(r['reserved'] for r in rows if r['actual'] is None)
        return dict(day=self.day(), timezone=self.policy['timezone'], unresolved_nano_usd=held,
            daily_encumbered_nano_usd=held+sum(r['actual'] for r in rows
                                            if r['actual'] is not None and r['day'] == self.day()),
            lifetime_encumbered_nano_usd=sum(r['reserved'] if r['actual'] is None else r['actual'] for r in rows),
            daily_limit_nano_usd=self.policy['daily'], lifetime_limit_nano_usd=self.policy['lifetime'],
            unresolved_requests=sum(r['actual'] is None for r in rows))

    def status(self):
        with self.tx() as db: return self.totals(db)

    def audit(self):
        with self.tx() as db:
            return [dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')]

    def reserve(self, ident, binding, maximum, *, provenance=None):
        e.require(e.sha(ident, 32) and e.sha(binding) and type(maximum) is int and maximum > 0,
                  'Invalid reservation')
        e.require(provenance is None or isinstance(provenance, dict) and
                  len(e.canonical(provenance)) <= 4096, 'Reservation provenance ceiling')
        with self.tx(True) as db:
            old = db.execute('SELECT * FROM requests WHERE id=?', (ident,)).fetchone()
            if old:
                e.require(old['binding'] == binding and old['reserved'] == maximum and old['receipt'] is not None,
                          'Duplicate conflict or unresolved request; do not retry')
                return e.decode(old['receipt'])
            t = self.totals(db)
            e.require(t['unresolved_requests'] == 0, 'One request maximum; reconcile unresolved hold')
            e.require(t['daily_encumbered_nano_usd']+maximum <= self.policy['daily'] and
                      t['lifetime_encumbered_nano_usd']+maximum <= self.policy['lifetime'], 'Budget exhausted')
            db.execute('INSERT INTO requests VALUES (?,?,?,?,NULL,NULL)', (ident, binding, self.day(), maximum))
            self.event(db, 'reserved', ident, dict(binding=binding, maximum_nano_usd=maximum, provenance=provenance))
        return None

    def settle(self, ident, actual, receipt, *, evidence=None):
        with self.tx(True) as db:
            r = db.execute('SELECT * FROM requests WHERE id=?', (ident,)).fetchone()
            e.require(r is not None and r['actual'] is None and type(actual) is int and
                      0 <= actual <= r['reserved'], 'Invalid reconciliation; hold retained')
            e.require(isinstance(receipt, dict) and len(e.canonical(receipt)) < 4096, 'Receipt ceiling')
            db.execute('UPDATE requests SET actual=?,receipt=? WHERE id=?', (actual, e.canonical(receipt), ident))
            self.event(db, 'operator-reconciled' if evidence else 'settled', ident,
                       dict(actual_nano_usd=actual, evidence=evidence, receipt=receipt))

    def reconcile(self, ident, actual, evidence):
        # Trusted operator only; not exposed to models or worker transports.
        e.require(e.sha(evidence), 'External billing/termination evidence digest required')
        receipt = dict(status='operator-reconciled', estimated_cost_nano_usd=actual, retry=False)
        self.settle(ident, actual, receipt, evidence=evidence)
        return receipt
